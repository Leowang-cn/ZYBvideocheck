from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Union


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
MediaSource = Union[Path, str]


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    width: int
    height: int
    codec: str


def fingerprint(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(file_path: MediaSource) -> VideoInfo:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name:format=duration",
            "-of",
            "json",
            str(file_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    if not streams:
        raise ValueError("未找到视频轨道")
    stream = streams[0]
    duration = float(payload.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("无法读取有效视频时长")
    return VideoInfo(
        duration=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        codec=str(stream.get("codec_name") or "unknown"),
    )


def snapshot_seconds(duration: float) -> tuple[float, ...]:
    seconds = [min(3.0, duration), max(duration - 3.0, 0.0)]
    if duration > 6.0:
        seconds.insert(1, duration / 2.0)
    return tuple(seconds)


def create_snapshot(
    file_path: MediaSource,
    output_path: Path,
    second: float,
    input_transfer: str = "bt709",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if input_transfer not in {"bt709", "srgb"}:
        raise ValueError(f"不支持的输入传递特性：{input_transfer}")
    # Video is normally BT.709 limited-range YUV, while browsers and macOS image
    # viewers expect full-range sRGB still images. Make that conversion explicit
    # and encode losslessly so the snapshot does not inherit JPEG's ambiguous
    # YCbCr matrix/range interpretation.
    color_filter = (
        "colorspace="
        f"ispace=bt709:irange=tv:iprimaries=bt709:itrc={input_transfer}:"
        "space=bt709:range=pc:primaries=bt709:trc=srgb:"
        "format=yuv444p:dither=fsb,format=rgb24"
    )
    attempts = (
        second,
        second,
        max(second - 3.0, 0.0),
        max(second - 10.0, 0.0),
        max(second - 30.0, 0.0),
        max(second - 180.0, 0.0),
    )
    last_error = "未知错误"
    for attempt, snapshot_second in enumerate(attempts):
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{snapshot_second:.3f}",
                "-i",
                str(file_path),
                "-vf",
                color_filter,
                "-frames:v",
                "1",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size:
            return
        last_error = next(
            (line.strip() for line in reversed(result.stderr.splitlines()) if line.strip()),
            f"ffmpeg 退出码 {result.returncode}",
        )
        output_path.unlink(missing_ok=True)
        if attempt == 0:
            time.sleep(1)
    raise RuntimeError(f"无法截取 {second:.3f} 秒画面：{last_error}")


def create_proxy_video(file_path: MediaSource, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(file_path),
            "-vf",
            "scale=w='min(1920,iw)':h=-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        check=True,
        capture_output=True,
    )


def find_videos(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    return sorted(
        file_path
        for file_path in input_dir.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS
    )
