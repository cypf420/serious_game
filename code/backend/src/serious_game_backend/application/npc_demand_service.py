from __future__ import annotations

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import NPCDemandDefinition, ScriptPackage
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)


DEMAND_STATUSES = {
    "unknown", "discovered", "acknowledged", "committed", "satisfied",
    "lawfully_refused", "breached", "expired",
}
FINAL_DEMAND_STATUSES = {"satisfied", "lawfully_refused", "breached", "expired"}
class NPCDemandService:
    """把剧本诉求投影为可持久化状态；不把资源或指标交给 LLM。"""

    @staticmethod
    def initialize(session: GameSession, package: ScriptPackage) -> None:
        for demand in package.npc_demands:
            session.npc_demand_states.setdefault(demand.demand_id, {
                "npc_id": demand.npc_id,
                "status": "unknown",
                "updated_day": session.game_state.story_day,
                "history": [],
            })
        NPCDemandService.sync(session, package)

    @staticmethod
    def sync(session: GameSession, package: ScriptPackage) -> None:
        for demand in package.npc_demands:
            state = session.npc_demand_states.setdefault(demand.demand_id, {
                "npc_id": demand.npc_id,
                "status": "unknown", "updated_day": session.game_state.story_day,
                "history": [],
            })
            state.setdefault("npc_id", demand.npc_id)
            status = str(state.get("status", "unknown"))
            if status not in DEMAND_STATUSES:
                state["status"] = "unknown"
                status = "unknown"
            if status == "unknown" and NPCDemandService._discovered(
                session, package, demand
            ):
                NPCDemandService.transition(
                    session, demand.demand_id, "discovered", reason="剧情与接触条件已满足"
                )
                status = "discovered"
            if status == "discovered" and NPCDemandService._was_contacted(
                session, demand.npc_id
            ):
                NPCDemandService.transition(
                    session, demand.demand_id, "acknowledged", reason="已通过正式接触确认"
                )
                status = "acknowledged"
            if status not in FINAL_DEMAND_STATUSES:
                required_flags = set(demand.satisfy.get("required_flags", ()))
                if (status in {"discovered", "acknowledged", "committed"}
                        and required_flags and required_flags.issubset(session.flags)):
                    NPCDemandService.transition(
                        session, demand.demand_id, "satisfied", reason="剧情事实满足处置条件"
                    )
                    # Story/action effects already account for the actual result.

    @staticmethod
    def transition(
        session: GameSession,
        demand_id: str,
        status: str,
        *,
        reason: str,
    ) -> None:
        if status not in DEMAND_STATUSES:
            raise ValueError("invalid NPC demand status")
        state = session.npc_demand_states[demand_id]
        previous = str(state.get("status", "unknown"))
        if previous == status:
            return
        state["status"] = status
        state["updated_day"] = session.game_state.story_day
        state.setdefault("history", []).append({
            "story_day": session.game_state.story_day,
            "from": previous,
            "to": status,
            "reason": reason,
        })
        session.logs.append({
            "type": "npc_demand_transition",
            "story_day": session.game_state.story_day,
            "demand_id": demand_id,
            "from": previous,
            "to": status,
            "visible_to_player": False,
        })

    @staticmethod
    def public(session: GameSession, package: ScriptPackage) -> list[dict]:
        # Contact does not disclose an NPC's complete private needs.
        return []

    @staticmethod
    def allowed_transitions(
        status: str,
        legal_disposition: str,
        *,
        can_fulfill: bool = False,
    ) -> list[str]:
        return []

    @staticmethod
    def can_fulfill(
        session: GameSession,
        package: ScriptPackage,
        demand: NPCDemandDefinition,
    ) -> bool:
        required_flags = set(demand.satisfy.get("required_flags", ()))
        return bool(required_flags and required_flags.issubset(session.flags))

    @staticmethod
    def _discovered(
        session: GameSession,
        package: ScriptPackage,
        demand: NPCDemandDefinition,
    ) -> bool:
        rule = demand.discover
        if session.game_state.story_day < int(rule.get("min_day", 1)):
            return False
        if package.gameplay_schema_version >= 4:
            visible_npcs = NPCRelationshipService.actionable_npc_ids(
                session, package
            )
        else:
            visible_npcs = set(
                (package.governance_config or {}).get(
                    "initial_visible_npc_ids", ()
                )
            )
        if package.gameplay_schema_version < 4:
            for opportunity in package.interaction_opportunities:
                if opportunity.availability_mode.value == "closed":
                    continue
                if session.game_state.story_day < opportunity.day_min:
                    continue
                if not opportunity.requires_flags.issubset(session.flags):
                    continue
                if not opportunity.requires_events.issubset(session.triggered_events):
                    continue
                visible_npcs.add(opportunity.npc_id)
        if demand.npc_id not in visible_npcs:
            return False
        flags = set(rule.get("required_any_flags", ()))
        facts = set(rule.get("required_any_fact_ids", ()))
        if flags and not flags.intersection(session.flags):
            return False
        if facts and not facts.intersection(session.known_fact_ids):
            return False
        return True

    @staticmethod
    def _was_contacted(session: GameSession, npc_id: str) -> bool:
        if any(npc_id in item.target_ids for item in session.governance_actions.values()):
            return True
        return any(
            item.get("npc_id") == npc_id
            and item.get("type") in {"conversation_started", "conversation_turn"}
            for item in session.logs
        )
