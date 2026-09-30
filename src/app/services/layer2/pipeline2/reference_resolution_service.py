from typing import Any
from uuid import UUID

import httpx

from app.adapters.crossref import CrossrefAdapter
from app.adapters.open_access import OpenAccessAdapter
from app.core.config import Settings
from app.repositories.reference_repository import ReferenceRepository


class ReferenceResolutionService:
    def __init__(
        self,
        repository: ReferenceRepository,
        resolver: CrossrefAdapter,
        settings: Settings,
        open_access: OpenAccessAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.settings = settings
        self.open_access = open_access

    async def resolve_submission(
        self,
        submission_id: UUID,
    ) -> dict[str, int]:
        references = await self.repository.list_unresolved(
            submission_id
        )

        metrics = {
            "total": len(references),
            "resolved": 0,
            "ambiguous": 0,
            "not_found": 0,
            "retryable_error": 0,
        }

        for reference in references:
            try:
                resolution = await self.resolver.resolve(
                    reference.raw_citation
                )
            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.HTTPStatusError,
            ) as exc:
                await self._record_retryable_error(
                    reference,
                    exc,
                )
                metrics["retryable_error"] += 1
                continue

            if (
                resolution.status == "resolved"
                and resolution.candidate is not None
            ):
                candidate = resolution.candidate

                if candidate.abstract is None and self.open_access is not None:
                    enriched_abstract = await self.open_access.fetch_abstract(
                        doi=candidate.doi,
                        title=candidate.title,
                    )
                    if enriched_abstract:
                        candidate = candidate.model_copy(update={"abstract": enriched_abstract})

                document = None
                if candidate.doi is not None:
                    document = (
                        await self.repository
                        .find_document_by_doi(candidate.doi)
                    )

                if document is None:
                    document = (
                        await self.repository
                        .create_reference_document(candidate)
                    )

                await self.repository.mark_resolved(
                    reference,
                    document,
                    candidate,
                    self.settings.reference_resolver_version,
                )

                metrics["resolved"] += 1
                continue

            alternatives = [
                item.model_dump(mode="json")
                for item in resolution.alternatives
            ]

            await self.repository.mark_unresolved_result(
                reference,
                resolution.status,
                self.settings.reference_resolver_version,
                {
                    "resolver_reason": resolution.reason,
                    "resolver_candidates": alternatives,
                },
            )

            metrics[resolution.status] += 1

        return metrics

    async def _record_retryable_error(
        self,
        reference: Any,
        error: Exception,
    ) -> None:
        reference.metadata_json = {
            **reference.metadata_json,
            "resolver_last_error": {
                "type": type(error).__name__,
                "retryable": True,
            },
        }
        await self.repository.session.flush()
