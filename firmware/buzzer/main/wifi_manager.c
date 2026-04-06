#include "wifi_manager.h"

#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_mac.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "nvs_config.h"

#define TAG "wifi_manager"

/*
 * AP SSID is built dynamically in wifi_manager_init() using the last 3 bytes
 * of the device's base MAC address:  "WKM-Buzzer-XXYYZZ"
 * Max length: 10 (prefix) + 1 (dash) + 6 (hex) + 1 (NUL) = 18 bytes.
 */
#define AP_SSID_PREFIX  "WKM-Buzzer-"
#define AP_SSID_LEN     18
#define AP_CHANNEL      1
#define AP_MAX_CONN     4

/* FreeRTOS event group bits. */
#define WIFI_CONNECTED_BIT BIT0
#define WIFI_FAIL_BIT      BIT1

static EventGroupHandle_t s_wifi_event_group;
static bool s_connected           = false;
static int  s_retry_count         = 0;
static bool s_intentional_disc    = false;  /* set before deliberate disconnect */
static bool s_reconnect_enabled   = true;   /* cleared while captive portal runs */
static char s_ap_ssid[AP_SSID_LEN] = {};
#define MAX_RETRY 3

/* ---- Event handler ------------------------------------------------------- */

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        s_connected = false;
        if (s_intentional_disc) {
            /* Deliberate disconnect requested by wifi_manager_connect() — signal
             * completion without triggering auto-retry. */
            s_intentional_disc = false;
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
        } else if (s_reconnect_enabled && s_retry_count < MAX_RETRY) {
            esp_wifi_connect();
            s_retry_count++;
            ESP_LOGW(TAG, "Retry Wi-Fi connection (%d/%d)", s_retry_count, MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
            ESP_LOGE(TAG, "Wi-Fi connection failed");
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry_count = 0;
        s_connected = true;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

/* ---- Public API ---------------------------------------------------------- */

void wifi_manager_init(void)
{
    s_wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    /* Create default interfaces. */
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    /*
     * Build unique AP SSID from the last 3 bytes of the base MAC address.
     * esp_efuse_mac_get_default() returns the factory-burned MAC (6 bytes).
     * Result example: "WKM-Buzzer-A1B2C3"
     */
    uint8_t mac[6] = {};
    esp_efuse_mac_get_default(mac);
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "%s%02X%02X%02X",
             AP_SSID_PREFIX, mac[3], mac[4], mac[5]);

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));

    /* AP configuration. */
    wifi_config_t ap_cfg = {};
    memcpy(ap_cfg.ap.ssid, s_ap_ssid, strlen(s_ap_ssid));
    ap_cfg.ap.ssid_len      = strlen(s_ap_ssid);
    ap_cfg.ap.channel       = AP_CHANNEL;
    ap_cfg.ap.authmode      = WIFI_AUTH_OPEN;
    ap_cfg.ap.max_connection = AP_MAX_CONN;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "AP started: SSID=%s (no password)", s_ap_ssid);

    /* Load saved credentials. If none, go straight to portal. */
    wifi_credential_t nets[NVS_MAX_NETWORKS];
    int net_count = 0;
    if (nvs_config_load_networks(nets, &net_count) != ESP_OK || net_count == 0) {
        ESP_LOGI(TAG, "No known networks — starting portal immediately");
        return;
    }

    ESP_LOGI(TAG, "%d known network(s) saved — scanning before connecting", net_count);

    /*
     * Scan-before-connect: only attempt networks visible in the current scan.
     * This avoids broadcasting credentials to access points that are not present.
     * Retry the scan up to SCAN_MAX_ATTEMPTS times with SCAN_RETRY_DELAY_MS delay.
     */
    #define SCAN_MAX_ATTEMPTS  3
    #define SCAN_MAX_AP        20
    #define SCAN_RETRY_DELAY_MS 5000

    wifi_ap_record_t *ap_list = malloc(SCAN_MAX_AP * sizeof(wifi_ap_record_t));
    if (!ap_list) {
        ESP_LOGE(TAG, "Out of memory for scan buffer — skipping scan");
        return;
    }

    bool connected = false;

    for (int attempt = 1; attempt <= SCAN_MAX_ATTEMPTS && !connected; attempt++) {
        ESP_LOGI(TAG, "Scan attempt %d/%d", attempt, SCAN_MAX_ATTEMPTS);

        esp_wifi_scan_start(NULL, true);   /* blocking scan */

        uint16_t ap_count = SCAN_MAX_AP;
        esp_wifi_scan_get_ap_records(&ap_count, ap_list);
        ESP_LOGI(TAG, "Found %d visible network(s)", ap_count);

        /* Match visible networks against saved list, preserving saved order. */
        for (int i = 0; i < net_count && !connected; i++) {
            for (int j = 0; j < ap_count; j++) {
                if (strcmp(nets[i].ssid, (char *)ap_list[j].ssid) == 0) {
                    ESP_LOGI(TAG, "Match: '%s' (RSSI %d) — connecting",
                             nets[i].ssid, ap_list[j].rssi);
                    connected = wifi_manager_connect(nets[i].ssid, nets[i].password);
                    break;
                }
            }
        }

        if (!connected) {
            ESP_LOGW(TAG, "No saved networks visible in scan");
            if (attempt < SCAN_MAX_ATTEMPTS) {
                ESP_LOGI(TAG, "Waiting %d s before next scan...", SCAN_RETRY_DELAY_MS / 1000);
                vTaskDelay(pdMS_TO_TICKS(SCAN_RETRY_DELAY_MS));
            }
        }
    }

    free(ap_list);

    if (!connected) {
        ESP_LOGW(TAG, "All scan attempts failed — portal will start");
    }

    #undef SCAN_MAX_ATTEMPTS
    #undef SCAN_MAX_AP
    #undef SCAN_RETRY_DELAY_MS
}

bool wifi_manager_is_connected(void)
{
    return s_connected;
}

bool wifi_manager_connect(const char *ssid, const char *password)
{
    /* If already connected to the same SSID, skip reconnection. */
    if (s_connected) {
        wifi_ap_record_t ap_info = {};
        if (esp_wifi_sta_get_ap_info(&ap_info) == ESP_OK &&
            strcmp((char *)ap_info.ssid, ssid) == 0) {
            ESP_LOGI(TAG, "Already connected to '%s' — skipping reconnect", ssid);
            return true;
        }

        /* Connected to a different network — disconnect cleanly first. */
        ESP_LOGI(TAG, "Disconnecting from current AP before connecting to '%s'", ssid);
        s_intentional_disc = true;
        xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT);
        esp_wifi_disconnect();
        /* Wait up to 5 s for disconnect confirmation from event handler. */
        xEventGroupWaitBits(s_wifi_event_group, WIFI_FAIL_BIT,
                            pdFALSE, pdFALSE, pdMS_TO_TICKS(5000));
        s_intentional_disc = false;
    }

    s_retry_count = 0;
    xEventGroupClearBits(s_wifi_event_group, WIFI_CONNECTED_BIT | WIFI_FAIL_BIT);

    wifi_config_t sta_cfg = {};
    strncpy((char *)sta_cfg.sta.ssid, ssid, sizeof(sta_cfg.sta.ssid) - 1);
    strncpy((char *)sta_cfg.sta.password, password, sizeof(sta_cfg.sta.password) - 1);

    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_cfg));
    esp_wifi_connect();

    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                                           WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(15000));

    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Connected to '%s'", ssid);
        return true;
    }
    ESP_LOGE(TAG, "Failed to connect to '%s'", ssid);
    return false;
}

void wifi_manager_set_reconnect(bool enabled)
{
    s_reconnect_enabled = enabled;
    ESP_LOGI(TAG, "Auto-reconnect %s", enabled ? "enabled" : "disabled");
}

const char *wifi_manager_get_ap_ssid(void)
{
    return s_ap_ssid;
}

void wifi_manager_get_ip(char *buf, size_t len)
{
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (!sta) {
        snprintf(buf, len, "0.0.0.0");
        return;
    }
    esp_netif_ip_info_t info;
    if (esp_netif_get_ip_info(sta, &info) == ESP_OK) {
        snprintf(buf, len, IPSTR, IP2STR(&info.ip));
    } else {
        snprintf(buf, len, "0.0.0.0");
    }
}
