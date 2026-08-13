#include <stdint.h>
#include <stdio.h>
#include <time.h>

#include "cyw43_ll.h"
#include "device/usbd.h"
#include "pico/platform.h"
#include "pico/multicore.h"
#include "pico/cyw43_arch.h"
#include "pico/sleep.h"
#include "pico/time.h"
#include "pico/types.h"
#include "pico/unique_id.h"
#include "pico/runtime_init.h"
#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "hardware/rtc.h"
#include "hardware/rosc.h"
#include "hardware/structs/timer.h"
#include "hardware/timer.h"
#include "hardware/watchdog.h"
#include "bsp/board.h"
#include "ff.h"

// For scb_hw so we can enable deep sleep
#include "hardware/structs/scb.h"

#include "sst.h"
#include "../ntp//ntp.h"
#include "../net/tcpserver.h"
#include "../rtc//ds3231.h"
#include "../util/list.h"
#include "../util/config.h"
#include "../sensor/sensor.h"
#include "../sensor/drdy_ring.h"

#include "hardware_config.h"
#include "buzzer.h"
#include "boardid.h"

static volatile enum state state;

// Whether the wireless chip came up in the MSC boot path — VSYS can only be
// read while it is powered (see on_msc).
static bool msc_vsys_ok;

static uint32_t scb_orig;
static uint32_t clock0_orig;
static uint32_t clock1_orig;

static ssd1306_t disp;
static FIL recording;
static struct tcpserver server;

struct ds3231 rtc;

extern struct sensor fork_sensor;
extern struct sensor shock_sensor;

#ifdef DEBUG
#define debug_printf(...) printf(__VA_ARGS__)
#else
#define debug_printf(...)
#endif

// ----------------------------------------------------------------------------
// Helper functions

static void display_message(ssd1306_t *disp, char *message) {
    ssd1306_clear(disp);
    ssd1306_draw_string(disp, 0, 10, 2, message);
    ssd1306_show(disp);
}

static void soft_reset() {
      watchdog_enable(1, 1);
      while(1);
}

static bool on_battery() {
    cyw43_thread_enter();
    bool ret = !cyw43_arch_gpio_get(2);
    cyw43_thread_exit();
    return ret;
}

// The missing /3 for the sample sum and *3 for the VSYS/3 divider cancel deliberately.
static float read_voltage() {
    cyw43_thread_enter();
    sleep_ms(1); // NOTE ADC3 readings are way too high without this sleep.
    adc_gpio_init(29);   // GPIO29 measures VSYS/3
    adc_select_input(3); // GPIO29 is ADC #3
    uint32_t vsys = 0;
    for(int i = 0; i < 3; i++) {
        vsys += adc_read();
    }
    cyw43_thread_exit();
    const float conversion_factor = 3.3f / (1 << 12);
    float ret = vsys * conversion_factor;
    return ret;
}

static bool msc_present() {
    // Wait for a maximum of 1 second for USB MSC to initialize
    uint32_t t = time_us_32();
    while (!tud_ready()) {
        if (time_us_32() - t > 1000000) {
            return false;
        }
        tud_task();
    }
    return true;
}

static bool wifi_connect(bool do_ntp) {
    cyw43_arch_enable_sta_mode();
    bool ret = cyw43_arch_wifi_connect_timeout_ms(config.ssid, config.psk, CYW43_AUTH_WPA2_AES_PSK, 20000) == 0;
    if (ret && do_ntp) {
        sync_rtc_to_ntp();
    }
    return ret;
}

static void wifi_disconnect() {
    cyw43_arch_disable_sta_mode();
    sleep_ms(100);
}

static void calibrate_if_needed() {
    gpio_init(BUTTON_LEFT);
    gpio_pull_up(BUTTON_LEFT);

    FRESULT fr = f_stat("CALIBRATION", NULL);
    if (fr != FR_OK || !gpio_get(BUTTON_LEFT)) {
        state = CAL_IDLE_1;
    } else {
        state = IDLE;
    }
}

// ----------------------------------------------------------------------------
// Data acquisition

static const uint16_t SAMPLE_RATE = 860;

// 1000000 = 860 * 1162 + 680. Carrying the remainder exactly makes the
// 43-tick pattern span precisely 50000 us, without accumulated drift.
static uint32_t grid_t_k_us;
static uint32_t grid_remainder;
static alarm_id_t grid_alarm_id;

// We are using two buffers. Data acquisition happens on core #1 into the active
// buffer (referred to by the pointer active_buffer) and we dump to Micro SD card
// on core #2.
//
// When the active buffer is filled on core #1,
//  - the buffer's pointer is sent to core #2 via the Pico's multicore FIFO
//  - the other buffer's address is read from the FIFO, and set as active buffer.
//  
// Core #2 waits until an address is sent from core #1, and
//  - dumps the content at that address to the card
//  - sends the buffer address to core #1 via FIFO 
// 

struct record databuffer1[BUFFER_SIZE];
struct record databuffer2[BUFFER_SIZE];
struct record * volatile active_buffer = databuffer1;
volatile uint16_t count = 0;

static int64_t data_acquisition_cb(alarm_id_t id, void *user_data) {
    (void)id;
    (void)user_data;

    if (count == BUFFER_SIZE) {
        count = 0;
        multicore_fifo_push_blocking(DUMP);
        multicore_fifo_push_blocking((uintptr_t)active_buffer);
        active_buffer = (struct record *)((uintptr_t)multicore_fifo_pop_blocking());
    }

    active_buffer[count].fork_angle =
        sensor_sample_at(&fork_sensor, grid_t_k_us);
    active_buffer[count].shock_angle =
        sensor_sample_at(&shock_sensor, grid_t_k_us);

    count += 1;

    uint32_t step = 1162;
    grid_remainder += 680;
    if (grid_remainder >= 860) {
        step = 1163;
        grid_remainder -= 860;
    }
    grid_t_k_us += step;

    // A negative delay is relative to the scheduled alarm time, not the actual
    // callback time. That prevents late-tick jitter from accumulating as drift.
    return state == RECORD ? -(int64_t)step : 0;
}

static bool wait_for_sensors_ready(void) {
    absolute_time_t timeout = make_timeout_time_ms(100);
    while ((fork_sensor.available && !sensor_ready(&fork_sensor)) ||
           (shock_sensor.available && !sensor_ready(&shock_sensor))) {
        if (absolute_time_diff_us(get_absolute_time(), timeout) < 0) {
            return false;
        }
        sleep_ms(1);
    }
    return true;
}

static bool report_sensor_counters(struct sensor *sensor,
                                   enum drdy_channel channel,
                                   const char *name) {
    if (!sensor->sample_at) {
        return false;
    }

    struct drdy_ring_counters counters = drdy_ring_get_counters(channel);
    debug_printf(
        "%s drdy=%lu late=%lu i2c=%lu glitch=%lu short=%lu before=%lu "
        "after=%lu torn=%lu\n",
        name, (unsigned long)counters.drdy_count,
        (unsigned long)counters.late_count,
        (unsigned long)counters.i2c_err_count,
        (unsigned long)counters.glitch_count,
        (unsigned long)counters.resample_short_count,
        (unsigned long)counters.resample_before_count,
        (unsigned long)counters.resample_after_count,
        (unsigned long)counters.resample_torn_count);

    // Show only one counter per channel to bound the delay. Priority is sorted
    // by data loss first, then timing anomalies, then held-value fallbacks.
    const char *counter = NULL;
    uint32_t value = 0;
    if (counters.i2c_err_count != 0) {
        counter = "I";
        value = counters.i2c_err_count;
    } else if (counters.resample_torn_count != 0) {
        counter = "T";
        value = counters.resample_torn_count;
    } else if (counters.late_count != 0) {
        counter = "L";
        value = counters.late_count;
    } else if (counters.glitch_count != 0) {
        counter = "G";
        value = counters.glitch_count;
    } else if (counters.resample_before_count != 0) {
        counter = "B";
        value = counters.resample_before_count;
    } else if (counters.resample_after_count != 0) {
        counter = "A";
        value = counters.resample_after_count;
    } else if (counters.resample_short_count != 0) {
        counter = "S";
        value = counters.resample_short_count;
    } else {
        return false;
    }

    char msg[10];
    if (value > 9999) {
        snprintf(msg, sizeof(msg), "%s %s:9999+", name, counter);
    } else {
        snprintf(msg, sizeof(msg), "%s %s:%lu", name, counter,
                 (unsigned long)value);
    }
    display_message(&disp, msg);
    sleep_ms(2000);
    return true;
}

static bool start_sensors() {
    absolute_time_t timeout = make_timeout_time_ms(3000);
    while (!(fork_sensor.check_availability(&fork_sensor) || shock_sensor.check_availability(&shock_sensor))) {
        if (absolute_time_diff_us(get_absolute_time(), timeout) < 0) {
            return false;
        }
        sleep_ms(10);
    }

    FIL calibration_fil;
    FRESULT fr = f_open(&calibration_fil, "CALIBRATION", FA_OPEN_EXISTING | FA_READ);
    if (!(fr == FR_OK || fr == FR_EXIST)) {
        return false;
    }

    uint br;
    uint16_t baseline;
    bool inverted;
    f_read(&calibration_fil, &baseline, sizeof(uint16_t), &br);
    f_read(&calibration_fil, &inverted, sizeof(bool), &br);
    fork_sensor.start(&fork_sensor, baseline, inverted);

    f_read(&calibration_fil, &baseline, sizeof(uint16_t), &br);
    f_read(&calibration_fil, &inverted, sizeof(bool), &br);
    shock_sensor.start(&shock_sensor, baseline, inverted);

    f_close(&calibration_fil);

    return fork_sensor.available || shock_sensor.available;
}

// ----------------------------------------------------------------------------
// Data storage
static int setup_storage() {
    static FATFS fs;
    FRESULT fr = f_mount(&fs, "", 1);
    if (fr != FR_OK) {
        return PICO_ERROR_GENERIC;
    }

    char board_id_str[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
    pico_get_unique_board_id_string(board_id_str, 2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1);
    FIL f;
    uint btw;
    fr = f_open(&f, "BOARDID", FA_CREATE_NEW | FA_WRITE);
    if (fr == FR_OK) {
        f_write(&f, board_id_str, 2*PICO_UNIQUE_BOARD_ID_SIZE_BYTES, &btw);
    }
    f_close(&f);

    fr = f_mkdir("uploaded");
    if (!(fr == FR_OK || fr == FR_EXIST)) {
        return PICO_ERROR_GENERIC;
    }

    fr = f_mkdir("trash");
    if (!(fr == FR_OK || fr == FR_EXIST)) {
        return PICO_ERROR_GENERIC;
    }

    return 0;
}

static int open_datafile() {
    // start from 1, 0 is the special value for the headers in tcpserver
    uint16_t index = 1;
    FIL index_fil;
    FRESULT fr = f_open(&index_fil, "INDEX", FA_OPEN_EXISTING | FA_READ);
    if (fr == FR_OK || fr == FR_EXIST) {
        uint br;
        f_read(&index_fil, &index, 2, &br);
        if (br == 2) {
            index = index + 1;
        }
    }
    f_close(&index_fil);

    fr = f_open(&index_fil, "INDEX", FA_OPEN_ALWAYS | FA_WRITE);
    if (fr == FR_OK) {
        f_lseek(&index_fil, 0);
        uint bw;
        f_write(&index_fil, &index, 2, &bw);
        f_close(&index_fil);
    } else {
        return PICO_ERROR_GENERIC;
    }

    char filename[10];
    sprintf(filename, "%05u.SST", index);
    fr = f_open(&recording, filename, FA_CREATE_NEW | FA_WRITE);
    if (fr != FR_OK) {
        return fr;
    }

    struct header h = {"SST", 4, SAMPLE_RATE, rtc_timestamp()};
    f_write(&recording, &h, sizeof(struct header), NULL);

    return index;
}

static void data_storage_core1() {
    int err = setup_storage();
    multicore_fifo_push_blocking(err);

    int index;
    enum command cmd;
    uint16_t size;
    struct record *buffer;
    while (true) {
        cmd = (enum command)multicore_fifo_pop_blocking();
        switch(cmd) {
            case OPEN:
                multicore_fifo_drain();
                index = open_datafile();
                multicore_fifo_push_blocking(index);
                multicore_fifo_push_blocking((uintptr_t)databuffer2);
                break;
            case DUMP:
                buffer = (struct record *)((uintptr_t)multicore_fifo_pop_blocking());
                multicore_fifo_push_blocking((uintptr_t)buffer);
                f_write(&recording, buffer, sizeof(struct record)*BUFFER_SIZE, NULL);
                f_sync(&recording);
                break;
            case FINISH:
                size = (uint16_t)multicore_fifo_pop_blocking();
                buffer = (struct record *)((uintptr_t)multicore_fifo_pop_blocking());
                f_write(&recording, buffer, sizeof(struct record)*size, NULL);
                f_sync(&recording);
                f_close(&recording);
                break;
        }
    }
}

// ----------------------------------------------------------------------------
// Setup functions

static void setup_display(ssd1306_t *disp) {
#ifdef SPI_DISPLAY
    spi_init(DISPLAY_SPI, 1000000);
    gpio_set_function(DISPLAY_PIN_SCK, GPIO_FUNC_SPI);  // SCK
    gpio_set_function(DISPLAY_PIN_MOSI, GPIO_FUNC_SPI); // MOSI

    disp->external_vcc = false;
    ssd1306_proto_t p = {
        DISPLAY_SPI,
        DISPLAY_PIN_CS,   // CS
        DISPLAY_PIN_MISO, // DC
        DISPLAY_PIN_RST   // RST
    };
    ssd1306_init(disp, DISPLAY_WIDTH, DISPLAY_HEIGHT, p);
#else
    ssd1306_proto_t p = {DISPLAY_ADDRESS, I2C_PIO, I2C_SM, pio_i2c_write_blocking};
    ssd1306_init(disp, DISPLAY_WIDTH, DISPLAY_HEIGHT, p);
#endif // SPI_DISPLAY
            
    ssd1306_flip(disp, DISPLAY_FLIPPED);
    ssd1306_clear(disp);
    ssd1306_show(disp);
}

// ----------------------------------------------------------------------------
// State handlers

static void on_cal_idle() {
    // No MSC if there is no USB cable connected, so checking
    // tud is not necessary.
    bool battery = on_battery();
    if (!battery && msc_present()) {
        soft_reset();
    }

    static absolute_time_t timeout = {0};
    if (absolute_time_diff_us(get_absolute_time(), timeout) < 0) {
        timeout = make_timeout_time_ms(1000);

        float voltage_percentage_float = ((read_voltage() - BATTERY_MIN_V) / BATTERY_RANGE) * 100;
        if (voltage_percentage_float < 0) voltage_percentage_float = 0;
        if (voltage_percentage_float > 100) voltage_percentage_float = 100;
        uint8_t voltage_percentage = (uint8_t)voltage_percentage_float;
        static char battery_str[] = " PWR";
        if (battery) {
            if (voltage_percentage > 99) {
                snprintf(battery_str, sizeof(battery_str), "FULL");
            } else {
                snprintf(battery_str, sizeof(battery_str), "% 3d%%", voltage_percentage);
            }
        }

        ssd1306_clear(&disp);
        ssd1306_draw_string(&disp, 96,  0, 1, battery_str);
        ssd1306_draw_string(&disp,   0, 0, 2, "CAL EXP");
        if (fork_sensor.check_availability(&fork_sensor)) {
            ssd1306_draw_string(&disp,  0, 24, 1, "fork");
        }
        if (shock_sensor.check_availability(&shock_sensor)) {
            ssd1306_draw_string(&disp, 40, 24, 1, "shock");
        }
        ssd1306_show(&disp);
    }
}

static void on_cal_exp() {
    fork_sensor.calibrate_expanded(&fork_sensor);
    shock_sensor.calibrate_expanded(&shock_sensor);

    if (fork_sensor.baseline == 0xffff || shock_sensor.baseline == 0xffff) {
        display_message(&disp, "CAL ERR");
        buzzer_sound_error();
        sleep_ms(1000);
        state = CAL_IDLE_1;
        return;
    }

    FIL calibration_fil;
    FRESULT fr = f_open(&calibration_fil, "CALIBRATION", FA_CREATE_ALWAYS | FA_WRITE);
    if (!(fr == FR_OK || fr == FR_EXIST)) {
        display_message(&disp, "CAL ERR");
        buzzer_sound_error();
        sleep_ms(1000);
        state = CAL_IDLE_1;
        return;
    }

    uint bw;
    f_write(&calibration_fil, &fork_sensor.baseline, sizeof(uint16_t), &bw);
    f_write(&calibration_fil, (const void *)&fork_sensor.inverted, sizeof(bool), &bw);
    f_write(&calibration_fil, &shock_sensor.baseline, sizeof(uint16_t), &bw);
    f_write(&calibration_fil, (const void *)&shock_sensor.inverted, sizeof(bool), &bw);
    f_close(&calibration_fil);

    state = boardid_templates_available() ? BOARDID_SELECT : IDLE;
}

static void on_rec_start() {
    count = 0;
    active_buffer = databuffer1;
    multicore_fifo_drain();
    
    display_message(&disp, "INIT SENS");
    sleep_ms(100);
    if (!start_sensors()) {
        display_message(&disp, "NO SENS");
        sleep_ms(1000);
        state = IDLE;
        return;
    }

    if (!wait_for_sensors_ready()) {
        sensor_stop(&fork_sensor);
        sensor_stop(&shock_sensor);
        display_message(&disp, "SENS WAIT");
        sleep_ms(1000);
        state = IDLE;
        return;
    }

    state = RECORD;
    char msg[16];
    sprintf(msg, "REC:%s|%s", fork_sensor.available ? "F" : ".", shock_sensor.available ? "S" : ".");
    display_message(&disp, msg);
    buzzer_sound_start();

    multicore_fifo_push_blocking(OPEN);
    int index = (int)multicore_fifo_pop_blocking();
    if (index < 0) {
        display_message(&disp, "FILE ERR");
        while(true) { tight_loop_contents(); }
    }

    // t_0 is in the past: Catmull-Rom needs two later support points. Three
    // periods of the slower Fork ADC provide one additional period for jitter.
    // absolute_time_t only schedules the alarm; grid arithmetic stays uint32_t
    // so timerawl wrap remains exact according to the AP3 rule.
    absolute_time_t base = get_absolute_time();
    grid_t_k_us = timer_hw->timerawl - 3603u;
    grid_remainder = 0;
    grid_alarm_id = add_alarm_at(base, data_acquisition_cb, NULL, true);
    if (grid_alarm_id <= 0) {
        display_message(&disp, "TIMER ERR");
        while(true) { tight_loop_contents(); }
    }
}

static void on_rec_stop() {
    state = IDLE;
    cancel_alarm(grid_alarm_id);
    grid_alarm_id = 0;
    sensor_stop(&fork_sensor);
    sensor_stop(&shock_sensor);
    buzzer_sound_stop();

    multicore_fifo_push_blocking(FINISH);
    multicore_fifo_push_blocking(count);
    multicore_fifo_push_blocking((uintptr_t)active_buffer);

    display_message(&disp, "IDLE");
    bool displayed = false;
    displayed |= report_sensor_counters(&fork_sensor, DRDY_CHANNEL_FORK, "F");
    displayed |= report_sensor_counters(&shock_sensor, DRDY_CHANNEL_SHOCK, "S");
    if (displayed) {
        display_message(&disp, "IDLE");
    }
}

static void on_sync_data() {
    display_message(&disp, "CONNECT");
    if (!wifi_connect(true)) {
        display_message(&disp, "CONN ERR");
        sleep_ms(1000);
    } else {
        display_message(&disp, "DAT SYNC");
        FRESULT fr;
        DIR dj;
        FILINFO fno;
        uint all = 0;

        // get a list of all .SST files in the root directory
        struct list *to_import = list_create();
        fr = f_findfirst(&dj, &fno, "", "?????.SST");
        while (fr == FR_OK && fno.fname[0]) {
            ++all;
            list_push(to_import, fno.fname);
            fr = f_findnext(&dj, &fno);
        }
        f_closedir(&dj);

        // send all files on the list via TCP, and move them
        // to the "uploaded" directory
        uint err = 0;
        uint curr = 0;
        struct node *n = to_import->head;
        TCHAR path_new[19];
        TCHAR status[10];
        TCHAR failed[12];

        while (n != NULL) {
            ++curr;
            if (send_file(n->data)) {
                sprintf(path_new, "uploaded/%s", n->data);
                f_rename(n->data, path_new);
            } else {
                ++err;
            }
            sprintf(status, "%u / %u", curr, all);
            sprintf(failed, "failed: %u", err);
            ssd1306_clear(&disp);
            ssd1306_draw_string(&disp, 0,  0, 2, status);
            ssd1306_draw_string(&disp, 0, 24, 1, failed);
            ssd1306_show(&disp);

            // wait a bit to avoid weird TCP errors...
            sleep_ms(100);
            n = n->next;
        }
        list_delete(to_import);

        // leave results on the display for a bit
        sleep_ms(3000);
    }
    wifi_disconnect();
    state = IDLE;
}

static void on_idle() {
    // No MSC if there is no USB cable connected, so checking
    // tud is not necessary.
    bool battery = on_battery();
    if (!battery && msc_present()) {
        soft_reset();
    }

    static absolute_time_t timeout = {0};
    if (absolute_time_diff_us(get_absolute_time(), timeout) < 0) {
        timeout = make_timeout_time_ms(1000);

        float voltage_percentage_float = ((read_voltage() - BATTERY_MIN_V) / BATTERY_RANGE) * 100;
        if (voltage_percentage_float < 0) voltage_percentage_float = 0;
        if (voltage_percentage_float > 100) voltage_percentage_float = 100;
        uint8_t voltage_percentage = (uint8_t)voltage_percentage_float;
        static char battery_str[] = " PWR";
        if (battery) {
            if (voltage_percentage > 99) {
                snprintf(battery_str, sizeof(battery_str), "FULL");
            } else {
                snprintf(battery_str, sizeof(battery_str), "% 3d%%", voltage_percentage);
            }
        }

        static char time_str[] = "00:00";
        static struct tm tz_tm;
        time_t t = rtc_timestamp();
        localtime_r(&t, &tz_tm);
        snprintf(time_str, sizeof(time_str), "%02d:%02d", tz_tm.tm_hour, tz_tm.tm_min);

        ssd1306_clear(&disp);
        ssd1306_draw_string(&disp, 96,  0, 1, battery_str);
        ssd1306_draw_string(&disp,   0, 0, 2, time_str);
        if (fork_sensor.check_availability(&fork_sensor)) {
            ssd1306_draw_string(&disp,  0, 24, 1, "fork");
        }
        if (shock_sensor.check_availability(&shock_sensor)) {
            ssd1306_draw_string(&disp, 40, 24, 1, "shock");
        }
        const char *suf = boardid_current_suffix();
        if (suf && suf[0]) {
            ssd1306_draw_string(&disp, 0, 46, 1, (char *)suf);
        }
        const char *bid = boardid_current_id();
        if (bid && bid[0]) {
            ssd1306_draw_string(&disp, 0, 56, 1, (char *)bid);
        }
        ssd1306_show(&disp);
    }
}

static void on_sleep() {
    // Play sleep sound blocking — must complete before clock reconfiguration,
    // otherwise the silence alarm is lost and PWM runs forever after wake.
    buzzer_sound_sleep();

    sleep_run_from_xosc();
    display_message(&disp, "SLEEP.");

    clocks_hw->sleep_en0 = CLOCKS_SLEEP_EN0_CLK_RTC_RTC_BITS;
    clocks_hw->sleep_en1 = 0x0;
    display_message(&disp, "SLEEP..");

    scb_hw->scr = scb_orig | M0PLUS_SCR_SLEEPDEEP_BITS;
    display_message(&disp, "SLEEP...");

    disable_button(BUTTON_LEFT, false);
    disable_button(BUTTON_RIGHT, true);
    ssd1306_poweroff(&disp);
    state = WAKING;
    __wfi();
}

static void on_waking() {
    rosc_write(&rosc_hw->ctrl, ROSC_CTRL_ENABLE_BITS);

    scb_hw->scr = scb_orig;
    clocks_hw->sleep_en0 = clock0_orig;
    clocks_hw->sleep_en1 = clock1_orig;
    runtime_init_clocks();
    buzzer_init();
    buzzer_sound_wake();

    ssd1306_poweron(&disp);
    enable_button(BUTTON_LEFT);
    enable_button(BUTTON_RIGHT);
    state = IDLE;
}

static void on_msc() {
    // A suspended bus must not reset the device: macOS parks an idle MSC
    // device a few minutes after mounting (the volume stays mounted and the
    // host resumes the device on the next access), and tud_task() handles
    // resume and host reboots by itself. Unplugging is detected via VSYS
    // instead — above ~4.4 V only happens on USB power, the battery tops out
    // at ~4.2 V. The read must go through read_voltage(): on the Pico W the
    // unpowered wireless chip clamps the shared ADC3/GPIO29 line to ~0 V, so
    // main() brings it up before entering MSC state. (VBUS via
    // cyw43_arch_gpio_get is no alternative either — the chip's power-save
    // makes that report VBUS loss spuriously.)
    static absolute_time_t vsys_check = {0};
    static int vsys_low = 0;
    if (msc_vsys_ok && absolute_time_diff_us(get_absolute_time(), vsys_check) < 0) {
        vsys_check = make_timeout_time_ms(250);
        if (read_voltage() < 4.4f) {
            if (++vsys_low >= 3) {
                soft_reset();
            }
        } else {
            vsys_low = 0;
        }
    }
    tud_task();
}

static void dummy() {
    tight_loop_contents();
}

static void on_serve_tcp() {
    bool auto_exit = false;
    display_message(&disp, "CONNECT");
    if (!wifi_connect(true)) {
        display_message(&disp, "CONN ERR");
        sleep_ms(1000);
    } else if (tcpserver_init(&server)) {
        display_message(&disp, "SERVER ON");
        tcpserver_serve(&server);
        // Auto-exit (client sent STATUS_FINISHED) leaves state == SERVE_TCP;
        // the right-button path sets state = IDLE before tcpserver_serve returns.
        auto_exit = (state == SERVE_TCP);
    }
    // Disconnect WiFi before the audible/visual confirmation so a stall in
    // cyw43/lwIP teardown can't keep the buzzer's silence alarm from firing.
    wifi_disconnect();
    if (auto_exit) {
        display_message(&disp, "DONE");
        sleep_ms(5000);
        // Completion owns the transition; override a late IRQ-side IDLE write.
        state = SLEEP;
    } else {
        state = IDLE;
    }
}

static struct boardid_menu boardid_menu_state;
static bool boardid_menu_entered = false;

static void on_boardid_select() {
    if (!boardid_menu_entered) {
        boardid_scan(&boardid_menu_state);
        if (boardid_menu_state.count == 0) {
            display_message(&disp, "NO TPL");
            buzzer_sound_error();
            sleep_ms(1000);
            state = IDLE;
            return;
        }
        boardid_render(&disp, &boardid_menu_state);
        boardid_menu_entered = true;
    }
    tight_loop_contents();
}

static void (*state_handlers[STATES_COUNT])() = {
    on_idle,      /* IDLE */
    on_sleep,     /* SLEEP */
    on_waking,    /* WAKING */
    on_rec_start, /* REC_START */
    dummy,        /* RECORD */
    on_rec_stop,  /* REC_STOP */
    on_sync_data, /* SYNC_DATA */
    on_serve_tcp, /* SERVE_TCP */
    on_msc,       /* MSC */
    on_cal_idle,       /* CAL_IDLE_1 */
    on_cal_exp,        /* CAL_EXP */
    on_boardid_select, /* BOARDID_SELECT */
};

// ----------------------------------------------------------------------------
// Button handlers

static void on_left_press(void *user_data) {
    switch(state) {
        case CAL_IDLE_1:
            buzzer_sound_cal();
            state = CAL_EXP;
            break;
        case IDLE:
            buzzer_sound_confirm();
            state = REC_START;
            break;
        case RECORD:
            state = REC_STOP;
            break;
        case BOARDID_SELECT:
            if (boardid_menu_state.count > 0) {
                boardid_menu_state.selected = (boardid_menu_state.selected + 1) % boardid_menu_state.count;
                int top = boardid_menu_state.top;
                int sel = boardid_menu_state.selected;
                if (sel < top) top = sel;
                else if (sel >= top + BOARDID_PAGE_SIZE) top = sel - BOARDID_PAGE_SIZE + 1;
                if (sel == 0) top = 0;
                boardid_menu_state.top = top;
                boardid_render(&disp, &boardid_menu_state);
                buzzer_sound_confirm();
            }
            break;
        default:
            break;
    }
}

static void on_left_longpress(void *user_data) {
    switch(state) {
        case IDLE:
            state = SYNC_DATA;
            break;
        default:
            break;
    }
}

static void on_right_press(void *user_data) {
    switch(state) {
        case IDLE:
            state = SLEEP;
            break;
        case SERVE_TCP:
            buzzer_sound_confirm();
            tcpserver_finish(&server);
            state = IDLE;
            break;
        case BOARDID_SELECT:
            if (boardid_menu_state.count > 0) {
                boardid_apply(boardid_menu_state.templates[boardid_menu_state.selected]);
                buzzer_sound_confirm();
            }
            boardid_menu_entered = false;
            state = IDLE;
            break;
        default:
            break;
    }
}

static void on_right_longpress(void *user_data) {
    switch(state) {
        case IDLE:
            buzzer_sound_confirm();
            state = SERVE_TCP;
            break;
        case BOARDID_SELECT:
            boardid_menu_entered = false;
            state = IDLE;
            break;
        default:
            break;
    }
}

// ----------------------------------------------------------------------------
// Entry point 

int main() {
    board_init();
    buzzer_init();
    buzzer_sound_wake();
    tusb_init();
    rtc_init();
    adc_init();
    fork_sensor.init(&fork_sensor);
    shock_sensor.init(&shock_sensor);
#ifndef NDEBUG
    stdio_uart_init();
#endif

    uint offset = pio_add_program(I2C_PIO, &i2c_program);
    i2c_program_init(I2C_PIO, I2C_SM, offset, PIO_PIN_SDA, PIO_PIN_SDA+1);

    datetime_t dt;
    ds3231_init(&rtc, I2C_PIO, I2C_SM,
                pio_i2c_write_blocking,
                pio_i2c_read_blocking);
    sleep_ms(1); // without this, garbage values are read from the RTC
    ds3231_get_datetime(&rtc, &dt);
    rtc_set_datetime(&dt);

    setup_display(&disp);

    if (msc_present()) {
        // The wireless chip has to be powered for the VSYS-based unplug
        // detection in on_msc — see there.
        msc_vsys_ok = cyw43_arch_init() == 0;
        state = MSC;
        display_message(&disp, "MSC MODE");
    } else {
        display_message(&disp, "INIT STOR");
        multicore_launch_core1(&data_storage_core1);
        int err = (int)multicore_fifo_pop_blocking();
        if (err < 0) {
            display_message(&disp, "CARD ERR");
            while(true) { tight_loop_contents(); }
        }

        if (!load_config()) {
            display_message(&disp, "CONF ERR");
            while(true) { tight_loop_contents(); }
        }

        setup_ntp(config.ntp_server);
        cyw43_arch_init_with_country(config.country);
        setenv("TZ", config.timezone, 1);
        tzset();

        scb_orig = scb_hw->scr;
        clock0_orig = clocks_hw->sleep_en0;
        clock1_orig = clocks_hw->sleep_en1;

        boardid_load_current_suffix();

        calibrate_if_needed();

        create_button(BUTTON_LEFT, NULL, on_left_press, on_left_longpress);
        create_button(BUTTON_RIGHT, NULL, on_right_press, on_right_longpress);
    }

    while (true) {
        state_handlers[state]();
    }

    return 0;
}
