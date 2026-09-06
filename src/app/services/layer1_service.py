import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.repositories.code_repository import CodeRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.pipeline_repository import PipelineRepository
from app.repositories.submission_repository import SubmissionRepository
from app.schemas.layer1_schema import ExtractedClaim, ReportRepresentation, SourceCodeRepresentation
from app.schemas.pipeline_schema import PipelineRunResponse
from app.services.claim_extraction_service import ClaimExtractionService
from app.services.report_preprocessing_service import ReportPreprocessingService
from app.services.source_code_preprocessing_service import SourceCodePreprocessingService

logger = logging.getLogger("uvicorn.error")


class Layer1Service:
    def __init__(
        self,
        submission_repository: SubmissionRepository,
        pipeline_repository: PipelineRepository,
        document_repository: DocumentRepository,
        code_repository: CodeRepository,
        report_preprocessor: ReportPreprocessingService,
        claim_extractor: ClaimExtractionService,
        source_code_preprocessor: SourceCodePreprocessingService,
    ) -> None:
        self.submission_repository = submission_repository
        self.pipeline_repository = pipeline_repository
        self.document_repository = document_repository
        self.code_repository = code_repository
        self.report_preprocessor = report_preprocessor
        self.claim_extractor = claim_extractor
        self.source_code_preprocessor = source_code_preprocessor

    async def submit(self, submission_id: UUID) -> PipelineRunResponse:
        logger.info("Layer 1: loading submission %s", submission_id)
        submission = await self.submission_repository.get_for_update(submission_id)
        if submission is None:
            raise AppError(ErrorCode.SUBMISSION_NOT_FOUND)

        if submission.status != "uploaded":
            raise AppError(ErrorCode.INVALID_STATE_TRANSITION)

        report_artifact = await self.submission_repository.get_latest_artifact(
            submission_id, "report_pdf"
        )
        source_artifact = await self.submission_repository.get_latest_artifact(
            submission_id, "source_archive"
        )

        if report_artifact is None or source_artifact is None:
            raise AppError(ErrorCode.ARTIFACT_NOT_FOUND)
        logger.info("Layer 1: report and source artifacts found")

        input_fingerprint = self._fingerprint(
            {
                "report": report_artifact.sha256,
                "source": source_artifact.sha256,
                "schema_version": "1.0",
            }
        )
        run = await self.pipeline_repository.create_run(
            {
                "submission_id": submission_id,
                "pipeline": "L1",
                "status": "running",
                "attempt_no": 1,
                "code_version": "0.1.0",
                "schema_version": "1.0",
                "policy_version": "1.0",
                "input_fingerprint": input_fingerprint,
                "config": {},
                "started_at": datetime.now(UTC),
            }
        )
        await self.submission_repository.update_status(submission_id, "processing")

        async def process_report_branch() -> tuple[ReportRepresentation, list[ExtractedClaim]]:
            logger.info("Layer 1: processing report with PaddleOCR")
            report = await self.report_preprocessor.process_artifact(report_artifact)
            if report.artifact_id != report_artifact.id:
                raise AppError(ErrorCode.PARSER_ERROR, "Report parser returned a wrong artifact")
            logger.info(
                "Layer 1: report parsed, sections=%s blocks=%s",
                len(report.sections),
                len(report.blocks),
            )
            logger.info("Layer 1: extracting claims with LLM")
            claims = await self.claim_extractor.extract(submission_id, report)
            logger.info("Layer 1: claims extracted, count=%s", len(claims))
            return report, claims

        async def process_source_branch() -> SourceCodeRepresentation:
            logger.info("Layer 1: processing source archive with Graphify")
            code = await self.source_code_preprocessor.process_artifact(source_artifact)
            if code.source_artifact_id != source_artifact.id:
                raise AppError(ErrorCode.PARSER_ERROR, "Code parser returned a wrong artifact")
            if code.source_sha256 != source_artifact.sha256:
                raise AppError(ErrorCode.CONFLICT, "Source artifact changed during Layer 1")
            logger.info("Layer 1: source graph completed")
            return code

        logger.info("Layer 1: starting report and source branches concurrently")
        branch_results = await asyncio.gather(
            process_report_branch(),
            process_source_branch(),
            return_exceptions=True,
        )
        report_result, code_result = branch_results
        if isinstance(report_result, BaseException):
            raise report_result
        if isinstance(code_result, BaseException):
            raise code_result
        report, claims = report_result
        code = code_result

        logger.info("Layer 1: saving normalized results")
        section_ids = await self.document_repository.save_sections(
            report.artifact_id, report.sections
        )
        block_ids = await self.document_repository.save_blocks(
            report.artifact_id,
            report.parser_version,
            report.blocks,
            section_ids,
        )
        await self.document_repository.save_claims(submission_id, claims, block_ids)
        await self.code_repository.save_graph_snapshot(submission_id, code)

        output_fingerprint = self._fingerprint(
            {
                "report": report.model_dump(mode="json"),
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "graph_sha256": code.graph_sha256,
            }
        )
        await self.pipeline_repository.mark_succeeded(run.id, output_fingerprint)
        logger.info("Layer 1 completed: run_id=%s", run.id)
        return PipelineRunResponse.model_validate(run, from_attributes=True)

    @staticmethod
    def _fingerprint(payload: object) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
