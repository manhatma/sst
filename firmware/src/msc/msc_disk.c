/* 
 * The MIT License (MIT)
 *
 * Copyright (c) 2019 Ha Thach (tinyusb.org)
 * Copyright (c) 2022 Tamás Szakály (sghctoma)
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 *
 */

#include "tusb.h"
#include "hardware/watchdog.h"

#include "hw_config.h"
#include "sd_card.h"

#if CFG_TUD_MSC

static const uint16_t BLOCK_SIZE = 512; // hardcoded in FatFs_SPI/sd_driver/sd_card.c@232
static sd_card_t *sd = NULL;
static bool ejected = false;

// Hang-detection phase codes, see MSC_PHASE_* in main.c. scratch[4] names
// the blocking call in flight; 2 is tud_task(), the caller of these callbacks.
#define MSC_PHASE_TUD      2
#define MSC_PHASE_SD_INIT  3
#define MSC_PHASE_SD_READ  4
#define MSC_PHASE_SD_WRITE 5

// Lazily (re)initialize the card. init() short-circuits when the card is
// already up and otherwise runs the full init sequence again, so a card left
// confused by a mid-transfer MCU reset recovers on the host's next poll.
static bool sd_ready(void)
{
    if (sd == NULL) {
        sd_init_driver();
        sd = sd_get_by_num(0);
        if (sd == NULL) {
            return false;
        }
    }
    watchdog_hw->scratch[4] = MSC_PHASE_SD_INIT;
    watchdog_update();
    bool ready = !(sd->init(sd) & (STA_NOINIT | STA_NODISK));
    watchdog_hw->scratch[4] = MSC_PHASE_TUD;
    return ready;
}

// Invoked when received SCSI_CMD_INQUIRY
// Application fill vendor id, product id and revision with string up to 8, 16, 4 characters respectively
void tud_msc_inquiry_cb(uint8_t lun, uint8_t vendor_id[8], uint8_t product_id[16], uint8_t product_rev[4])
{
    (void) lun;

    const char vid[] = "sghctoma";
    const char pid[] = "Sufni Suspension";
    const char rev[] = "0.1";

    memcpy(vendor_id  , vid, strlen(vid));
    memcpy(product_id , pid, strlen(pid));
    memcpy(product_rev, rev, strlen(rev));
}

// Invoked when received Test Unit Ready command.
// return true allowing host to read/write this LUN e.g SD card inserted
bool tud_msc_test_unit_ready_cb(uint8_t lun)
{
    (void) lun;

    if (ejected || !sd_ready()) {
        tud_msc_set_sense(lun, SCSI_SENSE_NOT_READY, 0x3a, 0x00);
        return false;
    }

    return true;
}

// Invoked when received SCSI_CMD_READ_CAPACITY_10 and SCSI_CMD_READ_FORMAT_CAPACITY to determine the disk size
// Application update block count and block size
void tud_msc_capacity_cb(uint8_t lun, uint32_t* block_count, uint16_t* block_size)
{
    (void) lun;

    *block_count = sd_ready() ? sd->get_num_sectors(sd) : 0;
    *block_size  = BLOCK_SIZE;
}

// Invoked when received Start Stop Unit command
// - Start = 0 : stopped power mode, if load_eject = 1 : unload disk storage
// - Start = 1 : active mode, if load_eject = 1 : load disk storage
bool tud_msc_start_stop_cb(uint8_t lun, uint8_t power_condition, bool start, bool load_eject)
{
    (void) lun;
    (void) power_condition;

    if ( load_eject ) {
        if (start) {
            // NB: init() returns a DSTATUS (0 = ready) — it must not be
            // returned as a bool, that would report success exactly on failure.
            return sd_ready();
        } else {
            // unload disk storage
            // XXX: not sure if this needs more handling...
            ejected = true;
        }
    }

    return true;
}

// Invoked when received SCSI READ10 command
// - Address = lba * BLOCK_SIZE + offset
//   - offset is only needed if CFG_TUD_MSC_EP_BUFSIZE is smaller than BLOCK_SIZE.
//
// - Application fill the buffer (up to bufsize) with address contents and return number of read byte. If
//   - read < bufsize : These bytes are transferred first and callback invoked again for remaining data.
//
//   - read == 0      : Indicate application is not ready yet e.g disk I/O busy.
//                      Callback invoked again with the same parameters later on.
//
//   - read < 0       : Indicate application error e.g invalid address. This request will be STALLed
//                      and return failed status in command status wrapper phase.
int32_t tud_msc_read10_cb(uint8_t lun, uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize)
{
    (void) lun;
    (void) offset; // ignored because CFG_TUD_MSC_EP_BUFSIZE == BLOCK_SIZE

    if (!sd_ready()) {
        tud_msc_set_sense(lun, SCSI_SENSE_NOT_READY, 0x3a, 0x00);
        return -1;
    }

    // bufsize is always a whole number of blocks: transfers are sector-sized
    // and TinyUSB chunks them by CFG_TUD_MSC_EP_BUFSIZE == BLOCK_SIZE.
    // The (positive) block_dev_err_t codes must not be returned here — TinyUSB
    // treats any positive return as "bytes transferred" and would hand the
    // host garbage sectors; errors have to take the -1 STALL path.
    watchdog_hw->scratch[4] = MSC_PHASE_SD_READ;
    watchdog_update();
    int rc = sd->read_blocks(sd, buffer, lba, bufsize / BLOCK_SIZE);
    watchdog_hw->scratch[4] = MSC_PHASE_TUD;
    if (rc != SD_BLOCK_DEVICE_ERROR_NONE) {
        tud_msc_set_sense(lun, SCSI_SENSE_MEDIUM_ERROR, 0x11, 0x00); // unrecovered read error
        return -1;
    }

    return (int32_t) bufsize;
}

// Invoked to check if device is writable as part of SCSI WRITE10
bool tud_msc_is_writable_cb (uint8_t lun)
{
    return true;
}

// Invoked when received SCSI WRITE10 command
// - Address = lba * BLOCK_SIZE + offset
//   - offset is only needed if CFG_TUD_MSC_EP_BUFSIZE is smaller than BLOCK_SIZE.
//
// - Application write data from buffer to address contents (up to bufsize) and return number of written byte. If
//   - write < bufsize : callback invoked again with remaining data later on.
//
//   - write == 0      : Indicate application is not ready yet e.g disk I/O busy.
//                       Callback invoked again with the same parameters later on.
//
//   - write < 0       : Indicate application error e.g invalid address. This request will be STALLed
//                       and return failed status in command status wrapper phase.
int32_t tud_msc_write10_cb(uint8_t lun, uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize)
{
    (void) lun;
    (void) offset; // ignored because CFG_TUD_MSC_EP_BUFSIZE == BLOCK_SIZE

    if (!sd_ready()) {
        tud_msc_set_sense(lun, SCSI_SENSE_NOT_READY, 0x3a, 0x00);
        return -1;
    }

    // See tud_msc_read10_cb: positive SD error codes would be misread as a
    // byte count and silently corrupt the write.
    watchdog_hw->scratch[4] = MSC_PHASE_SD_WRITE;
    watchdog_update();
    int rc = sd->write_blocks(sd, buffer, lba, bufsize / BLOCK_SIZE);
    watchdog_hw->scratch[4] = MSC_PHASE_TUD;
    if (rc != SD_BLOCK_DEVICE_ERROR_NONE) {
        tud_msc_set_sense(lun, SCSI_SENSE_MEDIUM_ERROR, 0x0c, 0x00); // write error
        return -1;
    }

    return (int32_t) bufsize;
}

// Callback invoked when received an SCSI command not in built-in list below
// - READ_CAPACITY10, READ_FORMAT_CAPACITY, INQUIRY, MODE_SENSE6, REQUEST_SENSE
// - READ10 and WRITE10 has their own callbacks
int32_t tud_msc_scsi_cb (uint8_t lun, uint8_t const scsi_cmd[16], void* buffer, uint16_t bufsize)
{
    // read10 & write10 has their own callback and MUST not be handled here

    void const* response = NULL;
    int32_t resplen = 0;

    // most scsi handled is input
    bool in_xfer = true;

    switch (scsi_cmd[0])
    {
        case SCSI_CMD_PREVENT_ALLOW_MEDIUM_REMOVAL:
            // Host is about to read/write etc ... better not to disconnect disk
            resplen = 0;
            break;

        case 0x35: // SYNCHRONIZE CACHE(10)
            // SD writes complete synchronously in write10_cb, nothing to flush.
            // Answering success avoids a failed-status/STALL round trip that
            // macOS follows with endpoint halt clears.
            resplen = 0;
            break;

        default:
            // Set Sense = Invalid Command Operation
            tud_msc_set_sense(lun, SCSI_SENSE_ILLEGAL_REQUEST, 0x20, 0x00);

            // negative means error -> tinyusb could stall and/or response with failed status
            resplen = -1;
            break;
    }

    // return resplen must not larger than bufsize
    if ( resplen > bufsize ) resplen = bufsize;

    if ( response && (resplen > 0) ) {
        if(in_xfer) {
            memcpy(buffer, response, resplen);
        } else {
            // SCSI output
        }
    }

    return resplen;
}

#endif
