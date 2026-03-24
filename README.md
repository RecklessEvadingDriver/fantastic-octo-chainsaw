# ⚡ Ab Bots — Telegram Video Processor

A feature-rich Telegram bot for video processing, powered by **⚡ Ab Bots**.  
Results are delivered to the user's **private chat (PM)**; group messages auto-delete after 30 s.

---

## ✨ Features

| Operation | Description |
|---|---|
| 🗜 Compress | Re-encode with CRF / preset / codec / resolution |
| 📝 Remove Subtitles | Strip all soft subtitle streams |
| 🎵 Remove Streams | Choose individual streams to drop |
| �� Hardsub (MLRE) | Burn subtitles into video pixels; supports custom fonts |
| ✂️ Trim | Cut to a start/end time range |
| 🎶 Extract Audio | Export audio as MP3 / AAC / OPUS / FLAC / WAV |
| 🔄 Replace Audio | Swap the audio track with another file |
| 🖼 Watermark | Overlay a PNG/JPG image at a chosen position |
| ✏️ Rename | Rename the output file |
| 🔗 Merge | Concatenate with a second video |

### 📢 Force-Join Channel
Admins can require users to join a Telegram channel before using the bot.

```
/setforcejoin @yourchannel      – enable the requirement
/removeforcejoin                – remove the requirement
```

### 📊 Live Processing Progress
While a video is being processed users see a real-time animated status:

```
⚙️ Processing your video…

📊 ████████░░ 80%
🔄 Compressing video…
⏱ Elapsed: 01:23
📋 Steps: 4 / 5

— ⚡ Ab Bots
```

### 👑 Admin Features
| Command | Description |
|---|---|
| `/setforcejoin <@ch or link>` | Require users to join a channel |
| `/removeforcejoin` | Remove the force-join requirement |
| `/addpremium <user_id>` | Grant premium status |
| `/removepremium <user_id>` | Revoke premium status |
| `/listpremium` | List all premium users |
| `/stats` | Bot usage statistics |
| `/broadcast <msg>` | Message all users |

### ⚙️ Reliability
- **One task per user** — prevents server overload
- **Auto file splitting** — files over `SPLIT_THRESHOLD_MB` sent as parts
- **Group auto-delete** — bot replies in groups deleted after `AUTO_DELETE_GROUP_SECONDS`
- **TG logs channel** — set `LOG_CHANNEL_ID` for structured activity logs

---

## 📁 Project Structure

```
bot.py                   ← entry point (main only)
sessions.py              ← global session store & state constants
config.py                ← configuration / env-vars
database.py              ← SQLite persistence
ffmpeg_utils.py          ← FFmpeg wrappers
keyboards.py             ← inline keyboard builders
tg_logger.py             ← Telegram channel logging

handlers/
  user_commands.py       ← /start /settings /setcrf /setres /setfont /clearfont
  admin_commands.py      ← /setforcejoin /removeforcejoin /addpremium … /broadcast
  file_handler.py        ← video & document upload handling
  text_handler.py        ← plain-text input (rename, trim)
  callback_handler.py    ← inline keyboard callbacks
  processing.py          ← pipeline orchestration + FFmpeg execution

utils/
  helpers.py             ← shared helper functions
  force_join.py          ← force-join channel logic
  progress.py            ← animated progress tracker
```

---

## 🚀 Heroku Deployment

1. Add buildpacks:
   ```bash
   heroku buildpacks:add --index 1 https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
   heroku buildpacks:add heroku/python
   ```

2. Set config vars:
   ```bash
   heroku config:set BOT_TOKEN=...
   heroku config:set ADMIN_IDS=123456789
   heroku config:set LOG_CHANNEL_ID=-1001234567890
   heroku config:set FORCE_JOIN_CHANNEL=@yourchannel
   heroku config:set AUTO_DELETE_GROUP_SECONDS=30
   heroku config:set SPLIT_THRESHOLD_MB=2000
   ```

3. Deploy and scale:
   ```bash
   git push heroku main
   heroku ps:scale worker=1
   ```

---

## 👤 User Commands

| Command | Description |
|---|---|
| `/start` | Welcome message & feature list |
| `/settings` | View / edit encoding settings |
| `/setcrf <0-51>` | Set CRF quality (lower = better) |
| `/setres <res>` | Set resolution (720p, 1080p, 1280x720, …) |
| `/setfont` | View custom font info |
| `/clearfont` | Remove saved custom font |

Upload any `.ttf` or `.otf` file to set it as your hardsub rendering font.

---

## 🔧 Environment Variables

See `.env.example` for a full documented list.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | **Required** Telegram bot token |
| `ADMIN_IDS` | `` | Comma-separated admin user IDs |
| `LOG_CHANNEL_ID` | `0` | Channel/group for TG logs (0 = disabled) |
| `ALLOWED_USER_IDS` | `` | Whitelist (empty = open to all) |
| `FORCE_JOIN_CHANNEL` | `` | Channel users must join (empty = disabled) |
| `SPLIT_THRESHOLD_MB` | `2000` | Split files larger than this |
| `SPLIT_PART_SIZE_MB` | `1950` | Size of each split part |
| `AUTO_DELETE_GROUP_SECONDS` | `30` | Group message TTL (0 = disabled) |

---

*Powered by ⚡ Ab Bots*
