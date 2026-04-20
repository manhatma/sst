#ifndef _BUZZER_H
#define _BUZZER_H

#include <stdint.h>

#define BUZZER_PIN 7

void buzzer_init(void);
void buzzer_beep(uint32_t freq_hz, uint32_t duration_ms);

void buzzer_sound_confirm(void);   // short ascending double-tone (button confirm)
void buzzer_sound_start(void);     // ascending 3-tone chirp (REC START)
void buzzer_sound_stop(void);      // descending 2-tone (REC STOP)
void buzzer_sound_cal(void);       // single mid-tone (calibration step)
void buzzer_sound_error(void);     // low double-tone (error)
void buzzer_sound_sleep(void);     // falling tone (before sleep)

#endif /* _BUZZER_H */
