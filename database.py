"""
SQLite-backed persistence for per-user settings, premium status, and usage stats.
"""
import sqlite3
import logging
import threading
from datetime import datetime, timezone
from config import DATABASE_PATH, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_CODEC, DEFAULT_RESOLUTION

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Whitelist of allowed setting column names (prevents f-string SQL injection)
_ALLOWED_COLUMNS: dict[str, str] = {
    "crf":              "crf",
    "preset":           "preset",
    "codec":            "codec",
    "resolution":       "resolution",
    "custom_font_path": "custom_font_path",
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create tables and apply any pending migrations."""
    with _lock, _get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS bot_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id           INTEGER PRIMARY KEY,
                crf               INTEGER NOT NULL DEFAULT 23,
                preset            TEXT    NOT NULL DEFAULT 'medium',
                codec             TEXT    NOT NULL DEFAULT 'libx264',
                resolution        TEXT    NOT NULL DEFAULT 'original',
                custom_font_path  TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS premium_users (
                user_id   INTEGER PRIMARY KEY,
                added_by  INTEGER NOT NULL DEFAULT 0,
                added_at  TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS user_stats (
                user_id        INTEGER PRIMARY KEY,
                username       TEXT    NOT NULL DEFAULT '',
                first_name     TEXT    NOT NULL DEFAULT '',
                files_processed INTEGER NOT NULL DEFAULT 0,
                last_seen      TEXT    NOT NULL DEFAULT ''
            );
            """
        )
        # Migrations: add columns that may not exist in older databases
        _add_column_if_missing(conn, "user_settings", "custom_font_path",
                               "TEXT NOT NULL DEFAULT ''")

    logger.info("Database initialised at %s", DATABASE_PATH)


def _add_column_if_missing(conn: sqlite3.Connection, table: str,
                            col: str, col_def: str) -> None:
    """ALTER TABLE … ADD COLUMN if the column does not already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ── User settings ──────────────────────────────────────────────────────────────

def get_settings(user_id: int) -> dict:
    """Return settings dict for *user_id*, creating defaults if missing."""
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_settings "
                "(user_id, crf, preset, codec, resolution, custom_font_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, DEFAULT_CRF, DEFAULT_PRESET,
                 DEFAULT_CODEC, DEFAULT_RESOLUTION, ""),
            )
            return {
                "crf": DEFAULT_CRF,
                "preset": DEFAULT_PRESET,
                "codec": DEFAULT_CODEC,
                "resolution": DEFAULT_RESOLUTION,
                "custom_font_path": "",
            }
        return dict(row)


def update_setting(user_id: int, key: str, value) -> None:
    """Upsert a single setting for *user_id*."""
    col = _ALLOWED_COLUMNS.get(key)
    if col is None:
        raise ValueError(f"Unknown setting key: {key!r}")
    get_settings(user_id)  # ensure row exists
    with _lock, _get_conn() as conn:
        conn.execute(
            f"UPDATE user_settings SET {col} = ? WHERE user_id = ?",
            (value, user_id),
        )


# ── Premium users ──────────────────────────────────────────────────────────────

def is_premium(user_id: int) -> bool:
    """Return True if *user_id* has premium status."""
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM premium_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None


def add_premium(user_id: int, added_by: int = 0) -> None:
    """Grant premium status to *user_id*."""
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO premium_users (user_id, added_by, added_at) "
            "VALUES (?, ?, ?)",
            (user_id, added_by, _now()),
        )


def remove_premium(user_id: int) -> None:
    """Revoke premium status from *user_id*."""
    with _lock, _get_conn() as conn:
        conn.execute("DELETE FROM premium_users WHERE user_id = ?", (user_id,))


def list_premium() -> list[dict]:
    """Return all premium users as a list of dicts."""
    with _lock, _get_conn() as conn:
        rows = conn.execute(
            "SELECT p.user_id, p.added_by, p.added_at, "
            "       COALESCE(s.username, '') AS username, "
            "       COALESCE(s.first_name, '') AS first_name "
            "FROM premium_users p "
            "LEFT JOIN user_stats s ON s.user_id = p.user_id "
            "ORDER BY p.added_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── User stats & tracking ──────────────────────────────────────────────────────

def record_user(user_id: int, username: str = "", first_name: str = "") -> None:
    """Upsert a user record (called on every interaction)."""
    with _lock, _get_conn() as conn:
        conn.execute(
            """INSERT INTO user_stats (user_id, username, first_name, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username   = excluded.username,
                   first_name = excluded.first_name,
                   last_seen  = excluded.last_seen""",
            (user_id, username or "", first_name or "", _now()),
        )


def increment_files_processed(user_id: int) -> None:
    """Increment the per-user files-processed counter."""
    record_user(user_id)  # ensure row exists
    with _lock, _get_conn() as conn:
        conn.execute(
            "UPDATE user_stats SET files_processed = files_processed + 1 "
            "WHERE user_id = ?",
            (user_id,),
        )


def get_all_user_ids() -> list[int]:
    """Return every user ID that has ever interacted with the bot."""
    with _lock, _get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM user_stats").fetchall()
        return [r["user_id"] for r in rows]


def get_stats() -> dict:
    """Return aggregate bot statistics."""
    with _lock, _get_conn() as conn:
        total_users = conn.execute(
            "SELECT COUNT(*) FROM user_stats"
        ).fetchone()[0]
        total_premium = conn.execute(
            "SELECT COUNT(*) FROM premium_users"
        ).fetchone()[0]
        total_files = conn.execute(
            "SELECT COALESCE(SUM(files_processed), 0) FROM user_stats"
        ).fetchone()[0]
        return {
            "total_users":   total_users,
            "total_premium": total_premium,
            "total_files":   total_files,
        }


# ── Bot-wide settings (force-join channel, etc.) ──────────────────────────────

def get_bot_setting(key: str, default: str = "") -> str:
    """Return a bot-wide setting value, or *default* if not set."""
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM bot_settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_bot_setting(key: str, value: str) -> None:
    """Upsert a bot-wide setting."""
    with _lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_force_join_channel() -> str:
    """Return the force-join channel identifier, or '' if not set."""
    return get_bot_setting("force_join_channel")


def set_force_join_channel(channel: str) -> None:
    """Persist the force-join channel identifier."""
    set_bot_setting("force_join_channel", channel)


def clear_force_join_channel() -> None:
    """Remove the force-join channel requirement."""
    set_bot_setting("force_join_channel", "")
