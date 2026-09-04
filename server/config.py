from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL


@dataclass(frozen=True)
class ServerSettings:
    database_url: str | URL
    import_token: str

    @classmethod
    def from_env(cls) -> "ServerSettings":
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url and os.getenv("DATABASE_HOST", "").strip():
            database_url = URL.create(
                "postgresql+psycopg",
                username=os.getenv("DATABASE_USER", "video_review").strip(),
                password=os.getenv("DATABASE_PASSWORD", ""),
                host=os.getenv("DATABASE_HOST", "database").strip(),
                port=int(os.getenv("DATABASE_PORT", "5432")),
                database=os.getenv("DATABASE_NAME", "video_review").strip(),
            )
        if not database_url:
            data_dir = Path(os.getenv("DATA_DIR", "数据")).resolve()
            database_url = f"sqlite:///{data_dir / 'video-review-server.sqlite'}"
        return cls(
            database_url=database_url,
            import_token=os.getenv("IMPORT_TOKEN", "").strip(),
        )