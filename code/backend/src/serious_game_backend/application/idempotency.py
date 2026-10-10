from __future__ import annotations

from serious_game_backend.domain.errors import DomainError, StoredOperationError
from serious_game_backend.domain.operation import OperationRecord


def serialize_operation_error(exc: Exception) -> dict:
    if isinstance(exc, DomainError):
        return {
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
            "http_status": exc.http_status,
        }
    return {
        "code": "INTERNAL_OPERATION_FAILED",
        "message": "操作执行失败",
        "details": {},
        "http_status": 500,
    }


def raise_stored_operation_error(operation: OperationRecord) -> None:
    error = operation.error or {}
    raise StoredOperationError(
        str(error.get("message") or "操作执行失败"),
        code=str(error.get("code") or "INTERNAL_OPERATION_FAILED"),
        http_status=int(error.get("http_status") or 500),
        details=dict(error.get("details") or {}),
    )
