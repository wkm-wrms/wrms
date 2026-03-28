# Raport Rozbieżności i Lista TODO - WRMS

Na podstawie analizy plików `requirements.md` oraz `use cases.md` względem aktualnej implementacji kodu.

## 1. Rozbieżności Krytyczne (Inna implementacja)

| Funkcja | Stan w Dokumentacji | Stan w Kodzie |
| :--- | :--- | :--- |
| **Algorytm Matchmaking** | Sortowanie kanałów wg sumy punktów (Vision + Risk) | Prosty podział: Analogi (niskie), Cyfry (wysokie) |
| **Pauza Pilota** | Zmiana statusu na "Zapauzowany" bez przeliczania grup | Brak statusu "Zapauzowany" (jest tylko usunięcie) |
| **Zasada 5 pilotów** | Podział 3+2 przy braku Low Band | Podział 4+1 (wynikający z math.ceil) |
| **Zasada Low Band** | Pilot LB jako 5. w grupie | Pilot LB zajmuje standardowy slot (jeśli dostępny) |
| **Obsługa Błędów** | Ujednolicone komunikaty API | Rozbieżność między `HTTPException` a słownikami `{"status": "error"}` |

### 2.1 Modele Danych
- [ ] **Pilot**: Dodanie pól `risk_factor` (1-6) oraz `vision_system` (mapowanie punktowe: Analog=1, DJI/WS=4, HDZero=5).
- [ ] **Sesja**: Implementacja `qr_token` do generowania dynamicznych linków publicznych.
- [ ] **Uczestnictwo**: Pełna obsługa statusu `Zapauzowany` dla pilota wewnątrz sesji.

### 2.2 Algorytm (Matchmaking 2.0)
- [ ] Implementacja grupowania systemów cyfrowych w pierwszej kolejności.
- [ ] Logika "5. zawodnika" dla osób z flagą `low_band`.
- [ ] Automatyczny rebalancing po usunięciu pilota (obecnie wymagane ręczne wywołanie `/rebalance`).

### 2.3 Udźwiękowienie (Frontend 1)
- [ ] **Text-To-Speech**: Wyczytywanie nicków pilotów na 3 minuty przed startem (z pominięciem zapauzowanych).
- [ ] **Odliczanie**: Głosowe odliczanie ostatnich 10 sekund przelotu.
- [ ] **Interwały**: Pikanie o zmiennej częstotliwości w trakcie 60-sekundowej przerwy między grupami.

### 2.4 Interfejs Użytkownika (UI/UX)
- [ ] **Dashboard**: Wyświetlanie kodu QR z dynamicznym linkiem.
- [ ] **Dashboard**: Oznaczenie wizualne pilotów o statusie "Zapauzowany".
- [ ] **Panel Admina**: Brak implementacji "Pauzy" i "Wznowienia" timera (obecnie zwracają 501).
- [ ] **Bezpieczeństwo**: Implementacja logowania (Authentication) do panelu `/admin`.
- [ ] **Panel Admina**: Brak podglądu historii sesji i generowania raportów po zakończeniu.

### 2.5 Audio i Stabilność
- [ ] **Audio Unlock**: Mechanizm wymuszający interakcję użytkownika (przycisk "Start Audio") na tabletach przed rozpoczęciem sesji.
- [ ] **Frontend 2**: Widok publiczny oparty na tokenie.

## 3. Roadmapa Wdrożenia

### Faza 1: Fundamenty i Bezpieczeństwo (Priorytet: Krytyczny)
1. **Autentykacja**: Dodanie prostego mechanizmu logowania do `/admin` (zgodnie z `database.py:verify_admin`).
2. **Stabilizacja UI**: Implementacja przycisku "Inicjuj Audio" na tablecie, aby odblokować API dźwięku w przeglądarce.
3. **Synchronizacja czasu**: Zastąpienie SSE zoptymalizowanym pollingiem (krótki interwał dla aktywnego biegu).

### Faza 2: Logika Wyścigowa (Priorytet: Wysoki)
1. **Rozszerzenie modelu Pilota**: `risk_factor` i `vision_system`.
2. **Matchmaking 2.0**: Implementacja pełnego algorytmu wagowego (Vision + Risk) oraz obsługi Low Band jako 5. zawodnika.
3. **Statusy**: Obsługa statusu "Zapauzowany" dla uczestnictwa w sesji.

### Faza 3: Automatyzacja i Multimedia (Priorytet: Średni)
1. **Komunikaty TTS**: Implementacja wyczytywania nicków przez Web Speech API.
2. **Pauza/Wznowienie**: Implementacja logiki zatrzymywania zegara w `session_api.py`.
3. **Raportowanie**: Zapisywanie wyników przelotów i eksport do podsumowania sesji.

## 4. Uwagi Techniczne
- **SSE**: Zrezygnowano z technologii Server-Sent Events z powodu ograniczeń hostingu dzielonego. System będzie polegał na zapytaniach HTTP GET (polling).
- **Prywatny Ekran Pilota**: Całkowity brak implementacji (scenariusz "Pilot uruchamia prywatny ekran monitorujący").

---
*Raport zaktualizowany: 2026-03-28 przez Gemini Code Assist*
