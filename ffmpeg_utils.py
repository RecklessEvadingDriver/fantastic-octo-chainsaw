"""
FFmpeg helper functions.

All functions are synchronous (run via asyncio.to_thread in the bot layer).
Every function returns the output path on success and raises RuntimeError
containing the relevant portion of ffmpeg/ffprobe stderr on failure.
"""
import glob as _glob
import json as _json
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Subprocess runner ──────────────────────────────────────────────────────────

def _run(cmd: list[str]) -> None:
    """Run *cmd*, raise RuntimeError with stderr context on non-zero exit."""
    logger.debug("ffmpeg cmd: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr
        # Keep both beginning and end so key errors are never hidden
        if len(stderr) > 4000:
            stderr = stderr[:2000] + "\n…\n" + stderr[-2000:]
        raise RuntimeError(stderr)


def _ffmpeg_escape(path: str) -> str:
    """
    Escape a filesystem path for use inside an FFmpeg filter-graph string
    that is wrapped in single quotes.
    """
    path = path.replace("\\", "/")
    for ch in ("'", ":", ",", "[", "]", ";"):
        path = path.replace(ch, "\\" + ch)
    return path


# ── Compress ───────────────────────────────────────────────────────────────────

def compress_video(
    input_path: str,
    output_path: str,
    crf: int,
    preset: str,
    codec: str,
    resolution: str,
) -> str:
    """
    Re-encode *input_path* with the given quality settings.

    Parameters
    ----------
    resolution : "original" or "WxH" (e.g. "1280x720")
    """
    cmd = ["ffmpeg", "-y", "-i", input_path,
           "-c:v", codec, "-crf", str(crf), "-preset", preset]

    if resolution and resolution.lower() != "original":
        parts = resolution.split("x")
        if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
            raise ValueError(
                f"Invalid resolution {resolution!r}. "
                "Expected 'WxH' (e.g. '1280x720') or 'original'."
            )
        w, h = parts
        cmd += ["-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease"]

    cmd += ["-c:a", "copy", "-c:s", "copy", output_path]
    _run(cmd)
    return output_path


# ── Remove subtitles ───────────────────────────────────────────────────────────

def remove_subtitles(input_path: str, output_path: str) -> str:
    """Strip every subtitle stream from *input_path*."""
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-map", "0", "-map", "-0:s",
        "-c", "copy", output_path,
    ])
    return output_path


# ── Remove selected streams ────────────────────────────────────────────────────

def remove_streams(
    input_path: str,
    output_path: str,
    stream_indices: list[int],
) -> str:
    """Remove streams at the given 0-based global indices."""
    cmd = ["ffmpeg", "-y", "-i", input_path, "-map", "0"]
    for idx in stream_indices:
        cmd += ["-map", f"-0:{idx}"]
    cmd += ["-c", "copy", output_path]
    _run(cmd)
    return output_path


# ── Merge two files ────────────────────────────────────────────────────────────

def merge_files(
    input_path1: str,
    input_path2: str,
    output_path: str,
) -> str:
    """Concatenate two video files without re-encoding."""
    list_file = output_path + ".concat_list.txt"
    try:
        with open(list_file, "w") as f:
            f.write(f"file '{os.path.abspath(input_path1)}'\n")
            f.write(f"file '{os.path.abspath(input_path2)}'\n")
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path,
        ])
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
    return output_path


# ── Hardsub / MLRE ─────────────────────────────────────────────────────────────

def hardsub_video(
    input_path: str,
    output_path: str,
    subtitle_path: str,
    font_path: str | None = None,
    crf: int = 23,
    preset: str = "medium",
    codec: str = "libx264",
) -> str:
    """
    Burn (hardsub) subtitles into the video — the MLRE operation.

    Supports .srt, .ass, .ssa subtitle formats.  When *font_path* is provided
    the custom font is used for rendering.  The video is re-encoded with the
    supplied quality settings.
    """
    ext = Path(subtitle_path).suffix.lower()
    esc_sub = _ffmpeg_escape(subtitle_path)

    if ext in (".ass", ".ssa"):
        if font_path:
            font_dir = _ffmpeg_escape(str(Path(font_path).parent))
            vf = f"ass='{esc_sub}':fontsdir='{font_dir}'"
        else:
            vf = f"ass='{esc_sub}'"
    else:
        if font_path:
            font_name = _ffmpeg_escape(Path(font_path).stem)
            font_dir  = _ffmpeg_escape(str(Path(font_path).parent))
            vf = (
                f"subtitles='{esc_sub}':fontsdir='{font_dir}':"
                f"force_style='Fontname={font_name}'"
            )
        else:
            vf = f"subtitles='{esc_sub}'"

    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", codec, "-crf", str(crf), "-preset", preset,
        "-c:a", "copy", output_path,
    ])
    return output_path


# ── Trim ───────────────────────────────────────────────────────────────────────

def trim_video(
    input_path: str,
    output_path: str,
    start_time: str,
    end_time: str = "",
) -> str:
    """
    Trim a video to [start_time, end_time].

    Times are in HH:MM:SS, MM:SS, or plain seconds format.
    *end_time* is optional; omit to keep everything from start to EOF.
    """
    cmd = ["ffmpeg", "-y", "-ss", start_time, "-i", input_path]
    if end_time:
        cmd += ["-to", end_time]
    cmd += ["-c", "copy", output_path]
    _run(cmd)
    return output_path


# ── Extract audio ──────────────────────────────────────────────────────────────

def extract_audio(
    input_path: str,
    output_path: str,
    fmt: str = "mp3",
) -> str:
    """
    Extract the audio track from a video as a standalone audio file.

    Parameters
    ----------
    fmt : "mp3" | "aac" | "opus" | "flac" | "wav"
    """
    codec_map = {
        "mp3":  "libmp3lame",
        "aac":  "aac",
        "opus": "libopus",
        "flac": "flac",
        "wav":  "pcm_s16le",
    }
    acodec = codec_map.get(fmt.lower(), "libmp3lame")
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-c:a", acodec,
        output_path,
    ])
    return output_path


# ── Replace audio ──────────────────────────────────────────────────────────────

def replace_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
) -> str:
    """Replace the audio of *video_path* with *audio_path*."""
    _run([
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        output_path,
    ])
    return output_path


# ── Add watermark ──────────────────────────────────────────────────────────────

_WATERMARK_POSITIONS: dict[str, str] = {
    "topleft":     "10:10",
    "topright":    "W-w-10:10",
    "bottomleft":  "10:H-h-10",
    "bottomright": "W-w-10:H-h-10",
    "center":      "(W-w)/2:(H-h)/2",
}


def add_watermark(
    input_path: str,
    output_path: str,
    watermark_path: str,
    position: str = "bottomright",
    opacity: float = 0.8,
) -> str:
    """
    Overlay a PNG/JPG watermark image onto the video.

    Parameters
    ----------
    position : one of topleft / topright / bottomleft / bottomright / center
    opacity  : 0.0 (transparent) – 1.0 (opaque)
    """
    pos = _WATERMARK_POSITIONS.get(position, _WATERMARK_POSITIONS["bottomright"])
    opacity = max(0.0, min(1.0, opacity))
    _run([
        "ffmpeg", "-y",
        "-i", input_path,
        "-i", watermark_path,
        "-filter_complex",
        f"[1:v]format=rgba,colorchannelmixer=aa={opacity}[wm];"
        f"[0:v][wm]overlay={pos}[out]",
        "-map", "[out]",
        "-map", "0:a?",
        "-c:a", "copy",
        output_path,
    ])
    return output_path


# ── Change speed ───────────────────────────────────────────────────────────────

def change_speed(
    input_path: str,
    output_path: str,
    speed: float,
) -> str:
    """
    Change video playback speed.

    Parameters
    ----------
    speed : multiplier – 0.5 = half speed, 2.0 = double speed (range 0.25–4.0)
    """
    speed = max(0.25, min(4.0, speed))
    video_filter = f"setpts={1.0 / speed}*PTS"

    # atempo supports 0.5–2.0; chain two filters for values outside that range
    if speed < 0.5:
        audio_filter = f"atempo=0.5,atempo={speed / 0.5:.4f}"
    elif speed > 2.0:
        audio_filter = f"atempo=2.0,atempo={speed / 2.0:.4f}"
    else:
        audio_filter = f"atempo={speed:.4f}"

    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex",
        f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]",
        "-map", "[v]", "-map", "[a]",
        output_path,
    ])
    return output_path


# ── Split large file ───────────────────────────────────────────────────────────

def split_video(
    input_path: str,
    output_dir: str,
    prefix: str,
    part_size_mb: int = 1950,
) -> list[str]:
    """
    Split a large video file into parts of at most *part_size_mb* MB each.

    Uses FFmpeg's segment muxer so each part is independently playable.
    Returns a sorted list of created file paths.
    """
    ext = Path(input_path).suffix or ".mp4"
    safe_prefix = "".join(c for c in prefix if c.isalnum() or c in "_-")
    pattern = os.path.join(output_dir, f"{safe_prefix}_part%03d{ext}")
    segment_bytes = part_size_mb * 1024 * 1024

    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-c", "copy",
        "-f", "segment",
        "-segment_size", str(segment_bytes),
        "-reset_timestamps", "1",
        pattern,
    ])

    parts = sorted(_glob.glob(os.path.join(output_dir, f"{safe_prefix}_part*{ext}")))
    return parts


# ── Probe streams ──────────────────────────────────────────────────────────────

def probe_streams(input_path: str) -> list[dict]:
    """
    Return stream descriptors for *input_path* via ffprobe.

    Each dict has at least: index, codec_type, codec_name, tags (dict).
    Returns an empty list on failure.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", input_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    data = _json.loads(result.stdout or "{}")
    return data.get("streams", [])


def probe_format(input_path: str) -> dict:
    """
    Return format/container info for *input_path* via ffprobe.

    Useful for reading duration and file size.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", input_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {}
    data = _json.loads(result.stdout or "{}")
    return data.get("format", {})

