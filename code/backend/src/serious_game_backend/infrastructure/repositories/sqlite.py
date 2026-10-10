from __future__ import annotations

import json
from dataclasses import asdict, replace
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from serious_game_backend.domain.errors import StateVersionConflictError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.operation import OperationRecord
from serious_game_backend.domain.enums import OperationStatus
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.snapshots import GameSnapshot, ManualSaveSlot
from serious_game_backend.domain.llm_runtime import LLMCallAudit, NPCMemory
from serious_game_backend.domain.consent import ConsentDocument, ConsentRecord
from serious_game_backend.domain.identity import Account, AuthSession
from serious_game_backend.domain.research import (
    ExperimentAssignment,
    ResearchEvent,
    ResearchSubject,
)
from serious_game_backend.infrastructure.repositories.codec import (
    decode_operation,
    decode_session,
    dumps,
    encode_operation,
    encode_session,
)
from serious_game_backend.infrastructure.migrations import SqliteMigrationRunner
from serious_game_backend.infrastructure.repositories.snapshot_codec import build_snapshot


BACKEND_ROOT = Path(__file__).resolve().parents[4]


class SqliteRuntimeStore:
    """开发与测试用持久化运行库；每个方法都是独立短事务。"""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute("pragma busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        SqliteMigrationRunner(
            self.path, BACKEND_ROOT / "migrations" / "sqlite"
        ).migrate()
        self._backfill_current_snapshots()

    def _backfill_current_snapshots(self) -> None:
        with self.connect() as connection:
            rows = connection.execute(
                """
                select s.payload_json
                from runtime_game_sessions s
                where not exists (
                  select 1 from runtime_game_snapshots p
                  where p.session_id = s.session_id
                )
                """
            ).fetchall()
            for row in rows:
                session = decode_session(json.loads(row["payload_json"]))
                _insert_snapshot(
                    connection,
                    build_snapshot(
                        session,
                        snapshot_type="checkpoint",
                        reason="migration_backfill",
                    ),
                )


def _snapshot_from_row(row: sqlite3.Row) -> GameSnapshot:
    return GameSnapshot(
        snapshot_id=str(row["snapshot_id"]),
        session_id=str(row["session_id"]),
        account_id=str(row["account_id"]),
        timeline_id=str(row["timeline_id"]),
        snapshot_type=str(row["snapshot_type"]),
        reason=str(row["reason"]),
        story_day=int(row["story_day"]),
        state_version=int(row["state_version"]),
        package_id=str(row["package_id"]),
        package_version=str(row["package_version"]),
        package_content_hash=str(row["package_content_hash"]),
        snapshot_hash=str(row["snapshot_hash"]),
        parent_snapshot_id=row["parent_snapshot_id"],
        created_at=str(row["created_at"]),
        session_payload=json.loads(row["payload_json"]),
    )


def _insert_snapshot(
    connection: sqlite3.Connection, snapshot: GameSnapshot
) -> None:
    connection.execute(
        """
        insert into runtime_game_snapshots(
          snapshot_id, session_id, account_id, timeline_id, snapshot_type,
          reason, story_day, state_version, package_id, package_version,
          package_content_hash, snapshot_hash, parent_snapshot_id,
          created_at, payload_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot.snapshot_id,
            snapshot.session_id,
            snapshot.account_id,
            snapshot.timeline_id,
            snapshot.snapshot_type,
            snapshot.reason,
            snapshot.story_day,
            snapshot.state_version,
            snapshot.package_id,
            snapshot.package_version,
            snapshot.package_content_hash,
            snapshot.snapshot_hash,
            snapshot.parent_snapshot_id,
            snapshot.created_at,
            dumps(snapshot.session_payload),
        ),
    )


class SqliteSnapshotRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def commit_session_snapshot(
        self,
        session: GameSession,
        *,
        expected_version: int,
        snapshot_type: str,
        reason: str,
    ) -> GameSnapshot:
        with self._store.connect() as connection:
            parent = connection.execute(
                """
                select snapshot_id from runtime_game_snapshots
                where session_id = ? and account_id = ? and timeline_id = ?
                order by state_version desc limit 1
                """,
                (session.session_id, session.account_id, session.timeline_id),
            ).fetchone()
            snapshot = build_snapshot(
                session,
                snapshot_type=snapshot_type,
                reason=reason,
                parent_snapshot_id=(str(parent["snapshot_id"]) if parent else None),
            )
            cursor = connection.execute(
                """
                update runtime_game_sessions
                set status = ?, state_version = ?, processing_action_id = ?,
                    updated_at = ?, payload_json = ?
                where session_id = ? and account_id = ? and state_version = ?
                """,
                (
                    session.status.value, session.state_version,
                    session.processing_action_id, session.updated_at,
                    dumps(encode_session(session)), session.session_id,
                    session.account_id, expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StateVersionConflictError("状态版本冲突")
            _insert_snapshot(connection, snapshot)
        return snapshot

    def get_owned(
        self, account_id: str, session_id: str, snapshot_id: str
    ) -> GameSnapshot | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select * from runtime_game_snapshots
                where account_id = ? and session_id = ? and snapshot_id = ?
                """,
                (account_id, session_id, snapshot_id),
            ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def current_for_session(self, session: GameSession) -> GameSnapshot | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select * from runtime_game_snapshots
                where account_id = ? and session_id = ? and timeline_id = ?
                  and state_version = ?
                """,
                (
                    session.account_id,
                    session.session_id,
                    session.timeline_id,
                    session.state_version,
                ),
            ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def list_manual_slots(
        self, account_id: str, session_id: str
    ) -> tuple[tuple[ManualSaveSlot, GameSnapshot], ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select s.account_id as slot_account_id,
                       s.session_id as slot_session_id,
                       s.slot_number, s.snapshot_id as slot_snapshot_id,
                       s.display_name, s.updated_at as slot_updated_at,
                       p.*
                from runtime_manual_save_slots s
                join runtime_game_snapshots p on p.snapshot_id = s.snapshot_id
                where s.account_id = ? and s.session_id = ?
                order by s.slot_number
                """,
                (account_id, session_id),
            ).fetchall()
        return tuple(
            (
                ManualSaveSlot(
                    account_id=str(row["slot_account_id"]),
                    session_id=str(row["slot_session_id"]),
                    slot_number=int(row["slot_number"]),
                    snapshot_id=str(row["slot_snapshot_id"]),
                    display_name=str(row["display_name"]),
                    updated_at=str(row["slot_updated_at"]),
                ),
                _snapshot_from_row(row),
            )
            for row in rows
        )

    def list_history(
        self, account_id: str, session_id: str, *, limit: int = 20
    ) -> tuple[GameSnapshot, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select * from runtime_game_snapshots
                where account_id = ? and session_id = ?
                order by created_at desc, state_version desc limit ?
                """,
                (account_id, session_id, limit),
            ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

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
        with self._store.connect() as connection:
            state_row = connection.execute(
                """
                select state_version, processing_action_id
                from runtime_game_sessions
                where account_id = ? and session_id = ?
                """,
                (session.account_id, session.session_id),
            ).fetchone()
            if (
                state_row is None
                or int(state_row["state_version"]) != session.state_version
                or state_row["processing_action_id"] is not None
            ):
                raise StateVersionConflictError("状态版本已变化或游戏正在处理操作")
            snapshot_row = connection.execute(
                """
                select * from runtime_game_snapshots
                where account_id = ? and session_id = ? and timeline_id = ?
                  and state_version = ?
                """,
                (
                    session.account_id,
                    session.session_id,
                    session.timeline_id,
                    session.state_version,
                ),
            ).fetchone()
            if snapshot_row is None:
                raise StateVersionConflictError("当前稳定状态缺少历史快照")
            existing = connection.execute(
                """
                select snapshot_id from runtime_manual_save_slots
                where account_id = ? and session_id = ? and slot_number = ?
                """,
                (session.account_id, session.session_id, slot_number),
            ).fetchone()
            if existing is not None and not overwrite:
                raise ActionUnavailableError("手动存档槽位已存在，覆盖前必须确认")
            automatic = _snapshot_from_row(snapshot_row)
            if snapshot.parent_snapshot_id != automatic.snapshot_id:
                raise StateVersionConflictError("自动快照已变化，请刷新后重试")
            _insert_snapshot(connection, snapshot)
            if existing is None:
                connection.execute(
                    """
                    insert into runtime_manual_save_slots(
                      account_id, session_id, slot_number, snapshot_id,
                      display_name, updated_at
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.account_id,
                        session.session_id,
                        slot_number,
                        snapshot.snapshot_id,
                        display_name,
                        operation.updated_at,
                    ),
                )
            else:
                connection.execute(
                    """
                    update runtime_manual_save_slots
                    set snapshot_id = ?, display_name = ?, updated_at = ?
                    where account_id = ? and session_id = ? and slot_number = ?
                    """,
                    (
                        snapshot.snapshot_id,
                        display_name,
                        operation.updated_at,
                        session.account_id,
                        session.session_id,
                        slot_number,
                    ),
                )
            connection.execute(
                """
                insert into runtime_operations(
                  operation_id, account_id, session_id, client_action_id,
                  status, payload_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.operation_id,
                    operation.account_id,
                    operation.session_id,
                    operation.client_action_id,
                    operation.status.value,
                    dumps(encode_operation(operation)),
                ),
            )
        slot = ManualSaveSlot(
            account_id=session.account_id,
            session_id=session.session_id,
            slot_number=slot_number,
            snapshot_id=snapshot.snapshot_id,
            display_name=display_name,
            updated_at=operation.updated_at,
        )
        return slot, snapshot

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
        with self._store.connect() as connection:
            cursor = connection.execute(
                """
                update runtime_game_sessions
                set status = ?, state_version = ?, processing_action_id = null,
                    updated_at = ?, payload_json = ?
                where session_id = ? and account_id = ? and state_version = ?
                  and processing_action_id is null
                """,
                (
                    restored.status.value,
                    restored.state_version,
                    restored.updated_at,
                    dumps(encode_session(restored)),
                    current.session_id,
                    current.account_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StateVersionConflictError("加载存档时状态版本已变化")
            _insert_snapshot(connection, result_snapshot)
            connection.execute(
                """
                insert into runtime_operations(
                  operation_id, account_id, session_id, client_action_id,
                  status, payload_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.operation_id,
                    operation.account_id,
                    operation.session_id,
                    operation.client_action_id,
                    operation.status.value,
                    dumps(encode_operation(operation)),
                ),
            )


class SqliteLLMCallAuditRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def save(self, audit: LLMCallAudit) -> None:
        with self._store.connect() as connection:
            connection.execute(
                """
                insert into runtime_llm_call_audits(
                  audit_id, session_id, operation_id, request_hash, status, payload_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.audit_id, audit.session_id, audit.operation_id,
                    audit.request_hash, audit.status,
                    dumps(asdict(audit)),
                ),
            )

    def successful_for_operation(
        self, *, account_id: str, session_id: str, operation_id: str,
        request_hash: str, config_version: str, endpoint_host: str,
    ) -> LLMCallAudit | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_llm_call_audits
                where operation_id = ? and request_hash = ? and status = 'succeeded'
                  and session_id = ?
                  and json_extract(payload_json, '$.account_id') = ?
                  and json_extract(payload_json, '$.config_version') = ?
                  and json_extract(payload_json, '$.endpoint_host') = ?
                order by rowid desc limit 1
                """,
                (
                    operation_id, request_hash, session_id, account_id,
                    config_version, endpoint_host,
                ),
            ).fetchone()
        return LLMCallAudit(**json.loads(row["payload_json"])) if row else None

    def list_for_session(self, session_id: str) -> tuple[LLMCallAudit, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_llm_call_audits
                where session_id = ? order by rowid
                """,
                (session_id,),
            ).fetchall()
        return tuple(LLMCallAudit(**json.loads(row["payload_json"])) for row in rows)

    def list_for_owned_session(
        self, account_id: str, session_id: str, *, after: str, limit: int
    ) -> tuple[LLMCallAudit, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_llm_call_audits
                where session_id = ?
                  and json_extract(payload_json, '$.account_id') = ?
                  and (json_extract(payload_json, '$.created_at') || '|' || audit_id) > ?
                order by json_extract(payload_json, '$.created_at'), audit_id
                limit ?
                """,
                (session_id, account_id, after, limit),
            ).fetchall()
        return tuple(LLMCallAudit(**json.loads(row["payload_json"])) for row in rows)


class SqliteNPCMemoryRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def save(self, memory: NPCMemory) -> None:
        with self._store.connect() as connection:
            connection.execute(
                """
                insert into runtime_npc_memories(
                  memory_id, session_id, npc_id, valid_from_day,
                  expires_after_day, invalidated_at, created_at, payload_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.memory_id, memory.session_id, memory.npc_id,
                    memory.valid_from_day, memory.expires_after_day,
                    memory.invalidated_at, memory.created_at,
                    dumps(asdict(memory)),
                ),
            )

    def active_for_npc(
        self, session_id: str, npc_id: str, story_day: int
    ) -> tuple[NPCMemory, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_npc_memories
                where session_id = ? and npc_id = ? and invalidated_at is null
                  and valid_from_day <= ?
                  and (expires_after_day is null or expires_after_day >= ?)
                order by created_at
                """,
                (session_id, npc_id, story_day, story_day),
            ).fetchall()
        values = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["keywords"] = tuple(payload.get("keywords", ()))
            values.append(NPCMemory(**payload))
        return tuple(values)

    def invalidate(self, memory_ids: tuple[str, ...], invalidated_at: str) -> None:
        if not memory_ids:
            return
        placeholders = ",".join("?" for _ in memory_ids)
        with self._store.connect() as connection:
            rows = connection.execute(
                f"select memory_id, payload_json from runtime_npc_memories where memory_id in ({placeholders})",
                memory_ids,
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                payload["invalidated_at"] = invalidated_at
                connection.execute(
                    "update runtime_npc_memories set invalidated_at = ?, payload_json = ? where memory_id = ?",
                    (invalidated_at, dumps(payload), row["memory_id"]),
                )


class SqliteGameSessionRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def create(self, session: GameSession) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_game_sessions(
                      session_id, account_id, status, state_version,
                      processing_action_id, updated_at, payload_json
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.account_id,
                        session.status.value,
                        session.state_version,
                        session.processing_action_id,
                        session.updated_at,
                        dumps(encode_session(session)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate session_id") from exc

    def get_owned(self, session_id: str, account_id: str) -> GameSession | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_game_sessions
                where session_id = ? and account_id = ?
                """,
                (session_id, account_id),
            ).fetchone()
        return decode_session(json.loads(row["payload_json"])) if row else None

    def latest_active(self, account_id: str) -> GameSession | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_game_sessions
                where account_id = ? and status = 'active'
                order by updated_at desc limit 1
                """,
                (account_id,),
            ).fetchone()
        return decode_session(json.loads(row["payload_json"])) if row else None

    def list_for_account(self, account_id: str) -> tuple[GameSession, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_game_sessions
                where account_id = ? order by updated_at desc
                """,
                (account_id,),
            ).fetchall()
        return tuple(decode_session(json.loads(row["payload_json"])) for row in rows)

    def save(self, session: GameSession, *, expected_version: int) -> None:
        reservation_guard = ""
        parameters: list[object] = [
            session.status.value,
            session.state_version,
            session.processing_action_id,
            session.updated_at,
            dumps(encode_session(session)),
            session.session_id,
            session.account_id,
            expected_version,
        ]
        if session.processing_action_id is not None:
            reservation_guard = " and processing_action_id is null"
        with self._store.connect() as connection:
            cursor = connection.execute(
                f"""
                update runtime_game_sessions
                set status = ?, state_version = ?, processing_action_id = ?,
                    updated_at = ?, payload_json = ?
                where session_id = ? and account_id = ? and state_version = ?
                {reservation_guard}
                """,
                parameters,
            )
            if cursor.rowcount != 1:
                raise StateVersionConflictError(
                    "状态版本冲突或已有操作占用当前游戏"
                )


class SqliteOperationRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def get(
        self,
        account_id: str,
        session_id: str,
        client_action_id: str,
    ) -> OperationRecord | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_operations
                where account_id = ? and session_id = ? and client_action_id = ?
                """,
                (account_id, session_id, client_action_id),
            ).fetchone()
        return decode_operation(json.loads(row["payload_json"])) if row else None

    def create(self, operation: OperationRecord) -> None:
        if operation.session_id is None:
            raise ValueError("game operation requires session_id")
        try:
            with self._store.connect() as connection:
                connection.execute(
                """
                insert into runtime_operations(
                  operation_id, account_id, session_id, client_action_id,
                  status, payload_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation.operation_id,
                    operation.account_id,
                    operation.session_id,
                    operation.client_action_id,
                    operation.status.value,
                    dumps(encode_operation(operation)),
                ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate idempotency key") from exc

    def save(self, operation: OperationRecord) -> None:
        with self._store.connect() as connection:
            cursor = connection.execute(
                """
                update runtime_operations set status = ?, payload_json = ?
                where operation_id = ?
                """,
                (
                    operation.status.value,
                    dumps(encode_operation(operation)),
                    operation.operation_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("operation does not exist")


class SqliteSessionRequestRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def get(
        self, account_id: str, client_request_id: str
    ) -> OperationRecord | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_session_requests
                where account_id = ? and client_request_id = ?
                """,
                (account_id, client_request_id),
            ).fetchone()
        return decode_operation(json.loads(row["payload_json"])) if row else None

    def create(self, request: OperationRecord) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                """
                insert into runtime_session_requests(
                  account_id, client_request_id, status, payload_json
                ) values (?, ?, ?, ?)
                """,
                (
                    request.account_id,
                    request.client_action_id,
                    request.status.value,
                    dumps(encode_operation(request)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate idempotency key") from exc

    def save(self, request: OperationRecord) -> None:
        with self._store.connect() as connection:
            cursor = connection.execute(
                """
                update runtime_session_requests set status = ?, payload_json = ?
                where account_id = ? and client_request_id = ?
                """,
                (
                    request.status.value,
                    dumps(encode_operation(request)),
                    request.account_id,
                    request.client_action_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("session request does not exist")


class SqliteRuntimeTransactionRepository:
    """跨 session 与幂等记录的 SQLite 原子提交边界。"""

    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def recover_stale_operations(self, stale_before: str) -> int:
        recovered = 0
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_operations
                where status = 'processing'
                """
            ).fetchall()
            for row in rows:
                operation = decode_operation(json.loads(row["payload_json"]))
                if (
                    operation.updated_at > stale_before
                    or operation.session_id is None
                ):
                    continue
                session_row = connection.execute(
                    """
                    select payload_json from runtime_game_sessions
                    where session_id = ? and account_id = ?
                      and processing_action_id = ?
                    """,
                    (
                        operation.session_id,
                        operation.account_id,
                        operation.reservation_id,
                    ),
                ).fetchone()
                if session_row is None:
                    continue
                session = decode_session(json.loads(session_row["payload_json"]))
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
                cursor = connection.execute(
                    """
                    update runtime_game_sessions
                    set processing_action_id = null, updated_at = ?, payload_json = ?
                    where session_id = ? and account_id = ?
                      and processing_action_id = ?
                    """,
                    (
                        session.updated_at,
                        dumps(encode_session(session)),
                        session.session_id,
                        session.account_id,
                        operation.reservation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    continue
                self._update_operation(connection, failed)
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
        if operation.session_id is None:
            raise ValueError("game operation requires session_id")
        try:
            with self._store.connect() as connection:
                cursor = connection.execute(
                    """
                    update runtime_game_sessions
                    set status = ?, state_version = ?, processing_action_id = ?,
                        updated_at = ?, payload_json = ?
                    where session_id = ? and account_id = ? and state_version = ?
                      and processing_action_id is null
                    """,
                    self._session_parameters(session, expected_version),
                )
                if cursor.rowcount != 1:
                    raise StateVersionConflictError(
                        "状态版本冲突或已有操作占用当前游戏"
                    )
                if create_operation:
                    connection.execute(
                        """
                        insert into runtime_operations(
                          operation_id, account_id, session_id, client_action_id,
                          status, payload_json
                        ) values (?, ?, ?, ?, ?, ?)
                        """,
                        self._operation_parameters(operation),
                    )
                else:
                    self._update_operation(connection, operation)
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate idempotency key") from exc

    def finish_operation(
        self,
        session: GameSession,
        *,
        expected_version: int,
        operation: OperationRecord,
        research_event: ResearchEvent | None = None,
    ) -> None:
        with self._store.connect() as connection:
            cursor = connection.execute(
                """
                update runtime_game_sessions
                set status = ?, state_version = ?, processing_action_id = ?,
                    updated_at = ?, payload_json = ?
                where session_id = ? and account_id = ? and state_version = ?
                  and processing_action_id = ?
                """,
                (*self._session_parameters(session, expected_version),
                 operation.reservation_id),
            )
            if cursor.rowcount != 1:
                raise StateVersionConflictError("动作预留已失效或状态版本冲突")
            self._update_operation(connection, operation)
            if (
                operation.status is OperationStatus.SUCCEEDED
                and session.state_version > expected_version
            ):
                parent = connection.execute(
                    """
                    select snapshot_id from runtime_game_snapshots
                    where session_id = ? and account_id = ? and timeline_id = ?
                    order by state_version desc limit 1
                    """,
                    (session.session_id, session.account_id, session.timeline_id),
                ).fetchone()
                _insert_snapshot(
                    connection,
                    build_snapshot(
                        session,
                        snapshot_type="auto",
                        reason="operation_committed",
                        parent_snapshot_id=(
                            str(parent["snapshot_id"]) if parent is not None else None
                        ),
                    ),
                )
            if research_event is not None:
                connection.execute(
                    """
                    insert into runtime_research_outbox(
                      research_event_id, research_subject_id, status,
                      attempt_count, created_at, payload_json
                    ) values (?, ?, 'pending', 0, ?, ?)
                    """,
                    (
                        research_event.research_event_id,
                        research_event.research_subject_id,
                        research_event.created_at,
                        dumps(asdict(research_event)),
                    ),
                )

    def complete_session_request(
        self,
        session: GameSession,
        request: OperationRecord,
    ) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_game_sessions(
                      session_id, account_id, status, state_version,
                      processing_action_id, updated_at, payload_json
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.account_id,
                        session.status.value,
                        session.state_version,
                        session.processing_action_id,
                        session.updated_at,
                        dumps(encode_session(session)),
                    ),
                )
                cursor = connection.execute(
                    """
                    update runtime_session_requests
                    set status = ?, payload_json = ?
                    where account_id = ? and client_request_id = ?
                      and status = 'processing'
                    """,
                    (
                        request.status.value,
                        dumps(encode_operation(request)),
                        request.account_id,
                        request.client_action_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("session request does not exist or is completed")
                _insert_snapshot(
                    connection,
                    build_snapshot(
                        session,
                        snapshot_type="checkpoint",
                        reason="session_started",
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate session_id") from exc

    @staticmethod
    def _session_parameters(
        session: GameSession, expected_version: int
    ) -> tuple[object, ...]:
        return (
            session.status.value,
            session.state_version,
            session.processing_action_id,
            session.updated_at,
            dumps(encode_session(session)),
            session.session_id,
            session.account_id,
            expected_version,
        )

    @staticmethod
    def _operation_parameters(operation: OperationRecord) -> tuple[object, ...]:
        return (
            operation.operation_id,
            operation.account_id,
            operation.session_id,
            operation.client_action_id,
            operation.status.value,
            dumps(encode_operation(operation)),
        )

    @staticmethod
    def _update_operation(
        connection: sqlite3.Connection, operation: OperationRecord
    ) -> None:
        cursor = connection.execute(
            """
            update runtime_operations set status = ?, payload_json = ?
            where operation_id = ?
            """,
            (
                operation.status.value,
                dumps(encode_operation(operation)),
                operation.operation_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("operation does not exist")


class SqliteAccountRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def create(self, account: Account) -> None:
        payload = asdict(account)
        payload["roles"] = sorted(account.roles)
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_accounts(
                      account_id, username, disabled, created_at, updated_at, payload_json
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.account_id, account.username, int(account.disabled),
                        account.created_at, account.updated_at, dumps(payload),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate account") from exc

    def get_by_id(self, account_id: str) -> Account | None:
        return self._get("account_id = ?", (account_id,))

    def get_by_username(self, username: str) -> Account | None:
        return self._get("username = ?", (username,))

    def _get(self, where: str, parameters: tuple[object, ...]) -> Account | None:
        with self._store.connect() as connection:
            row = connection.execute(
                f"select payload_json from runtime_accounts where {where}", parameters
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["roles"] = frozenset(payload.get("roles", ()))
        return Account(**payload)


class SqliteAuthSessionRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def create(self, session: AuthSession) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_auth_sessions(
                      token_hash, account_id, expires_at, revoked_at, payload_json
                    ) values (?, ?, ?, ?, ?)
                    """,
                    (
                        session.token_hash, session.account_id, session.expires_at,
                        session.revoked_at, dumps(asdict(session)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate auth session") from exc

    def get(self, token_hash: str) -> AuthSession | None:
        with self._store.connect() as connection:
            row = connection.execute(
                "select payload_json from runtime_auth_sessions where token_hash = ?",
                (token_hash,),
            ).fetchone()
        return AuthSession(**json.loads(row["payload_json"])) if row else None

    def save(self, session: AuthSession) -> None:
        with self._store.connect() as connection:
            cursor = connection.execute(
                """
                update runtime_auth_sessions
                set expires_at = ?, revoked_at = ?, payload_json = ?
                where token_hash = ?
                """,
                (
                    session.expires_at, session.revoked_at,
                    dumps(asdict(session)), session.token_hash,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("auth session does not exist")


class SqliteConsentRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def publish_document(self, document: ConsentDocument) -> None:
        with self._store.connect() as connection:
            row = connection.execute(
                "select document_hash from runtime_consent_documents where consent_version = ?",
                (document.consent_version,),
            ).fetchone()
            if row is not None:
                if row["document_hash"] != document.document_hash:
                    raise ValueError("consent version is immutable")
                return
            connection.execute(
                """
                insert into runtime_consent_documents(
                  consent_version, document_hash, payload_json
                ) values (?, ?, ?)
                """,
                (document.consent_version, document.document_hash, dumps(asdict(document))),
            )

    def get_document(self, consent_version: str) -> ConsentDocument | None:
        with self._store.connect() as connection:
            row = connection.execute(
                "select payload_json from runtime_consent_documents where consent_version = ?",
                (consent_version,),
            ).fetchone()
        return ConsentDocument(**json.loads(row["payload_json"])) if row else None

    def create_record(self, record: ConsentRecord) -> None:
        payload = self._record_payload(record)
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_consent_records(
                      consent_record_id, account_id, consent_version,
                      signed_at, withdrawn_at, payload_json
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.consent_record_id, record.account_id,
                        record.consent_version, record.signed_at,
                        record.withdrawn_at, dumps(payload),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate or invalid consent record") from exc

    def get_record(self, consent_record_id: str) -> ConsentRecord | None:
        with self._store.connect() as connection:
            row = connection.execute(
                "select payload_json from runtime_consent_records where consent_record_id = ?",
                (consent_record_id,),
            ).fetchone()
        return self._decode_record(row["payload_json"]) if row else None

    def latest_for_account(self, account_id: str) -> ConsentRecord | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_consent_records
                where account_id = ? order by signed_at desc limit 1
                """,
                (account_id,),
            ).fetchone()
        return self._decode_record(row["payload_json"]) if row else None

    def save_record(self, record: ConsentRecord) -> None:
        current = self.get_record(record.consent_record_id)
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
        with self._store.connect() as connection:
            connection.execute(
                """
                update runtime_consent_records
                set withdrawn_at = ?, payload_json = ? where consent_record_id = ?
                """,
                (
                    record.withdrawn_at, dumps(self._record_payload(record)),
                    record.consent_record_id,
                ),
            )

    @staticmethod
    def _record_payload(record: ConsentRecord) -> dict:
        payload = asdict(record)
        payload["scopes"] = sorted(record.scopes)
        return payload

    @staticmethod
    def _decode_record(value: str) -> ConsentRecord:
        payload = json.loads(value)
        payload["scopes"] = frozenset(payload.get("scopes", ()))
        return ConsentRecord(**payload)


class SqliteResearchIdentityRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def get_or_create(self, account_id: str) -> ResearchSubject:
        current = self.get_for_account(account_id)
        if current is not None:
            return current
        import secrets
        subject = ResearchSubject(
            research_subject_id=f"rs_{secrets.token_hex(16)}", account_id=account_id
        )
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_research_subjects(
                      research_subject_id, account_id, retired_at, payload_json
                    ) values (?, ?, ?, ?)
                    """,
                    (
                        subject.research_subject_id, subject.account_id,
                        subject.retired_at, dumps(asdict(subject)),
                    ),
                )
        except sqlite3.IntegrityError:
            current = self.get_for_account(account_id)
            if current is None:
                raise
            return current
        return subject

    def get_for_account(self, account_id: str) -> ResearchSubject | None:
        with self._store.connect() as connection:
            row = connection.execute(
                "select payload_json from runtime_research_subjects where account_id = ?",
                (account_id,),
            ).fetchone()
        return ResearchSubject(**json.loads(row["payload_json"])) if row else None


class SqliteExperimentAssignmentRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def create(self, assignment: ExperimentAssignment) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_experiment_assignments(
                      assignment_id, research_subject_id, experiment_id,
                      experiment_group_id, environment, payload_json
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assignment.assignment_id, assignment.research_subject_id,
                        assignment.experiment_id, assignment.experiment_group_id,
                        assignment.environment, dumps(asdict(assignment)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("experiment assignment is immutable") from exc

    def get_for_subject(
        self, research_subject_id: str, experiment_id: str
    ) -> ExperimentAssignment | None:
        with self._store.connect() as connection:
            row = connection.execute(
                """
                select payload_json from runtime_experiment_assignments
                where research_subject_id = ? and experiment_id = ?
                """,
                (research_subject_id, experiment_id),
            ).fetchone()
        return ExperimentAssignment(**json.loads(row["payload_json"])) if row else None


class SqliteResearchEventRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def append(self, event: ResearchEvent) -> None:
        try:
            with self._store.connect() as connection:
                connection.execute(
                    """
                    insert into runtime_research_events(
                      research_event_id, research_subject_id, experiment_id,
                      experiment_group_id, event_type, story_day, created_at, payload_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.research_event_id, event.research_subject_id,
                        event.experiment_id, event.experiment_group_id,
                        event.event_type, event.story_day, event.created_at,
                        dumps(asdict(event)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("duplicate research event") from exc

    def list_for_subject(self, research_subject_id: str) -> tuple[ResearchEvent, ...]:
        with self._store.connect() as connection:
            rows = connection.execute(
                """
                select payload_json from runtime_research_events
                where research_subject_id = ? order by created_at
                """,
                (research_subject_id,),
            ).fetchall()
        return tuple(ResearchEvent(**json.loads(row["payload_json"])) for row in rows)
