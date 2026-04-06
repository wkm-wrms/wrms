#pragma once

#include <stdbool.h>
#include <stddef.h>

/**
 * @brief Initialize the Wi-Fi subsystem (AP+STA mode).
 *
 * Loads known networks from NVS and attempts to connect to the first match
 * found in the current scan. If no match is found, the device stays in AP
 * mode and starts the captive portal. Background scanning continues until a
 * known network appears.
 *
 * This function must be called after nvs_config_init().
 */
void wifi_manager_init(void);

/**
 * @brief Return true if the station interface is connected to an AP.
 */
bool wifi_manager_is_connected(void);

/**
 * @brief Attempt to connect to a specific SSID/password pair.
 *
 * Used by the captive portal after the user submits the config form.
 *
 * @param ssid     Null-terminated SSID.
 * @param password Null-terminated password.
 * @return         true on successful association; false otherwise.
 */
bool wifi_manager_connect(const char *ssid, const char *password);

/**
 * @brief Return the current station IP address as a string.
 *        Returns "0.0.0.0" when not connected.
 */
void wifi_manager_get_ip(char *buf, size_t len);

/**
 * @brief Return the AP SSID that was set on wifi_manager_init().
 *
 * Format: "WKM-Buzzer-XXYYZZ" where XXYYZZ are the last 3 bytes of the
 * device's base MAC address in uppercase hex. Unique per device.
 */
const char *wifi_manager_get_ap_ssid(void);

/**
 * @brief Enable or disable automatic STA reconnection on disconnect.
 *
 * Disable while the captive portal is running to avoid background reconnect
 * attempts interfering with the HTTP server and WiFi scan.
 * Re-enable after the portal stops.
 */
void wifi_manager_set_reconnect(bool enabled);
