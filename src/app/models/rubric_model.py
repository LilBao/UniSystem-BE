from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class RubricSource(CreatedAtMixin, Base):
    __tablename__ = "rubric_sources"

    rubric_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rubric_versions.id"), primary_key=True
    )
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), unique=True)
    parse_status: Mapped[str] = mapped_column(Text, server_default="pending")
    parser_version: Mapped[str | None] = mapped_column(Text)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parse_error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (
        UniqueConstraint("rubric_version_id", "code"),
        UniqueConstraint("rubric_version_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rubric_version_id: Mapped[UUID] = mapped_column(ForeignKey("rubric_versions.id"))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("rubric_criteria.id"))
    code: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    weight: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    min_score: Mapped[Decimal] = mapped_column(Numeric(8, 3), server_default="0")
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    ordinal: Mapped[int]
    source_page: Mapped[int | None]
    source_bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_text: Mapped[str | None] = mapped_column(Text)
    grading_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
