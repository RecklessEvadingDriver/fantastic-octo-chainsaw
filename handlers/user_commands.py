"""
User-facing command handlers:
  /start  /settings  /setcrf  /setres  /setfont  /clearfont
"""
import asyncio
import logging
import os
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

import config
import database as db
import keyboards as kb
import tg_logger as tgl
from utils.helpers import is_allowed, schedule_delete
from utils.force_join import check_force_join

logger = logging.getLogger(__name__)


async def cmd_start(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return

    db.record_user(user.id, user.username or "", user.first_name or "")

    channel    = db.get_force_join_channel() or config.FORCE_JOIN_CHANNEL
    has_joined = await check_force_join(client, user.id)
    first_name = user.first_name or "there"

    body = (
        f"👋 **Welcome, {first_name}!**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 **{config.BOT_BRAND} — Video Processor**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send me any **video file** and choose from:\n\n"
        "  🗜 Compress  •  📝 Remove Subs  •  🎵 Remove Streams\n"
        "  🎨 Hardsub (Burn Subs)  •  ✂️ Trim  •  🎶 Extract Audio\n"
        "  🔄 Replace Audio  •  🖼 Watermark  •  ✏️ Rename  •  🔗 Merge\n\n"
        "✨ Select **multiple** operations — processed in one pass.\n"
        "📌 Results are always delivered to your **PM**.\n"
        "🎨 Upload any `.ttf`/`.otf` file as your custom hardsub font.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ /settings  —  encoding preferences\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_Powered by {config.BOT_BRAND}_"
    )

    if channel and not has_joined:
        body += "\n\n⚠️ **You must join our channel to use the bot!**"
        msg = await message.reply_text(body, reply_markup=kb.force_join_keyboard(channel))
    else:
        msg = await message.reply_text(body, reply_markup=kb.start_menu())
    schedule_delete(client, msg)


async def cmd_settings(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    db.record_user(user.id, user.username or "", user.first_name or "")
    s = db.get_settings(user.id)
    font_name = Path(s["custom_font_path"]).name if s.get("custom_font_path") else "none"
    text = (
        "⚙️ **Encoding Settings**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  🔢 **CRF:**        `{s['crf']}`\n"
        f"  📐 **Resolution:** `{s['resolution']}`\n"
        f"  ⚡ **Preset:**     `{s['preset']}`\n"
        f"  🎬 **Codec:**      `{s['codec']}`\n"
        f"  🎨 **Font:**       `{font_name}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_These settings apply to every Compress & Hardsub operation._"
    )
    await message.reply_text(text, reply_markup=kb.settings_menu())


async def cmd_setcrf(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    args = (message.command or [])[1:]
    if not args or not args[0].isdigit():
        await message.reply_text(
            "**Usage:** `/setcrf <value>`  (e.g. `/setcrf 18`)\n"
            "Range: 0–51 — lower = better quality / larger file."
        )
        return
    value = int(args[0])
    if not 0 <= value <= 51:
        await message.reply_text("❌ CRF must be between 0 and 51.")
        return
    db.update_setting(user.id, "crf", value)
    msg = await message.reply_text(f"✅ CRF set to `{value}`.")
    schedule_delete(client, msg)


async def cmd_setres(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    args = (message.command or [])[1:]
    if not args:
        opts = ", ".join(config.RESOLUTION_MAP.keys())
        await message.reply_text(
            f"**Usage:** `/setres <resolution>`\n\nShortcuts: {opts}\n"
            "Custom: `/setres 1280x720`"
        )
        return
    val      = args[0].lower()
    resolved = config.RESOLUTION_MAP.get(val, val)
    db.update_setting(user.id, "resolution", resolved)
    msg = await message.reply_text(f"✅ Resolution set to `{resolved}`.")
    schedule_delete(client, msg)


async def cmd_setfont(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    s         = db.get_settings(user.id)
    font_path = s.get("custom_font_path", "")
    if font_path and os.path.exists(font_path):
        font_name = Path(font_path).name
        await message.reply_text(
            f"🎨 **Current font:** `{font_name}`\n\n"
            "Upload a new `.ttf` or `.otf` file to replace it, "
            "or use /clearfont to remove it."
        )
    else:
        await message.reply_text(
            "🎨 **No custom font set.**\n\n"
            "Upload any `.ttf` or `.otf` file and it will be saved as your "
            "rendering font for **Hardsub** operations."
        )


async def cmd_clearfont(client: Client, message: Message) -> None:
    user = message.from_user
    if not user or not is_allowed(user.id):
        return
    s        = db.get_settings(user.id)
    old_font = s.get("custom_font_path", "")
    if old_font and os.path.exists(old_font):
        try:
            os.remove(old_font)
        except OSError:
            pass
    db.update_setting(user.id, "custom_font_path", "")
    await message.reply_text(
        "✅ Custom font cleared. Default system font will be used for hardsub."
    )
    asyncio.create_task(
        tgl.tg_log(
            "INFO", "Custom font cleared",
            user_id=user.id,
            username=user.username or "",
        )
    )
