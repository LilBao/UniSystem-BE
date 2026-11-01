import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.error_codes import ErrorCode
from app.core.exceptions import AppError

logger = logging.getLogger("uvicorn.error")

_RETRY_STATUSES = {408, 500, 502, 503, 504}


class PaddleParserAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def version(self) -> str:
        return f"{self.settings.paddleocr_model}:official-api-adapter-2"

    async def parse_pdf(self, file: Path) -> list[dict[str, Any]]:
        return await run_in_threadpool(self._parse_pdf, file)

    def _parse_pdf(self, file: Path) -> list[dict[str, Any]]:
        if not self.settings.paddleocr_access_token:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "PADDLEOCR_ACCESS_TOKEN is not configured",
            )

        headers = {"Authorization": f"bearer {self.settings.paddleocr_access_token}"}
        options = {
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }

        try:
            with requests.Session() as client:
                logger.info(
                    "PaddleOCR: uploading PDF, bytes=%s, model=%s",
                    file.stat().st_size,
                    self.settings.paddleocr_model,
                )
                response = self._upload_with_retry(client, file, headers, options)
                response.raise_for_status()
                job_id = str(response.json()["data"]["jobId"])
                logger.info("PaddleOCR job submitted: job_id=%s", job_id)

                jsonl_url = self._poll(client, headers, job_id)

                result = client.get(
                    jsonl_url,
                    timeout=(
                        self.settings.paddleocr_connect_timeout_seconds,
                        self.settings.paddleocr_request_timeout_seconds,
                    ),
                )
                result.raise_for_status()
                return self._parse_jsonl(result.text)
        except AppError:
            raise
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            msg = f"PaddleOCR HTTP {status}: request failed"
            logger.error("%s", msg)
            raise AppError(ErrorCode.PARSER_ERROR, msg) from exc
        except requests.ConnectionError as exc:
            msg = f"PaddleOCR connection error: {exc}"
            logger.error("%s", msg)
            raise AppError(ErrorCode.PARSER_ERROR, msg) from exc
        except requests.Timeout as exc:
            msg = f"PaddleOCR request timed out: {exc}"
            logger.error("%s", msg)
            raise AppError(ErrorCode.PARSER_ERROR, msg) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(ErrorCode.PARSER_ERROR, "Invalid PaddleOCR response") from exc

    def _upload_with_retry(
        self,
        client: requests.Session,
        file: Path,
        headers: dict[str, str],
        options: dict[str, bool],
    ) -> requests.Response:
        max_attempts = self.settings.paddleocr_retry_attempts
        for attempt in range(1, max_attempts + 1):
            try:
                with file.open("rb") as source:
                    response = client.post(
                        self.settings.paddleocr_job_url,
                        headers=headers,
                        data={
                            "model": self.settings.paddleocr_model,
                            "optionalPayload": json.dumps(options),
                        },
                        files={"file": source},
                        timeout=(
                            self.settings.paddleocr_connect_timeout_seconds,
                            self.settings.paddleocr_upload_timeout_seconds,
                        ),
                    )
                if response.status_code not in _RETRY_STATUSES or attempt == max_attempts:
                    return response
                reason = f"HTTP {response.status_code}"
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == max_attempts:
                    raise
                reason = str(exc)

            delay = self.settings.paddleocr_retry_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "PaddleOCR upload failed (%s), retry %s/%s in %.1fs",
                reason,
                attempt + 1,
                max_attempts,
                delay,
            )
            time.sleep(delay)

        raise RuntimeError("Unreachable retry state")

    def _poll(
        self,
        client: requests.Session,
        headers: dict[str, str],
        job_id: str,
    ) -> str:
        deadline = time.monotonic() + self.settings.paddleocr_poll_timeout_seconds
        url = f"{self.settings.paddleocr_job_url.rstrip('/')}/{job_id}"

        while time.monotonic() < deadline:
            response = client.get(
                url,
                headers=headers,
                timeout=(
                    self.settings.paddleocr_connect_timeout_seconds,
                    self.settings.paddleocr_request_timeout_seconds,
                ),
            )
            response.raise_for_status()
            data = response.json()["data"]
            state = data["state"]
            logger.info("PaddleOCR job %s: state=%s", job_id, state)
            if state == "done":
                return str(data["resultUrl"]["jsonUrl"])
            if state == "failed":
                raise AppError(
                    ErrorCode.PARSER_ERROR,
                    f"PaddleOCR job failed: {data.get('errorMsg') or 'Unknown error'}",
                )
            if state not in {"pending", "running"}:
                raise AppError(ErrorCode.PARSER_ERROR, f"Unknown PaddleOCR state: {state}")

            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(self.settings.paddleocr_poll_interval_seconds, remaining))

        raise AppError(ErrorCode.PARSER_ERROR, "PaddleOCR job polling timed out")

    def _parse_jsonl(self, content: str) -> list[dict[str, Any]]:
        if len(content.encode("utf-8")) > self.settings.ocr_max_output_bytes:
            raise AppError(ErrorCode.PARSER_ERROR, "OCR output exceeds quota")
        pages = [
            {"parsing_res_list": item["prunedResult"]["parsing_res_list"]}
            for line in content.splitlines()
            if line.strip()
            for item in json.loads(line)["result"]["layoutParsingResults"]
        ]
        if not pages:
            raise AppError(ErrorCode.PARSER_ERROR, "PaddleOCR returned no pages")
        return pages
