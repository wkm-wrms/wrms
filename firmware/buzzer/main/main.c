#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"

#include "nvs_config.h"
#include "wifi_manager.h"
#include "captive_portal.h"
#include "ntp_sync.h"
#include "api_client.h"
#include "alarm_scheduler.h"
#include "buzzer_gpio.h"
#include "led_rgb.h"

#define TAG "main"

/* Re-sync NTP every 60 minutes (in poll cycles). */
#define NTP_RESYNC_INTERVAL_SEC 3600

/* ---- Polling loop (CONNECTED state) ------------------------------------- */

static void connected_loop(const char *api_url)
{
    ESP_LOGI(TAG, "Entering connected loop — API: %s", api_url);
    led_rgb_set(LED_STATE_GREEN);

    int poll_interval_sec = 10;
    int ntp_resync_countdown = NTP_RESYNC_INTERVAL_SEC;
    bool api_was_reachable = true;

    while (1) {
        /* Alarm tick: check every 200 ms. */
        for (int i = 0; i < (poll_interval_sec * 1000) / 200; i++) {
            alarm_scheduler_tick();
            vTaskDelay(pdMS_TO_TICKS(200));

            /* Detect Wi-Fi drop. */
            if (!wifi_manager_is_connected()) {
                ESP_LOGE(TAG, "Wi-Fi dropped — returning to disconnected state");
                led_rgb_set(LED_STATE_RED);
                return;
            }

            /* Detect portal reconfiguration (user changed API URL via web form). */
            if (captive_portal_is_configured()) {
                ESP_LOGI(TAG, "Portal reconfiguration detected — reloading API URL");
                captive_portal_clear_configured();
                return;
            }
        }

        /* Periodic NTP re-sync. */
        ntp_resync_countdown -= poll_interval_sec;
        if (ntp_resync_countdown <= 0) {
            ESP_LOGI(TAG, "Periodic NTP re-sync");
            ntp_sync_now();
            ntp_resync_countdown = NTP_RESYNC_INTERVAL_SEC;
        }

        /* Poll API. */
        api_response_t resp;
        bool ok = api_client_fetch(api_url, &resp);

        if (!ok) {
            if (api_was_reachable) {
                ESP_LOGW(TAG, "API unreachable — holding alarm queue");
                led_rgb_set(LED_STATE_YELLOW);
                api_was_reachable = false;
            }
            poll_interval_sec = 5;
            continue;
        }

        if (!api_was_reachable) {
            ESP_LOGI(TAG, "API reachable again");
            led_rgb_set(LED_STATE_GREEN);
            api_was_reachable = true;
        }

        alarm_scheduler_update(&resp);
        poll_interval_sec = resp.poll_interval_sec > 0 ? resp.poll_interval_sec : 10;
    }
}

/* ---- App entry point ---------------------------------------------------- */

void app_main(void)
{
    ESP_LOGI(TAG, "WKM Buzzer starting...");

    /* 1. Initialise peripherals. */
    buzzer_gpio_init();
    led_rgb_init();
    alarm_scheduler_init();

    /* 2. Initialise NVS. */
    ESP_ERROR_CHECK(nvs_config_init());

    /* Signal startup. */
    led_rgb_set(LED_STATE_RED);

    /* 3. Wi-Fi: AP+STA, attempt known networks. */
    wifi_manager_init();

    /* 4. Main state machine loop. */
    while (1) {
        /* Read API URL from NVS. */
        char api_url[NVS_URL_LEN] = "";
        bool has_url = (nvs_config_get_api_url(api_url, sizeof(api_url)) == ESP_OK
                        && api_url[0] != '\0');

        if (!wifi_manager_is_connected() || !has_url) {
            /*
             * DISCONNECTED / not configured:
             * Start full portal (HTTP + DNS hijack) and block until
             * handle_connect completes the setup sequence.
             * After success, stop DNS only — HTTP stays up for reconfig.
             */
            ESP_LOGI(TAG, "State: DISCONNECTED — starting captive portal");
            led_rgb_set(LED_STATE_RED);
            captive_portal_start();

            while (!captive_portal_is_configured()) {
                vTaskDelay(pdMS_TO_TICKS(500));
            }

            captive_portal_stop_dns();       /* DNS no longer needed */
            captive_portal_clear_configured(); /* arm for next reconfiguration */

            /* Re-read URL written by handle_connect. */
            nvs_config_get_api_url(api_url, sizeof(api_url));
            ESP_LOGI(TAG, "Portal configuration complete — API: %s", api_url);
        } else {
            /*
             * Already connected and configured: start HTTP-only portal so the
             * user can change the API URL at any time via http://192.168.4.1/
             */
            captive_portal_start_reconfig();
        }

        /* NTP should already be synced by handle_connect, but re-init if not. */
        if (!ntp_sync_is_synced()) {
            ESP_LOGI(TAG, "Syncing NTP...");
            ntp_sync_init();
        }

        connected_loop(api_url);

        /*
         * connected_loop returns on Wi-Fi drop or portal reconfiguration.
         * Stop the portal fully before restarting the main loop so that
         * captive_portal_start() can bind DNS port 53 cleanly on the next pass.
         */
        captive_portal_stop();
    }
}
