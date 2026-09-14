from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from serious_game_backend.application.action_service import ActionService
from serious_game_backend.application.story_clock_service import StoryClockService
from serious_game_backend.domain.enums import ActionInputMode, SessionStatus
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.game_state import GameState
from serious_game_backend.infrastructure.repositories.codec import _decode_current_game_state


@pytest.mark.parametrize("old_cap,remaining,expected", [(5, 0, 3), (7, 2, 3), (8, 0, 0), (8, 11, 8)])
def test_legacy_save_load_removes_retired_fields_and_restores_lost_capacity(old_cap, remaining, expected):
    saved = {**asdict(GameState()), "fatigue": 90, "daily_action_point_cap": old_cap,
             "action_points": remaining, "overtime_used_today": True,
             "overtime_points_today": 3, "chapter_overtime_count": 3,
             "consecutive_full_load_days": 7}
    state = _decode_current_game_state(saved)
    assert state.action_points == expected
    assert state.daily_action_point_cap == 8
    assert not set(asdict(state)) & {"fatigue", "overtime_used_today", "overtime_points_today", "chapter_overtime_count", "consecutive_full_load_days"}
    assert saved["fatigue"] == 90
    assert _decode_current_game_state(asdict(state)) == state


@pytest.mark.parametrize("spent", [0, 3, 8, 11])
def test_next_day_always_restores_eight_points(spent):
    session = SimpleNamespace(status=SessionStatus.ACTIVE, pending_decision=None,
        game_state=GameState(action_points=0, points_spent_today=spent), logs=[], npc_states={})
    events = Mock()
    events.trigger_fixed_events.return_value = []
    package = SimpleNamespace(chapter_for=lambda day: 1)
    StoryClockService(events).end_day(session, package)
    assert session.game_state.action_points == 8
    assert session.game_state.story_day == 2
    assert session.game_state.points_spent_today == 0


def test_old_client_cannot_request_overtime():
    service = object.__new__(ActionService)
    state = GameState(action_points=0)
    session = SimpleNamespace(active_group_conversation=None, game_state=state)
    command = SimpleNamespace(input_mode=ActionInputMode.OVERTIME, parameters={"points": 3}, reference_ids=())
    with pytest.raises(ActionUnavailableError, match="加班机制已取消"):
        service._build_draft(session, SimpleNamespace(), command)
    assert session.game_state is state
