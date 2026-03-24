"""
Bot configuration.
Set BOT_TOKEN via environment variable or replace the placeholder below.
"""
import os

# ----- Required -----
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ----- Optional: restrict bot to specific users/groups (empty = open to all) -----
ALLOWED_USER_IDS: list[int] = []   # e.g. [123456789, 987654321]
ADMIN_IDS: list[int] = []          # future admin commands

# ----- Working directories -----
DOWNLOAD_DIR: str = os.environ.get("DOWNLOAD_DIR", "downloads")
OUTPUT_DIR: str = os.environ.get("OUTPUT_DIR", "outputs")

# ----- SQLite database path -----
DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "bot_data.db")

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
