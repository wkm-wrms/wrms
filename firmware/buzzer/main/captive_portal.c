#include "captive_portal.h"

#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "lwip/sockets.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_config.h"
#include "wifi_manager.h"
#include "ntp_sync.h"
#include "buzzer_gpio.h"
#include "led_rgb.h"
#include "api_client.h"

#define TAG "captive_portal"

static httpd_handle_t s_server        = NULL;
static char s_last_error[32]          = "";
static TaskHandle_t s_dns_task        = NULL;
static volatile bool s_configured     = false;
static volatile int  s_dns_sock       = -1;   /* shared so stop() can unblock recvfrom */

/* ---- DNS hijack server --------------------------------------------------- */

/*
 * Listens on UDP 53. Responds to every query with the AP's own IP (192.168.4.1)
 * so that mobile clients open the captive portal automatically.
 */
#define DNS_PORT 53
#define AP_IP    "192.168.4.1"

static void dns_server_task(void *arg)
{
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) {
        ESP_LOGE(TAG, "DNS socket creation failed");
        s_dns_sock = -1;
        vTaskDelete(NULL);
        return;
    }

    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(DNS_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        ESP_LOGE(TAG, "DNS bind failed");
        close(sock);
        s_dns_sock = -1;
        vTaskDelete(NULL);
        return;
    }

    s_dns_sock = sock;  /* publish handle so captive_portal_stop() can unblock us */

    uint8_t buf[512];
    struct sockaddr_in client;
    socklen_t clen = sizeof(client);

    while (1) {
        int len = recvfrom(sock, buf, sizeof(buf), 0, (struct sockaddr *)&client, &clen);
        if (len < 0) break;  /* socket shut down or closed — exit cleanly */

        /*
         * Build a minimal DNS A-record response.
         * Header flags: QR=1 AA=1 RCODE=0.
         * Single answer pointing to AP_IP.
         */
        if (len < 12) continue;

        /* Copy question into response buffer, set response flags. */
        uint8_t resp[512];
        memcpy(resp, buf, len);
        resp[2] = 0x81;  /* QR=1, OPCODE=0, AA=1 */
        resp[3] = 0x80;  /* RA=1, RCODE=0 */
        resp[6] = 0x00;  /* ANCOUNT high */
        resp[7] = 0x01;  /* ANCOUNT low = 1 */

        /* Append answer: pointer to question name + A type + TTL 60 + rdata */
        int off = len;
        resp[off++] = 0xC0; resp[off++] = 0x0C;  /* pointer to name at offset 12 */
        resp[off++] = 0x00; resp[off++] = 0x01;  /* TYPE A */
        resp[off++] = 0x00; resp[off++] = 0x01;  /* CLASS IN */
        resp[off++] = 0x00; resp[off++] = 0x00;  /* TTL high */
        resp[off++] = 0x00; resp[off++] = 0x3C;  /* TTL low (60 s) */
        resp[off++] = 0x00; resp[off++] = 0x04;  /* RDLENGTH */
        /* IP 192.168.4.1 */
        resp[off++] = 192; resp[off++] = 168; resp[off++] = 4; resp[off++] = 1;

        sendto(sock, resp, off, 0, (struct sockaddr *)&client, clen);
    }

    /* Close socket and clear handle before task exits. */
    close(sock);
    s_dns_sock = -1;
    s_dns_task = NULL;
    vTaskDelete(NULL);
}

/* ---- HTML page ----------------------------------------------------------- */

/* PORTAL_HTML_HEAD is used as a printf format: %s is replaced by the AP SSID. */
static const char *PORTAL_HTML_HEAD_FMT =
    "<!DOCTYPE html><html lang='en'><head>"
    "<meta charset='UTF-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>%s — Setup</title>"
    "<style>"
    "body{font-family:sans-serif;background:#111;color:#eee;padding:20px;max-width:480px;margin:auto;}"
    "h2{color:#00d4ff;}label{display:block;margin-top:12px;font-size:.9em;color:#aaa;}"
    "input,select{width:100%;padding:8px;margin-top:4px;background:#222;border:1px solid #444;"
    "color:#eee;border-radius:4px;box-sizing:border-box;}"
    "button{margin-top:20px;width:100%;padding:12px;background:#00d4ff;color:#000;"
    "font-weight:bold;border:none;border-radius:6px;cursor:pointer;}"
    ".err{color:#ff6b6b;margin-top:12px;font-size:.85em;}"
    "</style></head><body>"
    "<h2>%s — Setup</h2><form method='POST' action='/connect'>";

/* Footer format: %s = current api_url, %s = current tz */
static const char *PORTAL_HTML_FOOT_FMT =
    "<label>API URL"
      "<input name='url' value='%s' placeholder='http://192.168.1.10:8000/api/buzzer' required>"
    "</label>"
    "<label>Timezone (POSIX)<input name='tz' value='%s'></label>"
    "<button type='submit'>Save</button>"
    "</form>"
    "<hr style='border-color:#333;margin-top:24px'>"
    "<form method='POST' action='/clear-networks'"
      " onsubmit=\"return confirm('Clear all saved Wi-Fi networks?')\">"
      "<button type='submit'"
        " style='width:100%;padding:10px;background:#c0392b;color:#fff;"
        "font-weight:bold;border:none;border-radius:6px;cursor:pointer;'>"
        "Clear saved networks"
      "</button>"
    "</form>"
    "<p style='color:#888;font-size:.8em;margin-top:16px'>"
      "Leave Wi-Fi fields empty to keep the current connection."
    "</p>"
    "</body></html>";

/* ---- HTTP handlers ------------------------------------------------------- */

static esp_err_t handle_root(httpd_req_t *req)
{
    #define MAX_AP    16
    #define PAGE_SIZE 4096

    wifi_ap_record_t *ap_list = malloc(MAX_AP * sizeof(wifi_ap_record_t));
    char *page = malloc(PAGE_SIZE);
    if (!ap_list || !page) {
        free(ap_list);
        free(page);
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
        return ESP_FAIL;
    }

    /* Read current config from NVS for pre-filling. */
    char cur_url[NVS_URL_LEN] = "";
    char cur_tz[NVS_TZ_LEN]   = "CET-1CEST,M3.5.0,M10.5.0/3";
    nvs_config_get_api_url(cur_url, sizeof(cur_url));
    nvs_config_get_timezone(cur_tz, sizeof(cur_tz));

    /* Determine currently connected SSID (empty string if not connected). */
    char cur_ssid[33] = "";
    if (wifi_manager_is_connected()) {
        wifi_ap_record_t sta_ap = {};
        if (esp_wifi_sta_get_ap_info(&sta_ap) == ESP_OK) {
            strncpy(cur_ssid, (char *)sta_ap.ssid, sizeof(cur_ssid) - 1);
        }
    }

    /* Scan for nearby SSIDs. */
    uint16_t ap_count = 0;
    esp_wifi_scan_start(NULL, true);
    esp_wifi_scan_get_ap_num(&ap_count);
    if (ap_count > MAX_AP) ap_count = MAX_AP;
    esp_wifi_scan_get_ap_records(&ap_count, ap_list);

    const char *ap_ssid = wifi_manager_get_ap_ssid();
    int n = 0;
    n += snprintf(page + n, PAGE_SIZE - n, PORTAL_HTML_HEAD_FMT, ap_ssid, ap_ssid);

    /* SSID select — mark currently connected SSID as selected. */
    n += snprintf(page + n, PAGE_SIZE - n,
                  "<label>Wi-Fi Network (leave empty to keep current)"
                  "<select name='ssid'>"
                  "<option value=''>— keep current —</option>");
    for (int i = 0; i < ap_count; i++) {
        const char *sel = (strcmp((char *)ap_list[i].ssid, cur_ssid) == 0) ? " selected" : "";
        n += snprintf(page + n, PAGE_SIZE - n,
                      "<option%s>%s</option>", sel, (char *)ap_list[i].ssid);
    }
    n += snprintf(page + n, PAGE_SIZE - n, "</select></label>");
    n += snprintf(page + n, PAGE_SIZE - n,
                  "<label>Password<input name='pass' type='password'"
                  " placeholder='leave empty to keep current'></label>");

    /* Diagnostic error from previous attempt. */
    if (s_last_error[0] != '\0') {
        n += snprintf(page + n, PAGE_SIZE - n,
                      "<p class='err'>Error: %s</p>", s_last_error);
    }

    n += snprintf(page + n, PAGE_SIZE - n, PORTAL_HTML_FOOT_FMT, cur_url, cur_tz);

    httpd_resp_set_type(req, "text/html");
    httpd_resp_send(req, page, n);

    free(ap_list);
    free(page);
    return ESP_OK;

    #undef MAX_AP
    #undef PAGE_SIZE
}

/* Simple URL-decode (in-place, handles %XX and +). */
static void url_decode(char *s)
{
    char *r = s, *w = s;
    while (*r) {
        if (*r == '%' && r[1] && r[2]) {
            char hex[3] = {r[1], r[2], 0};
            *w++ = (char)strtol(hex, NULL, 16);
            r += 3;
        } else if (*r == '+') {
            *w++ = ' ';
            r++;
        } else {
            *w++ = *r++;
        }
    }
    *w = '\0';
}

static void parse_form_field(const char *body, const char *key, char *out, size_t out_len)
{
    char search[64];
    snprintf(search, sizeof(search), "%s=", key);
    const char *p = strstr(body, search);
    if (!p) { out[0] = '\0'; return; }
    p += strlen(search);
    const char *end = strchr(p, '&');
    size_t len = end ? (size_t)(end - p) : strlen(p);
    if (len >= out_len) len = out_len - 1;
    memcpy(out, p, len);
    out[len] = '\0';
    url_decode(out);
}

static esp_err_t handle_connect(httpd_req_t *req)
{
    char *body = calloc(1, 512);
    if (!body) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
        return ESP_FAIL;
    }
    int received = httpd_req_recv(req, body, 511);
    if (received <= 0) {
        free(body);
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "No body");
        return ESP_FAIL;
    }

    char ssid[NVS_SSID_LEN], pass[NVS_PASS_LEN], url[NVS_URL_LEN], tz[NVS_TZ_LEN];
    parse_form_field(body, "ssid", ssid, sizeof(ssid));
    parse_form_field(body, "pass", pass, sizeof(pass));
    parse_form_field(body, "url",  url,  sizeof(url));
    parse_form_field(body, "tz",   tz,   sizeof(tz));

    /* body is no longer needed after field parsing. */
    free(body);
    body = NULL;

    /*
     * Wi-Fi step: only reconnect when the user supplied a new SSID.
     * Leaving the SSID field empty means "keep the current connection".
     */
    if (ssid[0] != '\0') {
        bool connected = wifi_manager_connect(ssid, pass);
        if (!connected) {
            captive_portal_set_error("WIFI_AUTH_FAILED");
            buzzer_gpio_error_beep();
            httpd_resp_set_status(req, "302 Found");
            httpd_resp_set_hdr(req, "Location", "/");
            httpd_resp_send(req, NULL, 0);
            return ESP_OK;
        }
        nvs_config_save_network(ssid, pass);
    } else if (!wifi_manager_is_connected()) {
        captive_portal_set_error("WIFI_NOT_FOUND");
        httpd_resp_set_status(req, "302 Found");
        httpd_resp_set_hdr(req, "Location", "/");
        httpd_resp_send(req, NULL, 0);
        return ESP_OK;
    }

    /* Validate API endpoint. */
    api_response_t resp = {};
    if (!api_client_fetch(url, &resp)) {
        captive_portal_set_error("API_UNREACHABLE");
        buzzer_gpio_error_beep();
        httpd_resp_set_status(req, "302 Found");
        httpd_resp_set_hdr(req, "Location", "/");
        httpd_resp_send(req, NULL, 0);
        return ESP_OK;
    }

    /* NTP sync (no-op if already synced). */
    if (!ntp_sync_is_synced()) {
        bool synced = ntp_sync_init();
        if (!synced) {
            captive_portal_set_error("NTP_FAILED");
            buzzer_gpio_error_beep();
            httpd_resp_set_status(req, "302 Found");
            httpd_resp_set_hdr(req, "Location", "/");
            httpd_resp_send(req, NULL, 0);
            return ESP_OK;
        }
    }

    /* Persist configuration. */
    nvs_config_set_api_url(url);
    if (tz[0]) nvs_config_set_timezone(tz);
    s_last_error[0] = '\0';

    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr(req,
        "<html><body style='background:#111;color:#2ecc71;font-family:sans-serif;"
        "display:flex;align-items:center;justify-content:center;height:100vh;'>"
        "<h2>Saved! Buzzer is active.</h2>"
        "<p style='color:#aaa'><a href='/' style='color:#00d4ff'>Back to config</a></p>"
        "</body></html>");

    /*
     * Signal main.c that configuration changed. The portal keeps running so
     * the user can return to / and reconfigure again at any time.
     * main.c clears this flag after reloading the URL from NVS.
     */
    s_configured = true;

    return ESP_OK;
}

static esp_err_t handle_clear_networks(httpd_req_t *req)
{
    nvs_config_clear_networks();
    httpd_resp_set_type(req, "text/html");
    httpd_resp_sendstr(req,
        "<html><body style='background:#111;color:#2ecc71;font-family:sans-serif;"
        "display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;'>"
        "<h2>Saved networks cleared.</h2>"
        "<p style='color:#aaa'><a href='/' style='color:#00d4ff'>Back to config</a></p>"
        "</body></html>");
    return ESP_OK;
}

/* Redirect all unknown paths to root (captive portal trigger). */
static esp_err_t handle_redirect(httpd_req_t *req)
{
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", "http://192.168.4.1/");
    httpd_resp_send(req, NULL, 0);
    return ESP_OK;
}

/* ---- Public API ---------------------------------------------------------- */

void captive_portal_start(void)
{
    s_configured = false;   /* reset for this configuration attempt */
    s_dns_sock   = -1;
    wifi_manager_set_reconnect(false);  /* suppress background reconnect while portal runs */
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.uri_match_fn = httpd_uri_match_wildcard;
    cfg.stack_size = 16384;  /* esp_http_client inside handle_connect needs deep stack */

    if (httpd_start(&s_server, &cfg) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server");
        return;
    }

    httpd_uri_t root          = {"/",               HTTP_GET,  handle_root,           NULL};
    httpd_uri_t connect       = {"/connect",        HTTP_POST, handle_connect,         NULL};
    httpd_uri_t clear_nets    = {"/clear-networks", HTTP_POST, handle_clear_networks,  NULL};
    httpd_uri_t redir         = {"/*",              HTTP_GET,  handle_redirect,        NULL};
    httpd_register_uri_handler(s_server, &root);
    httpd_register_uri_handler(s_server, &connect);
    httpd_register_uri_handler(s_server, &clear_nets);
    httpd_register_uri_handler(s_server, &redir);

    xTaskCreate(dns_server_task, "dns_srv", 4096, NULL, 5, &s_dns_task);

    ESP_LOGI(TAG, "Captive portal started at http://192.168.4.1/");
}

void captive_portal_stop(void)
{
    if (s_server) {
        httpd_stop(s_server);
        s_server = NULL;
    }

    /*
     * Unblock the DNS task by shutting down its socket. recvfrom() returns -1,
     * the task closes the socket and deletes itself. We wait up to 500 ms for
     * that to complete so the port is free before the caller can start a new
     * portal instance.
     */
    if (s_dns_sock >= 0) {
        shutdown(s_dns_sock, SHUT_RDWR);
        /* Wait for the task to close the socket and self-delete. */
        for (int i = 0; i < 10 && s_dns_sock >= 0; i++) {
            vTaskDelay(pdMS_TO_TICKS(50));
        }
    }
    /* Fallback: force-delete if task did not exit on its own. */
    if (s_dns_task) {
        vTaskDelete(s_dns_task);
        s_dns_task = NULL;
    }

    wifi_manager_set_reconnect(true);   /* re-enable auto-reconnect after portal stops */
    ESP_LOGI(TAG, "Captive portal stopped");
}

const char *captive_portal_last_error(void)
{
    return s_last_error[0] ? s_last_error : NULL;
}

void captive_portal_set_error(const char *err)
{
    strncpy(s_last_error, err, sizeof(s_last_error) - 1);
    s_last_error[sizeof(s_last_error) - 1] = '\0';
    ESP_LOGW(TAG, "Connection error: %s", s_last_error);
}

bool captive_portal_is_configured(void)
{
    return s_configured;
}

void captive_portal_stop_dns(void)
{
    if (s_dns_sock >= 0) {
        shutdown(s_dns_sock, SHUT_RDWR);
        for (int i = 0; i < 10 && s_dns_sock >= 0; i++) {
            vTaskDelay(pdMS_TO_TICKS(50));
        }
    }
    if (s_dns_task) {
        vTaskDelete(s_dns_task);
        s_dns_task = NULL;
    }
    ESP_LOGI(TAG, "DNS hijack stopped");
}

void captive_portal_start_reconfig(void)
{
    if (s_server != NULL) return;  /* already running — nothing to do */
    wifi_manager_set_reconnect(false);  /* suppress background reconnect while portal runs */

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.uri_match_fn = httpd_uri_match_wildcard;
    cfg.stack_size = 16384;

    if (httpd_start(&s_server, &cfg) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start HTTP server (reconfig)");
        return;
    }

    httpd_uri_t root       = {"/",               HTTP_GET,  handle_root,          NULL};
    httpd_uri_t connect    = {"/connect",        HTTP_POST, handle_connect,        NULL};
    httpd_uri_t clear_nets = {"/clear-networks", HTTP_POST, handle_clear_networks, NULL};
    httpd_uri_t redir      = {"/*",              HTTP_GET,  handle_redirect,       NULL};
    httpd_register_uri_handler(s_server, &root);
    httpd_register_uri_handler(s_server, &connect);
    httpd_register_uri_handler(s_server, &clear_nets);
    httpd_register_uri_handler(s_server, &redir);

    ESP_LOGI(TAG, "Config HTTP server started (no DNS)");
}

bool captive_portal_is_running(void)
{
    return s_server != NULL;
}

void captive_portal_clear_configured(void)
{
    s_configured = false;
}
