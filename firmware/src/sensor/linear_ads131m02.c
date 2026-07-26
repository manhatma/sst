#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/irq.h"
#include "hardware/spi.h"
#include "hardware/structs/spi.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"

#include "sensor.h"
#include "../fw/hardware_config.h"
#include "../fw/sst.h"

#ifdef ADS131_SENSORS

#define ADS131_SPI_BAUD_RATE       8000000u
#define ADS131_FRAME_SIZE          12u
#define ADS131_SAMPLE_RATE         1000u
#define ADS131_TRAVEL_SCALE        27548u

#define ADS131_REG_ID              0x00u
#define ADS131_REG_STATUS          0x01u
#define ADS131_REG_MODE            0x02u
#define ADS131_REG_CLOCK           0x03u
#define ADS131_REG_GAIN            0x04u
#define ADS131_REG_CFG             0x06u

#define ADS131_MODE_VALUE          0x0510u
#define ADS131_CLOCK_VALUE         0x0316u
#define ADS131_GAIN_VALUE          0x0000u
#define ADS131_CFG_VALUE           0x0600u

#define ADS131_CMD_NULL            0x0000u
#define ADS131_CMD_STANDBY         0x0022u
#define ADS131_CMD_WAKEUP          0x0033u
#define ADS131_CMD_RREG            0xa000u
#define ADS131_CMD_WREG            0x6000u
#define ADS131_RREG_ADDRESS(addr)  ((uint16_t)(addr) << 7)
#define ADS131_WREG_RESPONSE       0x4000u

extern struct sensor fork_sensor;
extern struct sensor shock_sensor;

static bool ads131_initialized;
static bool ads131_awake;
static volatile bool dma_active;
static int dma_tx_channel = -1;
static int dma_rx_channel = -1;
static dma_channel_config dma_tx_config;
static dma_channel_config dma_rx_config;

static const uint8_t dma_tx_buffer[ADS131_FRAME_SIZE] = {0};
static uint8_t dma_rx_buffer[ADS131_FRAME_SIZE];

static volatile uint16_t latest_fork_16;
static volatile uint16_t latest_shock_16;
static volatile bool recording_active;
static struct record * volatile *record_buffer;
static volatile uint16_t *record_count;
static uint16_t record_buffer_size;

static void ads131_dma_irq_handler(void);
static void ads131_drdy_irq_handler(void);

static void frame_set_word(uint8_t *frame, uint index, uint16_t word) {
    uint offset = index * 3u;
    frame[offset] = (uint8_t)(word >> 8);
    frame[offset + 1u] = (uint8_t)word;
    frame[offset + 2u] = 0;
}

static uint16_t frame_get_word(const uint8_t *frame, uint index) {
    uint offset = index * 3u;
    return (uint16_t)(((uint16_t)frame[offset] << 8) | frame[offset + 1u]);
}

static bool ads131_transfer_frame(const uint8_t *tx, uint8_t *rx) {
    gpio_put(ADS131_PIN_CS, 0);
    int transferred = spi_write_read_blocking(ADS131_SPI, tx, rx, ADS131_FRAME_SIZE);
    gpio_put(ADS131_PIN_CS, 1);
    return transferred == ADS131_FRAME_SIZE;
}

static bool ads131_command(uint16_t command) {
    uint8_t tx[ADS131_FRAME_SIZE] = {0};
    uint8_t rx[ADS131_FRAME_SIZE];
    frame_set_word(tx, 0, command);
    return ads131_transfer_frame(tx, rx);
}

static bool ads131_read_register(uint8_t address, uint16_t *value) {
    uint8_t command_frame[ADS131_FRAME_SIZE] = {0};
    uint8_t response_frame[ADS131_FRAME_SIZE];
    uint8_t null_frame[ADS131_FRAME_SIZE] = {0};

    frame_set_word(command_frame, 0,
                   ADS131_CMD_RREG | ADS131_RREG_ADDRESS(address));
    if (!ads131_transfer_frame(command_frame, response_frame) ||
        !ads131_transfer_frame(null_frame, response_frame)) {
        return false;
    }

    *value = frame_get_word(response_frame, 0);
    return true;
}

static bool ads131_write_register(uint8_t address, uint16_t value) {
    uint8_t command_frame[ADS131_FRAME_SIZE] = {0};
    uint8_t response_frame[ADS131_FRAME_SIZE];
    uint8_t null_frame[ADS131_FRAME_SIZE] = {0};
    uint16_t command = ADS131_CMD_WREG | ADS131_RREG_ADDRESS(address);

    frame_set_word(command_frame, 0, command);
    frame_set_word(command_frame, 1, value);
    if (!ads131_transfer_frame(command_frame, response_frame) ||
        !ads131_transfer_frame(null_frame, response_frame)) {
        return false;
    }

    return frame_get_word(response_frame, 0) ==
           (ADS131_WREG_RESPONSE | ADS131_RREG_ADDRESS(address));
}

static void ads131_reset(void) {
    gpio_put(ADS131_PIN_RESET, 0);
    sleep_us(300);
    gpio_put(ADS131_PIN_RESET, 1);
    sleep_us(5);
}

static int32_t ads131_parse_sample(const uint8_t *sample) {
    int32_t value = ((int32_t)sample[0] << 16) |
                    ((int32_t)sample[1] << 8) |
                    sample[2];
    if (value & 0x00800000) {
        value |= (int32_t)0xff000000;
    }
    return value;
}

static uint16_t ads131_scale_sample(int32_t raw24) {
    if (raw24 <= 0) {
        return 0;
    }

    uint64_t scaled = ((uint64_t)(uint32_t)raw24 * ADS131_TRAVEL_SCALE) >> 23;
    return scaled > 0xfffeu ? 0xfffeu : (uint16_t)scaled;
}

static uint16_t subtract_baseline(uint16_t value, uint16_t baseline) {
    if (value <= baseline) {
        return 0;
    }

    uint32_t travel = (uint32_t)value - baseline;
    return travel > 0xfffeu ? 0xfffeu : (uint16_t)travel;
}

static void ads131_start_dma_frame(void) {
    spi_hw_t *spi_hw = spi_get_hw(ADS131_SPI);

    dma_channel_configure((uint)dma_rx_channel, &dma_rx_config,
                          dma_rx_buffer, &spi_hw->dr,
                          ADS131_FRAME_SIZE, false);
    dma_channel_configure((uint)dma_tx_channel, &dma_tx_config,
                          &spi_hw->dr, dma_tx_buffer,
                          ADS131_FRAME_SIZE, false);

    gpio_put(ADS131_PIN_CS, 0);
    dma_active = true;
    dma_start_channel_mask((1u << dma_rx_channel) | (1u << dma_tx_channel));
}

static void ads131_drdy_irq_handler(void) {
    uint32_t events = gpio_get_irq_event_mask(ADS131_PIN_DRDY);
    if (!(events & GPIO_IRQ_EDGE_FALL)) {
        return;
    }

    gpio_acknowledge_irq(ADS131_PIN_DRDY, GPIO_IRQ_EDGE_FALL);
    if (ads131_awake && !dma_active) {
        ads131_start_dma_frame();
    }
}

static void ads131_dma_irq_handler(void) {
    uint32_t channel_mask = 1u << dma_rx_channel;
    if (!(dma_hw->ints0 & channel_mask)) {
        return;
    }

    dma_hw->ints0 = channel_mask;
    gpio_put(ADS131_PIN_CS, 1);
    dma_active = false;

    latest_fork_16 = ads131_scale_sample(ads131_parse_sample(&dma_rx_buffer[3]));
    latest_shock_16 = ads131_scale_sample(ads131_parse_sample(&dma_rx_buffer[6]));

    if (!recording_active || record_buffer == NULL || record_count == NULL) {
        return;
    }

    uint16_t index = *record_count;
    struct record *buffer = *record_buffer;
    buffer[index].fork_angle = subtract_baseline(latest_fork_16,
                                                  fork_sensor.baseline);
    buffer[index].shock_angle = subtract_baseline(latest_shock_16,
                                                   shock_sensor.baseline);
    index++;
    *record_count = index;

    if (index == record_buffer_size) {
        *record_count = 0;
        multicore_fifo_push_blocking(DUMP);
        multicore_fifo_push_blocking((uintptr_t)buffer);
        *record_buffer = (struct record *)(uintptr_t)multicore_fifo_pop_blocking();
    }
}

static void ads131_pause_sampling(void) {
    gpio_set_irq_enabled(ADS131_PIN_DRDY, GPIO_IRQ_EDGE_FALL, false);
    gpio_acknowledge_irq(ADS131_PIN_DRDY, GPIO_IRQ_EDGE_FALL);
    while (dma_active) {
        tight_loop_contents();
    }
}

static void ads131_resume_sampling(void) {
    gpio_acknowledge_irq(ADS131_PIN_DRDY, GPIO_IRQ_EDGE_FALL);
    if (ads131_awake) {
        gpio_set_irq_enabled(ADS131_PIN_DRDY, GPIO_IRQ_EDGE_FALL, true);
    }
}

static bool ads131_configure(void) {
    uint16_t status;
    if (!ads131_read_register(ADS131_REG_STATUS, &status)) {
        return false;
    }

    return ads131_write_register(ADS131_REG_MODE, ADS131_MODE_VALUE) &&
           ads131_write_register(ADS131_REG_CLOCK, ADS131_CLOCK_VALUE) &&
           ads131_write_register(ADS131_REG_GAIN, ADS131_GAIN_VALUE) &&
           ads131_write_register(ADS131_REG_CFG, ADS131_CFG_VALUE);
}

static void linear_sensor_ads131_init(struct sensor *sensor) {
    if (ads131_initialized) {
        return;
    }

    spi_init(sensor->comm.spi.instance, ADS131_SPI_BAUD_RATE);
    spi_set_format(sensor->comm.spi.instance, 8, SPI_CPOL_0, SPI_CPHA_1,
                   SPI_MSB_FIRST);
    gpio_set_function(ADS131_PIN_SCK, GPIO_FUNC_SPI);
    gpio_set_function(ADS131_PIN_MOSI, GPIO_FUNC_SPI);
    gpio_set_function(ADS131_PIN_MISO, GPIO_FUNC_SPI);

    gpio_init(sensor->comm.spi.cs_gpio);
    gpio_set_dir(sensor->comm.spi.cs_gpio, GPIO_OUT);
    gpio_put(sensor->comm.spi.cs_gpio, 1);

    gpio_init(sensor->comm.spi.reset_gpio);
    gpio_set_dir(sensor->comm.spi.reset_gpio, GPIO_OUT);
    gpio_put(sensor->comm.spi.reset_gpio, 1);

    gpio_init(sensor->comm.spi.drdy_gpio);
    gpio_set_dir(sensor->comm.spi.drdy_gpio, GPIO_IN);

    ads131_reset();
    bool configured = ads131_configure();

    dma_tx_channel = dma_claim_unused_channel(true);
    dma_rx_channel = dma_claim_unused_channel(true);

    dma_tx_config = dma_channel_get_default_config((uint)dma_tx_channel);
    channel_config_set_transfer_data_size(&dma_tx_config, DMA_SIZE_8);
    channel_config_set_read_increment(&dma_tx_config, true);
    channel_config_set_write_increment(&dma_tx_config, false);
    channel_config_set_dreq(&dma_tx_config, spi_get_dreq(ADS131_SPI, true));

    dma_rx_config = dma_channel_get_default_config((uint)dma_rx_channel);
    channel_config_set_transfer_data_size(&dma_rx_config, DMA_SIZE_8);
    channel_config_set_read_increment(&dma_rx_config, false);
    channel_config_set_write_increment(&dma_rx_config, true);
    channel_config_set_dreq(&dma_rx_config, spi_get_dreq(ADS131_SPI, false));

    dma_channel_set_irq0_enabled((uint)dma_rx_channel, true);
    irq_set_exclusive_handler(DMA_IRQ_0, ads131_dma_irq_handler);
    irq_set_enabled(DMA_IRQ_0, true);

    gpio_add_raw_irq_handler(sensor->comm.spi.drdy_gpio,
                             ads131_drdy_irq_handler);
    irq_set_enabled(IO_IRQ_BANK0, true);

    ads131_initialized = true;
    ads131_awake = configured;
    fork_sensor.available = configured;
    shock_sensor.available = configured;
    ads131_resume_sampling();
}

static bool linear_sensor_ads131_check_availability(struct sensor *sensor) {
    if (!ads131_initialized || !ads131_awake) {
        sensor->available = false;
        return false;
    }

    uint16_t id;
    ads131_pause_sampling();
    bool available = ads131_read_register(ADS131_REG_ID, &id) &&
                     (((id >> 8) & 0x0fu) == 2u);
    ads131_resume_sampling();
    sensor->available = available;
    return available;
}

static bool linear_sensor_ads131_start(struct sensor *sensor, uint16_t baseline,
                                       bool inverted) {
    if (!sensor->check_availability(sensor)) {
        return false;
    }

    sensor->baseline = baseline;
    sensor->inverted = inverted;
    return true;
}

static void linear_sensor_ads131_calibrate_expanded(struct sensor *sensor) {
    sensor->baseline = 0xffff;
    if (!sensor->check_availability(sensor)) {
        return;
    }

    sensor->baseline = sensor == &fork_sensor ? latest_fork_16 : latest_shock_16;
}

static void linear_sensor_ads131_calibrate_compressed(struct sensor *sensor) {
    sensor->inverted = false;
}

static uint16_t linear_sensor_ads131_measure(struct sensor *sensor) {
    if (!sensor->available) {
        return 0xffff;
    }

    uint16_t latest = sensor == &fork_sensor ? latest_fork_16 : latest_shock_16;
    return subtract_baseline(latest, sensor->baseline);
}

void ads131_begin(struct record * volatile *active_buffer_ptr,
                  volatile uint16_t *count_ptr, uint16_t buffer_size) {
    ads131_pause_sampling();
    record_buffer = active_buffer_ptr;
    record_count = count_ptr;
    record_buffer_size = buffer_size;
    recording_active = true;
    ads131_resume_sampling();
}

void ads131_end(void) {
    ads131_pause_sampling();
    recording_active = false;
    record_buffer = NULL;
    record_count = NULL;
    ads131_resume_sampling();
}

uint16_t ads131_sample_rate(void) {
    return ADS131_SAMPLE_RATE;
}

void ads131_standby(void) {
    if (!ads131_initialized || !ads131_awake) {
        return;
    }

    ads131_pause_sampling();
    ads131_command(ADS131_CMD_STANDBY);
    ads131_awake = false;
}

void ads131_wake(void) {
    if (!ads131_initialized || ads131_awake) {
        return;
    }

    ads131_command(ADS131_CMD_WAKEUP);
    ads131_awake = true;
    ads131_resume_sampling();
}

struct sensor fork_sensor = {
    .comm.spi = {ADS131_SPI, ADS131_PIN_CS, ADS131_PIN_DRDY,
                 ADS131_PIN_RESET},
    .init = linear_sensor_ads131_init,
    .check_availability = linear_sensor_ads131_check_availability,
    .start = linear_sensor_ads131_start,
    .calibrate_expanded = linear_sensor_ads131_calibrate_expanded,
    .calibrate_compressed = linear_sensor_ads131_calibrate_compressed,
    .measure = linear_sensor_ads131_measure,
};

struct sensor shock_sensor = {
    .comm.spi = {ADS131_SPI, ADS131_PIN_CS, ADS131_PIN_DRDY,
                 ADS131_PIN_RESET},
    .init = linear_sensor_ads131_init,
    .check_availability = linear_sensor_ads131_check_availability,
    .start = linear_sensor_ads131_start,
    .calibrate_expanded = linear_sensor_ads131_calibrate_expanded,
    .calibrate_compressed = linear_sensor_ads131_calibrate_compressed,
    .measure = linear_sensor_ads131_measure,
};

#endif
