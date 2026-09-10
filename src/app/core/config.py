from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "DACN Evaluation API"
    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://dacn:dacn@localhost:5432/dacn"
    redis_url: str = "redis://localhost:6379/0"
    parser_timeout_seconds: float = 120
    parser_max_response_bytes: int = 32 * 1024 * 1024
    artifact_download_timeout_seconds: float = 120
    source_extract_max_files: int = 10_000
    source_extract_max_total_bytes: int = 512 * 1024 * 1024
    source_extract_max_file_bytes: int = 10 * 1024 * 1024
    source_extract_max_depth: int = 20
    source_extract_max_ratio: float = 100
    source_parse_max_file_bytes: int = 2 * 1024 * 1024
    ocr_provider: Literal["paddle_official", "local", "colab"] = "paddle_official"
    ocr_colab_url: str = ""
    paddleocr_upload_mode: Literal["auto", "file", "pages"] = "auto"
    paddleocr_access_token: str = ""
    paddleocr_model: Literal["PaddleOCR-VL", "PaddleOCR-VL-1.5", "PaddleOCR-VL-1.6"] = (
        "PaddleOCR-VL-1.6"
    )
    paddleocr_job_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_connect_timeout_seconds: float = 30
    paddleocr_request_timeout_seconds: float = 300
    paddleocr_upload_timeout_seconds: float = 60
    paddleocr_poll_timeout_seconds: float = 1800
    paddleocr_poll_interval_seconds: float = 5
    paddleocr_retry_attempts: int = 4
    paddleocr_retry_backoff_seconds: float = 2
    paddleocr_page_concurrency: int = 3
    ocr_device: str = "cpu"
    ocr_pipeline_version: Literal["v1", "v1.5", "v1.6"] = "v1.5"
    ocr_max_output_bytes: int = 32 * 1024 * 1024
    claim_llm_url: str = ""
    claim_llm_api_key: str = ""
    claim_llm_model: str = ""
    claim_max_input_chars: int = 24000
    cache_dir: Path = Path(".cache")
    cache_ttl_days: int = 7
    graphify_version: str = "0.9.55"
    graphify_timeout_seconds: float = 1800
    graphify_max_workers: int = 4

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = "dacn"
    cloudinary_delivery_type: str = "authenticated"

    max_report_bytes: int = 50 * 1024 * 1024
    max_source_bytes: int = 200 * 1024 * 1024

    @model_validator(mode="after")
    def validate_processing_limits(self) -> "Settings":
        for name in (
            "parser_timeout_seconds",
            "parser_max_response_bytes",
            "ocr_max_output_bytes",
            "paddleocr_connect_timeout_seconds",
            "paddleocr_request_timeout_seconds",
            "paddleocr_upload_timeout_seconds",
            "paddleocr_poll_timeout_seconds",
            "paddleocr_poll_interval_seconds",
            "paddleocr_retry_attempts",
            "paddleocr_retry_backoff_seconds",
            "paddleocr_page_concurrency",
            "artifact_download_timeout_seconds",
            "source_extract_max_files",
            "source_extract_max_total_bytes",
            "source_extract_max_file_bytes",
            "source_extract_max_depth",
            "source_extract_max_ratio",
            "source_parse_max_file_bytes",
            "claim_max_input_chars",
            "cache_ttl_days",
            "graphify_timeout_seconds",
            "graphify_max_workers",
            "max_report_bytes",
            "max_source_bytes",
        ):
            value = float(getattr(self, name))
            if not 0 < value < float("inf"):
                raise ValueError(f"{name} must be positive and finite")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
