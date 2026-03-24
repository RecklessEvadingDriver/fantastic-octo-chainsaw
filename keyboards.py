"""
Inline-keyboard builders for the multi-select operation menu and settings panels.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── Emoji markers ──────────────────────────────────────────────────────────────
_ON = "✅"
_OFF = "⬜"


def _tick(flag: bool) -> str:
    return _ON if flag else _OFF


# ── Operation menu ─────────────────────────────────────────────────────────────

OPERATIONS = {
    "compress":        "🗜 Compress",
    "remove_subs":     "📝 Remove Subtitles",
    "remove_streams":  "🎵 Remove Streams",
    "hardsub":         "🎨 Hardsub (Burn Subs)",
    "rename":          "✏️ Rename",
    "merge":           "🔗 Merge",
}


def operation_menu(selected: set[str]) -> InlineKeyboardMarkup:
    """
    Build the main multi-select operation menu.

    *selected* is the set of currently toggled operation keys.
    """
    rows = []
    op_items = list(OPERATIONS.items())
    # Two buttons per row
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

    # Action row
    rows.append(
        [
            InlineKeyboardButton("▶️ Process Now", callback_data="process"),
            InlineKeyboardButton("❌ Cancel",       callback_data="cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)


# ── Settings menu ──────────────────────────────────────────────────────────────

def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔢 Set CRF",        callback_data="cfg:crf"),
                InlineKeyboardButton("📐 Set Resolution",  callback_data="cfg:resolution"),
            ],
            [
                InlineKeyboardButton("⚡ Set Preset",      callback_data="cfg:preset"),
                InlineKeyboardButton("🎬 Set Codec",       callback_data="cfg:codec"),
            ],
            [InlineKeyboardButton("🎨 Manage Font",        callback_data="cfg:font")],
            [InlineKeyboardButton("« Back",                callback_data="cfg:back")],
        ]
    )


def preset_menu() -> InlineKeyboardMarkup:
    presets = [
        "ultrafast", "superfast", "veryfast", "faster",
        "fast", "medium", "slow", "slower", "veryslow",
    ]
    rows = []
    for i in range(0, len(presets), 3):
        rows.append(
            [
                InlineKeyboardButton(p, callback_data=f"set:preset:{p}")
                for p in presets[i : i + 3]
            ]
        )
    rows.append([InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")])
    return InlineKeyboardMarkup(rows)


def resolution_menu() -> InlineKeyboardMarkup:
    options = ["original", "4k", "2k", "1080p", "720p", "480p", "360p"]
    rows = []
    for i in range(0, len(options), 3):
        rows.append(
            [
                InlineKeyboardButton(o, callback_data=f"set:resolution:{o}")
                for o in options[i : i + 3]
            ]
        )
    rows.append([InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")])
    return InlineKeyboardMarkup(rows)


def codec_menu() -> InlineKeyboardMarkup:
    codecs = ["libx264", "libx265", "libvpx-vp9"]
    rows = [
        [InlineKeyboardButton(c, callback_data=f"set:codec:{c}") for c in codecs],
        [InlineKeyboardButton("« Back", callback_data="cfg:back_to_settings")],
    ]
    return InlineKeyboardMarkup(rows)


# ── Stream selection menu ──────────────────────────────────────────────────────

def stream_selection_menu(
    streams: list[dict],
    selected_indices: set[int],
) -> InlineKeyboardMarkup:
    """
    Show each detected stream as a toggleable button.
    Streams that are selected will be removed.
    """
    rows = []
    for s in streams:
        idx = s["index"]
        codec_type = s.get("codec_type", "unknown")
        codec_name = s.get("codec_name", "?")
        lang = s.get("tags", {}).get("language", "")
        title = s.get("tags", {}).get("title", "")
        label_parts = [f"[{idx}]", codec_type.upper(), codec_name]
        if lang:
            label_parts.append(lang)
        if title:
            label_parts.append(f'"{title}"')
        label = " ".join(label_parts)
        rows.append(
            [
                InlineKeyboardButton(
                    f"{_tick(idx in selected_indices)} {label}",
                    callback_data=f"stream:{idx}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton("✅ Confirm Selection", callback_data="stream:confirm"),
            InlineKeyboardButton("❌ Cancel",            callback_data="stream:cancel"),
        ]
    )
    return InlineKeyboardMarkup(rows)
