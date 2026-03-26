"""
Text message handler — processes plain-text input for rename and trim operations.
"""
import logging
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

import keyboards as kb
from sessions import ST_WAIT_RENAME, ST_WAIT_TRIM, ST_SELECTING
from utils.helpers import is_allowed, get_session, schedule_delete
from utils.force_join import require_join

logger = logging.getLogger(__name__)


async def handle_text(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    if not message.text:
        return
    if await require_join(client, message=message):
        return

    user_id = user.id
    sess    = get_session(user_id)
    if not sess:
        return

    text = message.text.strip()

    if sess["state"] == ST_WAIT_RENAME:
        if not text:
            await message.reply_text("Please send a valid filename.")
            return
        if not Path(text).suffix:
            text = text + Path(sess["file_name"]).suffix
        sess["rename_to"] = text
        sess["state"]     = ST_SELECTING
        r = await message.reply_text(
            f"✅ Will rename output to: **{text}**\n\nPress ▶️ **Process Now**.",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        schedule_delete(client, r)
        return

    if sess["state"] == ST_WAIT_TRIM:
        parts = text.split()
        if not parts:
            await message.reply_text(
                "Format: `HH:MM:SS [HH:MM:SS]`  e.g. `00:01:30 00:05:00`"
            )
            return
        sess["trim_start"] = parts[0]
        sess["trim_end"]   = parts[1] if len(parts) > 1 else ""
        sess["state"]      = ST_SELECTING
        rng = f"`{parts[0]}`" + (f" → `{parts[1]}`" if len(parts) > 1 else " → end")
        r = await message.reply_text(
            f"✅ Trim range: {rng}\n\nPress ▶️ **Process Now**.",
            reply_markup=kb.operation_menu(sess["selected_ops"]),
        )
        schedule_delete(client, r)
        return
