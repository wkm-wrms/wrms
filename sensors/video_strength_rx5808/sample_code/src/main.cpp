#include <Arduino.h>
#include "settings.h"
#include "channels.h"

// --- IMPLEMENTACJA SPI (Bit Banging) ---

static inline void sendBit(uint8_t value) {
    digitalWrite(PIN_SPI_CLOCK, LOW);
    delayMicroseconds(1);
    digitalWrite(PIN_SPI_DATA, value);
    delayMicroseconds(1);
    digitalWrite(PIN_SPI_CLOCK, HIGH);
    delayMicroseconds(1);
    digitalWrite(PIN_SPI_CLOCK, LOW);
    delayMicroseconds(1);
}

static inline void sendBits(uint32_t bits, uint8_t count) {
    for (uint8_t i = 0; i < count; i++) {
        sendBit(bits & 0x1);
        bits >>= 1;
    }
}

static inline void sendSlaveSelect(uint8_t value) {
    digitalWrite(PIN_SPI_SLAVE_SELECT, value);
    delayMicroseconds(1);
}

static inline void sendRegister(uint8_t address, uint32_t data) {
    sendSlaveSelect(LOW);
    sendBits(address, 4);
    sendBit(HIGH); // Enable write
    sendBits(data, 20);
    sendSlaveSelect(HIGH);
    
    digitalWrite(PIN_SPI_CLOCK, LOW);
    digitalWrite(PIN_SPI_DATA, LOW);
}

// Funkcja pomocnicza do ustawienia kanału
void setRxChannel(uint8_t channelIndex) {
    // Pobierz gotową wartość rejestru z pliku channels.cpp
    uint16_t regValue = Channels::getSynthRegisterB(channelIndex);
    
    // Pobierz częstotliwość dla logów
    uint16_t freq = Channels::getFrequency(channelIndex);

    Serial.print("Ustawianie indeksu: ");
    Serial.print(channelIndex);
    Serial.print(" | Czestotliwosc: ");
    Serial.print(freq);
    Serial.println(" MHz");

    // Wyślij do RX5808
    sendRegister(SPI_ADDRESS_SYNTH_A, regValue);
}

// --- GŁÓWNY PROGRAM ---

void setup() {
    Serial.begin(9600);
    Serial.println("Start RX5808 - Fixed Channel R3");

    // Konfiguracja pinów
    pinMode(PIN_SPI_DATA, OUTPUT);
    pinMode(PIN_SPI_SLAVE_SELECT, OUTPUT);
    pinMode(PIN_SPI_CLOCK, OUTPUT);

    // Stan początkowy SPI
    digitalWrite(PIN_SPI_SLAVE_SELECT, HIGH);
    digitalWrite(PIN_SPI_CLOCK, LOW);
    digitalWrite(PIN_SPI_DATA, LOW);

    delay(1000); // Czas na start modułu

    // USTAWIENIE KANAŁU NA STAŁE
    // RaceBand 1 (R1) to 5658 MHz.
    // W tablicy channels.cpp jest to indeks 32.
    setRxChannel(32);
}

void loop() {
    // Nic nie robimy, kanał jest ustawiony na stałe.
}