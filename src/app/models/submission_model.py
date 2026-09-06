from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "project_id"],
            ["project_groups.id", "project_groups.project_id"],
        ),
        ForeignKeyConstraint(
            ["group_id", "submitted_by_user_id"],
            ["group_members.group_id", "group_members.user_id"],
        ),
        ForeignKeyConstraint(
            ["rubric_version_id", "project_id"],
            ["rubric_versions.id", "rubric_versions.project_id"],
        ),
        UniqueConstraint("project_id", "group_id", "attempt_no"),
        Index(
            "uq_submissions_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    group_id: Mapped[UUID]
    submitted_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    rubric_version_id: Mapped[UUID]
    attempt_no: Mapped[int] = mapped_column(server_default="1")
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Artifact(CreatedAtMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("object_uri", "version_no"),
        UniqueConstraint("submission_id", "kind", "version_no", "sha256"),
        Index("idx_artifacts_submission", "submission_id", "kind", "version_no"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID | None] = mapped_column(ForeignKey("submissions.id"))
    kind: Mapped[str] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(server_default="1")
    object_uri: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(Text)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
