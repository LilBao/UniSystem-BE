import re

from app.schemas.layer1_schema import ReportRepresentation
from app.schemas.reference_schema import ExtractedReference

REFERENCE_ENTRY = re.compile(
    r"^\s*(\[\d+\])\s*(.+)$",
    flags=re.DOTALL,
)


class ReferenceExtractionService:
    def extract(
        self,
        report: ReportRepresentation,
    ) -> list[ExtractedReference]:
        references: list[ExtractedReference] = []
        seen: set[str] = set()
        for block in report.blocks:
            label = block.metadata.get("paddle_label")

            if label not in {"reference", "reference_content"}:
                continue

            text = (block.text_content or "").strip()
            if not text:
                continue
            match = REFERENCE_ENTRY.match(text)
            if match is None:
                continue

            marker = match.group(1)
            raw_citation = match.group(2).strip()

            if marker in seen or not raw_citation:
                continue

            references.append(
                ExtractedReference(
                    marker=marker,
                    raw_citation=raw_citation,
                    source_block_external_id=block.external_id,
                )
            )
            seen.add(marker)

        return references
