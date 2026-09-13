"""Contract schemes, negotiation retries and legacy preservation through real APIs."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests import test_contract_accounting as fixtures


@pytest.fixture
def game():
    f = fixtures.ContractAccountingTests()
    f.setUp()
    return f


def save_terms(f, terms=None, **extra):
    terms = dict(terms or f.session().household_contracts[f.cid].term_sheet)
    for key in ('policy_minimum_cash', 'payment_timing'):
        terms.pop(key, None)
    return f.client.put(f.base + f'/governance/contracts/{f.cid}/terms',
                        headers=f.headers,
                        json={'state_version': f.session().state_version, **terms, **extra})


def test_generated_contract_needs_no_writer_or_auditor(game):
    original = game.runtime.gameplay_governance._gateway.run_governance_task
    tasks = []
    def run(context):
        tasks.append(context.task)
        assert context.task not in ('draft_contract', 'audit_contract')
        return original(context)
    with patch.object(game.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=run):
        result = game.draft()
    text = result['contract']['contract_text']
    assert '第60日' in text
    assert '安置' in text
    assert 'housing_d1_120' not in text
    assert 'doc_compensation_policy_v1' not in text
    assert 'lead_recheck_slot' not in text
    assert '结构化' not in text
    assert result['contract']['audit_status'] == 'not_required'


def test_policy_reward_is_automatic_without_a_frontend_switch(game):
    game.draft()
    response = save_terms(game, public_window_reward=None, cash_amount=game.cash + 2)
    assert response.status_code == 200, response.text
    contract = response.json()['contract']
    assert contract['term_sheet']['public_window_reward'] is True
    assert contract['suggested_cash_amount'] == game.cash + 2
    assert '公开签约奖励' not in contract['contract_text']
    assert '不另行支付' in contract['contract_text']


def test_excess_cash_is_reported_at_the_cash_input(game):
    game.draft()
    response = save_terms(game, cash_amount=game.cash + 21)
    assert response.status_code == 409
    assert '补偿调整批文' in response.json()['error']['details']['field_errors']['cash_amount']


@pytest.mark.parametrize('day,eligible', [(75, True), (76, False)])
def test_omitted_reward_uses_current_policy_deadline(game, day, eligible):
    from dataclasses import replace
    game.draft()
    session = game.session()
    session.game_state = replace(session.game_state, story_day=day)
    game.save(session)
    terms = dict(session.household_contracts[game.cid].term_sheet)
    for key in ('policy_minimum_cash', 'payment_timing', 'public_window_reward'):
        terms.pop(key, None)
    response = save_terms(game, terms=terms, move_out_day=83,
                          housing_delivery_day=83, cash_amount=game.cash + 2)
    assert response.status_code == 200, response.text
    assert response.json()['contract']['term_sheet']['public_window_reward'] is eligible


def test_unchanged_scheme_is_idempotent_and_preserves_feedback(game):
    game.draft(missing_grave=True)
    game.review()
    before = deepcopy(game.session())
    response = save_terms(game)
    assert response.status_code == 200, response.text
    assert game.session() == before
    assert response.json()['contract']['review_reason']


def test_body_edit_is_retired_without_mutation(game):
    game.draft()
    before = deepcopy(game.session())
    response = game.client.put(game.base + f'/governance/contracts/{game.cid}/text',
                               headers=game.headers,
                               json={'state_version': before.state_version, 'text': '新增补偿999万元'})
    assert response.status_code == 409
    assert '修改方案' in response.text
    assert game.session() == before


def test_explanation_then_current_visit_turn_can_resubmit_same_version(game):
    game.draft(missing_grave=True)
    seen = []
    def review(context):
        seen.append(context)
        return SimpleNamespace(model_id="test-ai", data={'decision': 'explain', 'reason': '我想再聊聊。', 'counteroffer': {}})
    with patch.object(game.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=review):
        first = game.review()
        again = game.review()
        assert len(seen) == 1
        assert not again['contract']['can_review']
        s = game.session()
        s.governance_actions[game.action_id].transcript.append({'speaker_type': 'player', 'text': '我们先一起核实搬迁安排。'})
        game.save(s)
        second = game.review()
    # Conversation alone does not alter authoritative signing eligibility or
    # constitute another paid attempt under the final-check acceptance rules.
    assert len(seen) == 1
    assert first['contract']['current_version'] == second['contract']['current_version']
    assert second['contract']['review_version'] == second['contract']['current_version']
    assert first['contract']['review_reason'] == second['contract']['review_reason']
    assert second['contract']['status'] != 'signed'
    assert 'review_fingerprint' not in str(second)


def test_feedback_version_changes_only_with_scheme(game):
    game.draft(missing_grave=True)
    reviewed = game.review()['contract']
    terms = dict(reviewed['term_sheet']); terms['cash_amount'] += 1
    response = save_terms(game, terms)
    assert response.status_code == 200, response.text
    current = response.json()['contract']
    assert current['current_version'] == reviewed['current_version'] + 1
    assert current['review_reason'] == ''
    assert current['review_history'][-1]['version'] == reviewed['current_version']
    assert current['can_review']


def test_unsigned_legacy_text_requires_acknowledgement_and_is_retained(game):
    game.draft()
    s = game.session()
    version = s.household_contracts[game.cid].versions[-1]
    version.created_by = 'player'; version.text = '原有特殊约定：上门协助搬迁。'
    game.save(s)
    before = deepcopy(game.session())
    assert save_terms(game).status_code == 409
    assert game.session() == before
    response = save_terms(game, acknowledge_legacy_text=True)
    assert response.status_code == 200, response.text
    contract = response.json()['contract']
    assert not contract['legacy_draft']
    assert contract['legacy_versions'][0]['text'] == version.text
    assert '上门协助搬迁' not in contract['contract_text']


def test_resource_shortage_is_detected_while_saving_without_spending(game):
    game.draft()
    s = game.session()
    from serious_game_backend.domain.gameplay_governance import ResourceReservation
    s.resource_reservations.append(ResourceReservation('exhaust', 'contract', 'other', 'housing_d1_120', 7, 'allocated', 10))
    game.save(s)
    before = deepcopy(game.session())
    response = save_terms(game)
    assert response.status_code == 409
    assert 'housing_resource_id' in response.json()['error']['details']['field_errors']
    assert game.session() == before


def test_review_rejects_a_different_preview_version(game):
    game.draft()
    before = deepcopy(game.session())
    game.post(f'/governance/contracts/{game.cid}/review', {'expected_contract_version': 99}, 409)
    assert game.session() == before


def test_transition_needed_for_delivery_after_move_out(game):
    game.draft()
    terms = dict(game.session().household_contracts[game.cid].term_sheet)
    terms.update(move_out_day=20, housing_delivery_day=60, transition_months=0)
    response = save_terms(game, terms)
    assert response.status_code == 409
    assert '过渡' in response.text


def test_accessible_housing_context_contains_confirmed_attributes(game):
    game.draft()
    terms = dict(game.session().household_contracts[game.cid].term_sheet)
    terms['housing_resource_id'] = 'housing_d1_120_accessible'
    response = save_terms(game, terms)
    assert response.status_code == 200, response.text
    assert '无障碍' in response.json()['contract']['contract_text']
    seen = []
    def review(context):
        seen.append(context)
        return SimpleNamespace(model_id="test-ai", data={'decision': 'explain', 'reason': '我想去看看。', 'counteroffer': {}})
    with patch.object(game.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=review):
        game.review()
    assert len(seen) == 1
    assert seen[0].actor_context["selected_housing"]["attributes"]["accessible"]
    assert game.session().household_contracts[game.cid].status == 'signed'


def test_signed_legacy_read_does_not_rewrite_original(game):
    game.draft(); game.review()
    s = game.session(); c = s.household_contracts[game.cid]
    c.versions[-1].created_by = 'historical'; c.versions[-1].text = '历史原文 D60 保留。'
    game.save(s); before = deepcopy(game.session())
    response = game.client.get(game.base + f'/governance/contracts/{game.cid}', headers=game.headers)
    assert response.status_code == 200
    assert response.json()['contract']['contract_text'] == '历史原文 D60 保留。'
    assert not response.json()['contract']['legacy_draft']
    assert game.session() == before


def test_representative_visit_receives_current_independent_contract_and_answer(game):
    game.draft()
    result = SimpleNamespace(model_id="test-ai", data={'decision': 'explain', 'reason': '先说清楚安置安排。', 'counteroffer': {}})
    svc = game.runtime.gameplay_governance
    with patch.object(svc._gateway, 'run_governance_task', return_value=result):
        game.review()
    seen = []
    original = svc._npc_turns.run
    def turn(context, *args, **kwargs):
        seen.append(context)
        return original(context, *args, **kwargs)
    with patch.object(svc._npc_turns, 'run', side_effect=turn):
        game.post(f'/governance/actions/{game.action_id}/turn', {'player_text': '请解释这份合同的安置安排。'})
    contracts = seen[0].visible_world_context['own_contracts']
    current = next(c for c in contracts if c['household_id'] == 'ZDS-03')
    assert '先说清楚安置安排。' in str(current['reviews'])
    assert '第60日' in current['contract_text']
    assert current['selected_housing']['name']
    assert current['current_version'] == 1
    assert 'review_fingerprint' not in str(contracts)


def test_unrelated_visit_cannot_reroll_a_rejection(game):
    game.draft(missing_grave=True); game.review()
    s = game.session()
    from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord
    s.governance_actions['unrelated'] = GovernanceActionRecord(
        'unrelated', 'household_visit', 10, ('npc_tan_laoliu',), (),
        transcript=[{'speaker_type': 'player', 'text': '无关的私下谈话'}])
    game.save(s)
    before = deepcopy(game.session())
    with patch.object(game.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=AssertionError('must not reroll')):
        result = game.review()
    assert not result['contract']['can_review']
    assert game.session() == before


def test_same_scheme_save_can_recover_damaged_draft_hash(game):
    game.draft()
    s = game.session(); s.household_contracts[game.cid].versions[-1].text_hash = 'damaged'
    game.save(s)
    result = save_terms(game)
    assert result.status_code == 200
    assert result.json()['contract']['current_version'] == 2
    assert game.review()['contract']['status'] == 'signed'


def test_cross_day_signature_records_actual_payment_date_in_terms_and_hash(game):
    from dataclasses import replace
    game.draft()
    s = game.session(); s.game_state = replace(s.game_state, story_day=11)
    game.save(s)
    game.review()
    saved = game.session(); contract = saved.household_contracts[game.cid]
    assert contract.term_sheet['payment_day'] == contract.signed_day == 11
    assert contract.versions[-1].term_hash == game.runtime.gameplay_governance._hash(contract.term_sheet)
    assert saved.household_settlement_entries[-1].resource_details['payment_day'] == 11


def test_authorization_shortage_points_to_approval_selection(game):
    game.draft()
    s = game.session()
    s.administrative_documents['doc_compensation_policy_v1'].resolution_snapshot = {
        'resource_authorization_limits': {'budget:property_land': 1}}
    game.save(s)
    terms = dict(s.household_contracts[game.cid].term_sheet)
    terms['approval_document_ids'] = ['doc_compensation_policy_v1']
    response = save_terms(game, terms)
    assert response.status_code == 409
    assert 'approval_document_ids' in response.json()['error']['details']['field_errors']


def test_actual_viewing_unlocks_same_scheme_after_nonacceptance(game):
    from dataclasses import replace
    s = game.session(); s.game_state = replace(s.game_state, story_day=50)
    s.known_npc_ids.add('npc_lao_juetou'); s.encountered_npc_ids.add('npc_lao_juetou')
    game.save(s)
    game.draft(npc='npc_lao_juetou', household_id='LAO-01')
    first = game.review()['contract']
    assert first['status'] != 'signed'
    assert not first['can_review']
    game.post(f'/governance/actions/{game.action_id}/turn', {'player_text': '我们现在去看合同里这套可入住的安置房，好吗？'})
    second = game.review()['contract']
    assert second['status'] == 'signed'
    assert second['current_version'] == first['current_version']
