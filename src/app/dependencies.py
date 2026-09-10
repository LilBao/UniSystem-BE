from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.archive import SafeZipExtractor
from app.adapters.claim_llm import ClaimLLMAdapter
from app.adapters.colab_parser import ColabParserAdapter
from app.adapters.graphify import GraphifyAdapter
from app.adapters.local_parser import LocalParserAdapter
from app.adapters.parser import PaddleParserAdapter
from app.core.config import get_settings
from app.core.database import get_session
from app.repositories.artifact_repository import ArtifactRepository, GraphArtifactWriter
from app.repositories.cloudinary_repository import CloudinaryRepository
from app.repositories.code_repository import CodeRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.submission_repository import SubmissionRepository
from app.services.claim_extraction_service import ClaimExtractionService
from app.services.file_upload_service import FileUploadService
from app.services.layer1_service import Layer1Service
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
    writer = GraphArtifactWriter(CloudinaryRepository(settings), settings)
    return Layer1Service(
        SubmissionRepository(session),
        PipelineRepository(session),
        DocumentRepository(session),
        CodeRepository(session),
        ReportPreprocessingService(reader, get_parser_adapter(), settings),
        ClaimExtractionService(ClaimLLMAdapter(settings)),
        SourceCodePreprocessingService(
            reader,
            SafeZipExtractor(settings),
            GraphifyAdapter(settings),
            writer,
            settings,
        ),
    )
