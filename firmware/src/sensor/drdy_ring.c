// timerawl is a free-running uint32_t microsecond counter and wraps after
// 71.6 minutes. All time comparisons in this file must use
// (int32_t)(a - b). Never mix in absolute_time_t or any 64-bit time source;
// every relevant interval is much smaller than 2^31 us, so modular uint32_t
// arithmetic is exact by construction.

#include "drdy_ring.h"

#include <stddef.h>

#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/structs/timer.h"
#include "hardware/sync.h"
#include "pico.h"
#include "pico/platform.h"

#include "../fw/hardware_config.h"

#define DRDY_RING_MASK (DRDY_RING_SIZE - 1u)

// AP0 Test 2, measured on the device.
#define FORK_NOMINAL_DRDY_PERIOD_US 1201u
#define SHOCK_NOMINAL_DRDY_PERIOD_US 1152u

// AP0 Test 2: Fork 832.4 SPS / 1201 us; gate is 0.8 times that period.
#define FORK_MIN_DRDY_PERIOD_US 961u
// AP0 Test 2: Shock 868.1 SPS / 1152 us; gate is 0.8 times that period.
#define SHOCK_MIN_DRDY_PERIOD_US 922u

#define DRDY_IRQ_ORDER_PRIORITY \
    PICO_SHARED_IRQ_HANDLER_HIGHEST_ORDER_PRIORITY

static_assert((DRDY_RING_SIZE & DRDY_RING_MASK) == 0,
              "DRDY ring size must be a power of two");

struct drdy_ring_state {
    struct sample samples[DRDY_RING_SIZE];
    volatile uint32_t head;
    volatile uint32_t drdy_count;
    volatile uint32_t late_count;
    volatile uint32_t i2c_err_count;
    volatile uint32_t glitch_count;
    // These resampling counters are consumer-owned and never changed by an ISR.
    volatile uint32_t resample_short_count;
    volatile uint32_t resample_before_count;
    volatile uint32_t resample_after_count;
    volatile uint32_t resample_torn_count;
#if DRDY_RING_JITTER_STATS
    struct drdy_ring_jitter_stats jitter;
#endif
    uint32_t last_accepted_t_us;
    uint32_t min_period_us;
    uint16_t last_value;
#if DRDY_RING_JITTER_STATS
    uint32_t nominal_period_us;
#endif
    i2c_inst_t *i2c;
    uint8_t i2c_address;
    uint8_t gpio;
    bool has_last_accepted;
    bool has_last_value;
    bool initialized;
};

static struct drdy_ring_state rings[DRDY_CHANNEL_COUNT] = {
    [DRDY_CHANNEL_FORK] = {
        .min_period_us = FORK_MIN_DRDY_PERIOD_US,
#if DRDY_RING_JITTER_STATS
        .nominal_period_us = FORK_NOMINAL_DRDY_PERIOD_US,
#endif
        .gpio = FORK_PIN_DRDY,
    },
    [DRDY_CHANNEL_SHOCK] = {
        .min_period_us = SHOCK_MIN_DRDY_PERIOD_US,
#if DRDY_RING_JITTER_STATS
        .nominal_period_us = SHOCK_NOMINAL_DRDY_PERIOD_US,
#endif
        .gpio = SHOCK_PIN_DRDY,
    },
};

static bool channel_is_valid(enum drdy_channel channel) {
    return (unsigned)channel < DRDY_CHANNEL_COUNT;
}

static void reset_ring(struct drdy_ring_state *ring) {
    ring->head = 0;
    ring->drdy_count = 0;
    ring->late_count = 0;
    ring->i2c_err_count = 0;
    ring->glitch_count = 0;
    ring->resample_short_count = 0;
    ring->resample_before_count = 0;
    ring->resample_after_count = 0;
    ring->resample_torn_count = 0;
#if DRDY_RING_JITTER_STATS
    ring->jitter = (struct drdy_ring_jitter_stats){0};
#endif
    ring->last_accepted_t_us = 0;
    ring->last_value = 0;
    ring->has_last_accepted = false;
    ring->has_last_value = false;
}

static int32_t catmull_rom_q16(int32_t p0, int32_t p1, int32_t p2, int32_t p3,
                               int32_t u_q16) {
    int32_t c1 = -p0 + p2;
    int32_t c2 = 2 * p0 - 5 * p1 + 4 * p2 - p3;
    int32_t c3 = -p0 + 3 * p1 - 3 * p2 + p3;
    int64_t acc = c3;

    // GCC guarantees arithmetic right shifts for negative int64_t values here.
    acc = ((acc * u_q16) >> 16) + c2;
    acc = ((acc * u_q16) >> 16) + c1;
    acc = (acc * u_q16) >> 16;
    // This rounds down by at most half an LSB, negligible at 16-bit ADC scale.
    return p1 + (int32_t)(acc >> 1);
}

static uint16_t resample_fallback(const struct drdy_ring_state *ring,
                                  uint32_t head_snapshot, uint32_t count) {
    if (ring->has_last_value) {
        return ring->last_value;
    }
    if (count > 0) {
        return ring->samples[(head_snapshot - 1u) & DRDY_RING_MASK].v;
    }
    // Unreachable after AP5 supplies a correct t_0; keeps the function total.
    return 0;
}

static void handle_drdy(enum drdy_channel channel, uint32_t t_us) {
    struct drdy_ring_state *ring = &rings[channel];
    const uint32_t event = GPIO_IRQ_EDGE_FALL;
    int32_t dt_us = 0;

    if (!(gpio_get_irq_event_mask(ring->gpio) & event)) {
        return;
    }
    gpio_acknowledge_irq(ring->gpio, event);

    if (ring->has_last_accepted) {
        dt_us = (int32_t)(t_us - ring->last_accepted_t_us);
        if (dt_us < (int32_t)ring->min_period_us) {
            ring->glitch_count++;
            return;
        }

#if DRDY_RING_JITTER_STATS
        struct drdy_ring_jitter_stats *jitter = &ring->jitter;
        if (jitter->dt_count == 0 || dt_us < jitter->dt_min_us) {
            jitter->dt_min_us = dt_us;
        }
        if (jitter->dt_count == 0 || dt_us > jitter->dt_max_us) {
            jitter->dt_max_us = dt_us;
        }
        jitter->dt_sum_us += (uint32_t)dt_us;
        jitter->dt_count++;

        int32_t signed_deviation =
            (int32_t)((uint32_t)dt_us - ring->nominal_period_us);
        uint32_t deviation = signed_deviation < 0
                                 ? (uint32_t)(-signed_deviation)
                                 : (uint32_t)signed_deviation;
        if (deviation > jitter->max_deviation_us) {
            jitter->max_deviation_us = deviation;
        }
        // These deviation buckets are disjoint, not cumulative.
        if (deviation <= 5) {
            jitter->deviation_le5_count++;
        } else if (deviation <= 15) {
            jitter->deviation_le15_count++;
        } else if (deviation <= 35) {
            jitter->deviation_le35_count++;
        } else if (deviation <= 75) {
            jitter->deviation_le75_count++;
        } else {
            jitter->deviation_gt75_count++;
        }
#endif
    }

    ring->last_accepted_t_us = t_us;
    ring->has_last_accepted = true;
    ring->drdy_count++;

    uint8_t data[2];
    // At 1 MHz the 2-byte read takes about 30 us; 500 us remains generous within
    // the faster channel's 1152 us ADC period while bounding ISR time on a hung bus.
    int result = i2c_read_timeout_us(ring->i2c, ring->i2c_address, data,
                                    sizeof(data), false, 500);

    // The current edge was acknowledged before the blocking read. A newly
    // pending edge therefore arrived before that read finished. Leave it
    // pending so the next handler invocation can process it.
    if (gpio_get_irq_event_mask(ring->gpio) & event) {
        ring->late_count++;
    }

    if (result != (int)sizeof(data)) {
        ring->i2c_err_count++;
        return;
    }

    uint16_t value = ((uint16_t)data[0] << 8) | data[1];
    uint32_t head = ring->head;
    ring->samples[head & DRDY_RING_MASK] = (struct sample){t_us, value};
    __dmb();
    ring->head++;
}

static void fork_drdy_irq_handler(void) {
    uint32_t t_us = timer_hw->timerawl;
    handle_drdy(DRDY_CHANNEL_FORK, t_us);
}

static void shock_drdy_irq_handler(void) {
    uint32_t t_us = timer_hw->timerawl;
    handle_drdy(DRDY_CHANNEL_SHOCK, t_us);
}

void drdy_ring_init(enum drdy_channel channel, i2c_inst_t *i2c,
                    uint8_t i2c_address) {
    hard_assert(channel_is_valid(channel));
    hard_assert(i2c != NULL);
    hard_assert(get_core_num() == 0);

    struct drdy_ring_state *ring = &rings[channel];
    hard_assert(!ring->initialized);

    ring->i2c = i2c;
    ring->i2c_address = i2c_address;
    reset_ring(ring);

    gpio_init(ring->gpio);
    gpio_set_dir(ring->gpio, GPIO_IN);
    gpio_disable_pulls(ring->gpio);
    gpio_set_irq_enabled(ring->gpio, GPIO_IRQ_EDGE_FALL, false);

    irq_handler_t handler = channel == DRDY_CHANNEL_FORK
                                ? fork_drdy_irq_handler
                                : shock_drdy_irq_handler;
    gpio_add_raw_irq_handler_with_order_priority(
        ring->gpio, handler, DRDY_IRQ_ORDER_PRIORITY);
    ring->initialized = true;
}

void drdy_ring_enable(enum drdy_channel channel) {
    hard_assert(channel_is_valid(channel));
    hard_assert(get_core_num() == 0);
    struct drdy_ring_state *ring = &rings[channel];
    hard_assert(ring->initialized);

    gpio_set_irq_enabled(ring->gpio, GPIO_IRQ_EDGE_FALL, false);
    reset_ring(ring);
    gpio_set_irq_enabled(ring->gpio, GPIO_IRQ_EDGE_FALL, true);
}

void drdy_ring_disable(enum drdy_channel channel) {
    hard_assert(channel_is_valid(channel));
    hard_assert(get_core_num() == 0);
    struct drdy_ring_state *ring = &rings[channel];
    hard_assert(ring->initialized);
    gpio_set_irq_enabled(ring->gpio, GPIO_IRQ_EDGE_FALL, false);
}

uint32_t drdy_ring_head_snapshot(enum drdy_channel channel) {
    hard_assert(channel_is_valid(channel));
    uint32_t head_snapshot = rings[channel].head;
    __dmb();
    return head_snapshot;
}

uint32_t drdy_ring_count_at(uint32_t head_snapshot) {
    return head_snapshot < DRDY_RING_SIZE ? head_snapshot : DRDY_RING_SIZE;
}

uint32_t drdy_ring_count(enum drdy_channel channel) {
    return drdy_ring_count_at(drdy_ring_head_snapshot(channel));
}

bool drdy_ring_read(enum drdy_channel channel, uint32_t head_snapshot,
                    uint32_t index, struct sample *sample_out) {
    hard_assert(channel_is_valid(channel));
    hard_assert(sample_out != NULL);

    uint32_t count = drdy_ring_count_at(head_snapshot);
    if (index >= count) {
        return false;
    }

    uint32_t first = head_snapshot - count;
    *sample_out = rings[channel].samples[(first + index) & DRDY_RING_MASK];
    return true;
}

uint16_t drdy_ring_resample(enum drdy_channel channel, uint32_t t_k_us) {
    hard_assert(channel_is_valid(channel));
    struct drdy_ring_state *ring = &rings[channel];
    uint32_t head_before = drdy_ring_head_snapshot(channel);
    uint32_t count = drdy_ring_count_at(head_before);

    if (count < 4) {
        ring->resample_short_count++;
        return resample_fallback(ring, head_before, count);
    }

    uint32_t first = head_before - count;
    int32_t j = (int32_t)count - 3;
    while (j >= 1) {
        const struct sample *candidate =
            &ring->samples[(first + (uint32_t)j) & DRDY_RING_MASK];
        if ((int32_t)(t_k_us - candidate->t_us) >= 0) {
            break;
        }
        j--;
    }
    if (j < 1) {
        ring->resample_before_count++;
        return resample_fallback(ring, head_before, count);
    }

    struct sample p1 =
        ring->samples[(first + (uint32_t)j) & DRDY_RING_MASK];
    struct sample p2 =
        ring->samples[(first + (uint32_t)j + 1u) & DRDY_RING_MASK];
    if ((int32_t)(t_k_us - p2.t_us) >= 0) {
        ring->resample_after_count++;
        return resample_fallback(ring, head_before, count);
    }

    struct sample p0 =
        ring->samples[(first + (uint32_t)j - 1u) & DRDY_RING_MASK];
    struct sample p3 =
        ring->samples[(first + (uint32_t)j + 2u) & DRDY_RING_MASK];

    // Check after copying: only then can it prove that none of the local inputs
    // was overwritten by the ISR while the four samples were being collected.
    uint32_t head_after = drdy_ring_head_snapshot(channel);
    uint32_t oldest_touched = first + (uint32_t)(j - 1);
    if ((uint32_t)(head_after - oldest_touched) > DRDY_RING_SIZE) {
        ring->resample_torn_count++;
        return resample_fallback(ring, head_before, count);
    }

    int32_t dt = (int32_t)(p2.t_us - p1.t_us);
    if (dt <= 0) {
        // The AP3 interval gate makes this impossible without torn input.
        ring->resample_torn_count++;
        return resample_fallback(ring, head_before, count);
    }

    int32_t num = (int32_t)(t_k_us - p1.t_us);
    int32_t u_q16 = (int32_t)(((int64_t)num << 16) / dt);
    if (u_q16 < 0) {
        u_q16 = 0;
    } else if (u_q16 > 65536) {
        u_q16 = 65536;
    }

    // Missing samples merely widen an interval and locally distort uniform CR;
    // glitch_count and i2c_err_count already diagnose the underlying causes.
    int32_t value = catmull_rom_q16((int32_t)(int16_t)p0.v,
                                    (int32_t)(int16_t)p1.v,
                                    (int32_t)(int16_t)p2.v,
                                    (int32_t)(int16_t)p3.v, u_q16);
    if (value < -32768) {
        value = -32768;
    } else if (value > 32767) {
        value = 32767;
    }

    uint16_t raw_value = (uint16_t)(int16_t)value;
    ring->last_value = raw_value;
    ring->has_last_value = true;
    // 0xFFFF is already linear_ads1115.c's unavailable-channel sentinel and
    // formally collides with raw -1, a practically impossible divider reading;
    // channel availability itself remains the caller's responsibility.
    return raw_value;
}

struct drdy_ring_counters drdy_ring_get_counters(enum drdy_channel channel) {
    hard_assert(channel_is_valid(channel));
    struct drdy_ring_state *ring = &rings[channel];
    return (struct drdy_ring_counters){
        .drdy_count = ring->drdy_count,
        .late_count = ring->late_count,
        .i2c_err_count = ring->i2c_err_count,
        .glitch_count = ring->glitch_count,
        .resample_short_count = ring->resample_short_count,
        .resample_before_count = ring->resample_before_count,
        .resample_after_count = ring->resample_after_count,
        .resample_torn_count = ring->resample_torn_count,
    };
}

struct drdy_ring_jitter_stats drdy_ring_get_jitter_stats(
        enum drdy_channel channel) {
    hard_assert(channel_is_valid(channel));
#if DRDY_RING_JITTER_STATS
    return rings[channel].jitter;
#else
    return (struct drdy_ring_jitter_stats){0};
#endif
}
