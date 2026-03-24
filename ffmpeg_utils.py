"""
FFmpeg helper functions.

All functions are synchronous (run via asyncio.to_thread in the bot layer).
Every function returns the path of the output file on success and raises
RuntimeError with the ffmpeg stderr on failure.
"""
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> None:
    """Run *cmd*, raise RuntimeError with stderr on non-zero exit."""
    logger.debug("ffmpeg cmd: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr
        # Preserve both beginning and end of stderr to retain key error context
        if len(stderr) > 4000:
            stderr = stderr[:2000] + "\n…\n" + stderr[-2000:]
        raise RuntimeError(stderr)


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
    cmd = ["ffmpeg", "-y", "-i", input_path]

    # Video codec + quality
    cmd += ["-c:v", codec, "-crf", str(crf), "-preset", preset]

    # Scale only when a specific resolution is requested
    if resolution and resolution.lower() != "original":
        parts = resolution.split("x")
        if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
            raise ValueError(
                f"Invalid resolution {resolution!r}. Expected 'WxH' (e.g. '1280x720') or 'original'."
            )
        w, h = parts
        # Use scale with force_original_aspect_ratio to avoid stretching
        cmd += ["-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease"]

    # Copy all audio streams as-is
    cmd += ["-c:a", "copy"]

    # Copy subtitle streams as-is (they are handled separately)
    cmd += ["-c:s", "copy"]

    # Allow any input including PreDVD / low-quality sources — no restrictions
    cmd += [output_path]
    _run(cmd)
    return output_path


# ── Remove subtitles ───────────────────────────────────────────────────────────

def remove_subtitles(input_path: str, output_path: str) -> str:
    """Strip every subtitle stream from *input_path*."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-map", "0",           # start with all streams
        "-map", "-0:s",        # remove all subtitle streams
        "-c", "copy",
        output_path,
    ]
    _run(cmd)
    return output_path


# ── Remove selected streams ────────────────────────────────────────────────────

def remove_streams(
    input_path: str,
    output_path: str,
    stream_indices: list[int],
) -> str:
    """
    Remove the streams at the given *stream_indices* (0-based global indices
    as reported by probe_streams).
    """
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
    """
    Merge (concatenate) two video files into one.

    Uses the concat demuxer so that the second file is appended after the
    first without re-encoding.
    """
    list_file = output_path + ".concat_list.txt"
    try:
        with open(list_file, "w") as f:
            f.write(f"file '{os.path.abspath(input_path1)}'\n")
            f.write(f"file '{os.path.abspath(input_path2)}'\n")
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]
        _run(cmd)
    finally:
        if os.path.exists(list_file):
            os.remove(list_file)
    return output_path


# ── Probe streams ──────────────────────────────────────────────────────────────

def probe_streams(input_path: str) -> list[dict]:
    """
    Return a list of stream descriptors for *input_path*.

    Each dict has at least:  index, codec_type, codec_name, tags (dict).
    """
    import json as _json

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    data = _json.loads(result.stdout or "{}")
    return data.get("streams", [])
