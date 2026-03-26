"""
Admin command handlers:
  /setforcejoin  /removeforcejoin
  /addpremium  /removepremium  /listpremium  /stats  /broadcast
"""
import asyncio
import logging

from pyrogram import Client
from pyrogram.types import Message

import database as db
from sessions import _sessions, _active_tasks
from utils.helpers import is_admin, tg_log

logger = logging.getLogger(__name__)


async def cmd_setforcejoin(client: Client, message: Message) -> None:
    """Set the force-join channel. Usage: /setforcejoin @channel or invite link."""
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    args = (message.command or [])[1:]
    if not args:
        current = db.get_force_join_channel() or "_(not set)_"
        await message.reply_text(
            f"📢 **Force-Join Channel**\n\nCurrent: `{current}`\n\n"
            "**Usage:** `/setforcejoin @yourchannel`\n"
            "or: `/setforcejoin https://t.me/joinchat/...`"
        )
        return
    channel = args[0]
    db.set_force_join_channel(channel)
    await message.reply_text(
        f"✅ Force-join channel set to `{channel}`.\n\n"
        "Users must now join that channel before using the bot."
    )
    tg_log("INFO", f"Force-join channel set: {channel}", message)


async def cmd_removeforcejoin(client: Client, message: Message) -> None:
    """Remove the force-join channel requirement."""
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    db.clear_force_join_channel()
    await message.reply_text(
        "✅ Force-join requirement removed. All users can now use the bot freely."
    )
    tg_log("INFO", "Force-join channel cleared", message)


async def cmd_addpremium(client: Client, message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    args = (message.command or [])[1:]
    if not args or not args[0].lstrip("-").isdigit():
        await message.reply_text("**Usage:** `/addpremium <user_id>`")
        return
    target = int(args[0])
    db.add_premium(target, added_by=message.from_user.id)
    await message.reply_text(f"✅ User `{target}` is now premium.")
    tg_log("INFO", f"Premium granted to {target}", message)


async def cmd_removepremium(client: Client, message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    args = (message.command or [])[1:]
    if not args or not args[0].lstrip("-").isdigit():
        await message.reply_text("**Usage:** `/removepremium <user_id>`")
        return
    target = int(args[0])
    db.remove_premium(target)
    await message.reply_text(f"✅ Premium removed from `{target}`.")
    tg_log("INFO", f"Premium revoked from {target}", message)


async def cmd_listpremium(client: Client, message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    users = db.list_premium()
    if not users:
        await message.reply_text("No premium users.")
        return
    lines = ["👑 **Premium Users**\n"]
    for u in users:
        uname = f" (@{u['username']})" if u.get("username") else ""
        fn    = u.get("first_name", "")
        lines.append(
            f"  • `{u['user_id']}`{uname} {fn} — added {u['added_at'][:10]}"
        )
    await message.reply_text("\n".join(lines))


async def cmd_stats(client: Client, message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    s = db.get_stats()
    text = (
        "📊 **Bot Statistics**\n\n"
        f"  • Total users:     `{s['total_users']}`\n"
        f"  • Premium users:   `{s['total_premium']}`\n"
        f"  • Files processed: `{s['total_files']}`\n"
        f"  • Active tasks:    `{len(_active_tasks)}`\n"
        f"  • Active sessions: `{len(_sessions)}`"
    )
    await message.reply_text(text)


async def cmd_broadcast(client: Client, message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        await message.reply_text("⛔ Admin only.")
        return
    args = (message.command or [])[1:]
    if not args:
        await message.reply_text("**Usage:** `/broadcast <message>`")
        return
    text     = " ".join(args)
    user_ids = db.get_all_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await client.send_message(uid, f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)   # ~20 msgs/sec
    await message.reply_text(
        f"📢 Broadcast complete.\n✅ Sent: `{sent}`   ❌ Failed: `{failed}`"
    )
    tg_log("INFO", f"Broadcast: {sent}/{sent + failed}", message)
