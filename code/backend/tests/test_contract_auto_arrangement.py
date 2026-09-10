from tests.test_contract_workflow_v2 import game


def save_auto(game, housing="housing_d60_120", **extra):
    return game.client.put(game.base + f"/governance/contracts/{game.cid}/terms", headers=game.headers,
        json={"state_version": game.session().state_version, "auto_arrange": True,
              "policy_document_id": "doc_compensation_policy_v1", "cash_amount": game.cash + 2,
              "housing_resource_id": housing, "service_allocations": {"lead_recheck_slot": 1}, **extra})


def test_auto_schedule_total_and_signature_accounting(game):
    game.draft()
    before = game.session()
    response = save_auto(game)
    assert response.status_code == 200, response.text
    contract = response.json()["contract"]
    terms = contract["term_sheet"]
    assert terms["move_out_day"] == 30
    assert terms["housing_delivery_day"] == 60
    assert terms["transition_months"] == 1
    automatic = terms["automatic_arrangement"]
    assert automatic["transition_cash_amount"] > 0
    assert terms["cash_amount"] == automatic["base_cash_amount"] + automatic["transition_cash_amount"]
    assert sum(automatic["budget_allocations"].values()) == terms["cash_amount"]
    assert game.session().game_state.budget_remaining == before.game_state.budget_remaining
    again = save_auto(game)
    assert again.status_code == 200
    assert again.json()["contract"]["current_version"] == contract["current_version"]
    result = game.review()
    assert result["contract"]["status"] == "signed"
    assert game.session().game_state.budget_remaining == before.game_state.budget_remaining - terms["cash_amount"]
    after = game.session()
    game.review()
    assert game.session().game_state.budget_remaining == after.game_state.budget_remaining


def test_current_housing_has_no_transition_supplement(game):
    game.draft()
    response = save_auto(game, "housing_d1_120", move_out_day=89, housing_delivery_day=1, transition_months=12, budget_envelope="risk_reserve")
    assert response.status_code == 200, response.text
    terms = response.json()["contract"]["term_sheet"]
    assert terms["move_out_day"] == terms["housing_delivery_day"] == 30
    assert terms["transition_months"] == 0
    assert terms["cash_amount"] == game.cash + 2
    assert terms["budget_envelope"] == "property_land"


def test_no_housing_does_not_invent_delivery(game):
    game.draft()
    response = save_auto(game, None)
    assert response.status_code == 200, response.text
    assert response.json()["contract"]["term_sheet"]["transition_months"] == 0
    assert "交房日期" not in response.json()["contract"]["contract_text"]


def test_total_budget_shortage_including_supplement_is_atomic(game):
    from dataclasses import replace
    game.draft()
    state = game.session()
    state.game_state = replace(state.game_state, budget_remaining=game.cash + 2)
    game.save(state)
    before = game.session()
    response = save_auto(game)
    assert response.status_code == 409, response.text
    assert game.session() == before


def test_month_rounding_and_day_90_cap(game):
    from dataclasses import replace
    from serious_game_backend.application.contract_arrangement import arrange_contract
    game.draft()
    session = game.session()
    package = game.runtime.packages.get("pkg_gameplay_v3")
    contract = session.household_contracts[game.cid]
    for day, expected_months in [(9, 2), (10, 1), (39, 1), (40, 0), (89, 0)]:
        session.game_state = replace(session.game_state, story_day=day)
        terms, _ = arrange_contract(session, package, contract, {"cash_amount": 40, "housing_resource_id": "housing_d60_120"})
        assert terms["transition_months"] == expected_months
        assert terms["move_out_day"] <= 90
        assert terms["housing_delivery_day"] >= terms["move_out_day"]
