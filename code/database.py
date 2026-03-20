import sqlite3
import json
import traceback

from datetime import datetime
import hashlib


from pilot import Pilot
from session import Session, ActivePilot
from group import Group
from heat import Heat


class RaceDatabase:
    """
    A SQLite-based database manager for a race/training system.
    This class handles all database operations for managing pilots, training sessions,
    training groups with versioning, and race heats (individual races). It uses SQLite
    with WAL (Write-Ahead Logging) mode for concurrent access compatibility with uWSGI.
    The database structure includes:
    - pilots: Stores pilot information (name, country, creation timestamp)
    - users: Stores admin credentials (username, password hash)
    - sessions: Stores training sessions
    - groups: Stores training groups with version control (supports multiple versions)
    - heats: Stores individual races with status tracking and timing
    Key Features:
    - Automatic table initialization
    - Group versioning with is_latest flag for tracking current versions
    - Precise race timing using Unix epoch timestamps
    - JSON serialization for complex data (pilot IDs, pilot-channel mappings)
    - Password hashing for admin authentication
    - Row factory for column-name-based access
    Attributes:
        db_path (str): Path to the SQLite database file. Defaults to "data/race_system.db"
    Methods:
        Pilot Management:
            add_pilot(name, country): Add a new pilot to the database
            get_pilot_by_id(pilot_id): Retrieve pilot information by ID
            search_pilots(query): Search pilots by name
        Group Management (with versioning):
            create_or_update_group(session_id, name, pilot_ids): Create or version a group
            get_latest_groups(session_id): Get current versions of all groups in a session
        Heat Management:
            create_heat(group_id, pilot_channels): Plan a new race heat
            start_heat(heat_id): Start a heat and record precise start time
            get_heat_status(heat_id): Get heat status with elapsed time calculation
        Administration:
            add_admin(username, password): Create new admin user
            verify_admin(username, password): Authenticate admin credentials
    """

    db_path: str = None

    def __init__(self, db_path: str = "data/race_system.db"):
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")  # Kluczowe dla uWSGI
        # Ustawienie trybu WAL i obcych kluczy dla tej sesji
        conn.execute("PRAGMA foreign_keys = 1;")
        conn.row_factory = sqlite3.Row  # Pozwala na dostęp przez nazwy kolumn
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            # Piloci
            conn.execute("""CREATE TABLE IF NOT EXISTS pilot (
                pilot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                country TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name),
                check(name != "")
            )""")
            conn.execute(
                """CREATE index IF NOT EXISTS idx_pilots_name ON pilot(name)""")

            # Użytkownicy (Admini)
            conn.execute("""CREATE TABLE IF NOT EXISTS user (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )""")

            # Sesje Treningowe
#            conn.execute("drop table if exists active_pilots")
#            conn.execute("drop table if exists sessions")
            conn.execute("""CREATE TABLE IF NOT EXISTS session (
                session_id text PRIMARY KEY ,
                name TEXT NOT NULL,
                flight_duration_sec INTEGER,
                prep_duration_sec INTEGER,
                is_active BOOLEAN DEFAULT 0,
                current_heat_id INTEGER,
                current_group_id INTEGER,
                current_group_index INTEGER,
                next_heat_id INTEGER,
                timer_running BOOLEAN DEFAULT 0,
                timer_start_time_unix REAL,
                current_phase TEXT CHECK(current_phase IN ('IDLE', 'PREP', 'FLIGHT', 'PAUSED', 'FINISHED')) DEFAULT 'IDLE',
                phase_before_pause text   CHECK(phase_before_pause IN ('IDLE', 'PREP', 'FLIGHT', 'PAUSED')) DEFAULT 'PREP',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")

            conn.execute("""CREATE TABLE IF NOT EXISTS active_pilot (
                session_id text not null ,
                pilot_id INTEGER not null ,
                vtx TEXT not null,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, pilot_id),
                FOREIGN KEY(session_id) REFERENCES session(session_id),
                FOREIGN KEY(pilot_id) REFERENCES pilot(pilot_id)
            )""")

            conn.execute("""CREATE INDEX IF NOT EXISTS idx_active_pilot_session_id
                ON active_pilot(session_id)
            """)

            # Grupy Treningowe (z wersjonowaniem przez parent_group_id i version)
            conn.execute("""CREATE TABLE IF NOT EXISTS session_group (
                group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id text not null ,
                pilot_ids TEXT, -- Zapisane jako JSON [1, 2, 5]
                channel_map text , -- zapisane jako JSON "R1" -> pilot ID
                group_sequence INTEGER not null,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES session(session_id)
            )""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_groups_session_id
                ON session_group(session_id)
            """)

            # Biegi (Heats)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS heat (
                    session_id INTEGER NOT NULL,
                    heat_number INTEGER NOT NULL, -- np. Bieg w ramach sesji nr 1, 2, 3...
                    group_id INTEGER NOT NULL,

                    status TEXT DEFAULT 'INIT', -- INIT, PREP, FLIGHT, PAUSED, FINISHED

                    -- "Zamrożony" skład (JSON lub dedykowana tabela)
                    pilots_data_json TEXT NOT NULL,

                    -- Markery czasu (Unix Timestamp)
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    prep_started_at REAL,
                    flight_started_at REAL,
                    finished_at REAL,

                    -- Logika Pauzy
                    remaining_seconds_at_pause REAL,
                    last_resume_at REAL,

                    PRIMARY KEY (session_id, heat_number),
                    FOREIGN KEY (session_id) REFERENCES session(session_id)
                )
                        """
                         )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pilot_heat (
                    pilot_heat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    heat_number INTEGER NOT NULL,
                    pilot_id INTEGER NOT NULL,

                    -- Konfiguracja z momentu startu
                    vtx_channel TEXT NOT NULL,      -- np. R1
                    vtx_type TEXT NOT NULL,         -- np. Analog, DJI
                    radio_protocol TEXT,            -- np. ELRS 2.4G (opcjonalnie)

                    -- Markery czasowe dla konkretnego pilota
                    started_at REAL,                -- moment przekroczenia bramki startowej lub start biegu
                    finished_at REAL,               -- moment lądowania/rozbicia się
                    flight_time REAL,               -- czas trwania lotu (w sekundach)
                    status TEXT DEFAULT 'PLANNED',    -- PLANNED, READY, RACING, FINISHED, DNF (Did Not Finish), DNS (Did Not Start)

                    FOREIGN KEY (session_id, heat_number) REFERENCES heat(session_id, heat_number),
                    FOREIGN KEY (pilot_id) REFERENCES pilot(pilot_id),
                    FOREIGN KEY (session_id) REFERENCES session(session_id)
                )
                        """
                         )
            # -- Indeks dla szybkiego wyciągania historii pilota
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pilot_history ON pilot_heat (pilot_id, session_id);
                         """
                         )

            conn.commit()


# --- OBSŁUGA PILOTÓW --- ---------------------------------------------

    def add_pilot(self, name, country=""):
        """Dodaje nowego pilota do bazy danych."""
        with self._get_conn() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO pilot (name, country) VALUES (?, ?)", (name, country))
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Pilot o tej nazwie już istnieje lub nazwa jest pusta.") from exc
            return cursor.lastrowid

    def get_pilot_by_id(self, pilot_id) -> Pilot:
        """ Pobiera dane pilota na podstawie ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pilot WHERE pilot_id = ?", (pilot_id,)).fetchone()
            if row:
                return Pilot(id=row['pilot_id'], name=row['name'], country=row['country'])
            else:
                return None

    def search_pilots(self, query):
        """ Szuka pilotów po nazwie (częściowe dopasowanie)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pilot WHERE name LIKE ?", (f"%{query}%",)).fetchall()
            return [Pilot(id=row['pilot_id'], name=row['name'], country=row['country'])for row in rows]

    def get_active_pilots(self, session_id: str):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT pilot_id, vtx FROM active_pilot WHERE session_id = ?", (
                    session_id,)
            ).fetchall()
            return [
                ActivePilot(self.get_pilot_by_id(row['pilot_id']), row["vtx"]) for row in rows]
        return []

# -- Obsługa sesji

    def create_session(self, session: Session):
        """ Zaisz innicjalny obiekt sesio do bazy danych. Sesja bedzie na poczatku konfiguracji, wiec zakladam, ze bedzie miala tylko obowizkowe dane"""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO session (session_id, name, flight_duration_sec, prep_duration_sec)
                VALUES (?, ?, ?, ?)
            """, (session.session_id, session.name, session.flight_duration_sec, session.prep_duration_sec))
            conn.commit()
            return 0

    def get_active_session(self) -> Session:
        """ Pobierz z bazy danych aktywna sesje, jesli jest"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM session WHERE current_phase <>'FINISHED' LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self.get_session_by_id(row["session_id"])

    def get_session_by_id(self, session_id: str) -> Session:
        """ Pobierz pełne dane sesji na podstawie jej ID """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM session WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row:
                # Get current heat if it exists
                (current_group, next_heat, current_heat) = (None, None, None)

                if row['current_heat_id']:
                    current_heat = self.get_heat_by_id(row['current_heat_id'])
                if row['next_heat_id']:
                    next_heat = self.get_heat_by_id(row['next_heat_id'])
                active_pilots = self.get_active_pilots(session_id)
                timer_start_time_unix = row["timer_start_time_unix"]
                timer_start_time = datetime.fromtimestamp(
                    timer_start_time_unix) if timer_start_time_unix is not None else None
                groups = self.get_groups_by_session_id(session_id)
                current_group = self.get_group_by_id(
                    row["current_group_id"]) if row["current_group_id"] else None
                session = Session(
                    name=row['name'],
                    flight_duration_sec=row['flight_duration_sec'],
                    prep_duration_sec=row['prep_duration_sec'],
                    session_id=row['session_id'],
                    is_active=row['is_active'],
                    timer_running=row['timer_running'],
                    current_phase=row['current_phase'],
                    phase_before_pause=row['phase_before_pause'],
                    current_group_index=row['current_group_index'],
                    current_heat=current_heat,
                    next_heat=next_heat,
                    active_pilots=active_pilots,
                    timer_start_time=timer_start_time,
                    groups=groups,
                    current_group=current_group
                )
                return session
            return None

    def save_session_data(self, session: Session):
        """Updates all session values in the database."""
        with self._get_conn() as conn:
            timer_start_time_unix = session.timer_start_time.timestamp(
            ) if session.timer_start_time else None
            conn.execute("""
                UPDATE session SET
                    name = ?,
                    flight_duration_sec = ?,
                    prep_duration_sec = ?,
                    is_active = ?,
                    current_heat_id = ?,
                    next_heat_id = ?,
                    timer_running = ?,
                    timer_start_time_unix = ?,
                    current_phase = ?,
                    phase_before_pause = ?
                WHERE session_id = ?
            """, (
                session.name,
                session.flight_duration_sec,
                session.prep_duration_sec,
                session.is_active,
                session.current_heat.id if session.current_heat else None,
                session.next_heat.id if session.next_heat else None,
                session.timer_running,
                timer_start_time_unix,
                session.current_phase,
                session.phase_before_pause,
                session.session_id
            ))
            conn.commit()

    def get_all_sessions(self):
        """ Pobierz z bazy danych wszystkie sesje"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT session_id FROM sessions "
            ).fetchall()
#            return [row["id"] for row in rows]
            return [self.get_session_by_id(row["session_id"]) for row in rows]

    def session_add_pilot(self, session_id: str, pilot_id: int, vtx: str):
        with self._get_conn() as con:
            try:
                con.execute(
                    "INSERT INTO active_pilot (session_id, pilot_id, vtx) VALUES (?, ?, ?)",
                    (session_id, pilot_id, vtx)
                )
                con.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("Pilot już jest aktywny w grupie") from exc

    def session_remove_pilot(self, session_id: str, pilot_id: int):
        with self._get_conn() as con:
            con.execute(
                "delete from active_pilot where session_id=? and pilot_id =?",
                (session_id, pilot_id)
            )
            con.commit()


# --- OBSŁUGA GRUP


    def get_groups_by_session_id(self, session_id: str):
        """ Get all groups attached to specyfic session """
        with self._get_conn() as conn:
            # Fetch all group IDs for the session
            rows = conn.execute(
                "SELECT group_id FROM session_group WHERE session_id = ? ORDER BY group_sequence",
                (session_id,)
            ).fetchall()
            return [self.get_group_by_id(row["group_id"]) for row in rows]

    def get_group_by_id(self, group_id: int):
        """ GEt all session data """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT *  FROM session_group WHERE group_id=?  ORDER BY group_sequence",
                (group_id,)
            ).fetchone()
            pilots: list[Pilot] = []
            pilots_ids = json.loads(row['pilot_ids'])
            pilot_by_id: map[int, Pilot] = {}
            if pilots_ids is not None and isinstance(pilots_ids, list):
                for pilot_id in pilots_ids:
                    pilot = self.get_pilot_by_id(pilot_id)
                    if pilot:
                        pilots.append(pilot)
                        pilot_by_id[pilot_id] = pilot

            channels_map = json.loads(
                row['channel_map']) if row['channel_map'] else {}
            channels: map[str, Pilot] = {}
            if channels_map is not None and isinstance(channels_map, dict):
                for channel in channels_map:
                    pilot_id = channels_map[channel]
                    channels[channel] = pilot_by_id[pilot_id] if pilot_id in pilot_by_id else None
            return Group(
                group_id=row['group_id'], pilots=pilots, channels=channels, group_sequence=row['group_sequence'])

    def update_groups(self, session):
        """Tworzy nową grupę lub nową wersję istniejącej."""
        with self._get_conn() as conn:
            # Szukamy czy istnieje już grupa o tej nazwie w tej sesji
            conn.execute(
                "DELETE FROM session_group WHERE session_id = ?",
                (session.session_id,)
            )
            for group in session.groups:
                pilot_ids = [p.pilot.id for p in group.pilots]
                channels = {}
                for (k) in group.channels:
                    v = group.channels[k]
                    channels[k] = v.id
                conn.execute(
                    "INSERT INTO session_group (session_id, pilot_ids, channel_map, group_sequence ) VALUES (?, ?, ?, ?)",
                    (session.session_id,  json.dumps(pilot_ids),
                     json.dumps(channels), group.group_sequence,)
                )

    # --- OBSŁUGA BIEGÓW (Heats) ---
    def create_heat(self, session_id: str, heat_number: int, group_id: int, pilots_data: dict):
        """
        Tworzy nowy rekord w tabeli heat. 
        Status domyślnie ustawiony na 'INIT' przez schemat bazy.
        """
        query = """
            INSERT INTO heat (
                session_id, 
                heat_number, 
                group_id, 
                heat_pilots_data_json
            ) VALUES (?, ?, ?, ?)
        """
        # Konwertujemy słownik pilotów na string JSON
        pilots_json = json.dumps(pilots_data)

        with self._get_conn() as conn:
            try:
                conn.execute(
                    query, (session_id, heat_number, group_id, pilots_json))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Obsługa przypadku, gdy para session_id + heat_number już istnieje
                return False

    def update_heat(self, session_id: str, heat_number: int, update_data: dict):
        """
        Aktualizuje dynamiczne dane biegu.
        update_data może zawierać: heat_status, heat_prep_started_at, 
        heat_flight_started_at, heat_finished_at, heat_remaining_seconds_at_pause,
        heat_last_resume_at.
        """
        if not update_data:
            return False

        # Budujemy zapytanie dynamicznie na podstawie kluczy w słowniku
        # Filtrujemy tylko te klucze, które zaczynają się od 'heat_' dla bezpieczeństwa
        allowed_keys = [
            'heat_status', 'heat_prep_started_at', 'heat_flight_started_at',
            'heat_finished_at', 'heat_remaining_seconds_at_pause', 'heat_last_resume_at'
        ]

        fields_to_update = []
        values = []

        for key, value in update_data.items():
            if key in allowed_keys:
                fields_to_update.append(f"{key} = ?")
                values.append(value)

        if not fields_to_update:
            return False

        # Dodajemy parametry klucza złożonego na koniec listy wartości
        query = f"UPDATE heat SET {', '.join(fields_to_update)} WHERE session_id = ? AND heat_number = ?"
        values.extend([session_id, heat_number])

        with self._get_conn() as conn:
            cursor = conn.execute(query, values)
            conn.commit()
            return cursor.rowcount > 0

    def get_active_heats(self, session_id: str):
        """
        Pobiera listę wszystkich heat-ów dla danej sesji, 
        które nie zostały jeszcze zakończone (status inny niż 'FINISHED').
        Wyniki są sortowane po numerze heat-u.
        """
        query = """
            SELECT 
                session_id,
                heat_number,
                group_id,
                heat_status,
                heat_pilots_data_json,
                heat_prep_started_at,
                heat_flight_started_at,
                heat_remaining_seconds_at_pause,
                heat_last_resume_at
            FROM heat
            WHERE session_id = ? AND heat_status != 'FINISHED'
            ORDER BY heat_number ASC
        """

        with self.get_connection() as conn:
            cursor = conn.execute(query, (session_id,))
            rows = cursor.fetchall()

            # Przekształcamy sqlite3.Row na listę słowników i parsujemy JSON-a
            active_heats = []
            for row in rows:
                heat_dict = dict(row)
                # Opcjonalnie: od razu parsujemy JSON-a z danymi pilotów
                if heat_dict['heat_pilots_data_json']:
                    heat_dict['pilots_data'] = json.loads(
                        heat_dict['heat_pilots_data_json'])
                active_heats.append(heat_dict)

            return active_heats

    # --- ADMINISTRACJA ---

    def add_admin(self, username, password):
        """ Tworzy nowego administratora """

        hashed = hashlib.sha256(password)
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
        except sqlite3.IntegrityError:
            return False
        return True

    def verify_admin(self, username, password):
        """ Weryfikuje dane logowania administratora """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()
            hashed = hashlib.sha256(password)
            if row and (row['password_hash'] == hashed):
                return True
        return False


db_instance = RaceDatabase()


def get_db():
    """ Funkcja pomocnicza do uzyskania instancji bazy danych (np. dla FastAPI) """
    return db_instance
