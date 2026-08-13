#include <hardware/i2c.h>
#include <stdbool.h>
#include <stdint.h>

union port {
    i2c_inst_t *i2c;
    uint gpio;
};

struct i2c_comm {
    i2c_inst_t *instance;
    uint scl_gpio;
    uint sda_gpio;
};

struct adc_comm {
    uint adc_num;
    uint gpio;
};

union comm {
    struct i2c_comm i2c;
    struct adc_comm adc;
};

struct sensor {
    union comm comm;
    volatile bool available;
    uint16_t baseline;
    bool inverted;
    uint16_t last_measurement;
    void (*init)(struct sensor *sensor);
    bool (*check_availability)(struct sensor *sensor);
    bool (*start)(struct sensor *sensor, uint16_t baseline, bool inverted);
    void (*calibrate_expanded)(struct sensor *sensor);
    void (*calibrate_compressed)(struct sensor *sensor);
    uint16_t (*measure)(struct sensor *sensor);
    // These operations are optional so sensors that use the default behavior
    // do not all need changes just to provide identical implementations.
    uint16_t (*sample_at)(struct sensor *sensor, uint32_t t_k_us);
    bool (*ready)(struct sensor *sensor);
    void (*stop)(struct sensor *sensor);
};

static inline uint16_t sensor_sample_at(struct sensor *sensor,
                                        uint32_t t_k_us) {
    return sensor->sample_at ? sensor->sample_at(sensor, t_k_us)
                             : sensor->measure(sensor);
}

static inline bool sensor_ready(struct sensor *sensor) {
    return sensor->ready ? sensor->ready(sensor) : true;
}

static inline void sensor_stop(struct sensor *sensor) {
    if (sensor->stop) {
        sensor->stop(sensor);
    }
}
