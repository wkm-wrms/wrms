#include "nvs_config.h"

#include <string.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

#define TAG "nvs_config"

/* NVS namespace used for all buzzer configuration. */
#define NVS_NAMESPACE "buzzer"

/* NVS keys */
#define KEY_NET_COUNT  "net_count"   /* uint8: number of stored networks */
#define KEY_NET_SSID   "ssid_%d"     /* string: SSID for network index i */
#define KEY_NET_PASS   "pass_%d"     /* string: password for network index i */
#define KEY_API_URL    "api_url"
#define KEY_TIMEZONE   "timezone"

/* ---- Init ---------------------------------------------------------------- */

esp_err_t nvs_config_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "NVS partition problem (%s), erasing...", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    return err;
}

/* ---- Network list -------------------------------------------------------- */

esp_err_t nvs_config_load_networks(wifi_credential_t *out, int *count)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        *count = 0;
        return ESP_ERR_NVS_NOT_FOUND;
    }
    ESP_ERROR_CHECK(err);

    uint8_t n = 0;
    nvs_get_u8(h, KEY_NET_COUNT, &n);
    if (n > NVS_MAX_NETWORKS) n = NVS_MAX_NETWORKS;

    for (int i = 0; i < n; i++) {
        char key[16];
        size_t len;

        snprintf(key, sizeof(key), KEY_NET_SSID, i);
        len = NVS_SSID_LEN;
        nvs_get_str(h, key, out[i].ssid, &len);

        snprintf(key, sizeof(key), KEY_NET_PASS, i);
        len = NVS_PASS_LEN;
        nvs_get_str(h, key, out[i].password, &len);
    }

    *count = n;
    nvs_close(h);
    return ESP_OK;
}

esp_err_t nvs_config_save_network(const char *ssid, const char *password)
{
    wifi_credential_t nets[NVS_MAX_NETWORKS];
    int count = 0;

    /* Load current list (ignore not-found). */
    nvs_config_load_networks(nets, &count);

    /* Check for existing SSID to update in place. */
    int slot = -1;
    for (int i = 0; i < count; i++) {
        if (strcmp(nets[i].ssid, ssid) == 0) {
            slot = i;
            break;
        }
    }

    if (slot == -1) {
        if (count < NVS_MAX_NETWORKS) {
            slot = count;
            count++;
        } else {
            /* Evict the oldest entry (index 0) by shifting left. */
            memmove(&nets[0], &nets[1], (NVS_MAX_NETWORKS - 1) * sizeof(wifi_credential_t));
            slot = NVS_MAX_NETWORKS - 1;
        }
    }

    strncpy(nets[slot].ssid, ssid, NVS_SSID_LEN - 1);
    nets[slot].ssid[NVS_SSID_LEN - 1] = '\0';
    strncpy(nets[slot].password, password, NVS_PASS_LEN - 1);
    nets[slot].password[NVS_PASS_LEN - 1] = '\0';

    /* Persist. */
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h));

    nvs_set_u8(h, KEY_NET_COUNT, (uint8_t)count);
    for (int i = 0; i < count; i++) {
        char key[16];
        snprintf(key, sizeof(key), KEY_NET_SSID, i);
        nvs_set_str(h, key, nets[i].ssid);
        snprintf(key, sizeof(key), KEY_NET_PASS, i);
        nvs_set_str(h, key, nets[i].password);
    }

    esp_err_t err = nvs_commit(h);
    nvs_close(h);
    return err;
}

esp_err_t nvs_config_clear_networks(void)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h));

    /* Load current count so we know how many ssid_N / pass_N keys to erase. */
    uint8_t n = 0;
    nvs_get_u8(h, KEY_NET_COUNT, &n);
    if (n > NVS_MAX_NETWORKS) n = NVS_MAX_NETWORKS;

    for (int i = 0; i < n; i++) {
        char key[16];
        snprintf(key, sizeof(key), KEY_NET_SSID, i);
        nvs_erase_key(h, key);
        snprintf(key, sizeof(key), KEY_NET_PASS, i);
        nvs_erase_key(h, key);
    }
    nvs_erase_key(h, KEY_NET_COUNT);

    esp_err_t err = nvs_commit(h);
    nvs_close(h);
    ESP_LOGI(TAG, "All saved networks cleared (%d entries removed)", n);
    return err;
}

/* ---- API URL ------------------------------------------------------------- */

esp_err_t nvs_config_get_api_url(char *url, size_t buf_len)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    err = nvs_get_str(h, KEY_API_URL, url, &buf_len);
    nvs_close(h);
    return err;
}

esp_err_t nvs_config_set_api_url(const char *url)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h));
    esp_err_t err = nvs_set_str(h, KEY_API_URL, url);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

/* ---- Timezone ------------------------------------------------------------ */

esp_err_t nvs_config_get_timezone(char *tz, size_t buf_len)
{
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    err = nvs_get_str(h, KEY_TIMEZONE, tz, &buf_len);
    nvs_close(h);
    return err;
}

esp_err_t nvs_config_set_timezone(const char *tz)
{
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open(NVS_NAMESPACE, NVS_READWRITE, &h));
    esp_err_t err = nvs_set_str(h, KEY_TIMEZONE, tz);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}
