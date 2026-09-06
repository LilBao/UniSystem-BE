import asyncio
import hashlib
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError
from app.models.submission_model import Artifact
from app.repositories.cloudinary_repository import CloudinaryRepository


class ArtifactRepository:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def get_owned(self, submission_id: UUID, artifact_id: UUID, kind: str) -> Artifact:
        artifact = await self.session.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.submission_id == submission_id,
                Artifact.kind == kind,
            )
        )
        if artifact is None:
            raise AppError(ErrorCode.ARTIFACT_NOT_FOUND)
        return artifact

    def _download_url(self, artifact: Artifact, lifetime_seconds: int = 300) -> str:
        uri = urlsplit(artifact.object_uri)
        delivery, _, public_id = uri.path.lstrip("/").partition("/")
        prefix = (
            f"{self.settings.cloudinary_folder}/submissions/"
            f"{artifact.submission_id}/{artifact.kind}/"
        )
        if (
            uri.scheme != "cloudinary"
            or uri.netloc != "raw"
            or delivery != self.settings.cloudinary_delivery_type
            or not public_id.startswith(prefix)
            or not public_id[len(prefix) :]
            or uri.query
            or uri.fragment
            or any(p in {".", ".."} for p in public_id.split("/"))
        ):
            raise AppError(ErrorCode.STORAGE_ERROR, "Invalid artifact storage location")
        if not all(
            (
                self.settings.cloudinary_cloud_name,
                self.settings.cloudinary_api_key,
                self.settings.cloudinary_api_secret,
            )
        ):
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE, "Cloudinary credentials are not configured"
            )
        try:
            from cloudinary.utils import private_download_url

            return str(
                private_download_url(
                    public_id,
                    "",
                    resource_type="raw",
                    type=delivery,
                    expires_at=int(time.time()) + lifetime_seconds,
                    cloud_name=self.settings.cloudinary_cloud_name,
                    api_key=self.settings.cloudinary_api_key,
                    api_secret=self.settings.cloudinary_api_secret,
                    secure=True,
                )
            )
        except (ImportError, OSError, ValueError) as exc:
            raise AppError(ErrorCode.STORAGE_ERROR, "Could not sign artifact download") from exc

    def ocr_download_url(self, artifact: Artifact) -> str:
        lifetime = int(
            self.settings.paddleocr_poll_timeout_seconds
            + self.settings.paddleocr_request_timeout_seconds
        ) + 300
        return self._download_url(artifact, lifetime)

    async def download_to(self, artifact: Artifact, destination: Path, max_bytes: int) -> None:
        if artifact.byte_size <= 0 or artifact.byte_size > max_bytes:
            raise AppError(ErrorCode.PAYLOAD_TOO_LARGE)
        url = self._download_url(artifact)
        digest = hashlib.sha256()
        size = 0
        try:
            async with asyncio.timeout(self.settings.artifact_download_timeout_seconds):
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        with destination.open("xb") as output:
                            async for chunk in response.aiter_bytes(64 * 1024):
                                size += len(chunk)
                                if size > max_bytes or size > artifact.byte_size:
                                    raise AppError(ErrorCode.PAYLOAD_TOO_LARGE)
                                digest.update(chunk)
                                output.write(chunk)
            if size != artifact.byte_size or digest.hexdigest() != artifact.sha256:
                raise AppError(ErrorCode.CONFLICT, "Artifact checksum or size changed")
        except (httpx.HTTPError, TimeoutError, OSError) as exc:
            raise AppError(ErrorCode.STORAGE_ERROR, "Could not download artifact") from exc


class GraphArtifactWriter:
    def __init__(self, storage: CloudinaryRepository, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    async def upload(self, submission_id: UUID, graph_file: Path, sha256: str) -> str:
        with graph_file.open("rb") as source:
            result = await self.storage.upload_raw(
                source,
                folder=f"{self.settings.cloudinary_folder}/submissions/{submission_id}/code_graph",
                public_id=f"{sha256}.json",
            )
        try:
            if result["resource_type"] != "raw" or not result["public_id"]:
                raise ValueError("Invalid graph object")
            return f"cloudinary://raw/{result['type']}/{result['public_id']}"
        except (KeyError, ValueError, TypeError) as exc:
            raise AppError(ErrorCode.STORAGE_ERROR, "Invalid graph upload response") from exc
