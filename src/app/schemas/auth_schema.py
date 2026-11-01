import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.authorization import CourseRole, GlobalRole, GroupRole, Permission

_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _validate_and_normalize_email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL_PATTERN.match(cleaned):
        raise ValueError("Invalid email address format")
    return cleaned


def _validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
        raise ValueError("Password must contain at least one letter and one digit")
    return value


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    display_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_and_normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name must not be blank")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_and_normalize_email(value)


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class CourseMembershipSummary(BaseModel):
    course_id: UUID
    course_code: str | None = None
    course_name: str | None = None
    term: str | None = None
    role: CourseRole
    permissions: list[Permission]


class GroupMembershipSummary(BaseModel):
    group_id: UUID
    project_id: UUID
    group_name: str | None = None
    role: GroupRole
    permissions: list[Permission]


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    global_role: GlobalRole
    is_active: bool
    permissions: list[Permission]
    created_at: datetime | None = None


class UserProfileResponse(UserResponse):
    course_memberships: list[CourseMembershipSummary] = Field(default_factory=list)
    group_memberships: list[GroupMembershipSummary] = Field(default_factory=list)


class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    refresh_expires_in: int
    user: UserResponse


class UpdateGlobalRoleRequest(BaseModel):
    global_role: GlobalRole
    is_active: bool | None = None


class AssignCourseRoleRequest(BaseModel):
    role: CourseRole


class CourseMembershipResponse(BaseModel):
    course_id: UUID
    user_id: UUID
    role: CourseRole
    permissions: list[Permission]


class AssignGroupRoleRequest(BaseModel):
    role: GroupRole = GroupRole.MEMBER


class GroupMembershipResponse(BaseModel):
    group_id: UUID
    project_id: UUID
    user_id: UUID
    role: GroupRole
    permissions: list[Permission]


class PermissionCheckRequest(BaseModel):
    permission: Permission
    course_id: UUID | None = None
    project_id: UUID | None = None
    group_id: UUID | None = None
    submission_id: UUID | None = None


class PermissionCheckResponse(BaseModel):
    allowed: bool
    permission: Permission
    reason: str
    matched_roles: list[str]
    effective_permissions: list[Permission]
    course_id: UUID | None = None
    project_id: UUID | None = None
    group_id: UUID | None = None
    submission_id: UUID | None = None


class PermissionMatrixResponse(BaseModel):
    global_roles: dict[str, list[Permission]]
    course_roles: dict[str, list[Permission]]
    group_roles: dict[str, list[Permission]]

