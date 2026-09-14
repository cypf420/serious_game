"""Current saved plans guide dialogue without inventing signing prerequisites."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from serious_game_backend.application.contract_context import own_saved_contracts
from serious_game_backend.domain.llm import RoleTurnResult
from tests.test_final_check_contract_attempts import game
from tests.test_contract_workflow_v2 import save_terms
from tests.test_feedback16_contract_context import saved_contract


def prepare(game, npc, household):
    session = game.session()
    session.game_state = replace(session.game_state, story_day=50)
    session.known_npc_ids.add(npc)
    session.encountered_npc_ids.add(npc)
    game.save(session)
    game.draft(npc=npc, household_id=household)
    return game.runtime.packages.get("pkg_gameplay_v3")


def test_wu_satisfied_plan_is_explicit_in_real_governance_context(game):
    package = prepare(game, "npc_wu_xiuying", "WU-01")
    terms = dict(game.session().household_contracts[game.cid].term_sheet)
    terms.update(housing_resource_id="housing_d1_140", service_allocations={"grave_relocation_service": 1})
    assert save_terms(game, terms=terms).status_code == 200
    service = game.runtime.gameplay_governance
    session = game.session()
    assert service._missing_hard_conditions(session, package, session.household_contracts[game.cid]) == []
    seen = []
    def capture(context):
        seen.append(context)
        return RoleTurnResult(npc_id=context.npc_id, dialogue="请按当前保存方案核对。")
    with patch.object(service._npc_turns._gateway, "run_turn", side_effect=capture):
        game.post(f"/governance/actions/{game.action_id}/turn", {"player_text": "请核对当前合同的面积和交房日。"})
    current = next(c for c in seen[0].visible_world_context["own_contracts"] if c["contract_id"] == game.cid)
    assert current["requirements_assessed"] is True
    assert current["remaining_conditions"] == []
    constraints = " ".join(current["dialogue_constraints"])
    assert "不得新增签约前置条件" in constraints
    assert "未记录" in constraints and "过往发言" in constraints
    assert "剧情绝对日" in constraints and "60天后" in constraints
    assert current["terms"]["housing_delivery_day"] == 60


def test_current_conditions_refresh_after_save_without_mutation_or_household_leak(game):
    package = prepare(game, "npc_yuan_guilan", "YUAN-01")
    session = game.session()
    original = deepcopy(session)
    current = own_saved_contracts(session, package, "npc_yuan_guilan")[0]
    assert current["requirements_assessed"] is True
    assert current["remaining_conditions"] == game.runtime.gameplay_governance._missing_hard_conditions(
        session, package, session.household_contracts[game.cid])
    assert "本户对房源上下楼条件仍有顾虑" in current["remaining_conditions"]
    assert session == original
    assert own_saved_contracts(session, package, "npc_wu_xiuying") == []
    terms = dict(session.household_contracts[game.cid].term_sheet)
    terms["housing_resource_id"] = "housing_d1_120_accessible"
    assert save_terms(game, terms=terms).status_code == 200
    updated = own_saved_contracts(game.session(), package, "npc_yuan_guilan")[0]
    assert updated["current_version"] == current["current_version"] + 1
    assert "本户对房源上下楼条件仍有顾虑" not in updated["remaining_conditions"]
    updated["remaining_conditions"].append("test mutation")
    assert "test mutation" not in own_saved_contracts(game.session(), package, "npc_yuan_guilan")[0]["remaining_conditions"]


def test_old_unresolvable_partial_plan_does_not_claim_no_unmet_conditions():
    contract = saved_contract("owner")
    session = SimpleNamespace(household_contracts={contract.contract_id: contract}, contract_batches={})
    current = own_saved_contracts(session, SimpleNamespace(governance_config={}), "owner")[0]
    assert current["requirements_assessed"] is False
    assert current["remaining_conditions"] is None


def test_review_and_dialogue_share_the_same_authoritative_condition_function(game):
    package = prepare(game, "npc_wu_xiuying", "WU-01")
    from serious_game_backend.application import contract_requirements
    session = game.session()
    contract = session.household_contracts[game.cid]
    with patch.object(contract_requirements, "missing_contract_conditions", return_value=["authority sentinel"]) as authority:
        assert game.runtime.gameplay_governance._missing_hard_conditions(session, package, contract) == ["authority sentinel"]
        assert own_saved_contracts(session, package, "npc_wu_xiuying")[0]["remaining_conditions"] == ["authority sentinel"]
    assert authority.call_count == 2
