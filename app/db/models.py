from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    urls: Mapped[list["URL"]] = relationship(back_populates="user", lazy="selectin")


class URL(Base):
    __tablename__ = "urls"
    __table_args__ = (
        Index("ix_urls_short_id_unique", "short_id", unique=True),
        Index("ix_urls_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    short_id: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    user: Mapped[User] = relationship(back_populates="urls", lazy="joined")
    clicks: Mapped[list["ClickAnalytics"]] = relationship(
        back_populates="url", lazy="selectin", cascade="all, delete-orphan"
    )


class ClickAnalytics(Base):
    __tablename__ = "click_analytics"
    __table_args__ = (
        Index("ix_click_analytics_url_time", "url_id", "clicked_at"),
        Index("ix_click_analytics_user_time", "user_id", "clicked_at"),
        Index("uq_click_analytics_stream_id", "stream_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False)
    browser: Mapped[str] = mapped_column(String(128), nullable=False)
    referrer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stream_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    url: Mapped[URL] = relationship(back_populates="clicks", lazy="joined")
