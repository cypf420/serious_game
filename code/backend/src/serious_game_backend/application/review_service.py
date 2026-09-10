from __future__ import annotations

from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


class ReviewService:
    def __init__(self, projector: VisibleStateProjector) -> None:
        self._projector = projector

    def build(self, session: GameSession, package: ScriptPackage) -> dict:
        decisions = [
            {
                "story_day": item["story_day"],
                "decision_id": item["decision_id"],
                "title": (
                    item.get("visible_title")
                    or (
                        package.decisions[item["decision_id"]].title
                        if item["decision_id"] in package.decisions else "剧情决策"
                    )
                ),
                "prompt": (
                    item.get("visible_prompt")
                    or (
                        package.decisions[item["decision_id"]].prompt
                        if item["decision_id"] in package.decisions else ""
                    )
                ),
                "scene_id": (
                    item.get("visible_scene_id")
                    or (
                        package.decisions[item["decision_id"]].scene_id
                        if item["decision_id"] in package.decisions else None
                    )
                ),
                "option_id": item["option_id"],
                "choice": self._decision_choice(package, item),
                "cost_action_points": 0,
                **(
                    {"parameters": item["parameters"]}
                    if item.get("parameters")
                    else {}
                ),
            }
            for item in session.logs
            if item.get("type") == "decision"
        ]
        actions = [
            {
                "story_day": item["story_day"],
                "action_id": item["action_id"],
                "name": (
                    package.action_rules[item["action_id"]].name
                    if item.get("action_id") in package.action_rules else "自主行动"
                ),
                "cost_action_points": item["cost_action_points"],
                "budget_cost": item.get("budget_cost", 0),
                "public_result": item.get("public_narrative"),
                "target_ids": list(item.get("target_ids", ())),
            }
            for item in session.logs
            if item.get("type") == "action_completed"
        ]
        conversations = [
            {
                "story_day": item["story_day"],
                "event": item["type"],
                "npc_id": item.get("npc_id"),
                "npc_name": self._npc_name(package, item.get("npc_id")),
                "cost_action_points": item.get("cost_action_points", 0),
                "ended_by": item.get("ended_by"),
                "completion_status": item.get("completion_status"),
            }
            for item in session.logs
            if item.get("type") in {
                "conversation_started", "conversation_turn", "conversation_ended"
            }
        ]
        selected = {item["decision_id"] for item in decisions}
        triggered = session.triggered_events
        state = self._projector.project(session, package)
        return {
            "session_id": session.session_id,
            "status": session.status.value,
            "decision_timeline": decisions,
            "action_timeline": actions,
            "conversation_timeline": conversations,
            "group_conversation_timeline": [
                {
                    "conversation_id": item.get("conversation_id"),
                    "conversation_type": item.get("conversation_type"),
                    "story_day": item.get("story_day"),
                    "initiator_npc_id": item.get("initiator_npc_id"),
                    "participant_ids": list(item.get("participant_ids", ())),
                    "agenda": item.get("agenda"),
                    "demands": list(item.get("demands", ())),
                    "turn_count": item.get("turn_count", 0),
                    "transcript": list(item.get("transcript", ())),
                }
                for item in session.completed_group_conversations
            ],
            "night_timeline": [
                {
                    key: item.get(key)
                    for key in (
                        "story_day",
                        "beat_id",
                        "lines",
                        "summary",
                        "morning_card",
                        "propagation_count",
                    )
                }
                for item in session.night_logs
            ],
            "visible_events": state["visible_events"],
            "known_facts": [
                {
                    "fact_id": fact_id,
                    "title": package.facts[fact_id].title,
                    "text": package.facts[fact_id].text,
                    "source_label": package.facts[fact_id].source_label,
                    "use_hint": package.facts[fact_id].use_hint,
                }
                for fact_id in sorted(session.known_fact_ids)
                if fact_id in package.facts
            ],
            "ending": state["ending"],
            "final_visible_state": state if session.ending_result else None,
            "untriggered_paths": {
                "decision_ids": [
                    item.content_id
                    for item in package.decision_catalog
                    if item.content_id not in selected
                ],
                "event_ids": [
                    item.content_id
                    for item in package.event_catalog
                    if item.content_id not in triggered
                ],
            },
        }

    @staticmethod
    def _decision_choice(package: ScriptPackage, log: dict) -> str:
        recorded = log.get("selected_option_label")
        if isinstance(recorded, str) and recorded.strip():
            return recorded
        decision = package.decisions.get(log.get("decision_id"))
        option = decision.option(log.get("option_id")) if decision else None
        return option.text if option is not None else str(log.get("option_id", ""))

    @staticmethod
    def _npc_name(package: ScriptPackage, npc_id: str | None) -> str | None:
        if npc_id is None:
            return None
        return next(
            (item.name for item in package.npc_profiles if item.npc_id == npc_id),
            "剧情人物",
        )
