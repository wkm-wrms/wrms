#pragma once
#include <stdbool.h>

/**
 * @brief Start the captive portal HTTP server and DNS hijack server.
 *
 * Serves the configuration web page on port 80 inside the AP network
 * (192.168.4.1). All DNS queries are answered with 192.168.4.1 so that
 * phones open the portal automatically.
 *
 * This function must be called after wifi_manager_init() has raised the AP
 * interface.
 */
void captive_portal_start(void);

/**
 * @brief Stop the captive portal HTTP and DNS servers.
 *
 * Called once Wi-Fi association succeeds and the device transitions to the
 * CONNECTED state.
 */
void captive_portal_stop(void);

/**
 * @brief Return the last diagnostic error code produced during a portal
 *        connection attempt, or NULL if no error occurred.
 *
 * Possible values: "WIFI_NOT_FOUND", "WIFI_AUTH_FAILED",
 *                  "API_UNREACHABLE", "API_INVALID_RESPONSE", "NTP_FAILED"
 */
const char *captive_portal_last_error(void);

/**
 * @brief Set the last diagnostic error code.
 *
 * Called internally by the portal form handler.
 */
void captive_portal_set_error(const char *err);

/**
 * @brief Return true once handle_connect has successfully completed the full
 *        setup sequence (WiFi + API validation + NTP sync + NVS save).
 *
 * Cleared to false on every call to captive_portal_start() so that the flag
 * is fresh for the next configuration attempt.
 */
bool captive_portal_is_configured(void);
