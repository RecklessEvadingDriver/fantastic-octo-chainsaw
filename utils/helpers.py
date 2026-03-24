"""
General helper functions shared across all handler modules.
"""
import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import config
import tg_logger as tgl
from sessions import _sessions, _active_tasks, ST_SELECTING

logger = logging.getLogger(__name__)


# ── Session helpers ────────────────────────────────────────────────────────────

def get_session(user_id: int) -> dict | None:
    return _sessions.get(user_id)


def new_session(user_id: int, file_id: str, file_name: str) -> dict:
    _sessions[user_id] = {
        "file_id":            file_id,
        "file_name":          file_name,
        "local_path":         "",
        "selected_ops":       set(),
        "rename_to":          None,
        "merge_file_id":      None,
        "merge_file_name":    None,
        "merge_local_path":   "",
        "streams_info":       [],
        "streams_to_remove":  set(),
        "subtitle_file_path": None,
        "subtitle_file_name": None,
        "watermark_path":     None,
        "watermark_name":     None,
        "watermark_position": "bottomright",
        "replace_audio_path": None,
        "trim_start":         "",
        "trim_end":           "",
        "extract_audio_fmt":  "mp3",
        "state":              ST_SELECTING,
        "menu_message_id":    None,
    }
    return _sessions[user_id]


def clear_session(user_id: int) -> None:
    sess = _sessions.pop(user_id, None)
    if sess:
        for path_key in ("local_path", "merge_local_path", "subtitle_file_path",
                         "watermark_path", "replace_audio_path"):
            p = sess.get(path_key) or ""
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


# ── Access control ─────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


# ── File type detection ────────────────────────────────────────────────────────

def is_video_document(doc) -> bool:
    """Return True if *doc* (a Telegram Document) is a video file."""
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    ext  = Path(doc.file_name or "").suffix.lower()
    return mime.startswith("video/") or ext in config.VIDEO_EXTENSIONS


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"


# ── Group message auto-deletion ────────────────────────────────────────────────

async def auto_delete(context: ContextTypes.DEFAULT_TYPE,
                      chat_id: int, message_id: int) -> None:
    """Delete a group message after AUTO_DELETE_GROUP_SECONDS."""
    delay = config.AUTO_DELETE_GROUP_SECONDS
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def schedule_delete(context: ContextTypes.DEFAULT_TYPE,
                    update: Update, message) -> None:
    """Fire-and-forget deletion of bot messages sent in group chats."""
    if update.effective_chat and update.effective_chat.type != "private":
        asyncio.create_task(
            auto_delete(context, update.effective_chat.id, message.message_id)
        )


# ── TG channel logging ─────────────────────────────────────────────────────────

def tg_log(level: str, message: str, update: Update, **kw) -> None:
    """Fire-and-forget TG channel log from within an async handler."""
    u = update.effective_user
    asyncio.create_task(
        tgl.tg_log(level, message,
                   user_id=u.id if u else 0,
                   username=u.username or "" if u else "",
                   **kw)
    )


# ── File download ──────────────────────────────────────────────────────────────

async def download_tg_file(bot, file_id: str, dest: str) -> None:
    """Download any Telegram file to *dest*."""
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)


async def download_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[str, str, str]:
    """
    Download a video from the message.
    Returns (file_id, local_path, original_name).
    Raises ValueError for non-video messages.
    """
    msg = update.message
    if msg.video:
        tg_file = msg.video
        original_name = getattr(tg_file, "file_name", None) or "video.mp4"
        if not Path(original_name).suffix:
            original_name += ".mp4"
    elif msg.document and is_video_document(msg.document):
        tg_file = msg.document
        original_name = tg_file.file_name or "video.mp4"
    else:
        raise ValueError("Not a recognised video file.")

    file_id = tg_file.file_id
    dest = os.path.join(config.DOWNLOAD_DIR,
                        f"{update.effective_user.id}_{original_name}")
    await download_tg_file(context.bot, file_id, dest)
    return file_id, dest, original_name
