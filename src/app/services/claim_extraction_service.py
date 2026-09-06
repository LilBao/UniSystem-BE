from uuid import UUID

from pydantic import TypeAdapter

from app.adapters.claim_llm import ClaimLLMAdapter
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.schemas.layer1_schema import DocumentBlockType, ExtractedClaim, ReportRepresentation


class ClaimExtractionService:
    def __init__(self, parser: ClaimLLMAdapter) -> None:
        self.parser = parser

    async def extract(
        self,
        submission_id: UUID,
        report: ReportRepresentation,
    ) -> list[ExtractedClaim]:
        texts = [
            block
            for block in report.blocks
            if block.block_type == DocumentBlockType.TEXT
            and block.text_content
            and not block.metadata.get("exclude_from_claims")
        ]
        sections = {section.external_id: section for section in report.sections}
        groups: dict[str | None, list[str]] = {}
        by_id = {block.external_id: block for block in texts}
        for block in sorted(texts, key=lambda b: (b.page_no, b.reading_order)):
            groups.setdefault(block.section_external_id, []).append(block.external_id)
        claims: list[ExtractedClaim] = []
        seen: set[str] = set()
        for section_id, block_ids in groups.items():
            section = sections.get(section_id) if section_id else None
            result = await self.parser.extract(
                section.title if section else None,
                [by_id[block_id] for block_id in block_ids],
            )
            try:
                extracted = TypeAdapter(list[ExtractedClaim]).validate_python(result)
                for claim in extracted:
                    if claim.external_id in seen or claim.source_block_external_id not in block_ids:
                        raise ValueError("Duplicate claim or invalid source")
                    seen.add(claim.external_id)
                    if any(
                        context not in block_ids for context in claim.context_block_external_ids
                    ):
                        raise ValueError("Context outside current section")
                    source = by_id[claim.source_block_external_id]
                    span = claim.source_span
                    if (
                        set(span) != {"start", "end"}
                        or not 0 <= span["start"] < span["end"] <= len(source.text_content or "")
                        or not claim.text_content.strip()
                    ):
                        raise ValueError("Invalid claim source span")
                    allowed = set(source.citation_marker_ids)
                    for context in claim.context_block_external_ids:
                        allowed.update(by_id[context].citation_marker_ids)
                    if not set(claim.citation_markers).issubset(allowed):
                        raise ValueError("Claim invented citation markers")
                claims.extend(extracted)
            except (ValueError, KeyError, TypeError) as exc:
                raise AppError(ErrorCode.PARSER_ERROR, "Invalid extracted claims") from exc
        return claims
