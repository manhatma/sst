#include <hardware/i2c.h>
#include <hardware/spi.h>
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

struct spi_comm {
    spi_inst_t *instance;
    uint cs_gpio;
    uint drdy_gpio;
    uint reset_gpio;
};

union comm {
    struct i2c_comm i2c;
    struct adc_comm adc;
    struct spi_comm spi;
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
};

#ifdef ADS131_SENSORS
struct record;
void ads131_begin(struct record * volatile *active_buffer_ptr,
                  volatile uint16_t *count_ptr, uint16_t buffer_size);
void ads131_end(void);
uint16_t ads131_sample_rate(void);
void ads131_standby(void);
void ads131_wake(void);
#endif
