import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.layer1_schema import CodeProvenance


class GraphLocation(BaseModel):
    path: str
    start_line: int = Field(gt=0)
    end_line: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_location(self) -> "GraphLocation":
        if (
            self.end_line < self.start_line
            or self.path.startswith("/")
            or re.search(r"[\\:\x00]", self.path)
            or any(p in {"", ".", ".."} for p in self.path.split("/"))
        ):
            raise ValueError("Invalid graph source location")
        return self


class GraphElement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    location: GraphLocation | None
    provenance: CodeProvenance
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: dict[str, Any]

    @model_validator(mode="after")
    def validate_provenance(self) -> "GraphElement":
        if not all(self.evidence.get(key) for key in ("parser", "version", "rule")):
            raise ValueError("Missing parser evidence")
        if self.provenance == CodeProvenance.EXTRACTED and self.location is None:
            raise ValueError("Extracted elements require a source span")
        if self.provenance == CodeProvenance.INFERRED and self.confidence is None:
            raise ValueError("Inferred elements require confidence")
        if self.provenance == CodeProvenance.AMBIGUOUS and not self.evidence.get("reason"):
            raise ValueError("Ambiguous elements require a reason")
        return self


class GraphNode(GraphElement):
    kind: str = Field(min_length=1)
    name: str


class GraphEdge(GraphElement):
    source: str
    target: str
    relation: str = Field(min_length=1)


class CodeGraph(BaseModel):
    schema_version: str = "1.0"
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    warnings: list[str] = Field(default_factory=list)

    def validate_inventory(self, files: list[dict[str, Any]]) -> None:
        lengths = {item["path"]: item["line_count"] for item in files}
        node_ids = {node.id for node in self.nodes}
        if len(node_ids) != len(self.nodes) or len({e.id for e in self.edges}) != len(self.edges):
            raise ValueError("Duplicate graph IDs")
        for element in [*self.nodes, *self.edges]:
            location = element.location
            if location and (
                location.path not in lengths or location.end_line > lengths[location.path]
            ):
                raise ValueError("Graph location outside source inventory")
        for edge in self.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                raise ValueError("Unknown edge endpoint")
