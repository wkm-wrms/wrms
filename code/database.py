import sqlite3
import json

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
            conn.execute("""CREATE TABLE IF NOT EXISTS pilots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                country TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name),
                check(name != "")
            )""")
            conn.execute(
                """CREATE index IF NOT EXISTS idx_pilots_name ON pilots(name)""")

            # Użytkownicy (Admini)
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL
            )""")

            # Sesje Treningowe
#            conn.execute("drop table if exists active_pilots")
#            conn.execute("drop table if exists sessions")
            conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
                id text PRIMARY KEY ,
                name TEXT NOT NULL,
                flight_duration_sec INTEGER,
                prep_duration_sec INTEGER,
                is_active BOOLEAN DEFAULT 0,
                current_heat_id INTEGER,
                current_group_id INTEGER,
                next_heat_id INTEGER,
                timer_running BOOLEAN DEFAULT 0,
                timer_start_time_unix REAL,
                current_phase TEXT CHECK(current_phase IN ('IDLE', 'PREP', 'FLIGHT', 'PAUSED', 'FINISHED')) DEFAULT 'IDLE',
                phase_before_pause text   CHECK(phase_before_pause IN ('IDLE', 'PREP', 'FLIGHT', 'PAUSED')) DEFAULT 'PREP',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")

            conn.execute("""CREATE TABLE IF NOT EXISTS active_pilots (
                session_id text not null ,
                pilot_id INTEGER not null ,
                vtx TEXT not null,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (session_id, pilot_id),
                FOREIGN KEY(session_id) REFERENCES sessions(id),
                FOREIGN KEY(pilot_id) REFERENCES pilots(id)
            )""")

            conn.execute("""CREATE INDEX IF NOT EXISTS idx_active_pilots_session_id
                ON active_pilots(session_id)
            """)

            # Grupy Treningowe (z wersjonowaniem przez parent_group_id i version)
            conn.execute("""CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id text not null ,
                pilot_ids TEXT, -- Zapisane jako JSON [1, 2, 5]
                channel_map text , -- zapisane jako JSON "R1" -> pilot ID
                group_sequence INTEGER not null,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )""")
            conn.execute("""CREATE INDEX IF NOT EXISTS idx_groups_session_id
                ON groups(session_id)
            """)

            # Biegi (Heats)

            conn.execute("""CREATE TABLE IF NOT EXISTS heats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id string not null ,
                group_id INTEGER,
                phase TEXT CHECK(phase IN ('PREP', 'FLIGHT', 'NEXT', 'ARCHIVE')),
                start_time_unix REAL, -- Czas startu w formacie Epoch
                end_time_unix REAL,  -- czas zakonczenia biegu
                channels_map TEXT, -- JSON: { channel -> pilot_id ...}
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(group_id) REFERENCES groups(id),
                FOREIGN KEY(session_id) REFERENCES sessions(id)
            )""")
            conn.commit()


# --- OBSŁUGA PILOTÓW --- ---------------------------------------------


    def add_pilot(self, name, country=""):
        """Dodaje nowego pilota do bazy danych."""
        with self._get_conn() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO pilots (name, country) VALUES (?, ?)", (name, country))
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Pilot o tej nazwie już istnieje lub nazwa jest pusta.") from exc
            return cursor.lastrowid

    def get_pilot_by_id(self, pilot_id) -> Pilot:
        """ Pobiera dane pilota na podstawie ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pilots WHERE id = ?", (pilot_id,)).fetchone()
            if row:
                return Pilot(id=row['id'], name=row['name'], country=row['country'])
            else:
                return None

    def search_pilots(self, query):
        """ Szuka pilotów po nazwie (częściowe dopasowanie)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pilots WHERE name LIKE ?", (f"%{query}%",)).fetchall()
            return [Pilot(id=row['id'], name=row['name'], country=row['country'])for row in rows]

    def get_active_pilots(self, session_id: str):
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT pilot_id, vtx FROM active_pilots WHERE session_id = ?", (
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
                INSERT INTO sessions (id, name, flight_duration_sec, prep_duration_sec)
                VALUES (?, ?, ?, ?)
            """, (session.id, session.name, session.flight_duration_sec, session.prep_duration_sec))
            conn.commit()
            return 0

    def get_active_session(self) -> Session:
        """ Pobierz z bazy danych aktywna sesje, jesli jest"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE current_phase <>'FINISHED' LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self.get_session_by_id(row["id"])

    def get_session_by_id(self, session_id: str) -> Session:
        """ Pobierz pełne dane sesji na podstawie jej ID """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
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
                    id=row['id'],
                    is_active=row['is_active'],
                    timer_running=row['timer_running'],
                    current_phase=row['current_phase'],
                    phase_before_pause=row['phase_before_pause'],
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
                UPDATE sessions SET
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
                WHERE id = ?
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
                session.id
            ))
            conn.commit()

    def get_all_sessions(self):
        """ Pobierz z bazy danych wszystkie sesje"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id FROM sessions "
            ).fetchall()
#            return [row["id"] for row in rows]
            return [self.get_session_by_id(row["id"]) for row in rows]

    def session_add_pilot(self, session_id: str, pilot_id: int, vtx: str):
        with self._get_conn() as con:
            try:
                con.execute(
                    "INSERT INTO active_pilots (session_id, pilot_id, vtx) VALUES (?, ?, ?)",
                    (session_id, pilot_id, vtx)
                )
                con.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("Pilot już jest aktywny w grupie") from exc

    def session_remove_pilot(self, session_id: str, pilot_id: int):
        with self._get_conn() as con:
            con.execute(
                "delete from active_pilots where session_id=? and pilot_id =?",
                (session_id, pilot_id)
            )
            con.commit()


# --- OBSŁUGA GRUP

    def get_groups_by_session_id(self, session_id: str):
        """ Get all groups attached to specyfic session """
        with self._get_conn() as conn:
            # Fetch all group IDs for the session
            rows = conn.execute(
                "SELECT id FROM groups WHERE session_id = ? ORDER BY group_sequence",
                (session_id,)
            ).fetchall()

            return [self.get_group_by_id(row["id"]) for row in rows]

    def get_group_by_id(self, id: int):
        """ GEt all session data """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT *  FROM groups WHERE id=?  ORDER BY group_sequence",
                (id,)
            ).fetchone()
            groups: list[Group] = []
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
            if channels_map is not None and isinstance(channels_map, map):
                for channel, pilot_id in channels_map:
                    channels[channel] = pilot_by_id[pilot_id] if pilot_id in pilot_by_id else None
            groups.append(Group(
                id=row['id'], pilots=pilots, channels=channels, group_sequence=row['group_sequence']))
            return groups

    def update_groups(self, session):
        """Tworzy nową grupę lub nową wersję istniejącej."""
        with self._get_conn() as conn:
            # Szukamy czy istnieje już grupa o tej nazwie w tej sesji
            conn.execute(
                "DELETE FROM groups WHERE session_id = ?",
                (session.id,)
            )
            for group in session.groups:
                pilot_ids = [p.pilot.id for p in group.pilots]
                channels = {}
                for (k) in group.channels:
                    v = group.channels[k]
                    channels[k] = v.id
                conn.execute(
                    "INSERT INTO groups (session_id, pilot_ids, channel_map, group_sequence ) VALUES (?, ?, ?, ?)",
                    (session.id,  json.dumps(pilot_ids),
                     json.dumps(channels), group.group_sequence,)
                )

    # --- OBSŁUGA BIEGÓW (Heats) ---

    def save_heat(self, session_id: str, heat: Heat):
        """ Zapisuje w bazie nowy rekord heat"""
        with self._get_conn() as conn:
            pilot_channels = {(channel, pilot.pilot_id)
                              for (channel, pilot) in heat.channels_map}
            cursor = conn.execute("""
                INSERT INTO heats (session_id, group_id, phase, pilot_channels)
                VALUES (?, ?, 'PREP', ?)
                """, session_id, heat.group_id, json.dumps(pilot_channels))
            id = cursor.lastrowid
            heat.set_id(id)
            return heat

    def get_heat_by_id(self, id: int) -> Heat:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM heats WHERE id = ?", (id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            pilots_db = json.loads(data['pilots']) if data["pilots"] else []
            pilot_by_id = {}
            pilots = []
            for pilot_id in pilots_db:
                pilot = self.get_pilot_by_id(pilot_id)
                pilots.append(pilot)
                pilot_by_id[pilot_id] = pilot
            channels_map_db = json.loads(
                data['channels_map']) if data["channels_map"] else []
            channel_map = {(channel, pilot_by_id[pilot_id]) for (
                channel, pilot_id) in channels_map_db}
            time_start = datetime.fromtimestamp(
                data["time_start"]) if data["time_start"] else None
            time_end = datetime.fromtimestamp(
                data["time_end"]) if data["time_end"] else None
            return Heat(heat_id=data[id], group_id=data["group_id"], pilots=pilots, channels_map=channel_map, phase=data["phase"], time_start=time_start, time_end=time_end)

    def update_heat(self, heat: Heat):
        with self._get_conn() as conn:
            cursor = conn.execute("update heats set phase = ? , start_time=?, end_time=? where id=?",
                                  heat.phase,
                                  heat.start_time.timestamp() if heat.time_start else None,
                                  heat.end_time.timestamp() if heat.end_time else None,
                                  heat.heat_id
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


db_instance = RaceDatabase()


def get_db():
    """ Funkcja pomocnicza do uzyskania instancji bazy danych (np. dla FastAPI) """
    return db_instance
