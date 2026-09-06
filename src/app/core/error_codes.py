from enum import StrEnum
from http import HTTPStatus
from typing import Final, NamedTuple


class ErrorCode(StrEnum):
    BAD_REQUEST = "bad_request"
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    TOKEN_EXPIRED = "token_expired"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    SUBMISSION_NOT_FOUND = "submission_not_found"
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    PIPELINE_RUN_NOT_FOUND = "pipeline_run_not_found"
    CONFLICT = "conflict"
    DUPLICATE_RESOURCE = "duplicate_resource"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"
    NOT_IMPLEMENTED = "not_implemented"
    DATABASE_ERROR = "database_error"
    STORAGE_ERROR = "storage_error"
    PARSER_ERROR = "parser_error"
    SERVICE_UNAVAILABLE = "service_unavailable"


class ErrorDefinition(NamedTuple):
    error_code: int
    http_status: int
    message: str


# Quy ước số: 40300 = HTTP 403 + lỗi tổng quát số 00.
# Các lỗi cùng HTTP status tăng hậu tố: 40401, 40402, 40403...
ERROR_CATALOG: Final[dict[ErrorCode, ErrorDefinition]] = {
    ErrorCode.BAD_REQUEST: ErrorDefinition(40000, HTTPStatus.BAD_REQUEST, "Bad request"),
    ErrorCode.VALIDATION_ERROR: ErrorDefinition(
        42200, HTTPStatus.UNPROCESSABLE_ENTITY, "Request validation failed"
    ),
    ErrorCode.UNAUTHORIZED: ErrorDefinition(
        40100, HTTPStatus.UNAUTHORIZED, "Authentication required"
    ),
    ErrorCode.TOKEN_EXPIRED: ErrorDefinition(
        40101, HTTPStatus.UNAUTHORIZED, "Authentication token expired"
    ),
    ErrorCode.FORBIDDEN: ErrorDefinition(40300, HTTPStatus.FORBIDDEN, "Forbidden"),
    ErrorCode.NOT_FOUND: ErrorDefinition(40400, HTTPStatus.NOT_FOUND, "Resource not found"),
    ErrorCode.SUBMISSION_NOT_FOUND: ErrorDefinition(
        40401, HTTPStatus.NOT_FOUND, "Submission not found"
    ),
    ErrorCode.ARTIFACT_NOT_FOUND: ErrorDefinition(
        40402, HTTPStatus.NOT_FOUND, "Artifact not found"
    ),
    ErrorCode.PIPELINE_RUN_NOT_FOUND: ErrorDefinition(
        40403, HTTPStatus.NOT_FOUND, "Pipeline run not found"
    ),
    ErrorCode.CONFLICT: ErrorDefinition(40900, HTTPStatus.CONFLICT, "Resource conflict"),
    ErrorCode.DUPLICATE_RESOURCE: ErrorDefinition(
        40901, HTTPStatus.CONFLICT, "Resource already exists"
    ),
    ErrorCode.INVALID_STATE_TRANSITION: ErrorDefinition(
        40902, HTTPStatus.CONFLICT, "Invalid state transition"
    ),
    ErrorCode.PAYLOAD_TOO_LARGE: ErrorDefinition(
        41300, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Payload is too large"
    ),
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: ErrorDefinition(
        41500, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Unsupported media type"
    ),
    ErrorCode.RATE_LIMITED: ErrorDefinition(
        42900, HTTPStatus.TOO_MANY_REQUESTS, "Too many requests"
    ),
    ErrorCode.INTERNAL_ERROR: ErrorDefinition(
        50000, HTTPStatus.INTERNAL_SERVER_ERROR, "Internal server error"
    ),
    ErrorCode.DATABASE_ERROR: ErrorDefinition(
        50001, HTTPStatus.INTERNAL_SERVER_ERROR, "Database operation failed"
    ),
    ErrorCode.NOT_IMPLEMENTED: ErrorDefinition(
        50100, HTTPStatus.NOT_IMPLEMENTED, "Feature is not implemented"
    ),
    ErrorCode.STORAGE_ERROR: ErrorDefinition(
        50201, HTTPStatus.BAD_GATEWAY, "Object storage operation failed"
    ),
    ErrorCode.PARSER_ERROR: ErrorDefinition(
        50202, HTTPStatus.BAD_GATEWAY, "Document parser failed"
    ),
    ErrorCode.SERVICE_UNAVAILABLE: ErrorDefinition(
        50300, HTTPStatus.SERVICE_UNAVAILABLE, "Service temporarily unavailable"
    ),
}


def get_error(error_code: ErrorCode) -> ErrorDefinition:
    return ERROR_CATALOG[error_code]
