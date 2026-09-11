"""Scope and promised follow-up must survive the real contract API path."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from tests import test_contract_accounting as fixtures
from tests.test_contract_workflow_v2 import save_terms


@pytest.fixture
def game():
    f = fixtures.ContractAccountingTests()
    f.setUp()
    return f


def issue_adjustment(game, scope):
    session = game.session()
    document = deepcopy(session.administrative_documents["doc_compensation_policy_v1"])
    document.document_id = "scope-test-adjustment"
    document.document_type = "compensation_adjustment"
    document.status = "issued"
    document.source_meeting_id = "scope-test-meeting"
    document.resolution_snapshot = {"target_scope": scope, "resource_authorization_limits": {}}
    session.administrative_documents[document.document_id] = document
    game.save(session)
    return document.document_id


@pytest.mark.parametrize("scope", ["仅限WU-01户，不适用于其他家庭", "首批签约家庭", "全村36户但不包括ZDS-03", "不适用于ZDS-03", "", "ZDS-03及其他相关家庭", "ZDS-03、FAKE-01"])
def test_wrong_or_ambiguous_scope_cannot_spend(game, scope):
    game.draft()
    approval = issue_adjustment(game, scope)
    before = game.session()
    response = save_terms(game, cash_amount=game.cash + 21, approval_document_ids=[approval])
    assert response.status_code == 409, response.text
    assert "approval_document_ids" in response.json()["error"]["details"]["field_errors"]
    assert game.session() == before


@pytest.mark.parametrize("scope", ["ZDS-03", "仅限ZDS-03户，不适用于其他家庭", "WU-01、ZDS-03", "全村36户", "柳林村36户"])
def test_explicit_household_or_village_scope_allows_existing_approval(game, scope):
    game.draft()
    approval = issue_adjustment(game, scope)
    response = save_terms(game, cash_amount=game.cash + 21, approval_document_ids=[approval])
    assert response.status_code == 200, response.text
    assert game.review()["contract"]["status"] == "signed"


def test_scope_is_rechecked_when_reviewing_saved_draft(game):
    game.draft()
    approval = issue_adjustment(game, "全村36户")
    assert save_terms(game, cash_amount=game.cash + 21, approval_document_ids=[approval]).status_code == 200
    session = game.session()
    session.administrative_documents[approval].resolution_snapshot["target_scope"] = "WU-01"
    game.save(session)
    before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task") as call:
        game.review(status=409)
    call.assert_not_called()
    assert game.session() == before


def test_original_policy_remains_usable_without_meeting_scope(game):
    game.draft()
    assert save_terms(game, approval_document_ids=["doc_compensation_policy_v1"]).status_code == 200
    assert game.review()["contract"]["status"] == "signed"


@pytest.mark.parametrize("scope,expected", [("WU-01", 409), ("适用对象： ZDS-03", 200)])
def test_policy_itself_must_cover_household(game, scope, expected):
    game.draft()
    policy = issue_adjustment(game, scope)
    session = game.session()
    session.administrative_documents[policy].document_type = "compensation_policy"
    game.save(session)
    before = game.session()
    response = save_terms(game, policy_document_id=policy)
    assert response.status_code == expected, response.text
    if expected == 409:
        assert "policy_document_id" in response.json()["error"]["details"]["field_errors"]
        assert game.session() == before
    else:
        assert game.review()["contract"]["status"] == "signed"


PLAN = {"medical_provider": "县医院儿科", "recheck_interval_days": 30,
        "employment_receiver": "县就业服务中心", "medical_fee_arrangement": "allocated_medical_service"}


def prepare_he(game):
    session = game.session()
    session.known_npc_ids.add("npc_he_tiezhu")
    session.encountered_npc_ids.add("npc_he_tiezhu")
    game.save(session)
    game.draft(npc="npc_he_tiezhu", household_id="HE-02")


@pytest.mark.parametrize("services,plan", [
    ({"child_assessment_slot": 1}, None),
    ({"child_assessment_slot": 1, "stable_job_slot": 1}, PLAN),
    ({"lead_recheck_slot": 1}, PLAN),
    ({"lead_recheck_slot": 1, "stable_job_slot": 1}, None),
])
def test_he02_partial_promises_do_not_sign_or_spend(game, services, plan):
    prepare_he(game)
    response = save_terms(game, service_allocations=services, followup_plan=plan)
    assert response.status_code == 200, response.text
    before = game.session()
    result = game.review()["contract"]
    after = game.session()
    assert result["status"] != "signed"
    assert before.game_state.budget_remaining == after.game_state.budget_remaining
    assert before.game_state.signed_households == after.game_state.signed_households
    assert before.resource_reservations == after.resource_reservations


@pytest.mark.parametrize("employment", ["stable_job_slot", "training_slot"])
def test_he02_complete_attachment_and_resources_sign_once(game, employment):
    prepare_he(game)
    response = save_terms(game, service_allocations={"lead_recheck_slot": 1, employment: 1}, followup_plan=PLAN)
    assert response.status_code == 200, response.text
    text = response.json()["contract"]["contract_text"]
    assert "县医院儿科" in text and "每30日" in text and "县就业服务中心" in text
    assert "不另增现金承诺" in text and "尚不表示已确认接收" in text
    before = game.session()
    assert game.review()["contract"]["status"] == "signed"
    after = game.session()
    assert after.game_state.signed_households == before.game_state.signed_households + 1
    assert after.flags == before.flags
    assert after.game_state.budget_remaining == before.game_state.budget_remaining - game.cash
    game.review()
    assert game.session().resource_reservations == after.resource_reservations


@pytest.mark.parametrize("changes", [{"medical_provider": " "}, {"recheck_interval_days": 0}, {"recheck_interval_days": 366}, {"employment_receiver": " "}, {"medical_fee_arrangement": "unlimited_cash"}])
def test_invalid_followup_attachment_is_rejected_without_mutation(game, changes):
    prepare_he(game)
    before = game.session()
    response = save_terms(game, followup_plan={**PLAN, **changes})
    assert response.status_code == 422
    assert game.session() == before


def test_partial_followup_can_be_saved_then_completed(game):
    prepare_he(game)
    response = save_terms(game, service_allocations={"lead_recheck_slot": 1, "stable_job_slot": 1},
                          followup_plan={"medical_provider": PLAN["medical_provider"]})
    assert response.status_code == 200, response.text
    contract = response.json()["contract"]
    assert contract["term_sheet"]["followup_plan"] == {"medical_provider": PLAN["medical_provider"]}
    assert "医疗费用承担方式：待补充" in contract["contract_text"]
    assert "按已分配医疗服务资源承担" not in contract["contract_text"]
    assert game.review()["contract"]["status"] != "signed"
    assert save_terms(game, followup_plan=PLAN).status_code == 200
    assert game.review()["contract"]["status"] == "signed"
