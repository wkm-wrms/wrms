#include "buzzer_gpio.h"

#include <string.h>
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"

#define TAG "buzzer_gpio"

/* ---- Beep pattern primitives -------------------------------------------- */

/*
 * A pattern is a sequence of (on_ms, off_ms) pairs terminated by {0, 0}.
 * The buzzer is driven HIGH for on_ms then LOW for off_ms.
 */
typedef struct { int on_ms; int off_ms; } beep_t;

/* See BUZZER.md section 5.2 for timing rationale. */

static const beep_t PAT_PREP_START[] = {
    {100, 200}, {100, 200}, {0, 0}
};

static const beep_t PAT_FLIGHT_START[] = {
    {800, 0}, {0, 0}
};

static const beep_t PAT_WARNING_30[] = {
    {100, 150}, {100, 150}, {100, 150}, {0, 0}
};

static const beep_t PAT_COUNTDOWN[] = {
    {80, 0}, {0, 0}
};

static const beep_t PAT_FLIGHT_END[] = {
    /* long–short–short: 700 / 150 / 200 / 150 / 200 */
    {700, 200}, {150, 200}, {150, 0}, {0, 0}
};

static const beep_t PAT_SESSION_END[] = {
    {600, 400}, {600, 400}, {600, 400}, {0, 0}
};

static const beep_t PAT_ERROR[] = {
    {100, 100}, {100, 100}, {100, 0}, {0, 0}
};

/* ---- Task queue ---------------------------------------------------------- */

static QueueHandle_t s_queue;

static void buzzer_task(void *arg)
{
    const beep_t *pat;
    while (1) {
        if (xQueueReceive(s_queue, &pat, portMAX_DELAY)) {
            for (int i = 0; pat[i].on_ms > 0 || pat[i].off_ms > 0; i++) {
                gpio_set_level(BUZZER_GPIO, 1);
                vTaskDelay(pdMS_TO_TICKS(pat[i].on_ms));
                gpio_set_level(BUZZER_GPIO, 0);
                if (pat[i].off_ms > 0) {
                    vTaskDelay(pdMS_TO_TICKS(pat[i].off_ms));
                }
            }
        }
    }
}

/* ---- Type string mapping ------------------------------------------------- */

buzzer_alarm_type_t buzzer_alarm_type_from_str(const char *type_str)
{
    if (!type_str) return BUZZER_ALARM_UNKNOWN;
    if (strcmp(type_str, "PREP_START")         == 0) return BUZZER_ALARM_PREP_START;
    if (strcmp(type_str, "FLIGHT_START")        == 0) return BUZZER_ALARM_FLIGHT_START;
    if (strcmp(type_str, "FLIGHT_WARNING_30")   == 0) return BUZZER_ALARM_FLIGHT_WARNING_30;
    if (strcmp(type_str, "COUNTDOWN")           == 0) return BUZZER_ALARM_COUNTDOWN;
    if (strcmp(type_str, "FLIGHT_END")          == 0) return BUZZER_ALARM_FLIGHT_END;
    if (strcmp(type_str, "SESSION_END")         == 0) return BUZZER_ALARM_SESSION_END;
    return BUZZER_ALARM_UNKNOWN;
}

/* ---- Public API ---------------------------------------------------------- */

void buzzer_gpio_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << BUZZER_GPIO),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    gpio_set_level(BUZZER_GPIO, 0);

    s_queue = xQueueCreate(8, sizeof(const beep_t *));
    xTaskCreate(buzzer_task, "buzzer", 2048, NULL, 5, NULL);
    ESP_LOGI(TAG, "Buzzer initialised on GPIO %d", BUZZER_GPIO);
}

void buzzer_gpio_play(buzzer_alarm_type_t type)
{
    const beep_t *pat;
    switch (type) {
        case BUZZER_ALARM_PREP_START:         pat = PAT_PREP_START;   break;
        case BUZZER_ALARM_FLIGHT_START:       pat = PAT_FLIGHT_START; break;
        case BUZZER_ALARM_FLIGHT_WARNING_30:  pat = PAT_WARNING_30;   break;
        case BUZZER_ALARM_COUNTDOWN:          pat = PAT_COUNTDOWN;    break;
        case BUZZER_ALARM_FLIGHT_END:         pat = PAT_FLIGHT_END;   break;
        case BUZZER_ALARM_SESSION_END:        pat = PAT_SESSION_END;  break;
        default:
            ESP_LOGW(TAG, "Unknown alarm type %d — ignoring", type);
            return;
    }
    xQueueSend(s_queue, &pat, 0);
}

void buzzer_gpio_error_beep(void)
{
    const beep_t *pat = PAT_ERROR;
    xQueueSend(s_queue, &pat, 0);
}
