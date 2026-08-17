from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import URL, Date, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    level_1: Mapped[str] = mapped_column(String(255), default="", index=True)
    level_2: Mapped[str] = mapped_column(String(255), default="", index=True)
    batch: Mapped[str] = mapped_column(String(255), index=True)
    created_date: Mapped[date] = mapped_column(Date, index=True)
    file_name: Mapped[str] = mapped_column(String(1024))
    file_size: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    video_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    snapshots: Mapped[list["Snapshot"]] = relationship(
        cascade="all, delete-orphan", order_by="Snapshot.sequence"
    )
    review: Mapped["Review | None"] = relationship(
        cascade="all, delete-orphan", uselist=False
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_pk: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    second: Mapped[float] = mapped_column(Float)
    url: Mapped[str] = mapped_column(Text)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_pk: Mapped[int] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[str] = mapped_column(String(20), default="未评级", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    supplement: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def create_session_factory(database_url: str | URL) -> sessionmaker:
    is_sqlite = str(database_url).startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)