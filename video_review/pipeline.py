from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from video_review.config import Settings
from video_review.cos_storage import Uploader
from video_review.html_report import export_html
from video_review.history import History, ImportRecord
from video_review.media import (
    create_snapshot,
    find_videos,
    fingerprint,
    probe_video,
    snapshot_seconds,
)
from video_review.openlist_client import OpenListClient, OpenListFile
from video_review.server_client import push_records


def run(settings: Settings, uploader: Uploader, batch: str) -> tuple[Path | None, list[str]]:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    history = History(settings.data_dir / "import-history.sqlite")
    errors: list[str] = []
    try:
        if settings.openlist_path:
            if not settings.openlist_url or not settings.openlist_token:
                raise ValueError("已配置 OPENLIST_PATH，但 OPENLIST_URL 或 OPENLIST_TOKEN 为空")
            if not settings.effective_baidu_pan_mount_path():
                raise ValueError("无法从 OPENLIST_PATH 推断百度网盘挂载点")
            client = OpenListClient(settings.openlist_url, settings.openlist_token)
            for remote_file in client.find_videos(settings.openlist_path):
                try:
                    _process_openlist_video(remote_file, client, settings, uploader, history)
                except Exception as error:
                    errors.append(f"{remote_file.name}: {error}")

        for file_path in find_videos(settings.input_dir):
            try:
                _process_video(file_path, settings, uploader, history)
            except Exception as error:
                errors.append(f"{file_path.name}: {error}")

        records = history.pending_export()
        if not records:
            if settings.server_url:
                push_records(history.ready_records(), settings)
            return None, errors
        history.assign_batch([record.video_id for record in records], batch)
        ready_records = history.ready_records()
        if settings.server_url:
            push_records(ready_records, settings)
        output_path = settings.output_dir / "视频走查.html"
        export_html(ready_records, settings, batch, output_path)
        history.mark_exported([record.video_id for record in records])
        return output_path, errors
    finally:
        history.close()


def _process_openlist_video(
    remote_file: OpenListFile,
    client: OpenListClient,
    settings: Settings,
    uploader: Uploader,
    history: History,
) -> None:
    identity = f"openlist\0{remote_file.path}\0{remote_file.size}\0{remote_file.modified}"
    video_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    record = history.get(video_id)
    if record and record.exported:
        return

    if record is None:
        source_url = client.download_url(remote_file.path)
        info = probe_video(source_url)
        seconds = snapshot_seconds(info.duration)
        snapshot_paths = tuple(
            settings.output_dir / "截图" / f"{video_id}_{index}.jpg"
            for index in range(1, len(seconds) + 1)
        )
        for snapshot_path, second in zip(snapshot_paths, seconds):
            create_snapshot(client.download_url(remote_file.path), snapshot_path, second)
        week = datetime.now().strftime("%G-W%V")
        record = ImportRecord(
            video_id=video_id,
            source_path=remote_file.path,
            file_name=remote_file.name,
            file_size=remote_file.size,
            duration=info.duration,
            width=info.width,
            height=info.height,
            snapshot_seconds=seconds,
            snapshot_paths=tuple(str(path) for path in snapshot_paths),
            video_key=client.baidu_pan_page_url(
                remote_file.path, settings.effective_baidu_pan_mount_path()
            ),
            snapshot_keys=tuple(
                settings.object_key(f"{week}/{video_id}/snapshot-{index}.jpg")
                for index in range(1, len(seconds) + 1)
            ),
            video_uploaded=True,
            snapshot_uploaded=False,
            exported=False,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        history.save(record)

    if not record.snapshot_uploaded:
        for snapshot_path, snapshot_key in zip(record.snapshot_paths, record.snapshot_keys):
            uploader.upload(Path(snapshot_path), snapshot_key)
        record = replace(record, snapshot_uploaded=True)
        history.save(record)


def _process_video(
    file_path: Path, settings: Settings, uploader: Uploader, history: History
) -> None:
    video_id = fingerprint(file_path)
    record = history.get(video_id)
    if record and record.exported:
        return

    if record is None:
        info = probe_video(file_path)
        seconds = snapshot_seconds(info.duration)
        snapshot_paths = tuple(
            settings.output_dir / "截图" / f"{video_id}_{index}.jpg"
            for index in range(1, len(seconds) + 1)
        )
        for snapshot_path, second in zip(snapshot_paths, seconds):
            create_snapshot(file_path, snapshot_path, second)
        week = datetime.now().strftime("%G-W%V")
        extension = file_path.suffix.lower().lstrip(".") or "mp4"
        record = ImportRecord(
            video_id=video_id,
            source_path=str(file_path),
            file_name=file_path.name,
            file_size=file_path.stat().st_size,
            duration=info.duration,
            width=info.width,
            height=info.height,
            snapshot_seconds=seconds,
            snapshot_paths=tuple(str(path) for path in snapshot_paths),
            video_key=settings.object_key(f"{week}/{video_id}/video.{extension}"),
            snapshot_keys=tuple(
                settings.object_key(f"{week}/{video_id}/snapshot-{index}.jpg")
                for index in range(1, len(seconds) + 1)
            ),
            video_uploaded=False,
            snapshot_uploaded=False,
            exported=False,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        history.save(record)

    if not record.video_uploaded:
        uploader.upload(file_path, record.video_key)
        record = replace(record, video_uploaded=True)
        history.save(record)
    if not record.snapshot_uploaded:
        for snapshot_path, snapshot_key in zip(record.snapshot_paths, record.snapshot_keys):
            uploader.upload(Path(snapshot_path), snapshot_key)
        record = replace(record, snapshot_uploaded=True)
        history.save(record)
