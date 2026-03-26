"""
Bot configuration.
Set BOT_TOKEN, PYROGRAM_API_ID, and PYROGRAM_API_HASH via environment variables.
All values can be overridden through environment variables for Heroku deployment.
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ----- Required -----
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ----- Pyrogram MTProto credentials (REQUIRED) -----
# Obtain api_id and api_hash from https://my.telegram.org/apps.
# These are required — the entire bot runs on Pyrogram MTProto, which natively
# bypasses the 20 MB download and 50 MB upload limits of the standard Bot API.
PYROGRAM_API_ID: int = int(os.environ.get("PYROGRAM_API_ID", "0"))
PYROGRAM_API_HASH: str = os.environ.get("PYROGRAM_API_HASH", "")

# ----- Access control -----
# ALLOWED_USER_IDS: comma-separated list of user IDs; empty = open to all
ALLOWED_USER_IDS: list[int] = [
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
]
# ADMIN_IDS: comma-separated list of admin user IDs
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
OUTPUT_DIR: str   = os.environ.get("OUTPUT_DIR", "outputs")
FONTS_DIR: str    = os.environ.get("FONTS_DIR", "fonts")

# ----- SQLite database path -----
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "bot_data.db")

# ----- File size & splitting -----
# Pyrogram MTProto handles files up to Telegram's 2 GB limit.
# Files larger than SPLIT_THRESHOLD_MB are split before being sent.
SPLIT_THRESHOLD_MB: int = int(os.environ.get("SPLIT_THRESHOLD_MB", "1950"))
SPLIT_PART_SIZE_MB: int = int(os.environ.get("SPLIT_PART_SIZE_MB", "1900"))
# Upper bound for accepted uploads (Telegram hard limit is 2 000 MB).
MAX_DOWNLOAD_SIZE_MB: int = int(os.environ.get("MAX_DOWNLOAD_SIZE_MB", "2000"))

# ----- Ab Bots branding -----
BOT_BRAND: str = "⚡ Ab Bots"

# ----- Force-join channel -----
FORCE_JOIN_CHANNEL: str = os.environ.get("FORCE_JOIN_CHANNEL", "")

# ----- Group message auto-delete -----
AUTO_DELETE_GROUP_SECONDS: int = int(os.environ.get("AUTO_DELETE_GROUP_SECONDS", "30"))

# ----- Accepted video file extensions (for document uploads) -----
VIDEO_EXTENSIONS: frozenset = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv",
    ".wmv", ".ts", ".m4v", ".3gp", ".m2ts", ".mpeg", ".mpg", ".mxf",
})

# ----- Default compression settings (users can override these) -----
DEFAULT_CRF: int        = 23
DEFAULT_PRESET: str     = "medium"
DEFAULT_CODEC: str      = "libx264"
DEFAULT_RESOLUTION: str = "original"

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
