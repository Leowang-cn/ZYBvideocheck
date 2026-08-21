from __future__ import annotations

import json
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from video_review.config import Settings
from video_review.history import ImportRecord
from video_review.html_report import record_source_levels


def push_records(records: list[ImportRecord], settings: Settings) -> dict[str, object]:
    if not settings.server_url:
        return {"created": 0, "existing": 0, "updated": 0, "failed": []}
    if not settings.import_token:
        raise ValueError("已配置服务器地址，但 VIDEO_REVIEW_IMPORT_TOKEN 为空")

    payload = {
        "videos": [_record_payload(record, settings) for record in records]
    }
    request = Request(
        f"{settings.server_url}/api/videos/import",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.import_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"服务器导入失败（HTTP {error.code}）：{detail}") from error
    except URLError as error:
        raise RuntimeError(f"无法连接视频走查服务器：{error.reason}") from error


def _record_payload(record: ImportRecord, settings: Settings) -> dict[str, object]:
    level_1, level_2 = record_source_levels(record, settings)
    created_date = (record.created_at or date.today().isoformat())[:10]
    return {
        "video_id": record.video_id,
        "level_1": level_1,
        "level_2": level_2,
        "batch": record.batch or "未标记",
        "created_date": created_date,
        "file_name": record.file_name,
        "file_size": record.file_size,
        "duration": record.duration,
        "width": record.width,
        "height": record.height,
        "video_url": settings.public_url(record.video_key),
        "snapshots": [
            {
                "sequence": index,
                "second": second,
                "url": settings.public_url(key),
            }
            for index, (second, key) in enumerate(
                zip(record.snapshot_seconds, record.snapshot_keys), start=1
            )
        ],
    }