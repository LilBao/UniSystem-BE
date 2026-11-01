import html
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.schemas.reference_schema import (
    ReferenceCandidate,
    ReferenceResolution,
)

DOI_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    flags=re.IGNORECASE,
)

YEAR_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b")


class CrossrefAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def resolve(
        self,
        raw_citation: str,
    ) -> ReferenceResolution:
        doi = self._extract_doi(raw_citation)

        if doi is not None:
            candidate = await self._get_by_doi(doi)
            if candidate is not None:
                return ReferenceResolution(
                    status="resolved",
                    candidate=candidate,
                    reason="doi_exact_match",
                )

        candidates = await self._search_bibliographic(raw_citation)

        if not candidates:
            return ReferenceResolution(
                status="not_found",
                reason="no_crossref_candidate",
            )

        candidates.sort(
            key=lambda item: item.match_score,
            reverse=True,
        )

        best = candidates[0]

        if best.match_score < self.settings.reference_resolver_match_threshold:
            return ReferenceResolution(
                status="not_found",
                alternatives=candidates,
                reason="candidate_score_below_threshold",
            )

        if len(candidates) > 1:
            margin = best.match_score - candidates[1].match_score

            if margin < self.settings.reference_resolver_margin_threshold:
                return ReferenceResolution(
                    status="ambiguous",
                    alternatives=candidates,
                    reason="multiple_close_candidates",
                )

        return ReferenceResolution(
            status="resolved",
            candidate=best,
            alternatives=candidates[1:],
            reason="bibliographic_match",
        )

    async def _get_by_doi(
        self,
        doi: str,
    ) -> ReferenceCandidate | None:
        encoded_doi = quote(doi, safe="")

        async with self._client() as client:
            response = await client.get(f"/works/{encoded_doi}")

            if response.status_code == 404:
                return None

            response.raise_for_status()
            item = response.json()["message"]

        return self._to_candidate(item, match_score=1.0)

    async def _search_bibliographic(
        self,
        raw_citation: str,
    ) -> list[ReferenceCandidate]:
        async with self._client() as client:
            response = await client.get(
                "/works",
                params={
                    "query.bibliographic": raw_citation,
                    "rows": self.settings.reference_resolver_max_candidates,
                },
            )
            response.raise_for_status()
            items = response.json()["message"]["items"]

        return [
            self._to_candidate(
                item,
                match_score=self._calculate_match_score(
                    raw_citation,
                    item,
                ),
            )
            for item in items
            if item.get("title")
        ]

    def _client(self) -> httpx.AsyncClient:
        headers = {"User-Agent": (f"UniSystem/0.1 (mailto:{self.settings.crossref_mailto})")}

        return httpx.AsyncClient(
            base_url=self.settings.crossref_base_url,
            headers=headers,
            timeout=self.settings.reference_resolver_timeout_seconds,
        )

    def _to_candidate(
        self,
        item: dict[str, Any],
        match_score: float,
    ) -> ReferenceCandidate:
        title_values = item.get("title") or []
        title = str(title_values[0]).strip()

        doi = item.get("DOI")
        if isinstance(doi, str):
            doi = self._normalize_doi(doi)

        raw_abstract = item.get("abstract")
        abstract = None
        if isinstance(raw_abstract, str) and raw_abstract.strip():
            without_tags = re.sub(r"<[^>]+>", " ", raw_abstract)
            abstract = " ".join(html.unescape(without_tags).split())

        return ReferenceCandidate(
            title=title,
            authors=list(item.get("author") or []),
            publication_year=self._extract_year_from_item(item),
            doi=doi,
            canonical_url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            abstract=abstract,
            source_kind=self._map_source_kind(item.get("type")),
            match_score=match_score,
            provider_metadata={
                "provider": "crossref",
                "crossref_type": item.get("type"),
                "crossref_score": item.get("score"),
            },
        )

    def _calculate_match_score(
        self,
        raw_citation: str,
        item: dict[str, Any],
    ) -> float:
        title_values = item.get("title") or []
        if not title_values:
            return 0.0

        citation_normalized = self._normalize_text(raw_citation)
        title_normalized = self._normalize_text(str(title_values[0]))

        title_tokens = set(title_normalized.split())
        citation_tokens = set(citation_normalized.split())

        if not title_tokens:
            return 0.0

        containment = len(title_tokens & citation_tokens) / len(title_tokens)

        sequence_score = SequenceMatcher(
            None,
            title_normalized,
            citation_normalized,
        ).ratio()

        score = containment * 0.8 + sequence_score * 0.2

        citation_year = self._extract_year(raw_citation)
        candidate_year = self._extract_year_from_item(item)

        if citation_year is not None and candidate_year is not None:
            if citation_year == candidate_year:
                score += 0.05
            else:
                score -= 0.15

        return max(0.0, min(score, 1.0))

    @staticmethod
    def _extract_doi(raw_citation: str) -> str | None:
        match = DOI_PATTERN.search(raw_citation)
        if match is None:
            return None

        return CrossrefAdapter._normalize_doi(match.group(0))

    @staticmethod
    def _normalize_doi(doi: str) -> str:
        return doi.lower().rstrip(".,;)]}")

    @staticmethod
    def _normalize_text(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).lower()
        value = re.sub(r"[^\w\s]", " ", value)
        return " ".join(value.split())

    @staticmethod
    def _extract_year(value: str) -> int | None:
        match = YEAR_PATTERN.search(value)
        return int(match.group(0)) if match else None

    @staticmethod
    def _extract_year_from_item(
        item: dict[str, Any],
    ) -> int | None:
        for key in (
            "published-print",
            "published-online",
            "published",
        ):
            date_parts = item.get(key, {}).get("date-parts", [])

            if date_parts and date_parts[0]:
                return int(date_parts[0][0])

        return None

    @staticmethod
    def _map_source_kind(value: Any) -> str:
        mapping = {
            "journal-article": "paper",
            "proceedings-article": "paper",
            "posted-content": "paper",
            "book": "book",
            "book-chapter": "book",
            "dataset": "dataset",
        }
        return mapping.get(str(value), "other")
