from unittest.mock import Mock

import pytest

from terminal_client.api_client import ApiClient
from terminal_client.app import TerminalApp
from tests.test_app import visible_state


@pytest.mark.parametrize("menu_mode", [False, True])
def test_continue_reads_same_day_and_opens_end_day_without_settling(menu_mode):
    api = Mock(spec=ApiClient)
    api.new_key.return_value = "DEMO-story"
    api.continue_story.return_value = {"state_version": 2, "phase": "story_continued"}
    api.get_view.return_value = {
        "state": visible_state(version=2, day=8, pending=None),
        "commands": {"can_continue_story": False, "can_end_day": True},
        "feed": {"cursor": 2, "items": [{"cursor": 2, "kind": "narration", "text": "赵建国来电邀约。"}]},
    }
    output = []
    app = TerminalApp(api, output_fn=output.append, input_fn=lambda _: "1", menu_mode=menu_mode)
    app.session_id = "game_m1_test"
    app.state_version = 1
    app.state = visible_state(version=1, day=8, pending=None)
    app.commands = {"can_continue_story": True, "can_end_day": False}
    if menu_mode:
        app._menu_game_step()
    else:
        assert "next" in app._command_prompt()
        app.handle("next")
    api.continue_story.assert_called_once_with("game_m1_test", state_version=1, client_action_id="DEMO-story")
    api.end_day.assert_not_called()
    assert app.state["story"]["day"] == 8
    assert app.commands["can_end_day"] is True
    assert "赵建国来电邀约。" in "\n".join(output)
