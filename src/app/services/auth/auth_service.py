from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.authorization import (
    COURSE_ROLE_PERMISSIONS,
    GLOBAL_ROLE_PERMISSIONS,
    GROUP_ROLE_PERMISSIONS,
    AuthenticatedUser,
    CourseRole,
    GlobalRole,
    GroupRole,
    Permission,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    evaluate_permission,
    hash_password,
    resolve_effective_permissions,
    verify_password,
)
from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.models.academic_model import Course, Project, User
from app.repositories.auth_repository import AuthRepository
from app.schemas.auth_schema import (
    AssignCourseRoleRequest,
    AssignGroupRoleRequest,
    AuthTokenResponse,
    ChangePasswordRequest,
    CourseMembershipResponse,
    CourseMembershipSummary,
    GroupMembershipResponse,
    GroupMembershipSummary,
    LoginRequest,
    PermissionCheckRequest,
    PermissionCheckResponse,
    PermissionMatrixResponse,
    RefreshTokenRequest,
    RegisterRequest,
    UpdateGlobalRoleRequest,
    UserProfileResponse,
    UserResponse,
)

_LOCAL_SEED_COURSE_ID = UUID("00000000-0000-4000-8000-000000000002")
_LOCAL_SEED_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000003")
_LOCAL_SEED_GROUP_ID = UUID("00000000-0000-4000-8000-000000000004")


class AuthService:
    def __init__(self, repository: AuthRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    async def register(self, data: RegisterRequest) -> AuthTokenResponse:
        existing = await self.repository.get_user_by_email(data.email)
        if existing is not None:
            raise AppError(ErrorCode.DUPLICATE_RESOURCE, "Email already registered")

        password_hash = hash_password(
            data.password,
            rounds=self.settings.password_bcrypt_rounds,
        )
        try:
            user = await self.repository.create_user(
                email=data.email,
                display_name=data.display_name,
                password_hash=password_hash,
                global_role=GlobalRole.USER.value,
            )
        except IntegrityError as exc:
            raise AppError(ErrorCode.DUPLICATE_RESOURCE, "Email already registered") from exc

        if self.settings.app_env == "local":
            seed_course = await self.repository.get_course(_LOCAL_SEED_COURSE_ID)
            if seed_course is not None:
                await self.repository.upsert_course_membership(
                    course_id=_LOCAL_SEED_COURSE_ID,
                    user_id=user.id,
                    role=CourseRole.STUDENT.value,
                )
            seed_group = await self.repository.get_project_group(_LOCAL_SEED_GROUP_ID)
            if seed_group is not None:
                await self.repository.upsert_group_member(
                    group_id=_LOCAL_SEED_GROUP_ID,
                    project_id=_LOCAL_SEED_PROJECT_ID,
                    user_id=user.id,
                    role=GroupRole.MEMBER.value,
                )

        return self._issue_tokens_for_user(user)

    async def login(self, data: LoginRequest) -> AuthTokenResponse:
        user = await self.repository.get_user_by_email(data.email)
        if user is None or not verify_password(data.password, user.password_hash):
            raise AppError(ErrorCode.UNAUTHORIZED, "Invalid email or password")

        if not user.is_active:
            raise AppError(ErrorCode.FORBIDDEN, "User account is deactivated")

        return self._issue_tokens_for_user(user)

    async def refresh_tokens(self, data: RefreshTokenRequest) -> AuthTokenResponse:
        claims = decode_token(
            data.refresh_token,
            self.settings,
            expected_type=TokenType.REFRESH,
        )
        user = await self.repository.get_user_by_id(claims.sub)
        if user is None:
            raise AppError(ErrorCode.UNAUTHORIZED, "User not found")
        if not user.is_active:
            raise AppError(ErrorCode.FORBIDDEN, "User account is deactivated")

        return self._issue_tokens_for_user(user)

    async def authenticate_access_token(self, token: str) -> AuthenticatedUser:
        claims = decode_token(
            token,
            self.settings,
            expected_type=TokenType.ACCESS,
        )
        user = await self.repository.get_user_by_id(claims.sub)
        if user is None:
            raise AppError(ErrorCode.UNAUTHORIZED, "User not found")
        if not user.is_active:
            raise AppError(ErrorCode.FORBIDDEN, "User account is deactivated")

        global_role = self._parse_global_role(user.global_role)
        permissions = resolve_effective_permissions(global_role)
        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            global_role=global_role,
            is_active=user.is_active,
            permissions=permissions,
            token_jti=claims.jti,
        )

    async def get_profile(self, current_user: AuthenticatedUser) -> UserProfileResponse:
        user = await self.repository.get_user_by_id(current_user.id)
        if user is None:
            raise AppError(ErrorCode.NOT_FOUND, "User not found")

        course_rows = await self.repository.list_user_course_memberships(user.id)
        group_rows = await self.repository.list_user_group_memberships(user.id)

        course_summaries: list[CourseMembershipSummary] = []
        for membership, course in course_rows:
            c_role = self._parse_course_role(membership.role)
            c_perms = sorted(
                COURSE_ROLE_PERMISSIONS.get(c_role, frozenset()),
                key=lambda p: p.value,
            )
            course_summaries.append(
                CourseMembershipSummary(
                    course_id=course.id,
                    course_code=course.code,
                    course_name=course.name,
                    term=course.term,
                    role=c_role,
                    permissions=c_perms,
                )
            )

        group_summaries: list[GroupMembershipSummary] = []
        for member, group in group_rows:
            g_role = self._parse_group_role(member.role)
            g_perms = sorted(
                GROUP_ROLE_PERMISSIONS.get(g_role, frozenset()),
                key=lambda p: p.value,
            )
            group_summaries.append(
                GroupMembershipSummary(
                    group_id=group.id,
                    project_id=member.project_id,
                    group_name=group.name,
                    role=g_role,
                    permissions=g_perms,
                )
            )

        global_role = self._parse_global_role(user.global_role)
        global_perms = sorted(
            resolve_effective_permissions(global_role),
            key=lambda p: p.value,
        )

        return UserProfileResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            global_role=global_role,
            is_active=user.is_active,
            permissions=global_perms,
            created_at=getattr(user, "created_at", None),
            course_memberships=course_summaries,
            group_memberships=group_summaries,
        )

    async def change_password(
        self,
        current_user: AuthenticatedUser,
        data: ChangePasswordRequest,
    ) -> UserResponse:
        user = await self.repository.get_user_by_id(current_user.id)
        if user is None:
            raise AppError(ErrorCode.NOT_FOUND, "User not found")

        if not verify_password(data.current_password, user.password_hash):
            raise AppError(ErrorCode.UNAUTHORIZED, "Current password is incorrect")

        if data.current_password == data.new_password:
            raise AppError(
                ErrorCode.BAD_REQUEST,
                "New password must be different from current password",
            )

        new_hash = hash_password(
            data.new_password,
            rounds=self.settings.password_bcrypt_rounds,
        )
        updated = await self.repository.update_user_password(user.id, new_hash)
        if updated is None:
            raise AppError(ErrorCode.NOT_FOUND, "User not found")

        return self._to_user_response(updated)

    async def check_permission(
        self,
        actor: AuthenticatedUser,
        request: PermissionCheckRequest,
    ) -> PermissionCheckResponse:
        course_id = request.course_id
        project_id = request.project_id
        group_id = request.group_id
        submission_id = request.submission_id

        course: Course | None = None
        project: Project | None = None

        if submission_id is not None:
            submission = await self.repository.get_submission(submission_id)
            if submission is None:
                raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)
            if group_id is not None and submission.group_id != group_id:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    "Submission does not belong to the specified group",
                )
            if project_id is not None and submission.project_id != project_id:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    "Submission does not belong to the specified project",
                )
            group_id = submission.group_id
            project_id = submission.project_id

        if group_id is not None:
            group = await self.repository.get_project_group(group_id)
            if group is None:
                raise AppError(ErrorCode.NOT_FOUND, "Project group not found")
            if project_id is not None and group.project_id != project_id:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    "Group does not belong to the specified project",
                )
            project_id = group.project_id

        if project_id is not None:
            project = await self.repository.get_project(project_id)
            if project is None:
                raise AppError(ErrorCode.NOT_FOUND, "Project not found")
            if course_id is not None and project.course_id != course_id:
                raise AppError(
                    ErrorCode.BAD_REQUEST,
                    "Project does not belong to the specified course",
                )
            course_id = project.course_id

        if course_id is not None:
            course = await self.repository.get_course(course_id)
            if course is None:
                raise AppError(ErrorCode.NOT_FOUND, "Course not found")

        is_course_creator = bool(
            (course is not None and course.created_by == actor.id)
            or (project is not None and project.created_by == actor.id)
        )

        course_role: CourseRole | None = None
        if course_id is not None:
            raw_course_role = await self.repository.get_course_role(course_id, actor.id)
            if raw_course_role is not None:
                course_role = self._parse_course_role(raw_course_role)

        group_role: GroupRole | None = None
        if group_id is not None:
            raw_group_role = await self.repository.get_group_role(group_id, actor.id)
            if raw_group_role is not None:
                group_role = self._parse_group_role(raw_group_role)

        require_course_membership = course_id is not None
        require_group_membership = group_id is not None or submission_id is not None

        decision = evaluate_permission(
            request.permission,
            global_role=actor.global_role,
            course_role=course_role,
            group_role=group_role,
            is_course_creator=is_course_creator,
            require_course_membership=require_course_membership,
            require_group_membership_for_student=require_group_membership,
        )

        return PermissionCheckResponse(
            allowed=decision.allowed,
            permission=decision.permission,
            reason=decision.reason,
            matched_roles=list(decision.matched_roles),
            effective_permissions=sorted(
                decision.effective_permissions,
                key=lambda p: p.value,
            ),
            course_id=course_id,
            project_id=project_id,
            group_id=group_id,
            submission_id=submission_id,
        )

    async def enforce_permission(
        self,
        actor: AuthenticatedUser,
        permission: Permission,
        *,
        course_id: UUID | None = None,
        project_id: UUID | None = None,
        group_id: UUID | None = None,
        submission_id: UUID | None = None,
    ) -> PermissionCheckResponse:
        result = await self.check_permission(
            actor,
            PermissionCheckRequest(
                permission=permission,
                course_id=course_id,
                project_id=project_id,
                group_id=group_id,
                submission_id=submission_id,
            ),
        )
        if not result.allowed:
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"Permission '{permission.value}' denied ({result.reason})",
            )
        return result

    async def update_global_role(
        self,
        actor: AuthenticatedUser,
        target_user_id: UUID,
        data: UpdateGlobalRoleRequest,
    ) -> UserResponse:
        await self.enforce_permission(actor, Permission.USER_MANAGE)

        if actor.id == target_user_id and (
            data.global_role != GlobalRole.ADMIN or data.is_active is False
        ):
            raise AppError(
                ErrorCode.BAD_REQUEST,
                "Administrators cannot demote or deactivate their own account",
            )

        updated = await self.repository.update_user_role_and_status(
            target_user_id,
            global_role=data.global_role.value,
            is_active=data.is_active,
        )
        if updated is None:
            raise AppError(ErrorCode.NOT_FOUND, "Target user not found")

        return self._to_user_response(updated)

    async def assign_course_role(
        self,
        actor: AuthenticatedUser,
        course_id: UUID,
        target_user_id: UUID,
        data: AssignCourseRoleRequest,
    ) -> CourseMembershipResponse:
        await self.enforce_permission(
            actor,
            Permission.COURSE_MANAGE_MEMBERS,
            course_id=course_id,
        )
        course = await self.repository.get_course(course_id)
        if course is None:
            raise AppError(ErrorCode.NOT_FOUND, "Course not found")

        target_user = await self.repository.get_user_by_id(target_user_id)
        if target_user is None:
            raise AppError(ErrorCode.NOT_FOUND, "Target user not found")

        is_owner_or_admin = actor.is_admin or course.created_by == actor.id
        if target_user_id == course.created_by and data.role != CourseRole.INSTRUCTOR:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Cannot demote the primary course creator from instructor role",
            )
        existing_target_role = await self.repository.get_course_role(course_id, target_user_id)
        if not is_owner_or_admin and (
            data.role == CourseRole.INSTRUCTOR
            or existing_target_role == CourseRole.INSTRUCTOR.value
        ):
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only the primary course owner or admin can assign/modify other instructors",
            )

        membership = await self.repository.upsert_course_membership(
            course_id=course_id,
            user_id=target_user_id,
            role=data.role.value,
        )
        c_role = self._parse_course_role(membership.role)
        perms = sorted(
            COURSE_ROLE_PERMISSIONS.get(c_role, frozenset()),
            key=lambda p: p.value,
        )
        return CourseMembershipResponse(
            course_id=membership.course_id,
            user_id=membership.user_id,
            role=c_role,
            permissions=perms,
        )

    async def remove_course_member(
        self,
        actor: AuthenticatedUser,
        course_id: UUID,
        target_user_id: UUID,
    ) -> None:
        await self.enforce_permission(
            actor,
            Permission.COURSE_MANAGE_MEMBERS,
            course_id=course_id,
        )
        course = await self.repository.get_course(course_id)
        if course is None:
            raise AppError(ErrorCode.NOT_FOUND, "Course not found")

        if target_user_id == course.created_by:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Cannot remove the primary course creator from the course",
            )
        existing_target_role = await self.repository.get_course_role(course_id, target_user_id)
        is_owner_or_admin = actor.is_admin or course.created_by == actor.id
        if not is_owner_or_admin and existing_target_role == CourseRole.INSTRUCTOR.value:
            raise AppError(
                ErrorCode.FORBIDDEN,
                "Only the primary course owner or system admin can remove another instructor",
            )

        deleted = await self.repository.delete_course_membership(course_id, target_user_id)
        if not deleted:
            raise AppError(ErrorCode.NOT_FOUND, "Course membership not found")

    async def assign_group_role(
        self,
        actor: AuthenticatedUser,
        project_id: UUID,
        group_id: UUID,
        target_user_id: UUID,
        data: AssignGroupRoleRequest,
    ) -> GroupMembershipResponse:
        await self.enforce_permission(
            actor,
            Permission.GROUP_MANAGE_MEMBERS,
            project_id=project_id,
            group_id=group_id,
        )
        target_user = await self.repository.get_user_by_id(target_user_id)
        if target_user is None:
            raise AppError(ErrorCode.NOT_FOUND, "Target user not found")

        try:
            member = await self.repository.upsert_group_member(
                group_id=group_id,
                project_id=project_id,
                user_id=target_user_id,
                role=data.role.value,
            )
        except IntegrityError as exc:
            raise AppError(
                ErrorCode.CONFLICT,
                "User already belongs to another group in this project",
            ) from exc

        g_role = self._parse_group_role(member.role)
        perms = sorted(
            GROUP_ROLE_PERMISSIONS.get(g_role, frozenset()),
            key=lambda p: p.value,
        )
        return GroupMembershipResponse(
            group_id=member.group_id,
            project_id=member.project_id,
            user_id=member.user_id,
            role=g_role,
            permissions=perms,
        )

    async def remove_group_member(
        self,
        actor: AuthenticatedUser,
        project_id: UUID,
        group_id: UUID,
        target_user_id: UUID,
    ) -> None:
        await self.enforce_permission(
            actor,
            Permission.GROUP_MANAGE_MEMBERS,
            project_id=project_id,
            group_id=group_id,
        )
        deleted = await self.repository.delete_group_member(group_id, target_user_id)
        if not deleted:
            raise AppError(ErrorCode.NOT_FOUND, "Group membership not found")

    @staticmethod
    def get_permission_matrix() -> PermissionMatrixResponse:
        return PermissionMatrixResponse(
            global_roles={
                role.value: sorted(perms, key=lambda p: p.value)
                for role, perms in GLOBAL_ROLE_PERMISSIONS.items()
            },
            course_roles={
                role.value: sorted(perms, key=lambda p: p.value)
                for role, perms in COURSE_ROLE_PERMISSIONS.items()
            },
            group_roles={
                role.value: sorted(perms, key=lambda p: p.value)
                for role, perms in GROUP_ROLE_PERMISSIONS.items()
            },
        )

    def _issue_tokens_for_user(self, user: User) -> AuthTokenResponse:
        global_role = self._parse_global_role(user.global_role)
        permissions = resolve_effective_permissions(global_role)
        access_token, expires_in = create_access_token(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            global_role=global_role,
            settings=self.settings,
            permissions=permissions,
        )
        refresh_token, refresh_expires_in = create_refresh_token(
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            global_role=global_role,
            settings=self.settings,
        )
        return AuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
            refresh_expires_in=refresh_expires_in,
            user=self._to_user_response(user),
        )

    def _to_user_response(self, user: User) -> UserResponse:
        global_role = self._parse_global_role(user.global_role)
        permissions = sorted(
            resolve_effective_permissions(global_role),
            key=lambda p: p.value,
        )
        return UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            global_role=global_role,
            is_active=user.is_active,
            permissions=permissions,
            created_at=getattr(user, "created_at", None),
        )

    @staticmethod
    def _parse_global_role(value: str) -> GlobalRole:
        try:
            return GlobalRole(value)
        except ValueError:
            return GlobalRole.USER

    @staticmethod
    def _parse_course_role(value: str) -> CourseRole:
        try:
            return CourseRole(value)
        except ValueError:
            return CourseRole.STUDENT

    @staticmethod
    def _parse_group_role(value: str) -> GroupRole:
        try:
            return GroupRole(value)
        except ValueError:
            return GroupRole.MEMBER

