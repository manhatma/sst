#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "ads1115.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/pwm.h"
#include "hardware/structs/timer.h"
#include "pico/stdlib.h"
#include "pico/stdio_usb.h"
#include "ssd1306.h"

#include "../pio_i2c/pio_i2c.h"

#define ADS1115_ADDRESS 0x48

#define FORK_I2C i2c0
#define FORK_PIN_SDA 8
#define FORK_PIN_SCL 9
#define FORK_PIN_DRDY 21

#define SHOCK_I2C i2c1
#define SHOCK_PIN_SDA 14
#define SHOCK_PIN_SCL 15
#define SHOCK_PIN_DRDY 27

#define DISPLAY_PIO pio0
#define DISPLAY_SM 0
#define DISPLAY_PIN_SDA 2
#define DISPLAY_PIN_SCL 3
#define DISPLAY_ADDRESS 0x3c

#define EDGE_COUNT_MS 10000
#define PULSE_SAMPLES 100

enum capture_mode {
    CAPTURE_IDLE,
    CAPTURE_PULSES,
    CAPTURE_XCHK,
};

struct pulse_capture {
    volatile uint32_t falling[PULSE_SAMPLES + 1];
    volatile uint32_t rising[PULSE_SAMPLES];
    volatile uint32_t falling_count;
    volatile uint32_t rising_count;
    volatile uint32_t xchk_count;
};

static volatile enum capture_mode capture_mode;
static struct pulse_capture fork_capture;
static struct pulse_capture shock_capture;

static void display_lines(ssd1306_t *disp, const char *line1,
                          const char *line2, const char *line3,
                          const char *line4) {
    // Mirror everything to USB serial. The display is a convenience here,
    // the serial line is the primary output.
    printf("%s | %s | %s | %s\n", line1, line2, line3, line4);

    ssd1306_clear(disp);
    ssd1306_draw_string(disp, 0, 0, 1, line1);
    ssd1306_draw_string(disp, 0, 16, 1, line2);
    ssd1306_draw_string(disp, 0, 32, 1, line3);
    ssd1306_draw_string(disp, 0, 48, 1, line4);
    ssd1306_show(disp);
}

static void setup_display(ssd1306_t *disp) {
    uint offset = pio_add_program(DISPLAY_PIO, &i2c_program);
    i2c_program_init(DISPLAY_PIO, DISPLAY_SM, offset,
                     DISPLAY_PIN_SDA, DISPLAY_PIN_SCL);
    ssd1306_proto_t p = {
        DISPLAY_ADDRESS,
        DISPLAY_PIO,
        DISPLAY_SM,
        pio_i2c_write_blocking,
    };
    ssd1306_init(disp, 128, 64, p);
    ssd1306_flip(disp, 0);
    ssd1306_clear(disp);
    ssd1306_show(disp);
}

static bool arm_ads1115(i2c_inst_t *port, uint sda, uint scl,
                        ads1115_adc_t *adc) {
    static const uint8_t hi_thresh[] = {0x03, 0x80, 0x00};
    static const uint8_t lo_thresh[] = {0x02, 0x00, 0x00};

    i2c_init(port, 400 * 1000);
    gpio_set_function(sda, GPIO_FUNC_I2C);
    gpio_set_function(scl, GPIO_FUNC_I2C);

    int hi_result = i2c_write_blocking(port, ADS1115_ADDRESS,
                                       hi_thresh, sizeof(hi_thresh), false);
    int lo_result = i2c_write_blocking(port, ADS1115_ADDRESS,
                                       lo_thresh, sizeof(lo_thresh), false);

    ads1115_init(port, ADS1115_ADDRESS, adc);
    ads1115_set_input_mux(ADS1115_MUX_SINGLE_0, adc);
    ads1115_set_pga(ADS1115_PGA_4_096, adc);
    ads1115_set_operating_mode(ADS1115_MODE_CONTINUOUS, adc);
    ads1115_set_data_rate(ADS1115_RATE_860_SPS, adc);
    adc->config = (adc->config & ~ADS1115_COMP_QUE_MASK) |
                  ADS1115_COMPARATOR_QUE_1;
    ads1115_write_config(adc);

    return hi_result == (int)sizeof(hi_thresh) &&
           lo_result == (int)sizeof(lo_thresh);
}

static uint pwm_counter_setup(uint pin) {
    gpio_disable_pulls(pin);
    gpio_set_function(pin, GPIO_FUNC_PWM);

    uint slice = pwm_gpio_to_slice_num(pin);
    pwm_set_enabled(slice, false);
    pwm_set_clkdiv_mode(slice, PWM_DIV_B_FALLING);
    pwm_set_clkdiv(slice, 1.0f);
    pwm_set_wrap(slice, 65535);
    pwm_set_counter(slice, 0);
    return slice;
}

static void gpio_capture_setup(uint pin) {
    gpio_init(pin);
    gpio_set_dir(pin, GPIO_IN);
    gpio_disable_pulls(pin);
}

static void capture_edge(struct pulse_capture *capture, uint32_t events,
                         uint32_t now) {
    if (capture_mode == CAPTURE_XCHK) {
        if (events & GPIO_IRQ_EDGE_FALL) {
            capture->xchk_count++;
        }
        return;
    }

    if (capture_mode != CAPTURE_PULSES) {
        return;
    }

    if ((events & GPIO_IRQ_EDGE_FALL) &&
        capture->falling_count < PULSE_SAMPLES + 1) {
        capture->falling[capture->falling_count++] = now;
    }
    if ((events & GPIO_IRQ_EDGE_RISE) &&
        capture->rising_count < PULSE_SAMPLES &&
        capture->falling_count > capture->rising_count) {
        capture->rising[capture->rising_count++] = now;
    }
}

static void gpio_callback(uint gpio, uint32_t events) {
    uint32_t now = timer_hw->timerawl;

    if (gpio == FORK_PIN_DRDY) {
        capture_edge(&fork_capture, events, now);
    } else if (gpio == SHOCK_PIN_DRDY) {
        capture_edge(&shock_capture, events, now);
    }
}

static bool pulse_capture_complete(const struct pulse_capture *capture) {
    return capture->falling_count >= PULSE_SAMPLES + 1 &&
           capture->rising_count >= PULSE_SAMPLES;
}

static void analyze_capture(const struct pulse_capture *capture,
                            uint32_t *pulse_width, uint32_t *period) {
    uint32_t width_sum = 0;
    uint32_t period_sum = 0;
    uint32_t width_count = 0;
    uint32_t period_count = 0;

    // The capture may be partial if the wait timed out, so only evaluate
    // pairs that were actually recorded.
    uint32_t pairs = capture->rising_count;
    if (capture->falling_count < pairs + 1) {
        pairs = capture->falling_count > 0 ? capture->falling_count - 1 : 0;
    }

    for (uint i = 0; i < pairs; ++i) {
        int32_t width = (int32_t)(capture->rising[i] - capture->falling[i]);
        int32_t cycle = (int32_t)(capture->falling[i + 1] -
                                  capture->falling[i]);
        if (width > 0) {
            width_sum += (uint32_t)width;
            width_count++;
        }
        if (cycle > 0) {
            period_sum += (uint32_t)cycle;
            period_count++;
        }
    }

    *pulse_width = width_count ? width_sum / width_count : 0;
    *period = period_count ? period_sum / period_count : 0;
}

int main(void) {
    // Must be zeroed: ssd1306_init reads external_vcc to pick the charge pump
    // setting, and a non-zero value there disables it — the panel stays dark
    // while I2C traffic looks perfectly healthy. main.c gets this for free
    // because its display struct is static.
    ssd1306_t disp = {0};
    ads1115_adc_t fork_adc;
    ads1115_adc_t shock_adc;
    char line1[32];
    char line2[32];
    char line3[32];
    char line4[32];

    stdio_init_all();
    // Give the USB CDC host time to enumerate, otherwise the first lines are
    // lost. Also serves as the SSD1306 power-on delay: main.c reaches its own
    // display init only after the buzzer chirp, this build gets there in ~1 ms.
    for (int i = 0; i < 500 && !stdio_usb_connected(); ++i) {
        sleep_ms(10);
    }
    sleep_ms(300);

    setup_display(&disp);
    // Sign of life first: a blank display must not be ambiguous between
    // "still running", "hung" and "no power".
    display_lines(&disp, "DRDY PROBE", "display ok", "", "");
    sleep_ms(1500);

    bool fork_armed = arm_ads1115(FORK_I2C, FORK_PIN_SDA, FORK_PIN_SCL,
                                  &fork_adc);
    bool shock_armed = arm_ads1115(SHOCK_I2C, SHOCK_PIN_SDA, SHOCK_PIN_SCL,
                                   &shock_adc);
    display_lines(&disp, "DRDY PROBE",
                  fork_armed ? "fork armed" : "I2C ERR F",
                  shock_armed ? "shock armed" : "I2C ERR S",
                  "phase 1: 10s");
    sleep_ms(fork_armed && shock_armed ? 50 : 3000);

    // Phase 1: hardware falling-edge count.
    uint fork_slice = pwm_counter_setup(FORK_PIN_DRDY);
    uint shock_slice = pwm_counter_setup(SHOCK_PIN_DRDY);
    pwm_set_enabled(fork_slice, true);
    pwm_set_enabled(shock_slice, true);
    sleep_ms(EDGE_COUNT_MS);
    uint16_t n_fork = pwm_get_counter(fork_slice);
    uint16_t n_shock = pwm_get_counter(shock_slice);
    pwm_set_enabled(fork_slice, false);
    pwm_set_enabled(shock_slice, false);

    if (n_fork == 0 || n_shock == 0) {
        snprintf(line1, sizeof(line1), "F=%u S=%u", n_fork, n_shock);
        const char *no_pulse = n_fork == 0 && n_shock == 0 ? "NO PULSE F/S" :
                               n_fork == 0 ? "NO PULSE F" : "NO PULSE S";
        display_lines(&disp, line1, no_pulse, "", "");
        while (true) {
            tight_loop_contents();
        }
    }

    // Phase 1 result goes out before anything else can hang.
    snprintf(line1, sizeof(line1), "F=%u S=%u", n_fork, n_shock);
    display_lines(&disp, line1, "phase 2: pulse", "", "");

    // Phase 2: capture pulse width and period in microseconds.
    gpio_capture_setup(FORK_PIN_DRDY);
    gpio_capture_setup(SHOCK_PIN_DRDY);
    capture_mode = CAPTURE_PULSES;
    gpio_set_irq_enabled_with_callback(FORK_PIN_DRDY,
        GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE, true, gpio_callback);
    gpio_set_irq_enabled(SHOCK_PIN_DRDY,
        GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE, true);
    // 100 pulses need ~120 ms; 2 s is a generous bound that still guarantees
    // the loop ends. Partial captures are evaluated as far as they go.
    uint32_t wait_start = timer_hw->timerawl;
    while ((!pulse_capture_complete(&fork_capture) ||
            !pulse_capture_complete(&shock_capture)) &&
           (int32_t)(timer_hw->timerawl - wait_start) < 2000000) {
        tight_loop_contents();
    }
    gpio_set_irq_enabled(FORK_PIN_DRDY,
        GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE, false);
    gpio_set_irq_enabled(SHOCK_PIN_DRDY,
        GPIO_IRQ_EDGE_FALL | GPIO_IRQ_EDGE_RISE, false);
    capture_mode = CAPTURE_IDLE;

    uint32_t pw_fork;
    uint32_t pw_shock;
    uint32_t per_fork;
    uint32_t per_shock;
    analyze_capture(&fork_capture, &pw_fork, &per_fork);
    analyze_capture(&shock_capture, &pw_shock, &per_shock);

    snprintf(line2, sizeof(line2), "PW %lu/%lu us",
             (unsigned long)pw_fork, (unsigned long)pw_shock);
    snprintf(line3, sizeof(line3), "T %lu/%lu us",
             (unsigned long)per_fork, (unsigned long)per_shock);
    display_lines(&disp, line1, line2, line3, "phase 3: 10s");

    // Phase 3: compare hardware and GPIO IRQ falling-edge counts.
    fork_slice = pwm_counter_setup(FORK_PIN_DRDY);
    shock_slice = pwm_counter_setup(SHOCK_PIN_DRDY);
    fork_capture.xchk_count = 0;
    shock_capture.xchk_count = 0;
    capture_mode = CAPTURE_XCHK;
    gpio_set_irq_enabled(FORK_PIN_DRDY, GPIO_IRQ_EDGE_FALL, true);
    gpio_set_irq_enabled(SHOCK_PIN_DRDY, GPIO_IRQ_EDGE_FALL, true);
    pwm_set_enabled(fork_slice, true);
    pwm_set_enabled(shock_slice, true);
    sleep_ms(EDGE_COUNT_MS);
    uint16_t pwm_fork = pwm_get_counter(fork_slice);
    uint16_t pwm_shock = pwm_get_counter(shock_slice);
    pwm_set_enabled(fork_slice, false);
    pwm_set_enabled(shock_slice, false);
    gpio_set_irq_enabled(FORK_PIN_DRDY, GPIO_IRQ_EDGE_FALL, false);
    gpio_set_irq_enabled(SHOCK_PIN_DRDY, GPIO_IRQ_EDGE_FALL, false);
    capture_mode = CAPTURE_IDLE;

    int32_t diff_fork = (int32_t)pwm_fork - (int32_t)fork_capture.xchk_count;
    int32_t diff_shock = (int32_t)pwm_shock - (int32_t)shock_capture.xchk_count;
    snprintf(line1, sizeof(line1), "F=%u S=%u", n_fork, n_shock);
    snprintf(line2, sizeof(line2), "PW %lu/%lu us",
             (unsigned long)pw_fork, (unsigned long)pw_shock);
    snprintf(line3, sizeof(line3), "T %lu/%lu us",
             (unsigned long)per_fork, (unsigned long)per_shock);
    if (diff_fork == 0 && diff_shock == 0) {
        snprintf(line4, sizeof(line4), "XCHK OK");
    } else {
        snprintf(line4, sizeof(line4), "XCHK %ld/%ld",
                 (long)diff_fork, (long)diff_shock);
    }
    // Repeat forever so the result survives a serial connection made late.
    while (true) {
        display_lines(&disp, line1, line2, line3, line4);
        sleep_ms(2000);
    }
}
