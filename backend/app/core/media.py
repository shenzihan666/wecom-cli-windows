"""Media download + browser-friendly conversion (AMR->MP3, HEVC->H.264).

Bundled ./ffmpeg or ./bin binaries are preferred over PATH.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..config import settings
from .rpc import wecom_cli

MEDIA_DIR = settings.media_dir


def _tool_bin(name: str) -> str:
    """Prefer bundled ./ffmpeg or ./bin, then PATH."""
    for base in (settings.project_root / "ffmpeg", settings.project_root / "bin"):
        for candidate in (base / name, base / f"{name}.exe"):
            if candidate.is_file():
                return str(candidate)
    cmd = shutil.which(name)
    if not cmd:
        raise FileNotFoundError(f"{name} not found in ./ffmpeg, ./bin, or PATH")
    return cmd


def tool_exists(name: str) -> bool:
    """True if the media tool is available (vendored or on PATH). Used for startup checks."""
    for base in (settings.project_root / "ffmpeg", settings.project_root / "bin"):
        for candidate in (base / name, base / f"{name}.exe"):
            if candidate.is_file():
                return True
    return shutil.which(name) is not None


def _amr_to_mp3(amr_path: Path) -> Path | None:
    """Convert AMR to MP3 for browser playback. Returns mp3 path or None."""
    mp3 = amr_path.with_suffix(".mp3")
    if mp3.exists() and mp3.stat().st_size > 0:
        return mp3
    try:
        subprocess.run(
            [
                _tool_bin("ffmpeg"),
                "-y",
                "-i",
                str(amr_path),
                "-acodec",
                "libmp3lame",
                "-q:a",
                "4",
                str(mp3),
            ],
            check=True,
            capture_output=True,
        )
        return mp3 if mp3.exists() else None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _video_codec(path: Path) -> str:
    try:
        return (
            subprocess.check_output(
                [
                    _tool_bin("ffprobe"),
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                text=True,
            )
            .strip()
            .lower()
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def _video_to_h264(src: Path) -> Path | None:
    """Ensure browser-playable H.264/AAC MP4. Returns playable path or None."""
    playable = src.with_name(src.stem + "_h264.mp4")
    if playable.exists() and playable.stat().st_size > 0:
        return playable
    codec = _video_codec(src)
    if codec in ("h264", "avc1"):
        return src
    try:
        subprocess.run(
            [
                _tool_bin("ffmpeg"),
                "-y",
                "-i",
                str(src),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(playable),
            ],
            check=True,
            capture_output=True,
        )
        return playable if playable.exists() else None
    except (FileNotFoundError, subprocess.CalledProcessError):
        return src if src.exists() else None


def _media_stamp(send_time: str) -> str:
    return (send_time or "").replace(":", "-").replace(" ", "_")


def _media_result(path: Path, ctype: str = "") -> dict:
    return {
        "filename": path.name,
        "content_type": ctype,
        "size": path.stat().st_size,
        "path": str(path),
    }


def _finalize_media(path: Path, msgtype: str, ctype: str = "") -> dict | None:
    if not path.exists():
        return None
    if msgtype == "voice" and path.suffix.lower() == ".amr":
        converted = _amr_to_mp3(path)
        if converted:
            return _media_result(converted, "audio/mpeg")
    if msgtype == "voice" and path.suffix.lower() == ".mp3":
        return _media_result(path, "audio/mpeg")
    if msgtype == "video":
        converted = _video_to_h264(path)
        if converted:
            return _media_result(converted, "video/mp4")
    return _media_result(path, ctype)


def _find_cached_media(msgtype: str, media_id: str, send_time: str) -> dict | None:
    safe_id = media_id[-24:] if len(media_id) > 24 else media_id
    stamp = _media_stamp(send_time)

    if msgtype == "voice":
        for existing in MEDIA_DIR.glob(f"*_{msgtype}_{safe_id}_*.mp3"):
            return _media_result(existing, "audio/mpeg")
    if msgtype == "video":
        for existing in MEDIA_DIR.glob(f"*_{msgtype}_{safe_id}_*_h264.mp4"):
            return _media_result(existing, "video/mp4")

    for existing in MEDIA_DIR.glob(f"*_{msgtype}_{safe_id}_*"):
        if existing.name.endswith("_h264.mp4"):
            continue
        return _finalize_media(existing, msgtype)

    # media_id rotates each poll — fall back to same-second files already on disk
    if stamp:
        hits = sorted(
            MEDIA_DIR.glob(f"{stamp}_{msgtype}_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for existing in hits:
            if msgtype == "voice" and existing.suffix.lower() != ".mp3":
                got = _finalize_media(existing, msgtype)
                if got:
                    return got
                continue
            if msgtype == "video" and not existing.name.endswith("_h264.mp4"):
                got = _finalize_media(existing, msgtype)
                if got:
                    return got
                continue
            return _finalize_media(existing, msgtype)
    return None


def _get_msg_media_local(
    media_id: str, config_dir: str | Path | None = None
) -> tuple[str | None, str, str]:
    """Return (local_path, name, content_type). Handles CLI 'file already exists'."""
    cmd = [wecom_cli(), "msg", "get_msg_media", json.dumps({"media_id": media_id})]
    env = None
    if config_dir:
        env = os.environ.copy()
        env["WECOM_CLI_CONFIG_DIR"] = str(config_dir)
    try:
        out = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.STDOUT, env=env)
    except subprocess.CalledProcessError as e:
        text = e.output or str(e)
        m = re.search(r"已存在[：:]\s*(\S+)", text)
        if m and os.path.exists(m.group(1)):
            p = m.group(1)
            return p, Path(p).name, ""
        raise RuntimeError(text) from e

    outer = json.loads(out)
    if outer.get("result", {}).get("isError"):
        text = out
        try:
            text = outer["result"]["content"][0]["text"]
        except Exception:
            pass
        m = re.search(r"已存在[：:]\s*(\S+)", str(text))
        if m and os.path.exists(m.group(1)):
            p = m.group(1)
            return p, Path(p).name, ""
        raise RuntimeError(out)

    data = json.loads(outer["result"]["content"][0]["text"])
    if data.get("errcode") not in (0, None):
        m = re.search(r"已存在[：:]\s*(\S+)", data.get("errmsg") or "")
        if m and os.path.exists(m.group(1)):
            p = m.group(1)
            return p, Path(p).name, ""
        return None, "", ""
    item = data.get("media_item") or {}
    return item.get("local_path"), item.get("name") or "", item.get("content_type") or ""


def fetch_media(
    media_id: str,
    msgtype: str,
    send_time: str = "",
    config_dir: str | Path | None = None,
) -> dict | None:
    """Download media to MEDIA_DIR; return {filename, content_type, size} or None.

    Voice (AMR) -> MP3; video (e.g. HEVC) -> H.264 MP4 for browser playback.
    media_id from WeCom often rotates; we also match by send_time cache.
    """
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    cached = _find_cached_media(msgtype, media_id, send_time)
    if cached:
        return cached

    try:
        local, name, ctype = _get_msg_media_local(media_id, config_dir=config_dir)
    except Exception:
        # last resort: stamp-only cache (download failed)
        return _find_cached_media(msgtype, media_id, send_time)

    if not local or not os.path.exists(local):
        return _find_cached_media(msgtype, media_id, send_time)

    safe_id = media_id[-24:] if len(media_id) > 24 else media_id
    stamp = _media_stamp(send_time)
    base = name or Path(local).name or msgtype
    dest_name = f"{stamp}_{msgtype}_{safe_id}_{base}" if stamp else f"{msgtype}_{safe_id}_{base}"
    # also content-addressed name without rotating media_id
    stable = MEDIA_DIR / (f"{stamp}_{msgtype}_{base}" if stamp else f"{msgtype}_{base}")
    dest = MEDIA_DIR / dest_name
    if not dest.exists():
        shutil.copy2(local, dest)
    if not stable.exists():
        try:
            shutil.copy2(local, stable)
        except Exception:
            pass

    return _finalize_media(dest, msgtype, ctype)
