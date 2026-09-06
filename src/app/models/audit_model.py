from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    actor_type: Mapped[str] = mapped_column(Text, server_default="system")
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    actor_service: Mapped[str | None] = mapped_column(Text)
    course_id: Mapped[UUID | None] = mapped_column(ForeignKey("courses.id"))
    submission_id: Mapped[UUID | None] = mapped_column(ForeignKey("submissions.id"))
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, server_default="success")
    request_id: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="db_trigger")
    source_service: Mapped[str | None] = mapped_column(Text)
    http_method: Mapped[str | None] = mapped_column(Text)
    request_path: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None]
    ip_address: Mapped[Any | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    changed_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default=text("ARRAY[]::text[]")
    )
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )


class Highlight(CreatedAtMixin, Base):
    __tablename__ = "highlights"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    feedback_item_id: Mapped[UUID] = mapped_column(ForeignKey("feedback_items.id"))
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"))
    page_no: Mapped[int]
    quads: Mapped[list[Any]] = mapped_column(JSONB)
    color: Mapped[str] = mapped_column(Text, server_default="#F6C85F")
    tooltip: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text, server_default="student")
    annotation_status: Mapped[str] = mapped_column(Text, server_default="draft")
