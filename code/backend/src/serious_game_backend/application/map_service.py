from __future__ import annotations

from serious_game_backend.application.interaction_opportunity_service import (
    InteractionOpportunityService,
)
from serious_game_backend.application.action_variants import (
    map_entry_identifier,
    map_variant_title,
    configured_variants,
    default_npc_location,
    governance_action_permission,
    variant_availability,
    variant_target_choices,
    public_variant,
)
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


class MapService:
    def __init__(self, opportunities: InteractionOpportunityService) -> None:
        self._opportunities = opportunities

    def build(self, session: GameSession, package: ScriptPackage) -> dict:
        NPCRelationshipService.synchronize(session, package)
        if package.gameplay_schema_version >= 4:
            return self._build_governance_map(session, package)
        available_items = self._opportunities.list_available(session, package)
        available = {
            item.opportunity_id
            for item in available_items
            if governance_action_permission(
                session, package, item.action_id
            )[0]
        }
        opportunities = {item.opportunity_id: item for item in available_items}
        npc_names = {item.npc_id: item.name for item in package.npc_profiles}
        tier = package.action_cost_tier(session.game_state.story_day)
        active_event_ids = {
            item.event_id
            for item in session.visible_events
            if item.story_day == session.game_state.story_day
        }
        locations = []
        for item in package.map_locations:
            linked_opportunity_ids = tuple(dict.fromkeys((
                *item.linked_opportunity_ids,
                *(
                    opportunity.opportunity_id
                    for opportunity in available_items
                    if self._default_location(opportunity.npc_id) == item.location_id
                ),
            )))
            linked_action_ids = tuple(dict.fromkeys((
                *item.linked_action_ids,
                *(
                    definition.action_id
                    for definition in package.resource_actions.values()
                    if item.location_id in definition.location_ids
                ),
            )))
            if session.game_state.story_day < item.unlock_day:
                visual_state = "locked"
            elif not item.required_flags.issubset(session.flags):
                visual_state = "locked"
            elif set(linked_opportunity_ids) & available:
                visual_state = "available"
            elif any(
                package.resource_actions.get(action_id) is not None
                and package.resource_actions[action_id].enabled
                and governance_action_permission(
                    session, package, action_id
                )[0]
                for action_id in linked_action_ids
            ):
                visual_state = "available"
            elif set(item.linked_event_ids) & active_event_ids:
                visual_state = "event_active"
            else:
                visual_state = "known"
            entry_cards = []
            for opportunity_id in linked_opportunity_ids:
                opportunity = opportunities.get(opportunity_id)
                if opportunity is None:
                    continue
                rule = package.action_rules[opportunity.action_id]
                permission, permission_reason = governance_action_permission(
                    session, package, opportunity.action_id
                )
                entry_cards.append({
                    "title": f"与{npc_names.get(opportunity.npc_id, '剧情人物')}交谈",
                    "entry_type": "conversation",
                    "description": opportunity.conversation_goal,
                    "cost_action_points": rule.cost_for(tier),
                    "available": permission,
                    "unavailable_reason": permission_reason,
                    "submit": {
                        "opportunity_id": opportunity.opportunity_id,
                        "npc_id": opportunity.npc_id,
                    },
                })
            for action_id in linked_action_ids:
                definition = package.resource_actions.get(action_id)
                rule = package.action_rules.get(action_id)
                if definition is None or rule is None:
                    continue
                available_action, unavailable_reason = self._resource_availability(
                    session, definition, rule
                )
                permission, permission_reason = governance_action_permission(
                    session, package, action_id
                )
                if not permission:
                    available_action = False
                    unavailable_reason = permission_reason
                entry_cards.append({
                    "title": rule.name,
                    "entry_type": "resource_action",
                    "description": definition.narrative,
                    "cost_action_points": rule.cost_for(tier),
                    "direct_budget_cost": definition.budget_cost,
                    "available": available_action,
                    "unavailable_reason": unavailable_reason,
                    "target_schema": definition.target_schema,
                    "target_choices": self._target_choices(
                        session, package, action_id
                    ),
                    "parameter_schema": definition.parameter_schema,
                    "submit": {"action_id": action_id},
                })
            locations.append({
                "location_id": item.location_id,
                "name": item.name,
                "description": item.description,
                "visual_state": visual_state,
                "entry_cards": entry_cards,
                "newly_unlocked": False,
            })
        return {
            "state_version": session.state_version,
            "story_day": session.game_state.story_day,
            "locations": locations,
        }

    def _build_governance_map(
        self,
        session: GameSession,
        package: ScriptPackage,
    ) -> dict:
        variants = tuple(
            item for item in configured_variants(package)
            if item.get("enabled", False)
        )
        active_event_ids = {
            item.event_id
            for item in session.visible_events
            if item.story_day == session.game_state.story_day
        }
        locations = []
        for location in package.map_locations:
            location_unlocked = (
                session.game_state.story_day >= location.unlock_day
                and location.required_flags.issubset(session.flags)
            )
            cards = []
            for variant in variants:
                if location.location_id not in variant["legal_location_ids"]:
                    continue
                available, reason = variant_availability(session, variant)
                permission, permission_reason = governance_action_permission(
                    session, package, str(variant["action_id"])
                )
                if not permission:
                    available = False
                    reason = permission_reason
                if not location_unlocked:
                    available = False
                    reason = reason or f"第 {location.unlock_day} 日后开放"
                target_choices = variant_target_choices(session, package, variant)
                descriptor = public_variant(session, package, variant)
                if available and not descriptor["available"]:
                    available = False
                    reason = descriptor["unavailable_reason"]
                legal_npc_ids = {
                    item["target_id"] for item in target_choices
                    if str(item["target_id"]).startswith("npc_")
                }
                preselected_npc_ids = [
                    npc_id for npc_id in variant.get("legal_target_ids", ())
                    if npc_id in legal_npc_ids
                    and default_npc_location(npc_id) == location.location_id
                ]
                if len(preselected_npc_ids) > int(
                    descriptor["participant_rules"]["maximum"]
                ):
                    preselected_npc_ids = []
                cards.append({
                    "title": map_variant_title(variant, location.location_id),
                    "entry_type": "governance_navigation",
                    "description": variant.get(
                        "description", variant["visible_result"]
                    ),
                    "action_id": variant["action_id"],
                    "variant_id": variant["variant_id"],
                    "map_entry_id": map_entry_identifier(
                        location.location_id, variant["variant_id"]
                    ),
                    "location_locked": True,
                    "preselected_location_id": location.location_id,
                    "preselected_npc_ids": preselected_npc_ids,
                    "participant_rules": descriptor["participant_rules"],
                    "target_kind": descriptor["target_kind"],
                    "target_choices": descriptor["target_choices"],
                    "location_choices": [{
                        "location_id": location.location_id,
                        "label": location.name,
                    }],
                    "available": available,
                    "unavailable_reason": reason,
                })
            if not location_unlocked:
                visual_state = "locked"
            elif any(card["available"] for card in cards):
                visual_state = "available"
            elif set(location.linked_event_ids) & active_event_ids:
                visual_state = "event_active"
            else:
                visual_state = "known"
            locations.append({
                "location_id": location.location_id,
                "name": location.name,
                "description": location.description,
                "visual_state": visual_state,
                "entry_cards": cards,
                "newly_unlocked": False,
            })
        return {
            "state_version": session.state_version,
            "story_day": session.game_state.story_day,
            "locations": locations,
        }

    @staticmethod
    def _resource_availability(session, definition, rule) -> tuple[bool, str | None]:
        state = session.game_state
        if not definition.enabled:
            return False, definition.unavailable_reason or "当前版本尚未开放"
        if state.story_day < definition.unlock_day:
            return False, definition.unavailable_reason or f"第 {definition.unlock_day} 日后开放"
        if definition.executor_kind == "conversation":
            return False, "请从人物会谈入口发起"
        if not definition.required_flags.issubset(session.flags):
            return False, definition.unavailable_reason or "必要程序条件尚未满足"
        if definition.required_any_flags and not (
            definition.required_any_flags & session.flags
        ):
            return False, definition.unavailable_reason or "必要程序条件尚未满足"
        if definition.forbidden_flags & session.flags:
            return False, definition.unavailable_reason or "当前状态不允许再次办理"
        if rule.daily_cap is not None and (
            state.daily_action_counts.get(rule.action_id, 0) >= rule.daily_cap
        ):
            return False, "今日次数已用尽"
        if rule.half_day and state.half_day_action_used:
            return False, "今日半日行程已占用"
        if rule.precondition_flags_any and not any(
            flag in session.flags for flag in rule.precondition_flags_any
        ):
            return False, "行动前置条件尚未满足"
        return True, None

    @staticmethod
    def _target_choices(session, package, action_id: str) -> list[dict]:
        definition = package.resource_actions[action_id]
        target_kind = str(definition.target_schema.get("target_kind", "npc"))
        if target_kind == "household":
            return [{
                "target_id": item.household_id,
                "label": (
                    f"{item.household_id}｜{item.registered_population}人｜"
                    f"住宅 {item.legal_residential_area_m2:g}㎡"
                ),
            } for item in package.households]
        if target_kind == "fact" or action_id in {
            "cross_validate_clues", "zheng_clue_summary",
        }:
            return [
                {"target_id": fact_id, "label": package.facts[fact_id].title}
                for fact_id in sorted(session.known_fact_ids)
                if fact_id in package.facts
            ]
        if target_kind == "location" or action_id == "field_visit":
            return [
                {"target_id": item.location_id, "label": item.name}
                for item in package.map_locations
                if session.game_state.story_day >= item.unlock_day
                and item.required_flags.issubset(session.flags)
            ]
        visible_npc_ids = (
            NPCRelationshipService.actionable_npc_ids(session, package)
            if package.gameplay_schema_version >= 4
            else set(session.npc_states)
        )
        return [
            {"target_id": item.npc_id, "label": item.name}
            for item in package.npc_profiles
            if item.npc_id in session.npc_states
            and item.npc_id in visible_npc_ids
        ]

    @staticmethod
    def _default_location(npc_id: str) -> str:
        if npc_id in {"npc_shi_wenbin", "npc_ke_qinian"}:
            return "loc_environment_station"
        if npc_id in {"npc_he_tiezhu", "npc_yuan_guilan", "npc_luo_jian"}:
            return "loc_county_hospital"
        if npc_id == "npc_liu_san":
            return "loc_abandoned_grain_station"
        if npc_id in {
            "npc_zhou_dashan", "npc_zhou_kuiyuan", "npc_zhou_mancang",
            "npc_wu_xiuying", "npc_tan_laoliu", "npc_ma_changshun",
            "npc_ning_dehai", "npc_yang_bo", "npc_lao_juetou",
            "npc_miao_xiwang", "npc_deng_shouben", "npc_wang_fang",
        }:
            return "loc_liulin_village"
        return "loc_county_government"
