"""
Force-join channel helpers.
Admins can require users to join a specific Telegram channel before using the bot.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
import keyboards as kb
from utils.helpers import schedule_delete

logger = logging.getLogger(__name__)


async def check_force_join(user_id: int, bot) -> bool:
    """
    Return True if the user may proceed.
    True when: no force-join channel is configured, or the user is already a member.
    """
    channel = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    if not channel:
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return True  # Cannot verify → allow access


async def send_join_required(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the 'please join our channel' prompt to the user."""
    channel = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    text = (
        "⚠️ *Access Restricted*\n\n"
        "You must join our channel before using this bot.\n\n"
        "👇 Tap *Join Channel*, then send /start to continue.\n\n"
        f"_— {config.BOT_BRAND}_"
    )
    if update.callback_query:
        await update.callback_query.answer(
            "⚠️ Please join our channel first!", show_alert=True
        )
    elif update.message:
        msg = await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=kb.force_join_keyboard(channel),
        )
        schedule_delete(context, update, msg)


async def require_join(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Enforce force-join gate.

    Returns True (and sends the join prompt) when the user is *blocked*.
    Returns False when the user is allowed to continue.
    """
    user_id = update.effective_user.id if update.effective_user else 0
    if await check_force_join(user_id, context.bot):
        return False
    await send_join_required(update, context)
    return True
