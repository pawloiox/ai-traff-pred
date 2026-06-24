"""Warstwa trwalosci: SQLite z historia pomiarow ruchu i incydentow.

Tabele:
- measurements: szereg czasowy congestion ratio per punkt.
- incidents: migawki aktywnych incydentow per port.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from .config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    port_id TEXT NOT NULL,
    point_id TEXT NOT NULL,
    point_name TEXT NOT NULL,
    road TEXT,
    lat REAL,
    lon REAL,
    current_speed REAL,
    free_flow_speed REAL,
    congestion_ratio REAL,
    confidence REAL,
    road_closure INTEGER DEFAULT 0,
    source TEXT DEFAULT 'tomtom',
    confidence_label TEXT DEFAULT 'measured',
    intensity REAL
);
CREATE INDEX IF NOT EXISTS idx_meas_point_ts ON measurements(point_id, ts);
CREATE INDEX IF NOT EXISTS idx_meas_ts ON measurements(ts);

CREATE TABLE IF NOT EXISTS incidents (
    snapshot_ts REAL NOT NULL,
    port_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    category INTEGER,
    category_label TEXT,
    description TEXT,
    delay_seconds INTEGER,
    magnitude INTEGER,
    from_name TEXT,
    to_name TEXT,
    lat REAL,
    lon REAL
);
CREATE INDEX IF NOT EXISTS idx_inc_port_ts ON incidents(port_id, snapshot_ts);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    token TEXT PRIMARY KEY,
    role TEXT,
    created_at REAL
);
"""


class Storage:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or settings.db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Dodaje brakujace kolumny do istniejacych baz bez utraty danych.

        ADD COLUMN z DEFAULT wypelnia stare wiersze - cala dotychczasowa historia
        jest traktowana jako TomTom ('tomtom' / 'measured'), bo to bylo jedyne zrodlo.
        """
        existing = {row["name"] for row in self._conn.execute("PRAGMA table_info(measurements)")}
        migrations = {
            "source": "ALTER TABLE measurements ADD COLUMN source TEXT DEFAULT 'tomtom'",
            "confidence_label": "ALTER TABLE measurements ADD COLUMN confidence_label TEXT DEFAULT 'measured'",
            "intensity": "ALTER TABLE measurements ADD COLUMN intensity REAL",
        }
        for col, ddl in migrations.items():
            if col not in existing:
                self._conn.execute(ddl)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- zapis ---------------------------------------------------------------
    def insert_measurement(self, row: Dict[str, Any]) -> None:
        # Domyslne pola zrodlowe: starsi wywolujacy (job TomTom) nie przekazuja ich,
        # wiec laduja jako 'tomtom'/'measured'. TRISTAR/ZDiTM nadpisuja je jawnie.
        full = {
            "source": "tomtom",
            "confidence_label": "measured",
            "intensity": None,
            **row,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO measurements
                (ts, port_id, point_id, point_name, road, lat, lon,
                 current_speed, free_flow_speed, congestion_ratio,
                 confidence, road_closure, source, confidence_label, intensity)
                VALUES (:ts, :port_id, :point_id, :point_name, :road, :lat, :lon,
                        :current_speed, :free_flow_speed, :congestion_ratio,
                        :confidence, :road_closure, :source, :confidence_label, :intensity)
                """,
                full,
            )
            self._conn.commit()

    def replace_incidents(
        self, port_id: str, snapshot_ts: float, rows: List[Dict[str, Any]]
    ) -> None:
        """Czysci poprzednia migawke incydentow danego portu i wstawia nowa."""
        with self._lock:
            self._conn.execute("DELETE FROM incidents WHERE port_id = ?", (port_id,))
            if rows:
                self._conn.executemany(
                    """
                    INSERT INTO incidents
                    (snapshot_ts, port_id, incident_id, category, category_label,
                     description, delay_seconds, magnitude, from_name, to_name, lat, lon)
                    VALUES (:snapshot_ts, :port_id, :incident_id, :category, :category_label,
                            :description, :delay_seconds, :magnitude, :from_name, :to_name, :lat, :lon)
                    """,
                    rows,
                )
            self._conn.commit()

    def save_push_subscription(self, token: str, role: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO push_subscriptions (token, role, created_at) VALUES (?, ?, ?)",
                (token, role, time.time())
            )
            self._conn.commit()

    # --- odczyt --------------------------------------------------------------
    def latest_measurements(self, source: Optional[str] = "tomtom") -> List[Dict[str, Any]]:
        """Najnowszy pomiar dla kazdego punktu w obrebie danego zrodla.

        Domyslnie source='tomtom' - dzieki temu istniejace endpointy (status, anomalie,
        predykcje) widza wylacznie pomiary TomTom i nie mieszaja sie z TRISTAR/ZDiTM,
        ktore zapisuja te same point_id. source=None = wszystkie zrodla (uzytek CPI).
        """
        src_filter = "WHERE source = ?" if source is not None else ""
        params = (source,) if source is not None else ()
        with self._lock:
            cur = self._conn.execute(
                f"""
                SELECT m.* FROM measurements m
                JOIN (
                    SELECT point_id, MAX(ts) AS max_ts
                    FROM measurements {src_filter} GROUP BY point_id
                ) latest
                ON m.point_id = latest.point_id AND m.ts = latest.max_ts
                {('WHERE m.source = ?' if source is not None else '')}
                """,
                params + params,
            )
            return [dict(r) for r in cur.fetchall()]

    def measurements_since(
        self,
        since_ts: float,
        point_id: Optional[str] = None,
        source: Optional[str] = "tomtom",
    ) -> List[Dict[str, Any]]:
        """Pomiary od since_ts. Domyslnie tylko TomTom (jak latest_measurements).
        source=None = wszystkie zrodla."""
        clauses = ["ts >= ?"]
        params: List[Any] = [since_ts]
        if point_id:
            clauses.append("point_id = ?")
            params.append(point_id)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT * FROM measurements WHERE {' AND '.join(clauses)} ORDER BY ts ASC",
                tuple(params),
            )
            return [dict(r) for r in cur.fetchall()]

    def current_incidents(self, port_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            if port_id:
                cur = self._conn.execute(
                    "SELECT * FROM incidents WHERE port_id = ? ORDER BY delay_seconds DESC",
                    (port_id,),
                )
            else:
                cur = self._conn.execute(
                    "SELECT * FROM incidents ORDER BY delay_seconds DESC"
                )
            return [dict(r) for r in cur.fetchall()]

    def purge_older_than(self, max_age_seconds: float) -> None:
        cutoff = time.time() - max_age_seconds
        with self._lock:
            self._conn.execute("DELETE FROM measurements WHERE ts < ?", (cutoff,))
            self._conn.commit()


storage = Storage()
