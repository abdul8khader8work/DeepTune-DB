"""Typed application errors that render the uniform error envelope."""

from typing import Any


class ApiError(Exception):
    """An expected failure that maps to the documented error body."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        suggestion: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.suggestion = suggestion
        self.headers = headers

    def to_body(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "error_code": self.error_code,
            "message": self.message,
        }
        if self.suggestion:
            detail["suggestion"] = self.suggestion
        return {"detail": detail}


def bad_request(message: str, suggestion: str | None = None) -> ApiError:
    return ApiError(400, "BAD_REQUEST", message, suggestion)


def unauthorized(message: str = "Missing or invalid bearer token.") -> ApiError:
    return ApiError(
        401,
        "UNAUTHORIZED",
        message,
        "Send Authorization: Bearer <token> minted by the API owner.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def not_found(code: str, message: str) -> ApiError:
    return ApiError(404, code, message)


def conflict(code: str, message: str, suggestion: str | None = None) -> ApiError:
    return ApiError(409, code, message, suggestion)


def unprocessable(code: str, message: str, suggestion: str | None = None) -> ApiError:
    return ApiError(422, code, message, suggestion)


def bad_gateway(message: str) -> ApiError:
    return ApiError(
        502,
        "SHADOW_DB_UNAVAILABLE",
        message,
        "Start the shadow database with `docker compose up -d shadow_db`.",
    )


def gateway_timeout(message: str) -> ApiError:
    return ApiError(
        504,
        "DB_UNREACHABLE",
        message,
        "Check host, port, firewall rules, and that PostgreSQL is running.",
    )
