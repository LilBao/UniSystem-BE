"""Pipeline 1: Rubric-based Scoring & Summarization (Week 9-11).

Features:
- Zero-shot and Few-shot Rubric Scoring baselines
- Section Understanding & Synthesis (Evidence Pack)
- G-EVAL with Chain-of-Thought reasoning + continuous scoring
- Multi-run Self-Consistency (3-5 runs, variance tracking)
- Optional Phase 2: Calibration Network
"""

from app.services.layer2.pipeline1.geval_scoring_service import GEvalScoringService
from app.services.layer2.pipeline1.pipeline1_service import Pipeline1Service
from app.services.layer2.pipeline1.section_understanding_service import (
    SectionUnderstandingService,
)

__all__ = [
    "GEvalScoringService",
    "Pipeline1Service",
    "SectionUnderstandingService",
]
