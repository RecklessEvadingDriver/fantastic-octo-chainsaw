"""
Telegram channel logger.

Sends structured, HTML-formatted log events to a configured Telegram
channel or group.  Set LOG_CHANNEL_ID in config.py (or the env var) to
enable.  If LOG_CHANNEL_ID is 0 / unset, every call is a silent no-op.

Usage
-----
1.  Call ``init_tg_logger(bot, channel_id)`` once at startup.
2.  Anywhere in async code: ``await tg_log("INFO", "message", user_id=…)``
3.  For fire-and-forget inside handlers:
        import asyncio
        asyncio.create_task(tg_log("SUCCESS", "Done!", user_id=uid))
"""

import html
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Populated by init_tg_logger()
_bot = None
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


def init_tg_logger(bot, channel_id: int) -> None:
    """Initialise the module with a Bot instance and target channel/group ID."""
    global _bot, _channel_id
    _bot = bot
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
    if not _bot or not _channel_id:
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
        await _bot.send_message(chat_id=_channel_id, text=text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Failed to send TG log: %s", exc)
