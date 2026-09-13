from __future__ import annotations

from serious_game_backend.domain.enums import AvailabilityMode
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.interaction_opportunity import InteractionOpportunity
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.application.archive_investigation_service import (
    eligible_definitions,
    public_investigation_choice,
)


TARGET_SELECTION_RULES = {
    "household_visit": {"minimum": 1, "maximum": 1},
    "cadre_interview": {"minimum": 1, "maximum": 3},
    "leadership_meeting": {"minimum": 2, "maximum": 8},
    "inspect_archives": {"minimum": 1, "maximum": 1},
}


def governance_action_permission(
    session: GameSession,
    package: ScriptPackage,
    action_id: str,
) -> tuple[bool, str | None]:
    """Return the shared write gate for action catalog, map and submission.

    A pending narrative decision pauses ordinary actions, while archive
    inspection remains a legal read operation.  The check intentionally does
    not include action-point cost or target availability; those are evaluated
    by the caller after this permission gate.
    """
    if package.status == "retired":
        return False, "该剧本包已退役，本局仅供复盘"
    if getattr(session.status, "value", session.status) != "active":
        return False, "本局已经结束"
    if session.processing_action_id is not None:
        return False, "上一操作仍在处理中，请等待原操作完成"
    if session.active_group_conversation is not None:
        return False, "必须先完成NPC发起的群组会谈"
    if any(item.status == "active" for item in session.governance_actions.values()):
        return False, "基础行动场景正在进行，请先继续或结束"
    if session.active_conversation is not None:
        return False, "会谈正在进行，请先继续或结束当前会谈"

    beat = package.story_day(session.game_state.story_day)
    allow_actions = (
        beat is None
        or beat.allow_actions
        or (
            package.gameplay_schema_version >= 2
            and session.game_state.story_day < 90
        )
    )
    if action_id == "inspect_archives" and session.pending_decision is not None:
        return True, None
    if session.pending_decision is not None:
        return False, "必须先处理当前决策"
    if not allow_actions:
        return False, "当前剧情节点不开放自主行动"
    return True, None


def participant_rules(action_id: str) -> dict[str, int]:
    return dict(TARGET_SELECTION_RULES[action_id])


def configured_variants(package: ScriptPackage) -> tuple[dict, ...]:
    variants = tuple(
        dict(item)
        for item in (package.governance_config or {}).get("action_variants", ())
    )
    # Old saves lock their original package. Add the explicit signing route
    # without rewriting that package or changing the paid field-visit route.
    source = next((v for v in variants if v.get("variant_id") == "field_visit"
                   and v.get("action_id") == "household_visit"), None)
    if source is not None and not any(v.get("variant_id") == "contract_negotiation" for v in variants):
        variants += ({**source, "variant_id": "contract_negotiation",
                      "legacy_action_id": "contract_negotiation", "name": "签约协商",
                      "description": "讨论、保存和预览合同不扣精力；每次有效提交签约消耗1点，接受或拒签均计费。",
                      "visible_result": "形成签约协商记录；实地看房请另行进入现场走访。",
                      "action_point_costs": {tier: 0 for tier in source["action_point_costs"]},
                      "location_labels": {},
                      "hard_outcomes": [{"kind": "follow_up", "id": "governance_action_record"}]},)
    return variants


def variant_availability(
    session: GameSession,
    variant: dict,
) -> tuple[bool, str | None]:
    if not variant.get("enabled", False):
        return False, str(variant.get("unavailable_reason") or "当前版本尚未开放")
    story_day = session.game_state.story_day
    unlock_day = int(variant["unlock_day"])
    if story_day < unlock_day:
        return False, f"第 {unlock_day} 日后开放"
    required = set(variant.get("required_flags", ()))
    if not required.issubset(session.flags):
        return False, "必要剧情或材料条件尚未满足"
    required_any = set(variant.get("required_any_flags", ()))
    if required_any and not required_any.intersection(session.flags):
        return False, "必要剧情或材料条件尚未满足"
    forbidden = set(variant.get("forbidden_flags", ()))
    if forbidden.intersection(session.flags):
        return False, "当前状态不允许再次办理"
    return True, None


def variant_target_choices(
    session: GameSession,
    package: ScriptPackage,
    variant: dict,
) -> list[dict]:
    target_kind = str(variant["target_kind"])
    legal_ids = set(str(item) for item in variant.get("legal_target_ids", ()))
    if target_kind == "available_archive":
        if package.archive_investigations:
            investigation_choices = [
                public_investigation_choice(session, package, item)
                for item in eligible_definitions(
                    session, package, unread_only=True
                )
            ]
            investigation_ids = {
                item.archive_id for item in package.archive_investigations
            }
            background_choices = [
                {
                    "target_id": item.archive_id,
                    "label": item.title,
                    "archive_id": item.archive_id,
                    "title": item.title,
                    "category": item.category,
                    "evidence_level": item.evidence_level,
                    "confidentiality": item.confidentiality,
                    "first_read_cost_action_points": (
                        1
                        if package.action_cost_tier(
                            session.game_state.story_day
                        ).value == "normal"
                        else 2
                    ),
                    "read_status": "unread",
                    "result_fact_count": 0,
                    "strategic_uses": [],
                }
                for item in session.archive_records.values()
                if item.status == "available"
                and not item.read_at_days
                and item.archive_id not in investigation_ids
            ]
            return [*investigation_choices, *background_choices]
        return [
            {"target_id": item.archive_id, "label": item.title}
            for item in session.archive_records.values()
            if item.status == "available"
        ]
    if target_kind == "location":
        return [
            {"target_id": item.location_id, "label": item.name}
            for item in package.map_locations
            if item.location_id in legal_ids
            and session.game_state.story_day >= item.unlock_day
            and item.required_flags.issubset(session.flags)
        ]
    profiles = {item.npc_id: item.name for item in package.npc_profiles}
    visible_ids = visible_governance_npc_ids(session, package)
    return [
        {"target_id": npc_id, "label": profiles[npc_id]}
        for npc_id in variant.get("legal_target_ids", ())
        if npc_id in profiles
        and npc_id in session.npc_states
        and npc_id in visible_ids
    ]


def available_location_choices(
    session: GameSession,
    package: ScriptPackage,
    variant: dict,
) -> list[dict]:
    """Return legal locations that are unlocked in the current state."""
    location_names = {item.location_id: item.name for item in package.map_locations}
    return [
        {
            "location_id": str(location_id),
            "label": str(
                variant.get("location_labels", {}).get(
                    location_id, location_names.get(location_id, location_id)
                )
            ),
        }
        for location_id in variant.get("legal_location_ids", ())
        if any(
            item.location_id == location_id
            and session.game_state.story_day >= item.unlock_day
            and item.required_flags.issubset(session.flags)
            for item in package.map_locations
        )
    ]


def resolve_variant_location(
    session: GameSession,
    package: ScriptPackage,
    variant: dict,
    *,
    preferred_location_id: str | None = None,
) -> str | None:
    choices = available_location_choices(session, package, variant)
    if not choices:
        return None
    choice_ids = {item["location_id"] for item in choices}
    if preferred_location_id in choice_ids:
        return preferred_location_id
    return choices[0]["location_id"]


def public_variant(
    session: GameSession,
    package: ScriptPackage,
    variant: dict,
) -> dict:
    tier = package.action_cost_tier(session.game_state.story_day).value
    available, reason = variant_availability(session, variant)
    target_choices = variant_target_choices(session, package, variant)
    rules = participant_rules(str(variant["action_id"]))
    if available and len(target_choices) < rules["minimum"]:
        available = False
        if not target_choices:
            reason = (
                "尚无可查阅档案"
                if variant["target_kind"] == "available_archive"
                else "尚无已经正式接触的可选对象"
            )
        else:
            reason = (
                f"至少需要 {rules['minimum']} 名已经正式接触的对象，"
                f"目前只有 {len(target_choices)} 名"
            )
    location_choices = available_location_choices(session, package, variant)
    return {
        "variant_id": variant["variant_id"],
        "action_id": variant["action_id"],
        "name": variant["name"],
        "description": variant.get("description", variant["visible_result"]),
        "cost_action_points": int(variant["action_point_costs"][tier]),
        "cost_mode": "on_contract_submit" if variant["variant_id"] == "contract_negotiation" else "action",
        "resource_cost_mode": variant["resource_cost_mode"],
        "resource_costs": list(variant["resource_costs"]),
        "visible_result": variant["visible_result"],
        "legal_location_ids": list(variant["legal_location_ids"]),
        "location_choices": location_choices,
        "resolved_location_id": (
            location_choices[0]["location_id"] if location_choices else None
        ),
        "target_kind": variant["target_kind"],
        "target_choices": target_choices,
        "participant_rules": rules,
        "available": available,
        "unavailable_reason": reason,
    }


def find_variant(package: ScriptPackage, variant_id: str) -> dict | None:
    return next(
        (
            item
            for item in configured_variants(package)
            if item.get("variant_id") == variant_id
        ),
        None,
    )


def map_entry_identifier(location_id: str, variant_id: str) -> str:
    return f"map:{location_id}:{variant_id}"


def map_variant_title(variant: dict, location_id: str) -> str:
    return str(
        variant.get("location_labels", {}).get(location_id, variant.get("name", "治理行动"))
    )


def canonical_map_entry_descriptor(
    session: GameSession,
    package: ScriptPackage,
    map_entry_id: str,
) -> dict | None:
    """Rebuild an executable map entry from authoritative session content."""
    for location in package.map_locations:
        if session.game_state.story_day < location.unlock_day:
            continue
        if not location.required_flags.issubset(session.flags):
            continue
        for variant in configured_variants(package):
            if location.location_id not in variant.get("legal_location_ids", ()):
                continue
            expected_id = map_entry_identifier(
                location.location_id, str(variant.get("variant_id", ""))
            )
            if expected_id != map_entry_id:
                continue
            available, _ = variant_availability(session, variant)
            if not available:
                return None
            descriptor = public_variant(session, package, variant)
            if not descriptor["available"]:
                return None
            return {
                **descriptor,
                "title": map_variant_title(variant, location.location_id),
                "map_entry_id": expected_id,
                "location_locked": True,
                "preselected_location_id": location.location_id,
                "location_choices": [{
                    "location_id": location.location_id,
                    "label": location.name,
                }],
            }
    return None


def visible_governance_npc_ids(
    session: GameSession,
    package: ScriptPackage,
) -> set[str]:
    if package.gameplay_schema_version >= 4:
        return NPCRelationshipService.actionable_npc_ids(session, package)
    visible = set(
        (package.governance_config or {}).get("initial_visible_npc_ids", ())
    )
    story_day = session.game_state.story_day
    for opportunity in package.interaction_opportunities:
        if opportunity.availability_mode is AvailabilityMode.CLOSED:
            continue
        if story_day < opportunity.day_min:
            continue
        if not opportunity.requires_flags.issubset(session.flags):
            continue
        if not opportunity.requires_events.issubset(session.triggered_events):
            continue
        visible.add(opportunity.npc_id)
    return visible


def default_npc_location(npc_id: str) -> str:
    if npc_id == "npc_sun_qiang":
        return "loc_ferry_town"
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


def canonical_opportunity_descriptor(
    session: GameSession,
    package: ScriptPackage,
    opportunity: InteractionOpportunity,
) -> dict | None:
    """Return the one authoritative governance route for a people opportunity."""
    expected_action = {
        "home_visit": "household_visit",
        "field_visit": "household_visit",
        "welfare_medical_safety_net": "household_visit",
        "heart_to_heart": "cadre_interview",
        "interview_cadre": "cadre_interview",
        "liaise_zhang_li": "cadre_interview",
        "private_testimony": "cadre_interview",
        "meet_party_secretary": "cadre_interview",
        "contact_reporter": "cadre_interview",
    }.get(opportunity.action_id)
    if expected_action is None:
        return None
    for variant in configured_variants(package):
        if variant.get("action_id") != expected_action:
            continue
        if not variant_availability(session, variant)[0]:
            continue
        descriptor = public_variant(session, package, variant)
        if opportunity.npc_id not in {
            item["target_id"] for item in descriptor["target_choices"]
        }:
            continue
        legal_locations = [
            item["location_id"] for item in descriptor["location_choices"]
        ]
        preferred = default_npc_location(opportunity.npc_id)
        location_id = (
            preferred if preferred in legal_locations
            else (legal_locations[0] if legal_locations else "")
        )
        return {
            **descriptor,
            "opportunity_id": opportunity.opportunity_id,
            "preselected_npc_ids": [opportunity.npc_id],
            "preselected_location_id": location_id,
            "canonical_topic": opportunity.conversation_goal.strip(),
        }
    return None
