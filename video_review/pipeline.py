from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

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


def run(
    settings: Settings,
    uploader: Uploader,
    batch: str,
    progress: Optional[Callable[[str], None]] = None,
) -> tuple[Path | None, list[str]]:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    history = History(settings.data_dir / "import-history.sqlite")
    errors: list[str] = []
    try:
        remote_files: list[OpenListFile] = []
        if settings.openlist_path:
            if not settings.openlist_url or not settings.openlist_token:
                raise ValueError("已配置 OPENLIST_PATH，但 OPENLIST_URL 或 OPENLIST_TOKEN 为空")
            if not settings.effective_baidu_pan_mount_path():
                raise ValueError("无法从 OPENLIST_PATH 推断百度网盘挂载点")
            client = OpenListClient(settings.openlist_url, settings.openlist_token)
            remote_files = client.find_videos(settings.openlist_path)
            local_files = find_videos(settings.input_dir)
        else:
            local_files = find_videos(settings.input_dir)

        total = len(remote_files) + len(local_files)
        _report(progress, f"共发现 {total} 个视频，开始处理。")
        completed = 0

        if remote_files:
            for remote_file in remote_files:
                completed += 1
                _report(progress, f"[{completed}/{total}] 开始：{remote_file.name}")
                try:
                    _process_openlist_video(
                        remote_file, client, settings, uploader, history,
                        lambda message: _report(progress, f"[{completed}/{total}] {message}"),
                    )
                    _report(progress, f"[{completed}/{total}] 完成：{remote_file.name}")
                except Exception as error:
                    errors.append(f"{remote_file.name}: {error}")
                    _report(progress, f"[{completed}/{total}] 失败：{remote_file.name}：{error}")

        for file_path in local_files:
            completed += 1
            _report(progress, f"[{completed}/{total}] 开始：{file_path.name}")
            try:
                _process_video(
                    file_path, settings, uploader, history,
                    lambda message: _report(progress, f"[{completed}/{total}] {message}"),
                )
                _report(progress, f"[{completed}/{total}] 完成：{file_path.name}")
            except Exception as error:
                errors.append(f"{file_path.name}: {error}")
                _report(progress, f"[{completed}/{total}] 失败：{file_path.name}：{error}")

        if settings.snapshots_only:
            records = history.snapshot_records()
            if not records:
                return None, errors
            history.assign_batch([record.video_id for record in records], batch)
            records = history.snapshot_records()
            if settings.server_url:
                mount = settings.effective_baidu_pan_mount_path().rstrip("/")
                sync_records = [
                    record for record in records
                    if record.video_uploaded
                    or (mount and record.source_path.startswith(f"{mount}/"))
                ]
                if sync_records:
                    _report(progress, f"同步 {len(sync_records)} 条记录到服务器")
                    push_records(sync_records, settings)
            output_path = settings.output_dir / "视频走查.html"
            _report(progress, "生成 HTML 报告")
            export_html(records, settings, batch, output_path)
            return output_path, errors

        records = history.pending_export()
        if not records:
            if settings.server_url:
                _report(progress, "同步已有记录到服务器")
                push_records(history.ready_records(), settings)
            return None, errors
        history.assign_batch([record.video_id for record in records], batch)
        ready_records = history.ready_records()
        if settings.server_url:
            _report(progress, f"同步 {len(ready_records)} 条记录到服务器")
            push_records(ready_records, settings)
        output_path = settings.output_dir / "视频走查.html"
        _report(progress, "生成 HTML 报告")
        export_html(ready_records, settings, batch, output_path)
        history.mark_exported([record.video_id for record in records])
        return output_path, errors
    finally:
        history.close()


def _report(progress: Optional[Callable[[str], None]], message: str) -> None:
    if progress is not None:
        progress(message)


def _process_openlist_video(
    remote_file: OpenListFile,
    client: OpenListClient,
    settings: Settings,
    uploader: Uploader,
    history: History,
    progress: Optional[Callable[[str], None]] = None,
) -> None:
    identity = f"openlist\0{remote_file.path}\0{remote_file.size}\0{remote_file.modified}"
    video_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    record = history.get(video_id)
    if record and record.exported:
        return

    if record is None:
        _report(progress, "读取视频信息")
        source_url = client.download_url(remote_file.path)
        info = probe_video(source_url)
        seconds = snapshot_seconds(info.duration)
        snapshot_paths = tuple(
            settings.output_dir / "截图" / f"{video_id}_{index}.png"
            for index in range(1, len(seconds) + 1)
        )
        for index, (snapshot_path, second) in enumerate(zip(snapshot_paths, seconds), 1):
            _report(progress, f"截取截图 {index}/{len(snapshot_paths)}")
            create_snapshot(client.download_url(remote_file.path), snapshot_path, second)
        week = datetime.now().strftime("%G-W%V")
        extension = Path(remote_file.name).suffix.lower().lstrip(".") or "mp4"
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
            video_key=settings.object_key(f"{week}/{video_id}/video.{extension}"),
            snapshot_keys=tuple(
                settings.object_key(f"{week}/{video_id}/snapshot-{index}.png")
                for index in range(1, len(seconds) + 1)
            ),
            video_uploaded=False,
            snapshot_uploaded=False,
            exported=False,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            snapshot_version=2,
        )
        history.save(record)

    if not record.video_uploaded and not settings.snapshots_only:
        _report(progress, "下载并上传原视频")
        extension = Path(record.file_name).suffix.lower() or ".mp4"
        temporary_path = settings.data_dir / "temp" / f"{record.video_id}{extension}"
        temporary_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            client.download(record.source_path, temporary_path)
            if temporary_path.stat().st_size != record.file_size:
                raise RuntimeError(
                    f"下载文件大小不一致：预期 {record.file_size}，实际 {temporary_path.stat().st_size}"
                )
            uploader.upload(temporary_path, record.video_key)
            record = replace(record, video_uploaded=True)
            history.save(record)
        finally:
            temporary_path.unlink(missing_ok=True)

    if not record.snapshot_uploaded:
        for index, (snapshot_path, snapshot_key) in enumerate(
            zip(record.snapshot_paths, record.snapshot_keys), 1
        ):
            _report(progress, f"上传截图 {index}/{len(record.snapshot_paths)}")
            uploader.upload(Path(snapshot_path), snapshot_key)
        record = replace(record, snapshot_uploaded=True)
        history.save(record)


def _process_video(
    file_path: Path,
    settings: Settings,
    uploader: Uploader,
    history: History,
    progress: Optional[Callable[[str], None]] = None,
) -> None:
    video_id = fingerprint(file_path)
    record = history.get(video_id)
    if record and record.exported:
        return

    if record is None:
        _report(progress, "读取视频信息")
        info = probe_video(file_path)
        seconds = snapshot_seconds(info.duration)
        snapshot_paths = tuple(
            settings.output_dir / "截图" / f"{video_id}_{index}.png"
            for index in range(1, len(seconds) + 1)
        )
        for index, (snapshot_path, second) in enumerate(zip(snapshot_paths, seconds), 1):
            _report(progress, f"截取截图 {index}/{len(snapshot_paths)}")
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
                settings.object_key(f"{week}/{video_id}/snapshot-{index}.png")
                for index in range(1, len(seconds) + 1)
            ),
            video_uploaded=False,
            snapshot_uploaded=False,
            exported=False,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            snapshot_version=2,
        )
        history.save(record)

    if not record.video_uploaded and not settings.snapshots_only:
        _report(progress, "上传原视频")
        uploader.upload(file_path, record.video_key)
        record = replace(record, video_uploaded=True)
        history.save(record)
    if not record.snapshot_uploaded:
        for index, (snapshot_path, snapshot_key) in enumerate(
            zip(record.snapshot_paths, record.snapshot_keys), 1
        ):
            _report(progress, f"上传截图 {index}/{len(record.snapshot_paths)}")
            uploader.upload(Path(snapshot_path), snapshot_key)
        record = replace(record, snapshot_uploaded=True)
        history.save(record)
