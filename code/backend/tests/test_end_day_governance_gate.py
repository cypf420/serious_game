from copy import deepcopy

import pytest

from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord
from tests.test_story_review_round1 import StoryReviewRound1Tests


@pytest.mark.parametrize("status", ["active", "completed", "cancelled"])
def test_end_day_matches_view_governance_gate_without_mutating_blocked_session(status):
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f"end-day-governance-{status}")
    try:
        session = helper.reset_to_day(runtime, sid, headers, 35)
        session.governance_actions["gate-action"] = GovernanceActionRecord(
            action_instance_id="gate-action", action_kind="household_visit",
            story_day=35, target_ids=("npc_zhou_dashan",), required_permissions=("1.1",),
            status=status,
        )
        runtime.sessions.save(session, expected_version=session.state_version)
        base = f"/api/game/session/{sid}"
        view = client.get(base + "/view", headers=headers)
        assert view.status_code == 200, view.text
        before = deepcopy(runtime.sessions.get_owned(sid, headers["X-Account-ID"]))
        response = client.post(base + "/end-day", headers=headers, json={
            "state_version": session.state_version, "client_action_id": "gate-end-day-001",
        })
        after = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
        assert view.json()["commands"]["can_end_day"] is (status != "active")
        if status == "active":
            assert response.status_code == 409, response.text
            assert "基础行动场景正在进行" in response.text
            assert after == before
            assert runtime.operations.get(headers["X-Account-ID"], sid, "gate-end-day-001") is None
        else:
            assert response.status_code == 200, response.text
            assert after.game_state.story_day == 36
            assert after.governance_actions["gate-action"].status == status
    finally:
        client.close()
