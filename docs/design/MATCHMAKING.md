# Matchmaking 2.0 — Functional Specification Document

**Status:** Draft
**Author:** AI-assisted (claude-sonnet-4-6)
**Date:** 2026-03-29
**Based on:** `requirements.md` §3.1, `use cases.md` UC-Matchmaking, aktualny kod (`session.py`, `activepilot.py`, `pilot.py`)

---

## 1. Cel i kontekst

Matchmaking 1.0 (aktualny) przydziela pilotów do grup wyłącznie na podstawie liczby i typu systemu wizji (digital/analog). Nie uwzględnia:
- priorytetu grupowania cyfrowych razem (requirement 3.1.2),
- punktowej hierarchii kanałów w ramach grupy (requirement 3.1.4).

Matchmaking 2.0 dodaje te dwa brakujące wymiary **bez naruszania istniejącego interfejsu API i modeli danych**.

### Poza zakresem tego dokumentu

- **Low Band** (flaga `low_band`, 5. zawodnik w grupie) — odłożone świadomie, zostanie opisane oddzielnie po ustaleniu modelu danych.
- Ręczny override przydziału grup (UC: "Ręczna modyfikacja") — istniejący mechanizm move/drag pozostaje bez zmian.
- Automatyczny rebalancing po usunięciu pilota — osobny ticket.

---

## 2. Dane wejściowe

Algorytm operuje na kolekcji `Session.active_pilots: dict[int, ActivePilot]`.

Każdy `ActivePilot` zawiera:

| Pole | Typ | Źródło |
|---|---|---|
| `vtx` | `str` | przekazywane przy `add_pilot` |
| `is_digital` | `bool` | `vtx != "Analog"` |
| `pilot.risk_factor` | `int` 1–6 | profil pilota w DB |

Brakujący element potrzebny do obliczeń: **punkty za system wizji**. Nie ma osobnego pola `vision_points` — są derywowane z `vtx` za pomocą stałej tabeli mapowania.

### 2.1 Kanoniczne wartości `vtx` i ich punkty

Aktualne wartości dostępne w UI (select przy dodawaniu aktywnego pilota):

| Wartość `vtx` | System | `is_digital` | `vision_points` |
|---|---|---|---|
| `"Analog"` | Analog | `False` | 1 |
| `"DJI"` | DJI O3/O4 | `True` | 4 |
| `"HD0"` | HDZero | `True` | 5 |
| `"Walksnail"` | Walksnail/Avatar | `True` | 4 |

**Reguła `is_digital`:** wszystko co nie jest `"Analog"` jest traktowane jako digital. Zachowanie aktualne w kodzie (`vtx != "Analog"`) pozostaje bez zmian.

> **Uwaga implementacyjna:** Mapowanie `VTX_POINTS: dict[str, int]` zdefiniowane jako stała w `activepilot.py`. Wartości `vtx` spoza tabeli (typo, nowy system) fallbackują do `vision_points = 1` i `is_digital = True` (bezpieczne wartości domyślne).

### 2.2 Total score pilota

```
total_score = vision_points(vtx) + risk_factor
```

Zakres: min = 1 + 1 = **2**, max = 5 + 6 = **11**.

Wyższy score oznacza system droższy/bardziej zaawansowany lub pilot bardziej agresywny w lataniu.

---

## 3. Algorytm — specyfikacja faz

Algorytm składa się z trzech sekwencyjnych faz wykonywanych w ramach `Session.rebalance_groups()`.

```
Faza 1: Rozmiar grup     (ile grup, ile pilotów w każdej)
Faza 2: Przydział pilotów do grup  (digital-first)
Faza 3: Przydział kanałów w grupie (score-based)
```

---

### Faza 1: Rozmiar grup

**Wejście:** `n = len(active_pilots)`

**Reguły:**

| n | Liczba grup | Rozkład |
|---|---|---|
| 0 | 0 | — |
| 1–4 | 1 | n |
| 5 | 2 | 3 + 2 |
| 6 | 2 | 3 + 3 |
| 7 | 2 | 4 + 3 |
| 8 | 2 | 4 + 4 |
| 9 | 3 | 3 + 3 + 3 |
| 10 | 3 | 4 + 3 + 3 |
| 11 | 3 | 4 + 4 + 3 |
| 12 | 3 | 4 + 4 + 4 |

**Formuła ogólna:**
```python
num_groups = math.ceil(n / MAX_PILOTS_PER_GROUP)  # MAX = 4
base_size  = n // num_groups
remainder  = n % num_groups  # pierwsze `remainder` grup dostaje +1
```

Przykład n=5: `num_groups=2, base_size=2, remainder=1` → grupy: [3, 2] ✓

> **Uwaga:** Aktualna implementacja (`math.ceil` + even distribution) **już spełnia** tę specyfikację dla wszystkich wartości n. Faza 1 nie wymaga zmian w kodzie.

---

### Faza 2: Przydział pilotów do grup (digital-first)

**Cel:** Maksymalizować liczbę jednorodnych grup (wszystko cyfrowe lub wszystko analogowe). Wynika z wymagania: *"Wszyscy piloci z systemami cyfrowymi powinni, w miarę możliwości, znajdować się w tych samych grupach."*

**Metoda:** Przed rozdzieleniem do grup posortuj listę wszystkich aktywnych pilotów wg klucza:

```python
sort_key = (0 if pilot.is_digital else 1, -pilot.total_score())
```

Priorytet kluczy:
1. **Cyfrowi przed analogowymi** (is_digital=True → 0, is_digital=False → 1)
2. **W ramach tej samej grupy systemu: wyższy score pierwszy** (serve the "best" digital pilots to early groups)

Następnie rozdziel pilotów do grup sekwencyjnie (jak w Fazie 1) — pierwsze grupy wypełnią się cyfrowo.

**Przykłady:**

| n | Piloci | Wynik Faza 2 |
|---|---|---|
| 6 | D×3, A×3 | Gr.1: [D,D,D], Gr.2: [A,A,A] ✓ jednorodne |
| 5 | D×3, A×2 | Gr.1: [D,D,D], Gr.2: [A,A] ✓ jednorodne |
| 7 | D×4, A×3 | Gr.1: [D,D,D,D], Gr.2: [A,A,A] ✓ jednorodne |
| 6 | D×2, A×4 | Gr.1: [D,D,A], Gr.2: [A,A,A] — 1 mieszana, 1 analogowa ✓ |
| 8 | D×3, A×5 | Gr.1: [D,D,D,A], Gr.2: [A,A,A,A] — 1 mieszana (minimum możliwe) ✓ |

> **Uwaga:** Sortowanie digital-first jest greedy — nie jest optymalne globalnie dla każdej konfiguracji (np. D×5, A×3 → 2 grupy 4+4: Gr.1=[D,D,D,D], Gr.2=[D,A,A,A]), ale spełnia wymaganie "w miarę możliwości" i jest deterministyczne.

---

### Faza 3: Przydział kanałów w grupie (score-based)

**Cel:** W ramach grupy, pilot z wyższym `total_score` otrzymuje wyższy kanał.

**Dostępne kanały:** `["R1", "R3", "R6", "R7"]` (posortowane rosnąco wg częstotliwości)

**Reguła mieszana (requirement 3.1.3):** Jeśli w grupie są piloci analogowi i cyfrowi jednocześnie, pilotom analogowym przydzielane są kanały od dołu (R1, R3...), a cyfrowym od góry (R7, R6...).

**Algorytm przydziału:**

```
1. Oddziel pilotów grupy na listę digital i listę analog.
2. Posortuj digital malejąco wg total_score.
3. Posortuj analog malejąco wg total_score.
4. Przydzielaj kanały od zewnątrz do środka:
   - digital[0] → R7, digital[1] → R6, digital[2] → R3, digital[3] → R1
   - analog[0]  → R1, analog[1]  → R3, analog[2]  → R6, analog[3]  → R7
   (wskaźniki przesuną się do środka; nie ma kolizji jeśli digital+analog <= 4)
```

**Macierz przydziału dla typowych składów grup:**

| Skład | R1 | R3 | R6 | R7 |
|---|---|---|---|---|
| 4×D (score: 10,8,6,4) | D(4) | D(6) | D(8) | D(10) |
| 4×A (score: 7,6,5,4) | A(4) | A(5) | A(6) | A(7) |
| 2×D + 2×A | A(niższy) | A(wyższy) | D(niższy) | D(wyższy) |
| 3×D + 1×A | A | D(najniższy) | D(środkowy) | D(najwyższy) |
| 1×D + 3×A | A(najniższy) | A(środkowy) | A(najwyższy) | D |

**Implikacja:** W grupie jednorodnej (wszyscy digital lub wszyscy analog) kanały R6/R7 nadal mogą być przydzielone analogom (gdy jest ich więcej niż 2). Jest to poprawne zachowanie — analogowy pilot z najwyższym score otrzymuje wyższy kanał.

---

## 4. Przypadki brzegowe

| Przypadek | Zachowanie |
|---|---|
| 0 pilotów | `self.groups = []`, return |
| 1 pilot | 1 grupa, 1 kanał (wynikowy z jego is_digital + score) |
| Remis w total_score | Stabilne sortowanie — kolejność wynikająca z `dict` iteration order (kolejność dodania do sesji). Nie jest błędem. |
| Nieznany vtx string | `vision_points = 1` (fallback), `is_digital = vtx != "Analog"` (true dla nieznanych) |
| Wszyscy z tym samym score | Sortowanie nie zmienia kolejności (stable sort), kanały przydzielone wg kolejności dodania |

---

## 5. Zmiany implementacyjne

### 5.1 `activepilot.py` — nowe: `VTX_POINTS` + `total_score()`

```python
VTX_POINTS: dict[str, int] = {
    "Analog":    1,
    "DJI":       4,
    "Walksnail": 4,
    "HD0":       5,
}

class ActivePilot(BaseModel):
    ...
    def total_score(self) -> int:
        """Return matchmaking score: vision_points(vtx) + risk_factor."""
        vision = VTX_POINTS.get(self.vtx, 1)
        return vision + self.pilot.risk_factor
```

**Brak zmian w modelu ani w DB** — `total_score()` jest zawsze obliczane na żywo.

### 5.2 `session.py` — zmiana `rebalance_groups()`

**Faza 2 — sortowanie pilotów przed dystrybucją:**

```python
# Before: active_pilots_array = list(self.active_pilots.values())
# After:
active_pilots_array = sorted(
    self.active_pilots.values(),
    key=lambda p: (0 if p.is_digital else 1, -p.total_score())
)
```

> Sortowanie wykonać raz przed pętlą — nie wewnątrz niej.

**Faza 3 — score-based channel assignment wewnątrz grupy:**

```python
# Before:
for pilot in [p for p in group_pilots if p.is_digital]:
    channels[ALLOWED_CHANNELS[digital_idx]] = pilot

# After:
digital_sorted = sorted(
    [p for p in group_pilots if p.is_digital],
    key=lambda p: p.total_score(), reverse=True
)
for pilot in digital_sorted:
    channels[ALLOWED_CHANNELS[digital_idx]] = pilot
    digital_idx -= 1

analog_sorted = sorted(
    [p for p in group_pilots if not p.is_digital],
    key=lambda p: p.total_score(), reverse=True
)
for pilot in analog_sorted:
    channels[ALLOWED_CHANNELS[analog_idx]] = pilot
    analog_idx += 1
```

### 5.3 Brak zmian w pozostałych plikach

| Plik | Zmiana |
|---|---|
| `pilot.py` | Brak — `risk_factor` już istnieje |
| `database.py` | Brak — `total_score()` obliczane w pamięci |
| `routers/` | Brak — `/api/groups/rebalance` endpoint bez zmian |
| Frontend HTML/JS | Brak — grupy i kanały prezentowane tak samo |

---

## 6. Plan testów

### 6.1 Testy jednostkowe (nowy plik: `test_matchmaking_v2.py`)

| ID | Opis | Kluczowy assert |
|---|---|---|
| MM-01 | `total_score()`: Analog + risk=1 → 2 | `ap.total_score() == 2` |
| MM-02 | `total_score()`: HDZero + risk=6 → 11 | `ap.total_score() == 11` |
| MM-03 | `total_score()`: DJI + risk=3 → 7 | `ap.total_score() == 7` |
| MM-04 | Fallback: nieznany vtx → vision_points=1 | `ap.total_score() == 1 + risk_factor` |
| MM-05 | 6 pilotów: 3×D (score 8,7,6) + 3×A (score 5,4,3) → Gr.1 czysto digital, Gr.2 czysto analog | `all(p.is_digital for p in gr1_pilots)` |
| MM-06 | 8 pilotów: 3×D + 5×A → Gr.1: [D,D,D,A], Gr.2: [A,A,A,A] | skład grupy 1 |
| MM-07 | 4×D (score 11,8,5,2) → R7=11, R6=8, R3=5, R1=2 | kanały w grupie |
| MM-08 | 4×A (score 7,6,5,4) → R7=7, R6=6, R3=5, R1=4 | kanały w grupie |
| MM-09 | 2×D (score 9,6) + 2×A (score 7,4) → R7=D(9), R6=D(6), R3=A(7), R1=A(4) | kanały mieszane |
| MM-10 | 3×D (score 9,7,5) + 1×A (score 6) → R7=D(9), R6=D(7), R3=D(5), R1=A(6) | 3D+1A |
| MM-11 | 1×D (score 8) + 3×A (score 7,5,3) → R7=D(8), R6=A(7), R3=A(5), R1=A(3) | 1D+3A |
| MM-12 | Remis score w tej samej grupie → brak błędu, oba przydzielone | `len(channels) == 2` |
| MM-13 | 5 pilotów: 3×D + 2×A → Gr.1=[D,D,D], Gr.2=[A,A] | rozmiar grupy 3+2 |

### 6.2 Testy regresyjne

Istniejące testy w `test_groups_matchmaking.py` **nie mogą się psuć**. Szczególnie:
- `test_analog_pilots_get_low_channels` — analogowi nadal na R1/R3 ✓
- `test_digital_pilots_get_high_channels` — cyfrowi nadal na R6/R7 ✓
- `test_5_pilots_creates_2_groups` — 3+2 ✓
- Wszystkie testy manualnego move/drag — bez zmian ✓

---

## 7. Otwarte pytania / decyzje

| # | Pytanie | Propozycja |
|---|---|---|
| Q1 | Czy `vtx` powinno być enumem (walidacja na API), czy nadal wolnym stringiem? | Na razie zostawić string; enum można dodać jako osobny krok bez wpływu na logikę. |
| Q2 | ~~Kanoniczne wartości vtx?~~ | **Rozstrzygnięte:** `"Analog"`, `"DJI"`, `"HD0"`, `"Walksnail"`. `"Walksnail"` do dodania w UI (select). |
| Q3 | Czy `total_score()` ma być eksponowany w API (np. w response `/api/groups`)? | Nie na tym etapie — score jest implementacyjnym detalem matchmakingu, nie musi być widoczny w UI. |

---

*Dokument ten należy zaktualizować po ustaleniu podejścia do Low Band (dodanie flagi `low_band` do modelu `Pilot` + reguła 5. zawodnika).*
