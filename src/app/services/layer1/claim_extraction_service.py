import logging
from uuid import UUID

from app.adapters.claim_llm import ClaimLLMAdapter
from app.schemas.layer1_schema import DocumentBlockType, ExtractedClaim, ReportRepresentation

logger = logging.getLogger("uvicorn.error")


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
            try:
                result = await self.parser.extract(
                    section.title if section else None,
                    [by_id[block_id] for block_id in block_ids],
                )
            except Exception as exc:
                logger.warning(
                    "Claim extraction LLM call failed for section %s: %s",
                    section_id,
                    exc,
                )
                continue

            for item in result:
                try:
                    if not isinstance(item, dict):
                        continue

                    source_id = item.get("source_block_external_id")
                    if not source_id or source_id not in by_id or source_id not in block_ids:
                        logger.warning(
                            "Claim skipped: invalid or missing source_block_external_id %r",
                            source_id,
                        )
                        continue

                    source = by_id[source_id]
                    source_text = source.text_content or ""
                    text_len = len(source_text)

                    raw_text = str(item.get("text_content") or "").strip()
                    if not raw_text:
                        continue
                    item["text_content"] = raw_text

                    # 1. Sanitize source_span
                    span = item.get("source_span")
                    start = span.get("start") if isinstance(span, dict) else None
                    end = span.get("end") if isinstance(span, dict) else None

                    if (
                        not isinstance(start, int)
                        or not isinstance(end, int)
                        or not (0 <= start < end <= text_len)
                    ):
                        idx = source_text.find(raw_text)
                        if idx != -1:
                            start = idx
                            end = idx + len(raw_text)
                        elif isinstance(start, int) and isinstance(end, int) and text_len > 0:
                            start = max(0, min(start, text_len - 1))
                            end = max(start + 1, min(end, text_len))
                        else:
                            start = 0
                            end = max(1, text_len)

                    item["source_span"] = {"start": start, "end": end}

                    # 2. Sanitize context blocks (filter to existing blocks in current section)
                    contexts = item.get("context_block_external_ids")
                    if isinstance(contexts, list):
                        item["context_block_external_ids"] = [c for c in contexts if c in block_ids]
                    else:
                        item["context_block_external_ids"] = []

                    # 3. Keep citation markers only when they occur in source/context blocks.
                    allowed = set(source.citation_marker_ids)
                    for context_id in item["context_block_external_ids"]:
                        allowed.update(by_id[context_id].citation_marker_ids)

                    markers = item.get("citation_markers")
                    if isinstance(markers, list):
                        item["citation_markers"] = [m for m in markers if m in allowed]
                    else:
                        item["citation_markers"] = []

                    # 4. Normalize claim_type
                    claim_type = str(item.get("claim_type") or "text").lower()
                    if claim_type not in {"text", "factual", "citation", "implementation"}:
                        claim_type = "text"
                    item["claim_type"] = claim_type

                    claim = ExtractedClaim.model_validate(item)

                    # 5. Deduplicate
                    if claim.external_id in seen:
                        logger.debug("Skipping duplicate claim %s", claim.external_id)
                        continue

                    seen.add(claim.external_id)
                    claims.append(claim)
                except Exception as exc:
                    logger.warning("Failed to validate claim item %r: %s", item, exc)
                    continue

        return claims
