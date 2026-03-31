#include "ntp_sync.h"

#include <stdlib.h>
#include "esp_log.h"
#include "esp_sntp.h"        /* part of lwip component in ESP-IDF v5.x */
#include "nvs_config.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define TAG "ntp_sync"

#define NTP_SERVER      "pool.ntp.org"
#define SYNC_TIMEOUT_MS 10000

static bool s_synced        = false;
static bool s_initialized   = false;

static void sntp_sync_cb(struct timeval *tv)
{
    s_synced = true;
    ESP_LOGI(TAG, "Time synchronised: %lld", (long long)tv->tv_sec);
}

bool ntp_sync_init(void)
{
    /* Apply timezone from NVS. */
    char tz[NVS_TZ_LEN] = "";
    if (nvs_config_get_timezone(tz, sizeof(tz)) == ESP_OK && tz[0] != '\0') {
        setenv("TZ", tz, 1);
        tzset();
        ESP_LOGI(TAG, "Timezone set to: %s", tz);
    }

    if (!s_initialized) {
        /*
         * ESP-IDF v5.x SNTP API:
         *   esp_sntp_setoperatingmode / esp_sntp_setservername / esp_sntp_init
         * are wrappers around lwip sntp that remain available in v5.x.
         */
        esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);
        esp_sntp_setservername(0, NTP_SERVER);
        esp_sntp_set_time_sync_notification_cb(sntp_sync_cb);
        esp_sntp_init();
        s_initialized = true;
    }

    s_synced = false;

    /* Wait for first sync. */
    int elapsed = 0;
    while (!s_synced && elapsed < SYNC_TIMEOUT_MS) {
        vTaskDelay(pdMS_TO_TICKS(200));
        elapsed += 200;
    }

    if (!s_synced) {
        ESP_LOGE(TAG, "NTP sync timed out after %d ms", SYNC_TIMEOUT_MS);
    }
    return s_synced;
}

bool ntp_sync_now(void)
{
    /*
     * In ESP-IDF v5.x there is no esp_sntp_restart().
     * Force an immediate re-sync by stopping and re-initialising the client.
     */
    if (s_initialized) {
        esp_sntp_stop();
        s_initialized = false;
    }
    return ntp_sync_init();
}

bool ntp_sync_is_synced(void)
{
    return s_synced;
}

time_t ntp_sync_get_utc(void)
{
    return time(NULL);
}
