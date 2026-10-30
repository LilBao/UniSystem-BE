import re

from app.schemas.layer1_schema import ReportRepresentation
from app.schemas.reference_schema import ExtractedReference

REFERENCE_ENTRY = re.compile(
    r"^\s*(?:\[(\d+)\]|(\d+)\.|\b(\d+)\))\s*(.+)$",
    flags=re.DOTALL,
)

REFERENCE_KEYWORDS = (
    "tài liệu tham khảo",
    "tai lieu tham khao",
    "references",
    "bibliography",
    "tham khảo",
)


class ReferenceExtractionService:
    def extract(
        self,
        report: ReportRepresentation,
    ) -> list[ExtractedReference]:
        references: list[ExtractedReference] = []
        seen: set[str] = set()

        ref_section_ids = {
            section.external_id
            for section in report.sections
            if section.title
            and any(kw in section.title.lower() for kw in REFERENCE_KEYWORDS)
        }

        for block in report.blocks:
            label = block.metadata.get("paddle_label")
            is_ref_label = label in {"reference", "reference_content"}
            is_in_ref_section = block.section_external_id in ref_section_ids

            if not is_ref_label and not is_in_ref_section:
                continue

            text = (block.text_content or "").strip()
            if not text:
                continue
            match = REFERENCE_ENTRY.match(text)
            if match is None:
                continue

            num = match.group(1) or match.group(2) or match.group(3)
            raw_citation = match.group(4).strip()
            marker = f"[{num}]"

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
