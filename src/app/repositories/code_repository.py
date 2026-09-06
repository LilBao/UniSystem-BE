from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.layer1_model import CodeGraphSnapshot
from app.models.submission_model import Artifact
from app.schemas.layer1_schema import SourceCodeRepresentation


class CodeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_graph_snapshot(
        self, submission_id: UUID, representation: SourceCodeRepresentation
    ) -> CodeGraphSnapshot:
        graph_artifact = Artifact(
            id=uuid4(),
            submission_id=submission_id,
            kind="code_graph",
            version_no=1,
            object_uri=representation.graph_object_uri,
            media_type="application/json",
            byte_size=representation.graph_byte_size,
            sha256=representation.graph_sha256,
            metadata_json={
                "schema_version": representation.schema_version,
                "graphify_version": representation.graphify_version,
            },
        )
        self.session.add(graph_artifact)
        await self.session.flush()

        snapshot = CodeGraphSnapshot(
            id=uuid4(),
            submission_id=submission_id,
            source_artifact_id=representation.source_artifact_id,
            graph_artifact_id=graph_artifact.id,
            source_sha256=representation.source_sha256,
            graphify_version=representation.graphify_version,
            schema_version=representation.schema_version,
            node_count=representation.node_count,
            edge_count=representation.edge_count,
            provenance_summary={
                key.value: value for key, value in representation.provenance_summary.items()
            },
        )
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot
