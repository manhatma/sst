#include "buzzer.h"
#include "hardware/pwm.h"
#include "hardware/gpio.h"
#include "hardware/clocks.h"
#include "pico/time.h"

static uint slice_num;
static uint channel;
static alarm_id_t silence_alarm = -1;

static int64_t silence_callback(alarm_id_t id, void *user_data) {
    (void)id; (void)user_data;
    pwm_set_chan_level(slice_num, channel, 0);
    silence_alarm = -1;
    return 0;
}

void buzzer_init(void) {
    gpio_set_function(BUZZER_PIN, GPIO_FUNC_PWM);
    slice_num = pwm_gpio_to_slice_num(BUZZER_PIN);
    channel = pwm_gpio_to_channel(BUZZER_PIN);
    pwm_set_enabled(slice_num, true);
    pwm_set_chan_level(slice_num, channel, 0);
}

// Non-blocking beep: starts tone, schedules silence via alarm.
// Cancels any previously scheduled silence alarm before starting.
void buzzer_beep(uint32_t freq_hz, uint32_t duration_ms) {
    if (silence_alarm >= 0) {
        cancel_alarm(silence_alarm);
        silence_alarm = -1;
    }

    // Compute integer clock divider and wrap such that:
    //   f = clk_sys / (div * wrap),  wrap <= 65535
    uint32_t clk = clock_get_hz(clk_sys);
    uint32_t div = 1;
    uint32_t wrap;
    do {
        wrap = clk / (div * freq_hz);
        if (wrap <= 65535) break;
        div++;
    } while (div <= 255);

    pwm_set_clkdiv_int_frac(slice_num, (uint8_t)div, 0);
    pwm_set_wrap(slice_num, (uint16_t)(wrap - 1));
    pwm_set_chan_level(slice_num, channel, (uint16_t)(wrap / 2)); // 50% duty

    silence_alarm = add_alarm_in_ms(duration_ms, silence_callback, NULL, false);
}

// Immediately cancel any pending silence alarm and stop PWM output.
void buzzer_silence(void) {
    if (silence_alarm >= 0) {
        cancel_alarm(silence_alarm);
        silence_alarm = -1;
    }
    pwm_set_chan_level(slice_num, channel, 0);
}

// --- Sound functions (frequencies tuned toward 4 kHz PS1240P02BT resonance) ---

// Short ascending double-tone — called from button callback (alarm context).
void buzzer_sound_confirm(void) {
    buzzer_beep(3000, 60);
    sleep_ms(15);
    buzzer_beep(4000, 80);
}

// Ascending 3-tone chirp — called from on_rec_start(), blocking safe.
void buzzer_sound_start(void) {
    buzzer_beep(2500, 100);
    sleep_ms(120);
    buzzer_beep(3500, 100);
    sleep_ms(120);
    buzzer_beep(4500, 150);
}

// Descending 2-tone — called from on_rec_stop(), blocking safe.
void buzzer_sound_stop(void) {
    buzzer_beep(4000, 100);
    sleep_ms(120);
    buzzer_beep(2500, 150);
}

// Single mid-tone — called from button callback in CAL states (non-blocking).
void buzzer_sound_cal(void) {
    buzzer_beep(3500, 80);
}

// Low double-tone — called from state handlers in CAL states, blocking safe.
void buzzer_sound_error(void) {
    buzzer_beep(1500, 150);
    sleep_ms(180);
    buzzer_beep(1500, 150);
}

// Rising tone — called from on_waking() / startup, blocking.
void buzzer_sound_wake(void) {
    buzzer_beep(2000, 100);
    sleep_ms(120);
    buzzer_beep(3500, 150);
    sleep_ms(170);
    buzzer_silence();
}

// Falling tone — called from on_sleep() state handler, blocking.
void buzzer_sound_sleep(void) {
    buzzer_beep(3500, 100);
    sleep_ms(120);
    buzzer_beep(2000, 150);
    sleep_ms(170);
    buzzer_silence();
}
