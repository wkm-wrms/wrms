#pragma once

/*
 * GPIO pin used for the active buzzer (HIGH = on).
 * ESP32-C3 assignment: avoids strapping (GPIO2), boot button (GPIO9),
 * USB D-/D+ (GPIO18/19).
 */
#define BUZZER_GPIO 5

/**
 * @brief Alarm type identifiers — must match the string values returned by
 *        the API and defined in BUZZER.md section 5.2.
 */
typedef enum {
    BUZZER_ALARM_PREP_START,
    BUZZER_ALARM_FLIGHT_START,
    BUZZER_ALARM_FLIGHT_WARNING_30,
    BUZZER_ALARM_COUNTDOWN,
    BUZZER_ALARM_FLIGHT_END,
    BUZZER_ALARM_SESSION_END,
    BUZZER_ALARM_UNKNOWN,
} buzzer_alarm_type_t;

/**
 * @brief Convert a type string from the API response (e.g. "FLIGHT_START")
 *        to the corresponding enum value. Returns BUZZER_ALARM_UNKNOWN if
 *        the string is not recognised.
 */
buzzer_alarm_type_t buzzer_alarm_type_from_str(const char *type_str);

/**
 * @brief Initialise the buzzer GPIO pin.
 *
 * Must be called once on startup.
 */
void buzzer_gpio_init(void);

/**
 * @brief Play the pattern associated with the given alarm type.
 *
 * This function is non-blocking: it queues the pattern on a dedicated
 * FreeRTOS task. If a pattern is already playing it is completed first
 * and the new pattern is appended.
 *
 * @param type Alarm type whose pattern to play.
 */
void buzzer_gpio_play(buzzer_alarm_type_t type);

/**
 * @brief Produce a single short error beep (3 × 100 ms).
 *
 * Used by the captive portal on failed connection attempts.
 */
void buzzer_gpio_error_beep(void);
