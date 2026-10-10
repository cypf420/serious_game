from __future__ import annotations

from serious_game_backend.application.event_service import EventService
from serious_game_backend.domain.enums import SessionStatus
from serious_game_backend.domain.errors import DecisionRequiredError, SessionEndedError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage
from dataclasses import replace


class StoryClockService:
    def __init__(self, event_service: EventService) -> None:
        self._events = event_service

    def end_day(
        self,
        session: GameSession,
        package: ScriptPackage,
    ) -> list[str]:
        if session.status is not SessionStatus.ACTIVE:
            raise SessionEndedError("当前游戏已经结束")
        if session.pending_decision is not None:
            raise DecisionRequiredError("必须先处理当前决策")

        state = session.game_state
        if state.story_day >= 90:
            session.game_state = state.reset_for_day(
                story_day=90,
                days_left=0,
                action_point_cap=state.daily_action_point_cap,
            )
            session.status = SessionStatus.ENDED
            session.logs.append({
                "type": "ending_state_frozen",
                "story_day": 90,
                "visible_to_player": False,
            })
            return []

        next_day = state.story_day + 1
        next_days_left = max(0, state.days_left - 1)
        chapter_transition = package.chapter_for(next_day) != package.chapter_for(state.story_day)
        session.game_state = state.reset_for_day(
            story_day=next_day,
            days_left=next_days_left,
            action_point_cap=8,
        )
        if chapter_transition:
            for npc_id, npc_state in tuple(session.npc_states.items()):
                if npc_state.chapter_disclosure_used:
                    session.npc_states[npc_id] = replace(
                        npc_state, chapter_disclosure_used=False
                    )
        session.logs.append({
            "type": "day_advance",
            "from_day": state.story_day,
            "to_day": next_day,
            "visible_to_player": False,
        })
        triggered = self._events.trigger_fixed_events(session, package)
        if next_day == 90:
            session.logs.append({
                "type": "ending_anchor_reached",
                "story_day": 90,
                "visible_to_player": False,
            })
        return triggered
