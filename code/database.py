"""
Database layer for WRMS — all SQLite persistence operations.

Provides RaceDatabase, a single class managing pilots, sessions, groups,
heats, and admin credentials. Uses WAL mode for concurrent access.

The database path is resolved from the WRMS_DB_PATH environment variable,
falling back to 'data/race_system.db'. Tests override this variable before
importing the module so the production database is never touched.
"""
import json
import os
import secrets
import sqlite3
from datetime import datetime
import hashlib

from pilot import Pilot
from session import Session, ActivePilot
from group import Group
from heat import Heat

# Increment this whenever the DB schema changes (new table, column, index).
# Used by the backup/restore module to detect version mismatches.
SCHEMA_VERSION = 2


class RaceDatabase:
    """
    SQLite-backed persistence manager for the WRMS race system.

    All public methods open a fresh connection, operate within a context
    manager, and commit before returning. WAL mode and foreign-key checks
    are enabled on every connection.

    Attributes:
        db_path: Path to the SQLite file, resolved at construction time.
    """

    db_path: str = None

    def __init__(self, db_path: str = None):
        """
        Initialise the database, creating the file and tables if needed.

        Args:
            db_path: Explicit file path. When None, reads WRMS_DB_PATH env var
                     and falls back to 'data/race_system.db'.
        """
        if db_path is None:
            db_path = os.environ.get("WRMS_DB_PATH", "data/race_system.db")
        self.db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """Open a connection with WAL mode, foreign keys, and row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys = 1;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        """Create all tables and indexes if they do not already exist."""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pilot (
                    pilot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    country TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name),
                    check(name != '')
                )""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pilots_name ON pilot(name)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_session (
                    token TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    FOREIGN KEY (username) REFERENCES user(username)
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session (
                    session_id text PRIMARY KEY,
                    name TEXT NOT NULL,
                    flight_duration_sec INTEGER,
                    prep_duration_sec INTEGER,
                    is_active BOOLEAN DEFAULT 0,
                    current_heat_number INTEGER,
                    current_group_sequence INTEGER,
                    current_group_index INTEGER,
                    next_group_index INTEGER,
                    next_heat_number INTEGER,
                    current_phase TEXT
                        CHECK(current_phase IN
                            ('IDLE','PREP','FLIGHT','PAUSED','FINISHED'))
                        DEFAULT 'IDLE',
                    phase_before_pause TEXT
                        CHECK(phase_before_pause IN
                            ('IDLE','PREP','FLIGHT','PAUSED'))
                        DEFAULT 'PREP',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS active_pilot (
                    session_id text NOT NULL,
                    pilot_id INTEGER NOT NULL,
                    vtx TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, pilot_id),
                    FOREIGN KEY(session_id) REFERENCES session(session_id),
                    FOREIGN KEY(pilot_id) REFERENCES pilot(pilot_id)
                )""")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_active_pilot_session_id
                    ON active_pilot(session_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_group (
                    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id text NOT NULL,
                    pilot_ids TEXT,
                    channel_map TEXT,
                    group_sequence INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES session(session_id)
                )""")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_groups_session_id
                    ON session_group(session_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS heat (
                    session_id INTEGER NOT NULL,
                    heat_number INTEGER NOT NULL,
                    group_sequence INTEGER NOT NULL,
                    prep_time INTEGER NOT NULL,
                    flight_time INTEGER NOT NULL,
                    status TEXT DEFAULT 'INIT',
                    channels_json TEXT NOT NULL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    prep_started_at REAL,
                    flight_started_at REAL,
                    finished_at REAL,
                    remaining_seconds_at_pause REAL,
                    last_resume_at REAL,
                    phase_before_pause TEXT,
                    PRIMARY KEY (session_id, heat_number),
                    FOREIGN KEY (session_id) REFERENCES session(session_id)
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pilot_heat (
                    pilot_heat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    heat_number INTEGER NOT NULL,
                    pilot_id INTEGER NOT NULL,
                    vtx_channel TEXT NOT NULL,
                    vtx_type TEXT NOT NULL,
                    radio_protocol TEXT,
                    started_at REAL,
                    finished_at REAL,
                    flight_time REAL,
                    status TEXT DEFAULT 'PLANNED',
                    FOREIGN KEY (session_id, heat_number)
                        REFERENCES heat(session_id, heat_number),
                    FOREIGN KEY (pilot_id) REFERENCES pilot(pilot_id),
                    FOREIGN KEY (session_id) REFERENCES session(session_id)
                )""")
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_pilot_history
                    ON pilot_heat (pilot_id, session_id)
            """)
            # Idempotent column renames for databases created before this refactor.
            # ALTER TABLE RENAME COLUMN is a no-op when the old column no longer exists.
            _renames = [
                "ALTER TABLE heat RENAME COLUMN group_id TO group_sequence",
                "ALTER TABLE session RENAME COLUMN current_group_id TO current_group_sequence",
            ]
            for _sql in _renames:
                try:
                    conn.execute(_sql)
                except sqlite3.OperationalError:
                    pass  # column already renamed or freshly created with new name
            # Idempotent column additions for databases created before the auth feature.
            _adds = [
                "ALTER TABLE user ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE heat ADD COLUMN phase_before_pause TEXT",
                "ALTER TABLE pilot ADD COLUMN risk_factor INTEGER DEFAULT 3",
                "ALTER TABLE pilot ADD COLUMN notes TEXT DEFAULT ''",
                "ALTER TABLE active_pilot ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            ]
            for _sql in _adds:
                try:
                    conn.execute(_sql)
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.commit()

    # ------------------------------------------------------------------
    # Pilot operations
    # ------------------------------------------------------------------

    def add_pilot(self, name: str, country: str = "", risk_factor: int = 3, notes: str = "") -> int:
        """
        Insert a new pilot record.

        Args:
            name:        Unique pilot name (non-empty).
            country:     Optional two-letter country code.
            risk_factor: Flying aggressiveness level (1–6, default 3).
            notes:       Optional free-text notes for the race director.

        Returns:
            The newly assigned pilot_id.

        Raises:
            ValueError: If the name is empty or already exists.
        """
        with self._get_conn() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO pilot (name, country, risk_factor, notes) VALUES (?, ?, ?, ?)",
                    (name, country, risk_factor, notes)
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    "Pilot with this name already exists or name is empty."
                ) from exc
            return cursor.lastrowid

    def get_pilot_by_id(self, pilot_id: int) -> Pilot:
        """
        Fetch a pilot by primary key.

        Args:
            pilot_id: The pilot's database ID.

        Returns:
            A Pilot instance, or None if not found.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM pilot WHERE pilot_id = ?", (pilot_id,)
            ).fetchone()
            if row:
                return Pilot(
                    pilot_id=row['pilot_id'],
                    name=row['name'],
                    country=row['country'],
                    risk_factor=row['risk_factor'] if row['risk_factor'] is not None else 3,
                    notes=row['notes'] if row['notes'] is not None else "",
                )
            return None

    def search_pilots(self, query: str) -> list:
        """
        Search pilots by name (case-insensitive partial match).

        Args:
            query: Substring to search for. Pass '' to return all pilots.

        Returns:
            List of matching Pilot instances.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pilot WHERE name LIKE ?", (f"%{query}%",)
            ).fetchall()
            return [
                Pilot(
                    pilot_id=r['pilot_id'],
                    name=r['name'],
                    country=r['country'],
                    risk_factor=r['risk_factor'] if r['risk_factor'] is not None else 3,
                    notes=r['notes'] if r['notes'] is not None else "",
                )
                for r in rows
            ]

    def update_pilot(self, pilot_id: int, name: str, country: str, risk_factor: int, notes: str) -> None:
        """
        Update an existing pilot record.

        Args:
            pilot_id:    The pilot's database ID.
            name:        New unique callsign.
            country:     New country code.
            risk_factor: New aggressiveness level (1–6).
            notes:       New free-text notes.

        Raises:
            ValueError: If name is taken by another pilot.
        """
        with self._get_conn() as conn:
            try:
                conn.execute(
                    "UPDATE pilot SET name=?, country=?, risk_factor=?, notes=? WHERE pilot_id=?",
                    (name, country, risk_factor, notes, pilot_id)
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Pilot name already taken.") from exc

    def delete_pilot(self, pilot_id: int) -> None:
        """
        Delete a pilot record from the database.

        Args:
            pilot_id: The pilot's database ID.
        """
        with self._get_conn() as conn:
            conn.execute("DELETE FROM pilot WHERE pilot_id=?", (pilot_id,))

    def get_active_pilots(self, session_id: str) -> dict[int, ActivePilot]:
        """
        Load all pilots registered in the given session.

        Args:
            session_id: The parent session UUID.

        Returns:
            Dict mapping pilot_id → ActivePilot.
        """
        result = {}
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT pilot_id, vtx, status FROM active_pilot WHERE session_id = ?",
                (session_id,)
            ).fetchall()
            for row in rows:
                result[row["pilot_id"]] = ActivePilot(
                    self.get_pilot_by_id(row['pilot_id']), row["vtx"],
                    status=row["status"]
                )
        return result

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def create_session(self, session: Session):
        """
        Persist a newly created session (name and duration fields only).

        Args:
            session: The Session object to store.
        """
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO session
                       (session_id, name, flight_duration_sec, prep_duration_sec)
                   VALUES (?, ?, ?, ?)""",
                (
                    session.session_id,
                    session.name,
                    session.flight_duration_sec,
                    session.prep_duration_sec,
                ),
            )
            conn.commit()

    def get_active_session(self) -> Session:
        """
        Return the first session whose phase is not FINISHED, or None.

        Used by main.py on startup to restore an interrupted session.

        Returns:
            A fully hydrated Session, or None if no active session exists.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM session WHERE current_phase <> 'FINISHED' LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self.get_session_by_id(row["session_id"])

    def get_session_by_id(self, session_id: str) -> Session:
        """
        Load a complete Session from the database by ID.

        Hydrates active pilots, groups, and the two active heats (current +
        next). Current group is resolved via current_group_index to avoid the
        AUTOINCREMENT / in-memory id mismatch on the current_group_id column.

        Args:
            session_id: The session UUID to load.

        Returns:
            A fully hydrated Session, or None if not found.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM session WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None

            current_heat = next_heat = None
            current_heat_number = next_heat_number = None

            active_pilots = self.get_active_pilots(session_id)
            groups = self.get_groups_by_session_id(session_id, active_pilots)

            # Load the two non-FINISHED heats ordered by heat_number
            heats = self.get_active_heats(session_id, active_pilots)
            if len(heats) >= 1:
                current_heat = heats[0]
                current_heat_number = current_heat.heat_number
            if len(heats) >= 2:
                next_heat = heats[1]
                next_heat_number = next_heat.heat_number

            # Resolve current_group by index (current_group_id stores the
            # in-memory sequential id which does not match DB AUTOINCREMENT)
            idx = row["current_group_index"]
            current_group = (
                groups[idx]
                if idx is not None and groups and idx < len(groups)
                else None
            )

            return Session(
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
                current_group=current_group,
            )

    def save_session_data(self, session: Session):
        """
        Persist all mutable session fields to the database.

        Args:
            session: The Session whose current state should be saved.
        """
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE session SET
                       name = ?,
                       flight_duration_sec = ?,
                       prep_duration_sec = ?,
                       is_active = ?,
                       current_heat_number = ?,
                       next_heat_number = ?,
                       current_group_sequence = ?,
                       current_phase = ?,
                       phase_before_pause = ?,
                       current_group_index = ?,
                       next_group_index = ?
                   WHERE session_id = ?""",
                (
                    session.name,
                    session.flight_duration_sec,
                    session.prep_duration_sec,
                    session.is_active,
                    session.current_heat_number or None,
                    session.next_heat_number or None,
                    session.current_group.group_sequence if session.current_group else None,
                    session.current_phase,
                    session.phase_before_pause,
                    session.current_group_index,
                    session.next_group_index,
                    session.session_id,
                ),
            )
            conn.commit()

    def get_all_sessions(self) -> list:
        """
        Load and return all sessions from the database.

        Returns:
            List of fully hydrated Session objects.
        """
        with self._get_conn() as conn:
            rows = conn.execute("SELECT session_id FROM session").fetchall()
            return [self.get_session_by_id(row["session_id"]) for row in rows]

    def session_add_pilot(self, session_id: str, pilot_id: int, vtx: str):
        """
        Register a pilot as active in the given session.

        Args:
            session_id: Target session UUID.
            pilot_id:   Pilot to add.
            vtx:        VTX type string.

        Raises:
            ValueError: If the pilot is already active in this session.
        """
        with self._get_conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO active_pilot (session_id, pilot_id, vtx) VALUES (?, ?, ?)",
                    (session_id, pilot_id, vtx),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError("Pilot is already active in this session.") from exc

    def session_remove_pilot(self, session_id: str, pilot_id: int):
        """
        Remove a pilot from the active pilot list for the given session.

        Args:
            session_id: Target session UUID.
            pilot_id:   Pilot to remove.
        """
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM active_pilot WHERE session_id=? AND pilot_id=?",
                (session_id, pilot_id),
            )
            conn.commit()

    def update_pilot_status(self, session_id: str, pilot_id: int, status: str):
        """
        Update the participation status of a pilot in a session.

        Args:
            session_id: Target session UUID.
            pilot_id:   Pilot whose status should be changed.
            status:     New status string — 'active' or 'paused'.
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE active_pilot SET status=? WHERE session_id=? AND pilot_id=?",
                (status, session_id, pilot_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Group operations
    # ------------------------------------------------------------------

    def get_groups_by_session_id(
        self, session_id: str, active_pilots: dict[int, ActivePilot]
    ) -> list[Group]:
        """
        Load all groups for a session, ordered by group_sequence.

        Args:
            session_id:    Target session UUID.
            active_pilots: Dict of active pilots used to resolve channel maps.

        Returns:
            List of Group objects in display order.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT group_id FROM session_group "
                "WHERE session_id = ? ORDER BY group_sequence",
                (session_id,),
            ).fetchall()
            return [self.get_group_by_id(row["group_id"], active_pilots) for row in rows]

    def get_group_by_id(
        self, group_id: int, active_pilots: dict[int, ActivePilot]
    ) -> Group:
        """
        Load a single group by its AUTOINCREMENT database ID.

        Channels whose pilot is no longer in active_pilots are silently skipped
        (pilot may have been removed from the session after group assignment).

        Args:
            group_id:      The AUTOINCREMENT primary key in session_group.
            active_pilots: Dict of active pilots for resolving channel maps.

        Returns:
            A Group instance with the current channel assignments.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM session_group WHERE group_id=? ORDER BY group_sequence",
                (group_id,),
            ).fetchone()

            channels_map = json.loads(row['channel_map']) if row['channel_map'] else {}
            channels: dict[str, ActivePilot] = {}
            if isinstance(channels_map, dict):
                for channel, pilot_id in channels_map.items():
                    if pilot_id in active_pilots:
                        channels[channel] = active_pilots[pilot_id]

            return Group(
                group_sequence=row['group_sequence'],
                channels=channels,
            )

    def update_groups(self, session: Session):
        """
        Replace all group records for the session with the current in-memory state.

        Deletes existing rows and re-inserts from session.groups so the DB
        always reflects the latest roster (including manual moves and rebalances).

        Args:
            session: The session whose groups should be persisted.
        """
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM session_group WHERE session_id = ?",
                (session.session_id,),
            )
            for group in session.groups:
                channel_map = {ch: pilot.pilot_id for ch, pilot in group.channels.items()}
                conn.execute(
                    "INSERT INTO session_group (session_id, channel_map, group_sequence)"
                    " VALUES (?, ?, ?)",
                    (session.session_id, json.dumps(channel_map), group.group_sequence),
                )
            conn.commit()

    # ------------------------------------------------------------------
    # Heat operations
    # ------------------------------------------------------------------

    def create_or_update_heat(  # pylint: disable=too-many-locals
        self, heat: Heat, active_pilots: dict[int, ActivePilot]
    ):
        """
        Insert or update a heat record and its per-pilot pilot_heat rows.

        Checks whether the heat already exists (by session_id + heat_number)
        and issues either an INSERT or an UPDATE accordingly.

        Args:
            heat:          The Heat to persist.
            active_pilots: Active pilots dict (used for pilot_heat inserts).
        """
        if not heat:
            return

        # Serialise channel map to JSON
        channels = {
            ch: {
                "pilot_id": slot.pilot_id,
                "vtx_channel": slot.vtx,
                "is_digital": slot.is_digital,
            }
            for ch, slot in heat.channels.items()
        }

        # Convert datetime fields to Unix timestamps for storage
        created_at = heat.created_at.timestamp() if heat.created_at else None
        prep_started_at = heat.prep_started_at.timestamp() if heat.prep_started_at else None
        flight_started_at = (
            heat.flight_started_at.timestamp() if heat.flight_started_at else None
        )
        finished_at = heat.finished_at.timestamp() if heat.finished_at else None
        last_resume_at = heat.last_resume_at.timestamp() if heat.last_resume_at else None

        existing = self.get_heat_by_number(heat.session_id, heat.heat_number, active_pilots)

        if not existing:
            query_heat = """
                INSERT INTO heat (
                    group_sequence, status, channels_json,
                    prep_time, flight_time,
                    created_at, prep_started_at, flight_started_at, finished_at,
                    remaining_seconds_at_pause, last_resume_at,
                    phase_before_pause,
                    session_id, heat_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            query_pilots = """
                INSERT INTO pilot_heat (
                    vtx_channel, vtx_type,
                    started_at, finished_at, flight_time,
                    status, session_id, heat_number, pilot_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        else:
            query_heat = """
                UPDATE heat SET
                    group_sequence=?, status=?, channels_json=?,
                    prep_time=?, flight_time=?,
                    created_at=?, prep_started_at=?, flight_started_at=?,
                    finished_at=?,
                    remaining_seconds_at_pause=?, last_resume_at=?,
                    phase_before_pause=?
                WHERE session_id=? AND heat_number=?
            """
            query_pilots = """
                UPDATE pilot_heat SET
                    vtx_channel=?, vtx_type=?,
                    started_at=?, finished_at=?, flight_time=?,
                    status=?
                WHERE session_id=? AND heat_number=? AND pilot_id=?
            """

        params = (
            heat.group_sequence, heat.status, json.dumps(channels),
            heat.prep_time, heat.flight_time,
            created_at, prep_started_at, flight_started_at, finished_at,
            heat.remaining_seconds_at_pause, last_resume_at,
            heat.phase_before_pause,
            heat.session_id, heat.heat_number,
        )

        with self._get_conn() as conn:
            conn.execute(query_heat, params)
            for ch, slot in heat.channels.items():
                pilot_params = (
                    ch, slot.vtx,
                    flight_started_at, finished_at, heat.flight_time,
                    heat.status,
                    heat.session_id, heat.heat_number, slot.pilot_id,
                )
                conn.execute(query_pilots, pilot_params)
            conn.commit()

    def get_active_heats(
        self, session_id: str, active_pilots: dict[int, ActivePilot]
    ) -> list[Heat]:
        """
        Return all non-FINISHED heats for a session, ordered by heat_number.

        Used by get_session_by_id to restore current and next heat on reload.

        Args:
            session_id:    Target session UUID.
            active_pilots: Dict of active pilots for channel resolution.

        Returns:
            List of Heat objects with status != FINISHED, ascending order.
        """
        query = """
            SELECT session_id, heat_number
            FROM heat
            WHERE session_id = ? AND status != 'FINISHED'
            ORDER BY heat_number ASC
        """
        with self._get_conn() as conn:
            rows = conn.execute(query, (session_id,)).fetchall()
            return [
                h for row in rows
                if (h := self.get_heat_by_number(
                    row["session_id"], row["heat_number"], active_pilots
                )) is not None
            ]

    def get_heat_by_number(
        self,
        session_id: str,
        heat_number: int,
        active_pilots: dict[int, ActivePilot],
    ) -> Heat:
        """
        Load a single heat by session and heat number.

        Args:
            session_id:    Parent session UUID.
            heat_number:   Sequential heat number to fetch.
            active_pilots: Dict of active pilots for channel resolution.

        Returns:
            A Heat instance, or None if not found.
        """
        query = """
            SELECT session_id, heat_number, group_sequence, status,
                   prep_time, flight_time, channels_json, created_at,
                   prep_started_at, flight_started_at, finished_at,
                   remaining_seconds_at_pause, last_resume_at,
                   phase_before_pause
            FROM heat
            WHERE session_id = ? AND heat_number = ?
        """
        with self._get_conn() as conn:
            row = conn.execute(query, (session_id, heat_number)).fetchone()
            if not row:
                return None

            # Resolve channel map: only include pilots still active in the session
            channels_dict = json.loads(row["channels_json"])
            channels: dict[str, ActivePilot] = {}
            for ch, slot in channels_dict.items():
                pid = slot.get("pilot_id") if isinstance(slot, dict) else None
                if pid and pid in active_pilots:
                    channels[ch] = active_pilots[pid]

            # Convert Unix timestamps back to datetime objects
            def _ts(val):
                return datetime.fromtimestamp(val) if val else None

            return Heat(
                session_id=row["session_id"],
                heat_number=row["heat_number"],
                prep_time=row["prep_time"],
                flight_time=row["flight_time"],
                group_sequence=row["group_sequence"],
                channels=channels,
                status=row["status"],
                prep_started_at=_ts(row["prep_started_at"]),
                flight_started_at=_ts(row["flight_started_at"]),
                finished_at=_ts(row["finished_at"]),
                remaining_seconds_at_pause=row["remaining_seconds_at_pause"],
                last_resume_at=_ts(row["last_resume_at"]),
                phase_before_pause=row["phase_before_pause"],
            )

    # ------------------------------------------------------------------
    # Admin / authentication
    # ------------------------------------------------------------------

    def add_admin(self, username: str, password: str) -> bool:
        """
        Create a new admin user with a hashed password.

        Args:
            username: Unique admin username.
            password: Plain-text password (SHA-256 hashed before storage).

        Returns:
            True on success, False if the username already exists.
        """
        hashed = hashlib.sha256(password.encode()).hexdigest()
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO user (username, password_hash) VALUES (?, ?)",
                    (username, hashed),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def verify_admin(self, username: str, password: str) -> bool:
        """
        Verify admin credentials against the stored password hash.

        Args:
            username: Admin username to look up.
            password: Plain-text password to verify.

        Returns:
            True if credentials match, False otherwise.
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM user WHERE username = ?", (username,)
            ).fetchone()
            hashed = hashlib.sha256(password.encode()).hexdigest()
            return bool(row and row['password_hash'] == hashed)

    def create_admin_session(self, username: str) -> str:
        """
        Create a new DB-backed admin session and return the token.

        Session does not expire. Old sessions for the same user are pruned
        on creation to keep the table tidy.

        Args:
            username: The authenticated admin's username.

        Returns:
            A 64-character hex session token.
        """
        token = secrets.token_hex(32)
        now = datetime.now().timestamp()
        expires_at = now + 60 * 60 * 24 * 365 * 100  # non-expiring (100 years)
        with self._get_conn() as conn:
            # Prune old sessions for this user on new login
            conn.execute("DELETE FROM admin_session WHERE username = ?", (username,))
            conn.execute(
                "INSERT INTO admin_session (token, username, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (token, username, now, expires_at),
            )
            conn.commit()
        return token

    def validate_admin_session(self, token: str) -> str:
        """
        Validate a session token and return the associated username.

        Args:
            token: The session cookie value to validate.

        Returns:
            The admin username if the token exists in the database, else None.
        """
        if not token:
            return None
        now = datetime.now().timestamp()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT username FROM admin_session WHERE token = ? AND expires_at > ?",
                (token, now),
            ).fetchone()
            return row["username"] if row else None

    def delete_admin_session(self, token: str):
        """
        Delete a session token (logout).

        Args:
            token: The session token to invalidate.
        """
        with self._get_conn() as conn:
            conn.execute("DELETE FROM admin_session WHERE token = ?", (token,))
            conn.commit()

    def has_any_admin(self) -> bool:
        """
        Return True if at least one admin account exists in the database.

        Used to determine whether the first-time setup flow should be shown.
        """
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM user LIMIT 1").fetchone()
            return row is not None

    def list_admins(self) -> list:
        """
        Return all admin accounts (username and created_at, no password hash).

        Returns:
            List of dicts with 'username' and 'created_at' keys.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT username, created_at FROM user ORDER BY created_at"
            ).fetchall()
            return [{"username": r["username"], "created_at": r["created_at"]} for r in rows]

    def remove_admin(self, username: str) -> bool:
        """
        Delete an admin account and all its active sessions.

        Args:
            username: The admin account to remove.

        Returns:
            True if the account existed and was removed, False if not found.
        """
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM user WHERE username = ?", (username,))
            if cursor.rowcount == 0:
                return False
            conn.execute("DELETE FROM admin_session WHERE username = ?", (username,))
            conn.commit()
        return True

    def set_admin_password(self, username: str, new_password: str) -> bool:
        """
        Update the password hash for an admin account.

        Args:
            username:     Admin account to update.
            new_password: New plain-text password (will be SHA-256 hashed).

        Returns:
            True if the account existed and was updated, False if not found.
        """
        hashed = hashlib.sha256(new_password.encode()).hexdigest()
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE user SET password_hash = ? WHERE username = ?",
                (hashed, username),
            )
            if cursor.rowcount == 0:
                return False
            conn.commit()
        return True


db_instance = RaceDatabase()


def get_db() -> RaceDatabase:
    """Return the module-level RaceDatabase singleton."""
    return db_instance
