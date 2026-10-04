from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CodeConsistencyVerdict(StrEnum):
    CONSISTENT = "CONSISTENT"
    INCONSISTENT = "INCONSISTENT"
    PARTIAL = "PARTIAL"
    NEI = "NEI"


class VerificationStage(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"
    SKIPPED_TIER3 = "SKIPPED_TIER3"


class HighlightKind(StrEnum):
    CENTRAL_CONCEPT = "CENTRAL_CONCEPT"
    CORE_ALGORITHM = "CORE_ALGORITHM"
    KEY_ENTRYPOINT = "KEY_ENTRYPOINT"
    CORE_FEATURE = "CORE_FEATURE"
    MISMATCH_STRUCTURAL = "MISMATCH_STRUCTURAL"
    MISMATCH_SEMANTIC = "MISMATCH_SEMANTIC"
    MISMATCH_EXECUTION = "MISMATCH_EXECUTION"


class HighlightSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class CodeLocationSpan(BaseModel):
    path: str
    start_line: int = Field(gt=0)
    end_line: int = Field(gt=0)


class CodeHighlightItem(BaseModel):
    id: str
    kind: HighlightKind
    severity: HighlightSeverity
    title: str
    description: str
    location: CodeLocationSpan
    code_snippet: str | None = None
    importance_score: float | None = None
    related_claim_id: UUID | None = None
    feature_key: str | None = None
    layers: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    member_node_ids: list[str] = Field(default_factory=list)
    member_paths: list[str] = Field(default_factory=list)


class MismatchWitness(BaseModel):
    claim_id: UUID
    claim_text: str
    report_location: dict[str, Any] = Field(default_factory=dict)
    code_location: CodeLocationSpan
    code_snippet: str
    mismatch_type: HighlightKind
    severity: HighlightSeverity
    expected_behavior: str
    actual_behavior: str
    rationale: str


class CodeConsistencyResult(BaseModel):
    claim_id: UUID
    verdict: CodeConsistencyVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    verification_stage: VerificationStage
    requires_review: bool = False
    reason_codes: list[str] = Field(default_factory=list)
    stage_history: list[VerificationStage] = Field(default_factory=list)
    rationale: str = ""
    evidence_locations: list[CodeLocationSpan] = Field(default_factory=list)
    mismatch_witnesses: list[MismatchWitness] = Field(default_factory=list)


class P3WorkItem(BaseModel):
    claim_id: UUID
    text_content: str
    is_atomic: bool = True
    is_central: bool = False
    impact: int = 1
    testability: int = 0
    risk: int = 1
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    source_span: dict[str, Any] = Field(default_factory=dict)
    source_block_id: UUID | None = None


class VisualGraphNodeData(BaseModel):
    label: str
    kind: str  # "CLAIM" | "FILE" | "CLASS" | "FUNCTION" | "ENTRYPOINT"
    status: str  # "consistent" | "mismatch" | "unsupported" | "neutral"
    is_important: bool = False
    importance_score: float = 0.0
    has_mismatch: bool = False
    location: dict[str, Any] = Field(default_factory=dict)
    snippet: str | None = None
    cluster_id: str | None = None
    cluster_name: str | None = None
    role: str | None = None


class VisualGraphNode(BaseModel):
    id: str
    type: str  # "claim_node" | "code_node" | "cluster_group"
    data: VisualGraphNodeData


class VisualGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str  # "verifies_against" | "calls" | "imports" | "defines"
    is_mismatch: bool = False
    severity: HighlightSeverity | None = None
    discrepancy_details: str | None = None
    label: str | None = None
    is_aggregated: bool = False


class VisualGraphMetrics(BaseModel):
    total_nodes: int
    total_edges: int
    important_nodes_count: int
    mismatched_nodes_count: int
    mismatched_edges_count: int
    consistency_score: float


class VisualGraphResponse(BaseModel):
    submission_id: UUID
    run_id: UUID | None = None
    nodes: list[VisualGraphNode] = Field(default_factory=list)
    edges: list[VisualGraphEdge] = Field(default_factory=list)
    metrics: VisualGraphMetrics
    mismatch_witnesses: list[MismatchWitness] = Field(default_factory=list)

    def filtered(
        self, filter_mode: str = "all", min_importance: float = 0.0
    ) -> "VisualGraphResponse":
        if filter_mode == "all" and min_importance <= 0.0:
            return self

        kept_nodes: list[VisualGraphNode] = []
        for n in self.nodes:
            if n.type == "claim_node":
                if filter_mode == "mismatches_only" and not n.data.has_mismatch:
                    continue
                kept_nodes.append(n)
            else:
                if filter_mode == "mismatches_only" and not n.data.has_mismatch:
                    continue
                if (
                    filter_mode == "important_only"
                    and not n.data.is_important
                    and not n.data.has_mismatch
                ):
                    continue
                if n.data.importance_score < min_importance and not n.data.has_mismatch:
                    continue
                kept_nodes.append(n)

        kept_ids = {n.id for n in kept_nodes}
        kept_edges = [e for e in self.edges if e.source in kept_ids and e.target in kept_ids]

        metrics = VisualGraphMetrics(
            total_nodes=len(kept_nodes),
            total_edges=len(kept_edges),
            important_nodes_count=sum(1 for n in kept_nodes if n.data.is_important),
            mismatched_nodes_count=sum(1 for n in kept_nodes if n.data.has_mismatch),
            mismatched_edges_count=sum(1 for e in kept_edges if e.is_mismatch),
            consistency_score=self.metrics.consistency_score,
        )

        return VisualGraphResponse(
            submission_id=self.submission_id,
            run_id=self.run_id,
            nodes=kept_nodes,
            edges=kept_edges,
            metrics=metrics,
            mismatch_witnesses=self.mismatch_witnesses,
        )


class CodeEvidenceSymbol(BaseModel):
    ref: str
    name: str
    kind: str
    start_line: int
    end_line: int


class CodeEvidenceCard(BaseModel):
    ref: str
    path: str
    score: float = 0.0
    coverage: float = 0.0
    matched_terms: list[str] = Field(default_factory=list)
    symbols: list[CodeEvidenceSymbol] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    span: CodeLocationSpan


class CodeJudgementMismatch(BaseModel):
    ref: str | None = None
    expected_behavior: str = ""
    actual_behavior: str = ""


class CodeJudgement(BaseModel):
    verdict: CodeConsistencyVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    supporting_refs: list[str] = Field(default_factory=list)
    contradicting_refs: list[str] = Field(default_factory=list)
    mismatch: CodeJudgementMismatch | None = None


class Pipeline3RunResponse(BaseModel):
    run_id: UUID
    submission_id: UUID
    status: str
    total_claims: int
    consistent_count: int
    inconsistent_count: int
    partial_count: int
    requires_review_count: int
    important_highlights: list[CodeHighlightItem] = Field(default_factory=list)
    mismatch_witnesses: list[MismatchWitness] = Field(default_factory=list)
