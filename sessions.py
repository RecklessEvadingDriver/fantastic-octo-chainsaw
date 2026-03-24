"""
Global in-memory session store, active-task set, state constants,
and file-extension sets shared across all handler modules.
"""

# ── In-memory session store ────────────────────────────────────────────────────
# Structure per user_id:
# {
#   "file_id"              : str   – Telegram file_id of the uploaded file
#   "file_name"            : str   – original filename
#   "local_path"           : str   – path where the file has been downloaded
#   "selected_ops"         : set   – currently toggled operations
#   "rename_to"            : str   – new filename (set after user provides it)
#   "merge_file_id"        : str   – file_id of the second file for merge
#   "merge_file_name"      : str   – filename of the second file
#   "merge_local_path"     : str   – local path of the second file
#   "streams_info"         : list  – result of ffprobe
#   "streams_to_remove"    : set   – stream indices to remove
#   "subtitle_file_path"   : str   – local path of uploaded subtitle file
#   "subtitle_file_name"   : str   – original subtitle filename
#   "watermark_path"       : str   – local path of watermark image
#   "watermark_name"       : str   – original watermark filename
#   "watermark_position"   : str   – overlay position key
#   "replace_audio_path"   : str   – local path of replacement audio
#   "trim_start"           : str   – trim start time string
#   "trim_end"             : str   – trim end time string (may be empty)
#   "extract_audio_fmt"    : str   – output audio format (mp3/aac/…)
#   "state"                : str   – current conversation state
#   "menu_message_id"      : int   – message id of the operation-menu message
# }
_sessions: dict[int, dict] = {}

# ── Active-task guard (one task per user at a time) ───────────────────────────
_active_tasks: set[int] = set()

# ── State constants ────────────────────────────────────────────────────────────
ST_SELECTING        = "selecting"
ST_WAIT_RENAME      = "wait_rename"
ST_WAIT_MERGE       = "wait_merge"
ST_WAIT_STREAM      = "wait_stream"
ST_WAIT_SUBTITLE    = "wait_subtitle"
ST_WAIT_WATERMARK   = "wait_watermark"
ST_WAIT_WMARK_POS   = "wait_wmark_pos"
ST_WAIT_REPLACE_AUD = "wait_replace_audio"
ST_WAIT_TRIM        = "wait_trim"
ST_WAIT_AUDIO_FMT   = "wait_audio_fmt"
ST_PROCESSING       = "processing"

# ── File extension sets ────────────────────────────────────────────────────────
SUBTITLE_EXTS = frozenset({".srt", ".ass", ".ssa", ".vtt"})
FONT_EXTS     = frozenset({".ttf", ".otf"})
IMAGE_EXTS    = frozenset({".png", ".jpg", ".jpeg", ".webp"})
AUDIO_EXTS    = frozenset({".mp3", ".aac", ".ogg", ".opus", ".wav", ".flac", ".m4a"})
