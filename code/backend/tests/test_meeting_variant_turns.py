from unittest.mock import patch

import pytest

from tests.test_story_review_round1 import StoryReviewRound1Tests


@pytest.mark.parametrize("variant,location,participants,lead", [
    ("public_hearing", "loc_liulin_village", ("npc_zhao_jianguo", "npc_zhou_dashan"), None),
    ("clan_leader_campaign", "loc_zhou_ancestral_hall", ("npc_zhou_dashan", "npc_zhou_kuiyuan"), None),
    ("convene_leadership_meeting", "loc_county_government", ("npc_zhao_jianguo", "npc_feng_jingzhi"), "npc_feng_jingzhi"),
])
def test_meeting_variants_complete_real_api_discussion_resolution_and_archive(variant, location, participants, lead):
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f"meeting-flow-{variant}")
    try:
        session = helper.reset_to_day(runtime, sid, headers, 35)
        session.known_npc_ids.update(participants)
        session.encountered_npc_ids.update(participants)
        runtime.sessions.save(session, expected_version=session.state_version)
        base = f"/api/game/session/{sid}"
        started = client.post(base + "/governance/actions", headers=headers, json={
            "state_version": session.state_version, "action_kind": "leadership_meeting",
            "variant_id": variant, "location_id": location, "target_ids": list(participants),
            "topic": "协商补偿程序与后续责任", **({"lead_npc_id": lead} if lead else {}),
        })
        assert started.status_code == 201, started.text
        meeting = started.json()["meeting"]
        expected_order = [lead, *(p for p in participants if p != lead)] if lead else list(participants)
        assert meeting["speaking_order"] == expected_order
        assert meeting["lead_npc_id"] == (lead or "")
        contexts = []
        gateway = runtime.gameplay_governance._gateway
        original = gateway.run_night_turn
        def capture(context):
            contexts.append(context)
            return original(context)
        with patch.object(gateway, "run_night_turn", side_effect=capture):
            turn = client.post(base + f"/governance/meetings/{meeting['meeting_id']}/turn", headers=headers,
                json={"state_version": started.json()["state_version"],
                      "player_text": "请各方说明补偿程序诉求，明确责任人和办理期限。"})
        assert turn.status_code == 200, turn.text
        assert [c.npc_id for c in contexts] == expected_order
        if lead:
            assert "分管或牵头领导" in contexts[0].private_context
            assert turn.json()["replies"][0]["meeting_role"] == "lead_report"
        else:
            assert all("分管或牵头领导" not in c.private_context and "参会领导：" not in c.private_context for c in contexts)
            assert all(r["meeting_role"] == "member_position" for r in turn.json()["replies"])
        resolved = client.post(base + f"/governance/meetings/{meeting['meeting_id']}/resolve", headers=headers,
            json={"state_version": turn.json()["state_version"], "adopt": True, "resolution": {
                "decision": "按程序核实各方诉求并登记后续责任", "target_scope": "全村36户",
                "resources": {}, "responsible_ids": list(participants), "deadline_day": 40,
                "public_scope": ["全村36户"], "document_title": "补偿程序协商记录",
            }})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["meeting"]["status"] == "resolved"
        assert resolved.json()["meeting"]["speaking_order"] == expected_order
        stored = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
        assert stored.governance_actions[meeting["action_instance_id"]].status == "completed"
        archive_id = f"archive:meeting:{meeting['meeting_id']}"
        read = client.post(base + "/governance/actions", headers=headers, json={
            "state_version": resolved.json()["state_version"], "action_kind": "inspect_archives",
            "variant_id": "consult_county_archives", "location_id": "loc_county_government",
            "archive_ids": [archive_id], "topic": "查阅本次会议纪要",
        })
        assert read.status_code == 201, read.text
        archive = client.get(base + f"/governance/archives/{archive_id}", headers=headers)
        assert archive.status_code == 200, archive.text
        assert archive.json()["archive"]["source_id"] == meeting["meeting_id"]
        assert "协商补偿程序与后续责任" in archive.text
        assert turn.json()["replies"][0]["text"] in archive.text
        assert "按程序核实各方诉求并登记后续责任" in stored.archive_records[archive_id].content
    finally:
        client.close()


def test_leadership_meeting_still_requires_explicit_lead():
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api("lead-still-required")
    try:
        session = helper.reset_to_day(runtime, sid, headers, 35)
        participants = ["npc_zhao_jianguo", "npc_feng_jingzhi"]
        session.known_npc_ids.update(participants)
        session.encountered_npc_ids.update(participants)
        runtime.sessions.save(session, expected_version=session.state_version)
        response = client.post(f"/api/game/session/{sid}/governance/actions", headers=headers, json={
            "state_version": session.state_version, "action_kind": "leadership_meeting",
            "variant_id": "convene_leadership_meeting", "location_id": "loc_county_government",
            "target_ids": participants, "topic": "核对责任分工",
        })
        assert response.status_code == 409, response.text
        assert "牵头领导" in response.text
    finally:
        client.close()
