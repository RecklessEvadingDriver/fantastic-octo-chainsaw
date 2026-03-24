# 🎬 Telegram File-Operations Bot

A Telegram bot that lets you select **multiple file operations at once** and process them all in a single pass — no repeated uploads, no manual FFmpeg commands.

## Features

| Operation | Description |
|-----------|-------------|
| 🗜 **Compress** | Re-encode with your saved CRF, resolution, preset and codec. Works on any input including PreDVD sources. |
| 📝 **Remove Subtitles** | Strip all subtitle streams from the file. |
| 🎵 **Remove Streams** | Pick individual audio / video / subtitle streams to delete (interactive picker). |
| ✏️ **Rename** | Rename the final output file. |
| 🔗 **Merge** | Concatenate two files into one (no re-encoding). |

All selected operations are applied in a single stretch, in the order: **Merge → Remove Streams → Remove Subtitles → Compress → Rename**.

## Requirements

- Python 3.11+
- FFmpeg & FFprobe installed and available on `$PATH`

## Setup

```bash
# 1. Clone the repo and install dependencies
pip install -r requirements.txt

# 2. Set your bot token (from @BotFather)
export BOT_TOKEN="123456:ABCdef..."

# 3. Run the bot
python bot.py
```

You can also set `BOT_TOKEN` directly in `config.py`.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/settings` | Open persistent settings panel (CRF, resolution, preset, codec) |
| `/setcrf <value>` | Quickly set CRF (0–51, lower = better quality; e.g. `/setcrf 18`) |
| `/setres <value>` | Set output resolution (e.g. `/setres 720p` or `/setres 1280x720`) |

## Usage

1. Send any video or document to the bot.
2. An inline menu appears — tap to **toggle** any combination of operations.
3. Press **▶️ Process Now**.
   - If **Remove Streams** is selected, the bot shows a per-stream picker first.
   - If **Rename** is selected, the bot asks for the new filename.
   - If **Merge** is selected, the bot asks you to send the second file.
4. The bot processes everything and sends back the result.

## Compression Settings

Compression settings are **saved per user** and reused automatically — you never need to type FFmpeg flags.

| Setting | Default | How to change |
|---------|---------|---------------|
| CRF | 23 | `/setcrf 18` or via `/settings` |
| Resolution | original | `/setres 720p` or via `/settings` |
| Preset | medium | via `/settings` |
| Codec | libx264 | via `/settings` (libx264 / libx265 / libvpx-vp9) |

## Configuration

All configurable values live in `config.py`:

```python
BOT_TOKEN          = "..."       # or set via env var
ALLOWED_USER_IDS   = []          # empty = open to all users
DOWNLOAD_DIR       = "downloads"
OUTPUT_DIR         = "outputs"
DATABASE_PATH      = "bot_data.db"
DEFAULT_CRF        = 23
DEFAULT_PRESET     = "medium"
DEFAULT_CODEC      = "libx264"
DEFAULT_RESOLUTION = "original"
```

## Project Structure

```
bot.py           Main entry point — all Telegram handlers
config.py        Configuration variables
database.py      SQLite-backed user settings
ffmpeg_utils.py  FFmpeg / FFprobe wrappers
keyboards.py     Inline keyboard builders
requirements.txt Python dependencies
```
