import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final
from uuid import UUID, uuid4

import bcrypt

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

_HASH_ALGORITHMS: Final[dict[str, Callable[[], Any]]] = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}


class GlobalRole(StrEnum):
    USER = "user"
    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class CourseRole(StrEnum):
    INSTRUCTOR = "instructor"
    TA = "ta"
    STUDENT = "student"
    REVIEWER = "reviewer"


class GroupRole(StrEnum):
    LEADER = "leader"
    MEMBER = "member"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class Permission(StrEnum):
    # User & System
    USER_READ = "user:read"
    USER_MANAGE = "user:manage"
    AUDIT_READ = "audit:read"

    # Course & Project
    COURSE_CREATE = "course:create"
    COURSE_READ = "course:read"
    COURSE_UPDATE = "course:update"
    COURSE_MANAGE_MEMBERS = "course:manage_members"
    PROJECT_READ = "project:read"
    PROJECT_MANAGE = "project:manage"

    # Group
    GROUP_CREATE = "group:create"
    GROUP_READ = "group:read"
    GROUP_MANAGE_MEMBERS = "group:manage_members"

    # Rubric
    RUBRIC_READ = "rubric:read"
    RUBRIC_MANAGE = "rubric:manage"
    RUBRIC_PUBLISH = "rubric:publish"

    # Submission & Artifact
    SUBMISSION_CREATE = "submission:create"
    SUBMISSION_READ = "submission:read"
    SUBMISSION_UPLOAD = "submission:upload"
    SUBMISSION_SUBMIT = "submission:submit"

    # Pipeline & Evaluation
    PIPELINE_RUN = "pipeline:run"
    PIPELINE_READ = "pipeline:read"
    EVALUATION_READ = "evaluation:read"
    EVALUATION_OVERRIDE = "evaluation:override"
    EVALUATION_PUBLISH = "evaluation:publish"


ALL_PERMISSIONS: Final[frozenset[Permission]] = frozenset(Permission)

GLOBAL_ROLE_PERMISSIONS: Final[dict[GlobalRole, frozenset[Permission]]] = {
    GlobalRole.ADMIN: ALL_PERMISSIONS,
    GlobalRole.INSTRUCTOR: frozenset(
        {
            Permission.USER_READ,
            Permission.COURSE_CREATE,
        }
    ),
    GlobalRole.STUDENT: frozenset({Permission.USER_READ}),
    GlobalRole.USER: frozenset({Permission.USER_READ}),
}

COURSE_ROLE_PERMISSIONS: Final[dict[CourseRole, frozenset[Permission]]] = {
    CourseRole.INSTRUCTOR: frozenset(
        {
            Permission.COURSE_READ,
            Permission.COURSE_UPDATE,
            Permission.COURSE_MANAGE_MEMBERS,
            Permission.PROJECT_READ,
            Permission.PROJECT_MANAGE,
            Permission.GROUP_CREATE,
            Permission.GROUP_READ,
            Permission.GROUP_MANAGE_MEMBERS,
            Permission.RUBRIC_READ,
            Permission.RUBRIC_MANAGE,
            Permission.RUBRIC_PUBLISH,
            Permission.SUBMISSION_READ,
            Permission.PIPELINE_RUN,
            Permission.PIPELINE_READ,
            Permission.EVALUATION_READ,
            Permission.EVALUATION_OVERRIDE,
            Permission.EVALUATION_PUBLISH,
            Permission.AUDIT_READ,
        }
    ),
    CourseRole.TA: frozenset(
        {
            Permission.COURSE_READ,
            Permission.PROJECT_READ,
            Permission.GROUP_CREATE,
            Permission.GROUP_READ,
            Permission.GROUP_MANAGE_MEMBERS,
            Permission.RUBRIC_READ,
            Permission.RUBRIC_MANAGE,
            Permission.SUBMISSION_READ,
            Permission.PIPELINE_RUN,
            Permission.PIPELINE_READ,
            Permission.EVALUATION_READ,
            Permission.EVALUATION_OVERRIDE,
        }
    ),
    CourseRole.REVIEWER: frozenset(
        {
            Permission.COURSE_READ,
            Permission.PROJECT_READ,
            Permission.GROUP_READ,
            Permission.RUBRIC_READ,
            Permission.SUBMISSION_READ,
            Permission.PIPELINE_RUN,
            Permission.PIPELINE_READ,
            Permission.EVALUATION_READ,
            Permission.EVALUATION_OVERRIDE,
        }
    ),
    CourseRole.STUDENT: frozenset(
        {
            Permission.COURSE_READ,
            Permission.PROJECT_READ,
            Permission.GROUP_READ,
            Permission.RUBRIC_READ,
        }
    ),
}

GROUP_ROLE_PERMISSIONS: Final[dict[GroupRole, frozenset[Permission]]] = {
    GroupRole.LEADER: frozenset(
        {
            Permission.GROUP_READ,
            Permission.GROUP_MANAGE_MEMBERS,
            Permission.SUBMISSION_CREATE,
            Permission.SUBMISSION_READ,
            Permission.SUBMISSION_UPLOAD,
            Permission.SUBMISSION_SUBMIT,
            Permission.PIPELINE_READ,
            Permission.EVALUATION_READ,
        }
    ),
    GroupRole.MEMBER: frozenset(
        {
            Permission.GROUP_READ,
            Permission.SUBMISSION_CREATE,
            Permission.SUBMISSION_READ,
            Permission.SUBMISSION_UPLOAD,
            Permission.SUBMISSION_SUBMIT,
            Permission.PIPELINE_READ,
            Permission.EVALUATION_READ,
        }
    ),
}

COURSE_STAFF_ROLES: Final[frozenset[CourseRole]] = frozenset(
    {
        CourseRole.INSTRUCTOR,
        CourseRole.TA,
        CourseRole.REVIEWER,
    }
)

GROUP_SCOPED_PERMISSIONS: Final[frozenset[Permission]] = frozenset(
    {
        Permission.GROUP_MANAGE_MEMBERS,
        Permission.SUBMISSION_CREATE,
        Permission.SUBMISSION_READ,
        Permission.SUBMISSION_UPLOAD,
        Permission.SUBMISSION_SUBMIT,
        Permission.PIPELINE_READ,
        Permission.EVALUATION_READ,
    }
)


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    permission: Permission
    effective_permissions: frozenset[Permission]
    reason: str
    matched_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: UUID
    email: str
    display_name: str
    global_role: GlobalRole
    is_active: bool
    permissions: frozenset[Permission]
    token_jti: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.global_role == GlobalRole.ADMIN

    def has_permission(self, permission: Permission) -> bool:
        if self.is_admin:
            return True
        return permission in self.permissions

    def has_any_global_role(self, *roles: GlobalRole) -> bool:
        return self.global_role in roles


@dataclass(frozen=True, slots=True)
class TokenClaims:
    sub: UUID
    email: str
    display_name: str
    global_role: GlobalRole
    permissions: tuple[Permission, ...]
    token_type: TokenType
    jti: str
    iss: str
    iat: datetime
    exp: datetime


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode((segment + padding).encode("ascii"))
    except (ValueError, binascii.Error) as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token") from exc


def encode_jwt(payload: dict[str, Any], secret_key: str, algorithm: str = "HS256") -> str:
    digest_factory = _HASH_ALGORITHMS.get(algorithm)
    if digest_factory is None:
        raise ValueError(f"Unsupported JWT algorithm: {algorithm}")

    header = {"alg": algorithm, "typ": "JWT"}
    header_segment = _b64url_encode(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        digest_factory,
    ).digest()
    signature_segment = _b64url_encode(signature)
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def decode_jwt(
    token: str,
    secret_key: str,
    *,
    algorithm: str = "HS256",
    issuer: str | None = None,
) -> dict[str, Any]:
    digest_factory = _HASH_ALGORITHMS.get(algorithm)
    if digest_factory is None:
        raise ValueError(f"Unsupported JWT algorithm: {algorithm}")

    parts = token.strip().split(".")
    if len(parts) != 3 or not all(parts):
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token")

    header_segment, payload_segment, signature_segment = parts
    try:
        header = json.loads(_b64url_decode(header_segment).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token")

    if header.get("alg") != algorithm:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token algorithm")

    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected_sig = hmac.new(
        secret_key.encode("utf-8"),
        signing_input,
        digest_factory,
    ).digest()
    actual_sig = _b64url_decode(signature_segment)
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token signature")

    for required_claim in ("sub", "exp", "iat", "iss", "token_type", "jti"):
        if required_claim not in payload:
            raise AppError(ErrorCode.UNAUTHORIZED, f"Missing required claim: {required_claim}")

    if issuer is not None and payload.get("iss") != issuer:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authentication token issuer")

    try:
        exp_ts = int(payload["exp"])
    except (TypeError, ValueError) as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid token expiration claim") from exc

    now_ts = int(datetime.now(UTC).timestamp())
    if now_ts >= exp_ts:
        raise AppError(ErrorCode.TOKEN_EXPIRED)

    return payload


def resolve_effective_permissions(
    global_role: GlobalRole,
    course_role: CourseRole | None = None,
    group_role: GroupRole | None = None,
    *,
    is_course_creator: bool = False,
    require_group_membership_for_student: bool = False,
) -> frozenset[Permission]:
    """Compute the union of permissions granted to a user within a specific resource scope."""
    if global_role == GlobalRole.ADMIN:
        return ALL_PERMISSIONS

    effective: set[Permission] = set(GLOBAL_ROLE_PERMISSIONS.get(global_role, frozenset()))
    effective_course_role = (
        course_role
        if course_role is not None
        else (CourseRole.INSTRUCTOR if is_course_creator else None)
    )

    if effective_course_role is not None:
        effective.update(COURSE_ROLE_PERMISSIONS.get(effective_course_role, frozenset()))

    if group_role is not None:
        effective.update(GROUP_ROLE_PERMISSIONS.get(group_role, frozenset()))
    elif require_group_membership_for_student and effective_course_role not in COURSE_STAFF_ROLES:
        effective.difference_update(GROUP_SCOPED_PERMISSIONS)

    return frozenset(effective)


def evaluate_permission(
    required_permission: Permission,
    *,
    global_role: GlobalRole,
    course_role: CourseRole | None = None,
    group_role: GroupRole | None = None,
    is_course_creator: bool = False,
    require_course_membership: bool = False,
    require_group_membership_for_student: bool = False,
) -> AuthorizationDecision:
    """Evaluate a fine-grained permission against global, course, and group roles."""
    matched_roles: list[str] = [f"global:{global_role.value}"]
    effective_course_role = (
        course_role
        if course_role is not None
        else (CourseRole.INSTRUCTOR if is_course_creator else None)
    )
    if course_role is not None:
        matched_roles.append(f"course:{course_role.value}")
    elif is_course_creator:
        matched_roles.append("course:creator(instructor)")
    if group_role is not None:
        matched_roles.append(f"group:{group_role.value}")

    effective = resolve_effective_permissions(
        global_role=global_role,
        course_role=course_role,
        group_role=group_role,
        is_course_creator=is_course_creator,
        require_group_membership_for_student=require_group_membership_for_student,
    )

    if global_role == GlobalRole.ADMIN:
        return AuthorizationDecision(
            allowed=True,
            permission=required_permission,
            effective_permissions=effective,
            reason="GLOBAL_ADMIN",
            matched_roles=tuple(matched_roles),
        )

    if (
        require_course_membership
        and effective_course_role is None
        and group_role is None
    ):
        return AuthorizationDecision(
            allowed=False,
            permission=required_permission,
            effective_permissions=frozenset(GLOBAL_ROLE_PERMISSIONS.get(global_role, frozenset())),
            reason="NOT_COURSE_MEMBER",
            matched_roles=tuple(matched_roles),
        )

    if (
        require_group_membership_for_student
        and effective_course_role not in COURSE_STAFF_ROLES
        and required_permission in GROUP_SCOPED_PERMISSIONS
    ):
        if group_role is None:
            return AuthorizationDecision(
                allowed=False,
                permission=required_permission,
                effective_permissions=effective,
                reason="NOT_GROUP_MEMBER",
                matched_roles=tuple(matched_roles),
            )
        if required_permission not in GROUP_ROLE_PERMISSIONS.get(group_role, frozenset()):
            return AuthorizationDecision(
                allowed=False,
                permission=required_permission,
                effective_permissions=effective,
                reason=f"INSUFFICIENT_GROUP_ROLE:{group_role.value.upper()}",
                matched_roles=tuple(matched_roles),
            )
        return AuthorizationDecision(
            allowed=True,
            permission=required_permission,
            effective_permissions=effective,
            reason=f"GROUP_ROLE:{group_role.value.upper()}",
            matched_roles=tuple(matched_roles),
        )

    if required_permission in effective:
        course_perms = (
            COURSE_ROLE_PERMISSIONS.get(effective_course_role, frozenset())
            if effective_course_role is not None
            else frozenset()
        )
        if effective_course_role is not None and required_permission in course_perms:
            reason = (
                f"COURSE_ROLE:{course_role.value.upper()}"
                if course_role is not None
                else "COURSE_CREATOR"
            )
        elif group_role is not None and required_permission in GROUP_ROLE_PERMISSIONS.get(
            group_role, frozenset()
        ):
            reason = f"GROUP_ROLE:{group_role.value.upper()}"
        else:
            reason = f"GLOBAL_ROLE:{global_role.value.upper()}"
        return AuthorizationDecision(
            allowed=True,
            permission=required_permission,
            effective_permissions=effective,
            reason=reason,
            matched_roles=tuple(matched_roles),
        )

    return AuthorizationDecision(
        allowed=False,
        permission=required_permission,
        effective_permissions=effective,
        reason=f"MISSING_PERMISSION:{required_permission.value}",
        matched_roles=tuple(matched_roles),
    )


def hash_password(plain_password: str, rounds: int = 12) -> str:
    salt = bcrypt.gensalt(rounds=rounds)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def create_access_token(
    *,
    user_id: UUID,
    email: str,
    display_name: str,
    global_role: GlobalRole,
    settings: Settings,
    permissions: Iterable[Permission] | None = None,
    jti: str | None = None,
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expires_at = now + expires_delta
    resolved_permissions = (
        sorted({perm.value for perm in permissions})
        if permissions is not None
        else sorted(perm.value for perm in resolve_effective_permissions(global_role))
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "display_name": display_name,
        "global_role": global_role.value,
        "permissions": resolved_permissions,
        "token_type": TokenType.ACCESS.value,
        "jti": jti or str(uuid4()),
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = encode_jwt(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded, int(expires_delta.total_seconds())


def create_refresh_token(
    *,
    user_id: UUID,
    email: str,
    display_name: str,
    global_role: GlobalRole,
    settings: Settings,
    jti: str | None = None,
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    expires_at = now + expires_delta
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "display_name": display_name,
        "global_role": global_role.value,
        "permissions": [],
        "token_type": TokenType.REFRESH.value,
        "jti": jti or str(uuid4()),
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = encode_jwt(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded, int(expires_delta.total_seconds())


def decode_token(
    token: str,
    settings: Settings,
    *,
    expected_type: TokenType | None = TokenType.ACCESS,
) -> TokenClaims:
    raw = decode_jwt(
        token,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
    )

    try:
        sub = UUID(str(raw["sub"]))
        token_type = TokenType(str(raw["token_type"]))
        global_role = GlobalRole(str(raw.get("global_role", GlobalRole.USER.value)))
        raw_perms = raw.get("permissions", [])
        if not isinstance(raw_perms, list):
            raise ValueError("Invalid permissions claim")
        valid_perm_values = Permission._value2member_map_
        permissions = tuple(
            Permission(str(p)) for p in raw_perms if str(p) in valid_perm_values
        )
        iat = datetime.fromtimestamp(int(raw["iat"]), tz=UTC)
        exp = datetime.fromtimestamp(int(raw["exp"]), tz=UTC)
        email = str(raw.get("email", ""))
        display_name = str(raw.get("display_name", ""))
        jti = str(raw["jti"])
        iss = str(raw["iss"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AppError(ErrorCode.UNAUTHORIZED, "Malformed authentication token payload") from exc

    if expected_type is not None and token_type != expected_type:
        raise AppError(
            ErrorCode.UNAUTHORIZED,
            f"Expected {expected_type.value} token, got {token_type.value} token",
        )

    return TokenClaims(
        sub=sub,
        email=email,
        display_name=display_name,
        global_role=global_role,
        permissions=permissions,
        token_type=token_type,
        jti=jti,
        iss=iss,
        iat=iat,
        exp=exp,
    )
