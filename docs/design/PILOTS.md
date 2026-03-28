# PILOTS.md — Specyfikacja modułu zarządzania pilotami

## 1. Cel

Dostarczyć spójny interfejs administracyjny do przeglądania, dodawania, edytowania i usuwania
profili pilotów. Moduł wdraża jednocześnie rozszerzone pola modelu pilota, które będą
wykorzystywane przez algorytm Matchmaking 2.0.

---

## 2. Kontekst i wejście

Panel administratora (`session.html`) zawiera sekcję "Zarządzaj Pilotami". Aktualnie jest tam
pole wyszukiwania + lista wyników z przyciskiem "Dodaj" obok każdego pilota. Obok istniejącego
przycisku "Dodaj nowego pilota" pojawia się nowy przycisk **"Zarządzaj pilotami"** (wyrównany
do prawej). Jego kliknięcie otwiera modal z wbudowanym `<iframe>` ładującym `/pilots.html`.

Dzięki izolacji w iframe, `pilots.html` jest samodzielną stroną: ma własny CSS, własny JS
i komunikuje się z backendem wyłącznie przez API.

---

## 3. Rozszerzone pola modelu pilota

`Pilot` reprezentuje stałą tożsamość osoby — jej callsign, kraj i cechy charakteru latania.
**Sprzęt (VTX, Low Band) jest cechą zgłoszenia na sesję**, nie pilota — dlatego pozostaje
wyłącznie w `ActivePilot.vtx`. Model `Pilot` rozszerzamy tylko o pola, które nie zależą
od konkretnego zestawu sprzętowego.

| Pole          | Typ       | Domyślna | Opis                                                                           |
|---------------|-----------|----------|--------------------------------------------------------------------------------|
| `name`        | `str`     | —        | Unikalny callsign (istniejące)                                                 |
| `country`     | `str`     | `""`     | Dwuliterowy kod kraju (istniejące)                                             |
| `risk_factor` | `int` 1–6 | `3`      | Poziom ryzyka stylu latania (1 = bardzo ostrożny, 6 = agresywny). Stały atrybut pilota używany przy ważeniu grup w Matchmaking 2.0. |
| `notes`       | `str`     | `""`     | Dowolne notatki dla MC (np. uwagi organizacyjne). Niewidoczne publicznie.     |

---

## 4. Funkcjonalność pilots.html

### 4.1 Widok listy

- Tabela ze wszystkimi pilotami: **Nick**, **Kraj**, **Risk**, **Notatki**, **Akcje**
- Wyszukiwarka (live filter po nick) w nagłówku strony
- Przycisk **"+ Dodaj pilota"** otwiera formularz dodawania (inline lub jako drugi panel)
- Każdy wiersz ma przyciski: **Edytuj** (otwiera formularz edycji) i **Usuń** (z potwierdzeniem)
- Pusta lista: komunikat "Brak pilotów w bazie"
- Strona ładuje się automatycznie bez dodatkowej interakcji

### 4.2 Formularz dodawania

Pola:
- **Nick** — wymagane, unikalne
- **Kraj** — opcjonalne, 2–3 znaki (uppercase)
- **Poziom ryzyka** — suwak 1–6 z podpisem wartości, domyślnie 3
- **Notatki** — textarea opcjonalny

Walidacja po stronie frontendu:
- Nick nie może być pusty
- Kraj: jeśli wpisany, musi mieć 1–3 znaki

Akcja: `POST /api/pilot/` → po sukcesie lista odświeża się, formularz czyści.

### 4.3 Formularz edycji

Identyczne pola jak dodawanie, wstępnie wypełnione danymi pilota.
Nick można zmienić (backend waliduje unikalność).

Akcja: `PUT /api/pilot/{pilot_id}` → po sukcesie wiersz w tabeli aktualizuje się.

### 4.4 Usuwanie

Kliknięcie "Usuń" → `confirm()` z tekstem: *"Usunąć pilota [Nick]? Operacja jest nieodwracalna."*
Po potwierdzeniu: `DELETE /api/pilot/{pilot_id}`.

Jeśli pilot jest aktywny w bieżącej sesji, backend zwraca błąd — frontend wyświetla alert z
komunikatem z API.

---

## 5. Zmiany backendowe

### 5.1 Schemat bazy (`pilot` table)

Nowe kolumny dodawane przez idempotentne `ALTER TABLE` (jak `phase_before_pause`):

```sql
ALTER TABLE pilot ADD COLUMN risk_factor INTEGER DEFAULT 3;
ALTER TABLE pilot ADD COLUMN notes TEXT DEFAULT '';
```

### 5.2 Model `Pilot` (pilot.py)

Dodać pola z wartościami domyślnymi:
```python
risk_factor: int = 3
notes:       str = ""
```

### 5.3 Nowe endpointy API (`pilot_api.py`)

| Method | Path | Auth | Opis |
|--------|------|------|------|
| `GET`  | `/api/pilot/` | public | Lista wszystkich pilotów (istniejące) |
| `GET`  | `/api/pilot/{id}` | public | Pobierz pilota (istniejące) |
| `GET`  | `/api/pilot/search/{q}` | public | Szukaj (istniejące) |
| `POST` | `/api/pilot/` | admin | Utwórz pilota (istniejące — rozszerzyć o nowe pola) |
| `PUT`  | `/api/pilot/{id}` | admin | Zaktualizuj dane pilota (nowe) |
| `DELETE` | `/api/pilot/{id}` | admin | Usuń pilota (nowe) |

#### PUT /api/pilot/{id}
Przyjmuje: `name`, `country`, `risk_factor`, `notes`.
Walidacja: name nie pusty, risk_factor w zakresie 1–6.
Zwraca: `{"status": "ok", "pilot": {...}}`.

#### DELETE /api/pilot/{id}
Sprawdza, czy pilot nie jest aktywny w bieżącej sesji (przez `get_session()`).
Jeśli tak: `{"status": "error", "message": "Pilot is active in the current session."}`.
Jeśli nie: usuwa z DB, zwraca `{"status": "ok"}`.

### 5.4 Zmiany w `database.py`

- `add_pilot()` — przyjmuje i zapisuje nowe pola
- `get_pilot_by_id()` / `search_pilots()` — odczytuje nowe kolumny
- `update_pilot(pilot_id, ...)` — nowa metoda UPDATE
- `delete_pilot(pilot_id)` — nowa metoda DELETE

---

## 6. Integracja z session.html

### Przycisk "Zarządzaj pilotami"

W sekcji "Zarządzaj Pilotami" obok przycisku "Dodaj nowego pilota":
```html
<button class="btn btn-secondary" onclick="openPilotsManager()">Zarządzaj pilotami</button>
```

### Modal z iframe

```html
<div id="pilots-modal" class="modal-overlay" style="display:none">
  <div class="modal-box modal-xl">
    <div class="modal-header">
      <h3>Zarządzanie Pilotami</h3>
      <button onclick="closePilotsManager()">✕</button>
    </div>
    <iframe id="pilots-frame" src="/pilots.html" style="width:100%;height:70vh;border:none"></iframe>
  </div>
</div>
```

`openPilotsManager()` ustawia `display:flex` i odświeża iframe (wymuszony reload po każdym
otwarciu, żeby lista była aktualna).

---

## 7. Testy

- `test_pilots_extended.py` (nowy plik):
  - CRUD dla nowych pól: `POST` z risk_factor/vision_system/low_band/notes → `GET` odczytuje poprawnie
  - `PUT /api/pilot/{id}` happy path: zmiana każdego pola
  - `PUT` z duplikatem nicku → error
  - `PUT` z risk_factor=0 lub 7 → error
  - `DELETE` pilota nie będącego w sesji → ok
  - `DELETE` pilota aktywnego w sesji → error
  - `DELETE` nieistniejącego → error
  - Persistence: `add_pilot` z nowymi polami → nowy `RaceDatabase()` odczytuje te same wartości
  - Auth: `PUT` i `DELETE` bez tokenu → 401

---

## 8. Poza zakresem tej iteracji

- Import/export pilotów (CSV)
- Historia startów pilota (ile biegów, w jakich sesjach)
- Zdjęcie/avatar pilota
- Publiczny profil pilota na dashboardzie

---

*Autor: projekt WRMS | Data: 2026-03-29*
