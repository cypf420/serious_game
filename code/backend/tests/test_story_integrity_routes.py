from dataclasses import replace
import json
from pathlib import Path

import pytest

from serious_game_backend.application.story_flow_service import StoryFlowService, should_skip_permit_reissue
from tests import test_story_review_round1 as round1

PACKAGE = Path(__file__).resolve().parents[1] / 'content/packages/pkg_gameplay_v3'

def test_permit_predicate_preserves_defective_and_unissued_routes():
    assert should_skip_permit_reissue('dp5_09', {'祠堂地块批文已签发'})
    assert not should_skip_permit_reissue('dp5_08', {'祠堂地块批文已签发'})
    assert not should_skip_permit_reissue('dp5_09', set())
    assert not should_skip_permit_reissue('dp5_09', {'祠堂地块批文已签发', '用地手续有瑕疵'})

def test_d44_interview_queue():
    beats = json.loads((PACKAGE / 'story_beats.json').read_text(encoding='utf8'))['beats']
    by_day = {b['story_day']: b for b in beats}
    assert 'dp3_08' not in by_day[43]['decision_ids']
    assert by_day[44]['decision_ids'] == ['dp3_08', 'dp3_09']
    assert by_day[45]['decision_ids'] == ['dp3_10']

def test_d69_success_requires_success_flag():
    beats = json.loads((PACKAGE / 'story_beats.json').read_text(encoding='utf8'))['beats']
    beat = next(b for b in beats if b['story_day'] == 69)
    success = next(b for b in beat['opening_blocks'] if b['block_id'] == 'd69_source_opening')
    assert '周满仓核心矛盾已缓解' in success['required_flags']
    assert any('周满仓核心矛盾已缓解' in b.get('forbidden_flags', []) for b in beat['opening_blocks'])

@pytest.mark.parametrize('disposition', ['未获取','呈交上级','交给记者','被销毁','己方封存'])
def test_roster_original_visibility(disposition):
    helper = round1.StoryReviewRound1Tests()
    container, client, sid, headers = helper.build_api('roster-'+disposition.encode().hex())
    session = container.sessions.get_owned(sid, headers['X-Account-ID'])
    package = container.packages.get('pkg_gameplay_v3')
    session.state_values['lead_roster_disposition'] = disposition
    session.pending_decision = None
    StoryFlowService._present_decision_id(session, package, 'dp4_07')
    assert ('a' in session.pending_decision.option_ids) == (disposition == '己方封存')
    client.close()

def test_valid_permit_skip_is_idempotent_and_does_not_apply_effects():
    helper = round1.StoryReviewRound1Tests()
    container, client, sid, headers = helper.build_api('permit')
    session = container.sessions.get_owned(sid, headers['X-Account-ID'])
    package = container.packages.get('pkg_gameplay_v3')
    session.game_state = replace(session.game_state, story_day=74)
    session.flags.add('祠堂地块批文已签发')
    before = session.game_state
    session.pending_decision = None
    session.pending_decision_queue = ['dp5_09']
    flow = StoryFlowService()
    flow.present_next_decision(session, package)
    flow.present_next_decision(session, package)
    assert session.pending_decision is None
    assert session.game_state == before
    items = [i for i in flow.feed_since(session, 0)['items'] if i['content_instance_id'] == 'permit:already-issued']
    assert len(items) == 1
    assert '无需重复' in items[0]['text']
    client.close()

@pytest.mark.parametrize('day,did,oid', [(5,'dp1_03','b'),(10,'ev1_03','a'),(31,'dp3_01','d'),(84,'dp6_07','a_b_c_d_e')])
def test_resolved_full_consequence_survives_api_incremental_and_refresh(day,did,oid):
    """Real action API from controlled day fixtures; not a 90-day legal replay."""
    helper = round1.StoryReviewRound1Tests()
    container, client, sid, headers = helper.build_api('complete-'+did)
    session = helper.reset_to_day(container,sid,headers,day)
    package = container.packages.get('pkg_gameplay_v3')
    if not session.pending_decision or session.pending_decision.decision_id != did:
        session.pending_decision = None
        StoryFlowService._present_decision_id(session,package,did)
        container.sessions.save(session,expected_version=session.state_version)
    cursor = session.next_feed_cursor-1
    parameters = {'order':['a','b','c','d','e']} if day == 84 else None
    helper.submit_decision(client,sid,headers,session,did,oid,parameters=parameters)
    full = client.get(f'/api/game/session/{sid}/feed?after=0',headers=headers).json()['items']
    delta = client.get(f'/api/game/session/{sid}/feed?after={cursor}',headers=headers).json()['items']
    refreshed = client.get(f'/api/game/session/{sid}/view?after=0',headers=headers).json()['feed']['items']
    def outcome(items): return next(i for i in items if i['kind']=='consequence' and i['decision_id']==did)
    assert outcome(full) == outcome(delta) == outcome(refreshed)
    expected = package.decisions[did].option(oid).consequence
    assert expected in outcome(full)['text']
    assert len({i['content_instance_id'] for i in full}) == len(full)
    latest = client.get(f'/api/game/session/{sid}/feed?after={full[-1]["cursor"]}',headers=headers).json()['items']
    assert latest == []
    client.close()

def test_all_688_registered_consequences_are_emitted_whole_by_story_flow():
    """Serialization coverage only; availability and legal reachability tested separately."""
    from copy import deepcopy
    from dataclasses import replace
    from serious_game_backend.domain.events import PendingDecision
    helper = round1.StoryReviewRound1Tests()
    container, client, sid, headers = helper.build_api('all-copy')
    session = container.sessions.get_owned(sid,headers['X-Account-ID'])
    package = container.packages.get('pkg_gameplay_v3')
    flow = StoryFlowService()
    initial_session = deepcopy(session)
    count = 0
    for decision in package.decisions.values():
        for option in decision.options:
            session = deepcopy(initial_session)
            session.flags = set(option.required_flags) | set(option.required_any_flags)
            session.state_values = dict(option.required_state_values)
            clauses = (option, *option.availability_any[:1])
            for clause in clauses:
                session.flags.update(clause.required_flags | clause.required_any_flags)
                session.state_values.update(clause.required_state_values)
                for key, value in {**clause.minimum_ledger_values, **clause.maximum_ledger_values}.items():
                    if hasattr(session.game_state, key):
                        session.game_state = replace(session.game_state, **{key: value})
            # This test covers serialization, with each option's evidence prerequisites met.
            session.known_fact_ids = set(option.required_fact_ids) | set(option.required_any_fact_ids)
            session.pending_decision = PendingDecision(event_instance_id=f'copy-{decision.decision_id}-{option.option_id}',decision_id=decision.decision_id,option_ids=(option.option_id,))
            cursor = session.next_feed_cursor-1
            assert option.option_id in flow.current_pending_decision(session, package).option_ids, (decision.decision_id, option.option_id)
            expected = decision.visible_consequence(option, session.flags, session.known_fact_ids)
            flow.resolve_decision(session,package,decision_id=decision.decision_id,option_id=option.option_id)
            item = next(i for i in flow.feed_since(session,cursor)['items'] if i['kind']=='consequence')
            assert expected in item['text'], (decision.decision_id,option.option_id)
            count += 1
    assert count == 688
    client.close()

@pytest.mark.parametrize('disposition', ['未获取','呈交上级','交给记者','被销毁','己方封存'])
def test_day78_choice_preserves_original_custody_through_real_api(disposition):
    helper=round1.StoryReviewRound1Tests()
    container,client,sid,headers=helper.build_api('d78-'+disposition.encode().hex())
    session=helper.reset_to_day(container,sid,headers,78)
    session.state_values['lead_roster_disposition']=disposition
    container.sessions.save(session,expected_version=session.state_version)
    helper.submit_decision(client,sid,headers,session,'dp6_03','c')
    stored=container.sessions.get_owned(sid,headers['X-Account-ID'])
    assert stored.state_values['lead_roster_disposition']==disposition
    client.close()

def test_actual_day56_handoff_prevents_second_original_delivery_at83():
    helper=round1.StoryReviewRound1Tests()
    container,client,sid,headers=helper.build_api('handoff-through83')
    session=helper.reset_to_day(container,sid,headers,56)
    session.state_values['lead_roster_disposition']='己方封存'
    session.pending_decision=None
    package=container.packages.get('pkg_gameplay_v3')
    StoryFlowService._present_decision_id(session,package,'dp4_07')
    container.sessions.save(session,expected_version=session.state_version)
    helper.submit_decision(client,sid,headers,session,'dp4_07','a')
    stored=container.sessions.get_owned(sid,headers['X-Account-ID'])
    assert stored.state_values['lead_roster_disposition']=='交给记者'
    session=helper.reset_to_day(container,sid,headers,83,flags=stored.flags)
    assert 'a' not in session.pending_decision.option_ids
    assert '去向' in '\n'.join(i['text'] for i in helper.feed(client,sid,headers))
    client.close()

@pytest.mark.parametrize('choice,defective,skipped',[('a',False,True),('b',False,False),('a',True,False)])
def test_day52_permit_choice_controls_day74_after_pediatric_decision(choice,defective,skipped):
    helper=round1.StoryReviewRound1Tests()
    container,client,sid,headers=helper.build_api('permit-chain-'+choice+str(defective))
    session=helper.reset_to_day(container,sid,headers,52)
    helper.submit_decision(client,sid,headers,session,'dp4_05',choice)
    flags=set(container.sessions.get_owned(sid,headers['X-Account-ID']).flags)
    if defective: flags.add('用地手续有瑕疵')
    session=helper.reset_to_day(container,sid,headers,74,flags=flags)
    assert session.pending_decision.decision_id=='dp5_08'
    helper.submit_decision(client,sid,headers,session,'dp5_08','a')
    stored=container.sessions.get_owned(sid,headers['X-Account-ID'])
    assert (stored.pending_decision is None)==skipped
    if not skipped: assert stored.pending_decision.decision_id=='dp5_09'
    receipts=[i for i in helper.feed(client,sid,headers) if i['content_instance_id']=='permit:already-issued']
    assert len(receipts)==int(skipped)
    client.close()

@pytest.mark.parametrize('choice,deferred',[('c',True),('a',False)])
def test_day11_actual_choice_selects_day12_opening(choice,deferred):
    helper=round1.StoryReviewRound1Tests()
    container,client,sid,headers=helper.build_api('defer-'+choice)
    session=helper.reset_to_day(container,sid,headers,11)
    helper.submit_decision(client,sid,headers,session,'dp1_06',choice)
    stored=container.sessions.get_owned(sid,headers['X-Account-ID'])
    session=helper.reset_to_day(container,sid,headers,12,flags=stored.flags)
    text='\n'.join(i['text'] for i in helper.feed(client,sid,headers))
    assert ('尚未生效的拟签材料' in text)==deferred
    client.close()
