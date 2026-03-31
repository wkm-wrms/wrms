#include "led_rgb.h"

#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"

#define TAG "led_rgb"

static led_state_t   s_current     = LED_STATE_OFF;
static QueueHandle_t s_flash_queue = NULL;

/* ========================================================================== */
#if LED_USE_ONBOARD_SINGLE
/* ---- Single onboard LED backend (plain GPIO, active HIGH) ---------------- */
/*                                                                            */
/*  CONNECTED (GREEN)  → solid on                                             */
/*  DISCONNECTED (RED) → fast blink: 200 ms on / 200 ms off                  */
/*  API down (YELLOW)  → slow blink: 800 ms on / 800 ms off                  */
/* ========================================================================== */

static TaskHandle_t s_blink_task = NULL;

static void blink_task(void *arg)
{
    while (1) {
        led_state_t state = s_current;

        if (state == LED_STATE_GREEN) {
            gpio_set_level(LED_ONBOARD_GPIO, 1);
            vTaskDelay(pdMS_TO_TICKS(200));

        } else if (state == LED_STATE_RED) {
            /* Fast blink — disconnected */
            gpio_set_level(LED_ONBOARD_GPIO, 1);
            vTaskDelay(pdMS_TO_TICKS(200));
            gpio_set_level(LED_ONBOARD_GPIO, 0);
            vTaskDelay(pdMS_TO_TICKS(200));

        } else if (state == LED_STATE_YELLOW) {
            /* Slow blink — API unreachable */
            gpio_set_level(LED_ONBOARD_GPIO, 1);
            vTaskDelay(pdMS_TO_TICKS(800));
            gpio_set_level(LED_ONBOARD_GPIO, 0);
            vTaskDelay(pdMS_TO_TICKS(800));

        } else {
            gpio_set_level(LED_ONBOARD_GPIO, 0);
            vTaskDelay(pdMS_TO_TICKS(200));
        }
    }
}

void led_rgb_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << LED_ONBOARD_GPIO),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    gpio_set_level(LED_ONBOARD_GPIO, 0);

    s_flash_queue = xQueueCreate(4, sizeof(uint8_t));
    xTaskCreate(blink_task, "led_blink", 1024, NULL, 4, &s_blink_task);
    ESP_LOGI(TAG, "Onboard single LED initialised (GPIO%d)", LED_ONBOARD_GPIO);
}

void led_rgb_set(led_state_t state)
{
    s_current = state;
    /* blink_task picks up the new state on its next iteration */
}

void led_rgb_flash(void)
{
    /* Brief off flash — momentarily turn off then let blink_task restore */
    gpio_set_level(LED_ONBOARD_GPIO, 0);
    vTaskDelay(pdMS_TO_TICKS(80));
}

/* ========================================================================== */
#else
/* ---- External GPIO RGB backend (common cathode, GPIO6/7/8) --------------- */
/* ========================================================================== */

static void apply_state(led_state_t state)
{
    /* Common cathode: HIGH = on. */
    gpio_set_level(LED_RED_GPIO,   state == LED_STATE_RED    || state == LED_STATE_YELLOW ? 1 : 0);
    gpio_set_level(LED_GREEN_GPIO, state == LED_STATE_GREEN  || state == LED_STATE_YELLOW ? 1 : 0);
    gpio_set_level(LED_BLUE_GPIO,  0);
}

static void led_task(void *arg)
{
    uint8_t trigger;
    while (1) {
        if (xQueueReceive(s_flash_queue, &trigger, portMAX_DELAY)) {
            apply_state(LED_STATE_OFF);
            vTaskDelay(pdMS_TO_TICKS(100));
            apply_state(s_current);
        }
    }
}

void led_rgb_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << LED_RED_GPIO)
                      | (1ULL << LED_GREEN_GPIO)
                      | (1ULL << LED_BLUE_GPIO),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&io);
    apply_state(LED_STATE_OFF);

    s_flash_queue = xQueueCreate(4, sizeof(uint8_t));
    xTaskCreate(led_task, "led_rgb", 1024, NULL, 4, NULL);
    ESP_LOGI(TAG, "External RGB LED initialised (R=%d G=%d B=%d)",
             LED_RED_GPIO, LED_GREEN_GPIO, LED_BLUE_GPIO);
}

void led_rgb_set(led_state_t state)
{
    s_current = state;
    apply_state(state);
}

void led_rgb_flash(void)
{
    uint8_t trigger = 1;
    xQueueSend(s_flash_queue, &trigger, 0);
}

#endif  /* LED_USE_ONBOARD_SINGLE */
