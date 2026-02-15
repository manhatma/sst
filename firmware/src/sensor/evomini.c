/**
 * evomini.c
 *
 * Implementation of the Terabee TeraRanger Evo Mini sensor for short-range,
 * 1px mode operation (distance in millimetres) without CRC error handling.
 *
 * Detailed I2C transaction logs are written to an SD log file via evomini_debug.
 */

#include "sensor.h"                   // Sensor structure definitions (with include guards)
#include "../fw/hardware_config.h"    // Hardware configuration (defines pin assignments, etc.)
#include <pico/stdlib.h>              // For sleep_ms(), etc.
#include <hardware/i2c.h>             // For hardware I2C functions
#include "evomini_debug.h"            // Debug/logging functions (outsourced)
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <limits.h>                   // For UINT16_MAX
#include "ff.h"

#define EVOMINI_I2C_ADDR            0x31
#define EVOMINI_WHO_AM_I            0x01
#define EVOMINI_WHO_AM_I_RESPONSE   0xa1
#define EVOMINI_WHO_AM_I_READ_BYTES 1
//#define EVOMINI_SENSOR_TRIGGER      0x00 
#define EVOMINI_READ_TRIGGER    	0x00 // ((EVOMINI_I2C_ADDR << 1) | 1)
#define EVOMINI_READ_BYTES          3
// #define EVOMINI_FORK_TRAVEL			170

static void evomini_sensor_init(struct sensor *sensor) {
    sleep_ms(1000); // Delay for sensor initialization

    // Initialize I2C at 100 kHz
    i2c_init(sensor->comm.i2c.instance, 100 * 1000);

    // Set GPIO functions for I2C
    gpio_set_function(sensor->comm.i2c.sda_gpio, GPIO_FUNC_I2C);
    gpio_set_function(sensor->comm.i2c.scl_gpio, GPIO_FUNC_I2C);

    // Enable internal pull-up resistors
    gpio_pull_up(sensor->comm.i2c.sda_gpio); // Enable pull-up on SDA
    gpio_pull_up(sensor->comm.i2c.scl_gpio); // Enable pull-up on SCL

    // Log initialization message
    // evomini_log("EvoMini: Initializing sensor...");

    // Log completion message
    // evomini_log("EvoMini: Init complete.");
}

static bool evomini_sensor_check_availability(struct sensor *sensor) {
        sensor->available = true;
        return true;
}

static bool evomini_sensor_start(struct sensor *sensor, uint16_t baseline, bool inverted) {
    if (!sensor->check_availability(sensor)) {
    	// evomini_log("EvoMini: !sensor->check_availability - FALSE.");
        return false;
    }
    // Set baseline from the provided parameter
    sensor->baseline = baseline;
    // evomini_log("EvoMini: Baseline set to: %d mm", sensor->baseline);

    // evomini_log("EvoMini: Starting sensor mode.");
    return true;
}

static uint16_t evomini_sensor_measure(struct sensor *sensor) {
//	if (sensor->baseline == 0) {
//		sensor->baseline = EVOMINI_FORK_TRAVEL;
//	}
//    // evomini_log("EvoMini: Reading measurement.");

    uint8_t read_trigger = EVOMINI_READ_TRIGGER;      
    i2c_write_blocking(sensor->comm.i2c.instance, EVOMINI_I2C_ADDR, &read_trigger, 1, true);
//    // evomini_log_i2c_transaction("EvoMini: -> Read Trigger", EVOMINI_I2C_ADDR, &read_trigger, 1);
//    sleep_us(20);
    
    uint8_t data[EVOMINI_READ_BYTES] = {0};
    i2c_read_blocking(sensor->comm.i2c.instance, EVOMINI_I2C_ADDR, data, EVOMINI_READ_BYTES, false);
//    // evomini_log_i2c_transaction("EvoMini: Read Data from Sensor", EVOMINI_I2C_ADDR, data, EVOMINI_READ_BYTES);

    uint16_t raw_distance = (data[0] << 8) | data[1];
    int16_t rel_distance = (int16_t)sensor->baseline - (int16_t)raw_distance;
    if (rel_distance < 0) {
    	// evomini_log("EvoMini: Reading below Zero: %d mm", rel_distance);
    	rel_distance = 0;
    	// evomini_log("EvoMini: ->Adjusted Distance: %d mm", rel_distance);    	
    	return rel_distance;
    }
    else if (rel_distance > sensor->baseline) {
    	// evomini_log("EvoMini: Reading above Max: %d mm", rel_distance);
    	rel_distance = sensor->baseline;
    	// evomini_log("EvoMini: ->Adjusted Distance: %d mm", rel_distance);    	
    	return rel_distance;    		
    }
    else {
//	    // evomini_log("EvoMini: Raw Distance: %d mm", raw_distance);
    	// evomini_log("EvoMini: Distance: %d mm", rel_distance);
    	return rel_distance;
    }
}   

static void evomini_sensor_calibrate_expanded(struct sensor *sensor) {
    uint8_t read_trigger = EVOMINI_READ_TRIGGER;      
    i2c_write_blocking(sensor->comm.i2c.instance, EVOMINI_I2C_ADDR, &read_trigger, 1, true);
    uint8_t data[EVOMINI_READ_BYTES] = {0};
    i2c_read_blocking(sensor->comm.i2c.instance, EVOMINI_I2C_ADDR, data, EVOMINI_READ_BYTES, false);
    sensor->baseline = (data[0] << 8) | data[1];
    // evomini_log("EvoMini: Expanded calibration value: %d mm", sensor->baseline);
}

static void evomini_sensor_calibrate_compressed(struct sensor *sensor) {
    sensor->inverted = false;
}

//--------------------------------------------------------------------------
/* Sensor structure instances */
#ifdef EVOMINI_FORK_SENSOR
struct sensor fork_sensor = {
    .comm.i2c = {FORK_I2C, FORK_PIN_SCL, FORK_PIN_SDA},
    .init = evomini_sensor_init,
    .check_availability = evomini_sensor_check_availability,
    .start = evomini_sensor_start,
    .calibrate_expanded = evomini_sensor_calibrate_expanded,
    .calibrate_compressed = evomini_sensor_calibrate_compressed,
    .measure = evomini_sensor_measure,
};
#endif

#ifdef EVOMINI_SHOCK_SENSOR
struct sensor shock_sensor = {
    .comm.i2c = {SHOCK_I2C, SHOCK_PIN_SCL, SHOCK_PIN_SDA},
    .init = evomini_sensor_init,
    .check_availability = evomini_sensor_check_availability,
    .start = evomini_sensor_start,
    .calibrate_expanded = evomini_sensor_calibrate_expanded,
    .calibrate_compressed = evomini_sensor_calibrate_compressed,
    .measure = evomini_sensor_measure,
};
#endif
