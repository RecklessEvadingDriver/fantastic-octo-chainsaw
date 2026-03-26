"""
⚡ Ab Bots — Video Processor
============================
Pyrogram-based entry point.  All logic lives in sub-packages:

  handlers/
    user_commands.py    — /start  /settings  /setcrf  /setres  /setfont  /clearfont
    admin_commands.py   — /setforcejoin  /removeforcejoin  /addpremium
                          /removepremium  /listpremium  /stats  /broadcast
    file_handler.py     — video/document/audio upload handling
    text_handler.py     — plain-text input (rename, trim)
    callback_handler.py — inline keyboard callbacks
    processing.py       — start_processing + process_file with live progress

  utils/
    helpers.py          — shared helper functions
    force_join.py       — force-join channel enforcement
    progress.py         — animated progress tracker
    pyrogram_client.py  — Pyrogram MTProto client singleton

  sessions.py           — global in-memory session & task state
  database.py           — SQLite persistence
  config.py             — configuration / env-vars
  ffmpeg_utils.py       — FFmpeg wrappers
  keyboards.py          — Pyrogram inline keyboard builders
  tg_logger.py          — Telegram channel logging
"""

import asyncio
import json
import logging
import os
import urllib.request

from pyrogram import Client, filters, idle
from pyrogram.handlers import CallbackQueryHandler, MessageHandler

# pyrogram 2.0.x does not expose filters.edited; build the equivalent manually.
edited = filters.create(lambda _, __, m: bool(getattr(m, "edit_date", None)))

# pyrogram 2.0.x exposes filters.command as a factory *method*, not a filter
# instance, so `~filters.command` raises TypeError.  Build a plain filter that
# matches any bot-command message (text starting with "/") so it can be
# negated with ~.
is_command = filters.create(
    lambda _, __, m: bool(
        (m.text and m.text.startswith("/"))
        or (m.caption and m.caption.startswith("/"))
    )
)

import config
import database as db
import tg_logger as tgl
from utils.pyrogram_client import get_app

from handlers.user_commands import (
    cmd_start, cmd_settings, cmd_setcrf, cmd_setres, cmd_setfont, cmd_clearfont,
)
from handlers.admin_commands import (
    cmd_setforcejoin, cmd_removeforcejoin,
    cmd_addpremium, cmd_removepremium, cmd_listpremium,
    cmd_stats, cmd_broadcast,
)
from handlers.file_handler import handle_file
from handlers.text_handler import handle_text
from handlers.callback_handler import handle_callback

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Ensure working directories exist ──────────────────────────────────────────
os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
os.makedirs(config.OUTPUT_DIR,   exist_ok=True)
os.makedirs(config.FONTS_DIR,    exist_ok=True)


def _register_handlers(app: Client) -> None:
    """Register all message and callback handlers on *app*."""

    # ── User commands ──────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(
        cmd_start, filters.command(["start", "help"]) & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_settings, filters.command("settings") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_setcrf, filters.command("setcrf") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_setres, filters.command("setres") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_setfont, filters.command("setfont") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_clearfont, filters.command("clearfont") & ~edited,
    ))

    # ── Admin commands ─────────────────────────────────────────────────────────
    app.add_handler(MessageHandler(
        cmd_setforcejoin, filters.command("setforcejoin") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_removeforcejoin, filters.command("removeforcejoin") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_addpremium, filters.command("addpremium") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_removepremium, filters.command("removepremium") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_listpremium, filters.command("listpremium") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_stats, filters.command("stats") & ~edited,
    ))
    app.add_handler(MessageHandler(
        cmd_broadcast, filters.command("broadcast") & ~edited,
    ))

    # ── File uploads (video, documents, audio) ─────────────────────────────────
    app.add_handler(MessageHandler(
        handle_file,
        (filters.video | filters.document | filters.audio) & ~edited,
    ))

    # ── Plain text (rename, trim input) ────────────────────────────────────────
    app.add_handler(MessageHandler(
        handle_text,
        filters.text & ~is_command & ~edited,
    ))

    # ── Inline button callbacks ────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))


def _delete_telegram_webhook(token: str) -> None:
    """
    Delete any existing Telegram Bot API webhook.

    If a webhook was previously set, Telegram will keep POSTing updates to it
    even after switching to Pyrogram MTProto polling, causing Heroku H14 errors
    (no web dyno to receive those requests).  Calling deleteWebhook once at
    startup clears the webhook so Telegram stops making outbound HTTP requests.
    """
    try:
        url = (
            f"https://api.telegram.org/bot{token}"
            "/deleteWebhook?drop_pending_updates=false"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            logger.info("Telegram webhook deleted successfully.")
        else:
            logger.warning("deleteWebhook returned non-ok response: %s", data)
    except Exception as exc:
        logger.warning("Could not delete Telegram webhook: %s", exc)


async def main() -> None:
    db.init_db()

    if not config.PYROGRAM_API_ID or not config.PYROGRAM_API_HASH:
        logger.error(
            "PYROGRAM_API_ID and PYROGRAM_API_HASH are required. "
            "Obtain them from https://my.telegram.org/apps and set them as "
            "environment variables."
        )
        return

    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error(
            "BOT_TOKEN is not set. "
            "Export it as an environment variable or edit config.py."
        )
        return

    await asyncio.to_thread(_delete_telegram_webhook, config.BOT_TOKEN)

    app = get_app()
    _register_handlers(app)

    async with app:
        tgl.init_tg_logger(config.LOG_CHANNEL_ID)
        await tgl.tg_log("START", f"{config.BOT_BRAND} started (Pyrogram MTProto)")
        logger.info(
            "Bot started — polling via Pyrogram MTProto "
            "(no 20 MB download / 50 MB upload restriction)."
        )
        await idle()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
