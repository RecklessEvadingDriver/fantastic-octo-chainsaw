"""
Text message handler — processes plain-text input for rename and trim operations.
"""
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import keyboards as kb
from sessions import ST_WAIT_RENAME, ST_WAIT_TRIM, ST_SELECTING
from utils.helpers import is_allowed, get_session, schedule_delete
from utils.force_join import require_join

logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    if update.message is None or not update.message.text:
        return
    if await require_join(update, context):
        return

    user_id = update.effective_user.id
    sess    = get_session(user_id)
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
        schedule_delete(context, update, r)
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
        schedule_delete(context, update, r)
        return
