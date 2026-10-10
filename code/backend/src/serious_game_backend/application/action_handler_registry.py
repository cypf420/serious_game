from __future__ import annotations

from dataclasses import replace

from serious_game_backend.application.scripted_effect_service import ScriptedEffectService
from serious_game_backend.domain.action import ActionQuote, ResourceActionDefinition
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


class ActionHandlerRegistry:
    SUPPORTED = frozenset({
        "deterministic_analysis", "resource_dispatch", "policy_adjustment",
        "group_scene", "legal_procedure",
    })

    def __init__(self, scripted_effects: ScriptedEffectService) -> None:
        self._scripted_effects = scripted_effects

    def execute(
        self,
        session: GameSession,
        package: ScriptPackage,
        definition: ResourceActionDefinition,
        quote: ActionQuote,
        *,
        source_reference: str,
    ) -> str:
        if definition.executor_kind not in self.SUPPORTED:
            raise ContentValidationError(
                f"资源动作没有已注册处理器：{definition.executor_kind}"
            )
        if quote.budget_cost:
            state = session.game_state
            session.game_state = replace(
                state,
                budget_remaining=state.budget_remaining - quote.budget_cost,
                budget_committed=state.budget_committed + quote.budget_cost,
                budget_paid=state.budget_paid + quote.budget_cost,
            )
            session.resource_ledger_entries.append({
                "entry_id": (
                    f"resource:{state.story_day}:"
                    f"{len(session.resource_ledger_entries) + 1}"
                ),
                "story_day": state.story_day,
                "change_kind": "payment",
                "source_type": "player_action",
                "source_id": source_reference,
                "action_id": definition.action_id,
                "resource_id": "budget_remaining",
                "delta": -quote.budget_cost,
                "before": state.budget_remaining,
                "after": state.budget_remaining - quote.budget_cost,
                "payment_status": "paid",
            })
        self._scripted_effects.apply(
            session,
            package,
            definition.effects,
            source_id=f"resource_action:{definition.action_id}",
            resource_authority="player_action",
            resource_reference=source_reference,
        )
        newly_learned = definition.result_fact_ids - session.known_fact_ids
        session.known_fact_ids.update(definition.result_fact_ids)
        for fact_id in sorted(newly_learned):
            session.logs.append({
                "type": "fact_learned",
                "story_day": session.game_state.story_day,
                "fact_id": fact_id,
                "source_id": definition.action_id,
                "visible_to_player": True,
            })
        return definition.narrative or "行动已按登记程序提交，后续结果将进入本局记录。"
