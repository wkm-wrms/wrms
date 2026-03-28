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
- [ ] **Kanały**: Pełna obsługa kanału Low Band (LB) w warstwie walidacji i matchmakingu.

### 2.3 Udźwiękowienie (Frontend 1)
- [ ] **Text-To-Speech**: Wyczytywanie nicków pilotów na 3 minuty przed startem (z pominięciem zapauzowanych).
- [ ] **Odliczanie**: Głosowe odliczanie ostatnich 10 sekund przelotu.
- [ ] **Interwały**: Pikanie o zmiennej częstotliwości w trakcie 60-sekundowej przerwy między grupami.

### 2.4 Interfejs Użytkownika (UI/UX)
- [ ] **Dashboard**: Wyświetlanie kodu QR z dynamicznym linkiem.
- [ ] **Dashboard**: Oznaczenie wizualne pilotów o statusie "Zapauzowany".
- [x] **Panel Admina**: Implementacja "Pauzy" i "Wznowienia" timera.
- [x] **Bezpieczeństwo**: Implementacja logowania (Authentication) do panelu `/admin`.
- [ ] **Panel Admina**: Brak podglądu historii sesji i generowania raportów po zakończeniu.

### 2.5 Audio i Stabilność
- [x] **Audio Unlock**: Mechanizm wymuszający interakcję użytkownika (przycisk "Start Audio") na tabletach przed rozpoczęciem sesji.
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

## 5. Completed (Done)

| Date | Item |
| :--- | :--- |
| 2026-03-28 | Pylint compliance: all Python files reach 10.00/10. Added docstrings, fixed import order, removed unused imports, replaced deprecated API calls, added pop_archived_heat() public accessor |
| 2026-03-28 | Fixed 7 critical bugs: table names, hashlib encoding, mutable default datetime, dict mutation in remove_pilot, Pydantic Optional defaults, nested DB connections, dead variable |
| 2026-03-28 | Test isolation: WRMS_DB_PATH env var in database.py, conftest.py sets temp DB before app import |
| 2026-03-28 | Full test framework: 146 tests covering UC1-UC8, heat state machine, matchmaking, persistence, FLIGHT→FINISHED |
| 2026-03-28 | Fixed database.py bug: get_group_by_id skips None-mapped channels (prevents ValidationError) |
| 2026-03-28 | Fixed database.py bug: get_session_by_id uses current_group_index not current_group_id (AUTOINCREMENT mismatch) |
| 2026-03-28 | Admin authentication: DB-backed session cookies, login/logout/me/register/set_password/list/remove endpoints, login+register modals on session.html, CLI recovery script (manage_admins.py), 25 functional tests in test_auth.py |
| 2026-03-28 | Admin user management UI: modal on session.html with admin list (change password + remove per row), add account form, change own password form; page reload on logout |
| 2026-03-28 | Cleaned production DB: removed 493 test pilots and 203 test sessions (id>=13, date>=2026-03-28) |
| 2026-03-28 | Refactor: removed Group.group_id, unified group identity on group_sequence; renamed Heat.group_id → group_sequence; added idempotent ALTER TABLE migrations for existing DBs |
| 2026-03-28 | API error responses: replaced all HTTPException raises with {"status": "error", ...} JSON; removed HTTPException import from pilot_api and session_api; updated all affected tests |
| 2026-03-28 | Pause/resume: full implementation — heat.pause()/resume() for PREP and FLIGHT phases, session-level pause/resume, DB persistence (phase_before_pause column), correct timer arithmetic on resume, frontend timer freeze/resume (session.html + dashboard.html), session-status badge updates, 30 new tests in test_pause_resume.py |

## 6. Ideas / Future Improvements

- **Database schema versioning**: Store the current schema version in a dedicated `schema_version` table. The application code declares its expected version. On startup, if the code version is higher than the DB version, apply numbered migration patches in sequence to bring the DB up to date. Every future structural change to the DB (new table, new column, index change) must be accompanied by: (1) updating the `CREATE TABLE` baseline, (2) writing a numbered patch (e.g. `migrations/002_add_risk_factor.sql`), (3) bumping the expected version constant in code.
- **API method naming convention**: All methods in internal classes that are called by the API layer should be prefixed with `api_`. Their docstrings should fully describe accepted parameters and return values (type, shape, meaning).
- ~~**API error responses — no HTTP exceptions**~~ *(done 2026-03-28)*
- **Refactor/split database.py**: The class is large and hard to navigate. Analyse whether it can be split into cohesive submodules (e.g. `db_session.py`, `db_heat.py`, `db_pilot.py`, `db_group.py`) while keeping the public interface stable.
- **HTML refactoring — shared timer logic and consistent DOM naming**: Extract all timer logic into a single shared `timer.js`. Ensure all DOM element IDs follow the same naming convention in both the admin panel and the dashboard. Move visual/styling differences to separate CSS files (`timer.css` for the dashboard, `timer-admin.css` for the admin panel).
- **Code language audit**: Review all code comments and program messages — should be in English (currently mixed Polish/English). See section 1 discrepancies for context.
- **`heat.py`**: Replace deprecated `self.dict()` with `self.model_dump()` (Pydantic v2 warning in all test runs)
- ~~**Admin auth tests**: Add tests for `/api/admin/login` and `/api/admin/verify` endpoints~~ *(done 2026-03-28 — 25 tests in test_auth.py)*
- ~~**Pause/resume**: Implement the 501-returning pause/resume endpoints (session_api.py)~~ *(done 2026-03-28)*
- **Automatic rebalance after pilot removal**: Currently requires manual `/rebalance` call
- **5th pilot Low Band rule**: Full Low Band channel (LB) support in matchmaking
- ~~**Fix audio autoplay in browser**~~ *(done 2026-03-28 — startup modal with "z komunikatami" / "bez dźwięku" choice; silent.mp3 unlocks browser autoplay policy on first gesture)*
- **`is_active` flag semantics**: `session.stop()` sets `current_phase='FINISHED'` but leaves `is_active=True`; consider aligning or documenting

---
*Updated: 2026-03-28 (pause/resume completed)*
