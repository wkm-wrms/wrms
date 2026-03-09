# Specyfikacja Wymagań Systemu: FPV Training Manager

## 1. Architektura i Przegląd Systemu
System webowy typu klient-serwer, przeznaczony do zarządzania treningami wyścigów dronów FPV, automatycznego przydzielania grup (heatów) i częstotliwości (kanałów) oraz komunikacji wizualno-dźwiękowej z pilotami.

* **Środowisko:** Aplikacja webowa, responsywna (z naciskiem na ekrany tabletów w widoku horyzontalnym dla głównego widoku).
* **Domena docelowa:** `trening.wkm.waw.pl`
* **Preferowane technologie:** Backend oparty na frameworku Symfony (PHP), lekka baza danych SQLite.
* **Komponenty główne:**
    * **Backend (Serwer / API):** Logika biznesowa w Symfony, zarządzanie bazą danych, algorytm przydzielania grup, serwowanie danych przez API.
    * **Webowy Panel Administratora:** Dostępny przez przeglądarkę graficzny interfejs (GUI) zabezpieczony logowaniem dla admina do zarządzania bazą pilotów, logiką treningu i ręcznymi korektami.
    * **Frontend 1 (Kiosk / Tablet):** Zabezpieczony logowaniem, pełnoekranowy widok zarządzania czasem i udźwiękowieniem (fizycznie na miejscu treningu).
    * **Frontend 2 (Public View):** Dostępny publicznie przez dynamiczny QR kod, bezgłośny podgląd na żywo dla widzów/pilotów z poziomu ich własnych smartfonów.

---

## 2. Modele Danych (Struktura relacyjna)

### 2.1. Model: Pilot (Dane globalne profilu)
* `id`: UUID/Int
* `callsign`: String, unikalny - Nick pilota.
* `avatar`: String/URL, opcjonalny - Zdjęcie pilota.
* `vision_system`: Enum/Int - System wizji warty określoną liczbę punktów (Analog = 1 pkt, Walksnail = 4 pkt, DJI O4 = 4 pkt, HDZero = 5 pkt).
* `risk_factor`: Int - Wskaźnik nadawany przez admina w zakresie 1-6 pkt. (Pole niejawne dla frontendu).
* `low_band`: Boolean - Flaga określająca, czy pilot może lecieć na dolnym paśmie. (Pole niejawne dla frontendu).

### 2.2. Model: Trening (Wydarzenie)
* `id`: UUID/Int
* `date`: DateTime - Data i czas rozpoczęcia treningu.
* `status`: Enum - Planowany, W trakcie, Zakończony.
* `qr_token`: String - Dynamiczny token do wygenerowania publicznego linku dla Frontendu 2 (aktywny tylko gdy trening ma status "W trakcie").

### 2.3. Model: Uczestnictwo (Powiązanie Pilota z konkretnym Treningiem)
* `id`: UUID/Int
* `training_id`: Klucz obcy (FK) powiązany z modelem Trening.
* `pilot_id`: Klucz obcy (FK) powiązany z modelem Pilot.
* `status`: Enum - Aktywny, Zapauzowany, Usunięty. *(Status dotyczy wyłącznie obecności i stanu pilota na tym konkretnym treningu).*
* `current_group`: Int (opcjonalnie) - Numer aktualnie przypisanej grupy na danym treningu.
* `current_channel`: String/Int (opcjonalnie) - Aktualnie przypisany kanał.

---

## 3. Wymagania Funkcjonalne

### 3.1. Algorytm Przydzielania Grup (Matchmaking)
System automatycznie dzieli pilotów biorących udział w treningu (posiadających status "Aktywny" w tabeli Uczestnictwo) na grupy na podstawie wag i priorytetów (kolejność od najwyższego priorytetu):

1. **Rozmiar grup i wyjątek dla 5 pilotów:** Standardowy rozmiar grupy to 4 osoby. System zasadniczo nie tworzy grup 1- lub 2-osobowych, **z jednym ścisłym wyjątkiem**: jeśli w treningu bierze udział dokładnie 5 pilotów (i żaden nie ma flagi `low_band` pozwalającej na lot w 5 osób), system dzieli ich na dwie grupy: jedną 3-osobową i jedną 2-osobową.
2. **Grupowanie cyfrowe:** Wszyscy piloci z systemami cyfrowymi (O4, WS, HDZero) powinni, w miarę możliwości, znajdować się w tych samych grupach.
3. **Mieszanie Analog/Cyfra:** Jeśli w grupie znajduje się system analogowy oraz cyfrowy, pilotom analogowym przydzielane są kanały od 1 do 3.
4. **Sortowanie kanałów wg punktów:** System sumuje punkty pilota (punkty za `vision_system` + punkty za `risk_factor`). Piloci z wyższą łączną sumą punktów otrzymują wyższe numery kanałów w ramach swojej grupy.
5. **Zasada "Low Band":** Pilot oznaczony flagą `low_band` może zostać dołączony do pełnej grupy jako 5. zawodnik (maksymalnie 1 taki pilot na grupę).

### 3.2. Webowy Panel Administratora i Kontrola Treningu
* **Interfejs:** Aplikacja webowa dostępna z poziomu przeglądarki (np. pod adresem `/admin`), wymagająca konta z uprawnieniami administratora.
* **Baza Pilotów:** Moduł do zarządzania globalnymi danymi pilotów (dodawanie nowych, modyfikacja `risk_factor`, `vision_system`, itp.).
* **Zarządzanie na żywo (Live Control):**
    * **Dodanie lub Usunięcie pilota:** System natychmiastowo i automatycznie przelicza ponownie wszystkie grupy według algorytmu z pkt 3.1.
    * **Pauza pilota:** Zmiana statusu pilota na "Zapauzowany" **nie powoduje** ponownego przeliczenia grup. Pilot pozostaje przypisany do swojej dotychczasowej grupy (utrzymując jej strukturę), ale jest traktowany przez system jako chwilowo nieaktywny w danej rotacji.
    * **Ręczny "Override":** Możliwość ręcznego przydzielenia kanału lub przeniesienia pilota do innej grupy (nadpisuje to zasady algorytmu).
* **Historia:** Zapisywanie przeprowadzonych treningów do bazy z możliwością ich późniejszego odtworzenia lub podglądu, z zachowaniem przypisanych wtedy grup.

### 3.3. Frontend 1 (Widok Główny - Kiosk/Tablet)
* **Dostęp:** Wymaga uwierzytelnienia (login/hasło).
* **Wyświetlanie (tryb Full Screen):**
    * Aktywna grupa: lista pilotów wraz z przypisanymi im kanałami. Widoczne oznaczenie wizualne dla pilotów zapauzowanych.
    * Następna grupa w kolejce: lista pilotów i ich kanały.
    * Duży, czytelny z daleka minutnik odliczający czas do końca przelotu aktywnej grupy.
    * **Kod QR:** Widoczny przez cały czas na ekranie (np. w jednym z rogów), zawierający link do Frontendu 2, co umożliwia ciągłe skanowanie przez pilotów w dowolnym momencie.
* **Zarządzanie czasem i udźwiękowienie:**
    * Na 3:00 minuty przed końcem: Komunikat głosowy czytający callsigny pilotów z następnej grupy. **System bezwzględnie pomija podczas wyczytywania tych pilotów, którzy mają w danej chwili status "Zapauzowany".**
    * Ostatnie 10 sekund: Odliczanie głosowe od 10 do 0.
    * Przerwa między grupami (60 sekund): Interwałowe pikanie, którego częstotliwość rośnie z upływem czasu. W ostatnich 5 sekundach przerwy sygnał emitowany jest dokładnie co 1 sekundę.

### 3.4. Frontend 2 (Widok Publiczny / Osobisty dla pilotów)
* **Dostęp:** Bez logowania. Adres URL generowany dynamicznie na bazie tokena aktywnego treningu.
* **Wejście:** Zeskanowanie kodu QR z Frontendu 1.
* **Wyświetlanie:** Stan obecny treningu (kto leci, kto się przygotowuje, aktualny czas). Wymaga komunikacji w czasie rzeczywistym, aby dane odświeżały się synchronicznie z tabletem.
* **Brak udźwiękowienia:** W przeciwieństwie do Frontendu 1, na tym widoku **nie będą odtwarzane żadne komunikaty głosowe ani sygnały dźwiękowe**.
* **Cykl życia linku:** Po zamknięciu treningu w panelu admina (zmiana statusu w tabeli Trening na "Zakończony"), link z kodu QR ulega dezaktywacji.

---

## 4. Wymagania Niefunkcjonalne
* **Synchronizacja czasu:** Odliczanie powinno być realizowane po stronie serwera i synchronizowane z klientami, aby zapobiec rozjazdom na różnych urządzeniach.
* **Zarządzanie dźwiękiem (tylko Frontend 1):** Przeglądarki mobilne blokują autoodtwarzanie dźwięku. Developer musi wdrożyć przycisk np. "Start Treningu" lub "Inicjuj Audio" inicjujący system dźwiękowy po zalogowaniu na tablecie.
* **Baza danych:** **SQLite** – ze względu na prostotę struktury i wystarczającą wydajność dla tego zastosowania jest to preferowane rozwiązanie.
