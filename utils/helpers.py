"""
General helper functions shared across all handler modules.
"""
import asyncio
import logging
import os
from pathlib import Path

from pyrogram import Client, enums
from pyrogram.types import Message

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
    """Return True if *doc* (a Pyrogram Document) is a video file."""
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    ext  = Path(doc.file_name or "").suffix.lower()
    return mime.startswith("video/") or ext in config.VIDEO_EXTENSIONS


# ── Formatting ─────────────────────────────────────────────────────────────────

def fmt_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_duration(seconds: float) -> str:
    """Format a duration in seconds to MM:SS or HH:MM:SS."""
    secs = int(seconds)
    h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ── Group message auto-deletion ────────────────────────────────────────────────

async def _auto_delete(client: Client, chat_id: int, message_id: int) -> None:
    """Delete a group message after AUTO_DELETE_GROUP_SECONDS."""
    delay = config.AUTO_DELETE_GROUP_SECONDS
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, message_id)
    except Exception:
        pass


def schedule_delete(client: Client, message: Message) -> None:
    """Fire-and-forget deletion of bot messages sent in group chats."""
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        asyncio.create_task(
            _auto_delete(client, message.chat.id, message.id)
        )


# ── TG channel logging ─────────────────────────────────────────────────────────

def tg_log(level: str, text: str, message: Message, **kw) -> None:
    """Fire-and-forget TG channel log from within an async handler."""
    u = message.from_user
    asyncio.create_task(
        tgl.tg_log(level, text,
                   user_id=u.id if u else 0,
                   username=(u.username or "") if u else "",
                   **kw)
    )


# ── File download ──────────────────────────────────────────────────────────────

async def download_tg_file(client: Client, message: Message, dest: str) -> None:
    """Download any Telegram file to *dest* via Pyrogram MTProto.

    Uses ``client.download_media`` which routes through MTProto and bypasses
    both the 20 MB download limit and the standard Bot API file-size cap.
    The caller is responsible for deleting *dest* after use.
    """
    downloaded = await client.download_media(message, file_name=dest)
    # Pyrogram may append an extension; use shutil.move for cross-filesystem safety.
    if downloaded and os.path.abspath(str(downloaded)) != os.path.abspath(dest):
        import shutil
        shutil.move(str(downloaded), dest)


async def download_video(
    client: Client,
    message: Message,
) -> tuple[str, str, str]:
    """Download a video from *message* via Pyrogram MTProto.

    Returns ``(file_id, local_path, original_name)``.
    Raises ``ValueError`` for non-video messages or oversized files.

    All downloads use Pyrogram MTProto, natively bypassing the 20 MB
    Telegram Bot API restriction.  The caller must delete *local_path*
    after use (via ``clear_session`` or explicit ``try/finally`` + ``os.remove``).
    """
    if message.video:
        tg_file       = message.video
        original_name = tg_file.file_name or "video.mp4"
        if not Path(original_name).suffix:
            original_name += ".mp4"
    elif message.document and is_video_document(message.document):
        tg_file       = message.document
        original_name = tg_file.file_name or "video.mp4"
    else:
        raise ValueError("Not a recognised video file.")

    file_id   = tg_file.file_id
    file_size = getattr(tg_file, "file_size", None)
    limit_bytes = config.MAX_DOWNLOAD_SIZE_MB * 1024 * 1024
    if file_size is not None and file_size > limit_bytes:
        raise ValueError(
            f"File is too large ({fmt_size(file_size)}).  "
            f"Maximum accepted size is {config.MAX_DOWNLOAD_SIZE_MB} MB "
            f"(Telegram's 2 GB hard limit applies)."
        )

    dest = os.path.join(
        config.DOWNLOAD_DIR,
        f"{message.from_user.id}_{original_name}",
    )
    await download_tg_file(client, message, dest)
    return file_id, dest, original_name
