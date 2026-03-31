#include "alarm_scheduler.h"

#include <string.h>
#include <time.h>
#include "esp_log.h"
#include "buzzer_gpio.h"
#include "led_rgb.h"
#include "ntp_sync.h"

#define TAG "alarm_scheduler"

/* Maximum number of alarm IDs remembered as already fired. */
#define FIRED_MAX 64

/* ---- Internal state ------------------------------------------------------ */

static api_alarm_t s_queue[API_MAX_ALARMS];
static int         s_queue_len = 0;

/* Ring buffer of already-fired IDs for deduplication. */
static char s_fired[FIRED_MAX][API_ALARM_ID_LEN];
static int  s_fired_count = 0;

/* Phase seen on last update — used to detect session reset (active→IDLE). */
static api_phase_t s_last_phase = API_PHASE_IDLE;

/* ---- Helpers ------------------------------------------------------------- */

static bool already_fired(const char *id)
{
    for (int i = 0; i < s_fired_count; i++) {
        if (strcmp(s_fired[i], id) == 0) return true;
    }
    return false;
}

static void mark_fired(const char *id)
{
    if (s_fired_count >= FIRED_MAX) {
        /* Ring: evict oldest. */
        memmove(s_fired[0], s_fired[1], (FIRED_MAX - 1) * API_ALARM_ID_LEN);
        s_fired_count = FIRED_MAX - 1;
    }
    strncpy(s_fired[s_fired_count], id, API_ALARM_ID_LEN - 1);
    s_fired[s_fired_count][API_ALARM_ID_LEN - 1] = '\0';
    s_fired_count++;
}

/* ---- Public API ---------------------------------------------------------- */

void alarm_scheduler_init(void)
{
    s_queue_len   = 0;
    s_fired_count = 0;
    s_last_phase  = API_PHASE_IDLE;
}

void alarm_scheduler_update(const api_response_t *response)
{
    /* Detect session change: active phase → IDLE means a new session started. */
    if (s_last_phase != API_PHASE_IDLE && response->phase == API_PHASE_IDLE) {
        ESP_LOGI(TAG, "Phase returned to IDLE — resetting fired-ID list");
        alarm_scheduler_reset_session();
    }
    s_last_phase = response->phase;

    time_t now = ntp_sync_get_utc();
    s_queue_len = 0;

    for (int i = 0; i < response->alarm_count; i++) {
        const api_alarm_t *a = &response->alarms[i];

        if (already_fired(a->id)) {
            ESP_LOGD(TAG, "Skipping already-fired alarm '%s'", a->id);
            continue;
        }
        if (a->fire_at <= now) {
            ESP_LOGD(TAG, "Skipping past alarm '%s' (fire_at=%lld now=%lld)",
                     a->id, (long long)a->fire_at, (long long)now);
            continue;
        }

        s_queue[s_queue_len++] = *a;
        ESP_LOGI(TAG, "Queued alarm '%s' type=%s in %llds",
                 a->id, a->type, (long long)(a->fire_at - now));
    }
}

void alarm_scheduler_tick(void)
{
    if (s_queue_len == 0) return;
    if (!ntp_sync_is_synced()) return;

    time_t now = ntp_sync_get_utc();

    for (int i = 0; i < s_queue_len; i++) {
        if (s_queue[i].fire_at <= now && !already_fired(s_queue[i].id)) {
            ESP_LOGI(TAG, "Firing alarm '%s' type=%s", s_queue[i].id, s_queue[i].type);
            mark_fired(s_queue[i].id);

            buzzer_alarm_type_t type = buzzer_alarm_type_from_str(s_queue[i].type);
            buzzer_gpio_play(type);
            led_rgb_flash();

            /* Remove from queue. */
            memmove(&s_queue[i], &s_queue[i + 1],
                    (s_queue_len - i - 1) * sizeof(api_alarm_t));
            s_queue_len--;
            i--;
        }
    }
}

void alarm_scheduler_reset_session(void)
{
    s_fired_count = 0;
    ESP_LOGI(TAG, "Session reset — cleared fired-ID list");
}
