from __future__ import annotations

from dataclasses import asdict
from threading import Event
from typing import Callable

from serious_game_backend.application.package_lock import require_locked_package
from serious_game_backend.application.input_review_service import (
    InputReviewService,
    input_rejection_message,
)
from serious_game_backend.application.stream_lifecycle import (
    StreamCancelCallback,
    StreamCancelled,
    ensure_stream_open,
    wait_for_stream_ack,
)
from serious_game_backend.application.disclosure_gate_service import DisclosureGateService
from serious_game_backend.application.night_turn_safety import validate_night_turn_result
from serious_game_backend.application.turn_operation_lease import (
    TurnLease,
    TurnOperationLeaseService,
)
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    RoleLLMGateway,
    RuntimeTransactionRepository,
    ScriptPackageRepository,
)
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.application.npc_demand_service import NPCDemandService
from serious_game_backend.application.npc_memory_service import NPCMemoryService
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.llm import NightAgentContext


class GroupConversationService:
    def __init__(
        self,
        sessions: GameSessionRepository,
        packages: ScriptPackageRepository,
        gateway: RoleLLMGateway,
        projector: VisibleStateProjector,
        input_review: InputReviewService,
        operations: OperationRepository,
        transactions: RuntimeTransactionRepository,
        disclosure_gate: DisclosureGateService | None = None,
        npc_memories: NPCMemoryService | None = None,
    ) -> None:
        self._sessions = sessions
        self._packages = packages
        self._gateway = gateway
        self._projector = projector
        self._input_review = input_review
        self._leases = TurnOperationLeaseService(sessions, operations, transactions)
        self._disclosure_gate = disclosure_gate or DisclosureGateService()
        self._npc_memories = npc_memories

    def reply(
        self,
        *,
        account_id: str,
        session_id: str,
        state_version: int,
        player_text: str,
        client_action_id: str | None = None,
        retry: bool = False,
        stream_event: Callable[[dict], None] | None = None,
        stream_cancelled: StreamCancelled = None,
        stream_cancel_register: Callable[[StreamCancelCallback], None] | None = None,
    ) -> dict:
        text = player_text.strip()
        if not text:
            raise ActionUnavailableError("群组会谈回应不能为空")
        key = client_action_id or self._leases.legacy_client_action_id({
            "kind": "group_conversation_turn",
            "state_version": state_version,
            "player_text": text,
        })
        reserved = self._leases.reserve(
            account_id=account_id,
            session_id=session_id,
            client_action_id=key,
            state_version=state_version,
            request_payload={
                "kind": "group_conversation_turn",
                "state_version": state_version,
                "player_text": text,
            },
            retry=retry,
            stream_cancel_register=stream_cancel_register,
        )
        if isinstance(reserved, dict):
            return reserved
        lease: TurnLease = reserved
        session = lease.session
        created_memory_ids: list[str] = []
        committed = False
        try:
            conversation = session.active_group_conversation
            if conversation is None:
                raise ActionUnavailableError("当前没有强制群组会谈")
            if conversation.status == "completed":
                raise ActionUnavailableError("本场会谈已经结束")
            # A resolved conversation remains open for optional, ordinary
            # follow-up dialogue until the player explicitly finishes it.
            # Older snapshots may have persisted the resolved status while
            # omitting the newer phase field, so accept both representations.
            followup_mode = (
                conversation.phase == "resolved"
                or conversation.status == "resolved"
            )
            if conversation.phase not in {"active", "resolved"} and not followup_mode:
                raise ActionUnavailableError("本场会谈当前不能继续")
            if followup_mode:
                conversation.phase = "resolved"
            package = require_locked_package(self._packages, session)
            if stream_event is not None:
                stream_event({"type": "npc_thinking_start", "stream_id": "group:review",
                              "npc_name": "在场各方（正在理解你的发言）"})
            relevant, review_reason = self._input_review.review(
                session,
                operation_id=(
                    f"group:{session.session_id}:{conversation.conversation_id}:"
                    f"input-review:{conversation.turn_count + 1}"
                ),
                player_text=text,
                scene_goal=(
                    conversation.agenda
                    if not followup_mode else
                    f"{conversation.agenda}；会后与在场人物保持符合其身份的日常交流，"
                    "不改变本场会谈的结论"
                ),
            )
            ensure_stream_open(stream_cancelled)
            if stream_event is not None:
                stream_event({"type": "npc_thinking_end", "stream_id": "group:review"})
            if not relevant:
                session.logs.append({
                    "type": "unrelated_input_rejected",
                    "scene_type": "forced_group_conversation",
                    "scene_id": conversation.conversation_id,
                    "story_day": session.game_state.story_day,
                    "reason": review_reason,
                    "visible_to_player": False,
                })
                if not followup_mode:
                    NPCDemandService.sync(session, package)
                return self._leases.complete(lease, lambda committed: {
                    "completed": False,
                    "input_rejected": True,
                    "resolved": followup_mode,
                    "dialogue_mode": (
                        "followup" if followup_mode else "persuasion"
                    ),
                    "message": input_rejection_message(review_reason),
                    "turn_dialogues": [],
                    "visible_state": self._projector.project(committed, package),
                })
            profiles = {item.npc_id: item for item in package.npc_profiles}
            boundary = self._disclosure_gate.session_boundary(session, package)
            conversation.add_player_turn(text)
            turn_dialogues: list[dict] = []
            memory_candidates: list[tuple[str, str, str]] = []
            ordered_participants = tuple(
                npc_id for npc_id in conversation.participant_ids
                if npc_id != conversation.initiator_npc_id
            ) + (conversation.initiator_npc_id,)
            for npc_id in ordered_participants:
                profile = profiles.get(npc_id)
                if profile is None:
                    continue
                state = conversation.participant_states[npc_id]["status"]
                other_ids = tuple(
                    item for item in conversation.participant_ids
                    if item != npc_id
                )
                all_others_settled = all(
                    conversation.participant_states[item]["status"] == "settled"
                    for item in other_ids
                )
                allowed_dialogue_acts = (
                    ("followup",)
                    if followup_mode else
                    ("press", "challenge", "soften", "settle", "reopen")
                )
                if (
                    not followup_mode
                    and npc_id == conversation.initiator_npc_id
                    and all_others_settled
                ):
                    allowed_dialogue_acts += ("close",)
                memory_context = (
                    self._npc_memories.context(
                        session_id=session.session_id,
                        npc_id=npc_id,
                        story_day=session.game_state.story_day,
                        query=f"{conversation.agenda} {text}",
                    )
                    if self._npc_memories is not None else {
                        "memory_items": (),
                        "unresolved_commitments": (),
                    }
                )
                guidance = conversation.participant_guidance.get(npc_id, {})
                thinking_id = f"group:{conversation.turn_count + 1}:{npc_id}"
                if stream_event is not None:
                    stream_event({"type": "npc_thinking_start", "stream_id": thinking_id,
                                  "npc_id": npc_id, "npc_name": profile.name})
                raw_result = self._gateway.run_night_turn(NightAgentContext(
                    session_id=session.session_id,
                    account_id=session.account_id,
                    operation_id=(
                        f"group:{session.session_id}:{conversation.conversation_id}:"
                        f"{conversation.turn_count + 1}:{npc_id}"
                    ),
                    story_day=session.game_state.story_day,
                    scene_id=conversation.conversation_id,
                    phase=(
                        "resolved_group_followup"
                        if followup_mode else "player_group_dialogue"
                    ),
                    npc_id=npc_id,
                    npc_name=profile.name,
                    role_setting=profile.role_setting,
                    big_five=(
                        profile.big_five.as_dict() if profile.big_five else {}
                    ),
                    counterpart_ids=other_ids,
                    counterpart_names={item: profiles[item].name for item in other_ids if item in profiles},
                    counterpart_roles={
                        item: profiles[item].role_setting.splitlines()[0].lstrip("# ")
                        for item in other_ids if item in profiles and profiles[item].role_setting.strip()
                    },
                    transcript=tuple(conversation.transcript),
                    round_index=conversation.turn_count + 1,
                    scene_goal=conversation.agenda,
                    private_context=(
                        f"本场背景：{conversation.persuasion_context}\n"
                        f"本角色判断参考：{guidance}"
                        + (
                            "\n本场会谈已经收束；本次只是会后补充交流，"
                            "不得重新开启追问、改变会谈结论或兑现任何承诺。"
                            if followup_mode else ""
                        )
                    ),
                    public_expression_context=(
                        f"当前公开议题：{conversation.agenda}；"
                        f"当前会谈状态：{state}"
                        + (
                            "；模式：会后补充交流，不改变收束状态"
                            if followup_mode else ""
                        )
                    ),
                    allowed_topics=tuple(conversation.demands),
                    player_text=text,
                    memory_items=tuple(memory_context["memory_items"]),
                    unresolved_commitments=tuple(
                        memory_context["unresolved_commitments"]
                    ),
                    relationship_context=(
                        NPCRelationshipService.relationship_context(
                            session, npc_id
                        )
                    ),
                    participant_state=("settled" if followup_mode else state),
                    allowed_dialogue_acts=allowed_dialogue_acts,
                    all_other_participants_settled=all_others_settled,
                    forbidden_disclosure_markers=tuple(
                        signature
                        for signatures in boundary.forbidden_fact_signatures.values()
                        for signature in signatures
                    ),
                    model_id="",
                ))
                ensure_stream_open(stream_cancelled)
                if stream_event is not None:
                    stream_event({"type": "npc_thinking_end", "stream_id": thinking_id,
                                  "npc_id": npc_id, "npc_name": profile.name})
                result = validate_night_turn_result(
                    raw_result,
                    expected_npc_id=npc_id,
                    forbidden_fact_signatures=boundary.forbidden_fact_signatures,
                    # This field records the player's own unverified claim for
                    # later consistency checks.  It is private memory, not an
                    # NPC disclosure; players must remain free to bluff about
                    # facts they have not established.
                    allow_unverified_memory_claims=True,
                )
                if followup_mode:
                    # Follow-up dialogue is deliberately not a persuasion
                    # state transition.  The original settled states and
                    # resolved phase remain authoritative.
                    dialogue_act = "followup"
                else:
                    dialogue_act = result.dialogue_act or "press"
                    if dialogue_act not in allowed_dialogue_acts:
                        raise ActionUnavailableError("角色模型返回了当前不可用的会谈动作")
                    if dialogue_act == "close" and not (
                        npc_id == conversation.initiator_npc_id
                        and all_others_settled
                        and result.topic_settled
                    ):
                        raise ActionUnavailableError("发起人尚不能结束本场会谈")
                    if dialogue_act in {"settle", "close"} and result.topic_settled:
                        next_state = "settled"
                        public_summary = "暂时接受，仍在旁听"
                    elif dialogue_act == "soften":
                        next_state = "wavering"
                        public_summary = "态度有所动摇，仍在考虑"
                    else:
                        next_state = "active"
                        public_summary = (
                            "发现新矛盾，重新追问"
                            if dialogue_act == "reopen" else "仍在追问"
                        )
                    conversation.participant_states[npc_id] = {
                        "status": next_state,
                        "public_summary": public_summary,
                    }
                if result.dialogue:
                    conversation.add_npc_turn(
                        npc_id=npc_id,
                        npc_name=profile.name,
                        model_id=result.model_id,
                        text=result.dialogue,
                        dialogue_act=dialogue_act,
                        stance=result.stance or "guarded",
                    )
                    conversation.transcript[-1]["dialogue_mode"] = (
                        "followup" if followup_mode else "persuasion"
                    )
                    turn_dialogues.append({
                        "npc_id": npc_id,
                        "npc_name": profile.name,
                        "model_id": result.model_id,
                        "text": result.dialogue,
                        "dialogue_act": dialogue_act,
                        "dialogue_mode": (
                            "followup" if followup_mode else "persuasion"
                        ),
                        "stance": result.stance or "guarded",
                    })
                if result.memory_candidate:
                    memory_candidates.append((
                        npc_id,
                        result.memory_candidate,
                        f"{lease.operation.operation_id}:{npc_id}",
                    ))
            ensure_stream_open(stream_cancelled)
            conversation.turn_count += 1
            resolved = followup_mode
            if not followup_mode:
                resolved = all(
                    item["status"] == "settled"
                    for item in conversation.participant_states.values()
                ) and any(
                    item.get("speaker_type") == "npc"
                    and item.get("npc_id") == conversation.initiator_npc_id
                    and item.get("dialogue_act") == "close"
                    for item in reversed(conversation.transcript)
                )
                if resolved:
                    conversation.phase = "resolved"
                    conversation.closure_summary = (
                        "发起人确认在场人物暂时停止追问；这不代表承诺已经兑现。"
                    )
            if self._npc_memories is not None:
                for npc_id, candidate, operation_id in memory_candidates:
                    memory = self._npc_memories.record(
                        session_id=session.session_id,
                        account_id=session.account_id,
                        npc_id=npc_id,
                        operation_id=operation_id,
                        story_day=session.game_state.story_day,
                        candidate=candidate,
                    )
                    if memory is not None:
                        conversation.memory_ids.append(memory.memory_id)
                        created_memory_ids.append(memory.memory_id)
            if not followup_mode:
                NPCDemandService.sync(session, package)
            response = self._leases.complete(lease, lambda committed: {
                "completed": False,
                "resolved": resolved,
                "dialogue_mode": (
                    "followup" if followup_mode else "persuasion"
                ),
                "input_rejected": False,
                "turn_dialogues": turn_dialogues,
                "visible_state": self._projector.project(committed, package),
            })
            committed = True
            self._emit_committed_replies(
                turn_dialogues, stream_event, stream_cancelled
            )
            return response
        except Exception as exc:
            if (
                not committed
                and created_memory_ids
                and self._npc_memories is not None
            ):
                self._npc_memories.invalidate(tuple(created_memory_ids))
            self._leases.fail(lease, exc)
            raise

    def finish(
        self,
        *,
        account_id: str,
        session_id: str,
        state_version: int,
        client_action_id: str,
        retry: bool = False,
    ) -> dict:
        reserved = self._leases.reserve(
            account_id=account_id,
            session_id=session_id,
            client_action_id=client_action_id,
            state_version=state_version,
            request_payload={
                "kind": "group_conversation_finish",
                "state_version": state_version,
            },
            retry=retry,
        )
        if isinstance(reserved, dict):
            return reserved
        lease: TurnLease = reserved
        session = lease.session
        try:
            conversation = session.active_group_conversation
            if conversation is None:
                raise ActionUnavailableError("当前没有强制群组会谈")
            if conversation.phase != "resolved" and conversation.status != "resolved":
                raise ActionUnavailableError("在场人物尚未停止追问")
            # Normalize older snapshots before archiving them.
            conversation.phase = "resolved"
            package = require_locked_package(self._packages, session)
            conversation.status = "completed"
            session.completed_group_conversations.append(asdict(conversation))
            session.logs.append({
                "type": "forced_group_conversation_completed",
                "conversation_id": conversation.conversation_id,
                "conversation_type": conversation.conversation_type,
                "story_day": session.game_state.story_day,
                "participant_ids": list(conversation.participant_ids),
                "visible_to_player": True,
            })
            session.active_group_conversation = None
            if session.group_conversation_queue:
                session.active_group_conversation = session.group_conversation_queue.pop(0)
                session.active_group_conversation.status = "active"
                session.active_group_conversation.phase = "active"
            NPCDemandService.sync(session, package)
            return self._leases.complete(lease, lambda committed: {
                "completed": True,
                "visible_state": self._projector.project(committed, package),
            })
        except Exception as exc:
            self._leases.fail(lease, exc)
            raise

    @staticmethod
    def _emit_committed_replies(
        replies: list[dict],
        stream_event: Callable[[dict], None] | None,
        stream_cancelled: StreamCancelled,
    ) -> None:
        if stream_event is None:
            return
        for reply in replies:
            identity = {
                "stream_id": f"{reply['npc_id']}:committed",
                "npc_id": reply["npc_id"],
                "npc_name": reply["npc_name"],
                "dialogue_mode": reply.get("dialogue_mode", "persuasion"),
            }
            stream_event({"type": "npc_thinking_start", **identity})
            stream_event({"type": "npc_thinking_end", **identity})
            acknowledged = Event()
            stream_event({
                "type": "_npc_reply_ready",
                "reply": reply,
                "acknowledged": acknowledged,
            })
            wait_for_stream_ack(acknowledged, stream_cancelled)
