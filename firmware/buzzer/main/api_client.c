#include "api_client.h"

#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "cJSON.h"

#define TAG "api_client"

/* Maximum size of the raw HTTP response body. */
#define RESPONSE_BUF_LEN 4096

/* ---- HTTP response accumulator ------------------------------------------ */

typedef struct {
    char  *buf;
    int    len;
    int    cap;
} http_buf_t;

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    http_buf_t *acc = (http_buf_t *)evt->user_data;
    if (!acc) return ESP_OK;

    if (evt->event_id == HTTP_EVENT_ON_DATA && evt->data_len > 0) {
        int remaining = acc->cap - acc->len - 1;
        int to_copy = evt->data_len < remaining ? evt->data_len : remaining;
        memcpy(acc->buf + acc->len, evt->data, to_copy);
        acc->len += to_copy;
        acc->buf[acc->len] = '\0';
    }
    return ESP_OK;
}

/* ---- UTC mktime (timegm substitute) ------------------------------------- */

/*
 * timegm() is a GNU extension not available in ESP-IDF's newlib.
 * This implementation converts a UTC struct tm to a Unix timestamp without
 * relying on the local timezone — identical to timegm() semantics.
 */
static time_t utc_mktime(struct tm *t)
{
    /* Days per month (non-leap year). */
    static const int mdays[12] = {31,28,31,30,31,30,31,31,30,31,30,31};

    int y = t->tm_year + 1900;
    int m = t->tm_mon;   /* 0-based */

    /* Count leap days from epoch year (1970) up to start of current year. */
    int days = 0;
    for (int yr = 1970; yr < y; yr++) {
        days += 365;
        if ((yr % 4 == 0 && yr % 100 != 0) || yr % 400 == 0) days++;
    }

    /* Add days for months elapsed this year. */
    bool leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    for (int mo = 0; mo < m; mo++) {
        days += mdays[mo];
        if (mo == 1 && leap) days++;
    }

    days += t->tm_mday - 1;

    return (time_t)days * 86400
         + t->tm_hour * 3600
         + t->tm_min  * 60
         + t->tm_sec;
}

/* ---- ISO-8601 UTC parser (yyyy-mm-ddThh:mm:ss[.fff]Z) ------------------- */

static time_t parse_iso8601_utc(const char *s)
{
    struct tm t = {};
    if (sscanf(s, "%4d-%2d-%2dT%2d:%2d:%2d",
               &t.tm_year, &t.tm_mon, &t.tm_mday,
               &t.tm_hour, &t.tm_min, &t.tm_sec) != 6) {
        return 0;
    }
    t.tm_year -= 1900;
    t.tm_mon  -= 1;
    t.tm_isdst = 0;
    return utc_mktime(&t);
}

/* ---- Phase string parser ------------------------------------------------- */

static api_phase_t parse_phase(const char *s)
{
    if (!s) return API_PHASE_UNKNOWN;
    if (strcmp(s, "IDLE")   == 0) return API_PHASE_IDLE;
    if (strcmp(s, "PREP")   == 0) return API_PHASE_PREP;
    if (strcmp(s, "FLIGHT") == 0) return API_PHASE_FLIGHT;
    return API_PHASE_UNKNOWN;
}

/* ---- Public API ---------------------------------------------------------- */

bool api_client_fetch(const char *url, api_response_t *out)
{
    memset(out, 0, sizeof(*out));
    out->poll_interval_sec = 10;   /* safe default */

    char *buf = malloc(RESPONSE_BUF_LEN);
    if (!buf) {
        ESP_LOGE(TAG, "Out of memory");
        return false;
    }

    http_buf_t acc = { .buf = buf, .len = 0, .cap = RESPONSE_BUF_LEN };

    esp_http_client_config_t cfg = {
        .url            = url,
        .timeout_ms     = 5000,
        .event_handler  = http_event_handler,
        .user_data      = &acc,
        .method         = HTTP_METHOD_GET,
    };

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    if (err != ESP_OK || status != 200) {
        ESP_LOGE(TAG, "HTTP request failed: err=%s status=%d", esp_err_to_name(err), status);
        free(buf);
        return false;
    }

    /* Parse JSON. */
    cJSON *root = cJSON_Parse(buf);
    free(buf);

    if (!root) {
        ESP_LOGE(TAG, "JSON parse error");
        return false;
    }

    cJSON *status_j = cJSON_GetObjectItem(root, "status");
    if (!cJSON_IsString(status_j) || strcmp(status_j->valuestring, "ok") != 0) {
        ESP_LOGE(TAG, "API returned non-ok status");
        cJSON_Delete(root);
        return false;
    }

    cJSON *phase_j    = cJSON_GetObjectItem(root, "phase");
    cJSON *interval_j = cJSON_GetObjectItem(root, "poll_interval_sec");
    cJSON *stime_j    = cJSON_GetObjectItem(root, "server_time");
    cJSON *alarms_j   = cJSON_GetObjectItem(root, "alarms");

    out->phase             = parse_phase(cJSON_IsString(phase_j) ? phase_j->valuestring : NULL);
    out->poll_interval_sec = cJSON_IsNumber(interval_j) ? (int)interval_j->valuedouble : 10;
    out->server_time       = cJSON_IsString(stime_j)    ? parse_iso8601_utc(stime_j->valuestring) : 0;

    if (cJSON_IsArray(alarms_j)) {
        cJSON *alarm = NULL;
        cJSON_ArrayForEach(alarm, alarms_j) {
            if (out->alarm_count >= API_MAX_ALARMS) break;

            cJSON *id_j      = cJSON_GetObjectItem(alarm, "id");
            cJSON *type_j    = cJSON_GetObjectItem(alarm, "type");
            cJSON *fire_at_j = cJSON_GetObjectItem(alarm, "fire_at");

            if (!cJSON_IsString(id_j) || !cJSON_IsString(type_j) || !cJSON_IsString(fire_at_j))
                continue;

            api_alarm_t *a = &out->alarms[out->alarm_count];
            strncpy(a->id,   id_j->valuestring,      API_ALARM_ID_LEN - 1);
            strncpy(a->type, type_j->valuestring,     API_ALARM_TYPE_LEN - 1);
            a->fire_at = parse_iso8601_utc(fire_at_j->valuestring);
            out->alarm_count++;
        }
    }

    cJSON_Delete(root);
    out->ok = true;
    ESP_LOGI(TAG, "Fetched: phase=%d alarms=%d interval=%ds",
             out->phase, out->alarm_count, out->poll_interval_sec);
    return true;
}
