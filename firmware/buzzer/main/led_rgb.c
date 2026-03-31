#include "led_rgb.h"

#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"

#define TAG "led_rgb"

static led_state_t s_current = LED_STATE_OFF;
static QueueHandle_t s_flash_queue;

/* ---- GPIO helpers -------------------------------------------------------- */

static void apply_state(led_state_t state)
{
    /* Common cathode: HIGH = on. For common anode, invert these. */
    gpio_set_level(LED_RED_GPIO,   state == LED_STATE_RED    || state == LED_STATE_YELLOW ? 1 : 0);
    gpio_set_level(LED_GREEN_GPIO, state == LED_STATE_GREEN  || state == LED_STATE_YELLOW ? 1 : 0);
    gpio_set_level(LED_BLUE_GPIO,  0);
}

/* ---- Flash task ---------------------------------------------------------- */

static void led_task(void *arg)
{
    uint8_t trigger;
    while (1) {
        if (xQueueReceive(s_flash_queue, &trigger, portMAX_DELAY)) {
            /* Brief off then back to current state — gives a visible blink. */
            apply_state(LED_STATE_OFF);
            vTaskDelay(pdMS_TO_TICKS(100));
            apply_state(s_current);
        }
    }
}

/* ---- Public API ---------------------------------------------------------- */

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
    ESP_LOGI(TAG, "RGB LED initialised (R=%d G=%d B=%d)",
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
