from __future__ import annotations

from pathlib import Path
from typing import Protocol

from video_review.config import Settings


class Uploader(Protocol):
    def upload(self, local_path: Path, object_key: str) -> None: ...


class CosUploader:
    def __init__(self, settings: Settings) -> None:
        from qcloud_cos import CosConfig, CosS3Client

        if not settings.secret_id or not settings.secret_key:
            raise ValueError("请在 .env 中配置 COS_SECRET_ID 和 COS_SECRET_KEY")
        config = CosConfig(
            Region=settings.cos_region,
            SecretId=settings.secret_id,
            SecretKey=settings.secret_key,
        )
        self.client = CosS3Client(config)
        self.bucket = settings.cos_bucket

    def upload(self, local_path: Path, object_key: str) -> None:
        with local_path.open("rb") as file_handle:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=file_handle,
                ACL="public-read",
            )
