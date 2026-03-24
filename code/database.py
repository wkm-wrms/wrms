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

            # conn.execute("drop table if exists pilot_heat")
            # conn.execute("drop table if exists heat")
            # conn.execute("drop table if exists active_pilot")
            # conn.execute("drop table if exists session_group")
            # conn.execute("drop table if exists session")
            conn.execute("""CREATE TABLE IF NOT EXISTS session (
                session_id text PRIMARY KEY ,
                name TEXT NOT NULL,
                flight_duration_sec INTEGER,
                prep_duration_sec INTEGER,
                is_active BOOLEAN DEFAULT 0,
                current_heat_number INTEGER,
                current_group_id INTEGER,
                current_group_index INTEGER,
                next_group_index INTEGER,
                next_heat_number INTEGER,
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

                    prep_time INTEGER NOT NULL,
                    flight_time INTEGER NOT NULL,


                    status TEXT DEFAULT 'INIT', -- INIT, PREP, FLIGHT, PAUSED, FINISHED

                    -- "Zamrożony" skład (JSON lub dedykowana tabela)
                    channels_json TEXT NOT NULL,

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
                return Pilot(pilot_id=row['pilot_id'], name=row['name'], country=row['country'])
            else:
                return None

    def search_pilots(self, query):
        """ Szuka pilotów po nazwie (częściowe dopasowanie)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pilot WHERE name LIKE ?", (f"%{query}%",)).fetchall()
            return [Pilot(pilot_id=row['pilot_id'], name=row['name'], country=row['country'])for row in rows]

    def get_active_pilots(self, session_id: str):
        res = {}
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT pilot_id, vtx FROM active_pilot WHERE session_id = ?", (
                    session_id,)
            ).fetchall()
            ret = {}
            for row in rows:
                res[row["pilot_id"]] = ActivePilot(
                    self.get_pilot_by_id(row['pilot_id']), row["vtx"])
            return res
        return {}

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
                (current_group, next_heat, current_heat, current_heat_number,
                 next_heat_number) = (None, None, None, None, None)
                session_id = row['session_id']
                active_pilots = self.get_active_pilots(session_id)
                if row['current_heat_number']:
                    current_heat = self.get_heat_by_number(
                        session_id, row['current_heat_number'], active_pilots=active_pilots)
                if row['next_heat_number']:
                    next_heat = self.get_heat_by_number(session_id=session_id,
                                                        heat_number=row['next_heat_number'], active_pilots=active_pilots)

                groups = self.get_groups_by_session_id(
                    session_id, active_pilots)
                heats = self.get_active_heats(session_id, active_pilots)
                if len(heats) >= 1:
                    current_heat = heats[0]
                    current_heat_number = current_heat.heat_number
                if len(heats) >= 2:
                    next_heat = heats[1]
                    next_heat_number = next_heat.heat_number

                current_group = self.get_group_by_id(
                    row["current_group_id"], session.active_pilots) if row["current_group_id"] else None
                session = Session(
                    name=row['name'],
                    flight_duration_sec=row['flight_duration_sec'],
                    prep_duration_sec=row['prep_duration_sec'],
                    session_id=row['session_id'],
                    is_active=row['is_active'],
                    current_phase=row['current_phase'],
                    phase_before_pause=row['phase_before_pause'],
                    current_group_index=row['current_group_index'],
                    next_group_index=row['next_group_index'],
                    current_heat=current_heat,
                    current_heat_number=current_heat_number,
                    next_heat=next_heat,
                    next_heat_number=next_heat_number,


                    active_pilots=active_pilots,
                    groups=groups,
                    current_group=current_group
                )
                return session
            return None

    def save_session_data(self, session: Session):
        """Updates all session values in the database."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE session SET
                    name = ?,
                    flight_duration_sec = ?,
                    prep_duration_sec = ?,
                    is_active = ?,
                    current_heat_number = ?,
                    next_heat_number = ?,
                    current_phase = ?,
                    phase_before_pause = ?, 
                    current_group_index=?,
                    next_group_index=?
                WHERE session_id = ?
            """, (
                session.name,
                session.flight_duration_sec,
                session.prep_duration_sec,
                session.is_active,
                session.current_heat_number if session.current_heat_number else None,
                session.next_heat_number if session.next_heat_number else None,
                session.current_phase,
                session.phase_before_pause,
                session.current_group_index,
                session.next_group_index,
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


    def get_groups_by_session_id(self, session_id: str, active_pilots: dict[int, ActivePilot]):
        """ Get all groups attached to specyfic session """
        with self._get_conn() as conn:
            # Fetch all group IDs for the session
            rows = conn.execute(
                "SELECT group_id FROM session_group WHERE session_id = ? ORDER BY group_sequence",
                (session_id,)
            ).fetchall()
            return [self.get_group_by_id(row["group_id"], active_pilots) for row in rows]

    def get_group_by_id(self, group_id: int, active_pilots: dict[int, ActivePilot]):
        """ GEt all session data """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT *  FROM session_group WHERE group_id=?  ORDER BY group_sequence",
                (group_id,)
            ).fetchone()
#            pilots_ids = json.loads(row['pilot_ids'])
#            pilot_by_id: map[int, ActivePilot] = {}
#            if pilots_ids is not None and isinstance(pilots_ids, list):
#                for pilot_id in pilots_ids:
#                    pilot = active_pilots[pilot_id] if pilot_id in active_pilots else None
#                    if pilot:
#                        pilot_by_id[pilot_id] = pilot

            channels_map = json.loads(
                row['channel_map']) if row['channel_map'] else {}
            channels: map[str, ActivePilot] = {}
            if channels_map is not None and isinstance(channels_map, dict):
                for channel in channels_map:
                    pilot_id = channels_map[channel]
                    channels[channel] = active_pilots[pilot_id] if pilot_id in active_pilots else None
            return Group(
                group_id=row['group_id'],  channels=channels, group_sequence=row['group_sequence'])

    def update_groups(self, session):
        """Tworzy nową grupę lub nową wersję istniejącej."""
        with self._get_conn() as conn:
            # Szukamy czy istnieje już grupa o tej nazwie w tej sesji
            conn.execute(
                "DELETE FROM session_group WHERE session_id = ?",
                (session.session_id,)
            )
            for group in session.groups:
                #                pilot_ids = [p.pilot_id for p in group.pilots]
                channels = {}
                for (k) in group.channels:
                    v = group.channels[k]
                    channels[k] = v.pilot_id
                conn.execute(
                    "INSERT INTO session_group (session_id, channel_map, group_sequence ) VALUES (?, ?, ?)",
                    (session.session_id,
                     json.dumps(channels), group.group_sequence,)
                )

    # --- OBSŁUGA BIEGÓW (Heats) ---
    def create_or_update_heat(self, heat: Heat, active_pilots: dict[int, ActivePilot]):
        """
        Tworzy nowy rekord w tabeli heat.
        Status domyślnie ustawiony na 'INIT' przez schemat bazy.
        """
        if not heat:
            return

#        print(f"Saving or updating heat: {heat}")

        channels = {}
        for v in heat.channels.keys():
            channels[v] = {
                "pilot_id": heat.channels[v].pilot_id,
                "vtx_channel": heat.channels[v].vtx,
                "is_digital": heat.channels[v].is_digital
            }
        created_at = heat.created_at.timestamp() if heat.created_at else None
        prep_started_at = heat.prep_started_at.timestamp() if heat.prep_started_at else None
        flight_started_at = heat.flight_started_at.timestamp(
        ) if heat.flight_started_at else None
        finished_at = heat.finished_at.timestamp() if heat.finished_at else None
        remaining_seconds_at_pause = heat.remaining_seconds_at_pause
        last_resume_at = heat.last_resume_at.timestamp() if heat.last_resume_at else None
        search = self.get_heat_by_number(
            heat.session_id, heat.heat_number, active_pilots)

        if not search:
            query_heat = """
                INSERT INTO heat (
                    group_id, status, channels_json,
                    prep_time, flight_time,
                    created_at , prep_started_at, flight_started_at, finished_at,
                    remaining_seconds_at_pause, last_resume_at,
                    session_id, heat_number
                ) VALUES (
                    ?, ?, ?,
                    ?,?,
                    ? , ?,?,?,
                    ?, ?,
                    ?, ?
                )
            """
            query_pilots = """
                insert into pilot_heat (
                    vtx_channel, vtx_type, 
                    started_at, finished_at, flight_time,
                    status,
                    session_id ,heat_number, pilot_id)
                values (
                    ?, ?, 
                    ?, ?, ?,
                    ?,
                    ? ,?,?)
                """
        else:
            query_heat = """
                update  heat set
                     group_id=?, status=?, channels_json=?,
                     prep_time =? , flight_time=?,
                    created_at=? , prep_started_at=?, flight_started_at=?, finished_at=?,
                    remaining_seconds_at_pause=?, last_resume_at=?
            where
                    session_id=? and  heat_number=?
            """
            query_pilots = """
                update pilot_heat set
                    vtx_channel=?, vtx_type=?, 
                    started_at=?, finished_at=?, flight_time=?,
                    status=?
                where
                    session_id=? and heat_number=? and pilot_id=?
                """

        params = (heat.group_id, heat.status, json.dumps(channels),
                  heat.prep_time, heat.flight_time,
                  created_at, prep_started_at, flight_started_at, finished_at,
                  remaining_seconds_at_pause, last_resume_at, heat.session_id, heat.heat_number)
        with self._get_conn() as conn:
            conn.execute(query_heat, params)
            conn.commit()

        for k in heat.channels.keys():
            v = heat.channels[k]
            pilot_id = v.pilot_id
            vtx_channel = k
            pilot_params = (vtx_channel, v.vtx,
                            flight_started_at, finished_at, heat.flight_time,
                            heat.status, heat.session_id, heat.heat_number, pilot_id, )
#            print(
#                f"Updating or inserting pilot into heats: {pilot_params} with sql: {query_pilots}")
            with self._get_conn() as conn:
                conn.execute(query_pilots, pilot_params)
                conn.commit()

    def get_active_heats(self, session_id: str, active_pilots: dict[int, ActivePilot]):
        """
        Pobiera listę wszystkich heat-ów dla danej sesji,
        które nie zostały jeszcze zakończone(status inny niż 'FINISHED').
        Wyniki są sortowane po numerze heat-u.
        """
        query = """
             SELECT
                session_id,
                heat_number
            FROM heat
            WHERE session_id = ? AND status != 'FINISHED'
            ORDER BY heat_number ASC
        """

        with self._get_conn() as conn:
            cursor = conn.execute(query, (session_id,))
            rows = cursor.fetchall()

            # Przekształcamy sqlite3.Row na listę słowników i parsujemy JSON-a
            active_heats: list[Heat] = []
            for row in rows:

                heat = self.get_heat_by_number(
                    row["session_id"], row["heat_number"], active_pilots)
                if heat:
                    active_heats.append(heat)
            return active_heats

    def get_heat_by_number(self, session_id: str, heat_number: int, active_pilots: dict[int, ActivePilot]):
        """
        Pobiera listę wszystkich heat-ów dla danej sesji,
        które nie zostały jeszcze zakończone(status inny niż 'FINISHED').
        Wyniki są sortowane po numerze heat-u.
        """
        query = """
            SELECT
                session_id,
                heat_number,
                group_id,
                status,
                prep_time ,
                flight_time,

                channels_json,
                created_at,
                prep_started_at,
                flight_started_at,
                finished_at,
                remaining_seconds_at_pause,
                last_resume_at
            FROM heat
            WHERE session_id = ? AND heat_number = ?
        """

        with self._get_conn() as conn:
            cursor = conn.execute(query, (session_id, heat_number,))
            row = cursor.fetchone()

            if not row:
                return None

            channels_dict = json.loads(row["channels_json"])
            channels: map[str, ActivePilot] = {}
            for (k) in channels_dict.keys():
                v = channels_dict[k]
                pilot_id = v["pilot_id"] if "pilot_id" in v else None
                if pilot_id and pilot_id in active_pilots:
                    channels[k] = active_pilots[pilot_id]

            prep_started_at = datetime.fromtimestamp(
                row["prep_started_at"]) if row["prep_started_at"] else None
            flight_started_at = datetime.fromtimestamp(
                row["flight_started_at"]) if row["flight_started_at"] else None
            finished_at = datetime.fromtimestamp(
                row["finished_at"]) if row["finished_at"] else None
            last_resume_at = datetime.fromtimestamp(
                row["last_resume_at"]) if row["last_resume_at"] else None

            heat = Heat(
                session_id=row["session_id"],
                heat_number=row["heat_number"],
                prep_time=row["prep_time"],
                flight_time=row["flight_time"],
                group_id=row["group_id"],
                channels=channels,
                status=row["status"],

                prep_started_at=prep_started_at,
                flight_started_at=flight_started_at,
                finished_at=finished_at,

                remaining_seconds_at_pause=row["remaining_seconds_at_pause"],
                last_resume_at=last_resume_at
            )
            return heat

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

    # ----------- Obsługa heatów


db_instance = RaceDatabase()


def get_db():
    """ Funkcja pomocnicza do uzyskania instancji bazy danych(np. dla FastAPI) """
    return db_instance
