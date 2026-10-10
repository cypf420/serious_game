from __future__ import annotations

import hashlib
import json

from serious_game_backend.domain.action import ActionQuote
from serious_game_backend.domain.errors import (
    ActionUnavailableError,
    InsufficientActionPointsError,
)
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.application.resource_availability import (
    unencumbered_budget,
)


class ActionQuoteService:
    """生成可重算的执行前报价；quote_id 绑定状态版本和完整请求。"""

    def quote(
        self,
        session: GameSession,
        package: ScriptPackage,
        *,
        action_id: str,
        target_ids: tuple[str, ...],
        parameters: dict,
    ) -> ActionQuote:
        rule = package.action_rules.get(action_id)
        definition = package.resource_actions.get(action_id)
        if rule is None or definition is None:
            raise ActionUnavailableError("该工具没有登记资源动作处理器")
        if definition.executor_kind == "conversation":
            raise ActionUnavailableError("该工具必须从人物会谈入口执行")
        if not definition.enabled:
            raise ActionUnavailableError(
                definition.unavailable_reason or "该工具当前不可执行"
            )
        if session.game_state.story_day < definition.unlock_day:
            raise ActionUnavailableError(
                definition.unavailable_reason or f"第 {definition.unlock_day} 日后开放"
            )
        if not definition.required_flags.issubset(session.flags):
            raise ActionUnavailableError("行动所需前置材料尚未齐备")
        if definition.required_any_flags and not (
            definition.required_any_flags & session.flags
        ):
            raise ActionUnavailableError("行动所需前置材料尚未齐备")
        if definition.forbidden_flags & session.flags:
            raise ActionUnavailableError("当前局势已经关闭该行动")
        self._validate_targets(definition.target_schema, target_ids)
        allowed_targets = self._allowed_target_ids(
            session, package, action_id, definition.target_schema
        )
        if target_ids and not set(target_ids).issubset(allowed_targets):
            raise ActionUnavailableError("行动包含当前存档尚不可用的对象")
        self._validate_parameters(definition.parameter_schema, parameters)
        state = session.game_state
        if rule.daily_cap is not None and (
            state.daily_action_counts.get(action_id, 0) >= rule.daily_cap
        ):
            raise ActionUnavailableError("该行动已达到今日次数上限")
        if rule.half_day and state.half_day_action_used:
            raise ActionUnavailableError("今日半日行程已经占用")
        cost = rule.cost_for(package.action_cost_tier(state.story_day))
        if state.action_points < cost:
            raise InsufficientActionPointsError(
                "当日行动点不足",
                details={"required": cost, "remaining": state.action_points},
            )
        spendable_budget = unencumbered_budget(session)
        if spendable_budget < definition.budget_cost:
            raise ActionUnavailableError(
                "当前未被合同或文件占用的预算不足",
                details={
                    "required": definition.budget_cost,
                    "remaining": spendable_budget,
                    "ledger_remaining": state.budget_remaining,
                },
            )
        canonical = {
            "session_id": session.session_id,
            "state_version": session.state_version,
            "action_id": action_id,
            "target_ids": list(target_ids),
            "parameters": parameters,
            "action_point_cost": cost,
            "budget_cost": definition.budget_cost,
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:32]
        return ActionQuote(
            quote_id=f"quote_{digest}",
            state_version=session.state_version,
            action_id=action_id,
            target_ids=target_ids,
            parameters=dict(parameters),
            action_point_cost=cost,
            budget_cost=definition.budget_cost,
            budget_unit=state.budget_unit,
            executor_kind=definition.executor_kind,
            resource_ids=definition.resource_ids,
        )

    def require_matching(
        self,
        session: GameSession,
        package: ScriptPackage,
        *,
        action_id: str,
        target_ids: tuple[str, ...],
        parameters: dict,
        quote_id: str | None,
    ) -> ActionQuote:
        quote = self.quote(
            session,
            package,
            action_id=action_id,
            target_ids=target_ids,
            parameters=parameters,
        )
        if quote_id != quote.quote_id:
            raise ActionUnavailableError("报价已过期或与本次行动不匹配，请重新报价")
        return quote

    @staticmethod
    def public(quote: ActionQuote, definition) -> dict:
        return {
            "quote_id": quote.quote_id,
            "state_version": quote.state_version,
            "action_id": quote.action_id,
            "target_ids": list(quote.target_ids),
            "parameters": quote.parameters,
            "cost_action_points": quote.action_point_cost,
            "direct_budget_cost": quote.budget_cost,
            "budget_unit": quote.budget_unit,
            "executor_kind": quote.executor_kind,
            "resource_ids": list(quote.resource_ids),
            "program_conditions": {
                "required_flags_satisfied": True,
                "target_schema_satisfied": True,
                "parameter_schema_satisfied": True,
            },
            "narrative_preview": definition.narrative,
        }

    @staticmethod
    def _validate_targets(schema: dict, values: tuple[str, ...]) -> None:
        minimum = int(schema.get("min_items", 0))
        maximum = int(schema.get("max_items", max(minimum, 64)))
        if not minimum <= len(values) <= maximum:
            raise ActionUnavailableError(
                "行动对象数量不符合要求",
                details={"minimum": minimum, "maximum": maximum},
            )
        if len(values) != len(set(values)):
            raise ActionUnavailableError("行动对象不能重复")
        allowed = set(schema.get("allowed_ids", ()))
        if allowed and not set(values).issubset(allowed):
            raise ActionUnavailableError("行动包含未登记对象")

    @staticmethod
    def _validate_parameters(schema: dict, values: dict) -> None:
        properties = dict(schema.get("properties", {}))
        required = set(schema.get("required", ()))
        if required - set(values):
            raise ActionUnavailableError(
                "行动参数不完整", details={"missing": sorted(required - set(values))}
            )
        if set(values) - set(properties):
            raise ActionUnavailableError(
                "行动包含未登记参数",
                details={"unknown": sorted(set(values) - set(properties))},
            )
        for key, value in values.items():
            spec = properties[key]
            expected = spec.get("type", "string")
            if expected == "integer" and type(value) is not int:
                raise ActionUnavailableError(f"参数 {key} 必须是整数")
            if expected == "string" and not isinstance(value, str):
                raise ActionUnavailableError(f"参数 {key} 必须是字符串")
            if "enum" in spec and value not in spec["enum"]:
                raise ActionUnavailableError(f"参数 {key} 不在允许范围内")
            if type(value) is int:
                if value < int(spec.get("minimum", value)):
                    raise ActionUnavailableError(f"参数 {key} 小于允许下限")
                if value > int(spec.get("maximum", value)):
                    raise ActionUnavailableError(f"参数 {key} 超过允许上限")

    @staticmethod
    def _allowed_target_ids(
        session: GameSession, package: ScriptPackage, action_id: str, schema: dict
    ) -> set[str]:
        target_kind = str(schema.get("target_kind", "npc"))
        if target_kind == "household":
            return {item.household_id for item in package.households}
        if target_kind == "fact":
            return set(session.known_fact_ids)
        if target_kind == "location":
            return {
                item.location_id for item in package.map_locations
                if session.game_state.story_day >= item.unlock_day
                and item.required_flags.issubset(session.flags)
            }
        if action_id in {"cross_validate_clues", "zheng_clue_summary"}:
            return set(session.known_fact_ids)
        if action_id == "field_visit":
            return {
                item.location_id for item in package.map_locations
                if session.game_state.story_day >= item.unlock_day
                and item.required_flags.issubset(session.flags)
            }
        return set(session.npc_states)
