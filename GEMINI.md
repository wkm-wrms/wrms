# Projekt WRMS - Kontekst Gemini Code Assist

## Status Projektu (2026-03-28)
System zarządzania treningami FPV (FastAPI + SQLite). Wykonano migrację założeń z PHP do Pythona.

## Kluczowe Decyzje Architektoniczne
1. **Separacja Group vs Heat**: 
   - `Group` to szablon (Roster). `move_pilot` operuje na grupach.
   - `Heat` to instancja biegu. Tworzony jako snapshot grupy (`channels.copy()`). Zmiana w grupie w trakcie trwania biegu nie wpływa na trwający bieg.
2. **Zarządzanie Czasem**:
   - Brak SSE (ograniczenia hostingu). Dashboard i Admin polegają na pollingu `/api/heat`.
   - Czas `live_seconds_left` wyliczany dynamicznie na backendzie względem `flight_started_at`.
3. **Fazy Sesji**:
   - Sesja posiada fazę `FLIGHT`, która na poziomie Heat rozbija się na `PREP` i `FLIGHT`.
4. **Kanał Low Band (LB)**:
   - Podjęto decyzję o odłożeniu implementacji kanału LB. System aktualnie obsługuje 4 standardowe kanały Raceband (R1, R3, R6, R7).

## Ostatnie Zmiany
- Implementacja `skip_heat` (rotacja grup i archiwizacja biegów).
- Usunięcie martwych plików JS/HTML (logika przeniesiona do inline w `session.html`).
- Dodanie pełnej dokumentacji API (`docs/API.md`).
- Dodanie testów funkcjonalnych (`code/tests/`).

## Roadmapa (TODO)
1. **Autentykacja**: Zabezpieczenie `/admin` (Faza 1).
2. **Stabilizacja Audio**: Przycisk "Inicjuj Audio" dla tabletów (Faza 1).
3. **Matchmaking 2.0**: Implementacja wag `risk_factor` i `vision_system` (Faza 2).
4. **TTS**: Wyczytywanie nicków przez Web Speech API (Faza 3).

## Struktura Bazy (SQLite)
- `pilot`: Dane globalne.
- `session`: Stan sesji.
- `active_pilot`: Powiązanie pilota z sesją (VTX).
- `heat` / `pilot_heat`: Historia i snapshoty biegów.

## Jak uruchomić testy
Najlepszym sposobem na uruchomienie testów jest przejście do katalogu `code` i wywołanie pytest:
```bash
cd code && pytest tests/test_functional.py
```

---
*Zachowaj ten plik, aby utrzymać ciągłość wiedzy o snapshotach biegów i logice matchmakingu.*
