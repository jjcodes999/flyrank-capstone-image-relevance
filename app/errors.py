"""Domain errors. The API maps AppError subclasses to clean 4xx JSON responses."""


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class NotReady(AppError):
    status_code = 409
    code = "not_ready"


class BudgetExceeded(AppError):
    """Raised before an AI call that would exceed the configured budget. Never retried."""

    status_code = 402
    code = "budget_exceeded"


class InvalidModelOutput(Exception):
    """The model kept returning output that fails schema validation. Never stored."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"model output failed schema validation {len(errors)} time(s): {errors[-1]}")
        self.errors = errors
