import hashlib
from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_model import CitationVerdict as CitationVerdictModel
from app.models.evaluation_model import (
    ClaimReference,
    EvidenceItem,
    EvidencePack,
    PipelineResult,
    PipelineResultEvidence,
)
from app.models.layer1_model import Claim
from app.models.reference_model import (
    ReferenceDocument,
    ReferencePassage,
    SubmissionReference,
)
from app.schemas.p2_schema import (
    CitationEvidence,
    CitationVerificationInput,
    CitationVerificationResult,
    CitationWorkItem,
)


class P2Repository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_work_items(self, submission_id: UUID) -> list[CitationWorkItem]:
        statement = (
            select(Claim, SubmissionReference, ReferenceDocument)
            .join(ClaimReference, ClaimReference.claim_id == Claim.id)
            .join(
                SubmissionReference,
                SubmissionReference.id == ClaimReference.submission_reference_id,
            )
            .outerjoin(
                ReferenceDocument,
                ReferenceDocument.id == SubmissionReference.reference_document_id,
            )
            .where(Claim.submission_id == submission_id)
            .order_by(Claim.id, SubmissionReference.marker)
        )
        rows = list((await self.session.execute(statement)).all())
        document_ids = {document.id for _, _, document in rows if document is not None}
        passages_by_document: dict[UUID, list[ReferencePassage]] = defaultdict(list)
        if document_ids:
            passage_statement = (
                select(ReferencePassage)
                .where(
                    ReferencePassage.reference_document_id.in_(document_ids),
                    ReferencePassage.is_active.is_(True),
                    ReferencePassage.access_level.in_(("abstract", "full_text")),
                )
                .order_by(ReferencePassage.reference_document_id, ReferencePassage.ordinal)
            )
            for passage in (await self.session.scalars(passage_statement)).all():
                passages_by_document[passage.reference_document_id].append(passage)

        work_items: list[CitationWorkItem] = []
        for claim, reference, document in rows:
            evidence: list[CitationEvidence] = []
            if document is not None:
                for passage in passages_by_document[document.id]:
                    evidence.append(
                        CitationEvidence(
                            source_type="reference_passage",
                            source_id=passage.id,
                            text=passage.content,
                            location={
                                "page_start": passage.page_start,
                                "page_end": passage.page_end,
                                "section_path": passage.section_path,
                                "block_type": passage.block_type,
                            },
                            access_status=passage.access_level,
                            content_sha256=passage.content_sha256,
                        )
                    )
                abstract = document.metadata_json.get("abstract")
                if not evidence and isinstance(abstract, str) and abstract.strip():
                    normalized = abstract.strip()
                    evidence.append(
                        CitationEvidence(
                            source_type="reference_abstract",
                            source_id=document.id,
                            text=normalized,
                            location={"field": "abstract"},
                            access_status="abstract",
                            content_sha256=hashlib.sha256(normalized.encode()).hexdigest(),
                        )
                    )

            work_items.append(
                CitationWorkItem(
                    input=CitationVerificationInput(
                        claim_id=claim.id,
                        text_content=claim.text_content,
                        is_atomic=claim.is_atomic,
                        qualifiers=claim.qualifiers,
                        citation_marker=reference.marker,
                        submission_reference_id=reference.id,
                        reference_document_id=(document.id if document is not None else None),
                    ),
                    evidence=evidence,
                )
            )
        return work_items

    async def save_result(
        self,
        submission_id: UUID,
        pipeline_run_id: UUID,
        work_item: CitationWorkItem,
        result: CitationVerificationResult,
    ) -> None:
        pack = EvidencePack(
            id=uuid4(),
            submission_id=submission_id,
            claim_id=work_item.input.claim_id,
            rubric_criterion_id=None,
            pipeline_run_id=pipeline_run_id,
            coverage={
                "citation_marker": work_item.input.citation_marker,
                "available_evidence_count": len(work_item.evidence),
                "used_evidence_count": len(result.evidence),
                "verification_stage": result.verification_stage.value,
                "verification_stages": [stage.value for stage in result.stage_history],
                "atomic_claim_count": len(result.atomic_claims),
            },
            created_by="pipeline-p2",
        )
        self.session.add(pack)
        await self.session.flush()

        item_ids_by_source: dict[UUID, UUID] = {}
        supports_by_source: dict[UUID, set[str]] = defaultdict(set)
        contradicts_by_source: dict[UUID, set[str]] = defaultdict(set)
        for assessment in result.atom_assessments:
            for source_id in assessment.supporting_evidence_ids:
                supports_by_source[source_id].add(assessment.atom_id)
            for source_id in assessment.contradicting_evidence_ids:
                contradicts_by_source[source_id].add(assessment.atom_id)
        evidence_models: list[EvidenceItem] = []
        for evidence in result.evidence:
            evidence_id = uuid4()
            item_ids_by_source[evidence.source_id] = evidence_id
            source_type = (
                evidence.source_type if evidence.source_type == "reference_passage" else "other"
            )
            location = dict(evidence.location)
            if source_type == "other":
                location["original_source_type"] = evidence.source_type
            evidence_models.append(
                EvidenceItem(
                    id=evidence_id,
                    evidence_pack_id=pack.id,
                    source_type=source_type,
                    source_id=evidence.source_id,
                    source_uri=None,
                    text_snapshot=evidence.text,
                    location=location,
                    provenance=("retrieved" if source_type == "reference_passage" else "parsed"),
                    retrieval_score=evidence.retrieval_score,
                    rerank_score=evidence.rerank_score,
                    supports_atoms=sorted(supports_by_source[evidence.source_id]),
                    contradicts_atoms=sorted(contradicts_by_source[evidence.source_id]),
                    access_status=evidence.access_status,
                    content_sha256=evidence.content_sha256,
                )
            )
        self.session.add_all(evidence_models)
        await self.session.flush()

        pipeline_result = PipelineResult(
            id=uuid4(),
            pipeline_run_id=pipeline_run_id,
            subject_type="claim",
            subject_id=work_item.input.claim_id,
            status=result.status.value,
            verdict=result.verdict.value if result.verdict is not None else None,
            confidence=result.confidence,
            reason_codes=result.reason_codes,
            escalation_history=[],
            result={
                "citation_marker": work_item.input.citation_marker,
                "submission_reference_id": str(work_item.input.submission_reference_id),
                "reference_document_id": (
                    str(work_item.input.reference_document_id)
                    if work_item.input.reference_document_id is not None
                    else None
                ),
                "verification_stage": result.verification_stage.value,
                "verification_stages": [stage.value for stage in result.stage_history],
                "requires_review": result.requires_review,
                "rationale": result.rationale,
                "atomic_claims": [item.model_dump(mode="json") for item in result.atomic_claims],
                "atom_assessments": [
                    item.model_dump(mode="json") for item in result.atom_assessments
                ],
            },
        )
        self.session.add(pipeline_result)
        await self.session.flush()

        links = []
        for evidence in result.evidence:
            if evidence.source_id not in item_ids_by_source:
                continue
            supports = supports_by_source[evidence.source_id]
            contradicts = contradicts_by_source[evidence.source_id]
            usage = "context"
            if supports and not contradicts:
                usage = "support"
            elif contradicts and not supports:
                usage = "contradict"
            links.append(
                PipelineResultEvidence(
                    pipeline_result_id=pipeline_result.id,
                    evidence_item_id=item_ids_by_source[evidence.source_id],
                    usage=usage,
                )
            )
        self.session.add_all(links)

        if result.verdict is not None and result.confidence is not None:
            self.session.add(
                CitationVerdictModel(
                    id=uuid4(),
                    pipeline_result_id=pipeline_result.id,
                    claim_id=work_item.input.claim_id,
                    verdict=result.verdict.value,
                    confidence=result.confidence,
                    pair_accuracy_label=(
                        True
                        if result.verdict.value == "SUPPORT"
                        else False
                        if result.verdict.value == "REFUTE"
                        else None
                    ),
                    requires_review=result.requires_review,
                )
            )

        await self.session.flush()
