#ifndef SETTINGS_H
#define SETTINGS_H

#include <Arduino.h>

// Definicja pinów (dostosuj do swojego połączenia)
#define PIN_SPI_DATA         11  // MOSI / CH1
#define PIN_SPI_SLAVE_SELECT 10  // SS / CS / CH2
#define PIN_SPI_CLOCK        13  // SCK / CH3

// Stała adresu syntezatora RX5808
#define SPI_ADDRESS_SYNTH_A 0x01

#endif