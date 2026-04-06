#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
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

/* NTP re-sync period expressed in 100 ms ticks (= 60 min). */
#define NTP_RESYNC_TICKS (3600 * 10)

/* ---- Async API fetch task ------------------------------------------------ */

typedef struct {
    char url[NVS_URL_LEN];
} fetch_ctx_t;

static QueueHandle_t s_fetch_queue = NULL;
static TaskHandle_t  s_fetch_task  = NULL;

/*
 * Runs independently of the main loop.
 * Fetches the API at the server-specified interval and pushes the result
 * (heap-allocated) to s_fetch_queue. The main loop consumes it non-blocking
 * so alarm_scheduler_tick() is never paused while waiting for HTTP.
 *
 * On failure the task retries after 5 s. On success it uses poll_interval_sec
 * from the response. The queue depth is 1 — if the main loop hasn't consumed
 * the previous result yet, it is replaced with the newer one.
 */
static void fetch_task_fn(void *arg)
{
    fetch_ctx_t *ctx = (fetch_ctx_t *)arg;
    int poll_ms = 0;  /* fetch immediately on first iteration */

    while (1) {
        if (poll_ms > 0) {
            vTaskDelay(pdMS_TO_TICKS(poll_ms));
        }

        api_response_t *resp = malloc(sizeof(api_response_t));
        if (!resp) {
            ESP_LOGE(TAG, "fetch_task: out of memory");
            poll_ms = 5000;
            continue;
        }

        bool ok = api_client_fetch(ctx->url, resp);
        poll_ms = (ok && resp->poll_interval_sec > 0)
                  ? resp->poll_interval_sec * 1000
                  : 5000;

        /* Replace any unconsumed result so the queue never stalls. */
        api_response_t *stale = NULL;
        if (xQueueReceive(s_fetch_queue, &stale, 0) == pdTRUE) {
            free(stale);
        }
        xQueueSend(s_fetch_queue, &resp, 0);
    }
}

static void fetch_start(fetch_ctx_t *ctx, const char *url)
{
    strncpy(ctx->url, url, sizeof(ctx->url) - 1);
    ctx->url[sizeof(ctx->url) - 1] = '\0';
    s_fetch_queue = xQueueCreate(1, sizeof(api_response_t *));
    xTaskCreate(fetch_task_fn, "api_fetch", 8192, ctx, 4, &s_fetch_task);
}

static void fetch_stop(void)
{
    if (s_fetch_task) {
        vTaskDelete(s_fetch_task);
        s_fetch_task = NULL;
    }
    if (s_fetch_queue) {
        api_response_t *leftover = NULL;
        while (xQueueReceive(s_fetch_queue, &leftover, 0) == pdTRUE) {
            free(leftover);
        }
        vQueueDelete(s_fetch_queue);
        s_fetch_queue = NULL;
    }
}

/* ---- Polling loop (CONNECTED state) ------------------------------------- */

static void connected_loop(const char *api_url)
{
    ESP_LOGI(TAG, "Entering connected loop — API: %s", api_url);
    led_rgb_set(LED_STATE_GREEN);

    fetch_ctx_t fetch_ctx;
    fetch_start(&fetch_ctx, api_url);

    bool api_was_reachable = true;
    int  ntp_ticks = NTP_RESYNC_TICKS;

    while (1) {
        alarm_scheduler_tick();
        vTaskDelay(pdMS_TO_TICKS(100));

        /* Detect Wi-Fi drop. */
        if (!wifi_manager_is_connected()) {
            ESP_LOGE(TAG, "Wi-Fi dropped — returning to disconnected state");
            led_rgb_set(LED_STATE_RED);
            break;
        }

        /* Detect portal reconfiguration (user changed API URL via web form). */
        if (captive_portal_is_configured()) {
            ESP_LOGI(TAG, "Portal reconfiguration detected — reloading API URL");
            captive_portal_clear_configured();
            break;
        }

        /* Periodic NTP re-sync. */
        if (--ntp_ticks <= 0) {
            ESP_LOGI(TAG, "Periodic NTP re-sync");
            ntp_sync_now();
            ntp_ticks = NTP_RESYNC_TICKS;
        }

        /* Consume latest fetch result (non-blocking — never pauses alarm tick). */
        api_response_t *resp = NULL;
        if (xQueueReceive(s_fetch_queue, &resp, 0) == pdTRUE) {
            if (resp->ok) {
                if (!api_was_reachable) {
                    ESP_LOGI(TAG, "API reachable again");
                    led_rgb_set(LED_STATE_GREEN);
                    api_was_reachable = true;
                }
                alarm_scheduler_update(resp);
            } else {
                if (api_was_reachable) {
                    ESP_LOGW(TAG, "API unreachable — holding alarm queue");
                    led_rgb_set(LED_STATE_YELLOW);
                    api_was_reachable = false;
                }
            }
            free(resp);
        }
    }

    fetch_stop();
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

            captive_portal_stop_dns();        /* DNS no longer needed */
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
