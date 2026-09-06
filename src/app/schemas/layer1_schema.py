from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DocumentBlockType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    EQUATION = "equation"
    CITATION_POSITION = "citation"


class ClaimType(StrEnum):
    TEXT = "text"
    FACTUAL = "factual"
    CITATION = "citation"
    IMPLEMENTATION = "implementation"


class CodeProvenance(StrEnum):
    EXTRACTED = "EXTRACTED"
    INFERRED = "INFERRED"
    AMBIGUOUS = "AMBIGUOUS"


class ParsedSection(BaseModel):
    external_id: str
    parent_external_id: str | None = None
    title: str | None = None
    level: int = Field(default=1, gt=0)
    ordinal: int = Field(ge=0)
    page_start: int = Field(gt=0)
    page_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_page_range(self) -> "ParsedSection":
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ParsedBlock(BaseModel):
    external_id: str
    section_external_id: str | None = None
    parent_block_external_id: str | None = None
    caption_block_external_id: str | None = None
    block_type: DocumentBlockType
    page_no: int = Field(gt=0)
    reading_order: int = Field(ge=0)
    text_content: str | None = None
    bbox: dict[str, float]
    quads: list[Any] = Field(default_factory=list)
    citation_marker_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_locator: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedClaim(BaseModel):
    external_id: str
    claim_type: ClaimType
    text_content: str
    source_block_external_id: str
    context_block_external_ids: list[str] = Field(default_factory=list)
    citation_markers: list[str] = Field(default_factory=list)
    source_span: dict[str, int]
    is_atomic: bool = False
    confidence: float | None = Field(default=None, ge=0, le=1)
    extractor_version: str = Field(min_length=1)


class ReportRepresentation(BaseModel):
    artifact_id: UUID
    sections: list[ParsedSection]
    blocks: list[ParsedBlock]
    parser_version: str


class SourceCodeRepresentation(BaseModel):
    source_artifact_id: UUID
    graph_object_uri: str
    graphify_version: str
    schema_version: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    graph_byte_size: int = Field(ge=0)
    node_count: int | None = Field(default=None, ge=0)
    edge_count: int | None = Field(default=None, ge=0)
    provenance_summary: dict[CodeProvenance, int] = Field(default_factory=dict)
