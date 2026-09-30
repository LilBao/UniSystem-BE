import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_model import (
    CodeConsistencyVerdict as CodeConsistencyVerdictModel,
)
from app.models.evaluation_model import (
    EvidenceItem,
    EvidencePack,
    PipelineResult,
    PipelineResultEvidence,
)
from app.models.layer1_model import Claim, CodeGraphSnapshot
from app.models.pipeline_model import PipelineRun
from app.models.submission_model import Artifact
from app.schemas.code_graph_schema import CodeGraph
from app.schemas.p3_schema import (
    CodeConsistencyResult,
    P3WorkItem,
    VisualGraphResponse,
)


class P3Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_work_items(self, submission_id: UUID) -> list[P3WorkItem]:
        """Lấy danh sách các claim cần kiểm chứng tính nhất quán với code."""
        # Ưu tiên lấy claims có claim_type == "implementation", nếu không có thì lấy tất cả
        statement = (
            select(Claim)
            .where(Claim.submission_id == submission_id)
            .order_by(Claim.created_at)
        )
        claims = list((await self.session.scalars(statement)).all())
        implementation_claims = [
            c for c in claims if c.claim_type == "implementation"
        ]
        selected_claims = implementation_claims if implementation_claims else claims

        return [
            P3WorkItem(
                claim_id=claim.id,
                text_content=claim.text_content,
                is_atomic=claim.is_atomic,
                is_central=claim.is_central,
                impact=claim.impact,
                testability=claim.testability,
                risk=claim.risk,
                qualifiers=claim.qualifiers,
                source_span=claim.source_span,
                source_block_id=claim.source_block_id,
            )
            for claim in selected_claims
        ]

    async def get_latest_graph_snapshot(
        self, submission_id: UUID
    ) -> CodeGraphSnapshot | None:
        """Lấy CodeGraphSnapshot mới nhất do Layer 1 trích xuất."""
        statement = (
            select(CodeGraphSnapshot)
            .where(CodeGraphSnapshot.submission_id == submission_id)
            .order_by(CodeGraphSnapshot.created_at.desc())
            .limit(1)
        )
        return (await self.session.scalars(statement)).one_or_none()

    async def load_code_graph(self, snapshot: CodeGraphSnapshot | None) -> CodeGraph:
        """Tải dữ liệu CodeGraph từ Artifact."""
        if snapshot is None:
            return CodeGraph(nodes=[], edges=[])

        statement = select(Artifact).where(Artifact.id == snapshot.graph_artifact_id)
        artifact = (await self.session.scalars(statement)).one_or_none()
        if artifact is None or not artifact.object_uri:
            return CodeGraph(nodes=[], edges=[])

        # Thử đọc từ đường dẫn file cục bộ nếu có
        file_path = Path(artifact.object_uri)
        if file_path.is_file():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                return CodeGraph.model_validate(data)
            except Exception:
                pass

        return CodeGraph(nodes=[], edges=[])

    async def save_result(
        self,
        submission_id: UUID,
        pipeline_run_id: UUID,
        snapshot_id: UUID | None,
        work_item: P3WorkItem,
        result: CodeConsistencyResult,
    ) -> None:
        """Lưu trữ kết quả kiểm chứng vào Database.

        Bao gồm: EvidencePack, EvidenceItem, PipelineResult, CodeConsistencyVerdict.
        """
        pack = EvidencePack(
            id=uuid4(),
            submission_id=submission_id,
            claim_id=work_item.claim_id,
            rubric_criterion_id=None,
            pipeline_run_id=pipeline_run_id,
            coverage={
                "verification_stage": result.verification_stage.value,
                "stages": [s.value for s in result.stage_history],
                "evidence_count": len(result.evidence_locations),
                "mismatch_count": len(result.mismatch_witnesses),
            },
            created_by="pipeline-p3",
        )
        self.session.add(pack)
        await self.session.flush()

        evidence_models: list[EvidenceItem] = []
        for loc in result.evidence_locations:
            evidence_id = uuid4()
            evidence_models.append(
                EvidenceItem(
                    id=evidence_id,
                    evidence_pack_id=pack.id,
                    source_type="code",
                    source_id=snapshot_id,
                    source_uri=loc.path,
                    text_snapshot=None,
                    location={
                        "path": loc.path,
                        "start_line": loc.start_line,
                        "end_line": loc.end_line,
                    },
                    provenance="graphify",
                    retrieval_score=result.confidence,
                    rerank_score=None,
                    supports_atoms=[],
                    contradicts_atoms=[],
                    access_status="local",
                    content_sha256=None,
                )
            )
        self.session.add_all(evidence_models)
        await self.session.flush()

        pipeline_result = PipelineResult(
            id=uuid4(),
            pipeline_run_id=pipeline_run_id,
            subject_type="claim",
            subject_id=work_item.claim_id,
            status="succeeded",
            verdict=result.verdict.value,
            confidence=Decimal(str(result.confidence)),
            reason_codes=result.reason_codes,
            escalation_history=[s.value for s in result.stage_history],
            result={
                "verification_stage": result.verification_stage.value,
                "requires_review": result.requires_review,
                "rationale": result.rationale,
                "mismatch_witnesses": [
                    w.model_dump(mode="json") for w in result.mismatch_witnesses
                ],
            },
        )
        self.session.add(pipeline_result)
        await self.session.flush()

        # Liên kết bằng chứng
        links = [
            PipelineResultEvidence(
                pipeline_result_id=pipeline_result.id,
                evidence_item_id=ev.id,
                usage="support" if result.verdict == "CONSISTENT" else "contradict",
            )
            for ev in evidence_models
        ]
        self.session.add_all(links)

        # Lưu CodeConsistencyVerdict Model
        self.session.add(
            CodeConsistencyVerdictModel(
                id=uuid4(),
                pipeline_result_id=pipeline_result.id,
                claim_id=work_item.claim_id,
                graph_snapshot_id=snapshot_id,
                verdict=result.verdict.value,
                verification_stage=result.verification_stage.value,
                confidence=Decimal(str(result.confidence)),
                requires_review=result.requires_review,
            )
        )
        await self.session.flush()

    async def get_visual_graph(
        self,
        submission_id: UUID,
        filter_mode: str = "all",
        min_importance: float = 0.0,
    ) -> VisualGraphResponse | None:
        """Lấy dữ liệu visual graph đã lưu từ pipeline run mới nhất."""
        statement = (
            select(PipelineRun)
            .where(
                PipelineRun.submission_id == submission_id,
                PipelineRun.pipeline == "P3",
                PipelineRun.status.in_(("succeeded", "partial", "requires_review")),
            )
            .order_by(PipelineRun.finished_at.desc())
            .limit(1)
        )
        run = (await self.session.scalars(statement)).one_or_none()
        if run is None or not run.metrics:
            return None

        cached_graph = run.metrics.get("visual_graph")
        if not cached_graph or not isinstance(cached_graph, dict):
            return None

        try:
            return VisualGraphResponse.model_validate(cached_graph)
        except Exception:
            return None
