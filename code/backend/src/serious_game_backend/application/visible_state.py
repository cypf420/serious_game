"""内部权威状态到玩家可见 DTO 的唯一投影入口。"""

from __future__ import annotations

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import MetricBand, ScriptPackage
from serious_game_backend.application.npc_demand_service import NPCDemandService
from serious_game_backend.application.progress_broadcast_policy import (
    progress_broadcast,
)


VISIBLE_INDICATORS = (
    "public_trust",
    "social_stability",
    "political_credit",
    "media_pressure",
    "cadre_discontent",
)

STRUCTURED_DECISION_LABELS = {
    "dp2_08": {
        "a": "A·签约攻坚线：人手、资金和时间优先用于逐户协商。",
        "b": "B·反腐查案线：追查发票、关联公司与工程款去向。",
        "c": "C·环评真相线：复核三年数据并调查上游冶炼厂。",
        "d": "D·民生维稳线：优先处理信访、体检和安置诉求。",
    },
}


class VisibleStateProjector:
    def project(self, session: GameSession, package: ScriptPackage) -> dict:
        state = session.game_state
        indicators = {
            key: self._label(package.metric_bands[key], getattr(state, key))
            for key in VISIBLE_INDICATORS
        }
        pending = None
        if session.pending_decision is not None:
            input_schema = dict(session.pending_decision.input_schema or {})
            labels = STRUCTURED_DECISION_LABELS.get(session.pending_decision.decision_id)
            if labels:
                input_schema["labels"] = labels
            pending = {
                "event_instance_id": session.pending_decision.event_instance_id,
                "decision_id": session.pending_decision.decision_id,
                "option_ids": list(session.pending_decision.option_ids),
                "options": [
                    {
                        "option_id": item.option_id,
                        "text": item.text,
                        "available": item.available,
                        "unavailable_reason": item.unavailable_reason,
                    }
                    for item in session.pending_decision.options
                ],
                "title": session.pending_decision.visible_title,
                "text": session.pending_decision.visible_text,
                "scene_id": session.pending_decision.scene_id,
                "input_kind": session.pending_decision.input_kind,
                "input_schema": input_schema or None,
                "presentation_entry_id": (
                    session.pending_decision.presentation_entry_id
                ),
            }
        return {
            "session_id": session.session_id,
            "state_version": session.state_version,
            "status": session.status.value,
            "onboarding": {
                "free_action_completed": any(
                    item.status == "completed" for item in session.governance_actions.values()
                ),
            },
            "story": {
                "day": state.story_day,
                "chapter": package.chapter_for(state.story_day),
                "cost_tier": package.action_cost_tier(state.story_day).value,
                "beat_id": session.story_beat_id,
                "origin": {
                    "origin_id": session.origin_id,
                    "title": package.origins[session.origin_id].title,
                },
            },
            "ledger": {
                "days_left": state.days_left,
                "action_points": {
                    "remaining": state.action_points,
                    "daily_cap": state.daily_action_point_cap,
                    "overtime_available": (
                        state.action_points == 0
                        and not state.overtime_used_today
                        and state.chapter_overtime_count < 3
                        and state.fatigue < 75
                    ),
                    "chapter_overtime_remaining": max(
                        0, 3 - state.chapter_overtime_count
                    ),
                },
                "signed_households": {
                    "signed": state.signed_households,
                    "total": state.total_households,
                    "batches": session.signing_batch_summary(),
                },
                "budget": {
                    "remaining": state.budget_remaining,
                    "base_authorized": state.budget_base_authorized,
                    "approved_adjustments": state.budget_approved_adjustments,
                    "committed": state.budget_committed,
                    "paid": state.budget_paid,
                    "precoord_suspense": state.budget_precoord_suspense,
                    "unit": state.budget_unit,
                },
                "fatigue": {
                    "label": self._fatigue_label(state.fatigue),
                },
            },
            "indicators": indicators,
            "progress_broadcast": progress_broadcast(session),
            "npc_demands": NPCDemandService.public(session, package),
            "pending_decision": pending,
            "active_conversation": (
                {
                    "conversation_id": session.active_conversation.conversation_id,
                    "opportunity_id": session.active_conversation.opportunity_id,
                    "npc_id": session.active_conversation.npc_id,
                    "turn_count": session.active_conversation.turn_count,
                    "quoted_cost": session.active_conversation.quoted_cost,
                    "cost_charged": session.active_conversation.cost_charged,
                }
                if session.active_conversation is not None else None
            ),
            "active_group_conversation": (
                {
                    "conversation_id": (
                        session.active_group_conversation.conversation_id
                    ),
                    "conversation_type": (
                        session.active_group_conversation.conversation_type
                    ),
                    "followup_plan_id": (
                        session.active_group_conversation.followup_plan_id
                    ),
                    "initiator_npc_id": (
                        session.active_group_conversation.initiator_npc_id
                    ),
                    "participant_ids": list(
                        session.active_group_conversation.participant_ids
                    ),
                    "agenda": session.active_group_conversation.agenda,
                    "demands": list(
                        session.active_group_conversation.demands
                    ),
                     "urgency": session.active_group_conversation.urgency,
                     "phase": session.active_group_conversation.phase,
                     "dialogue_mode": (
                         "followup"
                         if (
                             session.active_group_conversation.phase == "resolved"
                             or session.active_group_conversation.status == "resolved"
                         )
                         else "persuasion"
                     ),
                    "participant_states": [
                        {
                            "npc_id": npc_id,
                            "status": state.get("status", "active"),
                            "public_summary": state.get(
                                "public_summary", "仍在追问"
                            ),
                        }
                        for npc_id, state in (
                            session.active_group_conversation.participant_states.items()
                        )
                    ],
                    "closure_summary": (
                        session.active_group_conversation.closure_summary
                    ),
                    "transcript": list(
                        session.active_group_conversation.transcript
                    ),
                    "queued_count": len(session.group_conversation_queue),
                }
                if session.active_group_conversation is not None else None
            ),
            "visible_events": [
                {
                    "event_id": item.event_id,
                    "story_day": item.story_day,
                    "title": item.title,
                    "summary": item.summary,
                }
                for item in session.visible_events[-20:]
            ],
            "ending": session.ending_result,
        }

    @staticmethod
    def _label(bands: tuple[MetricBand, ...], value: int) -> str:
        matches = [band.label for band in bands if band.minimum <= value <= band.maximum]
        if len(matches) != 1:
            raise ValueError(f"visible metric value {value} has no unique band")
        return matches[0]

    @staticmethod
    def _fatigue_label(value: int) -> str:
        if value >= 75:
            return "撑不住了"
        if value >= 50:
            return "有些吃力"
        if value >= 25:
            return "略显疲乏"
        return "精神尚可"
