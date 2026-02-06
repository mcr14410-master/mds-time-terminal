"""
SQLite Datenbank für Offline-Queue und User-Cache.

Tabellen:
- users: Lokaler Cache der MDS-Benutzerliste
- stamps: Offline-Queue für Stempelungen
- sync_log: Sync-Protokoll
"""

import sqlite3
import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = None


def get_db_path() -> str:
    global DB_PATH
    if DB_PATH is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DB_PATH = os.path.join(base_dir, "terminal.db")
    return DB_PATH


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Erstellt Tabellen falls nicht vorhanden."""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                rfid_chip_id TEXT UNIQUE,
                pin_code TEXT,
                time_tracking_enabled INTEGER DEFAULT 1,
                time_model_name TEXT,
                synced_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_users_rfid ON users(rfid_chip_id);
            CREATE INDEX IF NOT EXISTS idx_users_pin ON users(pin_code);

            CREATE TABLE IF NOT EXISTS stamps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entry_type TEXT NOT NULL CHECK(entry_type IN ('clock_in','clock_out','break_start','break_end')),
                timestamp TEXT NOT NULL,
                synced INTEGER DEFAULT 0,
                sync_attempts INTEGER DEFAULT 0,
                last_sync_attempt TEXT,
                sync_error TEXT,
                server_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_stamps_unsynced ON stamps(synced) WHERE synced = 0;
            CREATE INDEX IF NOT EXISTS idx_stamps_user ON stamps(user_id, timestamp);

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                details TEXT,
                success INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        logger.info("Datenbank initialisiert")
    finally:
        conn.close()


# ============================================
# User-Cache
# ============================================

def sync_users(users_from_server: list):
    """Aktualisiert lokalen User-Cache mit Daten vom Server."""
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        for user in users_from_server:
            conn.execute("""
                INSERT INTO users (id, first_name, last_name, rfid_chip_id, pin_code,
                                   time_tracking_enabled, time_model_name, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    rfid_chip_id = excluded.rfid_chip_id,
                    pin_code = excluded.pin_code,
                    time_tracking_enabled = excluded.time_tracking_enabled,
                    time_model_name = excluded.time_model_name,
                    synced_at = excluded.synced_at
            """, (
                user["id"], user["first_name"], user["last_name"],
                user.get("rfid_chip_id"), user.get("pin_code"),
                1 if user.get("time_tracking_enabled") else 0,
                user.get("time_model_name"),
                now,
            ))
        
        # User die nicht mehr vom Server kommen deaktivieren
        server_ids = [u["id"] for u in users_from_server]
        if server_ids:
            placeholders = ",".join("?" * len(server_ids))
            conn.execute(f"""
                UPDATE users SET time_tracking_enabled = 0
                WHERE id NOT IN ({placeholders})
            """, server_ids)

        conn.commit()
        logger.info(f"User-Cache aktualisiert: {len(users_from_server)} User")
    finally:
        conn.close()


def find_user_by_rfid(rfid_uid: str) -> dict | None:
    """Sucht User anhand RFID-UID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE rfid_chip_id = ? AND time_tracking_enabled = 1",
            (rfid_uid,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_user_by_pin(pin: str) -> dict | None:
    """Sucht User anhand PIN."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE pin_code = ? AND time_tracking_enabled = 1",
            (pin,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_active_users() -> list:
    """Alle aktiven User für PIN-Login Grid."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM users WHERE time_tracking_enabled = 1 ORDER BY last_name, first_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================
# Stempel-Queue
# ============================================

def save_stamp(user_id: int, entry_type: str, timestamp: str) -> int:
    """Speichert Stempelung lokal. Gibt lokale ID zurück."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO stamps (user_id, entry_type, timestamp) VALUES (?, ?, ?)",
            (user_id, entry_type, timestamp)
        )
        conn.commit()
        stamp_id = cursor.lastrowid
        logger.info(f"Stempelung lokal gespeichert: User {user_id}, {entry_type}, ID {stamp_id}")
        return stamp_id
    finally:
        conn.close()


def get_unsynced_stamps() -> list:
    """Alle noch nicht synchronisierten Stempelungen."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM stamps WHERE synced = 0 ORDER BY timestamp ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_stamp_synced(stamp_id: int, server_id: int = None):
    """Markiert Stempelung als synchronisiert."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE stamps SET synced = 1, server_id = ? WHERE id = ?",
            (server_id, stamp_id)
        )
        conn.commit()
    finally:
        conn.close()


def mark_stamp_failed(stamp_id: int, error: str):
    """Markiert fehlgeschlagenen Sync-Versuch."""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE stamps SET 
                sync_attempts = sync_attempts + 1,
                last_sync_attempt = datetime('now'),
                sync_error = ?
            WHERE id = ?
        """, (error, stamp_id))
        conn.commit()
    finally:
        conn.close()


def get_today_stamps(user_id: int) -> list:
    """Heutige Stempelungen eines Users (für Status-Ermittlung)."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT * FROM stamps
            WHERE user_id = ? AND date(timestamp) = ?
            ORDER BY timestamp ASC
        """, (user_id, today)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_last_stamp(user_id: int) -> dict | None:
    """Letzte Stempelung eines Users heute."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT * FROM stamps
            WHERE user_id = ? AND date(timestamp) = ?
            ORDER BY timestamp DESC LIMIT 1
        """, (user_id, today)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_pending_count() -> int:
    """Anzahl ungesyncter Stempelungen."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM stamps WHERE synced = 0").fetchone()
        return row["cnt"]
    finally:
        conn.close()


# ============================================
# Sync-Log
# ============================================

def log_sync_event(event: str, details: str = None, success: bool = True):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sync_log (event, details, success) VALUES (?, ?, ?)",
            (event, details, 1 if success else 0)
        )
        conn.commit()
    finally:
        conn.close()


# ============================================
# Status-Ermittlung
# ============================================

# Gültige Übergänge (State Machine)
VALID_TRANSITIONS = {
    "absent": ["clock_in"],
    "present": ["clock_out", "break_start"],
    "break": ["break_end"],
}

ENTRY_LABELS = {
    "clock_in": "Kommen",
    "clock_out": "Gehen",
    "break_start": "Pause Start",
    "break_end": "Pause Ende",
}


def get_user_status(user_id: int) -> dict:
    """
    Ermittelt aktuellen Status eines Users basierend auf lokalen Stempelungen.
    
    Returns:
        {
            "state": "absent" | "present" | "break",
            "valid_actions": ["clock_in"] | ["clock_out", "break_start"] | ["break_end"],
            "last_entry": {...} | None,
            "today_entries": [...],
            "worked_minutes": int,
            "break_minutes": int,
            "first_clock_in": str | None
        }
    """
    stamps = get_today_stamps(user_id)

    state = "absent"
    worked_minutes = 0
    break_minutes = 0
    clock_in_time = None
    break_start_time = None
    first_clock_in = None

    for s in stamps:
        ts = datetime.fromisoformat(s["timestamp"])

        if s["entry_type"] == "clock_in":
            if first_clock_in is None:
                first_clock_in = s["timestamp"]
            clock_in_time = ts
            state = "present"

        elif s["entry_type"] == "clock_out":
            if clock_in_time:
                worked_minutes += (ts - clock_in_time).total_seconds() / 60
                clock_in_time = None
            state = "absent"

        elif s["entry_type"] == "break_start":
            break_start_time = ts
            state = "break"

        elif s["entry_type"] == "break_end":
            if break_start_time:
                break_minutes += (ts - break_start_time).total_seconds() / 60
                break_start_time = None
            state = "present"

    # Laufende Arbeitszeit (noch eingestempelt)
    if clock_in_time and state == "present":
        worked_minutes += (datetime.now() - clock_in_time).total_seconds() / 60

    # Laufende Pause
    if break_start_time and state == "break":
        break_minutes += (datetime.now() - break_start_time).total_seconds() / 60

    valid_actions = VALID_TRANSITIONS.get(state, [])
    last_entry = stamps[-1] if stamps else None

    return {
        "state": state,
        "valid_actions": valid_actions,
        "last_entry": last_entry,
        "today_entries": stamps,
        "worked_minutes": round(worked_minutes),
        "break_minutes": round(break_minutes),
        "net_minutes": round(worked_minutes - break_minutes),
        "first_clock_in": first_clock_in,
    }
