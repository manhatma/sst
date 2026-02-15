#ifndef EVOMINI_H
#define EVOMINI_H

#ifdef __cplusplus
extern "C" {
#endif

#include "sensor.h"

/**
 * @brief Initialize the Evo Mini sensor.
 *
 * Sets up the sensor and I2C bus if necessary.
 *
 * @param s Pointer to the sensor structure.
 */
void evomini_sensor_init(struct sensor *s);

/**
 * @brief Check sensor availability.
 *
 * Triggers a measurement to verify sensor operation.
 *
 * @param s Pointer to the sensor structure.
 * @return _Bool true if available, false otherwise.
 */
_Bool evomini_sensor_check_availability(struct sensor *s);

/**
 * @brief Start sensor operation.
 *
 * @param s Pointer to the sensor structure.
 * @param param A parameter for sensor startup (unused).
 * @param flag A flag for sensor startup (unused).
 * @return _Bool true if sensor started successfully, false otherwise.
 */
_Bool evomini_sensor_start(struct sensor *s, uint16_t param, _Bool flag);

/**
 * @brief Perform expanded calibration.
 *
 * Not implemented for the Evo Mini sensor.
 *
 * @param s Pointer to the sensor structure.
 */
void evomini_sensor_calibrate_expanded(struct sensor *s);

/**
 * @brief Perform compressed calibration.
 *
 * Not implemented for the Evo Mini sensor.
 *
 * @param s Pointer to the sensor structure.
 */
void evomini_sensor_calibrate_compressed(struct sensor *s);

/**
 * @brief Trigger a measurement and return the distance.
 *
 * Operates in short-range, 1px mode and returns an absolute distance in millimetres.
 *
 * @param s Pointer to the sensor structure.
 * @return Measured distance in millimetres, or 0 on error.
 */
uint16_t evomini_sensor_measure(struct sensor *s);

#ifdef __cplusplus
}
#endif

#endif // EVOMINI_H
