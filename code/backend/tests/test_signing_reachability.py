from dataclasses import replace
from unittest.mock import patch

from tests.test_contract_workflow_v2 import game, save_terms
from serious_game_backend.application.contract_requirements import contract_requirement_feedback


def test_wu03_can_sign_using_only_available_scheme_fields(game):
    session = game.session()
    session.known_npc_ids.add('npc_wu_xiuying')
    session.encountered_npc_ids.add('npc_wu_xiuying')
    game.save(session)
    original_put = game.client.put
    def put(path, **kwargs):
        if path.endswith('/terms'):
            kwargs['json']['housing_resource_id'] = 'housing_d1_140'
        return original_put(path, **kwargs)
    with patch.object(game.client, 'put', side_effect=put):
        game.draft(npc='npc_wu_xiuying', household_id='WU-03')
    before = game.session().game_state.budget_remaining
    first = game.review()['contract']
    assert first['status'] != 'signed'
    assert game.session().game_state.budget_remaining == before
    response = save_terms(game, service_allocations={'lead_recheck_slot': 1, 'school_transition_seat': 1})
    assert response.status_code == 200, response.text
    with patch.object(game.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=AssertionError('no extra model veto')):
        result = game.review()['contract']
    assert result['status'] == 'signed'
    assert game.session().game_state.budget_remaining == before - game.cash
    game.review()
    assert game.session().game_state.budget_remaining == before - game.cash


def test_decline_mentions_one_concern_not_an_operation_checklist():
    text = contract_requirement_feedback(['医疗复检或评估资源未落实', '就学衔接资源未落实'])
    assert '身体' in text
    assert '学业' not in text
    for forbidden in ('修改方案', '配套服务', '1.', '必须', '写明', '治疗费用', '复检名额'):
        assert forbidden not in text
