#include "hardware/i2c.h"
#include "hardware/gpio.h"  // Added for gpio_set_function, gpio_pull_up, etc.
#include "sensor.h"
#include "../fw/hardware_config.h"
#include <stdint.h>
#include <stdio.h>

// Declare sensor instances so they are in scope
extern struct sensor fork_sensor;
extern struct sensor shock_sensor;

#define EVOMINI_I2C_ADDRESS 0x31   // I2C address for the Evo Mini sensor
#define ROTARY_SENSOR_MAX 4095     // Maximum value for 12-bit resolution (0-4095)

// Calibration structure: holds sensor readings for fully extended (expanded)
// and fully compressed (compressed) positions.
struct evomini_calibration {
    uint16_t expanded;   // Fully extended reading (max sensor value; corresponds to 0 displacement)
    uint16_t compressed; // Fully compressed reading (min sensor value; corresponds to full travel)
};

// Global calibration records for fork and shock sensors.
static struct evomini_calibration fork_cal = {0, 0};
static struct evomini_calibration shock_cal = {0, 0};

// Reads a 16-bit value from the Evo Mini sensor over I2C.
static uint16_t evomini_read_distance(i2c_inst_t *i2c) {
    uint8_t command = 0x00;      // Command to trigger a measurement
    uint8_t response[2] = {0};   // Buffer for the sensor response

    if (i2c_write_blocking(i2c, EVOMINI_I2C_ADDRESS, &command, 1, true) == PICO_ERROR_GENERIC) {
        return 0xFFFF;         // Return error value if write fails
    }
    if (i2c_read_blocking(i2c, EVOMINI_I2C_ADDRESS, response, 2, false) == PICO_ERROR_GENERIC) {
        return 0xFFFF;         // Return error value if read fails
    }
    return (response[0] << 8) | response[1];  // Combine bytes into a 16-bit value
}

// Initializes the sensor by setting up I2C and configuring GPIO pins.
static void rotational_sensor_init(struct sensor *sensor) {
    i2c_init(sensor->comm.i2c.instance, 1000000);  // Initialize I2C at 1MHz
    gpio_set_function(sensor->comm.i2c.sda_gpio, GPIO_FUNC_I2C); // Configure SDA for I2C
    gpio_set_function(sensor->comm.i2c.scl_gpio, GPIO_FUNC_I2C); // Configure SCL for I2C
    gpio_pull_up(sensor->comm.i2c.sda_gpio); // Enable pull-up on SDA
    gpio_pull_up(sensor->comm.i2c.scl_gpio); // Enable pull-up on SCL
}

// Checks if the sensor is responsive.
static bool rotational_sensor_check_availability(struct sensor *sensor) {
    uint8_t dummy = 0x00;
    int result = i2c_write_blocking(sensor->comm.i2c.instance, EVOMINI_I2C_ADDRESS, &dummy, 1, true);
    sensor->available = (result != PICO_ERROR_GENERIC);
    return sensor->available;
}

// Starts the sensor and stores a baseline value (inversion flag is ignored).
static bool rotational_sensor_start(struct sensor *sensor, uint16_t baseline, bool inverted) {
    if (!sensor->check_availability(sensor)) {
        return false;
    }
    sensor->baseline = baseline; // Store baseline for compatibility
    return true;
}

// Reads the sensor value and maps it into a 12-bit output (0–4095).
static uint16_t rotational_sensor_measure(struct sensor *sensor) {
    static uint16_t value = 0xFFFF;  // Default error value
    if (sensor->available) {
        uint16_t raw = evomini_read_distance(sensor->comm.i2c.instance);
        struct evomini_calibration *cal = NULL;
        if (sensor == &fork_sensor) {
            cal = &fork_cal;
        } else if (sensor == &shock_sensor) {
            cal = &shock_cal;
        }
        if (cal == NULL || cal->expanded <= cal->compressed) {
            value = 0;
        } else {
            if (raw > cal->expanded) raw = cal->expanded;
            if (raw < cal->compressed) raw = cal->compressed;
            value = ((uint32_t)(cal->expanded - raw) * ROTARY_SENSOR_MAX) /
                    (cal->expanded - cal->compressed);
        }
    }
    return value;
}

// Calibration: Record reading when fully extended.
static void rotational_sensor_calibrate_expanded(struct sensor *sensor) {
    sensor->baseline = 0xFFFF;
    if (sensor->check_availability(sensor)) {
        uint16_t reading = evomini_read_distance(sensor->comm.i2c.instance);
        sensor->baseline = reading;
        if (sensor == &fork_sensor) {
            fork_cal.expanded = reading;
        } else if (sensor == &shock_sensor) {
            shock_cal.expanded = reading;
        }
    }
}

// Calibration: Record reading when fully compressed.
static void rotational_sensor_calibrate_compressed(struct sensor *sensor) {
    sensor->baseline = 0xFFFF;
    if (sensor->check_availability(sensor)) {
        uint16_t reading = evomini_read_distance(sensor->comm.i2c.instance);
        if (sensor == &fork_sensor) {
            fork_cal.compressed = reading;
        } else if (sensor == &shock_sensor) {
            shock_cal.compressed = reading;
        }
    }
}

// The sensor instances (defined elsewhere, see sensor.h or below in this file)
#ifndef FORK_LINEAR
struct sensor fork_sensor = {
    .comm.i2c = {FORK_I2C, FORK_PIN_SCL, FORK_PIN_SDA},
    .init = rotational_sensor_init,
    .check_availability = rotational_sensor_check_availability,
    .start = rotational_sensor_start,
    .calibrate_expanded = rotational_sensor_calibrate_expanded,
    .calibrate_compressed = rotational_sensor_calibrate_compressed,
    .measure = rotational_sensor_measure,
};
#endif

#ifndef SHOCK_LINEAR
struct sensor shock_sensor = {
    .comm.i2c = {SHOCK_I2C, SHOCK_PIN_SCL, SHOCK_PIN_SDA},
    .init = rotational_sensor_init,
    .check_availability = rotational_sensor_check_availability,
    .start = rotational_sensor_start,
    .calibrate_expanded = rotational_sensor_calibrate_expanded,
    .calibrate_compressed = rotational_sensor_calibrate_compressed,
    .measure = rotational_sensor_measure,
};
#endif
