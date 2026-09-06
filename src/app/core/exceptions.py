from app.core.error_codes import ErrorCode, get_error


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        definition = get_error(code)
        self.code = code
        self.error_code = definition.error_code
        self.http_status = definition.http_status
        self.message = message or definition.message
        super().__init__(self.message)
