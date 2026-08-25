from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from server.config import ServerSettings
from server.database import Review, Snapshot, Video, create_session_factory


RATING_VALUES = ("未评级", "优秀", "良好", "合格", "不合格", "无需审核")
ORIGINAL_TYPE_VALUES = ("", "新片", "旧片新剪", "人像原片", "屏幕原片")
ISSUE_SEPARATOR = re.compile(r"[；;，,\n]+")


class SnapshotInput(BaseModel):
    sequence: int = Field(ge=1)
    second: float = Field(ge=0)
    url: HttpUrl


class VideoInput(BaseModel):
    video_id: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    level_1: str = Field(default="", max_length=255)
    level_2: str = Field(default="", max_length=255)
    batch: str = Field(min_length=1, max_length=255)
    created_date: date
    file_name: str = Field(min_length=1, max_length=1024)
    file_size: int = Field(ge=0)
    duration: float = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    video_url: HttpUrl
    snapshots: list[SnapshotInput] = Field(min_length=1, max_length=10)


class ImportPayload(BaseModel):
    videos: list[VideoInput] = Field(min_length=1, max_length=500)


class ReviewInput(BaseModel):
    original_type: Literal["", "新片", "旧片新剪", "人像原片", "屏幕原片"] = ""
    rating: Literal["未评级", "优秀", "良好", "合格", "不合格", "无需审核"]
    review_note: str = Field(default="", max_length=5000)
    supplement: str = Field(default="", max_length=5000)
    reviewer: str = Field(default="", max_length=255)
    version: Optional[int] = Field(default=None, ge=0)


def create_app(settings: Optional[ServerSettings] = None) -> FastAPI:
    settings = settings or ServerSettings.from_env()
    session_factory = create_session_factory(settings.database_url)
    application = FastAPI(title="视频走查服务", version="1.0.0")

    def database() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def authorize_import(authorization: Optional[str] = Header(default=None)) -> None:
        if not settings.import_token or authorization != f"Bearer {settings.import_token}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="导入 Token 无效")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(Path(__file__).with_name("static") / "index.html")

    @application.get("/statistics", include_in_schema=False)
    def statistics_page() -> FileResponse:
        return FileResponse(Path(__file__).with_name("static") / "statistics.html")

    @application.get("/api/health")
    def health(session: Session = Depends(database)) -> dict[str, str]:
        session.execute(select(1))
        return {"status": "ok"}

    @application.post("/api/videos/import", dependencies=[Depends(authorize_import)])
    def import_videos(
        payload: ImportPayload, session: Session = Depends(database)
    ) -> dict[str, object]:
        created = 0
        existing = 0
        record_ids: dict[str, int] = {}
        for item in payload.videos:
            normalized_id = item.video_id.lower()
            video = session.scalar(select(Video).where(Video.video_id == normalized_id))
            if video is not None:
                existing += 1
                record_ids[item.video_id] = video.id
                continue
            values = item.model_dump(exclude={"snapshots"})
            values["video_id"] = normalized_id
            values["video_url"] = str(item.video_url)
            video = Video(**values)
            video.snapshots = [
                Snapshot(sequence=snapshot.sequence, second=snapshot.second, url=str(snapshot.url))
                for snapshot in item.snapshots
            ]
            session.add(video)
            session.flush()
            record_ids[item.video_id] = video.id
            created += 1
        session.commit()
        return {
            "created": created,
            "existing": existing,
            "updated": 0,
            "failed": [],
            "record_ids": record_ids,
        }

    def filtered_query(
        level_1: Optional[str], level_2: Optional[str], batch: Optional[str],
        created_from: Optional[date], created_to: Optional[date], rating: Optional[str],
        keyword: Optional[str],
    ):
        query = select(Video)
        if level_1 is not None:
            query = query.where(Video.level_1 == level_1)
        if level_2 is not None:
            query = query.where(Video.level_2 == level_2)
        if batch:
            query = query.where(Video.batch == batch)
        if created_from:
            query = query.where(Video.created_date >= created_from)
        if created_to:
            query = query.where(Video.created_date <= created_to)
        if rating:
            if rating == "未评级":
                query = query.outerjoin(Review).where(
                    or_(Review.id.is_(None), Review.rating == "未评级")
                )
            else:
                query = query.join(Review).where(Review.rating == rating)
        if keyword:
            escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(Video.file_name.ilike(f"%{escaped}%", escape="\\"))
        return query

    def query_parameters(
        level_1: Optional[str] = Query(default=None),
        level_2: Optional[str] = Query(default=None),
        batch: Optional[str] = Query(default=None),
        created_from: Optional[date] = Query(default=None),
        created_to: Optional[date] = Query(default=None),
        rating: Optional[str] = Query(default=None),
        keyword: Optional[str] = Query(default=None, max_length=255),
    ) -> dict[str, object]:
        if rating and rating not in RATING_VALUES:
            raise HTTPException(status_code=422, detail="评级值无效")
        if created_from and created_to and created_from > created_to:
            raise HTTPException(status_code=422, detail="开始日期不能晚于结束日期")
        return locals()

    @application.get("/api/videos")
    def list_videos(
        filters: dict[str, object] = Depends(query_parameters),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(database),
    ) -> dict[str, object]:
        query = filtered_query(**filters)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        videos = session.scalars(
            query.options(selectinload(Video.snapshots), selectinload(Video.review))
            .order_by(Video.created_date.desc(), Video.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return {
            "items": [_video_data(video) for video in videos],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @application.get("/api/videos/options")
    def list_options(session: Session = Depends(database)) -> dict[str, list[str]]:
        def values(column) -> list[str]:
            return list(session.scalars(select(column).distinct().order_by(column)).all())

        return {
            "level_1": values(Video.level_1),
            "level_2": values(Video.level_2),
            "batch": values(Video.batch),
        }

    @application.get("/api/statistics/overview")
    def statistics_overview(
        filters: dict[str, object] = Depends(query_parameters),
        original_type: list[str] = Query(default=[]),
        session: Session = Depends(database),
    ) -> dict[str, object]:
        invalid_types = set(original_type) - set(ORIGINAL_TYPE_VALUES)
        if invalid_types:
            raise HTTPException(status_code=422, detail="原片类型值无效")
        videos = session.scalars(
            filtered_query(**filters)
            .options(selectinload(Video.review))
            .order_by(Video.created_date, Video.id)
        ).all()
        if original_type:
            videos = [
                video for video in videos
                if video.review and video.review.original_type in original_type
            ]
        ratings = {value: 0 for value in RATING_VALUES}
        original_types = {value: 0 for value in ORIGINAL_TYPE_VALUES if value}
        batches: dict[str, dict[str, object]] = {}
        issues: dict[str, int] = {}
        reviewed = 0
        reviewed_duration = 0.0
        noted = 0
        for video in videos:
            review = video.review
            rating = review.rating if review else "未评级"
            ratings[rating] = ratings.get(rating, 0) + 1
            is_reviewed = rating != "未评级"
            if is_reviewed:
                reviewed += 1
                reviewed_duration += video.duration
            original_type = review.original_type if review else ""
            if original_type:
                original_types[original_type] = original_types.get(original_type, 0) + 1
            note = review.review_note if review else ""
            if note:
                noted += 1
                for issue in _review_issues(note):
                    issues[issue] = issues.get(issue, 0) + 1
            batch = batches.setdefault(
                video.batch,
                {"batch": video.batch, "total": 0, "reviewed": 0, "failed": 0},
            )
            batch["total"] += 1
            batch["reviewed"] += int(is_reviewed)
            batch["failed"] += int(rating == "不合格")

        total = len(videos)
        batch_items = sorted(batches.values(), key=lambda item: (-item["total"], item["batch"]))
        for item in batch_items:
            item["completion_rate"] = round(item["reviewed"] / item["total"] * 100, 1)
        return {
            "summary": {
                "total": total,
                "reviewed": reviewed,
                "unreviewed": total - reviewed,
                "completion_rate": round(reviewed / total * 100, 1) if total else 0.0,
                "noted": noted,
                "total_duration": sum(video.duration for video in videos),
                "reviewed_duration": reviewed_duration,
            },
            "ratings": [{"name": name, "count": count} for name, count in ratings.items()],
            "original_types": [
                {"name": name, "count": count} for name, count in original_types.items()
            ],
            "batches": batch_items,
            "issues": [
                {"name": name, "count": count}
                for name, count in sorted(issues.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    @application.get("/api/statistics/issues/videos")
    def statistics_issue_videos(
        issue: str = Query(min_length=1, max_length=5000),
        filters: dict[str, object] = Depends(query_parameters),
        original_type: list[str] = Query(default=[]),
        session: Session = Depends(database),
    ) -> dict[str, object]:
        invalid_types = set(original_type) - set(ORIGINAL_TYPE_VALUES)
        if invalid_types:
            raise HTTPException(status_code=422, detail="原片类型值无效")
        videos = session.scalars(
            filtered_query(**filters)
            .options(selectinload(Video.snapshots), selectinload(Video.review))
            .order_by(Video.created_date.desc(), Video.id.desc())
        ).all()
        items = [
            video for video in videos
            if issue in _review_issues(video.review.review_note if video.review else "")
            and (not original_type or video.review.original_type in original_type)
        ]
        return {"issue": issue, "total": len(items), "items": [_video_data(video) for video in items]}

    @application.patch("/api/videos/{video_id}/review")
    def save_review(
        video_id: str, payload: ReviewInput, session: Session = Depends(database)
    ) -> dict[str, object]:
        video = session.scalar(
            select(Video).options(selectinload(Video.review)).where(Video.video_id == video_id.lower())
        )
        if video is None:
            raise HTTPException(status_code=404, detail="视频不存在")
        review = video.review
        if review is None:
            if payload.version not in (None, 0):
                raise HTTPException(status_code=409, detail="质检结果已被其他人修改，请刷新后重试")
            review = Review(video_pk=video.id, version=0)
            session.add(review)
        elif payload.version is not None and payload.version != review.version:
            raise HTTPException(status_code=409, detail="质检结果已被其他人修改，请刷新后重试")
        review.original_type = payload.original_type
        review.rating = payload.rating
        review.review_note = payload.review_note
        review.supplement = payload.supplement
        review.reviewer = payload.reviewer
        review.version += 1
        review.updated_at = datetime.utcnow()
        session.commit()
        return _review_data(review)

    @application.get("/api/videos/export.csv")
    def export_csv(
        filters: dict[str, object] = Depends(query_parameters),
        session: Session = Depends(database),
    ) -> StreamingResponse:
        videos = session.scalars(
            filtered_query(**filters)
            .options(selectinload(Video.snapshots), selectinload(Video.review))
            .order_by(Video.created_date.desc(), Video.id.desc())
        ).all()
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer)
        writer.writerow(["一级地址", "二级地址", "创建日期", "批次", "视频名称", "视频 URL", "截图 URL", "文件大小", "时长", "分辨率", "原片类型", "评级", "质检备注", "补充"])
        for video in videos:
            review = video.review
            writer.writerow([
                _csv_safe(video.level_1), _csv_safe(video.level_2),
                video.created_date.isoformat(), _csv_safe(video.batch),
                _csv_safe(video.file_name), video.video_url,
                "\n".join(snapshot.url for snapshot in video.snapshots),
                video.file_size, video.duration, f"{video.width} × {video.height}",
                review.original_type if review else "",
                review.rating if review else "未评级",
                _csv_safe(review.review_note if review else ""),
                _csv_safe(review.supplement if review else ""),
            ])
        headers = {"Content-Disposition": 'attachment; filename="video-review.csv"'}
        return StreamingResponse(
            iter([buffer.getvalue()]), media_type="text/csv; charset=utf-8", headers=headers
        )

    return application


def _review_data(review: Optional[Review]) -> dict[str, object]:
    if review is None:
        return {
            "original_type": "", "rating": "未评级", "review_note": "", "supplement": "",
            "reviewer": "", "version": 0, "updated_at": None,
        }
    return {
        "original_type": review.original_type, "rating": review.rating, "review_note": review.review_note,
        "supplement": review.supplement, "reviewer": review.reviewer,
        "version": review.version, "updated_at": review.updated_at.isoformat(),
    }


def _video_data(video: Video) -> dict[str, object]:
    return {
        "video_id": video.video_id, "level_1": video.level_1,
        "level_2": video.level_2, "batch": video.batch,
        "created_date": video.created_date.isoformat(), "file_name": video.file_name,
        "file_size": video.file_size, "duration": video.duration,
        "width": video.width, "height": video.height, "video_url": video.video_url,
        "snapshots": [
            {"sequence": item.sequence, "second": item.second, "url": item.url}
            for item in video.snapshots
        ],
        "review": _review_data(video.review),
    }


def _csv_safe(value: str) -> str:
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _review_issues(note: str) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in ISSUE_SEPARATOR.split(note) if value.strip()))


app = create_app()