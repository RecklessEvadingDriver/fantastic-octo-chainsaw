"""
Callback query handler — processes all inline keyboard button presses.
"""
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
import keyboards as kb
from sessions import ST_PROCESSING, ST_SELECTING, ST_WAIT_STREAM
from utils.helpers import is_allowed, get_session, clear_session, schedule_deletefrom utils.force_join import require_join

logger = logging.getLogger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        return

    if await require_join(update, context):
        return

    user_id = update.effective_user.id
    data    = query.data

    # ── Settings panel ─────────────────────────────────────────────────────────
    if data == "cfg:crf":
        await query.edit_message_text(
            "Send /setcrf <value> (0–51).\nLower = better quality. Recommended: 18–28."
        )
        return

    if data == "cfg:resolution":
        await query.edit_message_text(
            "Choose a resolution preset:", reply_markup=kb.resolution_menu()
        )
        return

    if data == "cfg:preset":
        await query.edit_message_text(
            "Choose an encoding preset.\nSlower = smaller file, longer encode time.",
            reply_markup=kb.preset_menu(),
        )
        return

    if data == "cfg:codec":
        await query.edit_message_text(
            "Choose a video codec:", reply_markup=kb.codec_menu()
        )
        return

    if data in ("cfg:back", "cfg:back_to_settings"):
        s  = db.get_settings(user_id)
        fn = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
        text = (
            "⚙️ *Current Settings*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"  🔢 CRF:        `{s['crf']}`\n"
            f"  📐 Resolution: `{s['resolution']}`\n"
            f"  ⚡ Preset:     `{s['preset']}`\n"
            f"  🎬 Codec:      `{s['codec']}`\n"
            f"  🎨 Font:       `{fn}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Saved and applied for every Compress & Hardsub operation._"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.settings_menu()
        )
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
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.settings_menu()
        )
        return

    if data.startswith("set:"):
        _, key, value = data.split(":", 2)
        if key == "resolution":
            value = config.RESOLUTION_MAP.get(value, value)
        db.update_setting(user_id, key, value)
        s  = db.get_settings(user_id)
        fn = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
        text = (
            f"✅ *{key.capitalize()}* updated to `{value}`\n\n"
            "⚙️ *Current Settings*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"  🔢 CRF:        `{s['crf']}`\n"
            f"  📐 Resolution: `{s['resolution']}`\n"
            f"  ⚡ Preset:     `{s['preset']}`\n"
            f"  🎬 Codec:      `{s['codec']}`\n"
            f"  🎨 Font:       `{fn}`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Saved and applied for every Compress & Hardsub operation._"
        )
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=kb.settings_menu()
        )
        return

    # ── Watermark position ─────────────────────────────────────────────────────
    if data.startswith("wmpos:"):
        sess = get_session(user_id)
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
        sess = get_session(user_id)
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
    sess = get_session(user_id)
    if not sess:
        await query.edit_message_text(
            "⚠️ Session expired or not found. Please send your video again to start a new session."
        )
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
        clear_session(user_id)
        await query.edit_message_text("❌ Operation cancelled. Send a new video whenever you're ready.")
        return

    if data == "process":
        from handlers.processing import start_processing
        await start_processing(update, context, query, sess)
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
