from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic_model import GroupMember, Project, RubricVersion
from app.models.submission_model import Artifact, Submission


class SubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_project_is_open(self, project_id: UUID) -> bool:
        statement = select(Project.id).where(
            Project.id == project_id,
            Project.status == "open",
        )
        return await self.session.scalar(statement) is not None

    async def check_rubric_is_published(self, rubric_version_id: UUID) -> bool:
        statement = select(RubricVersion.id).where(
            RubricVersion.id == rubric_version_id,
            RubricVersion.status == "published",
        )
        return await self.session.scalar(statement) is not None

    async def check_user_in_group(self, group_id: UUID, user_id: UUID) -> bool:
        statement = select(GroupMember.user_id).where(
            GroupMember.group_id == group_id,
            GroupMember.user_id == user_id,
        )
        return await self.session.scalar(statement) is not None

    async def create(self, values: dict[str, Any]) -> Submission:
        submission = Submission(**values)
        self.session.add(submission)
        await self.session.flush()
        await self.session.refresh(submission)
        return submission

    async def get_for_update(self, submission_id: UUID) -> Submission | None:
        statement = (
            select(Submission)
            .where(Submission.id == submission_id)
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def list_artifacts(self, submission_id: UUID) -> list[Artifact]:
        statement = (
            select(Artifact)
            .where(Artifact.submission_id == submission_id)
            .order_by(Artifact.kind, Artifact.version_no.desc())
        )
        return list((await self.session.scalars(statement)).all())

    async def get(self, submission_id: UUID) -> Submission | None:
        return await self.session.get(Submission, submission_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Submission | None:
        statement = select(Submission).where(Submission.idempotency_key == idempotency_key)
        return (await self.session.scalars(statement)).one_or_none()

    async def get_latest_artifact(self, submission_id: UUID, kind: str) -> Artifact | None:
        statement = (
            select(Artifact)
            .where(
                Artifact.submission_id == submission_id,
                Artifact.kind == kind,
            )
            .order_by(Artifact.version_no.desc())
            .limit(1)
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def get_latest_artifact_id(self, submission_id: UUID, kind: str) -> UUID | None:
        statement = (
            select(Artifact.id)
            .where(
                Artifact.submission_id == submission_id,
                Artifact.kind == kind,
            )
            .order_by(Artifact.version_no.desc())
            .limit(1)
        )
        return cast(UUID | None, await self.session.scalar(statement))

    async def create_artifact(self, values: dict[str, Any]) -> Artifact:
        artifact_values = dict(values)
        artifact_values["metadata_json"] = artifact_values.pop("metadata", {})
        artifact = Artifact(**artifact_values)
        self.session.add(artifact)
        await self.session.flush()
        await self.session.refresh(artifact)
        return artifact

    async def update_status(self, submission_id: UUID, new_status: str) -> None:
        submission = await self.session.get(Submission, submission_id)
        if submission is None:
            return
        submission.status = new_status
        await self.session.flush()
