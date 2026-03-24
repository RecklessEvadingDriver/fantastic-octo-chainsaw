"""
File upload handler and related helpers:
  handle_file, _receive_merge_file,
  _handle_font_upload, _handle_subtitle_upload,
  _handle_watermark_upload, _handle_replace_audio_upload
"""
import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
import ffmpeg_utils as ff
import keyboards as kb
import tg_logger as tgl
from sessions import (
    _active_tasks,
    ST_WAIT_SUBTITLE, ST_WAIT_WATERMARK, ST_WAIT_REPLACE_AUD, ST_WAIT_MERGE,
    SUBTITLE_EXTS, FONT_EXTS, IMAGE_EXTS, AUDIO_EXTS,
)
from utils.helpers import (
    is_allowed, get_session, new_session, schedule_delete,
    is_video_document, fmt_size, download_tg_file, download_video,
)
from utils.force_join import require_join

logger = logging.getLogger(__name__)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    if await require_join(update, context):
        return

    user_id = update.effective_user.id
    msg     = update.message
    db.record_user(user_id, update.effective_user.username or "",
                   update.effective_user.first_name or "")

    # ── Detect special file types by extension ─────────────────────────────────
    if msg.document:
        doc_ext = Path(msg.document.file_name or "").suffix.lower()
        sess    = get_session(user_id)

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
                schedule_delete(context, update, r)
            return

        if doc_ext in IMAGE_EXTS:
            if sess and sess["state"] == ST_WAIT_WATERMARK:
                await _handle_watermark_upload(update, context, sess)
            else:
                r = await update.message.reply_text(
                    "🖼 Image received. Select 🖼 Watermark and press ▶️ to use it."
                )
                schedule_delete(context, update, r)
            return

        if doc_ext in AUDIO_EXTS:
            if sess and sess["state"] == ST_WAIT_REPLACE_AUD:
                await _handle_replace_audio_upload(update, context, sess)
            else:
                r = await update.message.reply_text(
                    "🎵 Audio file received. Select 🔄 Replace Audio to use it."
                )
                schedule_delete(context, update, r)
            return

    sess = get_session(user_id)

    # ── Route waiting states ───────────────────────────────────────────────────
    if sess and sess["state"] == ST_WAIT_MERGE:
        if msg.video or (msg.document and is_video_document(msg.document)):
            await _receive_merge_file(update, context, sess)
            return

    if msg.audio and sess and sess["state"] == ST_WAIT_REPLACE_AUD:
        await _handle_replace_audio_upload(update, context, sess, use_audio=True)
        return

    # ── Videos only for new sessions ──────────────────────────────────────────
    is_video = msg.video or (msg.document and is_video_document(msg.document))
    if not is_video:
        r = await update.message.reply_text(
            "❌ Videos only.\nSend .mp4, .mkv, .avi, .mov, or any other video file."
        )
        schedule_delete(context, update, r)
        return

    # ── One-task-per-user guard ────────────────────────────────────────────────
    if user_id in _active_tasks:
        r = await update.message.reply_text(
            "⏳ You already have a task running. Please wait for it to finish."
        )
        schedule_delete(context, update, r)
        return

    # ── Download and start session ─────────────────────────────────────────────
    status_msg = await update.message.reply_text("⏳ Downloading your video…")
    try:
        file_id, local_path, original_name = await download_video(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        schedule_delete(context, update, status_msg)
        return

    await status_msg.delete()

    asyncio.create_task(
        tgl.tg_log(
            "FILE", f"Video received: {original_name}",
            user_id=user_id,
            username=update.effective_user.username or "",
            extra={"size": fmt_size(os.path.getsize(local_path))},
        )
    )

    sess = new_session(user_id, file_id, original_name)
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
    schedule_delete(context, update, menu_msg)


async def _receive_merge_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    status_msg = await update.message.reply_text("⏳ Downloading merge file…")
    try:
        file_id, local_path, original_name = await download_video(update, context)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        schedule_delete(context, update, status_msg)
        return
    await status_msg.delete()

    from sessions import ST_SELECTING
    sess["merge_file_id"]    = file_id
    sess["merge_file_name"]  = original_name
    sess["merge_local_path"] = local_path
    sess["state"]            = ST_SELECTING

    r = await update.message.reply_text(
        f"✅ Merge file received: *{original_name}*\n\nPress ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    schedule_delete(context, update, r)


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
    await download_tg_file(context.bot, doc.file_id, font_path)
    await status_msg.delete()

    db.update_setting(user_id, "custom_font_path", font_path)

    r = await update.message.reply_text(
        f"🎨 Font *{font_name}* saved as your default rendering font.\n\n"
        "It will be used automatically for *Hardsub* operations.\n"
        "Use /clearfont to remove it.",
        parse_mode="Markdown",
    )
    schedule_delete(context, update, r)
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
    from sessions import ST_SELECTING
    user_id  = update.effective_user.id
    doc      = update.message.document
    sub_name = doc.file_name or "subtitle.srt"
    sub_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_sub_{sub_name}")

    status_msg = await update.message.reply_text("⏳ Downloading subtitle file…")
    await download_tg_file(context.bot, doc.file_id, sub_path)
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
    schedule_delete(context, update, r)


async def _handle_watermark_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
) -> None:
    """Download a watermark image while in ST_WAIT_WATERMARK state."""
    from sessions import ST_WAIT_WMARK_POS
    user_id = update.effective_user.id
    doc     = update.message.document
    wm_name = doc.file_name or "watermark.png"
    wm_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_wm_{wm_name}")

    status_msg = await update.message.reply_text("⏳ Downloading watermark image…")
    await download_tg_file(context.bot, doc.file_id, wm_path)
    await status_msg.delete()

    sess["watermark_path"] = wm_path
    sess["watermark_name"] = wm_name
    sess["state"]          = ST_WAIT_WMARK_POS

    r = await update.message.reply_text(
        f"✅ Watermark image received: *{wm_name}*\n\nChoose the position:",
        parse_mode="Markdown",
        reply_markup=kb.watermark_position_menu(),
    )
    schedule_delete(context, update, r)


async def _handle_replace_audio_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sess: dict,
    use_audio: bool = False,
) -> None:
    """Download a replacement audio file while in ST_WAIT_REPLACE_AUD state."""
    from sessions import ST_SELECTING
    user_id = update.effective_user.id
    if use_audio:
        tg_obj  = update.message.audio
        au_name = getattr(tg_obj, "file_name", None) or "audio.mp3"
    else:
        tg_obj  = update.message.document
        au_name = tg_obj.file_name or "audio.mp3"
    au_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_aud_{au_name}")

    status_msg = await update.message.reply_text("⏳ Downloading audio file…")
    await download_tg_file(context.bot, tg_obj.file_id, au_path)
    await status_msg.delete()

    sess["replace_audio_path"] = au_path
    sess["state"]              = ST_SELECTING

    r = await update.message.reply_text(
        f"✅ Audio file received: *{au_name}*\n\nPress ▶️ Process Now.",
        parse_mode="Markdown",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    schedule_delete(context, update, r)
