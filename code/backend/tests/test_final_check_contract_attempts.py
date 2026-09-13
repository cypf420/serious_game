"""AC-03/05/07: paid signing attempts are atomic and separate from discussion."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import test_contract_accounting as fixtures
from tests.test_contract_workflow_v2 import save_terms


@pytest.fixture
def game():
    value = fixtures.ContractAccountingTests()
    value.setUp()
    return value


def points(game, amount):
    session = game.session()
    session.game_state = replace(session.game_state, action_points=amount)
    game.save(session)


@pytest.mark.parametrize("missing", [False, True])
def test_valid_submit_costs_one_for_success_or_refusal(game, missing):
    game.draft(missing_grave=missing)
    before = game.session()
    game.review()
    after = game.session()
    assert after.game_state.action_points == before.game_state.action_points - 1
    attempt = after.household_contracts[game.cid].review_history[-1]
    assert attempt["cost_action_points"] == 1
    assert attempt["cost_policy"] == "submit_v1"
    if missing:
        assert after.game_state.budget_remaining == before.game_state.budget_remaining
        assert after.resource_reservations == before.resource_reservations
    else:
        assert after.game_state.budget_remaining == before.game_state.budget_remaining - game.cash


def test_contract_expression_is_scoped_to_authoritative_name_and_supplied_housing(game):
    game.draft(missing_grave=True)
    service = game.runtime.gameplay_governance
    original = service._gateway.run_governance_task
    seen = []
    def capture(context):
        seen.append(context)
        return original(context)
    with patch.object(service._gateway, "run_governance_task", side_effect=capture):
        game.review()
    payload = seen[0].payload
    assert payload["authoritative_signatory_name"] == game.session().household_contracts[game.cid].signatory_name
    assert payload["current_housing"]["attributes"]["accessible"] is False
    assert "没有电梯" in " ".join(payload["expression_constraints"])
    assert "错名不能覆盖权威姓名" in " ".join(payload["expression_constraints"])
    # The real gateway serializes these server-owned facts in its expression
    # context, rather than silently dropping the new payload fields.
    from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
    actual_model_context = OpenAICompatibleRoleLLMGateway._character_context(seen[0])
    assert "expression_constraints" in actual_model_context
    assert payload["authoritative_signatory_name"] in actual_model_context
    assert payload["confirmed_decision"] == "explain"


def test_zero_energy_cannot_submit_new_attempt_or_call_model(game):
    game.draft(); points(game, 0)
    before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as model:
        game.review(409)
    assert not model.called
    assert game.session() == before


def test_same_terms_and_conditions_ignore_chat_and_retry_without_fee(game):
    game.draft(missing_grave=True); game.review(); points(game, 0)
    session = game.session()
    session.governance_actions[game.action_id].transcript.append({"speaker_type": "player", "text": "再问一次"})
    game.save(session); before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as model:
        game.review()
    assert not model.called
    assert game.session() == before


def test_changed_saved_proposal_is_new_attempt(game):
    game.draft(missing_grave=True); game.review()
    before = game.session()
    assert save_terms(game, cash_amount=game.cash + 1).status_code == 200
    game.review()
    after = game.session()
    assert after.game_state.action_points == before.game_state.action_points - 1
    assert len(after.household_contracts[game.cid].review_history) == 2


@pytest.mark.parametrize("failure", ["throw", "empty", "commit"])
def test_technical_failure_preserves_every_resource_and_review(game, failure):
    game.draft(); before = deepcopy(game.session())
    service = game.runtime.gameplay_governance
    if failure == "commit":
        target, method, kwargs = service, "_commit", {"side_effect": RuntimeError("write failed")}
    elif failure == "throw":
        target, method, kwargs = service._gateway, "run_governance_task", {"side_effect": RuntimeError("model failed")}
    else:
        target, method, kwargs = service._gateway, "run_governance_task", {"return_value": SimpleNamespace(model_id="test", data={"reason": ""})}
    with patch.object(target, method, **kwargs):
        if failure == "empty":
            game.review(409)
        else:
            with pytest.raises(RuntimeError):
                game.review()
    assert game.session() == before


def test_verified_old_paid_inflight_visit_credits_only_one_attempt(game):
    game.draft(missing_grave=True)
    session = game.session(); action = session.governance_actions[game.action_id]
    # Pre-upgrade persisted action, with a committed debit and timestamp.
    session.logs = [e for e in session.logs if not (e.get("type") == "governance_action_fee_policy"
                    and e.get("action_instance_id") == game.action_id)]
    action.cost_action_points = 1; action.cost_status = "committed"
    action.cost_committed_at = "2026-09-12T00:00:00+00:00"
    session.game_state = replace(session.game_state, action_points=0)
    game.save(session)
    game.review()
    review = game.session().household_contracts[game.cid].review_history[-1]
    assert review["cost_action_points"] == 0
    assert review["legacy_credit_action_id"] == game.action_id
    assert save_terms(game, cash_amount=game.cash + 1).status_code == 200
    before = game.session(); game.review(409)
    assert game.session() == before


def test_new_independent_field_visit_is_not_a_legacy_credit(game):
    game.draft()
    game.post(f"/governance/actions/{game.action_id}/turn", {"player_text": "我们核实一下现场情况。"})
    points(game, 0); before = game.session(); game.review(409)
    assert game.session() == before


def test_legacy_pending_conversation_cannot_charge_again_after_submit(game):
    game.draft(missing_grave=True)
    session = game.session()
    session.logs = [e for e in session.logs if not (e.get("type") == "governance_action_fee_policy"
                    and e.get("action_instance_id") == game.action_id)]
    game.save(session)
    before = game.session().game_state.action_points
    game.review()
    game.post(f"/governance/actions/{game.action_id}/turn", {"player_text": "我们再讨论一下搬迁的安排。"})
    assert game.session().game_state.action_points == before - 1


def test_legacy_cost_without_committed_timestamp_is_not_free_credit(game):
    game.draft(); session = game.session()
    session.logs = [e for e in session.logs if e.get("type") != "governance_action_fee_policy"]
    action = session.governance_actions[game.action_id]
    action.cost_status = "committed"; action.cost_action_points = 1; action.cost_committed_at = None
    session.game_state = replace(session.game_state, action_points=0)
    game.save(session); before = game.session(); game.review(409)
    assert game.session() == before


def test_saved_attempt_survives_codec_restore_and_zero_energy_retry(game):
    from serious_game_backend.infrastructure.repositories.codec import encode_session, decode_session
    game.draft(missing_grave=True); game.review(); points(game, 0)
    restored = decode_session(encode_session(game.session()))
    game.save(restored); before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as model:
        game.review()
    assert not model.called
    assert game.session() == before


def test_unchanged_old_review_is_reused_without_retroactive_cost(game):
    game.draft(missing_grave=True); game.review()
    session = game.session(); contract = session.household_contracts[game.cid]
    review = contract.review_history[-1]
    for key in ("cost_policy", "cost_action_points", "legacy_credit_action_id", "remaining_conditions"):
        review.pop(key, None)
    package = game.runtime.packages.get(session.package_id)
    review["review_fingerprint"] = game.runtime.gameplay_governance._contract_review_fingerprint(session, package, contract, legacy=True)
    session.game_state = replace(session.game_state, action_points=0)
    game.save(session); before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as model:
        game.review()
    assert not model.called
    assert game.session() == before


def test_completed_preupgrade_refusal_cannot_credit_a_revised_proposal(game):
    game.draft(missing_grave=True); game.review()
    session = game.session(); contract = session.household_contracts[game.cid]
    session.logs = [e for e in session.logs if e.get("type") not in {"governance_action_fee_policy", "contract_attempt_cost"}]
    action = session.governance_actions[game.action_id]
    action.cost_status = "committed"; action.cost_action_points = 1
    action.cost_committed_at = "2026-09-12T09:00:00+08:00"
    review = contract.review_history[-1]
    for key in ("cost_policy", "cost_action_points", "legacy_credit_action_id", "remaining_conditions"):
        review.pop(key, None)
    package = game.runtime.packages.get(session.package_id)
    review["review_fingerprint"] = game.runtime.gameplay_governance._contract_review_fingerprint(session, package, contract, legacy=True)
    session.game_state = replace(session.game_state, action_points=0)
    game.save(session)
    changed = save_terms(game, cash_amount=game.cash + 1)
    assert changed.status_code == 200
    assert changed.json()["contract"]["review_cost_action_points"] == 1
    assert changed.json()["contract"]["can_review"] is False
    before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as model:
        game.review(409)
    assert not model.called
    assert game.session() == before
    points(game, 1)
    game.review()
    assert game.session().game_state.action_points == 0
    assert game.session().household_contracts[game.cid].review_history[-1]["cost_action_points"] == 1


@pytest.mark.parametrize("history_day,allow_credit", [(9, True), (10, False), (11, False), (None, False)])
def test_legacy_representative_fee_cannot_be_recycled_across_households(game, history_day, allow_credit):
    game.draft(missing_grave=True)
    session = game.session(); current = session.household_contracts[game.cid]
    other = next(c for c in session.household_contracts.values() if c.contract_id != game.cid)
    old_review = {"version": 1, "decision": "explain", "reason": "旧方案未通过"}
    if history_day is not None:
        old_review["story_day"] = history_day
    other.review_history.append(old_review)
    session.logs = [e for e in session.logs if e.get("type") != "governance_action_fee_policy"]
    action = session.governance_actions[game.action_id]
    action.cost_status = "committed"; action.cost_action_points = 1
    action.cost_committed_at = "2026-09-12T09:00:00+08:00"
    session.game_state = replace(session.game_state, action_points=0)
    game.save(session); before = game.session()
    result = game.review(200 if allow_credit else 409)
    if allow_credit:
        latest = game.session().household_contracts[current.contract_id].review_history[-1]
        assert latest["legacy_credit_action_id"] == action.action_instance_id
        assert latest["cost_action_points"] == 0
    else:
        assert game.session() == before


def test_two_yuan_households_keep_versions_feedback_and_current_materials_separate(game):
    session = game.session()
    session.game_state = replace(session.game_state, story_day=60)
    session.flags.update({"袁桂兰核心矛盾已缓解", "袁桂兰合同批次可发起"})
    session.known_npc_ids.add("npc_yuan_guilan"); session.encountered_npc_ids.add("npc_yuan_guilan")
    game.save(session)
    game.draft(npc="npc_yuan_guilan", household_id="YUAN-01")
    first_id = game.cid
    game.review()  # A non-accessible unit leaves a genuine current concern.
    first = deepcopy(game.session().household_contracts[first_id])
    second = next(c for c in game.session().household_contracts.values() if c.household_id == "YUAN-02")
    game.cid = second.contract_id
    service = game.runtime.gameplay_governance
    package = game.runtime.packages.get("pkg_gameplay_v3")
    household = next(h for h in package.households if h.household_id == "YUAN-02")
    terms = dict(first.term_sheet)
    terms.update(housing_resource_id="housing_d1_120_accessible",
                 cash_amount=service._standard_cash(package, household, months=0, reward=False))
    assert save_terms(game, terms=terms).status_code == 200
    assert game.review()["contract"]["status"] == "signed"
    assert game.session().household_contracts[first_id] == first
    game.cid = first_id
    assert save_terms(game, housing_resource_id="housing_d1_100_accessible").status_code == 200
    observed = []
    original = service._gateway.run_governance_task
    def capture(context):
        observed.append(context)
        return original(context)
    with patch.object(service._gateway, "run_governance_task", side_effect=capture):
        result = game.review()["contract"]
    assert result["status"] == "signed"
    assert result["current_version"] == 2
    assert result["conversation_npc_id"] == "npc_yuan_guilan"
    assert observed[0].actor_context["household"]["household_id"] == "YUAN-01"
    assert observed[0].actor_context["selected_housing"]["attributes"]["area_m2"] == 100
    assert observed[0].payload["remaining_concern"] == []
    from serious_game_backend.application.contract_context import own_saved_contracts
    projected = own_saved_contracts(game.session(), package, "npc_yuan_guilan")
    assert {(c["household_id"], c["current_version"]) for c in projected} == {("YUAN-01", 2), ("YUAN-02", 1)}
    assert all(c["current_review"]["version"] == c["current_version"] for c in projected)


def test_free_signing_discussion_at_zero_energy_has_no_viewing_evidence(game):
    points(game, 0)
    response = game.post("/governance/actions", {"action_kind": "household_visit",
        "variant_id": "contract_negotiation", "target_ids": ["npc_zhou_dashan"], "topic": "签约协商"}, 201)
    action_id = response["action"]["action_instance_id"]
    game.post(f"/governance/actions/{action_id}/turn", {"player_text": "我们现在去看合同里这套可入住的安置房，好吗？"})
    session = game.session()
    assert session.game_state.action_points == 0
    assert session.governance_actions[action_id].cost_action_points == 0
    assert not any(o.get("id") == "real_unit_viewed" for o in session.governance_actions[action_id].hard_outcomes)
