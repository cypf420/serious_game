"""Meeting inputs remain factual and audience-scoped across conversation modes."""
from dataclasses import asdict
from unittest.mock import patch

import pytest

from tests.test_story_review_round1 import StoryReviewRound1Tests
from serious_game_backend.domain.gameplay_governance import ArchiveRecord, GovernanceActionRecord, MeetingRecord


@pytest.fixture
def meeting_world():
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api("meeting-reference-context")
    session = helper.reset_to_day(runtime, sid, headers, 35)
    participants = ("npc_feng_jingzhi", "npc_zhao_jianguo")
    session.known_npc_ids.update(participants)
    session.encountered_npc_ids.update(participants)
    session.governance_actions["prior"] = GovernanceActionRecord(
        "prior", "leadership_meeting", 34, participants, (),
        variant_id="public_hearing", status="completed")
    session.meetings["prior-meeting"] = MeetingRecord(
        "prior-meeting", "prior", 34, "核验材料听证", participants,
        "executive_decision", participants[0], status="resolved",
        resolution={"decision": "听证已完成，后续事项待办HEARING_FACT"})
    session.archive_records["public-evidence"] = ArchiveRecord(
        "public-evidence", "证据", "已核实材料", "本次测量已经核对安置房面积，等待会签确认。",
        "archive_investigation", "audit", 34, "read", read_at_days=[34],
        confidentiality="public", evidence_level="E3")
    session.archive_records["private-evidence"] = ArchiveRecord(
        "private-evidence", "证据", "私人材料", "此处为仅向冯静之披露的私人材料正文。",
        "archive_investigation", "audit", 34, "read", read_at_days=[34],
        confidentiality="private", evidence_level="E3", related_npc_ids=(participants[0],))
    runtime.sessions.save(session, expected_version=session.state_version)
    response = client.post(f"/api/game/session/{sid}/governance/actions", headers=headers, json={
        "state_version": session.state_version, "action_kind": "leadership_meeting",
        "variant_id": "convene_leadership_meeting", "location_id": "loc_county_government",
        "target_ids": list(participants), "lead_npc_id": participants[0],
        "topic": "安置实施方案", "archive_ids": ["public-evidence", "private-evidence"],
        "proposed_document_type": "implementation_notice"})
    assert response.status_code == 201, response.text
    yield runtime, client, sid, headers, response.json()
    client.close()


def test_meeting_receives_selected_public_evidence_and_actual_hearing_without_at(meeting_world):
    runtime, client, sid, headers, started = meeting_world
    seen = []
    gateway = runtime.gameplay_governance._gateway
    original = gateway.run_night_turn
    def capture(context):
        seen.append(asdict(context))
        return original(context)
    with patch.object(gateway, "run_night_turn", side_effect=capture):
        response = client.post(f"/api/game/session/{sid}/governance/meetings/{started['meeting']['meeting_id']}/turn",
            headers=headers, json={"state_version": started["state_version"],
                                  "player_text": "请核对所选材料及此前听证办理情况。"})
    assert response.status_code == 200, response.text
    assert len(seen) == 2
    for context in seen:
        assert "本次测量已经核对安置房面积，等待会签确认。" in context["private_context"]
        assert "public-evidence" in context["private_context"]
        assert "HEARING_FACT" in context["private_context"]
        assert '"status": "completed"' in context["private_context"]
        assert "此处为仅向冯静之披露的私人材料正文。" not in str(context)
        assert '"unavailable_count": 1' in context["private_context"]


def test_reference_directory_matches_all_current_participants_and_updates_after_switch(meeting_world):
    runtime, client, sid, headers, started = meeting_world
    path = f"/api/game/session/{sid}/governance/reference-documents"
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    documents = {d["id"]: d for d in response.json()["documents"]}
    assert documents["archive:public-evidence"]["can_reference"] is True
    assert documents["archive:private-evidence"]["can_reference"] is False
    assert documents["archive:private-evidence"]["reference_unavailable_reason"]
    assert not any(k.startswith("_") for d in documents.values() for k in d)
    session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    session.governance_actions[started["action"]["action_instance_id"]].status = "completed"
    session.governance_actions["private-visit"] = GovernanceActionRecord(
        "private-visit", "cadre_interview", 35, ("npc_feng_jingzhi",), (), status="active")
    runtime.sessions.save(session, expected_version=session.state_version)
    response = client.get(path, headers=headers)
    documents = {d["id"]: d for d in response.json()["documents"]}
    assert response.json()["audience_ids"] == ["npc_feng_jingzhi"]
    assert documents["archive:private-evidence"]["can_reference"] is True
    assert documents["archive:private-evidence"]["reference_unavailable_reason"] is None
