import pytest

from tests.test_group_references import group


@pytest.mark.parametrize("with_reference", [True, False])
def test_group_player_turn_persists_only_resolved_reference_metadata(group, with_reference):
    runtime, client, headers, session = group
    response = client.post(
        f"/api/game/session/{session.session_id}/group-conversation/turn", headers=headers,
        json={
            "client_action_id": "group-reference-history-001",
            "state_version": session.state_version,
            "player_text": "请逐户核对补偿材料，并落实各方责任。",
            **({"reference_ids": ["document:ref-doc"]} if with_reference else {}),
        },
    )
    assert response.status_code == 200, response.text
    saved = runtime.sessions.get_owned(session.session_id, headers["X-Account-ID"])
    player_turn = next(turn for turn in saved.active_group_conversation.transcript
                       if turn["speaker_type"] == "player")
    if with_reference:
        assert player_turn["references"] == [{
            "id": "document:ref-doc", "title": "责任核对材料", "version": 3,
            "status": "published",
        }]
    else:
        assert player_turn == {"speaker_type": "player", "text": "请逐户核对补偿材料，并落实各方责任。"}
