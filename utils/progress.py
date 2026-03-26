"""
Live processing-progress helpers.
Builds animated progress messages shown while FFmpeg operations run.
"""
import asyncio
import time

import config

# ── Human-readable operation names ────────────────────────────────────────────
OP_DISPLAY: dict[str, str] = {
    "merge":          "🔗 Merging videos",
    "remove_streams": "🎵 Removing streams",
    "remove_subs":    "📝 Removing subtitles",
    "trim":           "✂️ Trimming video",
    "replace_audio":  "🔄 Replacing audio",
    "watermark":      "🖼 Adding watermark",
    "hardsub":        "🎨 Burning subtitles",
    "compress":       "🗜 Compressing video",
    "extract_audio":  "🎶 Extracting audio",
    "rename":         "✏️ Renaming file",
}


def count_steps(ops: set, sess: dict) -> int:
    """Return the number of FFmpeg operations that will actually run."""
    count = 0
    if "merge"          in ops and sess.get("merge_local_path"):   count += 1
    if "remove_streams" in ops and sess.get("streams_to_remove"):  count += 1
    if "remove_subs"    in ops:                                     count += 1
    if "trim"           in ops and sess.get("trim_start"):          count += 1
    if "replace_audio"  in ops and sess.get("replace_audio_path"): count += 1
    if "watermark"      in ops and sess.get("watermark_path"):      count += 1
    if "hardsub"        in ops and sess.get("subtitle_file_path"):
        count += 1
    elif "compress"     in ops:
        count += 1
    if "extract_audio"  in ops:                                     count += 1
    if "rename"         in ops and sess.get("rename_to"):           count += 1
    return max(1, count)


def build_progress_text(progress: dict) -> str:
    """Format a rich progress message from the shared *progress* dict."""
    step    = progress.get("step", 0)
    total   = progress.get("total", 1)
    op_name = progress.get("op", "Starting…")
    elapsed = time.time() - progress.get("start", time.time())

    pct    = min(99, int(100 * step / max(1, total)))
    filled = pct // 5          # 20-cell bar
    bar    = "▓" * filled + "░" * (20 - filled)

    mins, secs = int(elapsed) // 60, int(elapsed) % 60

    # Estimate remaining time (only shown after ≥ 2 completed steps to avoid noise)
    if step >= 2:
        rate = elapsed / step
        remaining = max(0, int(rate * (total - step)))
        eta = f"`{remaining // 60:02d}:{remaining % 60:02d}` remaining"
    else:
        eta = "estimating…"

    spinners = ["🔄", "⚙️", "⏳", "🔃"]
    spin = spinners[int(elapsed / 2) % len(spinners)]

    return (
        f"⚙️ **Processing your video…**\n\n"
        f"`{bar}` **{pct}%**\n\n"
        f"{spin} **{op_name}**\n\n"
        f"⏱ Elapsed: `{mins:02d}:{secs:02d}`  •  {eta}\n"
        f"📋 Step: `{step} / {total}`\n\n"
        f"_— {config.BOT_BRAND}_"
    )


async def progress_updater(status_msg,
                            progress: dict,
                            stop_event: asyncio.Event) -> None:
    """Periodically edit *status_msg* with live progress info every 4 s."""
    while not stop_event.is_set():
        await asyncio.sleep(4)
        if stop_event.is_set():
            break
        try:
            await status_msg.edit_text(build_progress_text(progress))
        except Exception:
            pass  # message may already be deleted / rate-limited
