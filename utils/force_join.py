"""
Force-join channel helpers.
Admins can require users to join a specific Telegram channel before using the bot.
"""
import logging

from pyrogram import Client, enums
from pyrogram.types import Message, CallbackQuery

import config
import database as db
import keyboards as kb
from utils.helpers import schedule_delete

logger = logging.getLogger(__name__)


async def check_force_join(client: Client, user_id: int) -> bool:
    """
    Return True if the user may proceed.
    True when: no force-join channel is configured, or the user is already a member.
    """
    channel = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    if not channel:
        return True
    try:
        member = await client.get_chat_member(channel, user_id)
        return member.status not in (
            enums.ChatMemberStatus.LEFT,
            enums.ChatMemberStatus.BANNED,
        )
    except Exception:
        return True  # Cannot verify → allow access


async def send_join_required(
    client: Client,
    message: Message | None = None,
    query: CallbackQuery | None = None,
) -> None:
    """Send the 'please join our channel' prompt to the user."""
    channel = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    text = (
        "⚠️ **Access Restricted**\n\n"
        "You must join our channel before using this bot.\n\n"
        "👇 Tap **Join Channel**, then send /start to continue.\n\n"
        f"_— {config.BOT_BRAND}_"
    )
    if query:
        await query.answer("⚠️ Please join our channel first!", show_alert=True)
    elif message:
        msg = await message.reply_text(
            text,
            reply_markup=kb.force_join_keyboard(channel),
        )
        schedule_delete(client, msg)


async def require_join(
    client: Client,
    message: Message | None = None,
    query: CallbackQuery | None = None,
) -> bool:
    """
    Enforce force-join gate.

    Returns True (and sends the join prompt) when the user is *blocked*.
    Returns False when the user is allowed to continue.
    """
    if message:
        user_id = message.from_user.id if message.from_user else 0
    elif query:
        user_id = query.from_user.id if query.from_user else 0
    else:
        return False

    if await check_force_join(client, user_id):
        return False

    await send_join_required(client, message=message, query=query)
    return True
