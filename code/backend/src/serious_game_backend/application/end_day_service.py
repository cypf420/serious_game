from __future__ import annotations

from dataclasses import replace
import secrets

from serious_game_backend.application.hashing import canonical_request_hash
from serious_game_backend.application.idempotency import (
    raise_stored_operation_error,
    serialize_operation_error,
)
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    RuntimeTransactionRepository,
    ScriptPackageRepository,
)
from serious_game_backend.application.package_lock import require_locked_package
from serious_game_backend.application.ending_service import EndingService
from serious_game_backend.application.night_simulation_service import NightSimulationService
from serious_game_backend.application.story_clock_service import StoryClockService
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.gameplay_governance_service import (
    GameplayGovernanceService,
)
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.domain.enums import OperationStatus, SessionStatus
from serious_game_backend.domain.errors import (
    ActionUnavailableError,
    DecisionRequiredError,
    IdempotencyKeyReusedError,
    NotFoundError,
    OperationRetryRequiredError,
    SessionBusyError,
    SessionEndedError,
    StateVersionConflictError,
)
from serious_game_backend.domain.operation import OperationRecord, utc_now_iso


class EndDayService:
    """日终与普通动作共享 session 单飞门禁和乐观锁。"""

    def __init__(
        self,
        sessions: GameSessionRepository,
        operations: OperationRepository,
        transactions: RuntimeTransactionRepository,
        packages: ScriptPackageRepository,
        clock: StoryClockService,
        nights: NightSimulationService,
        endings: EndingService,
        projector: VisibleStateProjector,
        story_flow: StoryFlowService,
        gameplay_governance: GameplayGovernanceService | None = None,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._transactions = transactions
        self._packages = packages
        self._clock = clock
        self._nights = nights
        self._endings = endings
        self._projector = projector
        self._story_flow = story_flow
        self._gameplay_governance = gameplay_governance

    def end_day(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        state_version: int,
        retry: bool = False,
        read_night_first: bool = False,
        continue_story_only: bool = False,
    ) -> dict:
        payload = {
            "session_id": session_id,
            "client_action_id": client_action_id,
            "state_version": state_version,
        }
        if read_night_first:
            payload["read_night_first"] = True
        if continue_story_only:
            payload["continue_story_only"] = True
        request_hash = canonical_request_hash(payload)
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
                    "上次日终执行为可重试失败；请确认后显式设置 retry=true",
                    details={"operation_id": existing.operation_id},
                )

        session = self._sessions.get_owned(session_id, account_id)
        if session is None:
            raise NotFoundError("游戏不存在")
        if session.status is not SessionStatus.ACTIVE:
            raise SessionEndedError("当前游戏不可继续写入")
        if session.processing_action_id is not None:
            raise SessionBusyError("当前游戏正在处理另一个动作")
        if session.pending_decision is not None:
            raise DecisionRequiredError("必须先处理当前决策")
        if session.active_conversation is not None:
            raise ActionUnavailableError("会谈正在进行，请先结束当前会谈")
        if session.active_group_conversation is not None:
            raise ActionUnavailableError("强制群组会谈正在进行，请先完成")
        if any(action.status == "active" for action in session.governance_actions.values()):
            raise ActionUnavailableError("基础行动场景正在进行，请先继续或结束")
        if session.state_version != state_version:
            raise StateVersionConflictError(
                "状态版本已变化，请刷新后重试",
                details={"current_state_version": session.state_version},
            )
        package = require_locked_package(self._packages, session)
        beat = package.story_day(session.game_state.story_day)
        if beat is not None and not beat.allow_end_day:
            raise ActionUnavailableError("当前剧情节点尚不允许结束当天")
        if (
            beat is not None
            and not beat.end_day_requires_flags.issubset(session.flags)
        ):
            raise ActionUnavailableError("当前剧情节点还有必须完成的互动")

        continuation = self._story_flow.unread_day_continuation(session, package)
        if continuation and not continue_story_only:
            raise ActionUnavailableError(
                "当日还有后续剧情，请点击下一段读完后再结束今日。",
                details={"reason": "STORY_CONTINUATION_REQUIRED"},
            )
        if continue_story_only and not continuation:
            raise ActionUnavailableError("当前没有尚未展开的后续剧情，请刷新现场。")

        operation = (
            replace(
                existing,
                status=OperationStatus.PROCESSING,
                attempt_count=existing.attempt_count + 1,
                error=None,
                updated_at=utc_now_iso(),
            )
            if existing is not None
            else OperationRecord(
                operation_id=f"day_{secrets.token_hex(12)}",
                account_id=account_id,
                session_id=session_id,
                client_action_id=client_action_id,
                request_hash=request_hash,
            )
        )
        session.processing_action_id = operation.operation_id
        session.touch()
        self._transactions.reserve_operation(
            session,
            expected_version=state_version,
            operation=operation,
            create_operation=existing is None,
        )

        try:
            current = self._sessions.get_owned(session_id, account_id)
            if current is None:
                raise NotFoundError("游戏不存在")
            if current.processing_action_id != operation.operation_id:
                raise SessionBusyError("日终预留已失效")
            if current.state_version != state_version:
                raise StateVersionConflictError("状态版本已变化，请刷新后重试")

            if continue_story_only:
                # Normal story navigation persists the next passage without
                # touching the date, resources, or night simulation.
                self._story_flow.append_night(current, package)
                current.processing_action_id = None
                current.state_version += 1
                current.touch()
                response = {
                    "operation_id": operation.operation_id,
                    "status": OperationStatus.SUCCEEDED.value,
                    "phase": "story_continued",
                    "state_version": current.state_version,
                    "visible_state": self._projector.project(current, package),
                }
                self._transactions.finish_operation(
                    current,
                    expected_version=state_version,
                    operation=replace(
                        operation, status=OperationStatus.SUCCEEDED,
                        response=response, updated_at=utc_now_iso(),
                    ),
                )
                return response
            night_record = self._nights.run_night(current, package)
            triggered: list[str] = []
            contract_settlements: list[dict] = []
            expired_contract_reservations: list[str] = []
            simulated_days: list[int] = []
            while True:
                previous_day = current.game_state.story_day
                triggered.extend(
                    self._clock.end_day(current, package)
                )
                if current.game_state.story_day == previous_day:
                    break
                if self._gameplay_governance is not None:
                    expired_contract_reservations.extend(
                        self._gameplay_governance.expire_reservations(current)
                    )
                    contract_settlements.extend(
                        self._gameplay_governance.settle_due_contracts(
                            current, package
                        )
                    )
                for index, line in enumerate(night_record.get("morning_card", ())):
                    current.append_narrative(
                        story_day=current.game_state.story_day,
                        kind="morning_card",
                        text=line,
                        content_instance_id=(
                            f"morning:{night_record.get('story_day')}:{index}"
                        ),
                        beat_id=(
                            package.story_day(current.game_state.story_day).beat_id
                            if package.story_day(current.game_state.story_day)
                            else None
                        ),
                        presentation_phase="morning",
                    )
                self._story_flow.enter_current_day(current, package)
                if current.game_state.story_day == 90:
                    self._endings.finalize(current, package)
                    break
                if current.pending_decision is not None:
                    break
                if current.group_conversation_queue:
                    break
                next_beat = package.story_day(current.game_state.story_day)
                if (
                    package.gameplay_schema_version >= 2
                    or next_beat is None
                    or next_beat.day_mode != "simulated"
                ):
                    break
                simulated_days.append(current.game_state.story_day)
                self._story_flow.append_night(current, package)
                night_record = self._nights.run_night(current, package)
            self._nights.activate_next_group_conversation(current)
            NPCRelationshipService.synchronize(current, package)
            current.processing_action_id = None
            current.state_version += 1
            current.touch()
            response = {
                "operation_id": operation.operation_id,
                "status": OperationStatus.SUCCEEDED.value,
                "state_version": current.state_version,
                "triggered_event_ids": triggered,
                "simulated_story_days": simulated_days,
                "contract_settlements": contract_settlements,
                "expired_contract_reservations": sorted(set(
                    expired_contract_reservations
                )),
                "ending": current.ending_result,
                "visible_state": self._projector.project(current, package),
            }
            completed_operation = replace(
                operation,
                status=OperationStatus.SUCCEEDED,
                response=response,
                updated_at=utc_now_iso(),
            )
            self._transactions.finish_operation(
                current,
                expected_version=state_version,
                operation=completed_operation,
            )
            return response
        except Exception as exc:
            current = self._sessions.get_owned(session_id, account_id)
            if current is not None and current.processing_action_id == operation.operation_id:
                current.processing_action_id = None
                current.touch()
                failed_operation = replace(
                    operation,
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
                    operation=failed_operation,
                )
            raise
