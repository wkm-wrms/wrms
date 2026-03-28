# Dokumentacja API WRMS (WKM Racing Management System)
# Dokumentacja API WRMS (WKM Racing Management System)

## Zasady ogólne
- **Format**: JSON.
- **Nagłówki**: `Content-Type: application/json` dla żądań POST.
- **Format Odpowiedzi**: Każda odpowiedź zawiera klucz `status` ("ok" lub "error"). W przypadku błędu, klucz `message` lub `detail` zawiera opis problemu.

---

## 1. Zarządzanie Sesją (`/api/session`)

### POST `/api/session`
Tworzy nową sesję wyścigową.
**Input**:
```json
{
  "name": "string",
  "flight_duration_sec": 600,
  "prep_duration_sec": 120
}
```
**Output**: `{"status": "ok", "session": {...}}`

### GET `/api/session`
Pobiera aktualną sesję.
**Kluczowe pola dla UI**:
- `.session.name`: Nazwa sesji.
- `.session.current_phase`: Faza główna (`IDLE`, `FLIGHT`, `PAUSED`, `FINISHED`).
- `.session.active_pilots`: Słownik wszystkich pilotów biorących udział w sesji.

### POST `/api/session/start`
Uruchamia pierwszy bieg i odliczanie czasu.

### POST `/api/session/skip_heat`
Kończy aktualny bieg (nawet jeśli czas nie upłynął) i przechodzi do fazy przygotowania następnej grupy.

---

## 2. Zarządzanie Grupami (`/api/groups`)

### POST `/api/groups/move_pilot`
Główna metoda do zarządzania rosterem (Drag & Drop).
**Input**:
```json
{
  "pilot_id": 123,
  "from_group": 1,      // null jeśli z paddocku
  "from_channel": "R1", // null jeśli z paddocku
  "to_group": 2,        // null jeśli do paddocku
  "to_channel": "R3"    // null jeśli do paddocku
}
```
**Logika**: Jeśli `to_channel` w `to_group` jest zajęty, pilot tam przebywający zostaje usunięty z grupy (trafia do paddocku).

### POST `/api/groups/rebalance`
Automatycznie rozdziela pilotów do grup według algorytmu.

---

## 3. Monitorowanie Biegu (`/api/heat`)

### GET `/api/heat`
Najważniejszy endpoint dla Dashboardu (polling co ~1s).
**Output**:
```json
{
  "status": "ok",
  "heat": {
    "heat_number": 5,
    "status": "FLIGHT",        // PREP lub FLIGHT
    "live_seconds_left": 45.5, // Czas do końca fazy
    "channels": {
      "R1": {
        "pilot": { "name": "Boczi" },
        "vtx": "Analog"
      }
    }
  },
  "next_heat": { ... }         // Dane następnego zaplanowanego biegu
}
```

---

## 4. Baza Pilotów (`/api/pilot`)

### POST `/api/pilot`
Rejestruje nowego pilota w systemie.
**Input**: `{"name": "Nick", "country": "PL"}`

### GET `/api/pilot/search/{query}`
Wyszukiwanie pilotów do dodania do sesji.

---

## Definicje Struktur

### ActivePilot (Obiekt wewnątrz sesji/heat)
- `pilot_id`: int
- `pilot`: Obiekt Pilot (dane bazowe)
- `vtx`: string (np. "Analog", "DJI", "HD0")
- `is_digital`: bool

### Group
- `group_id`: int
- `group_sequence`: int (kolejność wyświetlania)
- `channels`: Słownik `{ "KANAŁ": ActivePilot }`
```

| **POST** | `` | Tworzy nową sesję | `session_id`, `status` || **POST** | `/start` | Uruchamia cykl wyścigowy | `status`, `message` |
*POST** | `/stop` | Kończy sesję | `status` |
| **POST** | `/skip_heat`| Przeskakuje d| **POST** | `/add_pilot` | Dodaje pilota do sesji | `pilot_id`, `vtx` (payload) |
lota z sesji | `pilot_id` (payload) |

### Uwagi do optymalizacji GUI:
Obecnie `GET /api/session` zwraca pełne obiekty `ActivePilot` (wraz z historią). GUI używa jedynie `pilot.name` i `vtx`. Można zredukować ten obiekt do formy uproszczonej.

## 2. Zarządzanie Grupami (`/api/groups`)

| Metoda | Endpoint | Opis | Główne pola używane przez GUI |
| :--- | :--- | :--- | :--- |
| **GET** | `` | Pobiera listę grup | `group_sequence`, `channels` |
mi (`/api/pilot`)
| **GET** | `/` | Lista wszystkich pilotów | `pilot_id`, `name` |
| **POST** | `/` | Tworzy profil pilota | `name` (payload) -> zwraca `id` | --

## Struktura Danych (Minimalna dla GUI)

```

### Session
Wymagane do renderowania Paddocku i Rostera:
```json
{
  "name": "Event Name",  "current_phase": "FLIGHT",
active_pilots": { "ID": { "pilot": {"name": "..."}, "vtx": "..." } },
  "groups": [    {
uence": 1,
      "channels": { "R1": { ... } }
    }
  ]
}
```  "next_heat": { ...analogiczna struktura... }
}
``

  "heat_number": 1,
  "live_seconds_left": 115.5,
  "channels": {

#W

  a"satus"PREP"heatnmber
"liv_os_eft":115.5,s {
   :{pilo{nmNick,"vx":"Ag}  }}`SessonWymg dredraPadcku RoternmeEvnt Nme,curren_phe"civepilots{"ID":{pit": {"am".."}"vx":"..."}},group[grou_sequec1chanes:{"R1":{...}]
```