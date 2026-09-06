import logging
from pathlib import Path
from threading import Lock
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

logger = logging.getLogger("uvicorn.error")


class LocalParserAdapter:
    """OCR local dùng PaddleOCR-VL chạy trên máy, không cần API key."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pipeline: Any = None
        self._lock = Lock()

    @property
    def version(self) -> str:
        return f"PaddleOCR-VL:{self.settings.ocr_pipeline_version}:local-adapter-1"

    async def parse_pdf(self, file: Path) -> list[dict[str, Any]]:
        return await run_in_threadpool(self._parse, file)

    def _parse(self, file: Path) -> list[dict[str, Any]]:
        with self._lock:
            if self._pipeline is None:
                self._pipeline = self._create_pipeline()
            try:
                logger.info(
                    "LocalOCR: processing PDF, bytes=%s, version=%s",
                    file.stat().st_size,
                    self.settings.ocr_pipeline_version,
                )
                pages = [
                    {"parsing_res_list": result.json["res"]["parsing_res_list"]}
                    for result in self._pipeline.predict(input=str(file))
                ]
                return self._validate(pages)
            except AppError:
                raise
            except Exception as exc:
                logger.exception("LocalOCR inference failed")
                raise AppError(
                    ErrorCode.PARSER_ERROR,
                    "Local PaddleOCR-VL inference failed",
                ) from exc

    def _validate(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not pages:
            raise AppError(ErrorCode.PARSER_ERROR, "LocalOCR returned no pages")
        import json

        byte_size = 0
        for page in pages:
            if not isinstance(page.get("parsing_res_list"), list):
                raise AppError(ErrorCode.PARSER_ERROR, "LocalOCR returned invalid page blocks")
            byte_size += len(json.dumps(page, ensure_ascii=False).encode("utf-8"))
            if byte_size > self.settings.ocr_max_output_bytes:
                raise AppError(ErrorCode.PARSER_ERROR, "OCR output exceeds quota")
        return pages

    def _create_pipeline(self) -> Any:
        try:
            import paddleocr  # type: ignore[import-untyped]

            logger.info(
                "LocalOCR: initializing PaddleOCR-VL, device=%s, version=%s",
                self.settings.ocr_device,
                self.settings.ocr_pipeline_version,
            )
            return paddleocr.PaddleOCRVL(
                device=self.settings.ocr_device,
                pipeline_version=self.settings.ocr_pipeline_version,
                use_layout_detection=True,
            )
        except ImportError as exc:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Local OCR dependencies are missing; install paddleocr package",
            ) from exc
        except Exception as exc:
            logger.exception("Could not initialize local PaddleOCR-VL")
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Could not initialize local PaddleOCR-VL; check runtime, device and model download",
            ) from exc
