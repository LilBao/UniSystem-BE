from typing import Any, Literal

from pydantic import BaseModel, Field


class ExtractedReference(BaseModel):
    marker: str = Field(min_length=1)
    raw_citation: str = Field(min_length=1)
    source_block_external_id: str | None = None


class ReferenceCandidate(BaseModel):
    title: str = Field(min_length=1)
    authors: list[dict[str, Any]] = Field(default_factory=list)
    publication_year: int | None = None
    doi: str | None = None
    canonical_url: str | None = None
    abstract: str | None = None
    source_kind: Literal[
        "paper",
        "book",
        "web",
        "dataset",
        "other",
    ] = "other"
    match_score: float = Field(ge=0, le=1)
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class ReferenceResolution(BaseModel):
    status: Literal[
        "resolved",
        "ambiguous",
        "not_found",
        "unresolved",
    ]
    candidate: ReferenceCandidate | None = None
    alternatives: list[ReferenceCandidate] = Field(default_factory=list)
    reason: str | None = None
