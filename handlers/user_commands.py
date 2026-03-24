"""
User-facing command handlers:
  /start  /settings  /setcrf  /setres  /setfont  /clearfont
"""
import asyncio
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

import config
import database as db
import keyboards as kb
import tg_logger as tgl
from utils.helpers import is_allowed, schedule_delete
from utils.force_join import check_force_join

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
    db.record_user(user_id,
                   update.effective_user.username or "",
                   update.effective_user.first_name or "")

    channel    = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    has_joined = await check_force_join(user_id, context.bot)
    first_name = update.effective_user.first_name or "there"

    body = (
        f"👋 *Welcome, {first_name}!*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 *{config.BOT_BRAND} — Video Processor*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send me any *video file* and choose from:\n\n"
        "  🗜 Compress  •  📝 Remove Subs  •  🎵 Remove Streams\n"
        "  🎨 Hardsub (MLRE)  •  ✂️ Trim  •  🎶 Extract Audio\n"
        "  🔄 Replace Audio  •  🖼 Watermark  •  ✏️ Rename  •  🔗 Merge\n\n"
        "✨ Select *multiple* operations — processed in one pass.\n\n"
        "📌 Results are always sent to your *PM*.\n"
        "🎨 Upload any `.ttf`/`.otf` file for a custom hardsub font.\n\n"
        "⚙️ /settings  —  encoding preferences\n"
        "🎨 /setfont   —  manage rendering font\n\n"
        f"_— Powered by {config.BOT_BRAND}_"
    )

    if channel and not has_joined:
        body += "\n\n⚠️ *You must join our channel to use the bot!*"
        msg = await update.message.reply_text(
            body,
            parse_mode="Markdown",
            reply_markup=kb.force_join_keyboard(channel),
        )
    else:
        msg = await update.message.reply_text(body, parse_mode="Markdown")
    schedule_delete(context, update, msg)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    user_id = update.effective_user.id
    db.record_user(user_id, update.effective_user.username or "",
                   update.effective_user.first_name or "")
    s = db.get_settings(user_id)
    font_name = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
    text = (
        "⚙️ *Current Settings*\n\n"
        f"  • CRF: `{s['crf']}`\n"
        f"  • Resolution: `{s['resolution']}`\n"
        f"  • Preset: `{s['preset']}`\n"
        f"  • Codec: `{s['codec']}`\n"
        f"  • Font: `{font_name}`\n\n"
        "These settings are saved and used automatically every time you compress or hardsub."
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=kb.settings_menu())


async def cmd_setcrf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text(
            "Usage: /setcrf <value>  (e.g. /setcrf 18)\nRange: 0–51, lower = better quality."
        )
        return
    value = int(args[0])
    if not 0 <= value <= 51:
        await update.message.reply_text("CRF must be between 0 and 51.")
        return
    db.update_setting(update.effective_user.id, "crf", value)
    msg = await update.message.reply_text(f"✅ CRF set to `{value}`.", parse_mode="Markdown")
    schedule_delete(context, update, msg)


async def cmd_setres(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    args = context.args
    if not args:
        opts = ", ".join(config.RESOLUTION_MAP.keys())
        await update.message.reply_text(
            f"Usage: /setres <resolution>\n\nShortcuts: {opts}\nor custom e.g. /setres 1280x720"
        )
        return
    val      = args[0].lower()
    resolved = config.RESOLUTION_MAP.get(val, val)
    db.update_setting(update.effective_user.id, "resolution", resolved)
    msg = await update.message.reply_text(
        f"✅ Resolution set to `{resolved}`.", parse_mode="Markdown"
    )
    schedule_delete(context, update, msg)


async def cmd_setfont(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    user_id   = update.effective_user.id
    s         = db.get_settings(user_id)
    font_path = s.get("custom_font_path", "")
    if font_path and os.path.exists(font_path):
        font_name = Path(font_path).name
        await update.message.reply_text(
            f"🎨 Current font: *{font_name}*\n\n"
            "Upload a new `.ttf` or `.otf` file to replace it, "
            "or use /clearfont to remove it.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "🎨 No custom font set.\n\n"
            "Upload any `.ttf` or `.otf` file and I'll save it as your "
            "rendering font for *Hardsub* operations.",
            parse_mode="Markdown",
        )


async def cmd_clearfont(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        return
    user_id  = update.effective_user.id
    s        = db.get_settings(user_id)
    old_font = s.get("custom_font_path", "")
    if old_font and os.path.exists(old_font):
        try:
            os.remove(old_font)
        except OSError:
            pass
    db.update_setting(user_id, "custom_font_path", "")
    await update.message.reply_text(
        "✅ Custom font cleared. Default system font will be used for hardsub.",
        parse_mode="Markdown",
    )
    asyncio.create_task(
        tgl.tg_log(
            "INFO", "Custom font cleared",
            user_id=user_id,
            username=update.effective_user.username or "",
        )
    )
