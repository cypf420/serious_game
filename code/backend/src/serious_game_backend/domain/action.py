from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from serious_game_backend.domain.enums import ActionCostTier, ActionInputMode
from serious_game_backend.domain.story import ScriptedEffects


@dataclass(frozen=True, slots=True)
class ActionRule:
    action_id: str
    name: str
    category: str
    effect_type: str
    costs: dict[ActionCostTier, int]
    daily_cap: int | None = None
    half_day: bool = False
    hard_force: bool = False
    precondition_flags_any: tuple[str, ...] = ()

    def cost_for(self, tier: ActionCostTier) -> int:
        return self.costs[tier]


@dataclass(frozen=True, slots=True)
class ResourceActionDefinition:
    """不依赖 NPC 会谈的确定性资源动作定义。"""

    action_id: str
    executor_kind: str
    enabled: bool = True
    unavailable_reason: str | None = None
    unlock_day: int = 1
    target_schema: dict[str, Any] = field(default_factory=dict)
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    budget_cost: int = 0
    resource_ids: tuple[str, ...] = ()
    location_ids: tuple[str, ...] = ()
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    effects: ScriptedEffects = field(default_factory=ScriptedEffects)
    result_fact_ids: frozenset[str] = frozenset()
    narrative: str = ""


@dataclass(frozen=True, slots=True)
class ActionQuote:
    quote_id: str
    state_version: int
    action_id: str
    target_ids: tuple[str, ...]
    parameters: dict[str, Any]
    action_point_cost: int
    budget_cost: int
    budget_unit: str
    executor_kind: str
    resource_ids: tuple[str, ...]
    cost_reasons: tuple[str, ...] = ()
    base_action_point_cost: int = 0
    friction_action_point_cost: int = 0
    discount_action_point_cost: int = 0


@dataclass(frozen=True, slots=True)
class ActionCommand:
    input_mode: ActionInputMode
    client_action_id: str
    state_version: int
    action_id: str | None = None
    opportunity_id: str | None = None
    player_text: str | None = None
    target_npc_id: str | None = None
    target_ids: tuple[str, ...] = ()
    quote_id: str | None = None
    conversation_id: str | None = None
    decision_id: str | None = None
    option_id: str | None = None
    ordered_option_ids: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    retry: bool = False
    reference_ids: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, Any]:
        # retry 是传输控制位，不属于业务请求；否则同一次可重试失败无法保持相同 hash。
        return {
            "input_mode": self.input_mode.value,
            "client_action_id": self.client_action_id,
            "state_version": self.state_version,
            "action_id": self.action_id,
            "opportunity_id": self.opportunity_id,
            "player_text": self.player_text,
            "target_npc_id": self.target_npc_id,
            "target_ids": list(self.target_ids),
            "quote_id": self.quote_id,
            "conversation_id": self.conversation_id,
            "decision_id": self.decision_id,
            "option_id": self.option_id,
            "ordered_option_ids": list(self.ordered_option_ids),
            "parameters": self.parameters,
            # Preserve hashes of existing/legacy requests without attachments.
            **({"reference_ids": list(self.reference_ids)} if self.reference_ids else {}),
        }
