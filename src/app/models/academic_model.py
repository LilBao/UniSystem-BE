from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    global_role: Mapped[str] = mapped_column(Text, server_default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Course(TimestampMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("code", "term"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    term: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class CourseMembership(CreatedAtMixin, Base):
    __tablename__ = "course_memberships"
    __table_args__ = (PrimaryKeyConstraint("course_id", "user_id"),)

    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(Text)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 3), server_default="10")
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class ProjectGroup(TimestampMixin, Base):
    __tablename__ = "project_groups"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        UniqueConstraint("project_id", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        PrimaryKeyConstraint("group_id", "user_id"),
        ForeignKeyConstraint(
            ["group_id", "project_id"],
            ["project_groups.id", "project_groups.project_id"],
        ),
        UniqueConstraint("project_id", "user_id"),
    )

    group_id: Mapped[UUID]
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(Text, server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RubricVersion(CreatedAtMixin, Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (
        UniqueConstraint("id", "project_id"),
        UniqueConstraint("project_id", "version_no"),
        CheckConstraint("status <> 'published' OR published_at IS NOT NULL"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"))
    version_no: Mapped[int]
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    policy_version: Mapped[str] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
