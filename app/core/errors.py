"""Application errors. Every one renders as {error_code, message, recoverable}."""

from __future__ import annotations


class AppError(Exception):
    status_code = 500
    error_code = "internal_error"
    recoverable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConsentRequiredError(AppError):
    status_code = 403
    error_code = "consent_required"
    recoverable = True

    def __init__(self, purpose: str) -> None:
        super().__init__(f"consent for '{purpose}' has not been recorded; POST /consent first")
        self.purpose = purpose


class IllegalTransitionError(AppError):
    status_code = 409
    error_code = "illegal_transition"
    recoverable = True


class ServiceUnavailableError(AppError):
    status_code = 503
    error_code = "service_unavailable"
    recoverable = True
