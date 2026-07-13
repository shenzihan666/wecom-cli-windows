"""Thin wecom-cli JSON-RPC helpers. No AI required."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEDIA_DIR = ROOT / "media"


def rpc(args: list[str]) -> dict:
    out = subprocess.check_output(["wecom-cli", *args], text=True)
    outer = json.loads(out)
    if outer.get("result", {}).get("isError"):
        raise RuntimeError(out)
    return json.loads(outer["result"]["content"][0]["text"])


def time_window(days: float = 6.0) -> tuple[str, str]:
    end = datetime.now()
    begin = end - timedelta(days=days)
    fmt = "%Y-%m-%d %H:%M:%S"
    return begin.strftime(fmt), end.strftime(fmt)


def get_userlist() -> list[dict]:
    return rpc(["contact", "get_userlist", "{}"]).get("userlist") or []


def get_messages(chatid: str, begin: str, end: str, chat_type: int = 1) -> list[dict]:
    msgs: list[dict] = []
    cursor = ""
    while True:
        payload: dict = {
            "chat_type": chat_type,
            "chatid": chatid,
            "begin_time": begin,
            "end_time": end,
        }
        if cursor:
            payload["cursor"] = cursor
        data = rpc(["msg", "get_message", json.dumps(payload, ensure_ascii=False)])
        if data.get("errcode"):
            return []
        msgs.extend(data.get("messages") or [])
        cursor = data.get("next_cursor") or ""
        if not cursor:
            break
    return msgs


def send_text(chatid: str, content: str, chat_type: int = 1) -> dict:
    payload = {
        "chat_type": chat_type,
        "chatid": chatid,
        "msgtype": "text",
        "text": {"content": content},
    }
    return rpc(["msg", "send_message", json.dumps(payload, ensure_ascii=False)])


def _amr_to_mp3(amr_path: Path) -> Path | None:
    """Convert AMR to MP3 for browser playback. Returns mp3 path or None."""
    mp3 = amr_path.with_suffix(".mp3")
    if mp3.exists() and mp3.stat().st_size > 0:
        return mp3
    try:
        subprocess.run(
            [
                "ffmpeg",
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
        return subprocess.check_output(
            [
                "ffprobe",
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
        ).strip().lower()
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
                "ffmpeg",
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


def _get_msg_media_local(media_id: str) -> tuple[str | None, str, str]:
    """Return (local_path, name, content_type). Handles CLI 'file already exists'."""
    import re

    cmd = ["wecom-cli", "msg", "get_msg_media", json.dumps({"media_id": media_id})]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
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


def fetch_media(media_id: str, msgtype: str, send_time: str = "") -> dict | None:
    """Download media to MEDIA_DIR; return {filename, content_type, size} or None.

    Voice (AMR) → MP3; video (e.g. HEVC) → H.264 MP4 for browser playback.
    media_id from WeCom often rotates; we also match by send_time cache.
    """
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    cached = _find_cached_media(msgtype, media_id, send_time)
    if cached:
        return cached

    try:
        local, name, ctype = _get_msg_media_local(media_id)
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


def preview_text(m: dict) -> str:
    mt = m.get("msgtype")
    if mt == "text":
        return (m.get("text") or {}).get("content") or ""
    return f"[{mt}]"
