"""
Pyrogram MTProto client — central bot client singleton.
"""
import logging

import config

logger = logging.getLogger(__name__)

_app = None  # shared Pyrogram Client instance


def get_app():
    """Return (and lazily create) the shared Pyrogram ``Client``.

    Raises ``RuntimeError`` when required credentials are missing.
    """
    global _app
    if _app is None:
        if not config.PYROGRAM_API_ID:
            raise RuntimeError(
                "PYROGRAM_API_ID is not set.  "
                "Obtain it from https://my.telegram.org/apps and set it as "
                "an environment variable."
            )
        if not config.PYROGRAM_API_HASH:
            raise RuntimeError(
                "PYROGRAM_API_HASH is not set.  "
                "Obtain it from https://my.telegram.org/apps and set it as "
                "an environment variable."
            )
        if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            raise RuntimeError(
                "BOT_TOKEN is not set.  "
                "Create a bot via @BotFather on Telegram and set the token as "
                "an environment variable."
            )
        from pyrogram import Client
        _app = Client(
            name="bot_session",
            api_id=config.PYROGRAM_API_ID,
            api_hash=config.PYROGRAM_API_HASH,
            bot_token=config.BOT_TOKEN,
            in_memory=True,   # no session file on Heroku's ephemeral filesystem
        )
    return _app

