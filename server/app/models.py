"""
SQLAlchemy ORM models for the backend.

Tables:
- users
- conversations
- transcripts
- embeddings
- recording_session_summaries (§7.6 chain summary)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
      UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Encrypted per-user key material (e.g. envelope key) for AES256.
    encrypted_key: Mapped[bytes | None] = mapped_column()

    # UI defaults: default_language, default_ttl_days, search_mode (fulltext|semantic)
    preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    oauth_identities: Mapped[list["UserOAuthIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserOAuthIdentity(Base):
    """Stable link between a VT user and `(provider, provider_subject)` — canonical login key (AUTH_AND_IDENTITY §5)."""

    __tablename__ = "user_oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="oauth_identities")


class UserApiKey(Base):
    """Long-lived API key for CLI/automation (Phase C6); store only SHA-256 of secret."""

    __tablename__ = "user_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship()


class AuthRefreshSession(Base):
    """Opaque refresh token for long-lived service session (C7.2); store only SHA-256 hash."""

    __tablename__ = "auth_refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    # When this conversation (and its objects) should be deleted.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Soft delete timestamp.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # S3 prefix where all artifacts for this conversation are stored.
    s3_prefix: Mapped[str] = mapped_column(String(512), nullable=False)

    # Расширение исходного аудио в S3 (audio.<ext>), без точки; по умолчанию webm.
    audio_object_ext: Mapped[str] = mapped_column(String(16), nullable=False, default="webm")

    # Время последней загрузки/замены исходного аудио (S3 audio.<ext>).
    audio_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Цепочка автопродления (ТЗ §7): для первой записи == id; для продолжений — id первой.
    recording_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    previous_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Выбор клиента для realtime (валидация по limits); для пакетной записи могут быть null.
    client_realtime_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_chunk_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Active transcript pointer (Scheme 2): points to the current "published" version.
    active_transcript_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("transcripts.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    # Explicitly disambiguate FK paths: Conversation links to Transcript both via
    # Transcript.conversation_id (one-to-many) and Conversation.active_transcript_id (one-to-one).
    transcripts: Mapped[list["Transcript"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Transcript.conversation_id",
    )
    active_transcript: Mapped["Transcript | None"] = relationship(
        foreign_keys=[active_transcript_id],
        post_update=True,
    )


class RecordingSessionSummary(Base):
    """Rolling LLM summary for an autoprolong chain (shared recording_session_id)."""

    __tablename__ = "recording_session_summaries"

    recording_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    summary_md: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        UniqueConstraint("conversation_id", "revision", name="uq_transcripts_conversation_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Monotonic revision number per conversation (1..N).
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Pipeline stage / kind (e.g. "asr", "asr_diarized").
    kind: Mapped[str] = mapped_column(String(64), nullable=False, default="asr")

    # Job status: pending | running | success | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")

    # Provider metadata and run parameters (device, models, speaker limits, timings, etc.)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Raw JSON transcript with timestamps and speaker labels.
    transcript_json: Mapped[dict | None] = mapped_column(JSONB)
    # Markdown representations.
    transcript_md: Mapped[str | None] = mapped_column(Text)
    summary_md: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    conversation: Mapped[Conversation] = relationship(
        back_populates="transcripts",
        foreign_keys=[conversation_id],
    )
    user: Mapped[User] = relationship()
    embeddings: Mapped[list["Embedding"]] = relationship(
        back_populates="transcript", cascade="all, delete-orphan"
    )


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "transcript_id", "kind", name="uq_embeddings_transcript_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # e.g. "summary", "full"
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    # Store vector as JSONB array of floats for portability.
    vector: Mapped[list[float]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    transcript: Mapped[Transcript] = relationship(back_populates="embeddings")

