idf_component_register(
    SRCS
        "main.c"
        "nvs_config.c"
        "wifi_manager.c"
        "captive_portal.c"
        "ntp_sync.c"
        "api_client.c"
        "alarm_scheduler.c"
        "buzzer_gpio.c"
        "led_rgb.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES
        nvs_flash
        esp_event
        esp_netif
        esp_wifi
        esp_http_client
        esp_http_server
        lwip
        driver
        json
)
# led_strip is a managed component declared in idf_component.yml
