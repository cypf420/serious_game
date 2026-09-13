import pytest

from serious_game_backend.application.reference_documents import hearing_facts
from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord, MeetingRecord
from tests.test_reference_documents import fixture
from tests.test_story_source_restoration import game


@pytest.mark.parametrize("option_id", ["a", "b", "c"])
def test_v3_decision_balance_matches_saved_effect_and_retry_is_read_only(game, option_id):
    helper, runtime, client, sid, headers = game
    session = helper.reset_to_day(runtime, sid, headers, 3)
    decision = runtime.packages.get("pkg_gameplay_v3").decisions["dp1_02"]
    option = next(item for item in decision.options if item.option_id == option_id)
    low, high = option.effects.ledger_deltas["budget_remaining"]
    before = session.game_state.budget_remaining
    payload = {"input_mode": "decision", "client_action_id": f"feedback16-budget-{option_id}",
               "state_version": session.state_version, "decision_id": decision.decision_id, "option_id": option_id}
    response = client.post(f"/api/game/session/{sid}/action", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    after = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert before + low <= after.game_state.budget_remaining <= before + high
    view = client.get(f"/api/game/session/{sid}/view", headers=headers).json()
    assert view["state"]["ledger"]["budget"]["remaining"] == after.game_state.budget_remaining
    retry = client.post(f"/api/game/session/{sid}/action", headers=headers, json=payload)
    assert retry.status_code == 200, retry.text
    assert runtime.sessions.get_owned(sid, headers["X-Account-ID"]) == after


def test_hearing_keeps_topic_status_and_old_case_boundary():
    session, _, _ = fixture()
    assert hearing_facts(session, "npc_tan_laoliu")["records"] == []
    action = GovernanceActionRecord("act", "leadership_meeting", 1, ("npc_tan_laoliu",), (),
                                    variant_id="public_hearing", topic="公共交通安排")
    meeting = MeetingRecord("meeting", "act", 1, "公共交通安排", ("npc_tan_laoliu",),
                            "executive_decision", "npc_tan_laoliu")
    session.governance_actions["act"] = action
    session.meetings["meeting"] = meeting
    for status, expected in [("discussing", "started"), ("resolved", "completed"), ("rejected", "completed")]:
        meeting.status = status
        facts = hearing_facts(session, "npc_tan_laoliu")
        assert facts["records"][0]["status"] == expected
        assert facts["records"][0]["topic"] == "公共交通安排"
        assert facts["old_case_resolved"] is False
        assert hearing_facts(session, "other")["records"] == []
    action.status = "cancelled"
    assert hearing_facts(session, "npc_tan_laoliu")["records"][0]["status"] == "aborted"
    action.variant_id = "convene_leadership_meeting"
    assert hearing_facts(session, "npc_tan_laoliu")["records"] == []
    assert session.flags == set()
