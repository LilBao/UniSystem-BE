from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin


class ReferenceDocument(TimestampMixin, Base):
    __tablename__ = "reference_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("courses.id"))
    source_kind: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, server_default="global")
    title: Mapped[str] = mapped_column(Text)
    authors: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    publication_year: Mapped[int | None]
    doi: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    artifact_id: Mapped[UUID | None] = mapped_column(ForeignKey("artifacts.id"))
    language: Mapped[str | None] = mapped_column(Text)
    access_status: Mapped[str] = mapped_column(Text, server_default="metadata_only")
    content_sha256: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ReferencePassage(TimestampMixin, Base):
    __tablename__ = "reference_passages"
    __table_args__ = (UniqueConstraint("reference_document_id", "ordinal", "chunker_version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference_document_id: Mapped[UUID] = mapped_column(ForeignKey("reference_documents.id"))
    ordinal: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int | None]
    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    page_start: Mapped[int | None]
    page_end: Mapped[int]
    block_type: Mapped[str] = mapped_column(Text, server_default="text")
    access_level: Mapped[str] = mapped_column(Text, server_default="full_text")
    content_sha256: Mapped[str] = mapped_column(Text)
    chunker_version: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class SubmissionReference(CreatedAtMixin, Base):
    __tablename__ = "submission_references"
    __table_args__ = (UniqueConstraint("submission_id", "marker"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    marker: Mapped[str] = mapped_column(Text)
    raw_citation: Mapped[str] = mapped_column(Text)
    reference_document_id: Mapped[UUID | None] = mapped_column(ForeignKey("reference_documents.id"))
    resolver_status: Mapped[str] = mapped_column(Text, server_default="unresolved")
    resolver_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    resolver_version: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
