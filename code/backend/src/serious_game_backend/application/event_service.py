from __future__ import annotations

from serious_game_backend.domain.events import VisibleEvent
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


class EventService:
    """只执行剧本包已登记的固定事件；不凭代码生成剧情。"""

    def trigger_fixed_events(self, session: GameSession, package: ScriptPackage) -> list[str]:
        triggered: list[str] = []
        day = session.game_state.story_day
        for rule in package.fixed_events:
            if rule.story_day != day or rule.event_id in session.triggered_events:
                continue
            if not rule.required_flags.issubset(session.flags):
                continue
            if rule.required_any_flags and not (
                rule.required_any_flags & session.flags
            ):
                continue
            if rule.forbidden_flags & session.flags:
                continue
            if rule.forbidden_event_ids & session.triggered_events:
                continue
            session.triggered_events.add(rule.event_id)
            session.visible_events.append(
                VisibleEvent(
                    event_id=rule.event_id,
                    story_day=day,
                    title=rule.title,
                    summary=rule.visible_summary,
                )
            )
            session.logs.append({
                "type": "fixed_event",
                "story_day": day,
                "event_id": rule.event_id,
                "visible_to_player": True,
            })
            triggered.append(rule.event_id)
            decision_id = rule.event_id.lower().replace("-", "_")
            if decision_id in package.decisions:
                session.pending_decision_queue.append(decision_id)
        return triggered
