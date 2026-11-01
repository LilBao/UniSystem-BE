from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_model import (
    Course,
    CourseMembership,
    GroupMember,
    Project,
    ProjectGroup,
    User,
)
from app.models.submission_model import Submission


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_user_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        statement = select(User).where(func.lower(User.email) == normalized)
        return (await self.session.scalars(statement)).one_or_none()

    async def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        global_role: str = "user",
    ) -> User:
        user = User(
            email=email.strip().lower(),
            display_name=display_name.strip(),
            password_hash=password_hash,
            global_role=global_role,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update_user_password(self, user_id: UUID, password_hash: str) -> User | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.password_hash = password_hash
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update_user_role_and_status(
        self,
        user_id: UUID,
        *,
        global_role: str,
        is_active: bool | None = None,
    ) -> User | None:
        user = await self.session.get(User, user_id)
        if user is None:
            return None
        user.global_role = global_role
        if is_active is not None:
            user.is_active = is_active
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def get_course(self, course_id: UUID) -> Course | None:
        return await self.session.get(Course, course_id)

    async def get_project(self, project_id: UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def get_project_group(self, group_id: UUID) -> ProjectGroup | None:
        return await self.session.get(ProjectGroup, group_id)

    async def get_submission(self, submission_id: UUID) -> Submission | None:
        return await self.session.get(Submission, submission_id)

    async def get_course_role(self, course_id: UUID, user_id: UUID) -> str | None:
        statement = select(CourseMembership.role).where(
            CourseMembership.course_id == course_id,
            CourseMembership.user_id == user_id,
        )
        result = await self.session.scalar(statement)
        return str(result) if result is not None else None

    async def get_group_role(self, group_id: UUID, user_id: UUID) -> str | None:
        statement = select(GroupMember.role).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
        result = await self.session.scalar(statement)
        return str(result) if result is not None else None

    async def list_user_course_memberships(
        self, user_id: UUID
    ) -> list[tuple[CourseMembership, Course]]:
        statement = (
            select(CourseMembership, Course)
            .join(Course, CourseMembership.course_id == Course.id)
            .where(CourseMembership.user_id == user_id)
            .order_by(Course.term.desc(), Course.code.asc())
        )
        rows = (await self.session.execute(statement)).all()
        return [(row[0], row[1]) for row in rows]

    async def list_user_group_memberships(
        self, user_id: UUID
    ) -> list[tuple[GroupMember, ProjectGroup]]:
        statement = (
            select(GroupMember, ProjectGroup)
            .join(ProjectGroup, GroupMember.group_id == ProjectGroup.id)
            .where(GroupMember.user_id == user_id)
            .order_by(ProjectGroup.name.asc())
        )
        rows = (await self.session.execute(statement)).all()
        return [(row[0], row[1]) for row in rows]

    async def upsert_course_membership(
        self,
        course_id: UUID,
        user_id: UUID,
        role: str,
    ) -> CourseMembership:
        existing = await self.session.get(CourseMembership, (course_id, user_id))
        if existing is not None:
            existing.role = role
            await self.session.flush()
            return existing
        membership = CourseMembership(
            course_id=course_id,
            user_id=user_id,
            role=role,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def delete_course_membership(self, course_id: UUID, user_id: UUID) -> bool:
        existing = await self.session.get(CourseMembership, (course_id, user_id))
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True

    async def upsert_group_member(
        self,
        group_id: UUID,
        project_id: UUID,
        user_id: UUID,
        role: str,
    ) -> GroupMember:
        existing = await self.session.get(GroupMember, (group_id, user_id))
        if existing is not None:
            existing.role = role
            await self.session.flush()
            return existing
        member = GroupMember(
            group_id=group_id,
            project_id=project_id,
            user_id=user_id,
            role=role,
        )
        self.session.add(member)
        await self.session.flush()
        return member

    async def delete_group_member(self, group_id: UUID, user_id: UUID) -> bool:
        existing = await self.session.get(GroupMember, (group_id, user_id))
        if existing is None:
            return False
        await self.session.delete(existing)
        await self.session.flush()
        return True

