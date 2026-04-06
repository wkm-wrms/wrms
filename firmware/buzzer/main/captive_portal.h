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
 */
void captive_portal_stop(void);

/**
 * @brief Stop the DNS hijack server only, keeping the HTTP server running.
 *
 * Called after the device transitions to CONNECTED state so that the
 * config page remains accessible at http://192.168.4.1/ for reconfiguration,
 * but aggressive DNS capture is no longer active.
 */
void captive_portal_stop_dns(void);

/**
 * @brief Start the HTTP config server only (no DNS hijack).
 *
 * Used when the device is already connected and just needs to expose the
 * reconfiguration page.  Has no effect if the server is already running.
 */
void captive_portal_start_reconfig(void);

/**
 * @brief Return true if the HTTP config server is currently running.
 */
bool captive_portal_is_running(void);

/**
 * @brief Clear the configured flag after main.c has consumed it.
 */
void captive_portal_clear_configured(void);

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
