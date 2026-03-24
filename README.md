# Telegram Video-Processing Bot

A feature-rich Telegram bot for video processing, deployable on Heroku.
Results are delivered to the user's **private chat (PM)**; group messages auto-delete after 30 s.

---

## Features

| Operation | Description |
|---|---|
| Compress | Re-encode with CRF / preset / codec / resolution |
| Remove Subtitles | Strip all soft subtitle streams |
| Remove Streams | Choose individual streams to drop |
| Hardsub (MLRE) | Burn subtitles into video pixels; supports custom fonts |
| Trim | Cut to a start/end time range |
| Extract Audio | Export audio as MP3 / AAC / OPUS / FLAC / WAV |
| Replace Audio | Swap the audio track with another file |
| Watermark | Overlay a PNG/JPG image |
| Rename | Rename the output file |
| Merge | Concatenate with a second video |

### Admin features
- `/addpremium <user_id>` - grant premium
- `/removepremium <user_id>` - revoke premium
- `/listpremium` - list all premium users
- `/stats` - usage statistics
- `/broadcast <msg>` - message all users

### Reliability
- **One task per user** - prevents overload
- **Auto file splitting** - files over `SPLIT_THRESHOLD_MB` are split and sent as parts
- **Group auto-delete** - bot replies in groups deleted after `AUTO_DELETE_GROUP_SECONDS`
- **TG logs channel** - set `LOG_CHANNEL_ID` for structured activity logs

---

## Heroku Deployment

1. Add buildpacks:
   ```
   heroku buildpacks:add --index 1 https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
   heroku buildpacks:add heroku/python
   ```

2. Set config vars:
   ```bash
   heroku config:set BOT_TOKEN=...
   heroku config:set ADMIN_IDS=123456789
   heroku config:set LOG_CHANNEL_ID=-1001234567890
   heroku config:set AUTO_DELETE_GROUP_SECONDS=30
   heroku config:set SPLIT_THRESHOLD_MB=2000
   ```

3. Deploy and scale:
   ```bash
   git push heroku main
   heroku ps:scale worker=1
   ```

---

## User Commands

| Command | Description |
|---|---|
| `/start` | Help message |
| `/settings` | View/edit encoding settings |
| `/setcrf <0-51>` | Set CRF quality |
| `/setres <res>` | Set resolution (720p, 1080p, 1280x720, ...) |
| `/setfont` | View custom font info |
| `/clearfont` | Remove saved custom font |

Upload any `.ttf` or `.otf` file to set it as your hardsub rendering font.

---

## Environment Variables

See `.env.example` for a full documented list.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | - | **Required** Telegram bot token |
| `ADMIN_IDS` | `` | Comma-separated admin user IDs |
| `LOG_CHANNEL_ID` | `0` | Channel/group for TG logs (0 = disabled) |
| `ALLOWED_USER_IDS` | `` | Whitelist (empty = open to all) |
| `SPLIT_THRESHOLD_MB` | `2000` | Split files larger than this |
| `SPLIT_PART_SIZE_MB` | `1950` | Size of each split part |
| `AUTO_DELETE_GROUP_SECONDS` | `30` | Group message TTL (0 = disabled) |
