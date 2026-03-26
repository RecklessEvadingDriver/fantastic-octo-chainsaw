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

from pyrogram import Client
from pyrogram.types import Message

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
    is_video_document, fmt_size, fmt_duration, download_tg_file, download_video,
)
from utils.force_join import require_join

logger = logging.getLogger(__name__)


async def handle_file(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    if await require_join(client, message=message):
        return

    user_id = user.id
    db.record_user(user_id, user.username or "", user.first_name or "")

    # ── Detect special file types by extension ─────────────────────────────────
    if message.document:
        doc_ext = Path(message.document.file_name or "").suffix.lower()
        sess    = get_session(user_id)

        if doc_ext in FONT_EXTS:
            await _handle_font_upload(client, message)
            return

        if doc_ext in SUBTITLE_EXTS:
            if sess and sess["state"] == ST_WAIT_SUBTITLE:
                await _handle_subtitle_upload(client, message, sess)
            else:
                r = await message.reply_text(
                    "📄 Subtitle file received.\n"
                    "To use it, first send a video then select 🎨 **Hardsub**."
                )
                schedule_delete(client, r)
            return

        if doc_ext in IMAGE_EXTS:
            if sess and sess["state"] == ST_WAIT_WATERMARK:
                await _handle_watermark_upload(client, message, sess)
            else:
                r = await message.reply_text(
                    "🖼 Image received. Select 🖼 **Watermark** and press ▶️ to use it."
                )
                schedule_delete(client, r)
            return

        if doc_ext in AUDIO_EXTS:
            if sess and sess["state"] == ST_WAIT_REPLACE_AUD:
                await _handle_replace_audio_upload(client, message, sess)
            else:
                r = await message.reply_text(
                    "🎵 Audio file received. Select 🔄 **Replace Audio** to use it."
                )
                schedule_delete(client, r)
            return

    sess = get_session(user_id)

    # ── Route waiting states ───────────────────────────────────────────────────
    if sess and sess["state"] == ST_WAIT_MERGE:
        if message.video or (message.document and is_video_document(message.document)):
            await _receive_merge_file(client, message, sess)
            return

    if message.audio and sess and sess["state"] == ST_WAIT_REPLACE_AUD:
        await _handle_replace_audio_upload(client, message, sess, use_audio=True)
        return

    # ── Videos only for new sessions ──────────────────────────────────────────
    is_video = message.video or (message.document and is_video_document(message.document))
    if not is_video:
        r = await message.reply_text(
            "❌ Videos only.\nSend `.mp4`, `.mkv`, `.avi`, `.mov`, or any other video file."
        )
        schedule_delete(client, r)
        return

    # ── One-task-per-user guard ────────────────────────────────────────────────
    if user_id in _active_tasks:
        r = await message.reply_text(
            "⏳ You already have a task running. Please wait for it to finish."
        )
        schedule_delete(client, r)
        return

    # ── Download and start session ─────────────────────────────────────────────
    status_msg = await message.reply_text("⏳ Downloading your video via MTProto…")
    try:
        file_id, local_path, original_name = await download_video(client, message)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        schedule_delete(client, status_msg)
        return

    await status_msg.delete()

    try:
        file_size = fmt_size(os.path.getsize(local_path))

        # Gather duration and stream count for the info card
        duration_str = ""
        stream_count = 0
        try:
            fmt_info     = await asyncio.to_thread(ff.probe_format, local_path)
            dur_secs     = float(fmt_info.get("duration") or 0)
            duration_str = fmt_duration(dur_secs) if dur_secs else ""
            streams      = await asyncio.to_thread(ff.probe_streams, local_path)
            stream_count = len(streams)
        except Exception:
            streams = []

        asyncio.create_task(
            tgl.tg_log(
                "FILE", f"Video received: {original_name}",
                user_id=user_id,
                username=user.username or "",
                extra={"size": file_size},
            )
        )

        sess = new_session(user_id, file_id, original_name)
        sess["local_path"]   = local_path
        sess["streams_info"] = streams

        # Build info line
        info_parts = [f"`{file_size}`"]
        if duration_str:
            info_parts.append(f"⏱ `{duration_str}`")
        if stream_count:
            info_parts.append(f"🎞 `{stream_count} streams`")
        info_line = "  •  ".join(info_parts)

        menu_msg = await message.reply_text(
            f"📁 **{original_name}**\n"
            f"{info_line}\n\n"
            "Select the operations you want to apply, then press ▶️ **Process Now**.\n"
            "_Results will be delivered to your PM._",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        sess["menu_message_id"] = menu_msg.id
        schedule_delete(client, menu_msg)
    except Exception as exc:
        try:
            os.remove(local_path)
        except OSError:
            pass
        raise exc


async def _receive_merge_file(
    client: Client,
    message: Message,
    sess: dict,
) -> None:
    status_msg = await message.reply_text("⏳ Downloading merge file via MTProto…")
    try:
        file_id, local_path, original_name = await download_video(client, message)
    except Exception as exc:
        await status_msg.edit_text(f"❌ Could not download: {exc}")
        schedule_delete(client, status_msg)
        return
    await status_msg.delete()

    try:
        from sessions import ST_SELECTING
        sess["merge_file_id"]    = file_id
        sess["merge_file_name"]  = original_name
        sess["merge_local_path"] = local_path
        sess["state"]            = ST_SELECTING

        r = await message.reply_text(
            f"✅ Merge file received: **{original_name}**\n\nPress ▶️ **Process Now**.",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        schedule_delete(client, r)
    except Exception as exc:
        try:
            os.remove(local_path)
        except OSError:
            pass
        raise exc


async def _handle_font_upload(client: Client, message: Message) -> None:
    """Save an uploaded .ttf/.otf file as the user's default rendering font."""
    user_id   = message.from_user.id
    doc       = message.document
    font_name = doc.file_name or "custom_font.ttf"

    fonts_dir = os.path.join(config.FONTS_DIR, str(user_id))
    os.makedirs(fonts_dir, exist_ok=True)
    font_path = os.path.join(fonts_dir, font_name)

    status_msg = await message.reply_text("⏳ Saving font file…")
    await download_tg_file(client, message, font_path)
    await status_msg.delete()

    db.update_setting(user_id, "custom_font_path", font_path)

    r = await message.reply_text(
        f"🎨 Font **{font_name}** saved as your default rendering font.\n\n"
        "It will be used automatically for **Hardsub** operations.\n"
        "Use /clearfont to remove it."
    )
    schedule_delete(client, r)
    asyncio.create_task(
        tgl.tg_log(
            "INFO", f"Custom font set: {font_name}",
            user_id=user_id,
            username=message.from_user.username or "",
        )
    )


async def _handle_subtitle_upload(
    client: Client,
    message: Message,
    sess: dict,
) -> None:
    """Download a subtitle file while in ST_WAIT_SUBTITLE state."""
    from sessions import ST_SELECTING
    user_id  = message.from_user.id
    doc      = message.document
    sub_name = doc.file_name or "subtitle.srt"
    sub_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_sub_{sub_name}")

    status_msg = await message.reply_text("⏳ Downloading subtitle file…")
    await download_tg_file(client, message, sub_path)
    await status_msg.delete()

    sess["subtitle_file_path"] = sub_path
    sess["subtitle_file_name"] = sub_name
    sess["state"]              = ST_SELECTING

    s = db.get_settings(user_id)
    font_info = (
        f"Font: **{Path(s['custom_font_path']).name}**"
        if s.get("custom_font_path") and os.path.exists(s["custom_font_path"])
        else "Font: system default (upload .ttf/.otf or /setfont)"
    )
    r = await message.reply_text(
        f"✅ Subtitle received: **{sub_name}**\n{font_info}\n\nPress ▶️ **Process Now**.",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    schedule_delete(client, r)


async def _handle_watermark_upload(
    client: Client,
    message: Message,
    sess: dict,
) -> None:
    """Download a watermark image while in ST_WAIT_WATERMARK state."""
    from sessions import ST_WAIT_WMARK_POS
    user_id = message.from_user.id
    doc     = message.document
    wm_name = doc.file_name or "watermark.png"
    wm_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_wm_{wm_name}")

    status_msg = await message.reply_text("⏳ Downloading watermark image…")
    await download_tg_file(client, message, wm_path)
    await status_msg.delete()

    sess["watermark_path"] = wm_path
    sess["watermark_name"] = wm_name
    sess["state"]          = ST_WAIT_WMARK_POS

    r = await message.reply_text(
        f"✅ Watermark received: **{wm_name}**\n\nChoose the overlay position:",
        reply_markup=kb.watermark_position_menu(),
    )
    schedule_delete(client, r)


async def _handle_replace_audio_upload(
    client: Client,
    message: Message,
    sess: dict,
    use_audio: bool = False,
) -> None:
    """Download a replacement audio file while in ST_WAIT_REPLACE_AUD state."""
    from sessions import ST_SELECTING
    user_id = message.from_user.id
    if use_audio:
        tg_obj  = message.audio
        au_name = getattr(tg_obj, "file_name", None) or "audio.mp3"
    else:
        tg_obj  = message.document
        au_name = tg_obj.file_name or "audio.mp3"
    au_path = os.path.join(config.DOWNLOAD_DIR, f"{user_id}_aud_{au_name}")

    status_msg = await message.reply_text("⏳ Downloading audio file…")
    await download_tg_file(client, message, au_path)
    await status_msg.delete()

    sess["replace_audio_path"] = au_path
    sess["state"]              = ST_SELECTING

    r = await message.reply_text(
        f"✅ Audio file received: **{au_name}**\n\nPress ▶️ **Process Now**.",
        reply_markup=kb.operation_menu(sess["selected_ops"]),
    )
    schedule_delete(client, r)
