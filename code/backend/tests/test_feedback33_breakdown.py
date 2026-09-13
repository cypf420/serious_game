from copy import deepcopy
from math import ceil
from dataclasses import replace
from tests.test_contract_accounting import ContractAccountingTests


def test_detail_breakdown_is_read_only_and_matches_authoritative_totals():
    game = ContractAccountingTests()
    game.setUp()
    game.draft()
    for day in (75, 76):
        session = game.session()
        session.game_state = replace(session.game_state, story_day=day)
        game.save(session)
        before = deepcopy(game.session())
        response = game.client.get(game.base + f'/governance/contracts/{game.cid}', headers=game.headers)
        assert response.status_code == 200, response.text
        contract = response.json()['contract']
        detail = contract['compensation_breakdown']
        assert detail['suggested_base_total'] == contract['suggested_base_cash_amount']
        assert ceil(sum(row['amount'] for row in detail['rows'])) == detail['suggested_base_total']
        assert abs(sum(row['amount'] for row in detail['rows']) + detail['rounding_adjustment'] - detail['suggested_base_total']) < 1e-9
        assert detail['reward_available'] == (day <= 75)
        assert detail['saved_total'] == before.household_contracts[game.cid].term_sheet['cash_amount']
        assert game.session() == before
