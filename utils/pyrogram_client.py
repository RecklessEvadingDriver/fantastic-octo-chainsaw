"""
Pyrogram MTProto client.

Used to download Telegram files via MTProto rather than the standard Bot API,
natively bypassing the 20 MB Bot API download limit without needing a Local
Bot API Server.

Lifecycle
---------
Call ``start_pyro_client()`` once at bot startup and
``stop_pyro_client()`` at shutdown.  During operation, call
``pyro_download_file(chat_id, message_id, dest)`` to download a file.
The caller is responsible for deleting *dest* via a ``try/finally`` block.

Requirements
------------
Set ``PYROGRAM_API_ID`` and ``PYROGRAM_API_HASH`` environment variables
(obtained from https://my.telegram.org) together with the existing
``BOT_TOKEN`` variable.  If either credential is missing, Pyrogram is
disabled and ``pyro_download_file`` raises ``RuntimeError``.
"""
import logging
import os

import config

logger = logging.getLogger(__name__)

_client = None  # shared Pyrogram Client instance


# ── Public helpers ─────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """Return ``True`` when both Pyrogram credentials are present."""
    return bool(config.PYROGRAM_API_ID and config.PYROGRAM_API_HASH)


def _get_client():
    """Return (and lazily create) the shared Pyrogram ``Client``.

    The client is configured with ``no_updates=True`` so it never competes
    with the python-telegram-bot dispatcher for incoming updates, and with
    ``in_memory=True`` so no session file is written to the (ephemeral)
    Heroku filesystem.
    """
    global _client
    if _client is None:
        if not is_configured():
            raise RuntimeError(
                "Pyrogram is not configured. "
                "Set PYROGRAM_API_ID and PYROGRAM_API_HASH environment variables "
                "(from https://my.telegram.org) to enable large-file downloads."
            )
        from pyrogram import Client  # deferred import – avoid hard dependency at module level
        _client = Client(
            name="bot_session",
            api_id=config.PYROGRAM_API_ID,
            api_hash=config.PYROGRAM_API_HASH,
            bot_token=config.BOT_TOKEN,
            no_updates=True,   # this client only downloads; PTB handles updates
            in_memory=True,    # avoid writing session files to ephemeral storage
        )
    return _client


async def start_pyro_client() -> None:
    """Connect the Pyrogram client.  Call once at bot startup."""
    if not is_configured():
        logger.info(
            "Pyrogram credentials not set – large-file MTProto downloads disabled."
        )
        return
    client = _get_client()
    if not client.is_connected:
        await client.start()
        logger.info("Pyrogram MTProto client started.")


async def stop_pyro_client() -> None:
    """Disconnect the Pyrogram client.  Call once at bot shutdown."""
    global _client
    if _client is not None and _client.is_connected:
        await _client.stop()
        logger.info("Pyrogram MTProto client stopped.")
    _client = None


# ── Core download function ─────────────────────────────────────────────────────

async def pyro_download_file(chat_id: int, message_id: int, dest: str) -> None:
    """Download a file from Telegram via MTProto, bypassing the 20 MB Bot API limit.

    Parameters
    ----------
    chat_id:    Telegram chat/user ID that contains the message.
    message_id: ID of the message that holds the file.
    dest:       Absolute or relative path where the downloaded file is written.

    Raises
    ------
    RuntimeError
        When Pyrogram credentials are not configured.
    ValueError
        When the message does not contain a downloadable media object.

    Notes
    -----
    **The caller must guarantee that *dest* is removed after use**, even if
    subsequent processing raises an exception.  The recommended pattern is::

        local_path = ...
        await pyro_download_file(chat_id, message_id, local_path)
        try:
            # process / upload the file
            ...
        finally:
            try:
                os.remove(local_path)
            except OSError:
                pass
    """
    client = _get_client()
    if not client.is_connected:
        await client.start()

    message = await client.get_messages(chat_id, message_id)
    if not message or not message.media:
        raise ValueError(
            f"Message {message_id} in chat {chat_id} contains no downloadable media."
        )

    # download_media writes the file and returns the path it used.
    # We pass file_name=dest so Pyrogram writes directly to our target path.
    downloaded = await client.download_media(message, file_name=dest)

    # Pyrogram may append an extension or alter the path; rename to dest if needed.
    if downloaded and os.path.abspath(downloaded) != os.path.abspath(dest):
        os.rename(downloaded, dest)
