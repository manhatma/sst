#ifndef _BOARDID_H
#define _BOARDID_H

#include <stdbool.h>
#include "ssd1306.h"
#include "sst.h"

#define BOARDID_MAX_TEMPLATES 8
#define BOARDID_PAGE_SIZE 3

struct boardid_menu {
    char templates[BOARDID_MAX_TEMPLATES][BOARDID_TEMPLATE_NAME_LENGTH]; // "EXC155" etc., no leading dot
    int count;
    int selected;
    int top;
};

void boardid_scan(struct boardid_menu *m);
void boardid_render(ssd1306_t *disp, struct boardid_menu *m);
int  boardid_apply(const char *suffix); // suffix without leading dot, e.g. "EXC155"
bool boardid_templates_available(void);
const char *boardid_current_suffix(void);
void boardid_load_current_suffix(void);
const char *boardid_current_id(void);

#endif /* _BOARDID_H */
