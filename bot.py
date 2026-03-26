"""
⚡ Ab Bots — Video Processor
============================
Entry point.  All logic lives in sub-packages:

  handlers/
    user_commands.py    — /start  /settings  /setcrf  /setres  /setfont  /clearfont
    admin_commands.py   — /setforcejoin  /removeforcejoin  /addpremium
                          /removepremium  /listpremium  /stats  /broadcast
    file_handler.py     — video/document/audio upload handling
    text_handler.py     — plain-text input (rename, trim)
    callback_handler.py — inline keyboard callbacks
    processing.py       — _start_processing + _process_file with live progress

  utils/
    helpers.py          — shared helper functions
    force_join.py       — force-join channel enforcement
    progress.py         — animated progress tracker

  sessions.py           — global in-memory session & task state
  database.py           — SQLite persistence
  config.py             — configuration / env-vars
  ffmpeg_utils.py       — FFmpeg wrappers
  keyboards.py          — inline keyboard builders
  tg_logger.py          — Telegram channel logging
"""

import logging
import os

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
import database as db
import tg_logger as tgl

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
os.makedirs(config.OUTPUT_DIR, exist_ok=True)
os.makedirs(config.FONTS_DIR, exist_ok=True)


def main() -> None:
    db.init_db()

    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error(
            "BOT_TOKEN is not set. "
            "Export it as an environment variable or edit config.py."
        )
        return

    async def _on_startup(app: Application) -> None:
        if config.LOG_CHANNEL_ID:
            tgl.init_tg_logger(app.bot, config.LOG_CHANNEL_ID)
        await tgl.tg_log("START", f"{config.BOT_BRAND} started and polling")

    builder = Application.builder().token(config.BOT_TOKEN)
    if config.LOCAL_API_SERVER:
        builder = (
            builder
            .base_url(f"{config.LOCAL_API_SERVER}/bot")
            .base_file_url(f"{config.LOCAL_API_SERVER}/file/bot")
            .local_mode(True)
        )
    app = builder.post_init(_on_startup).build()

    # ── User commands ──────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("settings",  cmd_settings))
    app.add_handler(CommandHandler("setcrf",    cmd_setcrf))
    app.add_handler(CommandHandler("setres",    cmd_setres))
    app.add_handler(CommandHandler("setfont",   cmd_setfont))
    app.add_handler(CommandHandler("clearfont", cmd_clearfont))

    # ── Admin commands ─────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("setforcejoin",    cmd_setforcejoin))
    app.add_handler(CommandHandler("removeforcejoin", cmd_removeforcejoin))
    app.add_handler(CommandHandler("addpremium",      cmd_addpremium))
    app.add_handler(CommandHandler("removepremium",   cmd_removepremium))
    app.add_handler(CommandHandler("listpremium",     cmd_listpremium))
    app.add_handler(CommandHandler("stats",           cmd_stats))
    app.add_handler(CommandHandler("broadcast",       cmd_broadcast))

    # ── File uploads (video, documents, audio) ─────────────────────────────────
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.ALL | filters.AUDIO,
            handle_file,
        )
    )

    # ── Plain text (rename, trim input) ────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # ── Inline button callbacks ────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot started. Polling…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
