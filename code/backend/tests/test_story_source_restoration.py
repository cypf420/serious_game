"""Source-backed recovery through real story/API consumers, not a full 90-day run."""
import pytest

from tests import test_story_review_round1 as review


@pytest.fixture
def game(request):
    helper = review.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(request.node.name)
    try:
        yield helper, runtime, client, sid, headers
    finally:
        client.close()


def choose(game, did, oid):
    helper, runtime, client, sid, headers = game
    session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
    helper.submit_decision(client, sid, headers, session, did, oid)
    return runtime.sessions.get_owned(sid, headers['X-Account-ID'])


def feed(game):
    helper, _, client, sid, headers = game
    return helper.feed(client, sid, headers)


def test_wu_fixed_quotes_do_not_end_the_conversation_before_it_starts(game):
    helper, runtime, client, sid, headers = game
    s = helper.reset_to_day(runtime, sid, headers, 2)
    choose(game, s.pending_decision.decision_id, s.pending_decision.option_ids[0])
    items = feed(game)
    quote = next(i for i, b in enumerate(items) if '谁的话在谁面前好使' in b['text'])
    reference = next(i for i, b in enumerate(items) if '你把这句话记在心里' in b['text'])
    assert quote < reference
    assert items[quote]['speaker'] == '吴秀英'
    assert not any('拎着菜篮子径自走了' in b['text'] for b in items)
    refreshed = client.get(f'/api/game/session/{sid}/view?after=0', headers=headers).json()['feed']['items']
    assert items == refreshed


@pytest.mark.parametrize('completed', [False, True])
def test_wu_start_keeps_fixed_prologue_without_repeating_first_encounter(game, completed):
    helper, runtime, client, sid, headers = game
    s = helper.reset_to_day(runtime, sid, headers, 2)
    s = choose(game, s.pending_decision.decision_id, s.pending_decision.option_ids[0])
    response = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
        'input_mode': 'conversation_start', 'client_action_id': 'fixed-wu-start',
        'state_version': s.state_version, 'target_npc_id': 'npc_wu_xiuying',
        'opportunity_id': 'opp_d02_wu_xiuying_first_talk',
    })
    assert response.status_code == 200, response.text
    # No free_text submission and no generated reply: only real fixed feed blocks.
    text = '\n'.join(item['text'] for item in feed(game))
    assert text.count('吴秀英拎着一篮') == 1
    assert text.count('谁的话在谁面前好使') == 1
    assert '拎着菜篮子径自走了' not in text
    assert '你没有急着作答' in response.json()['narrative']
    s = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
    conversation_id = s.active_conversation.conversation_id
    if completed:
        # A persisted completed-disclosure state, not fabricated dialogue prose.
        s.active_conversation.turn_count = 1
        s.logs.append({'type': 'conversation_turn', 'conversation_id': conversation_id,
                       'disclosure_id': 'fact_clan_power_map'})
        runtime.sessions.save(s, expected_version=s.state_version)
    ended = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
        'input_mode': 'conversation_end', 'client_action_id': 'fixed-wu-end',
        'state_version': s.state_version, 'conversation_id': conversation_id,
    })
    assert ended.status_code == 200, ended.text
    ended_text = '\n'.join(item['text'] for item in feed(game))
    assert ended_text.count('拎着菜篮子径自走了') == int(completed)



def test_car_arrives_before_day17_choice(game):
    helper, runtime, _, sid, headers = game
    helper.reset_to_day(runtime, sid, headers, 17)
    items = feed(game)
    car = next(i for i, b in enumerate(items) if '窗外有车进院' in b['text'])
    decision = next(i for i, b in enumerate(items) if b['kind'] == 'decision')
    assert car < decision
    assert '宏达化工的车牌' in items[car]['text']


def test_luo_explains_evidence_before_disposal_without_replaying_it(game):
    helper, runtime, _, sid, headers = game
    s = helper.reset_to_day(runtime, sid, headers, 34)
    s = choose(game, 'dp3_03', s.pending_decision.option_ids[0])
    assert s.pending_decision.decision_id == 'dp3_04'
    items = feed(game)
    evidence = next(i for i, b in enumerate(items) if '这一份是原始数据' in b['text'])
    decision = next(i for i, b in enumerate(items) if b['kind'] == 'decision' and b['decision_id'] == 'dp3_04')
    assert evidence < decision
    assert items[evidence]['speaker'] == '罗健'
    assert any('铅超标。报告里写的是达标' in b['text'] for b in items[:decision])
    assert any('不交，我晚上睡不着' in b['text'] for b in items[:decision])
    choose(game, 'dp3_04', 'a')
    assert sum('这一份是原始数据' in b['text'] for b in feed(game)) == 1


def test_day59_advance_visit_precedes_main_arrival(game):
    helper, runtime, client, sid, headers = game
    helper.reset_to_day(runtime, sid, headers, 58)
    s = choose(game, 'dp4_09', 'a')
    helper.end_day(client, sid, headers, s.state_version, 'source-d59')
    s = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
    assert s.pending_decision.decision_id == 'ev4_04'
    before = [b for b in feed(game) if b['story_day'] == 59]
    assert any('五点十分' in b['text'] for b in before)
    assert not any('顾克明下车' in b['text'] for b in before)
    s = choose(game, 'ev4_04', 'a')
    assert s.pending_decision.decision_id == 'dp4_10'
    items = [b for b in feed(game) if b['story_day'] == 59]
    resolved = next(i for i, b in enumerate(items) if b['kind'] == 'consequence')
    arrived = next(i for i, b in enumerate(items) if '顾克明下车' in b['text'])
    assert resolved < arrived


def test_day61_introduces_worklist_without_resetting_pending_count(game):
    helper, runtime, _, sid, headers = game
    s = helper.reset_to_day(runtime, sid, headers, 61)
    text = '\n'.join(b['text'] for b in feed(game))
    for name in ('周奎元', '周满仓', '马长顺', '宁德海', '老倔头', '苗喜旺', '邓守本'):
        assert name in text
    assert all('十三户' not in o.text for o in s.pending_decision.options)
    choose(game, 'dp5_01', 'b')
    assert all('十三户' not in b['text'] for b in feed(game))


def test_legacy_return_does_not_resurrect_originals_or_apply_second_effect(game):
    helper, runtime, client, sid, headers = game
    before = helper.reset_to_day(runtime, sid, headers, 46)
    s = choose(game, 'dp4_01', 'e')
    assert s.pending_decision is None
    assert s.state_values['lead_roster_disposition'] == '未获取'
    assert s.game_state == before.game_state
    assert s.flags == before.flags
    assert not any(b['decision_id'] == 'dp4_roster_disposition' for b in feed(game))
    result = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
        'input_mode': 'decision', 'client_action_id': 'invalid-return-then-retain',
        'state_version': s.state_version, 'decision_id': 'dp4_roster_disposition', 'option_id': 'a',
    })
    assert result.status_code == 409
    package = runtime.packages.get('pkg_gameplay_v3')
    # Restoring/re-presenting the same skipped node must be idempotent.
    snapshot = (dict(s.state_values), list(s.logs), list(s.narrative_feed))
    runtime.story_flow._present_decision_id(s, package, 'dp4_roster_disposition')
    assert s.pending_decision is None
    assert snapshot == (dict(s.state_values), list(s.logs), list(s.narrative_feed))


@pytest.mark.parametrize('option', ['a', 'b', 'c', 'd'])
def test_reporting_choices_still_allow_independent_original_custody(game, option):
    helper, runtime, _, sid, headers = game
    helper.reset_to_day(runtime, sid, headers, 46, known_fact_ids={'fact_lead_census'})
    s = choose(game, 'dp4_01', option)
    assert s.pending_decision.decision_id == 'dp4_roster_disposition'
    assert set(s.pending_decision.option_ids) == {'a', 'b', 'c', 'd', 'e'}
    s = choose(game, 'dp4_roster_disposition', 'e')
    assert s.state_values['lead_roster_disposition'] == '未获取'


def test_published_return_routes_do_not_later_demand_an_unowned_original(game):
    from tests.test_story_routes_v3 import WITNESS_PROFILE_PATH
    from tools.full_acceptance.ending_witnesses import load_witnesses
    helper, runtime, _, sid, headers = game
    helper.reset_to_day(runtime, sid, headers, 46)
    returned = choose(game, 'dp4_01', 'e')
    s = helper.reset_to_day(runtime, sid, headers, 83,
                            flags=set(returned.flags), known_fact_ids=set(returned.known_fact_ids))
    assert s.state_values['lead_roster_disposition'] == '未获取'
    for profile in load_witnesses(WITNESS_PROFILE_PATH):
        if profile.decision_policy.get('dp4_01') == 'e':
            assert profile.decision_policy['dp6_06'] in s.pending_decision.option_ids, profile.route_id
