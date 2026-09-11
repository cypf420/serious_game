from unittest.mock import patch

import pytest
from pydantic import ValidationError

from serious_game_backend.api.schemas import GroupConversationTurnRequest
from serious_game_backend.domain.conversation import ForcedGroupConversation
from serious_game_backend.domain.gameplay_governance import AdministrativeDocument
from tests.test_pending_archive_and_group_followup import _runtime


@pytest.mark.parametrize("ids", [["x", "x"], [""], ["x" * 257], [str(i) for i in range(9)]])
def test_group_schema_rejects_invalid_references(ids):
    with pytest.raises(ValidationError):
        GroupConversationTurnRequest(state_version=1, player_text="请看材料", reference_ids=ids)


@pytest.fixture
def group():
    runtime, client, headers, state = _runtime("acct-group-reference")
    session = runtime.sessions.get_owned(state["session_id"], headers["X-Account-ID"])
    session.pending_decision = None
    session.pending_decision_queue.clear()
    session.active_group_conversation = ForcedGroupConversation(
        conversation_id="group-reference", conversation_type="cadre_meeting",
        initiator_npc_id="npc_zhao_jianguo", participant_ids=("npc_zhao_jianguo", "npc_sun_qiang"),
        agenda="核对签约情况和下一步责任", demands=("说明责任",), urgency="high", story_day=11,
        status="active", followup_plan_id="followup_d10_county_reporting",
    )
    session.administrative_documents["ref-doc"] = AdministrativeDocument(
        "ref-doc", "hearing_notice", "责任核对材料", "published", 3,
        "请逐户核对补偿材料，并落实各方责任。", 1, "v3",
        public_scope=("npc_zhao_jianguo", "npc_sun_qiang"),
    )
    runtime.sessions.save(session, expected_version=session.state_version)
    yield runtime, client, headers, session
    client.close()


def test_group_turn_resolves_real_material_for_all_participants(group):
    runtime, client, headers, session = group
    seen = []
    gateway = runtime.group_conversations._gateway
    original = gateway.run_night_turn
    def capture(context):
        seen.append(context)
        return original(context)
    with patch.object(gateway, "run_night_turn", side_effect=capture):
        response = client.post(f"/api/game/session/{session.session_id}/group-conversation/turn", headers=headers,
            json=dict(client_action_id="group-reference-001", state_version=session.state_version,
                      player_text="请逐户核对补偿材料，并落实各方责任。", reference_ids=["document:ref-doc"]))
    assert response.status_code == 200, response.text
    assert len(seen) == 2
    assert all("请逐户核对补偿材料，并落实各方责任。" in context.private_context for context in seen)
    assert all('"version": 3' in context.private_context for context in seen)
    assert all("系统真实听证办理记录" in context.private_context for context in seen)


@pytest.mark.parametrize("reference", ["document:foreign-session", "document:ref-doc"])
def test_group_rejects_foreign_or_partial_audience_before_model(group, reference):
    runtime, client, headers, session = group
    session.administrative_documents["ref-doc"].public_scope = ("npc_zhao_jianguo",)
    runtime.sessions.save(session, expected_version=session.state_version)
    with patch.object(runtime.group_conversations._gateway, "run_night_turn") as model:
        response = client.post(f"/api/game/session/{session.session_id}/group-conversation/turn", headers=headers,
            json=dict(client_action_id="group-reference-denied", state_version=session.state_version,
                      player_text="请核对责任材料。", reference_ids=[reference]))
    assert response.status_code == 409, response.text
    model.assert_not_called()
    stored = runtime.sessions.get_owned(session.session_id, headers["X-Account-ID"])
    assert stored.active_group_conversation.transcript == session.active_group_conversation.transcript
    assert stored.flags == session.flags
    assert stored.game_state == session.game_state


def test_group_empty_references_keep_legacy_request_payload(group):
    runtime, _, headers, session = group
    payloads = []
    def reserve(**kwargs):
        payloads.append(kwargs["request_payload"])
        return {"state_version": session.state_version}
    with patch.object(runtime.group_conversations._leases, "reserve", side_effect=reserve):
        for references in [(), ("document:ref-doc",)]:
            runtime.group_conversations.reply(account_id=headers["X-Account-ID"], session_id=session.session_id,
                state_version=session.state_version, player_text="请核对责任材料。", reference_ids=references)
    assert "reference_ids" not in payloads[0]
    assert payloads[1] == {**payloads[0], "reference_ids": ["document:ref-doc"]}
