"""
Telegram channel logger.

Sends structured, HTML-formatted log events to a configured Telegram
channel or group using the Pyrogram MTProto client.  Set LOG_CHANNEL_ID
in config.py (or the env var) to enable.  If LOG_CHANNEL_ID is 0 / unset,
every call is a silent no-op.

Usage
-----
1.  Call ``init_tg_logger(channel_id)`` once at startup.
2.  Anywhere in async code: ``await tg_log("INFO", "message", user_id=…)``
3.  Fire-and-forget:
        import asyncio
        asyncio.create_task(tg_log("SUCCESS", "Done!", user_id=uid))
"""

import html
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_channel_id: int = 0

_LEVEL_EMOJI: dict[str, str] = {
    "INFO":    "ℹ️",
    "SUCCESS": "✅",
    "WARN":    "⚠️",
    "ERROR":   "❌",
    "START":   "🚀",
    "FILE":    "📁",
    "PROCESS": "⚙️",
}


def init_tg_logger(channel_id: int) -> None:
    """Initialise the module with a target channel/group ID."""
    global _channel_id
    _channel_id = channel_id
    logger.info("TG logger initialised (channel=%s)", channel_id)


async def tg_log(
    level: str,
    message: str,
    *,
    user_id: int = 0,
    username: str = "",
    extra: Optional[dict] = None,
) -> None:
    """
    Send a log entry to the configured Telegram channel.

    Parameters
    ----------
    level    : One of INFO / SUCCESS / WARN / ERROR / START / FILE / PROCESS
    message  : Human-readable description.
    user_id  : Telegram user ID (omit to skip user line).
    username : Telegram username without '@' (optional).
    extra    : Additional key→value pairs shown as a bullet list.
    """
    if not _channel_id:
        return

    emoji = _LEVEL_EMOJI.get(level.upper(), "📋")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [f"{emoji} <b>{html.escape(level)}</b>  |  <code>{html.escape(ts)}</code>"]

    if user_id:
        user_part = f"👤 User: <code>{user_id}</code>"
        if username:
            user_part += f" (@{html.escape(username)})"
        lines.append(user_part)

    lines.append(f"📋 {html.escape(str(message))}")

    if extra:
        for k, v in extra.items():
            lines.append(
                f"  • <b>{html.escape(str(k))}</b>: "
                f"<code>{html.escape(str(v))}</code>"
            )

    text = "\n".join(lines)
    try:
        from pyrogram import enums
        from utils.pyrogram_client import get_app
        client = get_app()
        if client.is_connected:
            await client.send_message(
                _channel_id, text, parse_mode=enums.ParseMode.HTML
            )
    except Exception as exc:
        logger.warning("Failed to send TG log: %s", exc)
