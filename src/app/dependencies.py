from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.archive import SafeZipExtractor
from app.adapters.claim_llm import ClaimLLMAdapter
from app.adapters.colab_parser import ColabParserAdapter
from app.adapters.crossref import CrossrefAdapter
from app.adapters.graphify import GraphifyAdapter
from app.adapters.local_parser import LocalParserAdapter
from app.adapters.parser import PaddleParserAdapter
from app.core.config import get_settings
from app.core.database import get_session
from app.repositories.artifact_repository import ArtifactRepository, GraphArtifactWriter
from app.repositories.cloudinary_repository import CloudinaryRepository
from app.repositories.code_repository import CodeRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.p2_repository import P2Repository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.reference_repository import ReferenceRepository
from app.repositories.submission_repository import SubmissionRepository
from app.services.citation_evidence_preparation_service import (
    CitationEvidencePreparationService,
)
from app.services.claim_extraction_service import ClaimExtractionService
from app.services.file_upload_service import FileUploadService
from app.services.layer1_service import Layer1Service
from app.services.pipeline2_service import Pipeline2Service
from app.services.reference_extraction_service import ReferenceExtractionService
from app.services.reference_resolution_service import ReferenceResolutionService
from app.services.report_preprocessing_service import ReportPreprocessingService
from app.services.source_code_preprocessing_service import SourceCodePreprocessingService
from app.services.submission_service import SubmissionService


@lru_cache
def get_parser_adapter() -> PaddleParserAdapter | LocalParserAdapter | ColabParserAdapter:
    settings = get_settings()
    if settings.ocr_provider == "local":
        return LocalParserAdapter(settings)
    if settings.ocr_provider == "colab":
        return ColabParserAdapter(settings)
    return PaddleParserAdapter(settings)


def get_file_upload_service() -> FileUploadService:
    settings = get_settings()
    return FileUploadService(CloudinaryRepository(settings), settings)


def get_submission_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SubmissionService:
    return SubmissionService(SubmissionRepository(session))


def get_layer1_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Layer1Service:
    settings = get_settings()

    reader = ArtifactRepository(session, settings)
    writer = GraphArtifactWriter(
        CloudinaryRepository(settings),
        settings,
    )

    return Layer1Service(
        submission_repository=SubmissionRepository(session),
        pipeline_repository=PipelineRepository(session),
        document_repository=DocumentRepository(session),
        code_repository=CodeRepository(session),
        reference_repository=ReferenceRepository(session),
        report_preprocessor=ReportPreprocessingService(
            reader,
            get_parser_adapter(),
            settings,
        ),
        claim_extractor=ClaimExtractionService(
            ClaimLLMAdapter(settings),
        ),
        source_code_preprocessor=SourceCodePreprocessingService(
            reader,
            SafeZipExtractor(settings),
            GraphifyAdapter(settings),
            writer,
            settings,
        ),
        reference_extractor=ReferenceExtractionService(),
    )

def get_reference_resolution_service(
    session: Annotated[
        AsyncSession,
        Depends(get_session),
    ],
) -> ReferenceResolutionService:
    settings = get_settings()

    return ReferenceResolutionService(
        ReferenceRepository(session),
        CrossrefAdapter(settings),
        settings,
    )


def get_pipeline2_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Pipeline2Service:
    settings = get_settings()
    return Pipeline2Service(
        SubmissionRepository(session),
        PipelineRepository(session),
        P2Repository(session),
        ReferenceResolutionService(
            ReferenceRepository(session),
            CrossrefAdapter(settings),
            settings,
        ),
        CitationEvidencePreparationService(),
    )
