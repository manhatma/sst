#include <stdio.h>
#include "hardware/i2c.h"
#include "hardware/gpio.h"
#include "sensor.h"
#include "ads1115.h"
#include "drdy_ring.h"
#include "../fw/hardware_config.h"
#include <stdint.h>
#include "pico/stdlib.h"
#include "hardware/uart.h"
#include <stdarg.h>


#define VREF			3.3
#define PGA				4.096
static const uint16_t MAX_ADC_3P3V = (uint16_t)((VREF/PGA)*32768.0f + 0.5f); // #define MAX_ADC_3P3V 	26400 

// Forward declarations --------------------------------------------------------
#ifdef FORK_LINEAR
extern struct sensor fork_sensor;
//#define VLP    							200
//#define FORK_THRESHOLD_MM				1
//#define FORK_ADC_RES_CNTPMM				(MAX_ADC_3P3V / VLP)	// 26400 / 200 = 132 cnt/mm
//#define FORK_LOWER_ADC_THRESHOLD		(FORK_ADC_RES_CNTPMM * FORK_THRESHOLD_MM)	// 132 -> 1 mm abs. 
#endif

#ifdef SHOCK_LINEAR
extern struct sensor shock_sensor;
//#define ELPM   							75
//#define SHOCK_THRESHOLD_MM				1
//#define SHOCK_ADC_RES_CNTPMM			(MAX_ADC_3P3V / ELPM)	// 26400 / 75 = 352 cnt/mm
//#define SHOCK_LOWER_ADC_THRESHOLD		(SHOCK_ADC_RES_CNTPMM * SHOCK_THRESHOLD_MM)	// 352 -> 1 mm abs.
#endif

// ADS1115 configurations ------------------------------------------------------
#ifdef FORK_LINEAR
static ads1115_adc_t fork_adc = {.i2c_addr = 0x48};
#endif

#ifdef SHOCK_LINEAR
static ads1115_adc_t shock_adc = {.i2c_addr = 0x48};
#endif

// Debugging utilities ---------------------------------------------------------
#ifdef DEBUG
#define DEBUG_UART uart0

static void uart_init_default() {
    uart_init(DEBUG_UART, 115200);
    gpio_set_function(0, GPIO_FUNC_UART);
    gpio_set_function(1, GPIO_FUNC_UART);
}

static void debug_print(const char *msg) {
    uart_puts(DEBUG_UART, msg);
}

static void debug_printf(const char *format, ...) {
    char buffer[128];
    va_list args;
    va_start(args, format);
    vsnprintf(buffer, sizeof(buffer), format, args);
    va_end(args);
    debug_print(buffer);
}
#else
#define debug_print(msg)
#define debug_printf(...)
#endif // DEBUG

// ADS1115 instance mapping ----------------------------------------------------
static ads1115_adc_t* get_ads1115(struct sensor *sensor) {
#ifdef FORK_LINEAR
    if (sensor == &fork_sensor) {
        fork_adc.i2c_port = sensor->comm.i2c.instance;
        return &fork_adc;
    }
#endif
#ifdef SHOCK_LINEAR
    if (sensor == &shock_sensor) {
        shock_adc.i2c_port = sensor->comm.i2c.instance;
        return &shock_adc;
    }
#endif

    return NULL;
}

static enum drdy_channel get_drdy_channel(struct sensor *sensor) {
#ifdef FORK_LINEAR
    if (sensor == &fork_sensor) {
        return DRDY_CHANNEL_FORK;
    }
#endif
#ifdef SHOCK_LINEAR
    if (sensor == &shock_sensor) {
        return DRDY_CHANNEL_SHOCK;
    }
#endif

    return DRDY_CHANNEL_COUNT;
}

// Sensor operations -----------------------------------------------------------
static void linear_sensor_ads1115_init(struct sensor *sensor) {
#ifdef DEBUG
    uart_init_default();
#endif

    i2c_init(sensor->comm.i2c.instance, 1000 * 1000);
    gpio_set_function(sensor->comm.i2c.sda_gpio, GPIO_FUNC_I2C);
    gpio_set_function(sensor->comm.i2c.scl_gpio, GPIO_FUNC_I2C);
    // External 2.2 kOhm pull-ups in parallel with the modules' 10 kOhm measure
    // 1.8 kOhm and keep rise time within the Fm+ spec; disable the internal
    // pull-ups to define that value. 1 MHz instead of 400 kHz halves ISR jitter
    // by blocking the read for less time (37 us rather than 81 us maximum).
    gpio_disable_pulls(sensor->comm.i2c.sda_gpio);
    gpio_disable_pulls(sensor->comm.i2c.scl_gpio);

    ads1115_adc_t *adc = get_ads1115(sensor);
    if (!adc) {
        return;
    }

    static const uint8_t hi_thresh[] = {0x03, 0x80, 0x00};
    static const uint8_t lo_thresh[] = {0x02, 0x00, 0x00};

    int hi_result = i2c_write_blocking(sensor->comm.i2c.instance,
                                       adc->i2c_addr, hi_thresh,
                                       sizeof(hi_thresh), false);
    if (hi_result != (int)sizeof(hi_thresh)) {
        debug_printf("ADS1115 HI_THRESH write failed: %d\n", hi_result);
    }

    int lo_result = i2c_write_blocking(sensor->comm.i2c.instance,
                                       adc->i2c_addr, lo_thresh,
                                       sizeof(lo_thresh), false);
    if (lo_result != (int)sizeof(lo_thresh)) {
        debug_printf("ADS1115 LO_THRESH write failed: %d\n", lo_result);
    }

    ads1115_init(sensor->comm.i2c.instance, adc->i2c_addr, adc);
    ads1115_set_input_mux(ADS1115_MUX_SINGLE_0, adc);
    ads1115_set_pga(ADS1115_PGA_4_096, adc);
    ads1115_set_operating_mode(ADS1115_MODE_CONTINUOUS, adc);
    ads1115_set_data_rate(ADS1115_RATE_860_SPS, adc);
    adc->config = (adc->config & ~ADS1115_COMP_QUE_MASK) |
                  ADS1115_COMPARATOR_QUE_1;

    ads1115_write_config(adc);

    uint8_t reg = ADS1115_POINTER_CONVERSION;
    int pointer_result = i2c_write_blocking(adc->i2c_port, adc->i2c_addr,
                                            &reg, 1, false);
    if (pointer_result != 1) {
        debug_printf("ADS1115 conversion pointer write failed: %d\n",
                     pointer_result);
    }

    drdy_ring_init(get_drdy_channel(sensor), adc->i2c_port, adc->i2c_addr);
}

static bool linear_sensor_ads1115_check_availability(struct sensor *sensor) {
    ads1115_adc_t* adc = get_ads1115(sensor);
    if (!adc) return false;

    uint8_t dummy;
    int ret = i2c_read_blocking(sensor->comm.i2c.instance, 
                               adc->i2c_addr, &dummy, 1, false);
    sensor->available = (ret >= 0);
    
    return sensor->available;
}

static bool linear_sensor_ads1115_start(struct sensor *sensor, uint16_t baseline, bool inverted) {
    if (!sensor->check_availability(sensor)) return false;
    sensor->baseline = baseline;
    drdy_ring_enable(get_drdy_channel(sensor));
    return true;
}

// The register pointer is set to 0x00 during init and no other path may move it.
// check_availability only reads, and calibrate_expanded uses this function. A
// future MUX change (ratiometric AIN1 tap, hardware checklist phase E) writes
// config at pointer 0x01 and must explicitly restore the pointer to 0x00.
static int ads1115_read_adc_debug(uint16_t *adc_value, ads1115_adc_t *adc) {
    uint8_t dst[2];

    // Read conversion result
    int ret = i2c_read_blocking(adc->i2c_port, adc->i2c_addr, dst, 2, false);
    if (ret != 2) {
        return -2;
    }
    
    *adc_value = (dst[0] << 8) | dst[1];
    return 0;
}

static uint16_t apply_baseline(const struct sensor *sensor,
                               uint16_t raw_value) {
    int16_t adc_travel = (int16_t)raw_value - (int16_t)sensor->baseline;

//    uint16_t lower_adc_threshold;
//    if (sensor == &fork_sensor) { 
//    	lower_adc_threshold = FORK_LOWER_ADC_THRESHOLD;
//	} else {
//    	lower_adc_threshold = SHOCK_LOWER_ADC_THRESHOLD;
//	}
	
    uint16_t travel;	
    if (adc_travel < 0) {// if (adc_travel <= lower_adc_threshold) {
    	travel = 0;
    } else {
    	travel = (uint16_t)adc_travel;
    }

    return travel;
}

static uint16_t linear_sensor_ads1115_measure(struct sensor *sensor) {
    ads1115_adc_t* adc = get_ads1115(sensor);
    if (!adc || !sensor->available) return 0xFFFF;

    uint16_t raw_value;
    int ret = ads1115_read_adc_debug(&raw_value, adc);
    if (ret != 0) {
        return 0xFFFF;
    }

    return apply_baseline(sensor, raw_value);
}

static uint16_t linear_sensor_ads1115_sample_at(struct sensor *sensor,
                                                 uint32_t t_k_us) {
    if (!sensor->available) return 0xFFFF;

    uint16_t raw_value =
        drdy_ring_resample(get_drdy_channel(sensor), t_k_us);
    return apply_baseline(sensor, raw_value);
}

static bool linear_sensor_ads1115_ready(struct sensor *sensor) {
    return drdy_ring_count(get_drdy_channel(sensor)) >= 4;
}

static void linear_sensor_ads1115_stop(struct sensor *sensor) {
    drdy_ring_disable(get_drdy_channel(sensor));
}

static void linear_sensor_ads1115_calibrate_expanded(struct sensor *sensor) {
	sensor->baseline = 0xFFFF;
    ads1115_adc_t* adc = get_ads1115(sensor);
    if (!adc) return;

    uint16_t raw_value = 0xFFFF;
    int ret = ads1115_read_adc_debug(&raw_value, adc);
    if (ret != 0) return;

    sensor->baseline = raw_value;
}

static void linear_sensor_ads1115_calibrate_compressed(struct sensor *sensor) {
	sensor->inverted = false;
}

// Sensor instances ------------------------------------------------------------
#ifdef FORK_LINEAR
struct sensor fork_sensor = {
    .comm.i2c = {FORK_I2C, FORK_PIN_SCL, FORK_PIN_SDA},
    .init = linear_sensor_ads1115_init,
    .check_availability = linear_sensor_ads1115_check_availability,
    .start = linear_sensor_ads1115_start,
    .calibrate_expanded = linear_sensor_ads1115_calibrate_expanded,
    .calibrate_compressed = linear_sensor_ads1115_calibrate_compressed,
    .measure = linear_sensor_ads1115_measure,
    .sample_at = linear_sensor_ads1115_sample_at,
    .ready = linear_sensor_ads1115_ready,
    .stop = linear_sensor_ads1115_stop,
};
#endif

#ifdef SHOCK_LINEAR
struct sensor shock_sensor = {
    .comm.i2c = {SHOCK_I2C, SHOCK_PIN_SCL, SHOCK_PIN_SDA},
    .init = linear_sensor_ads1115_init,
    .check_availability = linear_sensor_ads1115_check_availability,
    .start = linear_sensor_ads1115_start,
    .calibrate_expanded = linear_sensor_ads1115_calibrate_expanded,
    .calibrate_compressed = linear_sensor_ads1115_calibrate_compressed,
    .measure = linear_sensor_ads1115_measure,
    .sample_at = linear_sensor_ads1115_sample_at,
    .ready = linear_sensor_ads1115_ready,
    .stop = linear_sensor_ads1115_stop,
};
#endif
