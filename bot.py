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

# ── State constants ────────────────────────────────────────────────────────────
ST_SELECTING    = "selecting"
ST_WAIT_RENAME  = "wait_rename"
ST_WAIT_MERGE   = "wait_merge"
ST_WAIT_STREAM  = "wait_stream"
ST_WAIT_SUBTITLE = "wait_subtitle"
ST_PROCESSING   = "processing"

# ── File extension sets ────────────────────────────────────────────────────────
SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt"})
FONT_EXTS     = frozenset({".ttf", ".otf"})


# ── Helpers ────────────────────────────────────────────────────────────────────

def _session(user_id: int) -> dict | None:
    return _sessions.get(user_id)


def _new_session(user_id: int, file_id: str, file_name: str) -> dict:
    _sessions[user_id] = {
        "file_id":             file_id,
        "file_name":           file_name,
        "local_path":          "",
        "selected_ops":        set(),
        "rename_to":           None,
        "merge_file_id":       None,
        "merge_file_name":     None,
        "merge_local_path":    "",
        "streams_info":        [],
        "streams_to_remove":   set(),
        "subtitle_file_path":  None,
        "subtitle_file_name":  None,
        "state":               ST_SELECTING,
        "menu_message_id":     None,
    }
    return _sessions[user_id]


def _clear_session(user_id: int) -> None:
    sess = _sessions.pop(user_id, None)
    if sess:
        for path_key in ("local_path", "merge_local_path", "subtitle_file_path"):
            p = sess.get(path_key, "")
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def _is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


async def _download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str, str]:
    """Download the file from the message and return (file_id, local_path, original_name)."""
    msg = update.message
    if msg.video:
        tg_file = msg.video
        ext = ".mp4"
        original_name = getattr(tg_file, "file_name", None) or f"video{ext}"
    elif msg.document:
        tg_file = msg.document
        original_name = tg_file.file_name or "document"
        ext = Path(original_name).suffix or ".bin"
    elif msg.audio:
        tg_file = msg.audio
        ext = ".mp3"
        original_name = getattr(tg_file, "file_name", None) or f"audio{ext}"
    else:
        raise ValueError("Unsupported media type")

    file_id = tg_file.file_id
    dest = os.path.join(config.DOWNLOAD_DIR, f"{update.effective_user.id}_{original_name}")
    tg_dl = await context.bot.get_file(file_id)
    await tg_dl.download_to_drive(dest)
    return file_id, dest, original_name


# ── /start ─────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "👋 Hello!  I can process your video/audio files.\n\n"
        "📎 *Send me any video or document* and I'll show you a menu where you "
        "can select multiple operations:\n"
        "  • 🗜 Compress (with your saved CRF / resolution)\n"
        "  • 📝 Remove Subtitles\n"
        "  • 🎵 Remove Streams\n"
        "  • 🎨 Hardsub – burn subtitles into video (MLRE)\n"
        "  • ✏️ Rename\n"
        "  • 🔗 Merge with another file\n\n"
        "🎨 *Custom font for hardsub:* upload any `.ttf` or `.otf` file to set "
        "your rendering font, or use /setfont.\n\n"
        "Use /settings to configure compression quality.",
        parse_mode="Markdown",
    )


# ── /settings ──────────────────────────────────────────────────────────────────

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
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
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb.settings_menu())


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
    await update.message.reply_text(f"✅ CRF set to `{value}`.", parse_mode="Markdown")


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
    await update.message.reply_text(f"✅ Resolution set to `{resolved}`.", parse_mode="Markdown")


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


# ── File upload handler ────────────────────────────────────────────────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id
    msg = update.message

    # ── Font file (.ttf / .otf) – accepted at any time, saved as default font ──
    if msg.document:
        doc_ext = Path(msg.document.file_name or "").suffix.lower()
        if doc_ext in FONT_EXTS:
            await _handle_font_upload(update, context)
            return

    sess = _session(user_id)

    # ── Subtitle file – only accepted while waiting for one ────────────────────
    if msg.document:
        doc_ext = Path(msg.document.file_name or "").suffix.lower()
        if doc_ext in SUBTITLE_EXTS:
            if sess and sess["state"] == ST_WAIT_SUBTITLE:
                await _handle_subtitle_upload(update, context, sess)
            else:
                await update.message.reply_text(
                    "📄 Subtitle file received.\n\n"
                    "To use it, first send a video then select the "
                    "🎨 *Hardsub* operation.",
                    parse_mode="Markdown",
                )
            return

    # ── Merge file – waiting for second video ──────────────────────────────────
    if sess and sess["state"] == ST_WAIT_MERGE:
        await _receive_merge_file(update, context, sess)
        return

    # ── New video/audio file → start a fresh session ───────────────────────────
    status_msg = await update.message.reply_text("⏳ Downloading your file…")
    try:
        file_id, local_path, original_name = await _download_file(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download file: {exc}")
        return

    await status_msg.delete()

    asyncio.create_task(
        tgl.tg_log(
            "FILE", f"File received: {original_name}",
            user_id=user_id,
            username=update.effective_user.username or "",
            extra={"file": original_name},
        )
    )

    sess = _new_session(user_id, file_id, original_name)
    sess["local_path"] = local_path

    # Probe streams right away (used later for the remove-streams feature)
    sess["streams_info"] = await asyncio.to_thread(ff.probe_streams, local_path)

    menu_msg = await update.message.reply_text(
        f"📁 *{original_name}*\n\nSelect the operations you want to apply, then press ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    sess["menu_message_id"] = menu_msg.message_id


async def _receive_merge_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    """Download the second file for merge when we're in ST_WAIT_MERGE state."""
    status_msg = await update.message.reply_text("⏳ Downloading merge file…")
    try:
        file_id, local_path, original_name = await _download_file(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download file: {exc}")
        return
    await status_msg.delete()

    sess["merge_file_id"]    = file_id
    sess["merge_file_name"]  = original_name
    sess["merge_local_path"] = local_path
    sess["state"]            = ST_SELECTING

    user_id = update.effective_user.id
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ Merge file received: *{original_name}*\n\nNow press ▶️ Process Now to start.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )


async def _handle_font_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Save an uploaded .ttf/.otf file as the user's default rendering font."""
    user_id = update.effective_user.id
    doc = update.message.document
    font_name = doc.file_name or f"font{Path(doc.file_name or '.ttf').suffix}"

    user_fonts_dir = os.path.join(config.FONTS_DIR, str(user_id))
    os.makedirs(user_fonts_dir, exist_ok=True)
    font_path = os.path.join(user_fonts_dir, font_name)

    status_msg = await update.message.reply_text("⏳ Saving font file…")
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(font_path)
    await status_msg.delete()

    db.update_setting(user_id, "custom_font_path", font_path)

    await update.message.reply_text(
        f"🎨 Font *{font_name}* saved as your default rendering font.\n\n"
        "It will be used automatically for *Hardsub* operations.\n"
        "Use /clearfont to remove it.",
        parse_mode="Markdown",
    )
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
    user_id = update.effective_user.id
    doc = update.message.document
    sub_name = doc.file_name or "subtitle.srt"
    sub_path = os.path.join(
        config.DOWNLOAD_DIR, f"{user_id}_sub_{sub_name}"
    )

    status_msg = await update.message.reply_text("⏳ Downloading subtitle file…")
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(sub_path)
    await status_msg.delete()

    sess["subtitle_file_path"] = sub_path
    sess["subtitle_file_name"] = sub_name
    sess["state"]              = ST_SELECTING

    # Show which font will be used
    s = db.get_settings(user_id)
    font_info = (
        f"Font: *{Path(s['custom_font_path']).name}*"
        if s.get("custom_font_path") and os.path.exists(s["custom_font_path"])
        else "Font: system default (upload a .ttf/.otf or use /setfont to set a custom one)"
    )

    await update.message.reply_text(
        f"✅ Subtitle file received: *{sub_name}*\n"
        f"{font_info}\n\n"
        "Press ▶️ Process Now to start.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )


# ── Text message handler (for rename input) ────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        return
    if update.message is None or not update.message.text:
        return

    user_id = update.effective_user.id
    sess = _session(user_id)
    if not sess:
        return

    if sess["state"] == ST_WAIT_RENAME:
        new_name = update.message.text.strip()
        if not new_name:
            await update.message.reply_text("Please send a valid filename.")
            return
        # Preserve original extension if the user didn't include one
        if not Path(new_name).suffix:
            orig_ext = Path(sess["file_name"]).suffix
            new_name = new_name + orig_ext
        sess["rename_to"] = new_name
        sess["state"] = ST_SELECTING
        await update.message.reply_text(
            f"✅ Will rename output to: *{new_name}*\n\nPress ▶️ Process Now to start.",
            parse_mode="Markdown",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )


# ── Callback query handler ─────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    # ── Settings panel callbacks ───────────────────────────────────────────────
    if data == "cfg:crf":
        await query.edit_message_text(
            "Send /setcrf <value> (0–51) or just type the value below.\n"
            "Lower = better quality, larger file.  Recommended: 18–28.",
        )
        return

    if data == "cfg:resolution":
        await query.edit_message_text(
            "Choose a resolution preset or send /setres <value>.",
            reply_markup=kb.resolution_menu(),
        )
        return

    if data == "cfg:preset":
        await query.edit_message_text(
            "Choose an encoding preset.\n"
            "Slower preset = smaller file but longer encode time.",
            reply_markup=kb.preset_menu(),
        )
        return

    if data == "cfg:codec":
        await query.edit_message_text(
            "Choose a video codec.",
            reply_markup=kb.codec_menu(),
        )
        return

    if data in ("cfg:back", "cfg:back_to_settings"):
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
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.settings_menu())
        return

    if data == "cfg:font":
        s = db.get_settings(user_id)
        font_path = s.get("custom_font_path", "")
        if font_path and os.path.exists(font_path):
            font_name = Path(font_path).name
            text = (
                f"🎨 *Current font:* `{font_name}`\n\n"
                "Upload a new `.ttf` or `.otf` file to replace it, "
                "or use /clearfont to remove it."
            )
        else:
            text = (
                "🎨 *No custom font set.*\n\n"
                "Upload any `.ttf` or `.otf` file and I'll use it for "
                "*Hardsub* subtitle rendering."
            )
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=kb.settings_menu(),
        )
        return

    if data.startswith("set:"):
        _, key, value = data.split(":", 2)
        # Resolve shortcut for resolution
        if key == "resolution":
            value = config.RESOLUTION_MAP.get(value, value)
        db.update_setting(user_id, key, value)
        s = db.get_settings(user_id)
        text = (
            f"✅ *{key.capitalize()}* set to `{value}`\n\n"
            "⚙️ *Current Settings*\n\n"
            f"  • CRF: `{s['crf']}`\n"
            f"  • Resolution: `{s['resolution']}`\n"
            f"  • Preset: `{s['preset']}`\n"
            f"  • Codec: `{s['codec']}`"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb.settings_menu())
        return

    # ── Operation menu callbacks ───────────────────────────────────────────────
    sess = _session(user_id)
    if not sess:
        await query.edit_message_text("⚠️ Session expired. Please send your file again.")
        return

    if sess["state"] == ST_PROCESSING:
        await query.answer("⏳ Already processing, please wait…", show_alert=True)
        return

    # Toggle an operation
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

    # Cancel
    if data == "cancel":
        _clear_session(user_id)
        await query.edit_message_text("❌ Operation cancelled. Send a new file when ready.")
        return

    # Process
    if data == "process":
        await _start_processing(update, context, query, sess)
        return

    # Stream selection toggles
    if data.startswith("stream:"):
        suffix = data[7:]
        if suffix == "confirm":
            sess["state"] = ST_SELECTING
            await query.edit_message_text(
                f"✅ Will remove {len(sess['streams_to_remove'])} stream(s).\n\n"
                "Press ▶️ Process Now to continue.",
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

async def _start_processing(update, context, query, sess: dict) -> None:
    user_id = update.effective_user.id

    if not sess["selected_ops"]:
        await query.answer("⚠️ Please select at least one operation.", show_alert=True)
        return

    # ── Collect missing inputs before processing ───────────────────────────────

    # If "remove_streams" selected but no streams chosen yet, show stream picker
    if "remove_streams" in sess["selected_ops"] and not sess["streams_to_remove"]:
        if not sess["streams_info"]:
            await query.answer("⚠️ Could not read streams from file.", show_alert=True)
            return
        sess["state"] = ST_WAIT_STREAM
        await query.edit_message_text(
            "🎵 *Select streams to remove* (tap to toggle, selected = will be removed):",
            parse_mode="Markdown",
            reply_markup=kb.stream_selection_menu(sess["streams_info"], sess["streams_to_remove"]),
        )
        return

    # If "rename" selected but no new name yet, ask for it
    if "rename" in sess["selected_ops"] and not sess["rename_to"]:
        sess["state"] = ST_WAIT_RENAME
        await query.edit_message_text(
            "✏️ Please send the *new filename* (with or without extension):",
            parse_mode="Markdown",
        )
        return

    # If "merge" selected but no second file yet, ask for it
    if "merge" in sess["selected_ops"] and not sess["merge_file_id"]:
        sess["state"] = ST_WAIT_MERGE
        await query.edit_message_text(
            "🔗 Please send the *second file* to merge with:",
            parse_mode="Markdown",
        )
        return

    # ── All inputs collected – start processing ────────────────────────────────
    sess["state"] = ST_PROCESSING
    status_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⚙️ Processing… please wait.",
    )

    try:
        output_path = await asyncio.to_thread(
            _process_file, user_id, sess
        )
    except Exception as exc:
        logger.exception("Processing failed for user %s", user_id)
        await status_msg.edit_text(f"❌ Processing failed:\n<code>{exc}</code>", parse_mode="HTML")
        _clear_session(user_id)
        return

    # ── Upload result ──────────────────────────────────────────────────────────
    await status_msg.edit_text("📤 Uploading result…")
    final_name = sess.get("rename_to") or Path(output_path).name
    try:
        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=final_name,
                caption=f"✅ Done!  Operations applied: {', '.join(sorted(sess['selected_ops']))}",
            )
    except Exception as exc:
        await status_msg.edit_text(f"❌ Upload failed: {exc}")
    else:
        await status_msg.delete()
        # Clean up the operation-menu message too
        if sess.get("menu_message_id"):
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=sess["menu_message_id"],
                )
            except Exception:
                pass
    finally:
        # Clean up local files
        try:
            os.remove(output_path)
        except OSError:
            pass
        _clear_session(user_id)


def _process_file(user_id: int, sess: dict) -> str:
    """
    Run all selected operations synchronously (called via asyncio.to_thread).
    Returns the path to the final output file.
    """
    settings  = db.get_settings(user_id)
    ops       = sess["selected_ops"]
    src       = sess["local_path"]
    base_name = Path(sess["file_name"]).stem
    ext       = Path(sess["file_name"]).suffix or ".mp4"
    out_dir   = config.OUTPUT_DIR

    # We'll chain operations, each writing to a new temp file
    current = src
    step = 0

    def _next_path(suffix: str = "") -> str:
        nonlocal step
        step += 1
        return os.path.join(out_dir, f"{user_id}_step{step}{suffix}{ext}")

    # 1. Merge (first – gives us the combined source)
    if "merge" in ops and sess.get("merge_local_path"):
        out = _next_path("_merged")
        ff.merge_files(current, sess["merge_local_path"], out)
        current = out

    # 2. Remove streams
    if "remove_streams" in ops and sess["streams_to_remove"]:
        out = _next_path("_streams")
        ff.remove_streams(current, out, list(sess["streams_to_remove"]))
        current = out

    # 3. Remove subtitles
    if "remove_subs" in ops:
        out = _next_path("_nosubs")
        ff.remove_subtitles(current, out)
        current = out

    # 4. Compress (last video operation, applied to final content)
    if "compress" in ops:
        out = _next_path("_compressed")
        ff.compress_video(
            input_path=current,
            output_path=out,
            crf=settings["crf"],
            preset=settings["preset"],
            codec=settings["codec"],
            resolution=settings["resolution"],
        )
        current = out

    # 5. Rename – just copy/move to the desired name
    if "rename" in ops and sess.get("rename_to"):
        rename_path = os.path.join(out_dir, f"{user_id}_{sess['rename_to']}")
        shutil.copy2(current, rename_path)
        # If current is a temp file (not the original), remove it
        if current != src:
            try:
                os.remove(current)
            except OSError:
                pass
        current = rename_path

    return current


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db.init_db()

    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error(
            "BOT_TOKEN is not set.  "
            "Export it as an environment variable or edit config.py."
        )
        return

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("setcrf",   cmd_setcrf))
    app.add_handler(CommandHandler("setres",   cmd_setres))

    # File uploads (video + any document)
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.ALL | filters.AUDIO,
            handle_file,
        )
    )

    # Plain text (used for rename input)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot started. Polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
