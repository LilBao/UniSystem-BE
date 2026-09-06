from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (UniqueConstraint("artifact_id", "ordinal"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_sections.id"))
    title: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int] = mapped_column(server_default="1")
    ordinal: Mapped[int]
    page_start: Mapped[int]
    page_end: Mapped[int]
    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )


class DocumentBlock(CreatedAtMixin, Base):
    __tablename__ = "document_blocks"
    __table_args__ = (UniqueConstraint("artifact_id", "page_no", "reading_order"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    section_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_sections.id"))
    parent_block_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_blocks.id"))
    caption_block_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_blocks.id"))
    block_type: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int]
    reading_order: Mapped[int]
    text_content: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSONB)
    quads: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    citation_marker_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    parser_version: Mapped[str] = mapped_column(Text)
    source_locator: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Claim(CreatedAtMixin, Base):
    __tablename__ = "claims"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    source_block_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_blocks.id"))
    claim_type: Mapped[str] = mapped_column(Text)
    text_content: Mapped[str] = mapped_column(Text)
    is_atomic: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_central: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    qualifiers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    source_span: Mapped[dict[str, Any]] = mapped_column(JSONB)
    context_block_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), default=list, server_default=text("ARRAY[]::uuid[]")
    )
    impact: Mapped[int] = mapped_column(server_default="1")
    testability: Mapped[int] = mapped_column(server_default="0")
    risk: Mapped[int] = mapped_column(server_default="1")
    extractor_version: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))


class CodeGraphSnapshot(CreatedAtMixin, Base):
    __tablename__ = "code_graph_snapshots"
    __table_args__ = (
        UniqueConstraint("submission_id", "source_sha256", "graphify_version"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("submissions.id"))
    source_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    graph_artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    source_sha256: Mapped[str] = mapped_column(Text)
    graphify_version: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(Text)
    node_count: Mapped[int | None]
    edge_count: Mapped[int | None]
    provenance_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
