"""
SQLite-backed persistence for per-user settings and active processing sessions.
"""
import sqlite3
import logging
import threading
from config import DATABASE_PATH, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_CODEC, DEFAULT_RESOLUTION

logger = logging.getLogger(__name__)

_lock = threading.Lock()

# Whitelist of allowed setting column names (prevents f-string SQL issues)
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


def init_db() -> None:
    """Create tables and apply any pending migrations."""
    with _lock, _get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id           INTEGER PRIMARY KEY,
                crf               INTEGER NOT NULL DEFAULT 23,
                preset            TEXT    NOT NULL DEFAULT 'medium',
                codec             TEXT    NOT NULL DEFAULT 'libx264',
                resolution        TEXT    NOT NULL DEFAULT 'original',
                custom_font_path  TEXT    NOT NULL DEFAULT ''
            );
            """
        )
        # Migration: add custom_font_path to databases created before this column existed
        try:
            conn.execute(
                "ALTER TABLE user_settings ADD COLUMN custom_font_path TEXT NOT NULL DEFAULT ''"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists — nothing to do

    logger.info("Database initialised at %s", DATABASE_PATH)


# ── User settings ──────────────────────────────────────────────────────────────

def get_settings(user_id: int) -> dict:
    """Return settings dict for *user_id*, creating defaults if missing."""
    with _lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO user_settings (user_id, crf, preset, codec, resolution, custom_font_path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, DEFAULT_CRF, DEFAULT_PRESET, DEFAULT_CODEC, DEFAULT_RESOLUTION, ""),
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
    # Ensure the row exists first
    get_settings(user_id)
    with _lock, _get_conn() as conn:
        conn.execute(
            f"UPDATE user_settings SET {col} = ? WHERE user_id = ?",
            (value, user_id),
        )
