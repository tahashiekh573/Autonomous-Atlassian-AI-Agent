"""Application exception hierarchy. Every error carries a stable machine-readable code."""

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class RequestValidationAppError(AppError):
    status_code = 422
    code = "validation_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"


# --- Atlassian (upstream) errors -------------------------------------------------------------


class AtlassianError(AppError):
    """An error returned by, or while talking to, an Atlassian Cloud API."""

    status_code = 502
    code = "atlassian_error"

    def __init__(
        self,
        message: str,
        *,
        service: str,
        upstream_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"service": service, "upstream_status": upstream_status, **(details or {})}
        super().__init__(message, details=merged)
        self.service = service
        self.upstream_status = upstream_status


class AtlassianAuthError(AtlassianError):
    code = "atlassian_auth_failed"


class AtlassianPermissionError(AtlassianError):
    code = "atlassian_permission_denied"


class AtlassianNotFoundError(AtlassianError):
    code = "atlassian_not_found"


class AtlassianRateLimitError(AtlassianError):
    code = "atlassian_rate_limited"


class AtlassianUnsupportedError(AtlassianError):
    code = "atlassian_unsupported_operation"


class AtlassianConnectionError(AtlassianError):
    code = "atlassian_unreachable"


class AtlassianApiError(AtlassianError):
    code = "atlassian_api_error"


class AuthorizationError(AppError):
    status_code = 403
    code = "forbidden"


class LLMError(AppError):
    """The language model failed or returned unusable output."""

    status_code = 502
    code = "llm_error"


class SpeechError(AppError):
    status_code = 502
    code = "speech_error"


# --- Operation execution errors (raised by agent handlers) ------------------------------------


class OperationError(AppError):
    status_code = 422
    code = "operation_failed"


class OperationInputError(OperationError):
    """Parameters are invalid or reference resources that do not exist."""

    code = "operation_invalid_input"


class OperationConflictError(OperationError):
    """The target resource exists and differs from what the plan expects."""

    code = "operation_conflict"


class OperationUnsupportedError(OperationError):
    """Atlassian offers no public API for this operation."""

    code = "operation_unsupported"
