"""Safe, stable errors shared by every adapter."""

from __future__ import annotations


class MinervaError(Exception):
    """An expected failure safe to present without reflecting private input."""

    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.http_status = http_status


class NotFoundError(MinervaError):
    def __init__(self, code: str, message: str = "The requested resource was not found.") -> None:
        super().__init__(code, message, http_status=404)


class ConflictError(MinervaError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=409)


class IntegrityError(MinervaError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=422)


class SecurityBoundaryError(MinervaError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, http_status=403)
