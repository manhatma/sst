#ifndef _BOARDID_H
#define _BOARDID_H

#include <stdbool.h>
#include "ssd1306.h"
#include "sst.h"

#define BOARDID_MAX_TEMPLATES 8
#define BOARDID_PAGE_SIZE 3

struct boardid_menu {
    char templates[BOARDID_MAX_TEMPLATES][BOARDID_TEMPLATE_NAME_LENGTH]; // ".exc" etc.
    int count;
    int selected;
    int top;
};

void boardid_scan(struct boardid_menu *m);
void boardid_render(ssd1306_t *disp, struct boardid_menu *m);
int  boardid_apply(const char *extension); // extension WITH leading dot, e.g. ".exc"
bool boardid_templates_available(void);
const char *boardid_current_suffix(void);
void boardid_load_current_suffix(void);

#endif /* _BOARDID_H */
