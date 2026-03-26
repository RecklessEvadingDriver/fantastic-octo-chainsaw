"""
Bot configuration.
Set BOT_TOKEN via environment variable or replace the placeholder below.
All values can be overridden through environment variables for Heroku deployment.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ----- Required -----
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ----- Access control -----
# ALLOWED_USER_IDS: comma-separated list of user IDs; empty = open to all
ALLOWED_USER_IDS: list[int] = [
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
]
# ADMIN_IDS: comma-separated list of admin user IDs (can manage premium users etc.)
ADMIN_IDS: list[int] = [
    int(x) for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

# ----- Telegram logs channel -----
# Set to a channel/group ID (negative for groups, e.g. -1001234567890).
# Leave as 0 to disable TG logging.
LOG_CHANNEL_ID: int = int(os.environ.get("LOG_CHANNEL_ID", "0"))

# ----- Working directories -----
DOWNLOAD_DIR: str = os.environ.get("DOWNLOAD_DIR", "downloads")
OUTPUT_DIR: str = os.environ.get("OUTPUT_DIR", "outputs")
FONTS_DIR: str = os.environ.get("FONTS_DIR", "fonts")   # per-user custom fonts

# ----- SQLite database path -----
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "bot_data.db")

# ----- Local Telegram Bot API server -----
# Set LOCAL_API_SERVER to the base URL of your local Telegram Bot API server
# (e.g. "http://localhost:8081") to lift the 20 MB download restriction and
# allow files up to 2000 MB.  Leave empty to use the standard cloud API.
LOCAL_API_SERVER: str = os.environ.get("LOCAL_API_SERVER", "").rstrip("/")

# ----- File size & splitting -----
# Files larger than SPLIT_THRESHOLD_MB will be split into multiple parts.
# For the standard Telegram Bot API the practical send limit is ~2000 MB.
# With a local Bot API server this can be raised to ~4000 MB.
SPLIT_THRESHOLD_MB: int = int(os.environ.get("SPLIT_THRESHOLD_MB", "2000"))
# Size of each split part (should be ≤ SPLIT_THRESHOLD_MB)
SPLIT_PART_SIZE_MB: int = int(os.environ.get("SPLIT_PART_SIZE_MB", "1950"))
# Maximum file size that the Telegram Bot API allows downloading via getFile().
# Defaults to 20 MB for the standard cloud API, or 2000 MB when a local Bot
# API server is configured (LOCAL_API_SERVER).  Override via MAX_DOWNLOAD_SIZE_MB.
_default_max_dl: str = "2000" if LOCAL_API_SERVER else "20"
MAX_DOWNLOAD_SIZE_MB: int = int(os.environ.get("MAX_DOWNLOAD_SIZE_MB", _default_max_dl))

# ----- Ab Bots branding -----
BOT_BRAND: str = "⚡ Ab Bots"

# ----- Force-join channel -----
# Set to a channel username (e.g. @mychannel) or invite link so that users must
# join before they can interact with the bot.  Leave empty to disable.
FORCE_JOIN_CHANNEL: str = os.environ.get("FORCE_JOIN_CHANNEL", "")

# ----- Group message auto-delete -----
# Bot messages sent in group/supergroup chats are deleted after this many seconds.
# Set to 0 to disable auto-deletion. Does NOT affect PM messages.
AUTO_DELETE_GROUP_SECONDS: int = int(os.environ.get("AUTO_DELETE_GROUP_SECONDS", "30"))

# ----- Accepted video file extensions (for document uploads) -----
VIDEO_EXTENSIONS: frozenset = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv",
    ".wmv", ".ts", ".m4v", ".3gp", ".m2ts", ".mpeg", ".mpg", ".mxf",
})

# ----- Default compression settings (users can override these) -----
DEFAULT_CRF: int = 23           # 0–51; lower = better quality, larger file
DEFAULT_PRESET: str = "medium"  # ultrafast / superfast / veryfast / faster /
                                #   fast / medium / slow / slower / veryslow
DEFAULT_CODEC: str = "libx264"  # libx264 | libx265 | libvpx-vp9
DEFAULT_RESOLUTION: str = "original"  # "original" or e.g. "1280x720" / "1920x1080"

# ----- Valid preset choices (for validation) -----
VALID_PRESETS: tuple[str, ...] = (
    "ultrafast", "superfast", "veryfast", "faster",
    "fast", "medium", "slow", "slower", "veryslow",
)

# ----- Valid resolution shortcuts -----
RESOLUTION_MAP: dict[str, str] = {
    "original": "original",
    "4k":       "3840x2160",
    "2k":       "2560x1440",
    "1080p":    "1920x1080",
    "720p":     "1280x720",
    "480p":     "854x480",
    "360p":     "640x360",
}
