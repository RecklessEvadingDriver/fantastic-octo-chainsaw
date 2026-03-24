"""
Inline-keyboard builders for the multi-select operation menu, settings panels,
and admin operations.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── Emoji markers ──────────────────────────────────────────────────────────────
_ON  = "✅"
_OFF = "⬜"


def _tick(flag: bool) -> str:
    return _ON if flag else _OFF


# ── Operation definitions ──────────────────────────────────────────────────────

OPERATIONS: dict[str, str] = {
    "compress":       "🗜 Compress",
    "remove_subs":    "📝 Remove Subtitles",
    "remove_streams": "🎵 Remove Streams",
    "hardsub":        "🎨 Hardsub (Burn Subs)",
    "trim":           "✂️ Trim",
    "extract_audio":  "🎶 Extract Audio",
    "replace_audio":  "🔄 Replace Audio",
    "watermark":      "🖼 Watermark",
    "rename":         "✏️ Rename",
    "merge":          "🔗 Merge",
}


# ── Operation menu ─────────────────────────────────────────────────────────────

def operation_menu(selected: set[str]) -> InlineKeyboardMarkup:
    """
    Build the main multi-select operation menu.

    *selected* is the set of currently toggled operation keys.
    """
    rows = []
    op_items = list(OPERATIONS.items())
    for i in range(0, len(op_items), 2):
        row = []
        for key, label in op_items[i : i + 2]:
            row.append(
                InlineKeyboardButton(
                    f"{_tick(key in selected)} {label}",
                    callback_data=f"op:{key}",
                )
            )
        rows.append(row)

    rows.append([
        InlineKeyboardButton("▶️ Process Now", callback_data="process"),
        InlineKeyboardButton("❌ Cancel",       callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)


# ── Settings menu ──────────────────────────────────────────────────────────────

def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔢 Set CRF",       callback_data="cfg:crf"),
            InlineKeyboardButton("📐 Resolution",     callback_data="cfg:resolution"),
        ],
        [
            InlineKeyboardButton("⚡ Set Preset",     callback_data="cfg:preset"),
            InlineKeyboardButton("🎬 Set Codec",      callback_data="cfg:codec"),
        ],
        [InlineKeyboardButton("🎨 Manage Font",       callback_data="cfg:font")],
        [InlineKeyboardButton("« Back",               callback_data="cfg:back")],
    ])


def preset_menu() -> InlineKeyboardMarkup:
    presets = [
        "ultrafast", "superfast", "veryfast", "faster",
        "fast", "medium", "slow", "slower", "veryslow",
    ]
    rows = [
        [InlineKeyboardButton(p, callback_data=f"set:preset:{p}") for p in presets[i:i+3]]
        for i in range(0, len(presets), 3)
    ]
    rows.append([InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")])
    return InlineKeyboardMarkup(rows)


def resolution_menu() -> InlineKeyboardMarkup:
    options = ["original", "4k", "2k", "1080p", "720p", "480p", "360p"]
    rows = [
        [InlineKeyboardButton(o, callback_data=f"set:resolution:{o}") for o in options[i:i+3]]
        for i in range(0, len(options), 3)
    ]
    rows.append([InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")])
    return InlineKeyboardMarkup(rows)


def codec_menu() -> InlineKeyboardMarkup:
    codecs = ["libx264", "libx265", "libvpx-vp9"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(c, callback_data=f"set:codec:{c}") for c in codecs],
        [InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")],
    ])


# ── Stream selection menu ──────────────────────────────────────────────────────

def stream_selection_menu(
    streams: list[dict],
    selected_indices: set[int],
) -> InlineKeyboardMarkup:
    """Toggle-list of streams; selected = will be removed."""
    rows = []
    for s in streams:
        idx        = s["index"]
        ctype      = s.get("codec_type", "unknown").upper()
        cname      = s.get("codec_name", "?")
        lang       = s.get("tags", {}).get("language", "")
        title      = s.get("tags", {}).get("title", "")
        parts      = [f"[{idx}]", ctype, cname]
        if lang:
            parts.append(lang)
        if title:
            parts.append(f'"{title}"')
        rows.append([
            InlineKeyboardButton(
                f"{_tick(idx in selected_indices)} {' '.join(parts)}",
                callback_data=f"stream:{idx}",
            )
        ])

    rows.append([
        InlineKeyboardButton("✅ Confirm", callback_data="stream:confirm"),
        InlineKeyboardButton("❌ Cancel",  callback_data="stream:cancel"),
    ])
    return InlineKeyboardMarkup(rows)


# ── Audio format menu (for Extract Audio) ─────────────────────────────────────

def audio_format_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 MP3",  callback_data="audioformat:mp3"),
            InlineKeyboardButton("🎵 AAC",  callback_data="audioformat:aac"),
            InlineKeyboardButton("🎵 OPUS", callback_data="audioformat:opus"),
        ],
        [
            InlineKeyboardButton("🎵 FLAC", callback_data="audioformat:flac"),
            InlineKeyboardButton("🎵 WAV",  callback_data="audioformat:wav"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])


# ── Watermark position menu ────────────────────────────────────────────────────

def watermark_position_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↖ Top-Left",    callback_data="wmpos:topleft"),
            InlineKeyboardButton("↗ Top-Right",   callback_data="wmpos:topright"),
        ],
        [
            InlineKeyboardButton("↙ Bot-Left",    callback_data="wmpos:bottomleft"),
            InlineKeyboardButton("↘ Bot-Right",   callback_data="wmpos:bottomright"),
        ],
        [InlineKeyboardButton("⊙ Center",         callback_data="wmpos:center")],
        [InlineKeyboardButton("❌ Cancel",         callback_data="cancel")],
    ])

