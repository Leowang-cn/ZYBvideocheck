from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportRecord:
    video_id: str
    source_path: str
    file_name: str
    file_size: int
    duration: float
    width: int
    height: int
    snapshot_seconds: tuple[float, ...]
    snapshot_paths: tuple[str, ...]
    video_key: str
    snapshot_keys: tuple[str, ...]
    video_uploaded: bool
    snapshot_uploaded: bool
    exported: bool
    batch: str = ""
    created_at: str = ""


class History:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS imports (
                video_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                duration REAL NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                snapshot_second REAL NOT NULL,
                snapshot_path TEXT NOT NULL,
                video_key TEXT NOT NULL,
                snapshot_key TEXT NOT NULL,
                video_uploaded INTEGER NOT NULL DEFAULT 0,
                snapshot_uploaded INTEGER NOT NULL DEFAULT 0,
                exported INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(imports)").fetchall()
        }
        if "batch" not in columns:
            self.connection.execute(
                "ALTER TABLE imports ADD COLUMN batch TEXT NOT NULL DEFAULT ''"
            )
        if "created_at" not in columns:
            self.connection.execute(
                "ALTER TABLE imports ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"
            )
            self.connection.execute(
                "UPDATE imports SET created_at = updated_at WHERE created_at = ''"
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def get(self, video_id: str) -> ImportRecord | None:
        row = self.connection.execute(
            "SELECT * FROM imports WHERE video_id = ?", (video_id,)
        ).fetchone()
        return self._record(row) if row else None

    def save(self, record: ImportRecord, error: str | None = None) -> None:
        self.connection.execute(
            """
            INSERT INTO imports (
                video_id, source_path, file_name, file_size, duration, width, height,
                snapshot_second, snapshot_path, video_key, snapshot_key,
                video_uploaded, snapshot_uploaded, exported, error, updated_at, batch,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP))
            ON CONFLICT(video_id) DO UPDATE SET
                source_path=excluded.source_path,
                video_uploaded=excluded.video_uploaded,
                snapshot_uploaded=excluded.snapshot_uploaded,
                exported=excluded.exported,
                error=excluded.error,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                record.video_id,
                record.source_path,
                record.file_name,
                record.file_size,
                record.duration,
                record.width,
                record.height,
                json.dumps(record.snapshot_seconds),
                json.dumps(record.snapshot_paths, ensure_ascii=False),
                record.video_key,
                json.dumps(record.snapshot_keys, ensure_ascii=False),
                int(record.video_uploaded),
                int(record.snapshot_uploaded),
                int(record.exported),
                error,
                record.batch,
                record.created_at,
            ),
        )
        self.connection.commit()

    def pending_export(self) -> list[ImportRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM imports
            WHERE video_uploaded = 1 AND snapshot_uploaded = 1 AND exported = 0
            ORDER BY updated_at, file_name
            """
        ).fetchall()
        return [self._record(row) for row in rows]

    def mark_exported(self, video_ids: list[str]) -> None:
        self.connection.executemany(
            "UPDATE imports SET exported = 1, updated_at = CURRENT_TIMESTAMP WHERE video_id = ?",
            [(video_id,) for video_id in video_ids],
        )
        self.connection.commit()

    def assign_batch(self, video_ids: list[str], batch: str) -> None:
        self.connection.executemany(
            "UPDATE imports SET batch = ? WHERE video_id = ? AND batch = ''",
            [(batch, video_id) for video_id in video_ids],
        )
        self.connection.commit()

    def ready_records(self) -> list[ImportRecord]:
        rows = self.connection.execute(
            """
            SELECT * FROM imports
            WHERE video_uploaded = 1 AND snapshot_uploaded = 1
            ORDER BY updated_at, file_name
            """
        ).fetchall()
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: sqlite3.Row) -> ImportRecord:
        def load_tuple(value: str) -> tuple:
            try:
                loaded = json.loads(value)
                return tuple(loaded) if isinstance(loaded, list) else (loaded,)
            except (json.JSONDecodeError, TypeError):
                return (value,)

        return ImportRecord(
            video_id=row["video_id"],
            source_path=row["source_path"],
            file_name=row["file_name"],
            file_size=row["file_size"],
            duration=row["duration"],
            width=row["width"],
            height=row["height"],
            snapshot_seconds=tuple(float(value) for value in load_tuple(row["snapshot_second"])),
            snapshot_paths=tuple(str(value) for value in load_tuple(row["snapshot_path"])),
            video_key=row["video_key"],
            snapshot_keys=tuple(str(value) for value in load_tuple(row["snapshot_key"])),
            video_uploaded=bool(row["video_uploaded"]),
            snapshot_uploaded=bool(row["snapshot_uploaded"]),
            exported=bool(row["exported"]),
            batch=str(row["batch"]),
            created_at=str(row["created_at"]),
        )
