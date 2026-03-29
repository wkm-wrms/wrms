# BACKUP.md — Specyfikacja modułu backup/restore bazy danych

## 1. Cel

Umożliwić administratorowi tworzenie pełnych kopii zapasowych bazy danych i przywracanie
ich na żądanie, bez dostępu do serwera. Backup jest pobierany jako plik na komputer admina;
restore wymaga wgrania pliku przez przeglądarkę.

---

## 2. Format pliku backup

Plik: **SQL dump** (plain text), kompresja **gzip** (`.sql.gz`).

Uzasadnienie:
- SQL dump jest czytelny i przenośny — można go zaimportować do dowolnej instancji SQLite
  lub przejrzeć w edytorze tekstowym po rozpakowaniu.
- Gzip redukuje rozmiar o ~70–80% (tekstowe dane SQL kompresują się bardzo dobrze).
- Brak zależności binarnych — Python obsługuje `gzip` w stdlib.

### Nazwa pliku

```
wrms_backup_YYYYMMDD_HHMMSS.sql.gz
```

Przykład: `wrms_backup_20260329_143022.sql.gz`

### Struktura pliku (po dekompresji)

```sql
-- WRMS Database Backup
-- Created: 2026-03-29T14:30:22
-- Schema version: 2
-- App version: WRMS

BEGIN TRANSACTION;
... (pełny dump SQLite: CREATE TABLE + INSERT dla każdej tabeli) ...
COMMIT;
```

Nagłówek zawiera metadane jako komentarze SQL — są ignorowane przez SQLite, ale
odczytywane przez mechanizm restore do walidacji.

---

## 3. Wersjonowanie schematu

Stała `SCHEMA_VERSION: int` w `database.py` — inkrementowana przy każdej zmianie
struktury tabel (nowa tabela, nowa kolumna, zmiana typu/constraintu).

| Wersja | Opis zmiany |
|--------|-------------|
| 1      | Schemat bazowy (pilot, session, group, heat, user, admin_session, pilot_heat) |
| 2      | pilot.risk_factor, pilot.notes (2026-03-29) |

Przy restore:
- Backup version < current version → **ostrzeżenie** (import dozwolony, brakujące kolumny
  zostaną dodane przez migracje w `_init_tables`)
- Backup version > current version → **błąd** (backup pochodzi z nowszej wersji aplikacji,
  import odrzucony)
- Backup version == current version → import bez ostrzeżeń

---

## 4. Endpoint backup — `GET /api/backup/download`

**Auth:** admin required.

**Działanie:**
1. Otwiera połączenie SQLite do bieżącej bazy.
2. Generuje dump przez `sqlite3.Connection.iterdump()` — zwraca iterowalne linie SQL.
3. Dokłada nagłówek z metadanymi (data, schema version).
4. Kompresuje całość gzipem w pamięci (`io.BytesIO` + `gzip.GzipFile`).
5. Zwraca `StreamingResponse` z nagłówkami:
   - `Content-Type: application/gzip`
   - `Content-Disposition: attachment; filename="wrms_backup_YYYYMMDD_HHMMSS.sql.gz"`

Baza nie jest lockowana na czas dumpu — SQLite WAL zapewnia spójny snapshot.

---

## 5. Endpoint restore — `POST /api/backup/restore`

**Auth:** admin required.

**Wejście:** `multipart/form-data`, pole `file` (plik `.sql.gz`).

**Walidacja (kolejność):**

1. **Rozmiar pliku** — max 50 MB (zabezpieczenie przed DoS).
2. **Dekompresja** — próba odczytu gzip; błąd → odrzucenie z komunikatem.
3. **Nagłówek metadanych** — parsowanie komentarzy `-- Schema version: N`; brak → odrzucenie.
4. **Wersja schematu** — jak opisano w sekcji 3.
5. **Walidacja SQL** — whitelist dozwolonych poleceń. Każda linia (po pominięciu komentarzy
   i pustych linii) musi zaczynać się od jednego z:
   ```
   BEGIN, COMMIT, ROLLBACK,
   CREATE TABLE, CREATE INDEX, CREATE UNIQUE INDEX,
   INSERT INTO, DELETE FROM,
   PRAGMA
   ```
   Każda linia niezgodna z whitelistą powoduje odrzucenie całego pliku z informacją
   o numerze linii i treści naruszenia.
6. **Zakaz niebezpiecznych słów kluczowych** — odrzucenie, jeśli dump zawiera:
   `DROP`, `ALTER`, `UPDATE`, `ATTACH`, `DETACH`, `LOAD EXTENSION`, `pragma key`,
   `sqlite_master` (write), `writefile`.

**Działanie po pozytywnej walidacji:**

1. Bieżąca baza jest atomowo zastąpiona — backup pliku DB na `<db_path>.pre_restore`.
2. Nowa baza tworzona jest w pamięci (`:memory:`), wykonywany jest cały dump SQL.
3. Jeśli wykonanie bez błędów → baza zapisana do docelowego pliku przez
   `sqlite3.connect(new_path)` + `conn.executescript(dump)`.
4. `_init_tables()` wywoływana na nowej bazie — dodaje brakujące kolumny przez
   idempotentne migracje (obsługa starszych backupów).
5. Moduł `session` resetuje in-memory state (`set_session(None)`), aplikacja przeładuje
   sesję przy następnym żądaniu (jak przy restarcie serwera).
6. Plik `.pre_restore` pozostaje jako dodatkowe zabezpieczenie (nie jest usuwany automatycznie).

**Odpowiedź:**
```json
{
  "status": "ok",
  "backup_version": 2,
  "current_version": 2,
  "warning": null
}
```
lub przy backupie ze starszej wersji:
```json
{
  "status": "ok",
  "backup_version": 1,
  "current_version": 2,
  "warning": "Backup schema is older (v1 < v2). Migrations applied automatically."
}
```

---

## 6. Frontend — `backup.html`

Samodzielna strona ładowana w iframe wewnątrz modalu w session.html.

### Sekcja Backup

- Nagłówek: "Kopia zapasowa"
- Opis: "Pobierz pełny dump bazy danych (plik .sql.gz)."
- Przycisk **"Pobierz backup"** → wywołuje `GET /api/backup/download` jako `<a href>` z
  `download` — przeglądarka pobiera plik bez przeładowania strony.
- Po kliknięciu przycisk chwilowo pokazuje "Generowanie..." i wraca do stanu normalnego
  po 2 s (brak informacji zwrotnej z `<a>` download).

### Sekcja Restore

- Nagłówek: "Przywróć z kopii zapasowej"
- Ostrzeżenie wizualne (żółte tło): "Operacja nadpisze wszystkie bieżące dane. Wykonaj
  backup przed przywróceniem."
- `<input type="file" accept=".sql.gz">` — wybór pliku
- Przycisk **"Przywróć"** — aktywny tylko gdy plik wybrany
- Po kliknięciu: `confirm()` z pełnym ostrzeżeniem
- Po potwierdzeniu: `POST /api/backup/restore` jako `FormData`
- Spinner/komunikat w trakcie uploadu
- Po sukcesie: zielony komunikat + `window.location.reload()` po 3 s
- Po błędzie: czerwony komunikat z treścią błędu z API

---

## 7. Integracja z session.html

Przycisk **"Backup"** w górnym pasku admina (obok nazwy użytkownika, przed "Administratorzy"):

```html
<button class="btn btn-sm btn-secondary" onclick="openBackupModal()">Backup</button>
```

Modal z iframe — analogicznie do modalu pilotów:
```html
<div id="backup-modal" class="modal-overlay" ...>
  <div class="modal-box" style="width:500px">
    <div class="modal-header">...</div>
    <iframe id="backup-frame" src="" style="width:100%;height:360px;border:none"></iframe>
  </div>
</div>
```

---

## 8. Testy — `test_backup.py`

- `GET /api/backup/download` → status 200, Content-Type gzip, plik dekompresuje się poprawnie
- Dump zawiera nagłówek z `Schema version:`
- `POST /api/backup/restore` z własnym backupem → status ok, dane odczytywalne po restore
- Restore z plikiem zawierającym `DROP TABLE` → odrzucone
- Restore z plikiem zawierającym `UPDATE` → odrzucone
- Restore z nieprawidłowym gzip → odrzucone
- Restore z backup_version > current_version → odrzucone
- Restore z backup_version < current_version → ok + warning
- Restore bez auth → 401
- Download bez auth → 401

---

## 9. Zasady dla przyszłych zmian schematu

Przy każdej modyfikacji struktury DB (nowa tabela, kolumna, indeks):

1. Dodaj wpis do `_adds` lub `_renames` w `_init_tables()` (idempotentna migracja).
2. Zwiększ `SCHEMA_VERSION` o 1 w `database.py`.
3. Dodaj wiersz do tabeli wersji w tym pliku (sekcja 3).

Dzięki idempotentnym migracjom restore starszego backupu automatycznie uzupełni
brakujące kolumny — bez potrzeby pisania osobnych skryptów migracyjnych.

---

*Autor: projekt WRMS | Data: 2026-03-29*
