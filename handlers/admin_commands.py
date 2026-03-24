"""
Admin command handlers:
  /setforcejoin  /removeforcejoin
  /addpremium  /removepremium  /listpremium  /stats  /broadcast
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

import database as db
from sessions import _sessions, _active_tasks
from utils.helpers import is_admin, tg_log

logger = logging.getLogger(__name__)


async def cmd_setforcejoin(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set the force-join channel. Usage: /setforcejoin @channel or invite link."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        current = db.get_force_join_channel() or "_(not set)_"
        await update.message.reply_text(
            f"📢 *Force-Join Channel*\n\nCurrent: `{current}`\n\n"
            "Usage: `/setforcejoin @yourchannel`\n"
            "or:    `/setforcejoin https://t.me/joinchat/...`",
            parse_mode="Markdown",
        )
        return
    channel = context.args[0]
    db.set_force_join_channel(channel)
    await update.message.reply_text(
        f"✅ Force-join channel set to `{channel}`.\n\n"
        "Users must now join that channel before using the bot.",
        parse_mode="Markdown",
    )
    tg_log("INFO", f"Force-join channel set: {channel}", update)


async def cmd_removeforcejoin(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the force-join channel requirement."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    db.clear_force_join_channel()
    await update.message.reply_text(
        "✅ Force-join requirement removed. All users can now use the bot freely."
    )
    tg_log("INFO", "Force-join channel cleared", update)


async def cmd_addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /addpremium <user_id>")
        return
    target = int(args[0])
    db.add_premium(target, added_by=update.effective_user.id)
    await update.message.reply_text(
        f"✅ User `{target}` is now premium.", parse_mode="Markdown"
    )
    tg_log("INFO", f"Premium granted to {target}", update)


async def cmd_removepremium(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if not args or not args[0].lstrip("-").isdigit():
        await update.message.reply_text("Usage: /removepremium <user_id>")
        return
    target = int(args[0])
    db.remove_premium(target)
    await update.message.reply_text(
        f"✅ Premium removed from `{target}`.", parse_mode="Markdown"
    )
    tg_log("INFO", f"Premium revoked from {target}", update)


async def cmd_listpremium(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    users = db.list_premium()
    if not users:
        await update.message.reply_text("No premium users.")
        return
    lines = ["👑 *Premium Users*\n"]
    for u in users:
        uname = f" (@{u['username']})" if u.get("username") else ""
        fn    = u.get("first_name", "")
        lines.append(
            f"  • `{u['user_id']}`{uname} {fn} — added {u['added_at'][:10]}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    s = db.get_stats()
    text = (
        "📊 *Bot Statistics*\n\n"
        f"  • Total users:     `{s['total_users']}`\n"
        f"  • Premium users:   `{s['total_premium']}`\n"
        f"  • Files processed: `{s['total_files']}`\n"
        f"  • Active tasks:    `{len(_active_tasks)}`\n"
        f"  • Active sessions: `{len(_sessions)}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_broadcast(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text     = " ".join(context.args)
    user_ids = db.get_all_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msgs/sec
    await update.message.reply_text(
        f"📢 Broadcast done.\n✅ Sent: {sent}   ❌ Failed: {failed}"
    )
    tg_log("INFO", f"Broadcast: {sent}/{sent + failed}", update)
