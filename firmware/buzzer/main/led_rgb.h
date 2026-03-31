#pragma once
#include <stdbool.h>

/*
 * LED backend selection.
 *
 * LED_USE_ONBOARD_SINGLE = 1  — single onboard LED (plain GPIO, active HIGH).
 *                               ESP32-C3 DevKitC-1: blue LED on GPIO8.
 *                               States encoded as blink patterns:
 *                                 CONNECTED    — LED on (solid)
 *                                 DISCONNECTED — fast blink (200 ms on/off)
 *                                 API down     — slow blink (800 ms on/off)
 *
 * LED_USE_ONBOARD_SINGLE = 0  — external common-cathode RGB LED on
 *                               GPIO6 (R), GPIO7 (G), GPIO8 (B), each via
 *                               a 100 Ω resistor. See BUZZER.md section 2.3.
 */
#define LED_USE_ONBOARD_SINGLE  1

/* ---- GPIO assignments ---------------------------------------------------- */
#define LED_ONBOARD_GPIO  8   /* onboard LED on ESP32-C3 DevKitC-1 */

#define LED_RED_GPIO    6     /* external RGB only */
#define LED_GREEN_GPIO  7
#define LED_BLUE_GPIO   8

typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_RED,           /* disconnected / Wi-Fi dropped  → fast blink in single-LED mode */
    LED_STATE_GREEN,         /* connected, API reachable      → solid in single-LED mode */
    LED_STATE_YELLOW,        /* Wi-Fi OK but API unreachable  → slow blink in single-LED mode */
} led_state_t;

void led_rgb_init(void);
void led_rgb_set(led_state_t state);
void led_rgb_flash(void);
