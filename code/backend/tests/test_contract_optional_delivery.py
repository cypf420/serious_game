from tests.test_contract_workflow_v2 import game, save_terms


def test_no_housing_omits_delivery_date_without_a_delivery_promise(game):
    game.draft()
    terms = dict(game.session().household_contracts[game.cid].term_sheet)
    terms['housing_resource_id'] = None
    terms.pop('housing_delivery_day')
    response = save_terms(game, terms)
    assert response.status_code == 200, response.text
    contract = response.json()['contract']
    assert contract['term_sheet']['housing_delivery_day'] == terms['move_out_day']
    assert '交房日期' not in contract['contract_text']
    assert '不采用实物安置' in contract['contract_text']


def test_housing_still_requires_delivery_date(game):
    game.draft()
    terms = dict(game.session().household_contracts[game.cid].term_sheet)
    terms.pop('housing_delivery_day')
    response = save_terms(game, terms)
    assert response.status_code == 409
    assert 'housing_delivery_day' in response.json()['error']['details']['field_errors']


def test_housing_cannot_be_delivered_before_its_opening_day(game):
    game.draft()
    response = save_terms(game, housing_resource_id='housing_d30_140', housing_delivery_day=20)
    assert response.status_code == 409
    assert 'housing_delivery_day' in response.json()['error']['details']['field_errors']
