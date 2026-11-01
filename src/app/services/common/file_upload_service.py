from hashlib import sha256
from pathlib import Path
from typing import Any, BinaryIO, Protocol
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.schemas.upload_schema import CloudinaryUploadResponse, UploadArtifactKind


class ObjectStorageRepository(Protocol):
    async def upload_raw(
        self,
        file_object: BinaryIO,
        *,
        folder: str,
        public_id: str,
    ) -> dict[str, Any]: ...


class FileUploadService:
    _report_media_types = frozenset({"application/pdf"})
    _source_media_types = frozenset({"application/zip", "application/x-zip-compressed"})

    def __init__(self, repository: ObjectStorageRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    async def upload_submission_file(
        self,
        submission_id: UUID,
        kind: UploadArtifactKind,
        file: UploadFile,
    ) -> CloudinaryUploadResponse:
        filename = Path(file.filename or "").name
        media_type = file.content_type or "application/octet-stream"
        max_bytes = self._validate_metadata(kind, filename, media_type)
        byte_size, digest = await self._measure_and_hash(file, max_bytes)

        public_id = uuid4().hex
        folder = f"{self._settings.cloudinary_folder}/submissions/{submission_id}/{kind.value}"
        result = await self._repository.upload_raw(
            file.file,
            folder=folder,
            public_id=public_id,
        )

        try:
            remote_public_id = str(result["public_id"])
            resource_type = str(result["resource_type"])
            delivery_type = str(result["type"])
            return CloudinaryUploadResponse(
                submission_id=submission_id,
                kind=kind,
                asset_id=str(result["asset_id"]),
                public_id=remote_public_id,
                resource_type=resource_type,
                delivery_type=delivery_type,
                object_uri=(f"cloudinary://{resource_type}/{delivery_type}/{remote_public_id}"),
                secure_url=str(result["secure_url"]),
                original_filename=filename,
                media_type=media_type,
                byte_size=byte_size,
                sha256=digest,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(ErrorCode.STORAGE_ERROR, "Invalid response from Cloudinary") from exc

    def _validate_metadata(
        self,
        kind: UploadArtifactKind,
        filename: str,
        media_type: str,
    ) -> int:
        if not filename:
            raise AppError(ErrorCode.BAD_REQUEST, "File name is required")

        if kind is UploadArtifactKind.REPORT_PDF:
            is_invalid_pdf = (
                Path(filename).suffix.lower() != ".pdf"
                or media_type not in self._report_media_types
            )
            if is_invalid_pdf:
                raise AppError(ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Report must be a PDF file")
            return self._settings.max_report_bytes

        if Path(filename).suffix.lower() != ".zip" or media_type not in self._source_media_types:
            raise AppError(ErrorCode.UNSUPPORTED_MEDIA_TYPE, "Source code must be a ZIP file")
        return self._settings.max_source_bytes

    @staticmethod
    async def _measure_and_hash(file: UploadFile, max_bytes: int) -> tuple[int, str]:
        digest = sha256()
        byte_size = 0

        await file.seek(0)
        while chunk := await file.read(1024 * 1024):
            byte_size += len(chunk)
            if byte_size > max_bytes:
                await file.seek(0)
                raise AppError(
                    ErrorCode.PAYLOAD_TOO_LARGE,
                    f"File exceeds the {max_bytes}-byte limit",
                )
            digest.update(chunk)
        await file.seek(0)

        if byte_size == 0:
            raise AppError(ErrorCode.BAD_REQUEST, "File must not be empty")
        return byte_size, digest.hexdigest()
