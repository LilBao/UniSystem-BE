from collections.abc import Callable
from functools import partial
from typing import Any, BinaryIO

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

UploadCallable = Callable[..., dict[str, Any]]
ConfigureCallable = Callable[..., Any]


class CloudinaryRepository:
    def __init__(
        self,
        settings: Settings,
        upload_callable: UploadCallable | None = None,
        configure_callable: ConfigureCallable | None = None,
    ) -> None:
        self._settings = settings
        self._upload_callable = upload_callable
        self._configure_callable = configure_callable

    def _load_sdk(self) -> tuple[UploadCallable, ConfigureCallable]:
        if self._upload_callable is not None:
            configure = self._configure_callable or (lambda **_: None)
            return self._upload_callable, configure
        try:
            import cloudinary
            import cloudinary.uploader
        except (ImportError, OSError) as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Cloudinary SDK is not available",
            ) from exc
        return self._upload_callable or cloudinary.uploader.upload, (
            self._configure_callable or cloudinary.config
        )

    async def upload_raw(
        self,
        file_object: BinaryIO,
        *,
        folder: str,
        public_id: str,
    ) -> dict[str, Any]:
        if not all(
            (
                self._settings.cloudinary_cloud_name,
                self._settings.cloudinary_api_key,
                self._settings.cloudinary_api_secret,
            )
        ):
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Cloudinary credentials are not configured",
            )

        upload_callable, configure_callable = self._load_sdk()
        configure_callable(
            cloud_name=self._settings.cloudinary_cloud_name,
            api_key=self._settings.cloudinary_api_key,
            api_secret=self._settings.cloudinary_api_secret,
            secure=True,
        )

        try:
            upload = partial(
                upload_callable,
                file_object,
                resource_type="raw",
                type=self._settings.cloudinary_delivery_type,
                folder=folder,
                public_id=public_id,
                overwrite=False,
                use_filename=False,
                unique_filename=False,
            )
            return await run_in_threadpool(upload)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(ErrorCode.STORAGE_ERROR, "Could not upload file") from exc
