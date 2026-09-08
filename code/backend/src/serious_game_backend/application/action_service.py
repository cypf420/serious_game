from __future__ import annotations

from dataclasses import replace
import secrets
from typing import Callable

from serious_game_backend.application.hashing import canonical_request_hash
from serious_game_backend.application.idempotency import (
    raise_stored_operation_error,
    serialize_operation_error,
)
from serious_game_backend.application.interaction_opportunity_service import (
    InteractionOpportunityService,
)
from serious_game_backend.application.npc_turn_service import NPCTurnService
from serious_game_backend.application.npc_memory_service import NPCMemoryService
from serious_game_backend.application.npc_demand_service import NPCDemandService
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.application.stream_lifecycle import (
    StreamCancelCallback,
    StreamCancelled,
    ensure_stream_open,
)
from serious_game_backend.application.package_lock import require_locked_package
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    RuntimeTransactionRepository,
    ScriptPackageRepository,
)
from serious_game_backend.application.scripted_effect_service import ScriptedEffectService
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.application.action_quote_service import ActionQuoteService
from serious_game_backend.application.action_handler_registry import ActionHandlerRegistry
from serious_game_backend.application.trust_derivation_service import TrustDerivationService
from serious_game_backend.application.disclosure_gate_service import (
    DisclosureGateService,
)
from serious_game_backend.application.model_input_policy import ModelInputPolicy
from serious_game_backend.application.research_projection_service import (
    ResearchProjectionService,
)
from serious_game_backend.domain.action import ActionCommand, ActionRule
from serious_game_backend.domain.enums import ActionInputMode, OperationStatus, SessionStatus
from serious_game_backend.domain.errors import (
    ActionUnavailableError,
    DecisionRequiredError,
    IdempotencyKeyReusedError,
    InsufficientActionPointsError,
    NotFoundError,
    OperationRetryRequiredError,
    SessionBusyError,
    SessionEndedError,
    StateVersionConflictError,
)
from serious_game_backend.domain.operation import OperationRecord, utc_now_iso
from serious_game_backend.domain.llm import RoleTurnContext
from serious_game_backend.domain.story import ScriptedEffects
from serious_game_backend.domain.conversation import (
    ActiveConversation,
    CompletedConversation,
)


class ActionService:
    """短预留 -> 锁外执行 -> 短提交的原子动作门面。"""

    def __init__(
        self,
        sessions: GameSessionRepository,
        operations: OperationRepository,
        transactions: RuntimeTransactionRepository,
        packages: ScriptPackageRepository,
        projector: VisibleStateProjector,
        opportunities: InteractionOpportunityService,
        npc_turns: NPCTurnService,
        scripted_effects: ScriptedEffectService,
        story_flow: StoryFlowService,
        npc_memories: NPCMemoryService,
        action_quotes: ActionQuoteService | None = None,
        action_handlers: ActionHandlerRegistry | None = None,
        trust_derivation: TrustDerivationService | None = None,
        disclosure_gate: DisclosureGateService | None = None,
        model_input_policy: ModelInputPolicy | None = None,
        research_projection: ResearchProjectionService | None = None,
    ) -> None:
        self._sessions = sessions
        self._operations = operations
        self._transactions = transactions
        self._packages = packages
        self._projector = projector
        self._opportunities = opportunities
        self._npc_turns = npc_turns
        self._scripted_effects = scripted_effects
        self._story_flow = story_flow
        self._npc_memories = npc_memories
        self._action_quotes = action_quotes or ActionQuoteService()
        self._action_handlers = action_handlers or ActionHandlerRegistry(scripted_effects)
        self._trust_derivation = trust_derivation or TrustDerivationService()
        self._disclosure_gate = disclosure_gate or DisclosureGateService()
        self._model_input_policy = model_input_policy
        self._research_projection = research_projection

    def execute(
        self,
        *,
        account_id: str,
        session_id: str,
        command: ActionCommand,
        stream_event: Callable[[dict], None] | None = None,
        stream_cancelled: StreamCancelled = None,
        stream_cancel_register: Callable[[StreamCancelCallback], None] | None = None,
    ) -> dict:
        request_hash = canonical_request_hash({
            "session_id": session_id,
            **command.canonical_payload(),
        })
        existing = self._operations.get(account_id, session_id, command.client_action_id)
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
            if existing.status is OperationStatus.FAILED_RETRYABLE and not command.retry:
                raise OperationRetryRequiredError(
                    "上次执行为可重试失败；请确认后显式设置 retry=true",
                    details={"operation_id": existing.operation_id},
                )

        session = self._owned_session(session_id, account_id)
        package = require_locked_package(self._packages, session)
        NPCRelationshipService.synchronize(session, package)
        self._validate_write_gate(session, command)
        beat = package.story_day(session.game_state.story_day)
        if (
            command.input_mode is not ActionInputMode.DECISION
            and beat is not None
            and not beat.allow_actions
            and not (
                package.gameplay_schema_version >= 2
                and session.game_state.story_day < 90
            )
        ):
            raise ActionUnavailableError("当前剧情节点不开放自主行动")
        operation_id = (
            existing.operation_id if existing is not None else f"act_{secrets.token_hex(12)}"
        )
        # 128-bit attempt identity remains within MySQL's varchar(64) session
        # reservation column when combined with the stable action id.
        lease_token = secrets.token_hex(16)

        # 短预留：真实 MySQL 适配器在此做条件更新；不在这之后持数据库锁。
        if existing is None:
            operation = OperationRecord(
                operation_id=operation_id,
                account_id=account_id,
                session_id=session_id,
                client_action_id=command.client_action_id,
                request_hash=request_hash,
                lease_token=lease_token,
            )
        else:
            operation = replace(
                existing,
                status=OperationStatus.PROCESSING,
                attempt_count=existing.attempt_count + 1,
                error=None,
                updated_at=utc_now_iso(),
                lease_token=lease_token,
            )
        session.processing_action_id = operation.reservation_id
        session.touch()
        self._transactions.reserve_operation(
            session,
            expected_version=command.state_version,
            operation=operation,
            create_operation=existing is None,
        )
        if stream_cancel_register is not None:
            stream_cancel_register(lambda: self.abort_stream_operation(
                account_id=account_id,
                session_id=session_id,
                client_action_id=command.client_action_id,
                reservation_id=operation.reservation_id,
            ))

        try:
            draft = self._build_draft(
                session,
                package,
                command,
                account_id=account_id,
                operation_id=operation_id,
                stream_event=stream_event,
                stream_cancelled=stream_cancelled,
            )
            ensure_stream_open(stream_cancelled)
            # 真实 LLM 接入后只允许在这里（事务外）调用。
            current = self._owned_session(session_id, account_id)
            if current.processing_action_id != operation.reservation_id:
                raise SessionBusyError("当前动作预留已失效")
            if current.state_version != command.state_version:
                raise StateVersionConflictError("状态版本已变化，请刷新后重试")
            known_fact_ids_before = set(current.known_fact_ids)
            self._apply_draft(
                current,
                package,
                draft,
                resource_reference=command.client_action_id,
            )
            self._trust_derivation.apply(current, package)
            NPCDemandService.sync(current, package)
            NPCRelationshipService.synchronize(current, package)
            current.processing_action_id = None
            current.state_version += 1
            current.touch()
            response = {
                "operation_id": operation_id,
                "status": OperationStatus.SUCCEEDED.value,
                "state_version": current.state_version,
                "narrative": draft["narrative"],
                "visible_state": self._projector.project(current, package),
            }
            if draft["kind"] in {
                "conversation_start", "free_text", "conversation_end"
            } and draft.get("opportunity") is not None:
                response["fact_acquisition_bindings"] = [
                    {
                        "fact_id": fact_id,
                        "route_type": "conversation",
                        "source_id": draft["opportunity"].opportunity_id,
                    }
                    for fact_id in sorted(
                        set(current.known_fact_ids) - known_fact_ids_before
                    )
                ]
            elif draft["kind"] == "resource_action":
                response["fact_acquisition_bindings"] = [
                    {
                        "fact_id": fact_id,
                        "route_type": "action",
                        "source_id": draft["definition"].action_id,
                    }
                    for fact_id in sorted(
                        set(current.known_fact_ids) - known_fact_ids_before
                    )
                ]
            if draft.get("npc_reply") is not None:
                response["npc_reply"] = draft["npc_reply"]
            if draft["kind"] in {
                "conversation_start", "free_text", "input_rejected", "conversation_end"
            }:
                response["conversation"] = self._conversation_response(
                    current, draft
                )
            if draft.get("completion_status") is not None:
                response["completion_status"] = draft["completion_status"]
            completed_operation = replace(
                operation,
                status=OperationStatus.SUCCEEDED,
                response=response,
                updated_at=utc_now_iso(),
            )
            research_event = (
                self._research_projection.build_action_event(current, command, draft)
                if self._research_projection is not None else None
            )
            self._transactions.finish_operation(
                current,
                expected_version=command.state_version,
                operation=completed_operation,
                research_event=research_event,
            )
            if draft["kind"] == "free_text":
                self._record_turn_memories(
                    current,
                    package,
                    draft,
                    account_id=account_id,
                    operation_id=operation_id,
                )
            return response
        except Exception as exc:
            current = self._sessions.get_owned(session_id, account_id)
            if (
                current is not None
                and current.processing_action_id == operation.reservation_id
            ):
                current.processing_action_id = None
                current.touch()
                failure_status = (
                    OperationStatus.FAILED_RETRYABLE
                    if getattr(exc, "retryable", False)
                    else OperationStatus.FAILED_FINAL
                )
                failed_operation = replace(
                    operation,
                    status=failure_status,
                    error=serialize_operation_error(exc),
                    updated_at=utc_now_iso(),
                )
                self._transactions.finish_operation(
                    current,
                    expected_version=current.state_version,
                    operation=failed_operation,
                )
            raise

    def abort_stream_operation(
        self,
        *,
        account_id: str,
        session_id: str,
        client_action_id: str,
        reservation_id: str | None = None,
    ) -> bool:
        """Invalidate a disconnected stream reservation without waiting for its worker."""
        operation = self._operations.get(
            account_id, session_id, client_action_id
        )
        if (
            operation is None
            or operation.status is not OperationStatus.PROCESSING
        ):
            return False
        expected_reservation = reservation_id or operation.reservation_id
        if operation.reservation_id != expected_reservation:
            return False
        current = self._sessions.get_owned(session_id, account_id)
        if (
            current is None
            or current.processing_action_id != expected_reservation
        ):
            return False
        current.processing_action_id = None
        current.touch()
        failed_operation = replace(
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
                operation=failed_operation,
            )
        except StateVersionConflictError:
            # Another terminal transition won the reservation CAS.
            return False
        return True

    def _build_draft(
        self,
        session,
        package,
        command: ActionCommand,
        *,
        account_id: str = "",
        operation_id: str = "",
        stream_event: Callable[[dict], None] | None = None,
        stream_cancelled: StreamCancelled = None,
    ) -> dict:
        if session.active_group_conversation is not None:
            raise ActionUnavailableError("必须先完成NPC发起的群组会谈")
        if command.input_mode is ActionInputMode.CONVERSATION_START:
            if session.active_conversation is not None:
                raise ActionUnavailableError("已有进行中的会谈，请先继续或结束当前会谈")
            if not command.opportunity_id or not command.target_npc_id:
                raise ActionUnavailableError("开始会谈缺少互动机会或目标人物")
            opportunity = self._opportunities.require_available(
                command.opportunity_id, session, package
            )
            if opportunity.npc_id != command.target_npc_id:
                raise ActionUnavailableError("目标 NPC 与互动机会不匹配")
            rule = package.action_rules[opportunity.action_id]
            cost = self._validate_tool(
                session, package, rule, target_npc_ids=(opportunity.npc_id,)
            )
            return {
                "kind": "conversation_start",
                "rule": rule,
                "opportunity": opportunity,
                "npc_id": opportunity.npc_id,
                "conversation_id": f"conv_{secrets.token_hex(12)}",
                "cost": cost,
                "narrative": opportunity.opening_narrative,
            }
        if command.input_mode is ActionInputMode.CONVERSATION_END:
            conversation = session.active_conversation
            if conversation is None or conversation.conversation_id != command.conversation_id:
                raise ActionUnavailableError("当前没有这场进行中的会谈")
            opportunity = next(
                item for item in package.interaction_opportunities
                if item.opportunity_id == conversation.opportunity_id
            )
            profile = next(
                item for item in package.npc_profiles
                if item.npc_id == conversation.npc_id
            )
            disclosed = {
                item.get("disclosure_id")
                for item in session.logs
                if item.get("type") == "conversation_turn"
                and item.get("conversation_id") == conversation.conversation_id
                and item.get("disclosure_id")
            }
            completed = (
                opportunity.complete_on_player_exit
                and conversation.turn_count >= opportunity.minimum_turns
                and opportunity.required_disclosure_ids.issubset(disclosed)
            )
            narrative = (
                f"你收住话头，向{profile.name}告辞。本次会谈已经完成既定接触目标。"
                if completed else
                f"你先向{profile.name}告辞。这次接触尚未达到既定目标，相关机会仍会保留。"
            )
            return {
                "kind": "conversation_end",
                "opportunity": opportunity,
                "npc_id": conversation.npc_id,
                "conversation_id": conversation.conversation_id,
                "cost": 0,
                "narrative": narrative,
                "ended_by": "player",
                "completed": completed,
                "completion_status": "completed" if completed else "incomplete",
            }
        if command.input_mode is ActionInputMode.TOOL:
            if package.gameplay_schema_version >= 2:
                raise ActionUnavailableError(
                    "旧 tool 入口已停用；人物接触请开始会谈，非会谈工具请先报价"
                )
            if not command.action_id or not command.opportunity_id:
                raise ActionUnavailableError("tool 模式缺少 opportunity_id 或 action_id")
            opportunity = self._opportunities.require_available(
                command.opportunity_id, session, package
            )
            if opportunity.action_id != command.action_id:
                raise ActionUnavailableError("行动与当前机会不匹配")
            rule = package.action_rules.get(command.action_id)
            if rule is None:
                raise ActionUnavailableError("行动未在当前剧本包注册")
            cost = self._validate_tool(
                session, package, rule, target_npc_ids=(opportunity.npc_id,)
            )
            return {
                "kind": "tool",
                "rule": rule,
                "opportunity": opportunity,
                "cost": cost,
                "narrative": f"已执行：{rule.name}。具体后果将在剧情和后续状态中体现。",
            }
        if command.input_mode is ActionInputMode.RESOURCE_ACTION:
            if not command.action_id:
                raise ActionUnavailableError("资源动作缺少 action_id")
            quote = self._action_quotes.require_matching(
                session,
                package,
                action_id=command.action_id,
                target_ids=command.target_ids,
                parameters=command.parameters,
                quote_id=command.quote_id,
            )
            definition = package.resource_actions[command.action_id]
            return {
                "kind": "resource_action",
                "rule": package.action_rules[command.action_id],
                "definition": definition,
                "quote": quote,
                "cost": quote.action_point_cost,
                "narrative": definition.narrative,
            }
        if command.input_mode is ActionInputMode.DECISION:
            pending = session.pending_decision
            if pending is None:
                raise ActionUnavailableError("当前没有待处理决策")
            decision = package.decisions.get(command.decision_id)
            if decision is None or command.decision_id != pending.decision_id:
                raise ActionUnavailableError("决策与当前实例不匹配")
            parameters: dict = {}
            option_id = command.option_id
            effects = None
            if decision.input_kind == "allocation":
                option_id = "submit"
                parameters = self._validate_allocation(decision, command.parameters)
                effects = self._dp2_10_allocation_effects(parameters, decision.option(option_id))
            elif decision.input_kind == "sorting" and command.ordered_option_ids:
                option_id = "_".join(item.lower() for item in command.ordered_option_ids)
            if option_id not in pending.option_ids:
                raise ActionUnavailableError("决策选项与当前实例不匹配")
            option = decision.option(option_id)
            if option is None:
                raise ActionUnavailableError("决策选项未在剧本包注册")
            return {
                "kind": "decision",
                "decision_id": command.decision_id,
                "option_id": option_id,
                "option": option,
                "effects": effects or self._effective_effects(
                    option,
                    session.flags,
                    session.state_values,
                    self._ledger_values(session),
                    pending.context,
                    decision_id=decision.decision_id,
                    known_fact_ids=session.known_fact_ids,
                ),
                "parameters": parameters,
                "cost": 0,
                "narrative": self._story_flow.session_public_text(
                    decision.visible_consequence(option, session.flags, session.known_fact_ids), session
                ),
            }
        if command.input_mode is ActionInputMode.OVERTIME:
            state = session.game_state
            points = int(command.parameters["points"])
            if state.action_points != 0:
                raise ActionUnavailableError("只有当日可用行动点用尽后才能申请加班")
            if state.overtime_used_today:
                raise ActionUnavailableError("今天已经申请过加班")
            if state.chapter_overtime_count >= 3:
                raise ActionUnavailableError("本章加班次数已经用尽")
            if state.fatigue >= 75:
                raise ActionUnavailableError("当前已接近崩溃，不能继续加班")
            return {
                "kind": "overtime",
                "points": points,
                "cost": 0,
                "narrative": f"你决定再加班处理 {points} 点工作。新增行动点已经到账，疲惫将在日终结算。",
            }
        if (
            not command.conversation_id
            or not command.opportunity_id
            or not command.target_npc_id
            or not command.player_text
        ):
            raise ActionUnavailableError("自由文字请求字段不完整")
        conversation = session.active_conversation
        if conversation is None or conversation.conversation_id != command.conversation_id:
            raise ActionUnavailableError("当前没有这场进行中的会谈")
        if (
            conversation.opportunity_id != command.opportunity_id
            or conversation.npc_id != command.target_npc_id
        ):
            raise ActionUnavailableError("自由文字请求与当前会谈不匹配")
        opportunity = next(
            (
                item for item in package.interaction_opportunities
                if item.opportunity_id == conversation.opportunity_id
            ),
            None,
        )
        if opportunity is None:
            raise ActionUnavailableError("当前会谈引用的互动机会不存在")
        if opportunity.npc_id != command.target_npc_id:
            raise ActionUnavailableError("目标 NPC 与互动机会不匹配")
        rule = package.action_rules[opportunity.action_id]
        npc_state = session.npc_states[opportunity.npc_id]
        profile = next(
            item for item in package.npc_profiles
            if item.npc_id == opportunity.npc_id
        )
        normalized_text = "".join(command.player_text.split()).casefold()
        repeat_count = sum(
            "".join(item.get("player", "").split()).casefold() == normalized_text
            for item in conversation.transcript
        )
        fact_boundary = self._disclosure_gate.role_turn_boundary(
            session, package, opportunity, repeat_count=repeat_count,
            player_text=command.player_text,
        )
        memory_items = self._npc_memories.retrieve(
            session_id=session.session_id,
            npc_id=opportunity.npc_id,
            story_day=session.game_state.story_day,
            query=command.player_text,
        )
        memory_context = self._npc_memories.context(
            session_id=session.session_id,
            npc_id=opportunity.npc_id,
            story_day=session.game_state.story_day,
            query=command.player_text,
        )
        relationship_context = NPCRelationshipService.relationship_context(
            session, opportunity.npc_id
        )
        recent_change_reasons = (
            NPCRelationshipService.recent_visible_change_reasons(
                session, opportunity.npc_id
            )
        )
        unresolved_demands = tuple(
            demand.description
            for demand in package.npc_demands
            if demand.npc_id == opportunity.npc_id
            and session.npc_demand_states.get(demand.demand_id, {}).get("status") != "satisfied"
        )
        prepared_input = (
            self._model_input_policy.prepare(account_id, command.player_text)
            if self._model_input_policy is not None
            else None
        )
        beat = package.story_day(session.game_state.story_day)
        turn = self._npc_turns.run(
            RoleTurnContext(
                session_id=session.session_id,
                account_id=account_id,
                operation_id=operation_id,
                npc_id=opportunity.npc_id,
                player_text=(prepared_input.text if prepared_input else command.player_text),
                story_day=session.game_state.story_day,
                opportunity_id=opportunity.opportunity_id,
                allowed_fact_ids=fact_boundary.gate.allowed_fact_ids,
                required_disclosure_ids=fact_boundary.required_disclosure_ids,
                npc_name=profile.name,
                npc_state_tier=profile.state_tier.value,
                role_setting=profile.role_setting,
                big_five=(
                    profile.big_five.as_dict()
                    if profile.big_five is not None else {}
                ),
                prompt_template=package.role_turn_prompt,
                prompt_version=package.role_turn_prompt_version,
                allowed_fact_texts=fact_boundary.allowed_fact_texts,
                allowed_fact_markers=fact_boundary.allowed_fact_markers,
                forbidden_fact_markers=fact_boundary.forbidden_fact_markers,
                forbidden_fact_signatures=fact_boundary.forbidden_fact_signatures,
                memory_items=memory_items,
                relationship_context=relationship_context,
                recent_visible_change_reasons=recent_change_reasons,
                unresolved_commitments=memory_context["unresolved_commitments"],
                unresolved_demands=unresolved_demands,
                conversation_turn_count=conversation.turn_count,
                conversation_history=tuple(conversation.transcript),
                conversation_opening=opportunity.opening_narrative,
                conversation_goal=opportunity.conversation_goal,
                visible_world_context={
                    "player_identity": "李致远，云溪县县长",
                    "story_day": session.game_state.story_day,
                    "story_title": beat.title if beat is not None else "",
                    "origin": package.origins[session.origin_id].title,
                    "known_facts": [
                        package.facts[item].title
                        for item in sorted(session.known_fact_ids)
                        if item in package.facts
                    ],
                    "npc_disclosure_posture": fact_boundary.gate.trust_label,
                    "relationship_context": relationship_context,
                    "recent_visible_change_reasons": list(recent_change_reasons),
                    "unresolved_commitments": list(
                        memory_context["unresolved_commitments"]
                    ),
                    "unresolved_demands": list(unresolved_demands),
                    "fatigue_posture": (
                        "撑不住了" if session.game_state.fatigue >= 75 else
                        "有些吃力" if session.game_state.fatigue >= 50 else
                        "略显疲乏" if session.game_state.fatigue >= 25 else
                        "精神尚可"
                    ),
                },
                player_reference_materials={
                    "mission": package.public_briefing["mission"],
                    "compensation_policy": package.public_briefing["compensation_policy"],
                    "known_materials": [
                        {
                            "title": package.facts[item].title,
                            "text": package.facts[item].text,
                            "source": package.facts[item].source_label,
                        }
                        for item in sorted(session.known_fact_ids)
                        if item in package.facts
                    ],
                },
            ),
            npc_state,
            random_seed=session.random_seed,
            stream_event=stream_event,
            stream_cancelled=stream_cancelled,
        )
        if turn.input_relevance == "irrelevant":
            return {
                "kind": "input_rejected",
                "rule": rule,
                "cost": 0,
                "conversation_id": conversation.conversation_id,
                "opportunity": opportunity,
                "npc_id": opportunity.npc_id,
                "narrative": turn.dialogue,
            }
        if turn.attitude_delta > 0 and session.game_state.fatigue >= 25:
            factor = 0.9 if session.game_state.fatigue < 50 else (
                0.8 if session.game_state.fatigue < 75 else 0.7
            )
            turn = replace(turn, attitude_delta=int(turn.attitude_delta * factor))
        return {
            "kind": "free_text",
            "rule": rule,
            "cost": 0 if conversation.cost_charged else conversation.quoted_cost,
            "conversation_id": conversation.conversation_id,
            "player_text": command.player_text,
            "opportunity": opportunity,
            "npc_id": opportunity.npc_id,
            "turn": turn,
            "trust_consumption": -15 if repeat_count >= 2 else -5 if repeat_count == 1 else 0,
            "clear_disclosure_quota": repeat_count >= 2,
            "narrative": turn.dialogue,
            "npc_reply": {
                "npc_id": turn.npc_id,
                "text": turn.dialogue,
                "portrait_state": turn.portrait_state,
            },
            "ended_by": (
                "npc" if turn.conversation_state == "end" else None
            ),
            "privacy": ({
                "consent_record_id": prepared_input.consent_record_id,
                "pii_types": prepared_input.pii_types,
                "replacement_count": prepared_input.replacement_count,
            } if prepared_input else None),
        }

    def _validate_tool(
        self,
        session,
        package,
        rule: ActionRule,
        *,
        target_npc_ids: tuple[str, ...] = (),
    ) -> int:
        state = session.game_state
        if rule.daily_cap is not None:
            used = state.daily_action_counts.get(rule.action_id, 0)
            if used >= rule.daily_cap:
                raise ActionUnavailableError("该行动已达到今日次数上限")
        if rule.half_day and state.half_day_action_used:
            raise ActionUnavailableError("今日半日行程已经占用")
        if rule.hard_force and state.fatigue >= 75:
            raise ActionUnavailableError("当前状态不能执行强制手段")
        if rule.precondition_flags_any and not any(
            flag in session.flags for flag in rule.precondition_flags_any
        ):
            raise ActionUnavailableError("行动前置条件尚未满足")
        cost = rule.cost_for(package.action_cost_tier(state.story_day))
        if state.action_points < cost:
            raise InsufficientActionPointsError(
                "当日行动点不足",
                details={"required": cost, "remaining": state.action_points},
            )
        return cost

    def _apply_draft(
        self,
        session,
        package,
        draft: dict,
        *,
        resource_reference: str,
    ) -> None:
        if draft["kind"] in {
            "tool", "resource_action", "conversation_start", "free_text", "input_rejected",
            "conversation_end",
            "overtime",
        }:
            rule: ActionRule | None = draft.get("rule")
            if draft["kind"] in {"tool", "resource_action"} or (
                draft["kind"] == "free_text" and draft["cost"] > 0
            ):
                assert rule is not None
                session.game_state = session.game_state.spend_action_points(
                    rule.action_id,
                    draft["cost"],
                    half_day=rule.half_day,
                )
                if (
                    draft["kind"] == "resource_action"
                    and rule.category in {"调查手段", "强制手段"}
                ):
                    counts = dict(session.game_state.daily_action_counts)
                    key = f"category:{rule.category}"
                    counts[key] = counts.get(key, 0) + 1
                    session.game_state = replace(
                        session.game_state, daily_action_counts=counts
                    )
            log = {
                "type": draft["kind"],
                "story_day": session.game_state.story_day,
                "action_id": rule.action_id if rule is not None else None,
                "cost_action_points": (
                    0 if draft["kind"] == "conversation_start" else draft["cost"]
                ),
                "visible_to_player": True,
            }
            opportunity = draft.get("opportunity")
            if opportunity is not None:
                log["opportunity_id"] = opportunity.opportunity_id
            if draft["kind"] == "tool":
                self._apply_opportunity_completion(session, package, opportunity)
            elif draft["kind"] == "resource_action":
                narrative = self._action_handlers.execute(
                    session,
                    package,
                    draft["definition"],
                    draft["quote"],
                    source_reference=resource_reference,
                )
                draft["narrative"] = narrative
                log.update({
                    "type": "action_completed",
                    "target_ids": list(draft["quote"].target_ids),
                    "parameters": dict(draft["quote"].parameters),
                    "budget_cost": draft["quote"].budget_cost,
                    "public_narrative": narrative,
                })
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="action_result",
                    text=narrative,
                )
            elif draft["kind"] == "conversation_start":
                session.active_conversation = ActiveConversation(
                    conversation_id=draft["conversation_id"],
                    opportunity_id=opportunity.opportunity_id,
                    npc_id=draft["npc_id"],
                    story_day=session.game_state.story_day,
                    quoted_cost=draft["cost"],
                    cost_charged=False,
                    start_reason=opportunity.entry_type,
                )
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="conversation_opening",
                    speaker=next(
                        (
                            item.name
                            for item in package.npc_profiles
                            if item.npc_id == draft["npc_id"]
                        ),
                        draft["npc_id"],
                    ),
                    text=opportunity.opening_narrative,
                )
                log["type"] = "conversation_started"
                log["npc_id"] = draft["npc_id"]
                log["conversation_id"] = draft["conversation_id"]
            elif draft["kind"] == "free_text":
                turn = draft["turn"]
                conversation = session.active_conversation
                if conversation is None:
                    raise ActionUnavailableError("进行中的会谈已丢失")
                if draft["cost"] > 0:
                    conversation.cost_charged = True
                npc_state = session.npc_states[draft["npc_id"]]
                session.npc_states[draft["npc_id"]] = replace(
                    npc_state,
                    trust_score=(
                        max(0, npc_state.trust_score + draft["trust_consumption"])
                        if npc_state.trust_score is not None else None
                    ),
                    attitude_score=(
                        max(0, min(100, npc_state.attitude_score + turn.attitude_delta))
                        if npc_state.attitude_score is not None
                        else None
                    ),
                    anxiety_score=(
                        max(0, min(100, npc_state.anxiety_score + turn.anxiety_delta))
                        if npc_state.anxiety_score is not None
                        else None
                    ),
                    chapter_disclosure_used=(
                        npc_state.chapter_disclosure_used
                        or draft["clear_disclosure_quota"]
                    ),
                )
                visible_reasons = []
                public_topic = (
                    opportunity.conversation_goal.strip()
                    if opportunity is not None else "当前事项"
                ) or "当前事项"
                if draft["trust_consumption"] < 0:
                    visible_reasons.append((
                        "trust",
                        f"围绕“{public_topic}”的本次会谈触及了对方的信任边界。",
                    ))
                if turn.attitude_delta > 0:
                    visible_reasons.append(("attitude", f"围绕“{public_topic}”的本次会谈中，回应使对方更愿意合作。"))
                elif turn.attitude_delta < 0:
                    visible_reasons.append(("attitude", f"围绕“{public_topic}”的本次会谈中，表达使对方更为抵触。"))
                if turn.anxiety_delta > 0:
                    visible_reasons.append(("anxiety", f"围绕“{public_topic}”的本次会谈增加了对方对后续风险的担忧。"))
                elif turn.anxiety_delta < 0:
                    visible_reasons.append(("anxiety", f"围绕“{public_topic}”的本次会谈缓解了对方对后续风险的担忧。"))
                for dimension, reason in visible_reasons:
                    session.logs.append({
                        "type": "relationship_change",
                        "story_day": session.game_state.story_day,
                        "npc_id": draft["npc_id"],
                        "dimension": dimension,
                        "reason": reason,
                        "visible_to_player": True,
                    })
                log["type"] = "conversation_turn"
                log["npc_id"] = draft["npc_id"]
                log["conversation_id"] = conversation.conversation_id
                privacy = draft.get("privacy")
                if privacy is not None:
                    log["model_input_minimization"] = {
                        "consent_record_id": privacy["consent_record_id"],
                        "pii_types": list(privacy["pii_types"]),
                        "replacement_count": privacy["replacement_count"],
                    }
                if turn.disclosure_id is not None:
                    session.known_fact_ids.add(turn.disclosure_id)
                    log["disclosure_id"] = turn.disclosure_id
                    fact = package.facts.get(turn.disclosure_id)
                    if fact is not None and fact.disclosure_tier == 4:
                        session.npc_states[draft["npc_id"]] = replace(
                            session.npc_states[draft["npc_id"]],
                            chapter_disclosure_used=True,
                        )
                    session.logs.append({
                        "type": "fact_learned",
                        "story_day": session.game_state.story_day,
                        "fact_id": turn.disclosure_id,
                        "source_id": draft["npc_id"],
                        "visible_to_player": True,
                    })
                log["will_share_with"] = list(turn.will_share_with)
                if draft["trust_consumption"]:
                    session.logs.append({
                        "type": "trust_consumed",
                        "story_day": session.game_state.story_day,
                        "npc_id": draft["npc_id"],
                        "reason": "repeated_question",
                        "delta": draft["trust_consumption"],
                        "visible_to_player": False,
                    })
                npc_name = next(
                    (
                        item.name
                        for item in package.npc_profiles
                        if item.npc_id == draft["npc_id"]
                    ),
                    draft["npc_id"],
                )
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="player_dialogue",
                    speaker="李致远",
                    text=draft["player_text"],
                )
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="dialogue",
                    speaker=npc_name,
                    text=turn.dialogue,
                )
                conversation.add_turn(draft["player_text"], turn.dialogue)
                if turn.conversation_state == "end":
                    session.append_narrative(
                        story_day=session.game_state.story_day,
                        kind="conversation_exit",
                        text=turn.exit_narrative or "对方结束了这次会谈。",
                    )
                    disclosed = {
                        item.get("disclosure_id")
                        for item in session.logs
                        if item.get("type") == "conversation_turn"
                        and item.get("conversation_id") == conversation.conversation_id
                        and item.get("disclosure_id")
                    }
                    if turn.disclosure_id:
                        disclosed.add(turn.disclosure_id)
                    completed = (
                        opportunity.complete_on_npc_exit
                        and conversation.turn_count >= opportunity.minimum_turns
                        and opportunity.required_disclosure_ids.issubset(disclosed)
                    )
                    if completed:
                        self._apply_opportunity_completion(
                            session, package, opportunity, append_blocks=False
                        )
                    draft["completion_status"] = (
                        "completed" if completed else "incomplete"
                    )
                    session.logs.append({
                        "type": "conversation_ended",
                        "story_day": session.game_state.story_day,
                        "opportunity_id": opportunity.opportunity_id,
                        "conversation_id": conversation.conversation_id,
                        "npc_id": draft["npc_id"],
                        "ended_by": "npc",
                        "completion_status": draft["completion_status"],
                        "cost_action_points": 0,
                        "visible_to_player": True,
                    })
                    self._complete_conversation(
                        session,
                        conversation,
                        end_reason="npc_exit",
                        completion_status=draft["completion_status"],
                    )
                    session.active_conversation = None
                # 玩家日志不记录内部 delta；权威审计适配器另行保存来源字段。
            elif draft["kind"] == "input_rejected":
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="input_guard",
                    text=draft["narrative"],
                )
                log["type"] = "input_rejected"
                log["npc_id"] = draft["npc_id"]
                log["conversation_id"] = draft["conversation_id"]
            elif draft["kind"] == "conversation_end":
                session.append_narrative(
                    story_day=session.game_state.story_day,
                    kind="conversation_exit",
                    text=draft["narrative"],
                )
                if draft["completed"]:
                    self._apply_opportunity_completion(session, package, opportunity)
                conversation = session.active_conversation
                if conversation is None:
                    raise ActionUnavailableError("进行中的会谈已丢失")
                self._complete_conversation(
                    session,
                    conversation,
                    end_reason="player_exit",
                    completion_status=draft["completion_status"],
                )
                session.active_conversation = None
                log["type"] = "conversation_ended"
                log["npc_id"] = draft["npc_id"]
                log["conversation_id"] = draft["conversation_id"]
                log["ended_by"] = "player"
                log["completion_status"] = draft["completion_status"]
            elif draft["kind"] == "overtime":
                state = session.game_state
                session.game_state = replace(
                    state,
                    action_points=state.action_points + draft["points"],
                    overtime_points_today=draft["points"],
                    overtime_used_today=True,
                    chapter_overtime_count=state.chapter_overtime_count + 1,
                )
                log.update({
                    "type": "overtime_requested",
                    "points": draft["points"],
                })
            session.logs.append(log)
            if (
                opportunity is not None
                and opportunity.completion_decision_id
                and session.active_conversation is None
            ):
                self._story_flow.present_next_decision(session, package)
        else:
            repeat_decision = False
            presented_decision = session.pending_decision
            selected_option_label = next(
                (
                    item.text
                    for item in presented_decision.options
                    if item.option_id == draft["option_id"]
                ),
                draft["option_id"],
            ) if presented_decision is not None else draft["option_id"]
            pending_context = dict(
                session.pending_decision.context if session.pending_decision else {}
            )
            if draft["decision_id"] == "dp4_04":
                if draft["option_id"] == "a":
                    pending_context["listened_once"] = True
                    repeat_decision = True
                elif draft["option_id"] == "b":
                    pending_context["talk_money_count"] = int(
                        pending_context.get("talk_money_count", 0)
                    ) + 1
                    repeat_decision = pending_context["talk_money_count"] < 3
            decision_cost = 0
            option = self._story_flow.resolve_decision(
                session,
                package,
                decision_id=draft["decision_id"],
                option_id=draft["option_id"],
                complete=not repeat_decision,
            )
            self._scripted_effects.apply(
                session,
                package,
                draft["effects"],
                source_id=f"{draft['decision_id']}:{draft['option_id']}",
                resource_authority="player_choice",
                resource_reference=(
                    f"{draft['decision_id']}:{draft['option_id']}"
                ),
            )
            if draft.get("parameters"):
                session.decision_parameters[draft["decision_id"]] = dict(
                    draft["parameters"]
                )
            session.logs.append({
                "type": "decision",
                "story_day": session.game_state.story_day,
                "decision_id": draft["decision_id"],
                "option_id": draft["option_id"],
                "visible_title": (
                    presented_decision.visible_title
                    if presented_decision is not None else ""
                ),
                "visible_prompt": (
                    presented_decision.visible_text
                    if presented_decision is not None else ""
                ),
                "visible_scene_id": (
                    presented_decision.scene_id
                    if presented_decision is not None else None
                ),
                "selected_option_label": selected_option_label,
                "cost_action_points": decision_cost,
                "visible_to_player": True,
                **(
                    {"parameters": dict(draft["parameters"])}
                    if draft.get("parameters")
                    else {}
                ),
            })
            if (
                draft["decision_id"] == "dp5_04_recovery"
                and draft["option_id"] == "a"
            ):
                session.pending_decision_queue.insert(0, "dp5_05_recovery")
            if repeat_decision:
                session.pending_decision = None
                # 重新投影同一节点的选项面；局部计数保存在待决策实例中。
                from serious_game_backend.domain.events import PendingDecision
                session.pending_decision = PendingDecision(
                    event_instance_id=f"evt_{session.session_id}_{draft['decision_id']}_repeat",
                    decision_id=draft["decision_id"],
                    option_ids=(),
                    context=pending_context,
                )
                self._story_flow._present_decision_id(
                    session, package, draft["decision_id"]
                )
            else:
                self._story_flow.present_next_decision(session, package)

    def _apply_opportunity_completion(
        self, session, package, opportunity, *, append_blocks: bool = True
    ) -> None:
        if opportunity is None:
            return
        effects = opportunity.completion_effects
        if (
            effects.metric_deltas or effects.ledger_deltas or effects.open_flags
            or effects.close_flags or effects.state_assignments
        ):
            self._scripted_effects.apply(
                session,
                package,
                effects,
                source_id=f"opportunity:{opportunity.opportunity_id}",
            )
        if (
            opportunity.completion_decision_id
            and opportunity.completion_decision_id not in session.pending_decision_queue
        ):
            session.pending_decision_queue.insert(0, opportunity.completion_decision_id)
        session.known_fact_ids.update(opportunity.completion_fact_ids)
        session.flags.update(opportunity.completion_flags)
        if append_blocks:
            self._story_flow.append_blocks(session, opportunity.completion_blocks)

    @staticmethod
    def _conversation_response(session, draft: dict) -> dict:
        active = session.active_conversation
        if active is not None:
            return {
                "conversation_id": active.conversation_id,
                "opportunity_id": active.opportunity_id,
                "npc_id": active.npc_id,
                "status": "active",
                "turn_count": active.turn_count,
            }
        return {
            "conversation_id": draft.get("conversation_id"),
            "opportunity_id": (
                draft["opportunity"].opportunity_id
                if draft.get("opportunity") is not None else None
            ),
            "npc_id": draft.get("npc_id"),
            "status": "ended",
            "ended_by": draft.get("ended_by", "player"),
            "exit_narrative": (
                draft.get("turn").exit_narrative
                if draft.get("turn") is not None else draft.get("narrative")
            ),
        }

    @staticmethod
    def _complete_conversation(
        session,
        conversation: ActiveConversation,
        *,
        end_reason: str,
        completion_status: str,
    ) -> None:
        if any(
            item.conversation_id == conversation.conversation_id
            for item in session.completed_conversations
        ):
            return
        session.completed_conversations.append(CompletedConversation(
            conversation_id=conversation.conversation_id,
            opportunity_id=conversation.opportunity_id,
            npc_id=conversation.npc_id,
            story_day=conversation.story_day,
            start_reason=conversation.start_reason,
            end_reason=end_reason,
            completion_status=completion_status,
            transcript=tuple(dict(item) for item in conversation.transcript),
            started_at=conversation.started_at,
        ))

    def _record_turn_memories(
        self,
        session,
        package,
        draft: dict,
        *,
        account_id: str,
        operation_id: str,
    ) -> None:
        turn = draft["turn"]
        npc_id = draft["npc_id"]
        common = {
            "session_id": session.session_id,
            "account_id": account_id,
            "npc_id": npc_id,
            "operation_id": operation_id,
            "story_day": session.game_state.story_day,
        }
        try:
            self._npc_memories.record(
                **common,
                candidate=turn.memory_candidate,
            )
        except Exception:
            # 记忆是可重建的软状态，不允许反向破坏已提交的权威回合。
            pass

        authoritative: list[dict] = []
        if turn.disclosure_id is not None:
            fact = package.facts.get(turn.disclosure_id)
            authoritative.append({
                "memory_type": "disclosure",
                "content": (
                    f"{fact.title}：{fact.text}"
                    if fact is not None else f"已披露事实：{turn.disclosure_id}"
                ),
                "actor_id": npc_id,
                "due_day": None,
                "resolution_state": "observed",
            })
        if turn.attitude_delta != 0 or turn.anxiety_delta != 0:
            npc_name = next(
                (
                    item.name for item in package.npc_profiles
                    if item.npc_id == npc_id
                ),
                npc_id,
            )
            authoritative.append({
                "memory_type": "relationship",
                "content": f"本次会谈使玩家与{npc_name}的关系发生了可观察变化。",
                "actor_id": npc_id,
                "due_day": None,
                "resolution_state": "observed",
            })
        for demand in package.npc_demands:
            if demand.npc_id != npc_id:
                continue
            state = session.npc_demand_states.get(demand.demand_id, {})
            status = str(state.get("status", "unknown"))
            if status not in {"discovered", "acknowledged", "committed"}:
                continue
            raw_due_day = state.get(
                "due_day", demand.satisfy.get("expires_day")
            )
            authoritative.append({
                "memory_type": "demand",
                "content": f"{demand.title}：{demand.description}",
                "actor_id": demand.npc_id,
                "due_day": (
                    int(raw_due_day) if raw_due_day is not None else None
                ),
                "resolution_state": "unresolved",
            })
        for memory in authoritative:
            try:
                self._npc_memories.record_authoritative(
                    **common,
                    **memory,
                )
            except Exception:
                # 每条权威记忆独立落库，单条失败不能阻断已提交的游戏动作。
                continue

    def _owned_session(self, session_id: str, account_id: str):
        session = self._sessions.get_owned(session_id, account_id)
        if session is None:
            raise NotFoundError("游戏不存在")
        return session

    @staticmethod
    def _validate_allocation(decision, parameters: dict) -> dict[str, int]:
        schema = decision.input_schema
        fields = tuple(schema.get("fields", []))
        total = int(schema.get("total", 0))
        values = parameters.get("allocations", parameters)
        if not isinstance(values, dict) or set(values) != set(fields):
            raise ActionUnavailableError(
                "分配题必须提交全部去向",
                details={"required_fields": list(fields)},
            )
        if any(type(values[item]) is not int or values[item] < 0 for item in fields):
            raise ActionUnavailableError("分配额度必须是非负整数")
        normalized = {item: int(values[item]) for item in fields}
        if sum(normalized.values()) != total:
            raise ActionUnavailableError(
                "分配总额不正确",
                details={"required_total": total, "actual_total": sum(normalized.values())},
            )
        return normalized

    @staticmethod
    def _dp2_10_allocation_effects(
        allocations: dict[str, int], base_option
    ) -> ScriptedEffects:
        if set(allocations) != {
            "signing_compensation",
            "livelihood_support",
            "environmental_retest",
            "emergency_stability",
        }:
            raise ActionUnavailableError("当前分配题字段与剧本不一致")
        total = sum(allocations.values())
        uniform_quarter = len(set(allocations.values())) == 1
        values = {
            "signing_compensation": {
                "public_trust": (0, -1, -2),
                "social_stability": (1, 2, 2),
                "env_clue": (0, -2, -3),
            },
            "livelihood_support": {
                "public_trust": (3, 5, 6),
                "social_stability": (2, 3, 4),
            },
            "environmental_retest": {
                "env_clue": (4, 6, 8),
                "social_stability": (0, -1, -2),
            },
            "emergency_stability": {
                "public_trust": (),
                "social_stability": (3, 5, 6),
                "media_pressure": (-2, -4, -5),
                "env_clue": (0, 1, 2),
            },
        }
        deltas: dict[str, int] = {}
        for field, amount in allocations.items():
            if amount == 0:
                continue
            ratio = amount / total
            if uniform_quarter or ratio < 0.25:
                band = 0
            elif ratio < 0.5:
                band = 1
            else:
                band = 2
            for metric, bands in values[field].items():
                if not bands:
                    continue
                deltas[metric] = deltas.get(metric, 0) + bands[band]
        return ScriptedEffects(
            metric_deltas={key: (value, value) for key, value in deltas.items()},
            ledger_deltas=base_option.effects.ledger_deltas,
            open_flags=base_option.effects.open_flags,
            close_flags=base_option.effects.close_flags,
        )

    @staticmethod
    def _effective_effects(
        option,
        flags: set[str],
        state_values: dict[str, str] | None = None,
        ledger_values: dict[str, int] | None = None,
        context: dict | None = None,
        *,
        decision_id: str = "",
        known_fact_ids: set[str] | None = None,
    ) -> ScriptedEffects:
        state_values = state_values or {}
        ledger_values = ledger_values or {}
        context = context or {}
        metric_deltas = dict(option.effects.metric_deltas)
        ledger_deltas = dict(option.effects.ledger_deltas)
        open_flags = set(option.effects.open_flags)
        close_flags = set(option.effects.close_flags)
        state_assignments = dict(option.effects.state_assignments)
        for branch in option.conditional_effects:
            if not branch.matches(flags, state_values, ledger_values, known_fact_ids):
                continue
            if branch.replace_base:
                metric_deltas = {}
                ledger_deltas = {}
                open_flags = set()
                close_flags = set()
                state_assignments = {}
            for field, delta in branch.effects.metric_deltas.items():
                current = metric_deltas.get(field, (0, 0))
                metric_deltas[field] = (
                    current[0] + delta[0], current[1] + delta[1]
                )
            for field, delta in branch.effects.ledger_deltas.items():
                current = ledger_deltas.get(field, (0, 0))
                ledger_deltas[field] = (
                    current[0] + delta[0], current[1] + delta[1]
                )
            open_flags.update(branch.effects.open_flags)
            close_flags.update(branch.effects.close_flags)
            state_assignments.update(branch.effects.state_assignments)
        if decision_id == "dp4_04" and option.option_id == "c" and not (
            int(context.get("talk_money_count", 0)) == 0
            and "周家祖坟事由已知" in flags
        ):
            metric_deltas = {"public_trust": (2, 2)}
            ledger_deltas = {}
            open_flags = {"迁坟条件待议"}
            close_flags = set()
            state_assignments = {}
        if decision_id == "dp6_10":
            attitudes = {"蒋崇岳背书", "蒋崇岳默许", "蒋崇岳弃保", "蒋崇岳否决"}
            open_flags.difference_update(attitudes)
            close_flags.difference_update(attitudes)
            public_agenda = bool({"环评已处理", "账目揭发"} & flags)
            endorsed = "蒋崇岳背书" in flags
            if public_agenda and not endorsed:
                open_flags.add("蒋崇岳否决")
                close_flags.update(attitudes - {"蒋崇岳否决"})
                close_flags.add("环评已处理")
            elif endorsed and option.option_id == "c":
                open_flags.add("蒋崇岳弃保")
                close_flags.update(attitudes - {"蒋崇岳弃保"})
        open_flags.difference_update(close_flags)
        return ScriptedEffects(
            metric_deltas=metric_deltas,
            ledger_deltas=ledger_deltas,
            open_flags=frozenset(open_flags),
            close_flags=frozenset(close_flags),
            state_assignments=state_assignments,
        )

    @staticmethod
    def _ledger_values(session) -> dict[str, int]:
        return {
            "budget_remaining": session.game_state.budget_remaining,
            "signed_households": session.game_state.signed_households,
            "reported_signed_households": session.game_state.reported_signed_households,
            "chapter_overtime_count": session.game_state.chapter_overtime_count,
        }

    @staticmethod
    def _validate_write_gate(session, command: ActionCommand) -> None:
        if session.status is not SessionStatus.ACTIVE:
            raise SessionEndedError("当前游戏不可继续写入")
        if session.processing_action_id is not None:
            raise SessionBusyError("当前游戏正在处理另一个动作")
        if (
            session.active_conversation is not None
            and command.input_mode not in {
                ActionInputMode.FREE_TEXT, ActionInputMode.CONVERSATION_END
            }
        ):
            raise ActionUnavailableError("会谈正在进行，请先继续或结束当前会谈")
        if (
            session.active_conversation is None
            and command.input_mode in {
                ActionInputMode.FREE_TEXT, ActionInputMode.CONVERSATION_END
            }
        ):
            raise ActionUnavailableError("当前没有进行中的会谈")
        if (
            session.pending_decision is not None
            and command.input_mode is not ActionInputMode.DECISION
        ):
            raise DecisionRequiredError("必须先处理当前决策")
        if session.state_version != command.state_version:
            raise StateVersionConflictError(
                "状态版本已变化，请刷新后重试",
                details={"current_state_version": session.state_version},
            )
