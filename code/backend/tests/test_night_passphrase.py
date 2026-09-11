from copy import deepcopy
from unittest.mock import patch

import pytest

from tests.test_group_references import group


@pytest.mark.parametrize("stream", [False, True])
def test_passphrase_completes_only_current_conversation_without_ai(group, stream):
    runtime, client, headers, session = group
    before = deepcopy(session.game_state)
    next_conversation = deepcopy(session.active_group_conversation)
    next_conversation.conversation_id = "queued-night-conversation"
    session.group_conversation_queue.append(next_conversation)
    runtime.sessions.save(session, expected_version=session.state_version)
    url = f"/api/game/session/{session.session_id}/group-conversation/turn" + ("/stream" if stream else "")
    body = dict(client_action_id="DEMO-night-passphrase", state_version=session.state_version,
                player_text="zju need more vacation")
    with patch.object(runtime.group_conversations._gateway, "run_night_turn") as model, \
         patch.object(runtime.group_conversations._input_review, "review") as review:
        response = client.post(url, headers=headers, json=body)
        assert response.status_code == 200, response.text
        model.assert_not_called()
        review.assert_not_called()
        saved = runtime.sessions.get_owned(session.session_id, headers["X-Account-ID"])
        assert saved.game_state == before
        assert saved.active_group_conversation.conversation_id == "queued-night-conversation"
        assert saved.active_group_conversation.phase == "active"
        assert len(saved.completed_group_conversations) == 1
        assert saved.completed_group_conversations[0]["status"] == "completed"
        assert all(p["status"] == "settled" for p in saved.completed_group_conversations[0]["participant_states"].values())
        repeated = client.post(url, headers=headers, json=body)
        assert repeated.status_code == 200, repeated.text
        assert len(runtime.sessions.get_owned(session.session_id, headers["X-Account-ID"]).completed_group_conversations) == 1


def test_near_match_remains_normal_input(group):
    runtime, client, headers, session = group
    with patch.object(runtime.group_conversations._input_review, "review", return_value=(False, "irrelevant")) as review:
        response = client.post(f"/api/game/session/{session.session_id}/group-conversation/turn", headers=headers,
            json=dict(client_action_id="DEMO-near-match", state_version=session.state_version,
                      player_text="zju need more vaction"))
        assert response.status_code == 200, response.text
        review.assert_called_once()
        assert runtime.sessions.get_owned(session.session_id, headers["X-Account-ID"]).active_group_conversation is not None
