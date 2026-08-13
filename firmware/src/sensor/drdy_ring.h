#ifndef DRDY_RING_H
#define DRDY_RING_H

#include <stdbool.h>
#include <stdint.h>

#include "hardware/i2c.h"

#define DRDY_RING_SIZE 16u

#ifndef DRDY_RING_JITTER_STATS
#define DRDY_RING_JITTER_STATS 1
#endif

struct sample {
    uint32_t t_us;
    uint16_t v;
};

enum drdy_channel {
    DRDY_CHANNEL_FORK = 0,
    DRDY_CHANNEL_SHOCK,
    DRDY_CHANNEL_COUNT,
};

struct drdy_ring_counters {
    uint32_t drdy_count;
    uint32_t late_count;
    uint32_t i2c_err_count;
    uint32_t glitch_count;
    uint32_t resample_short_count;
    uint32_t resample_before_count;
    uint32_t resample_after_count;
    uint32_t resample_torn_count;
};

struct drdy_ring_jitter_stats {
    int32_t dt_min_us;
    int32_t dt_max_us;
    uint32_t dt_sum_us;
    uint32_t dt_count;
    uint32_t max_deviation_us;
    uint32_t deviation_le5_count;
    uint32_t deviation_le15_count;
    uint32_t deviation_le35_count;
    uint32_t deviation_le75_count;
    uint32_t deviation_gt75_count;
};

// Must be called on Core0. Initialisation leaves the falling-edge IRQ disabled.
void drdy_ring_init(enum drdy_channel channel, i2c_inst_t *i2c,
                    uint8_t i2c_address);

// Enabling resets the selected channel's ring and diagnostic counters.
void drdy_ring_enable(enum drdy_channel channel);
void drdy_ring_disable(enum drdy_channel channel);

// Snapshot head once, then pass that value to all reads in one consumer pass.
uint32_t drdy_ring_head_snapshot(enum drdy_channel channel);
uint32_t drdy_ring_count(enum drdy_channel channel);
uint32_t drdy_ring_count_at(uint32_t head_snapshot);

// Index zero is the oldest entry visible in head_snapshot.
bool drdy_ring_read(enum drdy_channel channel, uint32_t head_snapshot,
                    uint32_t index, struct sample *sample_out);

// Returns the raw ADS1115 word. The caller applies baseline and clamping.
// Only call from the consumer, never from an ISR.
uint16_t drdy_ring_resample(enum drdy_channel channel, uint32_t t_k_us);

struct drdy_ring_counters drdy_ring_get_counters(enum drdy_channel channel);
struct drdy_ring_jitter_stats drdy_ring_get_jitter_stats(
    enum drdy_channel channel);

#endif // DRDY_RING_H
