import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.adapters.archive import SafeZipExtractor, inventory
from app.adapters.graphify import GraphifyAdapter
from app.core.config import Settings
from app.models.submission_model import Artifact
from app.repositories.artifact_repository import ArtifactRepository, GraphArtifactWriter
from app.schemas.layer1_schema import SourceCodeRepresentation


class SourceCodePreprocessingService:
    def __init__(
        self,
        reader: ArtifactRepository,
        extractor: SafeZipExtractor,
        parser: GraphifyAdapter,
        writer: GraphArtifactWriter,
        settings: Settings,
    ) -> None:
        self.reader, self.extractor, self.parser = reader, extractor, parser
        self.writer, self.settings = writer, settings

    async def process(
        self,
        submission_id: UUID,
        source_artifact_id: UUID,
    ) -> SourceCodeRepresentation:
        artifact = await self.reader.get_owned(submission_id, source_artifact_id, "source_archive")
        return await self.process_artifact(artifact)

    async def process_artifact(self, artifact: Artifact) -> SourceCodeRepresentation:
        source_artifact_id = artifact.id
        submission_id = artifact.submission_id
        if submission_id is None:
            raise ValueError("Source artifact is not owned by a submission")
        with TemporaryDirectory(prefix="source-") as temporary:
            workspace = Path(temporary)
            archive, repository = workspace / "source.zip", workspace / "repository"
            repository.mkdir()
            await self.reader.download_to(artifact, archive, self.settings.max_source_bytes)
            await self.extractor.extract(archive, repository)
            detected = await run_in_threadpool(inventory, repository, self.settings)

            filtered = workspace / "filtered"
            filtered.mkdir()
            for item in detected["files"]:
                target = filtered / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repository / item["path"], target)
            graph = await self.parser.build(filtered, detected)
            graph.validate_inventory(detected["files"])
            summary = Counter(element.provenance for element in [*graph.nodes, *graph.edges])

            graphify_version = self.parser.version
            payload = graph.model_dump(mode="json")
            payload.update(
                {
                    "generator": {"name": "graphify", "version": graphify_version},
                    "source": {"artifact_id": str(source_artifact_id), "sha256": artifact.sha256},
                    "repository": detected,
                    "provenance_summary": dict(summary),
                    "status": "partial" if graph.warnings else "complete",
                }
            )
            serialized = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            digest = hashlib.sha256(serialized).hexdigest()
            graph_file = workspace / "graph.json"
            graph_file.write_bytes(serialized)
            uri = await self.writer.upload(submission_id, graph_file, digest)
            return SourceCodeRepresentation(
                source_artifact_id=source_artifact_id,
                graph_object_uri=uri,
                graphify_version=graphify_version,
                schema_version=graph.schema_version,
                source_sha256=artifact.sha256,
                graph_sha256=digest,
                graph_byte_size=len(serialized),
                node_count=len(graph.nodes),
                edge_count=len(graph.edges),
                provenance_summary=dict(summary),
            )
