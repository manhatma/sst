#include "ntp.h"
#include "lwip/apps/sntp.h"
#include "pico/time.h"
#include "hardware/rtc.h"

#include "../rtc/ds3231.h"
#include "../util/config.h"

extern struct ds3231 rtc;

static volatile uint64_t start_time_us = 0;
static volatile bool ntp_done = false;

static bool datetime_plausible(const datetime_t *dt) {
    return dt->sec >= 0 && dt->sec <= 59
        && dt->min >= 0 && dt->min <= 59
        && dt->hour >= 0 && dt->hour <= 23
        && dt->dotw >= 0 && dt->dotw <= 6
        && dt->day >= 1 && dt->day <= 31
        && dt->month >= 1 && dt->month <= 12
        && dt->year >= 2024 && dt->year <= 2099;
}

static time_t datetime_to_epoch(const datetime_t *dt) {
    struct tm utc = {
        .tm_year = dt->year - 1900,
        .tm_mon = dt->month - 1,
        .tm_mday = dt->day,
        .tm_hour = dt->hour,
        .tm_min = dt->min,
        .tm_sec = dt->sec,
        .tm_isdst = -1,
        .tm_wday = 0,
        .tm_yday = 0,
    };

    // We want to store UTC values in record files, and we don't have timegm,
    // so we set UTC0 as timezone string here ...
    setenv("TZ", "UTC0", 1);
    tzset();

    time_t t = mktime(&utc);

    // ... and we restore the original one after we got the timestamp.
    setenv("TZ", config.timezone, 1);
    tzset();

    return t;
}

time_t rtc_timestamp() {
    datetime_t dt;
    ds3231_get_datetime(&rtc, &dt);

    if (datetime_plausible(&dt)) {
        rtc_set_datetime(&dt);
        return datetime_to_epoch(&dt);
    }

    rtc_get_datetime(&dt);
    return datetime_to_epoch(&dt);
}

bool sync_rtc_to_ntp() {
    ntp_done = false;
    sntp_init();

    absolute_time_t timeout_time = make_timeout_time_ms(NTP_TIMEOUT_TIME);
    while (!ntp_done && absolute_time_diff_us(get_absolute_time(), timeout_time) > 0) {
        tight_loop_contents();
    }

    sntp_stop();

    return ntp_done;
}

void setup_ntp(const char* server) {
    sntp_setoperatingmode(SNTP_OPMODE_POLL);
    sntp_setservername(0, server);
    start_time_us = rtc_timestamp() * 1000000;
}

uint64_t get_system_time_us() {
    return start_time_us + time_us_64();
}

void set_system_time_us(uint32_t sec, uint32_t us) {
    // Writing the DS3231 seconds register restarts its 1 Hz divider. When us
    // is known, wait out the rest of the current second and write the next
    // second so both clocks land on the real second boundary. This blocks
    // for < 1 s. Safe here: pico_cyw43_arch_lwip_threadsafe_background keeps
    // lwIP running in the background, and process_time_sync() runs in main
    // context, not in a button callback. us == 0 keeps the old immediate
    // write (old app, no sub-second info).
    if (us > 0 && us < 1000000) {
        busy_wait_us(1000000 - us);
        sec += 1;
        us = 0;
    }

    time_t epoch = sec;
    struct tm *time = gmtime(&epoch);
    datetime_t dt = {
        .year  = time->tm_year + 1900,
        .month = time->tm_mon + 1,
        .day   = time->tm_mday,
        .dotw  = time->tm_wday,
        .hour  = time->tm_hour,
        .min   = time->tm_min,
        .sec   = time->tm_sec,
    };
    rtc_set_datetime(&dt);
    ds3231_set_datetime(&rtc, &dt);
    start_time_us = (epoch * 1000000 + us) - time_us_64();
    ntp_done = true;
}
