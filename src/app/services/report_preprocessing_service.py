import json
import logging
import math
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.models.submission_model import Artifact
from app.repositories.artifact_repository import ArtifactRepository
from app.schemas.layer1_schema import (
    DocumentBlockType,
    ParsedBlock,
    ParsedSection,
    ReportRepresentation,
)

CITATIONS = re.compile(r"\[\d+(?:\s*[,;–-]\s*\d+)*\]|\([A-ZÀ-Ỹ][^()\n]{0,100},\s*\d{4}[a-z]?\)")
logger = logging.getLogger("uvicorn.error")


class ReportParser(Protocol):
    @property
    def version(self) -> str: ...

    async def parse_pdf(self, file: Path) -> list[dict[str, Any]]: ...


class ReportPreprocessingService:
    def __init__(
        self, reader: ArtifactRepository, parser: ReportParser, settings: Settings
    ) -> None:
        self.reader, self.parser, self.settings = reader, parser, settings

    async def process(self, submission_id: UUID, report_artifact_id: UUID) -> ReportRepresentation:
        artifact = await self.reader.get_owned(submission_id, report_artifact_id, "report_pdf")
        return await self.process_artifact(artifact)

    async def process_artifact(self, artifact: Artifact) -> ReportRepresentation:
        cache_file = self.settings.cache_dir / "ocr" / f"{artifact.sha256}.json"
        if cache_file.exists():
            try:
                with cache_file.open("r", encoding="utf-8") as f:
                    pages = json.load(f)
                logger.info(
                    "Layer 1 report: loaded PaddleOCR result from cache %s, pages=%s",
                    cache_file,
                    len(pages),
                )
                return self.normalize(artifact.id, pages)
            except Exception as exc:
                logger.warning("Failed to load OCR cache, will re-parse: %s", exc)

        with TemporaryDirectory(prefix="report-") as temporary:
            file = Path(temporary) / "report.pdf"
            logger.info("Layer 1 report: downloading PDF from storage")
            await self.reader.download_to(artifact, file, self.settings.max_report_bytes)
            logger.info("Layer 1 report: PDF downloaded, bytes=%s", artifact.byte_size)
            with file.open("rb") as source:
                signature = source.read(1024)
            if not signature.lstrip().startswith(b"%PDF-"):
                raise AppError(ErrorCode.BAD_REQUEST, "Invalid PDF signature")
            logger.info("Layer 1 report: submitting PDF to PaddleOCR")
            pages = await self.parser.parse_pdf(file)
            logger.info("Layer 1 report: PaddleOCR returned pages=%s", len(pages))

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with cache_file.open("w", encoding="utf-8") as f:
                json.dump(pages, f, ensure_ascii=False)
            logger.info("Layer 1 report: saved PaddleOCR result to cache %s", cache_file)
        except Exception as exc:
            logger.warning("Failed to save OCR cache: %s", exc)

        try:
            return self.normalize(artifact.id, pages)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise AppError(ErrorCode.PARSER_ERROR, "Invalid PaddleOCR-VL output") from exc

    def normalize(self, artifact_id: UUID, pages: list[dict[str, Any]]) -> ReportRepresentation:
        if not pages:
            raise ValueError("Parser returned no pages")
        sections: list[ParsedSection] = []
        blocks: list[ParsedBlock] = []
        stack: list[ParsedSection] = []
        labels = {
            "table": DocumentBlockType.TABLE,
            "image": DocumentBlockType.FIGURE,
            "figure": DocumentBlockType.FIGURE,
            "chart": DocumentBlockType.FIGURE,
            "formula": DocumentBlockType.EQUATION,
            "display_formula": DocumentBlockType.EQUATION,
            "equation": DocumentBlockType.EQUATION,
        }
        for page_no, page in enumerate(pages, 1):
            page_blocks: list[ParsedBlock] = []
            for ordinal, raw in enumerate(page["parsing_res_list"]):
                text = str(raw.get("block_content") or "")
                label = str(raw["block_label"])
                if label in {"doc_title", "paragraph_title", "section_title"}:
                    number = re.match(r"^(\d+(?:\.\d+)*)(?:[.)]?\s)", text)
                    level = len(number[1].split(".")) if number else 1
                    while stack and stack[-1].level >= level:
                        stack.pop()
                    section = ParsedSection(
                        external_id=f"section-{len(sections)}",
                        title=text,
                        level=level,
                        parent_external_id=stack[-1].external_id if stack else None,
                        ordinal=len(sections),
                        page_start=page_no,
                        page_end=page_no,
                    )
                    sections.append(section)
                    stack.append(section)
                for ancestor in stack:
                    ancestor.page_end = page_no
                bbox = dict(zip(("x0", "y0", "x1", "y1"), raw["block_bbox"], strict=True))
                if (
                    not all(math.isfinite(float(v)) for v in bbox.values())
                    or not 0 <= bbox["x0"] <= bbox["x1"]
                    or not 0 <= bbox["y0"] <= bbox["y1"]
                ):
                    raise ValueError("Invalid bounding box")
                matches = list(CITATIONS.finditer(text))
                block = ParsedBlock(
                    external_id=f"p{page_no}-b{ordinal}",
                    section_external_id=stack[-1].external_id if stack else None,
                    block_type=labels.get(label, DocumentBlockType.TEXT),
                    page_no=page_no,
                    reading_order=len(page_blocks),
                    text_content=text,
                    bbox=bbox,
                    citation_marker_ids=list(dict.fromkeys(m[0] for m in matches)),
                    source_locator={
                        "page": page_no,
                        "paddle_block_id": raw.get("block_id"),
                        "paddle_label": label,
                    },
                    metadata={
                        "paddle_label": label,
                        "paddle_block_order": raw.get("block_order"),
                        "coordinate_system": "paddle_page_pixels",
                        "section_detection": "heading_label_and_numbering",
                        "exclude_from_claims": label
                        in {
                            "doc_title",
                            "paragraph_title",
                            "section_title",
                            "header",
                            "footer",
                            "page_number",
                            "figure_title",
                            "table_title",
                            "figure_caption",
                            "table_caption",
                            "reference",
                            "reference_content",
                        },
                    },
                )
                page_blocks.append(block)
                for index, match in enumerate(matches):
                    page_blocks.append(
                        ParsedBlock(
                            external_id=f"{block.external_id}-citation-{index}",
                            parent_block_external_id=block.external_id,
                            section_external_id=block.section_external_id,
                            block_type=DocumentBlockType.CITATION_POSITION,
                            page_no=page_no,
                            reading_order=len(page_blocks),
                            text_content=match[0],
                            bbox=bbox,
                            citation_marker_ids=[match[0]],
                            source_locator={"start": match.start(), "end": match.end()},
                            metadata={
                                "bbox_precision": "parent_block",
                                "span_unit": "unicode_codepoint",
                            },
                        )
                    )

            for caption in page_blocks:
                caption_label = str(caption.metadata.get("paddle_label") or "")
                kind = {
                    "figure_title": DocumentBlockType.FIGURE,
                    "figure_caption": DocumentBlockType.FIGURE,
                    "table_title": DocumentBlockType.TABLE,
                    "table_caption": DocumentBlockType.TABLE,
                }.get(caption_label)
                candidates = [
                    b
                    for b in page_blocks
                    if b.block_type == kind
                    and b.section_external_id == caption.section_external_id
                    and b.caption_block_external_id is None
                    and min(b.bbox["x1"], caption.bbox["x1"])
                    > max(b.bbox["x0"], caption.bbox["x0"])
                ]
                if candidates:
                    nearest = min(
                        candidates,
                        key=lambda b: min(
                            abs(b.bbox["y1"] - caption.bbox["y0"]),
                            abs(caption.bbox["y1"] - b.bbox["y0"]),
                        ),
                    )
                    nearest.caption_block_external_id = caption.external_id
                    nearest.metadata["caption_link_method"] = "nearest_vertical_overlap"
            blocks.extend(page_blocks)
        return ReportRepresentation(
            artifact_id=artifact_id,
            sections=sections,
            blocks=blocks,
            parser_version=self.parser.version,
        )
