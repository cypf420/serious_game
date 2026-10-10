from __future__ import annotations

from dataclasses import replace
import secrets

from serious_game_backend.application.hashing import canonical_request_hash
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    SnapshotRepository,
)
from serious_game_backend.domain.enums import OperationStatus
from serious_game_backend.domain.errors import (
    ContentValidationError,
    IdempotencyKeyReusedError,
    NotFoundError,
    SessionBusyError,
    SnapshotStateMismatchError,
    StateVersionConflictError,
)
from serious_game_backend.domain.operation import OperationRecord, utc_now_iso
from serious_game_backend.infrastructure.repositories.codec import decode_session
from serious_game_backend.infrastructure.repositories.snapshot_codec import (
    build_snapshot,
    snapshot_semantic_differences,
    verify_snapshot,
)


class SaveService:
    def __init__(
        self,
        sessions: GameSessionRepository,
        operations: OperationRepository,
        snapshots: SnapshotRepository,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._snapshots = snapshots

    def list_manual_saves(self, *, account_id: str, session_id: str) -> dict:
        session = self._owned_session(account_id, session_id)
        history = self._snapshots.list_history(account_id, session_id)
        return {
            "state_version": session.state_version,
            "timeline_id": session.timeline_id,
            "manual_saves": [
                {
                    "slot_number": slot.slot_number,
                    "display_name": slot.display_name,
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_type": snapshot.snapshot_type,
                    "story_day": snapshot.story_day,
                    "state_version": snapshot.state_version,
                    "timeline_id": snapshot.timeline_id,
                    "created_at": snapshot.created_at,
                    "updated_at": slot.updated_at,
                }
                for slot, snapshot in self._snapshots.list_manual_slots(
                    account_id, session_id
                )
            ],
            "recent_snapshots": [
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "snapshot_type": snapshot.snapshot_type,
                    "reason": snapshot.reason,
                    "story_day": snapshot.story_day,
                    "state_version": snapshot.state_version,
                    "timeline_id": snapshot.timeline_id,
                    "parent_snapshot_id": snapshot.parent_snapshot_id,
                    "created_at": snapshot.created_at,
                }
                for snapshot in history
            ],
        }

    def create_manual_save(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        state_version: int,
        slot_number: int,
        display_name: str,
        overwrite: bool,
    ) -> dict:
        payload = {
            "session_id": session_id,
            "client_action_id": client_action_id,
            "state_version": state_version,
            "slot_number": slot_number,
            "display_name": display_name,
            "overwrite": overwrite,
        }
        request_hash = canonical_request_hash(payload)
        replay = self._replay(account_id, session_id, client_action_id, request_hash)
        if replay is not None:
            return replay
        session = self._writable_session(account_id, session_id, state_version)
        current_snapshot = self._snapshots.current_for_session(session)
        if current_snapshot is None:
            raise StateVersionConflictError("当前稳定状态缺少历史快照")
        differing_fields = snapshot_semantic_differences(session, current_snapshot)
        if differing_fields:
            raise SnapshotStateMismatchError(
                "当前游戏状态与同版本自动快照不一致，未创建手动存档",
                details={
                    "state_version": session.state_version,
                    "differing_fields": list(differing_fields),
                },
            )
        now = utc_now_iso()
        operation_id = f"save_{secrets.token_hex(12)}"
        manual_snapshot = replace(
            build_snapshot(
                session,
                snapshot_type="manual",
                reason="manual_save",
                parent_snapshot_id=current_snapshot.snapshot_id,
            ),
            # Automatic snapshots are unique per active timeline/version.
            # A manual snapshot owns the same full payload on an isolated,
            # immutable branch rather than pointing at the automatic row.
            timeline_id=(
                f"manual_{session.timeline_id}_{slot_number}_{secrets.token_hex(6)}"
            ),
        )
        response = {
            "operation_id": operation_id,
            "status": OperationStatus.SUCCEEDED.value,
            "state_version": session.state_version,
            "slot_number": slot_number,
            "display_name": display_name,
            "snapshot_id": manual_snapshot.snapshot_id,
            "timeline_id": manual_snapshot.timeline_id,
            "story_day": manual_snapshot.story_day,
            "created_at": manual_snapshot.created_at,
            "slot_updated_at": now,
        }
        operation = OperationRecord(
            operation_id=operation_id,
            account_id=account_id,
            session_id=session_id,
            client_action_id=client_action_id,
            request_hash=request_hash,
            status=OperationStatus.SUCCEEDED,
            response=response,
            updated_at=now,
        )
        self._snapshots.create_manual_save(
            session,
            snapshot=manual_snapshot,
            slot_number=slot_number,
            display_name=display_name,
            overwrite=overwrite,
            operation=operation,
        )
        return response

    def load_snapshot(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        state_version: int,
        snapshot_id: str,
        confirmed: bool,
    ) -> dict:
        payload = {
            "session_id": session_id,
            "client_action_id": client_action_id,
            "state_version": state_version,
            "snapshot_id": snapshot_id,
            "confirmed": confirmed,
        }
        request_hash = canonical_request_hash(payload)
        replay = self._replay(account_id, session_id, client_action_id, request_hash)
        if replay is not None:
            return replay
        if not confirmed:
            raise ContentValidationError("加载存档必须明确二次确认")
        current = self._writable_session(account_id, session_id, state_version)
        source = self._snapshots.get_owned(account_id, session_id, snapshot_id)
        if source is None:
            raise NotFoundError("存档快照不存在")
        if not verify_snapshot(source):
            raise ContentValidationError("存档快照完整性校验失败")
        if (
            source.package_id != current.package_id
            or source.package_version != current.package_version
            or source.package_content_hash != current.package_content_hash
        ):
            raise ContentValidationError("存档剧本包版本与当前游戏不一致")

        restored_value = decode_session(source.session_payload)
        now = utc_now_iso()
        restored_value.logs.append(
            {
                "type": "snapshot_loaded",
                "source_snapshot_id": source.snapshot_id,
                "from_timeline_id": current.timeline_id,
                "visible_to_player": False,
            }
        )
        restored = replace(
            restored_value,
            session_id=current.session_id,
            account_id=current.account_id,
            package_id=current.package_id,
            package_version=current.package_version,
            package_content_hash=current.package_content_hash,
            environment=current.environment,
            consent_record_id=current.consent_record_id,
            research_subject_id=current.research_subject_id,
            experiment_id=current.experiment_id,
            experiment_group_id=current.experiment_group_id,
            timeline_id=f"timeline_{secrets.token_hex(16)}",
            loaded_from_snapshot_id=source.snapshot_id,
            state_version=current.state_version + 1,
            processing_action_id=None,
            updated_at=now,
        )
        if restored.pending_decision is not None:
            restored.pending_decision = replace(
                restored.pending_decision,
                presented_state_version=restored.state_version,
            )
        result_snapshot = build_snapshot(
            restored,
            snapshot_type="checkpoint",
            reason="snapshot_loaded",
            parent_snapshot_id=source.snapshot_id,
        )
        operation_id = f"load_{secrets.token_hex(12)}"
        response = {
            "operation_id": operation_id,
            "status": OperationStatus.SUCCEEDED.value,
            "state_version": restored.state_version,
            "timeline_id": restored.timeline_id,
            "loaded_from_snapshot_id": source.snapshot_id,
            "snapshot_id": result_snapshot.snapshot_id,
            "story_day": restored.game_state.story_day,
        }
        operation = OperationRecord(
            operation_id=operation_id,
            account_id=account_id,
            session_id=session_id,
            client_action_id=client_action_id,
            request_hash=request_hash,
            status=OperationStatus.SUCCEEDED,
            response=response,
            updated_at=now,
        )
        self._snapshots.commit_load(
            current,
            restored,
            expected_version=state_version,
            source_snapshot=source,
            result_snapshot=result_snapshot,
            operation=operation,
        )
        return response

    def _owned_session(self, account_id: str, session_id: str):
        session = self._sessions.get_owned(session_id, account_id)
        if session is None:
            raise NotFoundError("游戏不存在")
        return session

    def _writable_session(
        self, account_id: str, session_id: str, state_version: int
    ):
        session = self._owned_session(account_id, session_id)
        if session.processing_action_id is not None:
            raise SessionBusyError("当前游戏正在处理另一个动作")
        if session.state_version != state_version:
            raise StateVersionConflictError(
                "状态版本已变化，请刷新后重试",
                details={"current_state_version": session.state_version},
            )
        return session

    def _replay(
        self,
        account_id: str,
        session_id: str,
        client_action_id: str,
        request_hash: str,
    ) -> dict | None:
        existing = self._operations.get(account_id, session_id, client_action_id)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError("client_action_id 已用于不同请求")
        if existing.status is OperationStatus.SUCCEEDED and existing.response is not None:
            return existing.response
        raise SessionBusyError("存档操作正在处理")
