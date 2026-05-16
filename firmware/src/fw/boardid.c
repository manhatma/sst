#include "boardid.h"

#include <string.h>
#include <stdio.h>

#include "ff.h"
#include "pico/unique_id.h"

static char current_suffix[BOARDID_TEMPLATE_NAME_LENGTH] = {0};
static char current_id[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1] = {0};

static void load_current_id(void) {
    current_id[0] = '\0';
    FIL f;
    if (f_open(&f, "BOARDID", FA_OPEN_EXISTING | FA_READ) != FR_OK) return;
    UINT br;
    f_read(&f, current_id, 2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES, &br);
    current_id[br] = '\0';
    f_close(&f);
}

void boardid_scan(struct boardid_menu *m) {
    m->count = 0;
    m->selected = 0;
    m->top = 0;

    DIR dj;
    FILINFO fno;
    FRESULT fr = f_findfirst(&dj, &fno, "", "BOARDID.*");
    while (fr == FR_OK && fno.fname[0] && m->count < BOARDID_MAX_TEMPLATES) {
        const char *ext = strchr(fno.fname, '.');
        if (ext) {
            // Skip reserved marker file BOARDID.CUR used for persistence.
            if (strcmp(ext, ".CUR") != 0) {
                // Store suffix without the leading dot — the dot is only a
                // filename separator, not part of the displayed/persisted name.
                strncpy(m->templates[m->count], ext + 1, BOARDID_TEMPLATE_NAME_LENGTH - 1);
                m->templates[m->count][BOARDID_TEMPLATE_NAME_LENGTH - 1] = '\0';
                m->count++;
            }
        }
        fr = f_findnext(&dj, &fno);
    }
    f_closedir(&dj);
}

bool boardid_templates_available(void) {
    DIR dj;
    FILINFO fno;
    bool found = false;
    FRESULT fr = f_findfirst(&dj, &fno, "", "BOARDID.*");
    while (fr == FR_OK && fno.fname[0]) {
        const char *ext = strchr(fno.fname, '.');
        if (ext && strcmp(ext, ".CUR") != 0) {
            found = true;
            break;
        }
        fr = f_findnext(&dj, &fno);
    }
    f_closedir(&dj);
    return found;
}

void boardid_render(ssd1306_t *disp, struct boardid_menu *m) {
    ssd1306_clear(disp);
    ssd1306_draw_string(disp, 0, 0, 2, "BOARDID");

    int y[BOARDID_PAGE_SIZE] = {24, 34, 44};
    for (int i = 0; i < BOARDID_PAGE_SIZE; i++) {
        int idx = m->top + i;
        if (idx >= m->count) break;
        char line[BOARDID_TEMPLATE_NAME_LENGTH + 3];
        snprintf(line, sizeof(line), "%s %s",
                 idx == m->selected ? ">" : " ",
                 m->templates[idx]);
        ssd1306_draw_string(disp, 0, y[i], 1, line);
    }

    ssd1306_draw_string(disp, 0, 56, 1, "L:next R:ok");
    ssd1306_show(disp);
}

int boardid_apply(const char *suffix) {
    if (!suffix || !suffix[0]) return -1;

    // suffix is stored without the leading dot; rebuild the filename.
    char src[BOARDID_TEMPLATE_NAME_LENGTH + 8];
    if (suffix[0] == '.') {
        snprintf(src, sizeof(src), "BOARDID%s", suffix);
    } else {
        snprintf(src, sizeof(src), "BOARDID.%s", suffix);
    }

    FIL fi, fo;
    FRESULT fr = f_open(&fi, src, FA_OPEN_EXISTING | FA_READ);
    if (fr != FR_OK) return -1;

    fr = f_open(&fo, "BOARDID", FA_CREATE_ALWAYS | FA_WRITE);
    if (fr != FR_OK) {
        f_close(&fi);
        return -1;
    }

    char buf[64];
    UINT br, bw;
    while (f_read(&fi, buf, sizeof(buf), &br) == FR_OK && br > 0) {
        f_write(&fo, buf, br, &bw);
    }
    f_close(&fi);
    f_close(&fo);

    // Persist suffix (without leading dot) to BOARDID.CUR for IDLE-screen display.
    const char *suf = suffix[0] == '.' ? suffix + 1 : suffix;
    FIL fc;
    fr = f_open(&fc, "BOARDID.CUR", FA_CREATE_ALWAYS | FA_WRITE);
    if (fr == FR_OK) {
        UINT cw;
        f_write(&fc, suf, strlen(suf), &cw);
        f_close(&fc);
    }

    strncpy(current_suffix, suf, BOARDID_TEMPLATE_NAME_LENGTH - 1);
    current_suffix[BOARDID_TEMPLATE_NAME_LENGTH - 1] = '\0';
    load_current_id();
    return 0;
}

const char *boardid_current_suffix(void) {
    return current_suffix;
}

const char *boardid_current_id(void) {
    return current_id;
}

void boardid_load_current_suffix(void) {
    FIL f;
    FRESULT fr = f_open(&f, "BOARDID.CUR", FA_OPEN_EXISTING | FA_READ);
    if (fr != FR_OK) {
        current_suffix[0] = '\0';
        return;
    }
    UINT br;
    f_read(&f, current_suffix, BOARDID_TEMPLATE_NAME_LENGTH - 1, &br);
    current_suffix[br] = '\0';
    for (UINT i = 0; i < br; i++) {
        if (current_suffix[i] == '\n' || current_suffix[i] == '\r') {
            current_suffix[i] = '\0';
            break;
        }
    }
    // Tolerate older BOARDID.CUR files that were written with the leading dot.
    if (current_suffix[0] == '.') {
        memmove(current_suffix, current_suffix + 1, strlen(current_suffix));
    }
    f_close(&f);
    load_current_id();
}
