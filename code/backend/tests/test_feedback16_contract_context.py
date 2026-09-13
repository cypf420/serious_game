from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from serious_game_backend.application.contract_context import own_saved_contracts
from serious_game_backend.domain.gameplay_governance import ContractVersion, HouseholdContract
from tests.test_conversation_references import conversation
from tests.test_group_references import group


def saved_contract(npc_id, identifier="own", batch_id="batch"):
    return HouseholdContract(
        contract_id=identifier, batch_id=batch_id, household_id=f"TEST-{identifier}",
        signatory_name="测试户", signatory_npc_id=npc_id, created_day=2,
        status="rejected", current_version=2, term_sheet={"cash_amount": 27},
        versions=[ContractVersion(1, "旧正文", "t1", "x1", "test"),
                  ContractVersion(2, f"已保存正文-{identifier}", "t2", "x2", "test")],
        review_history=[{"version": 1, "reason": "请核对扶手", "review_fingerprint": "internal"}],
    )


def test_saved_contract_projection_is_scoped_versioned_and_detached():
    own = saved_contract("owner")
    neighbor = saved_contract("neighbor", "neighbor")
    pending = saved_contract("owner", "pending")
    pending.versions = []
    pending.current_version = 0
    session = SimpleNamespace(household_contracts={c.contract_id: c for c in [own, neighbor, pending]},
                              contract_batches={"batch": SimpleNamespace(representative_npc_id="representative")})
    package = SimpleNamespace(governance_config={})
    original = deepcopy(session)
    result = own_saved_contracts(session, package, "owner")
    assert len(result) == 1
    assert result[0]["current_version"] == 2
    assert result[0]["contract_text"] == "已保存正文-own"
    assert result[0]["reviews"] == [{"version": 1, "reason": "请核对扶手"}]
    assert len(own_saved_contracts(session, package, "representative")) == 2
    assert all("须由各户本人决定签署" in item["scope"] for item in own_saved_contracts(session, package, "representative"))
    assert own_saved_contracts(session, package, "unrelated") == []
    result[0]["terms"]["cash_amount"] = 999
    result[0]["reviews"][0]["reason"] = "被修改的上下文"
    assert session == original
    own.current_version = 99
    assert own_saved_contracts(session, package, "owner") == []


def test_free_text_receives_current_saved_contract_and_public_feedback(conversation):
    helper, started = conversation
    session = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    own = saved_contract("npc_wu_xiuying")
    foreign = saved_contract("npc_yuan_guilan", "foreign", "other-batch")
    session.household_contracts = {c.contract_id: c for c in [own, foreign]}
    helper.container.sessions.save(session, expected_version=session.state_version)
    gateway = helper.container.npc_turns._gateway
    original = gateway.run_turn
    seen = []
    def capture(context):
        seen.append(context)
        return original(context)
    with patch.object(gateway, "run_turn", side_effect=capture):
        helper.action(dict(input_mode="free_text", client_action_id="saved-contract-context-001",
            state_version=started["state_version"], conversation_id=started["conversation"]["conversation_id"],
            opportunity_id="opp_d02_wu_xiuying_first_talk", target_npc_id="npc_wu_xiuying",
            player_text="请核对已保存合同中的补偿和扶手安排。"))
    contracts = seen[0].visible_world_context["own_contracts"]
    assert len(contracts) == 1
    assert contracts[0]["contract_text"] == "已保存正文-own"
    assert contracts[0]["current_version"] == 2
    assert contracts[0]["terms"] == {"cash_amount": 27}
    assert contracts[0]["reviews"][0]["reason"] == "请核对扶手"


def test_group_only_receives_each_speakers_authorized_saved_contracts(group):
    runtime, client, headers, session = group
    contract = saved_contract("npc_zhao_jianguo", "private-zhao")
    session.household_contracts[contract.contract_id] = contract
    runtime.sessions.save(session, expected_version=session.state_version)
    seen = []
    gateway = runtime.group_conversations._gateway
    original = gateway.run_night_turn
    def capture(context):
        seen.append(context)
        return original(context)
    with patch.object(gateway, "run_night_turn", side_effect=capture):
        response = client.post(f"/api/game/session/{session.session_id}/group-conversation/turn", headers=headers,
            json=dict(client_action_id="group-saved-contracts", state_version=session.state_version,
                      player_text="请核对各自有权查阅的已保存条款。"))
    assert response.status_code == 200, response.text
    by_npc = {context.npc_id: context for context in seen}
    assert "已保存正文-private-zhao" in by_npc["npc_zhao_jianguo"].private_context
    assert "已保存正文-private-zhao" not in by_npc["npc_sun_qiang"].private_context
    assert "已保存正文-private-zhao" not in by_npc["npc_sun_qiang"].reference_context
