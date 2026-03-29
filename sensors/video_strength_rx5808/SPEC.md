# SPECYFIKACJA TECHNICZNA: FPV LAP TIMER & TELEMETRY SYSTEM (ESP32 + RX5808)

## 1. OPIS PROJEKTU
Projekt obejmuje budowę autonomicznego systemu pomiaru czasu okrążeń dla dronów wyścigowych. System bazuje na analizie mocy sygnału wideo (RSSI) w paśmie 5.8 GHz. Urządzenie wykrywa moment minięcia bramki (Peak), rejestruje czas, przechowuje rekordy w pamięci nieulotnej i przesyła dane w czasie rzeczywistym przez protokół ESP-NOW.

---

## 2. ARCHITEKTURA SPRZĘTOWA (BOM)

### 2.1 Lista komponentów
| Lp. | Element | Specyfikacja | Ilość |
|:---:|:---|:---|:---:|
| 1 | Mikrokontroler | ESP32 DevKit V1 (30-pin) | 1 szt. |
| 2 | Odbiornik Video | Moduł RX5808 (wymagana modyfikacja SPI) | 1 szt. |
| 3 | Wyświetlacz | OLED 0.96" SSD1306 (I2C, 128x64) | 1 szt. |
| 4 | Zasilanie | Przetwornica Buck MP1584EN (ustawiona na 5.0V) | 1 szt. |
| 5 | Sygnalizacja | Buzzer aktywny 5V | 1 szt. |
| 6 | Antena | 5.8 GHz (Dipol lub koniczynka) | 1 szt. |

### 2.2 Schemat połączeń
| Moduł | Pin | ESP32 GPIO | Funkcja |
|:---|:---|:---|:---|
| **RX5808** | CH1 | **GPIO 23** | SPI DATA (MOSI) |
| **RX5808** | CH2 | **GPIO 18** | SPI CLK (SCK) |
| **RX5808** | CH3 | **GPIO 5** | SPI LE (Latch Enable) |
| **RX5808** | RSSI | **GPIO 34** | Analog Out (ADC1) |
| **OLED** | SDA | **GPIO 21** | I2C Data |
| **OLED** | SCL | **GPIO 22** | I2C Clock |
| **Buzzer** | (+) | **GPIO 4** | PWM / Digital Out |

### 2.3 Modyfikacja modułu RX5808 (KRYTYCZNE)
Moduł musi zostać przełączony w tryb SPI. W tym celu należy:
1. Zdjąć metalową osłonę ekranującą.
2. Usunąć rezystor pull-down (zazwyczaj 1kΩ lub 0Ω) połączony z pinem **CH1**.
3. Sprawdzić miernikiem, czy pin CH1 nie ma już przejścia do masy (GND).

---

## 3. SPECYFIKACJA KOMUNIKACJI I REJESTRÓW

### 3.1 Protokół SPI (RTC6705)
Komunikacja odbywa się za pomocą 25-bitowych ramek (LSB First).
* **Struktura ramki:** `[4 bity ADRES] [1 bit R/W] [20 bitów DANE]`.
* **Adres rejestru syntezatora (A):** `0x01`.

### 3.2 Matematyka częstotliwości (PLL)
Ustawienie kanału wymaga obliczenia wartości dla syntezatora zgodnie ze wzorem:
$$f_{RF} = 2 \cdot (N \cdot 32 + A) + 479 \text{ MHz}$$
Dla pasma Raceband 3 (5732 MHz), gotowy kod HEX do wysłania to: `0x44016F5`.

---

## 4. ANALIZA SYGNAŁU I LOGIKA WYKRYWANIA PEAKU

### 4.1 Oversampling (Uśrednianie)
Aby zminimalizować szum ADC, stosujemy średnią arytmetyczną z 32 szybkich próbek:
$$RSSI_{avg} = \frac{1}{32} \sum_{i=1}^{32} RSSI_i$$

### 4.2 Algorytm detekcji Peak (Moment minięcia)
System wykorzystuje automat stanowy z dynamicznym progiem:
1. **Trigger:** Wejście w tryb śledzenia, gdy $RSSI > RSSI_{floor} + 150$.
2. **Peak:** Rejestracja najwyższej wartości ($maxRSSI$).
3. **Potwierdzenie:** Uznanie przelotu, gdy sygnał spadnie o wartość **Histerezy** ($H = 40$) poniżej $maxRSSI$.

---

## 5. ZASILANIE I AUTONOMIA
* **Pobór prądu:** Średnio 400mA (0.4A).
* **Wymagany czas pracy:** 6 godzin.
* **Minimalna pojemność baterii:** 2400 mAh (przy 5V użytecznym).
* **Rekomendacja:** Pakiet 2x 18650 Li-Ion (ok. 3000mAh) zapewni ok. 7.5h pracy.

---

## 6. KOD ŹRÓDŁOWY (ZARYS IMPLEMENTACJI)

```cpp
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Preferences.h>
#include <esp_now.h>
#include <WiFi.h>

// Konfiguracja sprzętowa
Adafruit_SSD1306 display(128, 64, &Wire, -1);
Preferences preferences;

// Dane telemetrii
typedef struct { float rssi; float lap; bool peak; } msg;
msg data;
uint8_t targetAddress[] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

void setup() {
  // Inicjalizacja SPI dla RX5808, OLED i NVS (Best Lap)
  preferences.begin("laptimer", false);
  float best = preferences.getFloat("best", 0.0);
  
  WiFi.mode(WIFI_STA);
  esp_now_init();
  // ... reszta inicjalizacji
}

void loop() {
  // 1. Próbkowanie RSSI (uśrednione)
  // 2. Logika detekcji Peak (histereza)
  // 3. Obsługa buzzera i zapisu do pamięci Flash
  // 4. Wysyłanie telemetrii via ESP-NOW co 50ms
}

## WYTYCZNE DLA WYKONAWCY
1. **Filtracja zasilania**: Należy zastosować kondensator 470uF na wejściu 5V modułu RX5808 (redukcja szumów obrazu/RSSI).

2. ** Chłodzenie**: RX5808 grzeje się podczas pracy – zapewnić radiator lub wentylację obudowy.

3.  **Kalibracja**: Każdorazowo po włączeniu system musi wykonać 3-sekundowy pomiar szumu tła (bez włączonych dronów w okolicy).
