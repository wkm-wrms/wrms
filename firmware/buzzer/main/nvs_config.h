#pragma once

#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

/* Maximum number of remembered Wi-Fi networks stored in NVS. */
#define NVS_MAX_NETWORKS 5

/* Maximum SSID and password lengths (including null terminator). */
#define NVS_SSID_LEN 33
#define NVS_PASS_LEN 65

/* Maximum API URL length (including null terminator). */
#define NVS_URL_LEN 128

/* Maximum POSIX timezone string length (including null terminator). */
#define NVS_TZ_LEN 64

typedef struct {
    char ssid[NVS_SSID_LEN];
    char password[NVS_PASS_LEN];
} wifi_credential_t;

/**
 * @brief Initialize NVS flash. Must be called once on startup before any
 *        other nvs_config function.
 *
 * @return ESP_OK on success; ESP_ERR_NVS_NO_FREE_PAGES or
 *         ESP_ERR_NVS_NEW_VERSION_FOUND if the partition needs erasing
 *         (caller should erase and retry).
 */
esp_err_t nvs_config_init(void);

/**
 * @brief Load all known Wi-Fi credentials from NVS.
 *
 * @param[out] out   Caller-allocated array of at least NVS_MAX_NETWORKS entries.
 * @param[out] count Number of entries written to *out*.
 * @return           ESP_OK, or ESP_ERR_NVS_NOT_FOUND if no credentials stored yet.
 */
esp_err_t nvs_config_load_networks(wifi_credential_t *out, int *count);

/**
 * @brief Append a Wi-Fi credential to the stored list (duplicate SSIDs are
 *        updated in place). The list is capped at NVS_MAX_NETWORKS entries;
 *        the oldest entry is evicted when the cap is reached.
 *
 * @param ssid     Null-terminated SSID string.
 * @param password Null-terminated password string.
 * @return         ESP_OK on success.
 */
esp_err_t nvs_config_save_network(const char *ssid, const char *password);

/**
 * @brief Read the API endpoint URL from NVS.
 *
 * @param[out] url     Output buffer.
 * @param[in]  buf_len Size of the output buffer.
 * @return             ESP_OK, or ESP_ERR_NVS_NOT_FOUND.
 */
esp_err_t nvs_config_get_api_url(char *url, size_t buf_len);

/**
 * @brief Persist the API endpoint URL in NVS.
 */
esp_err_t nvs_config_set_api_url(const char *url);

/**
 * @brief Read the POSIX timezone string from NVS.
 */
esp_err_t nvs_config_get_timezone(char *tz, size_t buf_len);

/**
 * @brief Persist the POSIX timezone string in NVS.
 */
esp_err_t nvs_config_set_timezone(const char *tz);

/**
 * @brief Erase all saved Wi-Fi credentials from NVS.
 */
esp_err_t nvs_config_clear_networks(void);
