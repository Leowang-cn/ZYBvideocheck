from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Settings:
    input_dir: Path
    output_dir: Path
    data_dir: Path
    cos_bucket: str
    cos_region: str
    cos_prefix: str
    cos_public_base_url: str
    secret_id: str
    secret_key: str
    server_url: str = ""
    import_token: str = ""
    openlist_url: str = ""
    openlist_token: str = ""
    openlist_path: str = ""
    baidu_pan_mount_path: str = ""

    @classmethod
    def from_env(cls, root_dir: Path) -> "Settings":
        bucket = os.getenv("COS_BUCKET", "zyb-cxyj-content1-1253445850").strip()
        region = os.getenv("COS_REGION", "ap-beijing").strip()
        prefix = os.getenv("COS_PREFIX", "").strip().strip("/")
        base_url = os.getenv(
            "COS_PUBLIC_BASE_URL",
            f"https://{bucket}.cos.{region}.myqcloud.com",
        ).strip().rstrip("/")

        if not prefix:
            raise ValueError("COS_PREFIX 未配置，请填写桶内固定子文件夹")

        return cls(
            input_dir=Path(os.getenv("INPUT_DIR", root_dir / "待处理视频")).expanduser(),
            output_dir=Path(os.getenv("OUTPUT_DIR", root_dir / "输出")).expanduser(),
            data_dir=Path(os.getenv("DATA_DIR", root_dir / "数据")).expanduser(),
            cos_bucket=bucket,
            cos_region=region,
            cos_prefix=prefix,
            cos_public_base_url=base_url,
            secret_id=os.getenv("COS_SECRET_ID", "").strip(),
            secret_key=os.getenv("COS_SECRET_KEY", "").strip(),
            server_url=os.getenv("VIDEO_REVIEW_SERVER_URL", "").strip().rstrip("/"),
            import_token=os.getenv("VIDEO_REVIEW_IMPORT_TOKEN", "").strip(),
            openlist_url=os.getenv("OPENLIST_URL", "").strip().rstrip("/"),
            openlist_token=os.getenv("OPENLIST_TOKEN", "").strip(),
            openlist_path=os.getenv("OPENLIST_PATH", "").strip(),
            baidu_pan_mount_path=os.getenv("BAIDU_PAN_MOUNT_PATH", "").strip(),
        )

    def object_key(self, relative_key: str) -> str:
        return f"{self.cos_prefix}/{relative_key.lstrip('/')}"

    def effective_baidu_pan_mount_path(self) -> str:
        if self.baidu_pan_mount_path:
            return self.baidu_pan_mount_path
        parts = PurePosixPath(self.openlist_path).parts
        return f"/{parts[1]}" if len(parts) > 1 else ""

    def public_url(self, object_key: str) -> str:
        if object_key.startswith(("http://", "https://")):
            return object_key
        return f"{self.cos_public_base_url}/{object_key.lstrip('/')}"
