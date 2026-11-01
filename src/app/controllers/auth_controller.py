from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.core.authorization import AuthenticatedUser
from app.dependencies import get_auth_service, get_current_user
from app.schemas.auth_schema import (
    AssignCourseRoleRequest,
    AssignGroupRoleRequest,
    AuthTokenResponse,
    ChangePasswordRequest,
    CourseMembershipResponse,
    GroupMembershipResponse,
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
from app.services.auth.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Authorization"])


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokenResponse:
    """Đăng ký tài khoản mới và cấp cặp JWT (access_token + refresh_token)."""
    return await service.register(body)


@router.post("/login", response_model=AuthTokenResponse)
async def login(
    body: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokenResponse:
    """Đăng nhập bằng email/password và nhận cặp JWT."""
    return await service.login(body)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthTokenResponse:
    """Làm mới access_token và refresh_token từ refresh_token hợp lệ."""
    return await service.refresh_tokens(body)


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    """Lấy thông tin tài khoản hiện tại cùng danh sách vai trò và quyền hạn theo khóa học/nhóm."""
    return await service.get_profile(current_user)


@router.post("/change-password", response_model=UserResponse)
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Đổi mật khẩu cho tài khoản đang đăng nhập."""
    return await service.change_password(current_user, body)


@router.get("/permissions/matrix", response_model=PermissionMatrixResponse)
async def get_permission_matrix(
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PermissionMatrixResponse:
    """Trả về ma trận phân quyền chi tiết (RBAC) theo Global Role, Course Role và Group Role."""
    return service.get_permission_matrix()


@router.post("/permissions/check", response_model=PermissionCheckResponse)
async def check_permission(
    body: PermissionCheckRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PermissionCheckResponse:
    """Kiểm tra quyền chi tiết của user hiện tại trên phạm vi tài nguyên."""
    return await service.check_permission(current_user, body)


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_global_role(
    user_id: UUID,
    body: UpdateGlobalRoleRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserResponse:
    """Cập nhật vai trò toàn cục (user/admin) hoặc trạng thái hoạt động (chỉ dành cho Admin)."""
    return await service.update_global_role(current_user, user_id, body)


@router.put(
    "/courses/{course_id}/memberships/{user_id}",
    response_model=CourseMembershipResponse,
)
async def assign_course_role(
    course_id: UUID,
    user_id: UUID,
    body: AssignCourseRoleRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> CourseMembershipResponse:
    """Gán hoặc cập nhật vai trò trong khóa học (instructor/ta/student/reviewer)."""
    return await service.assign_course_role(current_user, course_id, user_id, body)


@router.delete(
    "/courses/{course_id}/memberships/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_course_member(
    course_id: UUID,
    user_id: UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    """Xóa thành viên khỏi khóa học."""
    await service.remove_course_member(current_user, course_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/projects/{project_id}/groups/{group_id}/members/{user_id}",
    response_model=GroupMembershipResponse,
)
async def assign_group_role(
    project_id: UUID,
    group_id: UUID,
    user_id: UUID,
    body: AssignGroupRoleRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> GroupMembershipResponse:
    """Gán hoặc cập nhật vai trò thành viên trong nhóm đồ án (leader/member)."""
    return await service.assign_group_role(
        current_user,
        project_id,
        group_id,
        user_id,
        body,
    )


@router.delete(
    "/projects/{project_id}/groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    project_id: UUID,
    group_id: UUID,
    user_id: UUID,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    """Xóa thành viên khỏi nhóm đồ án."""
    await service.remove_group_member(current_user, project_id, group_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
