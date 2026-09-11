from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.controllers.pipeline2_controller import router as pipeline2_router
from app.controllers.reference_controller import router as reference_router
from app.controllers.submission_controller import router as submission_router
from app.controllers.upload_controller import router as upload_router
from app.core.config import get_settings
from app.core.error_codes import ErrorCode, get_error
from app.core.exceptions import AppError
from app.services.cache_eviction_service import evict_stale_cache


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    import asyncio

    settings = get_settings()
    await asyncio.to_thread(evict_stale_cache, settings)
    yield


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.include_router(submission_router)
app.include_router(upload_router)
app.include_router(reference_router)
app.include_router(pipeline2_router)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    error = get_error(ErrorCode.VALIDATION_ERROR)
    return JSONResponse(
        status_code=error.http_status,
        content={
            "errorCode": error.error_code,
            "code": ErrorCode.VALIDATION_ERROR.value,
            "message": error.message,
            "details": exc.errors(),
        },
    )


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "errorCode": exc.error_code,
            "code": exc.code.value,
            "message": exc.message,
        },
    )


@app.exception_handler(NotImplementedError)
async def handle_not_implemented(_: Request, exc: NotImplementedError) -> JSONResponse:
    error = get_error(ErrorCode.NOT_IMPLEMENTED)
    return JSONResponse(
        status_code=error.http_status,
        content={
            "errorCode": error.error_code,
            "code": ErrorCode.NOT_IMPLEMENTED.value,
            "message": str(exc) or error.message,
        },
    )


@app.get("/health", tags=["System"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
