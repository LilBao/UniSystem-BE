"""Service: Chứa use cases và luật nghiệp vụ, phân tầng theo Layer và Pipeline.

Kiến trúc:
- app.services.common: Core submission, upload, và background lifecycle.
- app.services.layer1: Document parsing (PaddleOCR), claim extraction (LLM),
  source code graph (Graphify), reference extraction.
- app.services.layer2.pipeline1: Rubric-based Scoring & Summarization (G-EVAL).
- app.services.layer2.pipeline2: Citation Verification (SciLens-based Atomic Claims & RAG).
- app.services.layer2.pipeline3: Code-Report Consistency Verification (Graphify + CASCADE).
- app.services.layer2.pipeline4: AI-generated Text Likelihood Signal (Binoculars / VietBinoculars).
- app.services.layer3: Evidence-grounded Decision Layer (Aggregator & Collaborative Judge).
"""

# Common / Platform
from app.services.common.cache_eviction_service import evict_stale_cache
from app.services.common.file_upload_service import FileUploadService
from app.services.common.submission_service import SubmissionService

# Layer 1
from app.services.layer1.claim_extraction_service import ClaimExtractionService
from app.services.layer1.layer1_service import Layer1Service
from app.services.layer1.reference_extraction_service import ReferenceExtractionService
from app.services.layer1.report_preprocessing_service import ReportPreprocessingService
from app.services.layer1.source_code_preprocessing_service import SourceCodePreprocessingService

# Layer 2 - Pipeline 2
from app.services.layer2.pipeline2.citation_evaluation_service import (
    CitationEvaluationReport,
    CitationEvaluationService,
)
from app.services.layer2.pipeline2.citation_evidence_preparation_service import (
    CitationEvidencePreparationService,
)
from app.services.layer2.pipeline2.citation_verification_service import CitationVerificationService
from app.services.layer2.pipeline2.pipeline2_service import Pipeline2Service
from app.services.layer2.pipeline2.reference_passage_service import ReferencePassageService
from app.services.layer2.pipeline2.reference_resolution_service import ReferenceResolutionService

__all__ = [
    # Common
    "evict_stale_cache",
    "FileUploadService",
    "SubmissionService",
    # Layer 1
    "Layer1Service",
    "ReportPreprocessingService",
    "ClaimExtractionService",
    "SourceCodePreprocessingService",
    "ReferenceExtractionService",
    # Layer 2 - Pipeline 2
    "Pipeline2Service",
    "CitationVerificationService",
    "CitationEvaluationService",
    "CitationEvaluationReport",
    "CitationEvidencePreparationService",
    "ReferenceResolutionService",
    "ReferencePassageService",
]
