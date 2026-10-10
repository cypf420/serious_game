from __future__ import annotations

from serious_game_backend.domain.script_package import ScriptPackage


class PackageValidationService:
    def build_report(self, package: ScriptPackage) -> dict:
        chapter_counts = {
            str(chapter): sum(
                item.chapter == chapter for item in package.decision_catalog
            )
            for chapter in range(1, 7)
        }
        return {
            "package_id": package.package_id,
            "package_version": package.package_version,
            "content_hash": package.content_hash,
            "status": package.status,
            "gameplay_schema_version": package.gameplay_schema_version,
            "valid": True,
            "counts": {
                "story_days": len(package.story_days),
                "actions": len(package.action_rules),
                "resource_action_definitions": len(package.resource_actions),
                "households": len(package.households),
                "household_registered_population": sum(
                    item.registered_population for item in package.households
                ),
                "household_resettlement_population": sum(
                    item.resettlement_population for item in package.households
                ),
                "registered_resource_handlers": sum(
                    item.executor_kind != "conversation"
                    for item in package.resource_actions.values()
                ),
                "conversation_action_definitions": sum(
                    item.executor_kind == "conversation"
                    for item in package.resource_actions.values()
                ),
                "npcs": len(package.npc_profiles),
                "npc_role_profiles": sum(
                    bool(item.role_setting) for item in package.npc_profiles
                ),
                "npc_big_five_profiles": sum(
                    item.big_five is not None for item in package.npc_profiles
                ),
                "facts_and_clues": len(package.facts),
                "public_dossiers": len(package.public_briefing.get("dossiers", [])),
                "public_tool_guidance": len(package.public_briefing.get("tool_guidance", {})),
                "unresolved_policy_numbers": len(
                    package.public_briefing.get("compensation_policy", {}).get(
                        "unresolved_numeric_fields", []
                    )
                ),
                "interaction_opportunities": len(package.interaction_opportunities),
                "decision_catalog": len(package.decision_catalog),
                "event_catalog": len(package.event_catalog),
                "runtime_decisions": len(package.decisions),
                "runtime_options": sum(
                    len(item.options) for item in package.decisions.values()
                ),
                "sorting_decisions": sum(
                    item.input_kind == "sorting" for item in package.decisions.values()
                ),
                "allocation_decisions": sum(
                    item.input_kind == "allocation" for item in package.decisions.values()
                ),
                "night_rules": len(package.story_days),
                "source_night_blocks": sum(
                    len(item.night_blocks) for item in package.story_days.values()
                ),
                "conditional_night_rules": sum(
                    len(item.night_conditional_effects)
                    for item in package.story_days.values()
                ) + sum(
                    bool(item.get("effects"))
                    for item in (package.night_agent_actions or {}).values()
                ),
                "night_agent_scenes": len(package.night_agent_scenes),
                "night_agent_actions": len(package.night_agent_actions or {}),
                "map_locations": len(package.map_locations),
                "main_endings": len(package.main_endings),
                "sub_endings": len(package.sub_endings),
                "ending_appendices": len(package.ending_appendices),
            },
            "decision_counts_by_chapter": chapter_counts,
            "anchors": {
                item.event_id: item.story_day
                for item in package.fixed_events
                if item.story_day in {31, 45, 59, 90}
            },
            "source_sha256": package.source_sha256,
        }
