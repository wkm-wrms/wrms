#pragma once

/*
 * GPIO pins for the RGB LED (common cathode: HIGH = on).
 * ESP32-C3 assignment: avoids strapping (GPIO2), boot button (GPIO9),
 * USB D-/D+ (GPIO18/19), and buzzer (GPIO5).
 */
#define LED_RED_GPIO   6
#define LED_GREEN_GPIO 7
#define LED_BLUE_GPIO  8

typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_RED,           /* disconnected / Wi-Fi dropped */
    LED_STATE_GREEN,         /* connected, API reachable */
    LED_STATE_YELLOW,        /* connected to Wi-Fi but API unreachable */
} led_state_t;

/**
 * @brief Initialise all three LED GPIO pins as outputs.
 */
void led_rgb_init(void);

/**
 * @brief Set the steady-state LED colour.
 *
 * Any ongoing flash is cancelled and the LED immediately transitions to the
 * new state.
 *
 * @param state Desired colour.
 */
void led_rgb_set(led_state_t state);

/**
 * @brief Perform a single 100 ms off→on→off flash of the current colour.
 *
 * Called by the alarm scheduler when an alarm fires. Non-blocking (handled
 * by the LED task).
 */
void led_rgb_flash(void);
