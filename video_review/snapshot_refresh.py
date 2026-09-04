from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv

from video_review.config import Settings
from video_review.cos_storage import CosUploader
from video_review.history import History, ImportRecord
from video_review.html_report import export_html
from video_review.media import MediaSource, create_snapshot
from video_review.openlist_client import OpenListClient


TARGET_SNAPSHOT_VERSION = 2


def _color_metadata(source: MediaSource) -> dict[str, str]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=color_range,color_space,color_transfer,color_primaries",
            "-of", "json", str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    streams = json.loads(result.stdout).get("streams") or []
    if not streams:
        raise ValueError("未找到视频轨道")
    return {key: str(value) for key, value in streams[0].items()}


def _input_transfer(metadata: dict[str, str]) -> str:
    expected = {
        "color_range": "tv",
        "color_space": "bt709",
        "color_transfer": "bt709",
        "color_primaries": "bt709",
    }
    if not metadata:
        return "bt709"
    mismatches = [
        f"{key}={metadata.get(key, 'unknown')}"
        for key, value in expected.items()
        if metadata.get(key) != value
    ]
    if not mismatches:
        return "bt709"
    if (
        metadata.get("color_range") == "tv"
        and metadata.get("color_space") == "bt709"
        and metadata.get("color_primaries") == "bt709"
        and metadata.get("color_transfer") == "iec61966-2-1"
    ):
        return "srgb"
    raise ValueError("非受支持的 SDR 色彩标签：" + ", ".join(mismatches))


def _backup_keys(record: ImportRecord) -> tuple[str, ...]:
    if not record.snapshot_keys:
        raise ValueError("历史记录没有截图 Object Key")
    parent = PurePosixPath(record.snapshot_keys[0]).parent
    return tuple(
        str(parent / f"snapshot-v1-{index}.jpg")
        for index in range(1, len(record.snapshot_seconds) + 1)
    )


def _snapshot_paths(record: ImportRecord, settings: Settings) -> tuple[Path, ...]:
    return tuple(
        settings.output_dir / "截图" / f"{record.video_id}_{index}_v{TARGET_SNAPSHOT_VERSION}.png"
        for index in range(1, len(record.snapshot_seconds) + 1)
    )


def _source_for_probe(
    record: ImportRecord, client: OpenListClient
) -> tuple[MediaSource, bool]:
    local_path = Path(record.source_path)
    if local_path.is_file():
        return local_path, True
    return client.download_url(record.source_path), False


def refresh_record(
    record: ImportRecord,
    settings: Settings,
    client: OpenListClient,
    uploader: CosUploader,
    history: History,
) -> None:
    probe_source, is_local = _source_for_probe(record, client)
    input_transfer = _input_transfer(_color_metadata(probe_source))
    paths = _snapshot_paths(record, settings)
    keys = record.snapshot_keys
    backup_keys = _backup_keys(record)
    old_paths = tuple(Path(path) for path in record.snapshot_paths)
    missing_old_paths = [str(path) for path in old_paths if not path.is_file()]
    if missing_old_paths:
        raise FileNotFoundError("本地旧截图缺失：" + ", ".join(missing_old_paths))
    for path, second in zip(paths, record.snapshot_seconds):
        source = probe_source if is_local else client.download_url(record.source_path)
        create_snapshot(source, path, second, input_transfer=input_transfer)
    for old_path, backup_key in zip(old_paths, backup_keys):
        uploader.upload_with_metadata(
            old_path,
            backup_key,
            content_type="image/jpeg",
            cache_control="private, max-age=0, no-cache",
        )
    try:
        for path, key in zip(paths, keys):
            uploader.upload_with_metadata(
                path,
                key,
                content_type="image/png",
                cache_control="no-cache, max-age=0, must-revalidate",
            )
    except Exception:
        for old_path, key in zip(old_paths, keys):
            uploader.upload_with_metadata(
                old_path,
                key,
                content_type="image/jpeg",
                cache_control="no-cache, max-age=0, must-revalidate",
            )
        raise
    history.update_snapshots(
        record.video_id,
        tuple(str(path) for path in paths),
        keys,
        TARGET_SNAPSHOT_VERSION,
    )


def run_refresh(
    settings: Settings,
    uploader: CosUploader | None,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    history = History(settings.data_dir / "import-history.sqlite")
    client = OpenListClient(settings.openlist_url, settings.openlist_token)
    completed = 0
    errors: list[str] = []
    try:
        candidates = history.snapshot_refresh_candidates(TARGET_SNAPSHOT_VERSION)
        if limit is not None:
            candidates = candidates[:limit]
        total = len(candidates)
        for index, record in enumerate(candidates, start=1):
            print(f"[{index}/{total}] {record.file_name}", flush=True)
            try:
                if dry_run:
                    source, _ = _source_for_probe(record, client)
                    _input_transfer(_color_metadata(source))
                else:
                    if uploader is None:
                        raise AssertionError("迁移模式缺少 COS 上传器")
                    refresh_record(record, settings, client, uploader, history)
                completed += 1
            except Exception as error:
                message = f"{record.file_name}: {error}"
                errors.append(message)
                print(f"  失败：{error}", file=sys.stderr, flush=True)
        if not dry_run and completed:
            export_html(
                history.ready_records(),
                settings,
                "历史截图刷新",
                settings.output_dir / "视频走查.html",
            )
        return completed, errors
    finally:
        history.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="将历史 JPEG 截图刷新为 sRGB PNG")
    parser.add_argument("--limit", type=int, default=None, help="最多处理的视频数")
    parser.add_argument("--dry-run", action="store_true", help="只检查原片和色彩信息")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=True)
    settings = Settings.from_env(root)
    if not settings.openlist_url or not settings.openlist_token:
        print("OPENLIST_URL 或 OPENLIST_TOKEN 未配置", file=sys.stderr)
        return 1
    if args.dry_run:
        uploader = None
    else:
        uploader = CosUploader(settings)
    completed, errors = run_refresh(settings, uploader, args.limit, args.dry_run)
    print(f"完成 {completed} 条，失败 {len(errors)} 条")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
