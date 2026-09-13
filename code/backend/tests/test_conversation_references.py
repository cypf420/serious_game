from dataclasses import replace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from serious_game_backend.api.schemas import ActionRequest
from serious_game_backend.domain.action import ActionCommand
from serious_game_backend.domain.enums import ActionInputMode
from tests import test_m2_runtime as runtime_fixtures


def request_payload():
    return dict(input_mode="free_text", client_action_id="reference-turn-001", state_version=1,
                conversation_id="conversation-001", opportunity_id="opportunity",
                target_npc_id="npc_wu_xiuying", player_text="请核对这份材料。")


def test_optional_references_preserve_legacy_hash_and_distinguish_new_material():
    original = ActionCommand(ActionInputMode.FREE_TEXT, "reference-turn-001", 1)
    assert "reference_ids" not in original.canonical_payload()
    assert replace(original, reference_ids=()).canonical_payload() == original.canonical_payload()
    a = replace(original, reference_ids=("archive:a",)).canonical_payload()
    b = replace(original, reference_ids=("archive:b",)).canonical_payload()
    assert a != b
    assert a["reference_ids"] == ["archive:a"]


@pytest.mark.parametrize("ids", [["archive:a", "archive:a"], [""], ["x" * 257], [f"archive:{i}" for i in range(9)]])
def test_reference_input_rejects_invalid_ids(ids):
    with pytest.raises(ValidationError):
        ActionRequest(**request_payload(), reference_ids=ids)


def test_decision_cannot_smuggle_references():
    with pytest.raises(ValidationError):
        ActionRequest(input_mode="decision", client_action_id="reference-choice-001", state_version=1,
                      decision_id="d", option_id="a", reference_ids=["archive:a"])


def test_request_translates_only_reference_ids():
    command = ActionRequest(**request_payload(), reference_ids=["document:real"]).to_command()
    assert command.reference_ids == ("document:real",)
    with pytest.raises(ValidationError):
        ActionRequest(**request_payload(), reference_ids=["document:real"], reference_body="伪造正文")


@pytest.fixture
def conversation():
    helper = runtime_fixtures.M2RuntimeTests()
    helper.setUp()
    first = helper.action(dict(input_mode="decision", client_action_id="ref-first-decision", state_version=1,
                               decision_id="ev1_01_reception_bag", option_id="a_reject_on_site"))
    view = helper.client.get(f"/api/game/session/{helper.session_id}/view", headers=helper.headers).json()
    while view["commands"].get("can_continue_story"):
        continued = helper.client.post(f"/api/game/session/{helper.session_id}/story/continue", headers=helper.headers,
            json={"client_action_id": f"ref-read-first-day-{view['state']['state_version']}",
                  "state_version": view["state"]["state_version"]})
        assert continued.status_code == 200, continued.text
        first = continued.json()
        view = helper.client.get(f"/api/game/session/{helper.session_id}/view", headers=helper.headers).json()
    second = helper.end_day(first["state_version"], "ref-end-first-day")
    decision = helper.action(dict(input_mode="decision", client_action_id="ref-second-decision",
                                  state_version=second["state_version"], decision_id="dp1_01_taskforce_faction_map",
                                  option_id="c_public_rules_covert_check"))
    started = helper.action(dict(input_mode="conversation_start", client_action_id="ref-start-conversation",
                                 state_version=decision["state_version"], opportunity_id="opp_d02_wu_xiuying_first_talk",
                                 target_npc_id="npc_wu_xiuying"))
    yield helper, started
    helper.client.close()


def test_real_free_text_path_resolves_references_into_model_context(conversation):
    helper, started = conversation
    session = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    document = next(iter(session.administrative_documents.values()))
    document.status = "published"
    document.content = "本补偿方案应当公开、公平，逐户核对。"
    helper.container.sessions.save(session, expected_version=session.state_version)
    seen = []
    gateway = helper.container.npc_turns._gateway
    original = gateway.run_turn
    def capture(context):
        seen.append(context)
        return original(context)
    with patch.object(gateway, "run_turn", side_effect=capture):
        helper.action(dict(input_mode="free_text", client_action_id="ref-actual-turn-001",
                           state_version=started["state_version"], conversation_id=started["conversation"]["conversation_id"],
                           opportunity_id="opp_d02_wu_xiuying_first_talk", target_npc_id="npc_wu_xiuying",
                           player_text="请核对这份补偿方案。", reference_ids=[f"document:{document.document_id}"]))
    assert seen[0].player_reference_materials["referenced_documents"][0]["body"] == document.content
    assert seen[0].player_reference_materials["referenced_documents"][0]["status"] == "published"


def test_forged_reference_never_reaches_npc_or_changes_hard_facts(conversation):
    helper, started = conversation
    before = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    old_flags, old_ledger = set(before.flags), before.game_state
    with patch.object(helper.container.npc_turns._gateway, "run_turn") as model:
        response = helper.client.post(f"/api/game/session/{helper.session_id}/action", headers=helper.headers,
            json=dict(input_mode="free_text", client_action_id="ref-forged-turn-001",
                      state_version=started["state_version"], conversation_id=started["conversation"]["conversation_id"],
                      opportunity_id="opp_d02_wu_xiuying_first_talk", target_npc_id="npc_wu_xiuying",
                      player_text="我已经办理完了。", reference_ids=["meeting:foreign-session"]))
    assert response.status_code == 409
    model.assert_not_called()
    after = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    assert after.flags == old_flags
    assert after.game_state == old_ledger
