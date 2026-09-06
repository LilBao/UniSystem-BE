from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pipeline_model import PipelineRun


class PipelineRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_run(self, values: dict[str, Any]) -> PipelineRun:
        run = PipelineRun(**values)
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_run_for_update(self, run_id: UUID) -> PipelineRun | None:
        statement = (
            select(PipelineRun)
            .where(PipelineRun.id == run_id)
            .with_for_update()
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def mark_succeeded(self, run_id: UUID, output_fingerprint: str) -> None:
        run = await self.get_run_for_update(run_id)
        if run is None:
            return
        run.status = "succeeded"
        run.output_fingerprint = output_fingerprint
        run.finished_at = datetime.now(UTC)
        await self.session.flush()

    async def mark_failed(self, run_id: UUID, error: dict[str, Any]) -> None:
        run = await self.get_run_for_update(run_id)
        if run is None:
            return
        run.status = "failed"
        run.error = error
        run.finished_at = datetime.now(UTC)
        await self.session.flush()
