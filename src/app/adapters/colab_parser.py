import asyncio
import logging
import time
from pathlib import Path
from typing import Any, cast

import httpx

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

logger = logging.getLogger("uvicorn.error")


class ColabParserAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def version(self) -> str:
        return f"PaddleOCR-VL:{self.settings.ocr_pipeline_version}:colab-gpu-adapter"

    async def parse_pdf(self, file: Path) -> list[dict[str, Any]]:
        if not self.settings.ocr_colab_url:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "OCR_COLAB_URL is not configured in .env",
            )

        base_url = self.settings.ocr_colab_url.strip().rstrip("/")
        headers = {"ngrok-skip-browser-warning": "1"}
        upload_timeout = httpx.Timeout(120.0, connect=30.0, read=120.0)

        async with httpx.AsyncClient(timeout=upload_timeout) as client:
            logger.info(
                "ColabOCR: uploading PDF to %s/jobs, bytes=%s",
                base_url,
                file.stat().st_size,
            )
            try:
                with file.open("rb") as f:
                    files = {"file": (file.name, f, "application/pdf")}
                    resp = await client.post(f"{base_url}/jobs", files=files, headers=headers)
                    resp.raise_for_status()
                    job_id = resp.json()["job_id"]
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return await self._parse_direct(client, base_url, file, headers)
                logger.exception("Colab OCR job creation failed: %s", exc)
                raise AppError(ErrorCode.PARSER_ERROR, f"Colab OCR failed: {exc}") from exc
            except Exception as exc:
                logger.exception("Colab OCR job creation failed: %s", exc)
                raise AppError(ErrorCode.PARSER_ERROR, f"Colab OCR failed: {exc}") from exc

            logger.info("ColabOCR: job created (job_id=%s), polling GPU progress...", job_id)
            start_time = time.time()
            max_wait_seconds = 900.0  # Tối đa 15 phút

            poll_timeout = httpx.Timeout(15.0, connect=10.0, read=15.0)
            while time.time() - start_time < max_wait_seconds:
                await asyncio.sleep(4)
                try:
                    poll_resp = await client.get(
                        f"{base_url}/jobs/{job_id}",
                        headers=headers,
                        timeout=poll_timeout,
                    )
                    poll_resp.raise_for_status()
                    data = poll_resp.json()
                    status = data.get("status")

                    if status == "completed":
                        pages = data.get("result")
                        if not isinstance(pages, list):
                            raise ValueError("Invalid pages format in Colab response")
                        logger.info(
                            "ColabOCR: job %s completed with %s pages in %.1fs",
                            job_id,
                            len(pages),
                            time.time() - start_time,
                        )
                        return pages
                    elif status == "failed":
                        err_msg = data.get("error", "Unknown error")
                        logger.error("ColabOCR: job %s failed on Colab: %s", job_id, err_msg)
                        raise AppError(
                            ErrorCode.PARSER_ERROR,
                            f"Colab GPU processing error: {err_msg}",
                        )
                except AppError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "ColabOCR: transient polling error on job %s: %s, retrying...",
                        job_id,
                        exc,
                    )

            raise AppError(ErrorCode.PARSER_ERROR, "Colab OCR job timed out after 15 minutes")

    async def _parse_direct(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        file: Path,
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        long_timeout = httpx.Timeout(600.0, connect=30.0, read=600.0)
        with file.open("rb") as f:
            files = {"file": (file.name, f, "application/pdf")}
            resp = await client.post(
                f"{base_url}/predict",
                files=files,
                headers=headers,
                timeout=long_timeout,
            )
            resp.raise_for_status()
            return cast(list[dict[str, Any]], resp.json())
