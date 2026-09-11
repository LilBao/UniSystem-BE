from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation_model import ClaimReference
from app.models.reference_model import (
    ReferenceDocument,
    SubmissionReference,
)
from app.schemas.layer1_schema import ExtractedClaim
from app.schemas.reference_schema import ExtractedReference, ReferenceCandidate


class ReferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_submission_references(
        self,
        submission_id: UUID,
        references: Sequence[ExtractedReference],
    ) -> dict[str, UUID]:
        reference_ids: dict[str, UUID] = {}
        models: list[SubmissionReference] = []
        for reference in references:
            reference_id = uuid4()
            reference_ids[reference.marker] = reference_id

            models.append(
                SubmissionReference(
                    id=reference_id,
                    submission_id=submission_id,
                    marker=reference.marker,
                    raw_citation=reference.raw_citation,
                    reference_document_id=None,
                    resolver_status="unresolved",
                    resolver_confidence=None,
                    resolver_version=None,
                    metadata_json={
                        "source_block_external_id":
                            reference.source_block_external_id
                    },
                )
            )

        self.session.add_all(models)
        await self.session.flush()

        return reference_ids

    async def save_claim_reference_links(
        self,
        claims: Sequence[ExtractedClaim],
        claim_ids: dict[str, UUID],
        reference_ids: dict[str, UUID],
    ) -> None:
        links: list[ClaimReference] = []
        seen: set[tuple[UUID, UUID]] = set()

        for claim in claims:
            claim_id = claim_ids[claim.external_id]

            for marker in claim.citation_markers:
                reference_id = reference_ids.get(marker)
                if reference_id is None:
                    continue

                key = (claim_id, reference_id)
                if key in seen:
                    continue

                seen.add(key)
                links.append(
                    ClaimReference(
                        claim_id=claim_id,
                        submission_reference_id=reference_id,
                    )
                )

        self.session.add_all(links)
        await self.session.flush()

    async def list_unresolved(
        self,
        submission_id: UUID,
    ) -> list[SubmissionReference]:
        statement = (
            select(SubmissionReference)
            .where(
                SubmissionReference.submission_id == submission_id,
                SubmissionReference.resolver_status
                == "unresolved",
            )
            .order_by(SubmissionReference.marker)
        )

        return list(
            (await self.session.scalars(statement)).all()
        )

    async def find_document_by_doi(
        self,
        doi: str,
    ) -> ReferenceDocument | None:
        statement = select(ReferenceDocument).where(
            func.lower(ReferenceDocument.doi)
            == doi.lower()
        )

        return (
            await self.session.scalars(statement)
        ).one_or_none()

    async def create_reference_document(
        self,
        candidate: ReferenceCandidate,
    ) -> ReferenceDocument:
        document = ReferenceDocument(
            tenant_id=None,
            source_kind=candidate.source_kind,
            visibility="global",
            title=candidate.title,
            authors=candidate.authors,
            publication_year=candidate.publication_year,
            doi=candidate.doi,
            canonical_url=candidate.canonical_url,
            artifact_id=None,
            language=None,
            access_status="abstract" if candidate.abstract else "metadata_only",
            content_sha256=None,
            metadata_json={
                **candidate.provider_metadata,
                "resolver_match_score": candidate.match_score,
                "abstract": candidate.abstract,
            },
            is_active=True,
        )

        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)

        return document

    async def mark_resolved(
        self,
        submission_reference: SubmissionReference,
        document: ReferenceDocument,
        candidate: ReferenceCandidate,
        resolver_version: str,
    ) -> None:
        submission_reference.reference_document_id = document.id
        submission_reference.resolver_status = "resolved"
        submission_reference.resolver_confidence = Decimal(str(candidate.match_score))
        submission_reference.resolver_version = resolver_version
        submission_reference.metadata_json = {
            **submission_reference.metadata_json,
            "resolver": candidate.provider_metadata,
        }

        await self.session.flush()

    async def mark_unresolved_result(
        self,
        submission_reference: SubmissionReference,
        status: str,
        resolver_version: str,
        metadata: dict[str, Any],
    ) -> None:
        submission_reference.reference_document_id = None
        submission_reference.resolver_status = status
        submission_reference.resolver_version = resolver_version
        submission_reference.metadata_json = {
            **submission_reference.metadata_json,
            **metadata,
        }

        await self.session.flush()
