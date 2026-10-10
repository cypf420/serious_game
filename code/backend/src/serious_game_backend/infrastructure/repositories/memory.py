from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from threading import RLock

from serious_game_backend.domain.errors import StateVersionConflictError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.operation import OperationRecord
from serious_game_backend.domain.enums import OperationStatus
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.snapshots import GameSnapshot, ManualSaveSlot
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.llm_runtime import LLMCallAudit, NPCMemory
from serious_game_backend.domain.consent import ConsentDocument, ConsentRecord
from serious_game_backend.domain.identity import Account, AuthSession
from serious_game_backend.domain.research import (
    ExperimentAssignment,
    ResearchEvent,
    ResearchSubject,
)
import secrets
from serious_game_backend.infrastructure.repositories.snapshot_codec import build_snapshot


class InMemoryGameSessionRepository:
    def __init__(self) -> None:
        self._items: dict[str, GameSession] = {}
        self._lock = RLock()

    def create(self, session: GameSession) -> None:
        with self._lock:
            if session.session_id in self._items:
                raise ValueError("duplicate session_id")
            self._items[session.session_id] = deepcopy(session)

    def get_owned(self, session_id: str, account_id: str) -> GameSession | None:
        with self._lock:
            session = self._items.get(session_id)
            if session is None or session.account_id != account_id:
                return None
            return deepcopy(session)

    def latest_active(self, account_id: str) -> GameSession | None:
        with self._lock:
            values = [
                item
                for item in self._items.values()
                if item.account_id == account_id and item.status.value == "active"
            ]
            if not values:
                return None
            return deepcopy(max(values, key=lambda item: item.updated_at))

    def list_for_account(self, account_id: str) -> tuple[GameSession, ...]:
        with self._lock:
            values = sorted(
                (item for item in self._items.values() if item.account_id == account_id),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            return tuple(deepcopy(item) for item in values)

    def save(self, session: GameSession, *, expected_version: int) -> None:
        with self._lock:
            current = self._items.get(session.session_id)
            if current is None or current.account_id != session.account_id:
                raise StateVersionConflictError("游戏不存在或所有权已变化")
            if current.state_version != expected_version:
                raise StateVersionConflictError(
                    "状态版本冲突",
                    details={"current_state_version": current.state_version},
                )
            if (
                session.processing_action_id is not None
                and current.processing_action_id is not None
                and current.processing_action_id != session.processing_action_id
            ):
                raise StateVersionConflictError("当前游戏已被另一操作占用")
            self._items[session.session_id] = deepcopy(session)


class InMemoryOperationRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], OperationRecord] = {}
        self._lock = RLock()

    def get(
        self,
        account_id: str,
        session_id: str,
        client_action_id: str,
    ) -> OperationRecord | None:
        with self._lock:
            value = self._items.get((account_id, session_id, client_action_id))
            return deepcopy(value) if value is not None else None

    def create(self, operation: OperationRecord) -> None:
        if operation.session_id is None:
            raise ValueError("game operation requires session_id")
        key = (operation.account_id, operation.session_id, operation.client_action_id)
        with self._lock:
            if key in self._items:
                raise ValueError("duplicate idempotency key")
            self._items[key] = deepcopy(operation)

    def save(self, operation: OperationRecord) -> None:
        if operation.session_id is None:
            raise ValueError("game operation requires session_id")
        key = (operation.account_id, operation.session_id, operation.client_action_id)
        with self._lock:
            if key not in self._items:
                raise ValueError("operation does not exist")
            self._items[key] = deepcopy(operation)


class InMemorySessionRequestRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], OperationRecord] = {}
        self._lock = RLock()

    def get(self, account_id: str, client_request_id: str) -> OperationRecord | None:
        with self._lock:
            value = self._items.get((account_id, client_request_id))
            return deepcopy(value) if value is not None else None

    def create(self, request: OperationRecord) -> None:
        key = (request.account_id, request.client_action_id)
        with self._lock:
            if key in self._items:
                raise ValueError("duplicate idempotency key")
            self._items[key] = deepcopy(request)

    def save(self, request: OperationRecord) -> None:
        key = (request.account_id, request.client_action_id)
        with self._lock:
            if key not in self._items:
                raise ValueError("session request does not exist")
            self._items[key] = deepcopy(request)


class InMemorySnapshotRepository:
    def __init__(
        self,
        sessions: InMemoryGameSessionRepository,
        operations: InMemoryOperationRepository,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._snapshots: dict[str, GameSnapshot] = {}
        self._slots: dict[tuple[str, str, int], ManualSaveSlot] = {}
        self._lock = RLock()

    def commit_session_snapshot(
        self,
        session: GameSession,
        *,
        expected_version: int,
        snapshot_type: str,
        reason: str,
    ) -> GameSnapshot:
        # A shared critical section is the in-memory transaction boundary.
        with self._sessions._lock, self._lock:
            current = self._sessions._items.get(session.session_id)
            if (
                current is None
                or current.account_id != session.account_id
                or current.state_version != expected_version
            ):
                raise StateVersionConflictError("状态版本冲突")
            parents = [
                item for item in self._snapshots.values()
                if item.session_id == session.session_id
                and item.account_id == session.account_id
                and item.timeline_id == session.timeline_id
            ]
            parent_id = (
                max(parents, key=lambda item: item.state_version).snapshot_id
                if parents else None
            )
            snapshot = build_snapshot(
                session,
                snapshot_type=snapshot_type,
                reason=reason,
                parent_snapshot_id=parent_id,
            )
            if any(
                item.session_id == snapshot.session_id
                and item.timeline_id == snapshot.timeline_id
                and item.state_version == snapshot.state_version
                for item in self._snapshots.values()
            ):
                raise ValueError("duplicate snapshot version")
            # Validate/insert the snapshot before publishing the session copy.
            self._insert_snapshot(snapshot)
            self._sessions._items[session.session_id] = deepcopy(session)
            return deepcopy(snapshot)

    def _insert_snapshot(self, snapshot: GameSnapshot) -> None:
        self._snapshots[snapshot.snapshot_id] = deepcopy(snapshot)

    def append(
        self,
        session: GameSession,
        *,
        snapshot_type: str,
        reason: str,
        parent_snapshot_id: str | None = None,
    ) -> GameSnapshot:
        snapshot = build_snapshot(
            session,
            snapshot_type=snapshot_type,
            reason=reason,
            parent_snapshot_id=parent_snapshot_id,
        )
        with self._lock:
            if any(
                item.session_id == snapshot.session_id
                and item.timeline_id == snapshot.timeline_id
                and item.state_version == snapshot.state_version
                for item in self._snapshots.values()
            ):
                raise ValueError("duplicate snapshot version")
            self._snapshots[snapshot.snapshot_id] = deepcopy(snapshot)
        return snapshot

    def latest_for_timeline(self, session: GameSession) -> GameSnapshot | None:
        with self._lock:
            values = [
                item
                for item in self._snapshots.values()
                if item.account_id == session.account_id
                and item.session_id == session.session_id
                and item.timeline_id == session.timeline_id
            ]
            return deepcopy(max(values, key=lambda item: item.state_version)) if values else None

    def get_owned(
        self, account_id: str, session_id: str, snapshot_id: str
    ) -> GameSnapshot | None:
        with self._lock:
            value = self._snapshots.get(snapshot_id)
            if (
                value is None
                or value.account_id != account_id
                or value.session_id != session_id
            ):
                return None
            return deepcopy(value)

    def current_for_session(self, session: GameSession) -> GameSnapshot | None:
        with self._lock:
            for value in self._snapshots.values():
                if (
                    value.account_id == session.account_id
                    and value.session_id == session.session_id
                    and value.timeline_id == session.timeline_id
                    and value.state_version == session.state_version
                ):
                    return deepcopy(value)
        return None

    def list_manual_slots(
        self, account_id: str, session_id: str
    ) -> tuple[tuple[ManualSaveSlot, GameSnapshot], ...]:
        with self._lock:
            values = [
                (slot, self._snapshots[slot.snapshot_id])
                for slot in self._slots.values()
                if slot.account_id == account_id and slot.session_id == session_id
            ]
            return tuple(
                (deepcopy(slot), deepcopy(snapshot))
                for slot, snapshot in sorted(values, key=lambda item: item[0].slot_number)
            )

    def list_history(
        self, account_id: str, session_id: str, *, limit: int = 20
    ) -> tuple[GameSnapshot, ...]:
        with self._lock:
            values = [
                item
                for item in self._snapshots.values()
                if item.account_id == account_id and item.session_id == session_id
            ]
            values.sort(key=lambda item: (item.created_at, item.state_version), reverse=True)
            return tuple(deepcopy(values[:limit]))

    def create_manual_save(
        self,
        session: GameSession,
        *,
        snapshot: GameSnapshot,
        slot_number: int,
        display_name: str,
        overwrite: bool,
        operation: OperationRecord,
    ) -> tuple[ManualSaveSlot, GameSnapshot]:
        key = (session.account_id, session.session_id, slot_number)
        operation_key = (
            operation.account_id,
            operation.session_id,
            operation.client_action_id,
        )
        with self._sessions._lock, self._operations._lock, self._lock:
            current = self._sessions._items.get(session.session_id)
            if (
                current is None
                or current.account_id != session.account_id
                or current.state_version != session.state_version
                or current.processing_action_id is not None
            ):
                raise StateVersionConflictError("状态版本已变化或游戏正在处理操作")
            if key in self._slots and not overwrite:
                raise ActionUnavailableError("手动存档槽位已存在，覆盖前必须确认")
            if snapshot.snapshot_id in self._snapshots:
                raise ValueError("duplicate snapshot_id")
            if operation_key in self._operations._items:
                raise ValueError("duplicate idempotency key")
            slot = ManualSaveSlot(
                account_id=session.account_id,
                session_id=session.session_id,
                slot_number=slot_number,
                snapshot_id=snapshot.snapshot_id,
                display_name=display_name,
                updated_at=operation.updated_at,
            )
            self._snapshots[snapshot.snapshot_id] = deepcopy(snapshot)
            self._operations._items[operation_key] = deepcopy(operation)
            self._slots[key] = slot
            return deepcopy(slot), deepcopy(snapshot)

    def commit_load(
        self,
        current: GameSession,
        restored: GameSession,
        *,
        expected_version: int,
        source_snapshot: GameSnapshot,
        result_snapshot: GameSnapshot,
        operation: OperationRecord,
    ) -> None:
        with self._lock:
            self._sessions.save(restored, expected_version=expected_version)
            self._operations.create(operation)
            self._snapshots[result_snapshot.snapshot_id] = deepcopy(result_snapshot)


class InMemoryRuntimeTransactionRepository:
    """内存测试适配器；生产级原子性由持久化适配器保证。"""

    def __init__(
        self,
        sessions: InMemoryGameSessionRepository,
        operations: InMemoryOperationRepository,
        requests: InMemorySessionRequestRepository,
        research_events: InMemoryResearchEventRepository | None = None,
        snapshots: InMemorySnapshotRepository | None = None,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._requests = requests
        self._research_events = research_events
        self._snapshots = snapshots
        self._lock = RLock()

    def recover_stale_operations(self, stale_before: str) -> int:
        recovered = 0
        with self._lock:
            for operation in tuple(self._operations._items.values()):
                if (
                    operation.status is not OperationStatus.PROCESSING
                    or operation.updated_at > stale_before
                    or operation.session_id is None
                ):
                    continue
                session = self._sessions.get_owned(
                    operation.session_id, operation.account_id
                )
                if (
                    session is None
                    or session.processing_action_id != operation.reservation_id
                ):
                    continue
                session.processing_action_id = None
                session.touch()
                failed = replace(
                    operation,
                    status=OperationStatus.FAILED_RETRYABLE,
                    error={
                        "code": "OPERATION_LEASE_EXPIRED",
                        "message": "操作进程中断，已释放占用；请显式重试",
                        "details": {},
                        "http_status": 409,
                    },
                    updated_at=session.updated_at,
                )
                self._sessions.save(session, expected_version=session.state_version)
                self._operations.save(failed)
                recovered += 1
        return recovered

    def reserve_operation(
        self,
        session: GameSession,
        *,
        expected_version: int,
        operation: OperationRecord,
        create_operation: bool,
    ) -> None:
        with self._lock:
            reserved = self._sessions.get_owned(session.session_id, session.account_id)
            if (
                reserved is None
                or reserved.state_version != expected_version
                or reserved.processing_action_id is not None
            ):
                raise StateVersionConflictError(
                    "状态版本冲突或已有操作占用当前游戏"
                )
            self._sessions.save(session, expected_version=expected_version)
            if create_operation:
                self._operations.create(operation)
            else:
                self._operations.save(operation)

    def finish_operation(
        self,
        session: GameSession,
        *,
        expected_version: int,
        operation: OperationRecord,
        research_event: ResearchEvent | None = None,
    ) -> None:
        with self._lock:
            reserved = self._sessions.get_owned(
                session.session_id, session.account_id
            )
            if (
                reserved is None
                or reserved.state_version != expected_version
                or reserved.processing_action_id != operation.reservation_id
            ):
                raise StateVersionConflictError(
                    "动作预留已失效或状态版本冲突"
                )
            self._sessions.save(session, expected_version=expected_version)
            self._operations.save(operation)
            if (
                self._snapshots is not None
                and operation.status is OperationStatus.SUCCEEDED
                and session.state_version > expected_version
            ):
                parent = self._snapshots.latest_for_timeline(session)
                self._snapshots.append(
                    session,
                    snapshot_type="auto",
                    reason="operation_committed",
                    parent_snapshot_id=(
                        parent.snapshot_id if parent is not None else None
                    ),
                )
            if research_event is not None and self._research_events is not None:
                self._research_events.append(research_event)

    def complete_session_request(
        self,
        session: GameSession,
        request: OperationRecord,
    ) -> None:
        with self._lock:
            self._sessions.create(session)
            self._requests.save(request)
            if self._snapshots is not None:
                self._snapshots.append(
                    session,
                    snapshot_type="checkpoint",
                    reason="session_started",
                )

class InMemoryScriptPackageRepository:
    def __init__(self, packages: list[ScriptPackage]) -> None:
        self._items = {item.package_id: item for item in packages}

    def get(self, package_id: str) -> ScriptPackage | None:
        return self._items.get(package_id)


class InMemoryLLMCallAuditRepository:
    def __init__(self) -> None:
        self._items: list[LLMCallAudit] = []
        self._lock = RLock()

    def save(self, audit: LLMCallAudit) -> None:
        with self._lock:
            self._items.append(deepcopy(audit))

    def successful_for_operation(
        self, *, account_id: str, session_id: str, operation_id: str,
        request_hash: str, config_version: str, endpoint_host: str,
    ) -> LLMCallAudit | None:
        with self._lock:
            matches = [
                item for item in self._items
                if item.operation_id == operation_id
                and item.request_hash == request_hash
                and item.account_id == account_id
                and item.session_id == session_id
                and item.config_version == config_version
                and item.endpoint_host == endpoint_host
                and item.status == "succeeded"
            ]
            return deepcopy(matches[-1]) if matches else None

    def list_for_session(self, session_id: str) -> tuple[LLMCallAudit, ...]:
        with self._lock:
            return tuple(deepcopy(
                [item for item in self._items if item.session_id == session_id]
            ))

    def list_for_owned_session(
        self, account_id: str, session_id: str, *, after: str, limit: int
    ) -> tuple[LLMCallAudit, ...]:
        with self._lock:
            ordered = sorted(
                (
                    item for item in self._items
                    if item.account_id == account_id and item.session_id == session_id
                ),
                key=lambda item: (item.created_at, item.audit_id),
            )
            if after:
                ordered = [
                    item for item in ordered
                    if f"{item.created_at}|{item.audit_id}" > after
                ]
            return tuple(deepcopy(ordered[:limit]))


class InMemoryNPCMemoryRepository:
    def __init__(self) -> None:
        self._items: dict[str, NPCMemory] = {}
        self._lock = RLock()

    def save(self, memory: NPCMemory) -> None:
        with self._lock:
            self._items[memory.memory_id] = deepcopy(memory)

    def active_for_npc(
        self, session_id: str, npc_id: str, story_day: int
    ) -> tuple[NPCMemory, ...]:
        with self._lock:
            values = [
                item for item in self._items.values()
                if item.session_id == session_id
                and item.npc_id == npc_id
                and item.is_active(story_day)
            ]
            return tuple(deepcopy(sorted(values, key=lambda item: item.created_at)))

    def invalidate(self, memory_ids: tuple[str, ...], invalidated_at: str) -> None:
        with self._lock:
            for memory_id in memory_ids:
                current = self._items.get(memory_id)
                if current is not None:
                    from dataclasses import replace
                    self._items[memory_id] = replace(
                        current, invalidated_at=invalidated_at
                    )


class InMemoryAccountRepository:
    def __init__(self) -> None:
        self._items: dict[str, Account] = {}
        self._usernames: dict[str, str] = {}
        self._lock = RLock()

    def create(self, account: Account) -> None:
        with self._lock:
            if account.account_id in self._items or account.username in self._usernames:
                raise ValueError("duplicate account")
            self._items[account.account_id] = deepcopy(account)
            self._usernames[account.username] = account.account_id

    def get_by_id(self, account_id: str) -> Account | None:
        with self._lock:
            value = self._items.get(account_id)
            return deepcopy(value) if value else None

    def get_by_username(self, username: str) -> Account | None:
        with self._lock:
            account_id = self._usernames.get(username)
            value = self._items.get(account_id) if account_id else None
            return deepcopy(value) if value else None


class InMemoryAuthSessionRepository:
    def __init__(self) -> None:
        self._items: dict[str, AuthSession] = {}
        self._lock = RLock()

    def create(self, session: AuthSession) -> None:
        with self._lock:
            if session.token_hash in self._items:
                raise ValueError("duplicate auth session")
            self._items[session.token_hash] = deepcopy(session)

    def get(self, token_hash: str) -> AuthSession | None:
        with self._lock:
            value = self._items.get(token_hash)
            return deepcopy(value) if value else None

    def save(self, session: AuthSession) -> None:
        with self._lock:
            if session.token_hash not in self._items:
                raise ValueError("auth session does not exist")
            self._items[session.token_hash] = deepcopy(session)


class InMemoryConsentRepository:
    def __init__(self) -> None:
        self._documents: dict[str, ConsentDocument] = {}
        self._records: dict[str, ConsentRecord] = {}
        self._lock = RLock()

    def publish_document(self, document: ConsentDocument) -> None:
        with self._lock:
            current = self._documents.get(document.consent_version)
            if current is not None and current.document_hash != document.document_hash:
                raise ValueError("consent version is immutable")
            self._documents[document.consent_version] = deepcopy(document)

    def get_document(self, consent_version: str) -> ConsentDocument | None:
        with self._lock:
            value = self._documents.get(consent_version)
            return deepcopy(value) if value else None

    def create_record(self, record: ConsentRecord) -> None:
        with self._lock:
            if record.consent_record_id in self._records:
                raise ValueError("duplicate consent record")
            self._records[record.consent_record_id] = deepcopy(record)

    def get_record(self, consent_record_id: str) -> ConsentRecord | None:
        with self._lock:
            value = self._records.get(consent_record_id)
            return deepcopy(value) if value else None

    def latest_for_account(self, account_id: str) -> ConsentRecord | None:
        with self._lock:
            values = [item for item in self._records.values() if item.account_id == account_id]
            return deepcopy(max(values, key=lambda item: item.signed_at)) if values else None

    def save_record(self, record: ConsentRecord) -> None:
        with self._lock:
            current = self._records.get(record.consent_record_id)
            if current is None:
                raise ValueError("consent record does not exist")
            if (
                current.account_id != record.account_id
                or current.consent_version != record.consent_version
                or current.document_hash != record.document_hash
                or current.scopes != record.scopes
                or current.signed_at != record.signed_at
            ):
                raise ValueError("signed consent fields are immutable")
            self._records[record.consent_record_id] = deepcopy(record)


class InMemoryResearchIdentityRepository:
    def __init__(self) -> None:
        self._items: dict[str, ResearchSubject] = {}
        self._lock = RLock()

    def get_or_create(self, account_id: str) -> ResearchSubject:
        with self._lock:
            current = self._items.get(account_id)
            if current is None:
                current = ResearchSubject(
                    research_subject_id=f"rs_{secrets.token_hex(16)}",
                    account_id=account_id,
                )
                self._items[account_id] = current
            return deepcopy(current)

    def get_for_account(self, account_id: str) -> ResearchSubject | None:
        with self._lock:
            value = self._items.get(account_id)
            return deepcopy(value) if value else None


class InMemoryExperimentAssignmentRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], ExperimentAssignment] = {}
        self._lock = RLock()

    def create(self, assignment: ExperimentAssignment) -> None:
        key = (assignment.research_subject_id, assignment.experiment_id)
        with self._lock:
            if key in self._items:
                raise ValueError("experiment assignment is immutable")
            self._items[key] = deepcopy(assignment)

    def get_for_subject(
        self, research_subject_id: str, experiment_id: str
    ) -> ExperimentAssignment | None:
        with self._lock:
            value = self._items.get((research_subject_id, experiment_id))
            return deepcopy(value) if value else None


class InMemoryResearchEventRepository:
    def __init__(self) -> None:
        self._items: list[ResearchEvent] = []
        self._lock = RLock()

    def append(self, event: ResearchEvent) -> None:
        with self._lock:
            if any(item.research_event_id == event.research_event_id for item in self._items):
                raise ValueError("duplicate research event")
            self._items.append(deepcopy(event))

    def list_for_subject(self, research_subject_id: str) -> tuple[ResearchEvent, ...]:
        with self._lock:
            return tuple(deepcopy([
                item for item in self._items
                if item.research_subject_id == research_subject_id
            ]))
