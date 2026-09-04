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
        self.upload_with_metadata(local_path, object_key)

    def upload_with_metadata(
        self,
        local_path: Path,
        object_key: str,
        content_type: str | None = None,
        cache_control: str | None = None,
    ) -> None:
        options = {}
        if content_type:
            options["ContentType"] = content_type
        if cache_control:
            options["CacheControl"] = cache_control
        self.client.upload_file(
            Bucket=self.bucket,
            Key=object_key,
            LocalFilePath=str(local_path),
            PartSize=8,
            MAXThread=4,
            EnableMD5=True,
            ACL="public-read",
            **options,
        )
        metadata = self.client.head_object(Bucket=self.bucket, Key=object_key)
        remote_size = int(metadata["Content-Length"])
        local_size = local_path.stat().st_size
        if remote_size != local_size:
            raise RuntimeError(
                f"COS 对象大小不一致：本地 {local_size}，远端 {remote_size}"
            )
