"""
Core processing logic:
  start_processing — orchestrates the pipeline with live progress updates
  process_file     — synchronous FFmpeg pipeline (runs via asyncio.to_thread)
"""
import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from pyrogram import Client
from pyrogram.errors import UserIsBlocked, PeerIdInvalid
from pyrogram.types import CallbackQuery

import config
import database as db
import ffmpeg_utils as ff
import tg_logger as tgl
from sessions import _active_tasks, ST_PROCESSING, ST_WAIT_STREAM, ST_WAIT_SUBTITLE
from sessions import ST_WAIT_RENAME, ST_WAIT_MERGE, ST_WAIT_WATERMARK
from sessions import ST_WAIT_REPLACE_AUD, ST_WAIT_TRIM, ST_WAIT_AUDIO_FMT
from utils.helpers import clear_session, schedule_delete, tg_log, fmt_size
from utils.progress import OP_DISPLAY, count_steps, build_progress_text, progress_updater
import keyboards as kb

logger = logging.getLogger(__name__)


async def start_processing(
    client: Client,
    query: CallbackQuery,
    sess: dict,
) -> None:
    user_id = query.from_user.id

    if not sess["selected_ops"]:
        await query.answer("⚠️ Please select at least one operation.", show_alert=True)
        return

    ops = sess["selected_ops"]

    # ── Gather extra inputs needed before running ──────────────────────────────
    if "remove_streams" in ops and not sess["streams_to_remove"]:
        if not sess["streams_info"]:
            await query.answer("⚠️ Could not read streams.", show_alert=True)
            return
        sess["state"] = ST_WAIT_STREAM
        await query.edit_message_text(
            "🎵 **Select streams to remove** (tap to toggle):",
            reply_markup=kb.stream_selection_menu(
                sess["streams_info"], sess["streams_to_remove"]
            ),
        )
        return

    if "hardsub" in ops and not sess.get("subtitle_file_path"):
        sess["state"] = ST_WAIT_SUBTITLE
        await query.edit_message_text(
            "🎨 **Hardsub selected.**\n\nSend your subtitle file (`.srt` / `.ass` / `.ssa`):"
        )
        return

    if "rename" in ops and not sess.get("rename_to"):
        sess["state"] = ST_WAIT_RENAME
        await query.edit_message_text(
            "✏️ Send the **new filename** (with or without extension):"
        )
        return

    if "merge" in ops and not sess.get("merge_file_id"):
        sess["state"] = ST_WAIT_MERGE
        await query.edit_message_text(
            "🔗 Send the **second video** to merge with:"
        )
        return

    if "watermark" in ops and not sess.get("watermark_path"):
        sess["state"] = ST_WAIT_WATERMARK
        await query.edit_message_text(
            "🖼 Send the **watermark image** (PNG or JPG):"
        )
        return

    if "replace_audio" in ops and not sess.get("replace_audio_path"):
        sess["state"] = ST_WAIT_REPLACE_AUD
        await query.edit_message_text(
            "🔄 Send the **replacement audio file**:"
        )
        return

    if "trim" in ops and not sess.get("trim_start"):
        sess["state"] = ST_WAIT_TRIM
        await query.edit_message_text(
            "✂️ Send the **trim range**: `start [end]`\ne.g. `00:01:30 00:05:00`"
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

    # ── All inputs ready – kick off ────────────────────────────────────────────
    sess["state"] = ST_PROCESSING
    _active_tasks.add(user_id)

    progress = {
        "step":  0,
        "total": count_steps(ops, sess),
        "op":    "Starting…",
        "start": time.time(),
    }

    chat_id    = query.message.chat.id
    status_msg = await client.send_message(chat_id, build_progress_text(progress))
    schedule_delete(client, status_msg)

    asyncio.create_task(
        tgl.tg_log(
            "PROCESS", f"Processing started: {', '.join(sorted(ops))}",
            user_id=user_id,
            username=query.from_user.username or "",
        )
    )

    stop_event   = asyncio.Event()
    updater_task = asyncio.create_task(
        progress_updater(status_msg, progress, stop_event)
    )

    try:
        output_files = await asyncio.to_thread(
            process_file, user_id, sess, progress
        )
    except Exception as exc:
        stop_event.set()
        await updater_task
        logger.exception("Processing failed for user %s", user_id)
        err_msg = await client.send_message(
            chat_id,
            f"❌ **Processing failed:**\n`{exc}`",
        )
        schedule_delete(client, err_msg)
        asyncio.create_task(
            tgl.tg_log(
                "ERROR", f"Processing failed: {exc}",
                user_id=user_id,
                username=query.from_user.username or "",
            )
        )
        _active_tasks.discard(user_id)
        clear_session(user_id)
        return

    stop_event.set()
    await updater_task

    elapsed_secs = int(time.time() - progress["start"])
    elapsed_str  = f"{elapsed_secs // 60:02d}:{elapsed_secs % 60:02d}"

    # ── Deliver results to user's PM via MTProto ───────────────────────────────
    try:
        await status_msg.edit_text("📤 Uploading result to your PM via MTProto…")
    except Exception:
        pass

    final_base  = sess.get("rename_to") or Path(sess["file_name"]).stem
    ops_caption = ", ".join(sorted(ops))
    total_parts = len(output_files)
    delivered   = 0

    for i, out_path in enumerate(output_files):
        part_label = f"**Part {i + 1}/{total_parts}**\n" if total_parts > 1 else ""
        file_size  = fmt_size(os.path.getsize(out_path))
        caption    = (
            f"✅ {part_label}"
            f"📋 **Operations:** {ops_caption}\n"
            f"📦 **Size:** `{file_size}`  •  ⏱ **Time:** `{elapsed_str}`\n\n"
            f"_— {config.BOT_BRAND}_"
        )
        fname = (
            f"{final_base}.part{i + 1:03d}{Path(out_path).suffix}"
            if total_parts > 1
            else (sess.get("rename_to") or Path(out_path).name)
        )
        try:
            await client.send_document(
                chat_id=user_id,   # always PM
                document=out_path,
                file_name=fname,
                caption=caption,
            )
            delivered += 1
        except (UserIsBlocked, PeerIdInvalid):
            await client.send_message(
                chat_id,
                "⚠️ I can't send files to your PM.\n"
                "Please send /start to this bot in a **private message** first, "
                "then try again.",
            )
            break
        except Exception as exc:
            await client.send_message(
                chat_id,
                f"❌ Upload failed (part {i + 1}): `{exc}`",
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
            username=query.from_user.username or "",
            extra={"ops": ops_caption},
        )
    )

    try:
        await status_msg.delete()
    except Exception:
        pass

    if sess.get("menu_message_id"):
        try:
            await client.delete_messages(chat_id, sess["menu_message_id"])
        except Exception:
            pass

    db.increment_files_processed(user_id)
    _active_tasks.discard(user_id)
    clear_session(user_id)


def process_file(user_id: int, sess: dict,
                 progress: dict | None = None) -> list[str]:
    """
    Apply all selected operations synchronously (runs via asyncio.to_thread).
    Updates *progress* dict in-place so the async progress_updater can read it.
    Returns a list of output file paths (multiple if the file is split).
    """
    settings = db.get_settings(user_id)
    ops      = set(sess["selected_ops"])
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

    def _tick(op_key: str) -> None:
        if progress is not None:
            progress["op"]   = OP_DISPLAY.get(op_key, op_key)
            progress["step"] = progress.get("step", 0) + 1

    font_path = settings.get("custom_font_path") or None
    if font_path and not os.path.exists(font_path):
        font_path = None

    # 1. Merge
    if "merge" in ops and sess.get("merge_local_path"):
        _tick("merge")
        out = _next("_merged")
        ff.merge_files(current, sess["merge_local_path"], out)
        current = out

    # 2. Remove streams
    if "remove_streams" in ops and sess["streams_to_remove"]:
        _tick("remove_streams")
        out = _next("_streams")
        ff.remove_streams(current, out, list(sess["streams_to_remove"]))
        current = out

    # 3. Remove subtitles
    if "remove_subs" in ops:
        _tick("remove_subs")
        out = _next("_nosubs")
        ff.remove_subtitles(current, out)
        current = out

    # 4. Trim
    if "trim" in ops and sess.get("trim_start"):
        _tick("trim")
        out = _next("_trimmed")
        ff.trim_video(current, out, sess["trim_start"], sess.get("trim_end", ""))
        current = out

    # 5. Replace audio
    if "replace_audio" in ops and sess.get("replace_audio_path"):
        _tick("replace_audio")
        out = _next("_replaced")
        ff.replace_audio(current, sess["replace_audio_path"], out)
        current = out

    # 6. Watermark
    if "watermark" in ops and sess.get("watermark_path"):
        _tick("watermark")
        out = _next("_watermark")
        ff.add_watermark(
            current, out,
            sess["watermark_path"],
            position=sess.get("watermark_position", "bottomright"),
        )
        current = out

    # 7. Hardsub — re-encodes and absorbs compress
    if "hardsub" in ops and sess.get("subtitle_file_path"):
        _tick("hardsub")
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
        _tick("compress")
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

    # 9. Extract audio (standalone)
    if "extract_audio" in ops:
        _tick("extract_audio")
        fmt = sess.get("extract_audio_fmt", "mp3")
        out = _next("_audio", use_ext=f".{fmt}")
        ff.extract_audio(current, out, fmt=fmt)
        return [out]

    # 10. Rename
    if "rename" in ops and sess.get("rename_to"):
        _tick("rename")
        rename_path = os.path.join(out_dir, f"{user_id}_{sess['rename_to']}")
        shutil.copy2(current, rename_path)
        if current != src:
            try:
                os.remove(current)
            except OSError:
                pass
        current = rename_path

    # ── Split large output if above threshold ──────────────────────────────────
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
