from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.archive import SafeZipExtractor
from app.adapters.bm25_retriever import BM25Retriever
from app.adapters.claim_llm import ClaimLLMAdapter
from app.adapters.colab_parser import ColabParserAdapter
from app.adapters.crossref import CrossrefAdapter
from app.adapters.graphify import GraphifyAdapter
from app.adapters.llm_citation_judge import LLMCitationJudge
from app.adapters.llm_code_judge import LLMCodeConsistencyJudge
from app.adapters.local_parser import LocalParserAdapter
from app.adapters.open_access import OpenAccessAdapter
from app.adapters.parser import PaddleParserAdapter
from app.core.authorization import (
    AuthenticatedUser,
    GlobalRole,
    Permission,
    TokenType,
    decode_token,
    resolve_effective_permissions,
)
from app.core.config import get_settings
from app.core.database import get_session
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.artifact_repository import ArtifactRepository, GraphArtifactWriter
from app.repositories.auth_repository import AuthRepository
from app.repositories.cloudinary_repository import CloudinaryRepository
from app.repositories.code_repository import CodeRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.p2_repository import P2Repository
from app.repositories.p3_repository import P3Repository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.reference_repository import ReferenceRepository
from app.repositories.submission_repository import SubmissionRepository
from app.services.auth.auth_service import AuthService
from app.services.common.file_upload_service import FileUploadService
from app.services.common.submission_service import SubmissionService
from app.services.layer1.claim_extraction_service import ClaimExtractionService
from app.services.layer1.layer1_service import Layer1Service
from app.services.layer1.reference_extraction_service import ReferenceExtractionService
from app.services.layer1.report_preprocessing_service import ReportPreprocessingService
from app.services.layer1.source_code_preprocessing_service import SourceCodePreprocessingService
from app.services.layer2.pipeline2.citation_verification_service import CitationVerificationService
from app.services.layer2.pipeline2.pipeline2_service import Pipeline2Service
from app.services.layer2.pipeline2.reference_resolution_service import ReferenceResolutionService
from app.services.layer2.pipeline3.cascade_execution_service import CascadeExecutionService
from app.services.layer2.pipeline3.code_highlight_service import CodeHighlightService
from app.services.layer2.pipeline3.code_semantic_judge_service import CodeSemanticJudgeService
from app.services.layer2.pipeline3.pipeline3_service import Pipeline3Service
from app.services.layer2.pipeline3.structural_consistency_service import (
    StructuralConsistencyService,
)


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
        OpenAccessAdapter(settings),
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
            OpenAccessAdapter(settings),
        ),
        CitationVerificationService(
            LLMCitationJudge(settings),
            settings,
            BM25Retriever(),
        ),
    )


def get_pipeline3_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Pipeline3Service:
    settings = get_settings()
    return Pipeline3Service(
        SubmissionRepository(session),
        PipelineRepository(session),
        P3Repository(session),
        StructuralConsistencyService(),
        CodeSemanticJudgeService(
            confidence_threshold=settings.citation_judge_confidence_threshold,
            llm=LLMCodeConsistencyJudge(settings),
            max_cards=settings.code_judge_max_cards,
        ),
        CascadeExecutionService(),
        CodeHighlightService(),
        semantic_concurrency=settings.code_judge_concurrency,
    )


bearer_scheme = HTTPBearer(auto_error=False, scheme_name="BearerAuth")


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    settings = get_settings()
    return AuthService(AuthRepository(session), settings)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials.strip()
    ):
        raise AppError(ErrorCode.UNAUTHORIZED)
    return await auth_service.authenticate_access_token(credentials.credentials.strip())


async def get_optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser | None:
    settings = get_settings()
    if credentials is None:
        if settings.auth_enforced:
            raise AppError(ErrorCode.UNAUTHORIZED)
        return None
    if credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
        raise AppError(ErrorCode.UNAUTHORIZED, "Invalid authorization header")
    claims = decode_token(
        credentials.credentials.strip(),
        settings,
        expected_type=TokenType.ACCESS,
    )
    return AuthenticatedUser(
        id=claims.sub,
        email=claims.email,
        display_name=claims.display_name,
        global_role=claims.global_role,
        is_active=True,
        permissions=frozenset(claims.permissions)
        or resolve_effective_permissions(claims.global_role),
        token_jti=claims.jti,
    )


def require_global_roles(
    *roles: GlobalRole,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def _dependency(
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        if not current_user.has_any_global_role(*roles):
            allowed_str = ", ".join(r.value for r in roles)
            raise AppError(
                ErrorCode.FORBIDDEN,
                f"Requires global role in [{allowed_str}]",
            )
        return current_user

    return _dependency


def require_permissions(
    *permissions: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def _dependency(
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        for perm in permissions:
            if not current_user.has_permission(perm):
                raise AppError(
                    ErrorCode.FORBIDDEN,
                    f"Missing required permission: {perm.value}",
                )
        return current_user

    return _dependency


def require_course_permission(
    permission: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def _dependency(
        course_id: UUID,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> AuthenticatedUser:
        await auth_service.enforce_permission(
            current_user,
            permission,
            course_id=course_id,
        )
        return current_user

    return _dependency


def require_group_permission(
    permission: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def _dependency(
        project_id: UUID,
        group_id: UUID,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> AuthenticatedUser:
        await auth_service.enforce_permission(
            current_user,
            permission,
            project_id=project_id,
            group_id=group_id,
        )
        return current_user

    return _dependency


def require_submission_permission(
    permission: Permission,
) -> Callable[..., Awaitable[AuthenticatedUser]]:
    async def _dependency(
        submission_id: UUID,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
        auth_service: Annotated[AuthService, Depends(get_auth_service)],
    ) -> AuthenticatedUser:
        await auth_service.enforce_permission(
            current_user,
            permission,
            submission_id=submission_id,
        )
        return current_user

    return _dependency
