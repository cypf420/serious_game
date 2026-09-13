from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace as NS

from tests import test_story_review_round1 as helpers
from tests.test_reference_documents import fixture
from serious_game_backend.application.archive_investigation_service import eligible_definitions
from serious_game_backend.application.archive_investigation_service import (
    COMPENSATION_ORIGINAL, apply_original_archive_read, materialize_for_read,
)
from serious_game_backend.application.luo_evidence import luo_copy_context, record_luo_copy_inquiry, LUO_COPY_ID
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.reference_documents import resolve_references
from serious_game_backend.application.reference_documents import hearing_facts
from serious_game_backend.domain.errors import ActionUnavailableError
import pytest
from serious_game_backend.application.npc_relationship_service import NPCRelationshipService
from serious_game_backend.application.reference_documents import catalog
from serious_game_backend.domain.gameplay_governance import MeetingRecord


def test_original_is_normally_available_but_comparison_does_not_grant_it():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('final-original')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32, known_fact_ids={'fact_false_signing'})
        package = runtime.packages.get('pkg_gameplay_v3')
        option = next(o for o in session.pending_decision.options if o.option_id == 'a')
        assert not option.available
        assert '原件' in option.unavailable_reason
        assert any(x.archive_id == 'archive_compensation_detail_original' for x in eligible_definitions(session, package))
        assert option.next_steps[0]['archive_id'] == 'archive_compensation_detail_original'
    finally:
        client.close()


def test_hearing_titles_distinguish_same_topic_same_day_and_preserve_reference_ids():
    session, package, project = fixture()
    for n in (1, 2):
        session.meetings[str(n)] = MeetingRecord(str(n), f'action{n}', 50, '旧案核对', ('tan',), 'consensus', 'tan')
    docs = [d for d in catalog(session, package, project) if d['source_kind'] == 'meeting']
    assert len({d['title'] for d in docs}) == 2
    assert all('第50日' in d['title'] and '讨论中' in d['title'] for d in docs)
    assert {d['id'] for d in docs} == {'meeting:1', 'meeting:2'}


def test_relationship_reasons_deduplicate_one_event_but_keep_distinct_events():
    event = dict(type='relationship_change', npc_id='tan', visible_to_player=True,
                 story_day=50, reason='公开协商改善了合作。', dimension='attitude')
    session = NS(logs=[dict(event, event_id='one'), dict(event, event_id='one'), dict(event, event_id='two')])
    reasons = NPCRelationshipService.recent_visible_change_reasons(session, 'tan')
    assert len(reasons) == 2
    assert len(set(reasons)) == 2
    assert all('第50日' in r for r in reasons)


def test_day51_repeated_money_choices_have_distinct_consequences_and_same_effect_count():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('final-day51')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 51)
        for n in range(3):
            response = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
                'input_mode': 'decision', 'client_action_id': f'final-money-{n}',
                'state_version': session.state_version, 'decision_id': 'dp4_04', 'option_id': 'b'})
            assert response.status_code == 200, response.text
            session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        before = deepcopy(session)
        consequences = [x for x in runtime.story_flow.feed_since(session, 0)['items']
                        if x['decision_id'] == 'dp4_04' and x['kind'] == 'consequence']
        assert len(consequences) == 3
        assert len({x['text'] for x in consequences}) == 3
        assert len({x['content_instance_id'] for x in consequences}) == 3
        assert session == before
        assert len([l for l in session.logs if l.get('type') == 'decision' and l.get('option_id') == 'b']) == 3
    finally:
        client.close()


def test_original_read_and_luo_copy_are_separate_atomic_evidence_events():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('final-luo')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32)
        package = runtime.packages.get('pkg_gameplay_v3')
        assert any(o.npc_id == 'npc_luo_jian' for o in runtime.opportunities.list_available(session, package))
        record = materialize_for_read(session, COMPENSATION_ORIGINAL)
        apply_original_archive_read(session, record.archive_id)
        assert '见过原件' not in session.flags
        record.read_at_days.append(32)
        apply_original_archive_read(session, record.archive_id)
        session.known_fact_ids.add('fact_false_signing')
        assert 'a' in StoryFlowService.current_pending_decision(session, package).option_ids
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', '为什么留着箱子？', 'inquiry-1')
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', '为什么留着箱子？', 'inquiry-1')
        assert '罗健留底' not in session.flags
        for text in ('不用找副本', '我不问留底', '我知道你有复印件', '请不要找复印件好吗？'):
            assert not record_luo_copy_inquiry(session, 'npc_luo_jian', text, 'negative-'+text)
            assert not luo_copy_context(session, 'npc_luo_jian', text)['confirm_copy_this_turn']
        assert luo_copy_context(session, 'npc_luo_jian', '箱子里的复印件还留着吗？')['confirm_copy_this_turn']
        assert record_luo_copy_inquiry(session, 'npc_luo_jian', '箱子里的复印件还留着吗？', 'inquiry-2')
        assert '罗健留底' in session.flags
        assert LUO_COPY_ID in session.archive_records
        assert '不是环评或儿童检测名册' in session.archive_records[LUO_COPY_ID].content
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', '箱子里的复印件还留着吗？', 'inquiry-3')
    finally:
        client.close()


@pytest.mark.parametrize('disposition, phrase', [('己方封存', None), ('呈交上级', '移交上级'),
    ('交给记者', '已经交给记者'), ('被销毁', '已被销毁'), ('未获取', '未留取')])
def test_roster_guidance_matches_actual_custody(disposition, phrase):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('final-roster')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 56, known_fact_ids={'fact_lead_census'})
        session.state_values['lead_roster_disposition'] = disposition
        option = next(o for o in StoryFlowService.current_pending_decision(session, runtime.packages.get('pkg_gameplay_v3')).options if o.option_id == 'a')
        assert option.available == (phrase is None)
        if phrase:
            assert phrase in option.unavailable_reason
            assert option.next_steps == ()
    finally:
        client.close()


def test_saved_housing_reference_is_household_and_version_scoped():
    session, package, project = fixture()
    session.household_contracts = {'c': NS(contract_id='c', batch_id='b', household_id='WU-01',
        signatory_name='吴秀英', signatory_npc_id='tan', status='draft', current_version=2,
        versions=[NS(version=1), NS(version=2)], term_sheet={'housing_resource_id':'housing1','housing_delivery_day':55})}
    session.contract_batches = {}
    package.governance_config = {'resource_pools':[{'resource_id':'housing1','category':'housing','name':'东侧安置房',
                                                  'available_day':50,'attributes':{'area_m2':65,'accessible':True}}]}
    before = deepcopy(session)
    docs = resolve_references(session, package, ['housing_plan:c'], ['tan'], project)
    assert docs[0]['version'] == 2
    assert '65平方米' in docs[0]['body']
    assert '不是建筑测绘原图' in docs[0]['body']
    with pytest.raises(ActionUnavailableError):
        resolve_references(session, package, ['housing_plan:c'], ['other'], project)
    assert session == before


def test_hearing_does_not_complete_old_case_or_create_a_legal_review_button():
    session, _package, _project = fixture()
    session.game_state = NS(story_day=50)
    session.meetings = {'m': MeetingRecord('m', 'action', 50, '旧案听证', ('npc_tan_laoliu',), 'consensus', 'npc_tan_laoliu', status='resolved')}
    session.governance_actions = {'action': NS(variant_id='public_hearing', status='completed')}
    result = hearing_facts(session, 'npc_tan_laoliu')
    assert result['records'][0]['status'] == 'completed'
    assert not result['old_case_resolved']
    assert '没有独立的' in result['legal_review_interpretation']
    assert '待后续依法复核' in result['next_step']
    session.flags.add('旧案了结')
    result = hearing_facts(session, 'npc_tan_laoliu')
    assert result['old_case_resolved']
    assert '已有旧案书面结果' in result['next_step']
