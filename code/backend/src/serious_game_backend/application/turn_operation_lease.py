from __future__ import annotations

from dataclasses import dataclass, replace
import secrets
from typing import Callable

from serious_game_backend.application.hashing import canonical_request_hash
from serious_game_backend.application.idempotency import (
    raise_stored_operation_error,
    serialize_operation_error,
)
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    RuntimeTransactionRepository,
)
from serious_game_backend.application.stream_lifecycle import StreamCancelCallback
from serious_game_backend.domain.enums import OperationStatus, SessionStatus
from serious_game_backend.domain.errors import (
    IdempotencyKeyReusedError,
    NotFoundError,
    OperationRetryRequiredError,
    SessionBusyError,
    SessionEndedError,
    StateVersionConflictError,
)
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.operation import OperationRecord, utc_now_iso


@dataclass(frozen=True, slots=True)
class TurnLease:
    session: GameSession
    operation: OperationRecord
    expected_version: int


class TurnOperationLeaseService:
    """Atomic attempt lease shared by streamed conversation-style mutations."""

    def __init__(
        self,
        sessions: GameSessionRepository,
        operations: OperationRepository,
        transactions: RuntimeTransactionRepository,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._transactions = transactions

    @staticmethod
    def legacy_client_action_id(payload: dict) -> str:
        return "legacy-turn-" + canonical_request_hash(payload).split(":", 1)[1][:32]

    def reserve(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        state_version: int,
        request_payload: dict,
        retry: bool,
        stream_cancel_register: Callable[[StreamCancelCallback], None] | None = None,
    ) -> TurnLease | dict:
        request_hash = canonical_request_hash({
            "session_id": session_id,
            **request_payload,
        })
        existing = self._operations.get(account_id, session_id, client_action_id)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyKeyReusedError("client_action_id 已用于不同请求")
            if existing.status is OperationStatus.SUCCEEDED and existing.response is not None:
                return existing.response
            if existing.status is OperationStatus.PROCESSING:
                return {
                    "operation_id": existing.operation_id,
                    "status": OperationStatus.PROCESSING.value,
                    "poll_after_ms": 500,
                }
            if existing.status is OperationStatus.FAILED_FINAL:
                raise_stored_operation_error(existing)
            if existing.status is OperationStatus.FAILED_RETRYABLE and not retry:
                raise OperationRetryRequiredError(
                    "上次执行为可重试失败；请确认后显式设置 retry=true",
                    details={"operation_id": existing.operation_id},
                )

        session = self._sessions.get_owned(session_id, account_id)
        if session is None:
            raise NotFoundError("游戏不存在")
        if session.status is not SessionStatus.ACTIVE:
            raise SessionEndedError("当前游戏不可继续写入")
        if session.state_version != state_version:
            raise StateVersionConflictError(
                "状态版本已变化，请刷新后重试",
                details={"current_state_version": session.state_version},
            )
        if session.processing_action_id is not None:
            raise SessionBusyError("上一操作仍在处理中")

        operation_id = (
            existing.operation_id
            if existing is not None
            else f"turn_{secrets.token_hex(12)}"
        )
        lease_token = secrets.token_hex(16)
        operation = (
            OperationRecord(
                operation_id=operation_id,
                account_id=account_id,
                session_id=session_id,
                client_action_id=client_action_id,
                request_hash=request_hash,
                lease_token=lease_token,
            )
            if existing is None
            else replace(
                existing,
                status=OperationStatus.PROCESSING,
                attempt_count=existing.attempt_count + 1,
                error=None,
                response=None,
                updated_at=utc_now_iso(),
                lease_token=lease_token,
            )
        )
        session.processing_action_id = operation.reservation_id
        session.touch()
        self._transactions.reserve_operation(
            session,
            expected_version=state_version,
            operation=operation,
            create_operation=existing is None,
        )
        if stream_cancel_register is not None:
            stream_cancel_register(lambda: self.abort(
                account_id=account_id,
                session_id=session_id,
                client_action_id=client_action_id,
                reservation_id=operation.reservation_id,
            ))
        return TurnLease(session, operation, state_version)

    def assert_owner(self, lease: TurnLease) -> None:
        current = self._sessions.get_owned(
            lease.session.session_id, lease.session.account_id
        )
        if current is None or current.processing_action_id != lease.operation.reservation_id:
            raise SessionBusyError("当前回合预留已失效")
        if current.state_version != lease.expected_version:
            raise StateVersionConflictError("状态版本已变化，请刷新后重试")

    def complete(
        self,
        lease: TurnLease,
        response: dict | Callable[[GameSession], dict],
    ) -> dict:
        self.assert_owner(lease)
        session = lease.session
        session.processing_action_id = None
        session.state_version += 1
        session.touch()
        if callable(response):
            response = response(session)
        response["operation_id"] = lease.operation.operation_id
        response["status"] = OperationStatus.SUCCEEDED.value
        response["state_version"] = session.state_version
        completed = replace(
            lease.operation,
            status=OperationStatus.SUCCEEDED,
            response=response,
            updated_at=utc_now_iso(),
        )
        self._transactions.finish_operation(
            session,
            expected_version=lease.expected_version,
            operation=completed,
        )
        return response

    def fail(self, lease: TurnLease, exc: Exception) -> None:
        current = self._sessions.get_owned(
            lease.session.session_id, lease.session.account_id
        )
        if current is None or current.processing_action_id != lease.operation.reservation_id:
            return
        current.processing_action_id = None
        current.touch()
        failed = replace(
            lease.operation,
            status=(
                OperationStatus.FAILED_RETRYABLE
                if getattr(exc, "retryable", False)
                else OperationStatus.FAILED_FINAL
            ),
            error=serialize_operation_error(exc),
            updated_at=utc_now_iso(),
        )
        self._transactions.finish_operation(
            current,
            expected_version=current.state_version,
            operation=failed,
        )

    def abort(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        reservation_id: str,
    ) -> bool:
        operation = self._operations.get(account_id, session_id, client_action_id)
        if (
            operation is None
            or operation.status is not OperationStatus.PROCESSING
            or operation.reservation_id != reservation_id
        ):
            return False
        current = self._sessions.get_owned(session_id, account_id)
        if current is None or current.processing_action_id != reservation_id:
            return False
        current.processing_action_id = None
        current.touch()
        failed = replace(
            operation,
            status=OperationStatus.FAILED_RETRYABLE,
            error={
                "code": "NPC_STREAM_DISCONNECTED",
                "message": "NPC 回应流已中断，本次操作未结算",
                "details": {},
                "http_status": 409,
            },
            updated_at=utc_now_iso(),
        )
        try:
            self._transactions.finish_operation(
                current,
                expected_version=current.state_version,
                operation=failed,
            )
        except StateVersionConflictError:
            return False
        return True
