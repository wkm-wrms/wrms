#pragma once

#include <stdbool.h>
#include "api_client.h"

/**
 * @brief Initialise the alarm scheduler.
 *
 * Must be called once before alarm_scheduler_update() or alarm_scheduler_tick().
 */
void alarm_scheduler_init(void);

/**
 * @brief Replace the current alarm queue with fresh alarms from an API response.
 *
 * Alarms whose IDs were already fired in the current session are silently
 * dropped. Alarms with fire_at < now are also dropped.
 *
 * @param response Pointer to a successful api_response_t.
 */
void alarm_scheduler_update(const api_response_t *response);

/**
 * @brief Check whether any queued alarm is due and fire it.
 *
 * Should be called frequently (e.g. every 100 ms) from the main loop.
 * When an alarm fires, buzzer_gpio_play() and led_rgb_flash() are called
 * automatically.
 */
void alarm_scheduler_tick(void);

/**
 * @brief Clear the set of already-fired alarm IDs (call on session change:
 *        transition from active phase back to IDLE).
 */
void alarm_scheduler_reset_session(void);
