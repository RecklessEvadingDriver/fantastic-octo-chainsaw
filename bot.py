"""
Telegram File-Operations Bot
============================
Allows users to select **multiple** file operations in a single session and
process everything in one stretch.

Supported operations
--------------------
  • 🗜  Compress     – re-encode with saved CRF / resolution / preset / codec
  • 📝  Remove Subs  – strip all subtitle streams
  • 🎵  Remove Streams – remove selected audio/video/subtitle streams
  • 🎨  Hardsub (MLRE) – burn subtitles into video with optional custom font
  • ✏️   Rename       – rename the output file
  • 🔗  Merge        – concatenate with a second video

Usage
-----
1.  Send any video / document to the bot.
2.  Toggle the operations you want with the inline buttons.
3.  Press ▶️ Process Now – the bot will ask for any extra input
    (subtitle file, new name, second file, streams to remove) and then run
    everything in one go.

Settings
--------
/settings  – open the persistent settings panel (CRF, resolution, preset, codec)
/setcrf    – quickly change CRF  (e.g. /setcrf 18)
/setres    – quickly change resolution (e.g. /setres 720p or /setres 1280x720)
/setfont   – show current font status (upload .ttf/.otf to set a custom font)
/clearfont – remove saved custom font
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path

from telegram import Document, Update, Video
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import database as db
import ffmpeg_utils as ff
import keyboards as kb
import tg_logger as tgl

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Ensure working directories exist ──────────────────────────────────────────
os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR, exist_ok=True)
os.makedirs(config.FONTS_DIR, exist_ok=True)

# ── In-memory session store ────────────────────────────────────────────────────
# Structure per user_id:
# {
#   "file_id"              : str   – Telegram file_id of the uploaded file
#   "file_name"            : str   – original filename
#   "local_path"           : str   – path where the file has been downloaded
#   "selected_ops"         : set   – currently toggled operations
#   "rename_to"            : str   – new filename (set after user provides it)
#   "merge_file_id"        : str   – file_id of the second file for merge
#   "merge_file_name"      : str   – filename of the second file
#   "merge_local_path"     : str   – local path of the second file
#   "streams_info"         : list  – result of ffprobe
#   "streams_to_remove"    : set   – stream indices to remove
#   "subtitle_file_path"   : str   – local path of uploaded subtitle file
#   "subtitle_file_name"   : str   – original subtitle filename
#   "state"                : str   – current conversation state
#   "menu_message_id"      : int   – message id of the operation-menu message
# }
_sessions: dict[int, dict] = {}

# ── Active-task guard (one task per user at a time) ───────────────────────────
_active_tasks: set[int] = set()

# ── State constants ────────────────────────────────────────────────────────────
ST_SELECTING        = "selecting"
ST_WAIT_RENAME      = "wait_rename"
ST_WAIT_MERGE       = "wait_merge"
ST_WAIT_STREAM      = "wait_stream"
ST_WAIT_SUBTITLE    = "wait_subtitle"
ST_WAIT_WATERMARK   = "wait_watermark"
ST_WAIT_WMARK_POS   = "wait_wmark_pos"
ST_WAIT_REPLACE_AUD = "wait_replace_audio"
ST_WAIT_TRIM        = "wait_trim"
ST_WAIT_AUDIO_FMT   = "wait_audio_fmt"
ST_PROCESSING       = "processing"

# ── File extension sets ────────────────────────────────────────────────────────
SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt"})
FONT_EXTS     = frozenset({".ttf", ".otf"})
IMAGE_EXTS    = frozenset({".png", ".jpg", ".jpeg", ".webp"})
AUDIO_EXTS    = frozenset({".mp3", ".aac", ".ogg", ".opus", ".wav", ".flac", ".m4a"})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _session(user_id: int) -> dict | None:
    return _sessions.get(user_id)


def _new_session(user_id: int, file_id: str, file_name: str) -> dict:
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


def _clear_session(user_id: int) -> None:
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


def _is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


def _is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def _is_video_document(doc) -> bool:
    """Return True if *doc* (a Telegram Document) is a video file."""
    if doc is None:
        return False
    mime = (doc.mime_type or "").lower()
    ext  = Path(doc.file_name or "").suffix.lower()
    return mime.startswith("video/") or ext in config.VIDEO_EXTENSIONS


def _fmt_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.1f} TB"


async def _auto_delete(context: ContextTypes.DEFAULT_TYPE,
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


def _schedule_delete(context: ContextTypes.DEFAULT_TYPE,
                      update: Update, message) -> None:
    """Fire-and-forget deletion of bot messages sent in group chats."""
    if update.effective_chat and update.effective_chat.type != "private":
        asyncio.create_task(
            _auto_delete(context, update.effective_chat.id, message.message_id)
        )


def _tg_log(level: str, message: str, update: Update, **kw) -> None:
    """Fire-and-forget TG channel log from within an async handler."""
    u = update.effective_user
    asyncio.create_task(
        tgl.tg_log(level, message,
                   user_id=u.id if u else 0,
                   username=u.username or "" if u else "",
                   **kw)
    )


async def _download_tg_file(bot, file_id: str, dest: str) -> None:
    """Download any Telegram file to *dest*."""
    tg_file = await bot.get_file(file_id)
    await tg_file.download_to_drive(dest)


async def _download_video(
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
    elif msg.document and _is_video_document(msg.document):
        tg_file = msg.document
        original_name = tg_file.file_name or "video.mp4"
    else:
        raise ValueError("Not a recognised video file.")

    file_id = tg_file.file_id
    dest = os.path.join(config.DOWNLOAD_DIR,
                        f"{update.effective_user.id}_{original_name}")
    await _download_tg_file(context.bot, file_id, dest)
    return file_id, dest, original_name


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    db.record_user(update.effective_user.id,
                   update.effective_user.username or "",
                   update.effective_user.first_name or "")
    msg = await update.message.reply_text(
        "👋 *Video Processing Bot*\n\n"
        "Send me any *video file* and choose from:\n"
        "  🗜 Compress  •  📝 Remove Subs  •  🎵 Remove Streams\n"
        "  🎨 Hardsub (MLRE)  •  ✂️ Trim  •  🎶 Extract Audio\n"
        "  🔄 Replace Audio  •  🖼 Watermark  •  ✏️ Rename  •  🔗 Merge\n\n"
        "Select *multiple* operations at once — all run in one pass.\n\n"
        "📌 *Results are always sent to your PM.*\n"
        "🎨 Upload any `.ttf`/`.otf` file to set a custom hardsub font.\n\n"
        "/settings – compression & encoding settings\n"
        "/setfont  – manage custom rendering font",
        parse_mode="Markdown",
    )
    _schedule_delete(context, update, msg)


# ── /settings ──────────────────────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
    db.record_user(user_id, update.effective_user.username or "",
                   update.effective_user.first_name or "")
    s = db.get_settings(user_id)
    font_name = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
    text = (
        "⚙️ *Current Settings*\n\n"
        f"  • CRF: `{s['crf']}`\n"
        f"  • Resolution: `{s['resolution']}`\n"
        f"  • Preset: `{s['preset']}`\n"
        f"  • Codec: `{s['codec']}`\n"
        f"  • Font: `{font_name}`\n\n"
        "These settings are saved and used automatically every time you compress or hardsub."
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=kb.settings_menu())


# ── /setcrf <value> ────────────────────────────────────────────────────────────

async def cmd_setcrf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /setcrf <value>  (e.g. /setcrf 18)\nRange: 0–51, lower = better quality.")
        return
    value = int(args[0])
    if not 0 <= value <= 51:
        await update.message.reply_text("CRF must be between 0 and 51.")
        return
    db.update_setting(update.effective_user.id, "crf", value)
    msg = await update.message.reply_text(f"✅ CRF set to `{value}`.", parse_mode="Markdown")
    _schedule_delete(context, update, msg)


# ── /setres <resolution> ───────────────────────────────────────────────────────

async def cmd_setres(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    args = context.args
    if not args:
        opts = ", ".join(config.RESOLUTION_MAP.keys())
        await update.message.reply_text(
            f"Usage: /setres <resolution>\n\nShortcuts: {opts}\nor custom e.g. /setres 1280x720"
        )
        return
    val = args[0].lower()
    resolved = config.RESOLUTION_MAP.get(val, val)  # allow raw WxH values too
    db.update_setting(update.effective_user.id, "resolution", resolved)
    msg = await update.message.reply_text(f"✅ Resolution set to `{resolved}`.", parse_mode="Markdown")
    _schedule_delete(context, update, msg)


# ── /setfont ───────────────────────────────────────────────────────────────────

async def cmd_setfont(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
    s = db.get_settings(user_id)
    font_path = s.get("custom_font_path", "")
    if font_path and os.path.exists(font_path):
        font_name = Path(font_path).name
        await update.message.reply_text(
            f"🎨 Current font: *{font_name}*\n\n"
            "Upload a new `.ttf` or `.otf` file to replace it, "
            "or use /clearfont to remove it.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🎨 No custom font set.\n\n"
            "Upload any `.ttf` or `.otf` file and I'll save it as your "
            "rendering font for *Hardsub* operations.",
            parse_mode="Markdown",
        )


# ── /clearfont ─────────────────────────────────────────────────────────────────

async def cmd_clearfont(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
    s = db.get_settings(user_id)
    old_font = s.get("custom_font_path", "")
    if old_font and os.path.exists(old_font):
        try:
            os.remove(old_font)
        except OSError:
            pass
    db.update_setting(user_id, "custom_font_path", "")
    await update.message.reply_text(
        "✅ Custom font cleared. Default system font will be used for hardsub.",
        parse_mode="Markdown",
    )
    asyncio.create_task(
        tgl.tg_log(
            "INFO", "Custom font cleared",
            user_id=user_id,
            username=update.effective_user.username or "",
        )
    )


# ══════════════════════════════════════════════════════════════════════════════
# Admin commands
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /addpremium <user_id>")
        return
    target = int(args[0])
    db.add_premium(target, added_by=update.effective_user.id)
    await update.message.reply_text(f"✅ User `{target}` is now premium.",
                                    parse_mode="Markdown")
    _tg_log("INFO", f"Premium granted to {target}", update)


async def cmd_removepremium(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /removepremium <user_id>")
        return
    target = int(args[0])
    db.remove_premium(target)
    await update.message.reply_text(f"✅ Premium removed from `{target}`.",
                                    parse_mode="Markdown")
    _tg_log("INFO", f"Premium revoked from {target}", update)


async def cmd_listpremium(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    users = db.list_premium()
    if not users:
        await update.message.reply_text("No premium users.")
        return
    lines = ["👑 *Premium Users*\n"]
    for u in users:
        uname = f" (@{u['username']})" if u.get("username") else ""
        fn    = u.get("first_name", "")
        lines.append(
            f"  • `{u['user_id']}`{uname} {fn} — added {u['added_at'][:10]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    s = db.get_stats()
    text = (
        "📊 *Bot Statistics*\n\n"
        f"  • Total users:     `{s['total_users']}`\n"
        f"  • Premium users:   `{s['total_premium']}`\n"
        f"  • Files processed: `{s['total_files']}`\n"
        f"  • Active tasks:    `{len(_active_tasks)}`\n"
        f"  • Active sessions: `{len(_sessions)}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_broadcast(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text     = " ".join(context.args)
    user_ids = db.get_all_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # ~20 msgs/sec
    await update.message.reply_text(
        f"📢 Broadcast done.\n✅ Sent: {sent}   ❌ Failed: {failed}"
    )
    _tg_log("INFO", f"Broadcast: {sent}/{sent+failed}", update)


# ── File upload handler ────────────────────────────────────────────────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id
    msg     = update.message
    db.record_user(user_id, update.effective_user.username or "",
                   update.effective_user.first_name or "")

    # ── Detect special file types by extension ─────────────────────────────────
    if msg.document:
        doc_ext = Path(msg.document.file_name or "").suffix.lower()
        sess    = _session(user_id)

        if doc_ext in FONT_EXTS:
            await _handle_font_upload(update, context)
            return

        if doc_ext in SUBTITLE_EXTS:
            if sess and sess["state"] == ST_WAIT_SUBTITLE:
                await _handle_subtitle_upload(update, context, sess)
            else:
                r = await update.message.reply_text(
                    "📄 Subtitle file received.\n"
                    "To use it, first send a video then select 🎨 Hardsub.",
                    parse_mode="Markdown",
                )
                _schedule_delete(context, update, r)
            return

        if doc_ext in IMAGE_EXTS:
            if sess and sess["state"] == ST_WAIT_WATERMARK:
                await _handle_watermark_upload(update, context, sess)
            else:
                r = await update.message.reply_text(
                    "🖼 Image received. Select 🖼 Watermark and press ▶️ to use it."
                )
                _schedule_delete(context, update, r)
            return

        if doc_ext in AUDIO_EXTS:
            if sess and sess["state"] == ST_WAIT_REPLACE_AUD:
                await _handle_replace_audio_upload(update, context, sess)
            else:
                r = await update.message.reply_text(
                    "🎵 Audio file received. Select 🔄 Replace Audio to use it."
                )
                _schedule_delete(context, update, r)
            return

    sess = _session(user_id)

    # ── Route waiting states ───────────────────────────────────────────────────
    if sess and sess["state"] == ST_WAIT_MERGE:
        if msg.video or (msg.document and _is_video_document(msg.document)):
            await _receive_merge_file(update, context, sess)
            return

    if msg.audio and sess and sess["state"] == ST_WAIT_REPLACE_AUD:
        await _handle_replace_audio_upload(update, context, sess, use_audio=True)
        return

    # ── Videos only for new sessions ──────────────────────────────────────────
    is_video = msg.video or (msg.document and _is_video_document(msg.document))
    if not is_video:
        r = await update.message.reply_text(
            "❌ Videos only.\nSend .mp4, .mkv, .avi, .mov, or any other video file."
        )
        _schedule_delete(context, update, r)
        return

    # ── One-task-per-user guard ────────────────────────────────────────────────
    if user_id in _active_tasks:
        r = await update.message.reply_text(
            "⏳ You already have a task running. Please wait for it to finish."
        )
        _schedule_delete(context, update, r)
        return

    # ── Download and start session ─────────────────────────────────────────────
    status_msg = await update.message.reply_text("⏳ Downloading your video…")
    try:
        file_id, local_path, original_name = await _download_video(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        _schedule_delete(context, update, status_msg)
        return

    await status_msg.delete()

    asyncio.create_task(
        tgl.tg_log(
            "FILE", f"Video received: {original_name}",
            user_id=user_id,
            username=update.effective_user.username or "",
            extra={"size": _fmt_size(os.path.getsize(local_path))},
        )
    )

    sess = _new_session(user_id, file_id, original_name)
    sess["local_path"]   = local_path
    sess["streams_info"] = await asyncio.to_thread(ff.probe_streams, local_path)

    menu_msg = await update.message.reply_text(
        f"📁 *{original_name}*\n\n"
        "Select the operations you want to apply, then press ▶️ Process Now.\n"
        "_Results will be sent to your PM._",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    sess["menu_message_id"] = menu_msg.message_id
    _schedule_delete(context, update, menu_msg)


async def _receive_merge_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    status_msg = await update.message.reply_text("⏳ Downloading merge file…")
    try:
        file_id, local_path, original_name = await _download_video(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        _schedule_delete(context, update, status_msg)
        return
    await status_msg.delete()

    sess["merge_file_id"]    = file_id
    sess["merge_file_name"]  = original_name
    sess["merge_local_path"] = local_path
    sess["state"]            = ST_SELECTING

    r = await update.message.reply_text(
        f"✅ Merge file received: *{original_name}*\n\nPress ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    _schedule_delete(context, update, r)


async def _handle_font_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Save an uploaded .ttf/.otf file as the user's default rendering font."""
    user_id   = update.effective_user.id
    doc       = update.message.document
    font_name = doc.file_name or "custom_font.ttf"

    fonts_dir = os.path.join(config.FONTS_DIR, str(user_id))
    os.makedirs(fonts_dir, exist_ok=True)
    font_path = os.path.join(fonts_dir, font_name)

    status_msg = await update.message.reply_text("⏳ Saving font file…")
    await _download_tg_file(context.bot, doc.file_id, font_path)
    await status_msg.delete()

    db.update_setting(user_id, "custom_font_path", font_path)

    r = await update.message.reply_text(
        f"🎨 Font *{font_name}* saved as your default rendering font.\n\n"
        "It will be used automatically for *Hardsub* operations.\n"
        "Use /clearfont to remove it.",
        parse_mode="Markdown",
    )
    _schedule_delete(context, update, r)
    asyncio.create_task(
        tgl.tg_log(
            "INFO", f"Custom font set: {font_name}",
            user_id=user_id,
            username=update.effective_user.username or "",
        )
    )


async def _handle_subtitle_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    """Download a subtitle file while in ST_WAIT_SUBTITLE state."""
    user_id  = update.effective_user.id
    doc      = update.message.document
    sub_name = doc.file_name or "subtitle.srt"
    sub_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_sub_{sub_name}")

    status_msg = await update.message.reply_text("⏳ Downloading subtitle file…")
    await _download_tg_file(context.bot, doc.file_id, sub_path)
    await status_msg.delete()

    sess["subtitle_file_path"] = sub_path
    sess["subtitle_file_name"] = sub_name
    sess["state"]              = ST_SELECTING

    s = db.get_settings(user_id)
    font_info = (
        f"Font: *{Path(s['custom_font_path']).name}*"
        if s.get("custom_font_path") and os.path.exists(s["custom_font_path"])
        else "Font: system default (upload .ttf/.otf or /setfont)"
    )
    r = await update.message.reply_text(
        f"✅ Subtitle received: *{sub_name}*\n{font_info}\n\nPress ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    _schedule_delete(context, update, r)


async def _handle_watermark_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    """Download a watermark image while in ST_WAIT_WATERMARK state."""
    user_id = update.effective_user.id
    doc     = update.message.document
    wm_name = doc.file_name or "watermark.png"
    wm_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_wm_{wm_name}")

    status_msg = await update.message.reply_text("⏳ Downloading watermark image…")
    await _download_tg_file(context.bot, doc.file_id, wm_path)
    await status_msg.delete()

    sess["watermark_path"] = wm_path
    sess["watermark_name"] = wm_name
    sess["state"]          = ST_WAIT_WMARK_POS

    r = await update.message.reply_text(
        f"✅ Watermark image received: *{wm_name}*\n\nChoose the position:",
        parse_mode="Markdown",
        reply_markup=kb.watermark_position_menu(),
    )
    _schedule_delete(context, update, r)


async def _handle_replace_audio_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
    use_audio: bool = False,
) -> None:
    """Download a replacement audio file while in ST_WAIT_REPLACE_AUD state."""
    user_id = update.effective_user.id
    if use_audio:
        tg_obj  = update.message.audio
        au_name = getattr(tg_obj, "file_name", None) or "audio.mp3"
    else:
        tg_obj  = update.message.document
        au_name = tg_obj.file_name or "audio.mp3"
    au_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_aud_{au_name}")

    status_msg = await update.message.reply_text("⏳ Downloading audio file…")
    await _download_tg_file(context.bot, tg_obj.file_id, au_path)
    await status_msg.delete()

    sess["replace_audio_path"] = au_path
    sess["state"]              = ST_SELECTING

    r = await update.message.reply_text(
        f"✅ Audio file received: *{au_name}*\n\nPress ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    _schedule_delete(context, update, r)


# ── Text message handler (rename, trim) ───────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    if update.message is None or not update.message.text:
        return

    user_id = update.effective_user.id
    sess = _session(user_id)
    if not sess:
        return

    text = update.message.text.strip()

    if sess["state"] == ST_WAIT_RENAME:
        if not text:
            await update.message.reply_text("Please send a valid filename.")
            return
        if not Path(text).suffix:
            text = text + Path(sess["file_name"]).suffix
        sess["rename_to"] = text
        sess["state"]     = ST_SELECTING
        r = await update.message.reply_text(
            f"✅ Will rename output to: *{text}*\n\nPress ▶️ Process Now.",
            parse_mode="Markdown",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        _schedule_delete(context, update, r)
        return

    if sess["state"] == ST_WAIT_TRIM:
        parts = text.split()
        if not parts:
            await update.message.reply_text(
                "Format: `HH:MM:SS [HH:MM:SS]`  e.g. `00:01:30 00:05:00`",
                parse_mode="Markdown",
            )
            return
        sess["trim_start"] = parts[0]
        sess["trim_end"]   = parts[1] if len(parts) > 1 else ""
        sess["state"]      = ST_SELECTING
        rng = f"`{parts[0]}`" + (f" → `{parts[1]}`" if len(parts) > 1 else " → end")
        r = await update.message.reply_text(
            f"✅ Trim range: {rng}\n\nPress ▶️ Process Now.",
            parse_mode="Markdown",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        _schedule_delete(context, update, r)
        return


# ── Callback query handler ─────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data    = query.data

    # ── Settings panel ─────────────────────────────────────────────────────────
    if data == "cfg:crf":
        await query.edit_message_text(
            "Send /setcrf <value> (0–51).\nLower = better quality. Recommended: 18–28."
        )
        return

    if data == "cfg:resolution":
        await query.edit_message_text("Choose a resolution preset:",
                                       reply_markup=kb.resolution_menu())
        return

    if data == "cfg:preset":
        await query.edit_message_text(
            "Choose an encoding preset.\nSlower = smaller file, longer encode time.",
            reply_markup=kb.preset_menu(),
        )
        return

    if data == "cfg:codec":
        await query.edit_message_text("Choose a video codec:",
                                       reply_markup=kb.codec_menu())
        return

    if data in ("cfg:back", "cfg:back_to_settings"):
        s = db.get_settings(user_id)
        fn = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
        text = (
            "⚙️ *Current Settings*\n\n"
            f"  • CRF: `{s['crf']}`\n"
            f"  • Resolution: `{s['resolution']}`\n"
            f"  • Preset: `{s['preset']}`\n"
            f"  • Codec: `{s['codec']}`\n"
            f"  • Font: `{fn}`\n\n"
            "Saved and used for every Compress & Hardsub operation."
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=kb.settings_menu())
        return

    if data == "cfg:font":
        s  = db.get_settings(user_id)
        fp = s.get("custom_font_path", "")
        if fp and os.path.exists(fp):
            text = (
                f"🎨 *Current font:* `{Path(fp).name}`\n\n"
                "Upload a new `.ttf`/`.otf` to replace, or /clearfont."
            )
        else:
            text = (
                "🎨 *No custom font set.*\n\n"
                "Upload any `.ttf`/`.otf` for hardsub rendering."
            )
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=kb.settings_menu())
        return

    if data.startswith("set:"):
        _, key, value = data.split(":", 2)
        if key == "resolution":
            value = config.RESOLUTION_MAP.get(value, value)
        db.update_setting(user_id, key, value)
        s  = db.get_settings(user_id)
        fn = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
        text = (
            f"✅ *{key.capitalize()}* → `{value}`\n\n"
            "⚙️ *Settings*\n\n"
            f"  • CRF: `{s['crf']}`\n"
            f"  • Resolution: `{s['resolution']}`\n"
            f"  • Preset: `{s['preset']}`\n"
            f"  • Codec: `{s['codec']}`\n"
            f"  • Font: `{fn}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown",
                                       reply_markup=kb.settings_menu())
        return

    # ── Watermark position ─────────────────────────────────────────────────────
    if data.startswith("wmpos:"):
        sess = _session(user_id)
        if sess:
            sess["watermark_position"] = data[6:]
            sess["state"]              = ST_SELECTING
            await query.edit_message_text(
                f"✅ Watermark position: *{data[6:]}*\n\nPress ▶️ Process Now.",
                parse_mode="Markdown",
                reply_markup=kb.operation_menu(sess["selected_ops"]),
            )
        return

    # ── Audio format (Extract Audio) ───────────────────────────────────────────
    if data.startswith("audioformat:"):
        sess = _session(user_id)
        if sess:
            fmt = data[12:]
            sess["extract_audio_fmt"] = fmt
            sess["state"]             = ST_SELECTING
            await query.edit_message_text(
                f"✅ Audio format: *{fmt.upper()}*\n\nPress ▶️ Process Now.",
                parse_mode="Markdown",
                reply_markup=kb.operation_menu(sess["selected_ops"]),
            )
        return

    # ── Operation menu ─────────────────────────────────────────────────────────
    sess = _session(user_id)
    if not sess:
        await query.edit_message_text("⚠️ Session expired. Please send your video again.")
        return

    if sess["state"] == ST_PROCESSING:
        await query.answer("⏳ Already processing, please wait…", show_alert=True)
        return

    if data.startswith("op:"):
        op_key = data[3:]
        if op_key in sess["selected_ops"]:
            sess["selected_ops"].discard(op_key)
        else:
            sess["selected_ops"].add(op_key)
        await query.edit_message_reply_markup(
            reply_markup=kb.operation_menu(sess["selected_ops"])
        )
        return

    if data == "cancel":
        _clear_session(user_id)
        await query.edit_message_text("❌ Cancelled. Send a new video when ready.")
        return

    if data == "process":
        await _start_processing(update, context, query, sess)
        return

    # ── Stream selection toggles ───────────────────────────────────────────────
    if data.startswith("stream:"):
        suffix = data[7:]
        if suffix == "confirm":
            sess["state"] = ST_SELECTING
            await query.edit_message_text(
                f"✅ Will remove {len(sess['streams_to_remove'])} stream(s).\n\n"
                "Press ▶️ Process Now.",
                reply_markup=kb.operation_menu(sess["selected_ops"]),
            )
        elif suffix == "cancel":
            sess["streams_to_remove"].clear()
            sess["selected_ops"].discard("remove_streams")
            sess["state"] = ST_SELECTING
            await query.edit_message_reply_markup(
                reply_markup=kb.operation_menu(sess["selected_ops"])
            )
        else:
            idx = int(suffix)
            if idx in sess["streams_to_remove"]:
                sess["streams_to_remove"].discard(idx)
            else:
                sess["streams_to_remove"].add(idx)
            await query.edit_message_reply_markup(
                reply_markup=kb.stream_selection_menu(
                    sess["streams_info"], sess["streams_to_remove"]
                )
            )
        return


# ── Core processing logic ──────────────────────────────────────────────────────

async def _start_processing(update: Update,
                             context: ContextTypes.DEFAULT_TYPE,
                             query,
                             sess: dict) -> None:
    user_id = update.effective_user.id

    if not sess["selected_ops"]:
        await query.answer("⚠️ Please select at least one operation.", show_alert=True)
        return

    ops = sess["selected_ops"]

    # ── Gather extra inputs needed before running ─────────────────────────────
    if "remove_streams" in ops and not sess["streams_to_remove"]:
        if not sess["streams_info"]:
            await query.answer("⚠️ Could not read streams.", show_alert=True)
            return
        sess["state"] = ST_WAIT_STREAM
        await query.edit_message_text(
            "🎵 *Select streams to remove* (tap to toggle):",
            parse_mode="Markdown",
            reply_markup=kb.stream_selection_menu(
                sess["streams_info"], sess["streams_to_remove"]
            ),
        )
        return

    if "hardsub" in ops and not sess.get("subtitle_file_path"):
        sess["state"] = ST_WAIT_SUBTITLE
        await query.edit_message_text(
            "🎨 *Hardsub selected.*\n\nSend your subtitle file (.srt / .ass / .ssa):",
            parse_mode="Markdown",
        )
        return

    if "rename" in ops and not sess.get("rename_to"):
        sess["state"] = ST_WAIT_RENAME
        await query.edit_message_text(
            "✏️ Send the *new filename* (with or without extension):",
            parse_mode="Markdown",
        )
        return

    if "merge" in ops and not sess.get("merge_file_id"):
        sess["state"] = ST_WAIT_MERGE
        await query.edit_message_text(
            "🔗 Send the *second video* to merge with:",
            parse_mode="Markdown",
        )
        return

    if "watermark" in ops and not sess.get("watermark_path"):
        sess["state"] = ST_WAIT_WATERMARK
        await query.edit_message_text(
            "🖼 Send the *watermark image* (PNG or JPG):",
            parse_mode="Markdown",
        )
        return

    if "replace_audio" in ops and not sess.get("replace_audio_path"):
        sess["state"] = ST_WAIT_REPLACE_AUD
        await query.edit_message_text(
            "🔄 Send the *replacement audio file*:",
            parse_mode="Markdown",
        )
        return

    if "trim" in ops and not sess.get("trim_start"):
        sess["state"] = ST_WAIT_TRIM
        await query.edit_message_text(
            "✂️ Send the *trim range*: `start [end]`\ne.g. `00:01:30 00:05:00`",
            parse_mode="Markdown",
        )
        return

    if "extract_audio" in ops and not sess.get("extract_audio_fmt"):
        sess["state"] = ST_WAIT_AUDIO_FMT
        await query.edit_message_text(
            "🎶 Choose output audio format:",
            reply_markup=kb.audio_format_menu(),
        )
        return

    # ── One-task-per-user guard ────────────────────────────────────────────────
    if user_id in _active_tasks:
        await query.answer("⏳ Already processing. Please wait.", show_alert=True)
        return

    # ── All inputs ready – start ───────────────────────────────────────────────
    sess["state"] = ST_PROCESSING
    _active_tasks.add(user_id)

    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚙️ Processing… please wait.",
    )
    _schedule_delete(context, update, status_msg)
    asyncio.create_task(
        tgl.tg_log(
            "PROCESS", f"Processing started: {', '.join(sorted(ops))}",
            user_id=user_id,
            username=update.effective_user.username or "",
        )
    )

    try:
        output_files = await asyncio.to_thread(_process_file, user_id, sess)
    except Exception as exc:
        logger.exception("Processing failed for user %s", user_id)
        err_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Processing failed:\n<code>{exc}</code>",
            parse_mode="HTML",
        )
        _schedule_delete(context, update, err_msg)
        asyncio.create_task(
            tgl.tg_log(
                "ERROR", f"Processing failed: {exc}",
                user_id=user_id,
                username=update.effective_user.username or "",
            )
        )
        _active_tasks.discard(user_id)
        _clear_session(user_id)
        return

    # ── Deliver results to user's PM ──────────────────────────────────────────
    try:
        await status_msg.edit_text("📤 Sending result to your PM…")
    except Exception:
        pass

    final_base  = sess.get("rename_to") or Path(sess["file_name"]).stem
    ops_caption = ", ".join(sorted(ops))
    total_parts = len(output_files)
    delivered   = 0

    for i, out_path in enumerate(output_files):
        part_label = f"Part {i + 1}/{total_parts}\n" if total_parts > 1 else ""
        caption    = f"✅ {part_label}Operations: {ops_caption}"
        fname      = (
            f"{final_base}.part{i + 1:03d}{Path(out_path).suffix}"
            if total_parts > 1
            else (sess.get("rename_to") or Path(out_path).name)
        )
        try:
            with open(out_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,        # always PM
                    document=f,
                    filename=fname,
                    caption=caption,
                )
            delivered += 1
        except Forbidden:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ I can't send files to your PM. "
                     "Please start a chat with me first, then try again.",
            )
            break
        except Exception as exc:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Upload failed (part {i + 1}): {exc}",
            )
        finally:
            try:
                os.remove(out_path)
            except OSError:
                pass

    asyncio.create_task(
        tgl.tg_log(
            "SUCCESS" if delivered == total_parts else "WARN",
            f"Delivered {delivered}/{total_parts} file(s)",
            user_id=user_id,
            username=update.effective_user.username or "",
            extra={"ops": ops_caption},
        )
    )

    try:
        await status_msg.delete()
    except Exception:
        pass
    if sess.get("menu_message_id") and update.effective_chat.type != "private":
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=sess["menu_message_id"],
            )
        except Exception:
            pass

    db.increment_files_processed(user_id)
    _active_tasks.discard(user_id)
    _clear_session(user_id)


def _process_file(user_id: int, sess: dict) -> list[str]:
    """
    Apply all selected operations synchronously (runs via asyncio.to_thread).
    Returns a list of output file paths (multiple if file is split).
    """
    settings = db.get_settings(user_id)
    ops      = set(sess["selected_ops"])    # local copy so we can mutate
    src      = sess["local_path"]
    ext      = Path(sess["file_name"]).suffix or ".mp4"
    out_dir  = config.OUTPUT_DIR
    current  = src
    step     = 0

    def _next(suffix: str = "", use_ext: str | None = None) -> str:
        nonlocal step
        step += 1
        e = use_ext if use_ext is not None else ext
        return os.path.join(out_dir, f"{user_id}_step{step}{suffix}{e}")

    font_path = settings.get("custom_font_path") or None
    if font_path and not os.path.exists(font_path):
        font_path = None

    # 1. Merge
    if "merge" in ops and sess.get("merge_local_path"):
        out = _next("_merged")
        ff.merge_files(current, sess["merge_local_path"], out)
        current = out

    # 2. Remove streams
    if "remove_streams" in ops and sess["streams_to_remove"]:
        out = _next("_streams")
        ff.remove_streams(current, out, list(sess["streams_to_remove"]))
        current = out

    # 3. Remove subtitles
    if "remove_subs" in ops:
        out = _next("_nosubs")
        ff.remove_subtitles(current, out)
        current = out

    # 4. Trim
    if "trim" in ops and sess.get("trim_start"):
        out = _next("_trimmed")
        ff.trim_video(current, out, sess["trim_start"], sess.get("trim_end", ""))
        current = out

    # 5. Replace audio
    if "replace_audio" in ops and sess.get("replace_audio_path"):
        out = _next("_replaced")
        ff.replace_audio(current, sess["replace_audio_path"], out)
        current = out

    # 6. Watermark
    if "watermark" in ops and sess.get("watermark_path"):
        out = _next("_watermark")
        ff.add_watermark(
            current, out,
            sess["watermark_path"],
            position=sess.get("watermark_position", "bottomright"),
        )
        current = out

    # 7. Hardsub (MLRE) – also encodes, so absorbs compress
    if "hardsub" in ops and sess.get("subtitle_file_path"):
        out = _next("_hardsubbed")
        ff.hardsub_video(
            current, out,
            sess["subtitle_file_path"],
            font_path=font_path,
            crf=settings["crf"],
            preset=settings["preset"],
            codec=settings["codec"],
        )
        current = out
        ops.discard("compress")

    # 8. Compress
    if "compress" in ops:
        out = _next("_compressed")
        ff.compress_video(
            input_path=current,
            output_path=out,
            crf=settings["crf"],
            preset=settings["preset"],
            codec=settings["codec"],
            resolution=settings["resolution"],
        )
        current = out

    # 9. Extract audio (returns standalone audio; skips remaining video steps)
    if "extract_audio" in ops:
        fmt = sess.get("extract_audio_fmt", "mp3")
        out = _next("_audio", use_ext=f".{fmt}")
        ff.extract_audio(current, out, fmt=fmt)
        return [out]

    # 10. Rename
    if "rename" in ops and sess.get("rename_to"):
        rename_path = os.path.join(out_dir, f"{user_id}_{sess['rename_to']}")
        shutil.copy2(current, rename_path)
        if current != src:
            try:
                os.remove(current)
            except OSError:
                pass
        current = rename_path

    # ── Split large output if above threshold ─────────────────────────────────
    threshold = config.SPLIT_THRESHOLD_MB * 1024 * 1024
    if os.path.getsize(current) > threshold:
        prefix = f"{user_id}_out"
        parts  = ff.split_video(
            current, out_dir, prefix,
            part_size_mb=config.SPLIT_PART_SIZE_MB,
        )
        if current != src:
            try:
                os.remove(current)
            except OSError:
                pass
        return parts

    return [current]


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db.init_db()

    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error(
            "BOT_TOKEN is not set.  "
            "Export it as an environment variable or edit config.py."
        )
        return

    async def _on_startup(app: Application) -> None:
        if config.LOG_CHANNEL_ID:
            tgl.init_tg_logger(app.bot, config.LOG_CHANNEL_ID)
        await tgl.tg_log("START", "Bot started and polling")

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(_on_startup)
        .build()
    )

    # User commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("settings",  cmd_settings))
    app.add_handler(CommandHandler("setcrf",    cmd_setcrf))
    app.add_handler(CommandHandler("setres",    cmd_setres))
    app.add_handler(CommandHandler("setfont",   cmd_setfont))
    app.add_handler(CommandHandler("clearfont", cmd_clearfont))

    # Admin commands
    app.add_handler(CommandHandler("addpremium",    cmd_addpremium))
    app.add_handler(CommandHandler("removepremium", cmd_removepremium))
    app.add_handler(CommandHandler("listpremium",   cmd_listpremium))
    app.add_handler(CommandHandler("stats",         cmd_stats))
    app.add_handler(CommandHandler("broadcast",     cmd_broadcast))

    # File uploads (video, documents, audio – special types handled inside)
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.ALL | filters.AUDIO,
            handle_file,
        )
    )

    # Plain text (rename, trim input)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot started. Polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
