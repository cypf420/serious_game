"""Stage boundaries for the early Luo evidence route, including real-model regressions."""
from dataclasses import asdict, replace
from unittest.mock import patch

import pytest
from tests import test_story_review_round1 as helpers
from serious_game_backend.domain.conversation import ForcedGroupConversation
from serious_game_backend.application.npc_context_visibility import stage_role_setting, stage_unresolved_demands


@pytest.mark.parametrize('day', [32, 42])
def test_ordinary_luo_context_only_contains_current_stage_profile_and_demands(day):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f'luo-stage-{day}')
    try:
        session = helper.reset_to_day(runtime, sid, headers, day, known_fact_ids={'fact_false_signing'})
        session.pending_decision = None
        session.pending_decision_queue.clear()
        runtime.sessions.save(session, expected_version=session.state_version)
        base = f'/api/game/session/{sid}'
        start = client.post(base+'/action', headers=headers, json={
            'state_version': session.state_version, 'input_mode': 'conversation_start',
            'client_action_id': 'stage-start', 'opportunity_id': 'opp_31_luo_jian_contact',
            'target_npc_id': 'npc_luo_jian'})
        assert start.status_code == 200, start.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        seen = []
        gateway = runtime.npc_turns._gateway
        original = gateway.run_turn
        def capture(context):
            seen.append(context)
            return original(context)
        with patch.object(gateway, 'run_turn', side_effect=capture):
            response = client.post(base+'/action', headers=headers, json={
                'state_version': session.state_version, 'input_mode': 'free_text',
                'client_action_id': 'stage-question', 'opportunity_id': 'opp_31_luo_jian_contact',
                'conversation_id': session.active_conversation.conversation_id,
                'target_npc_id': 'npc_luo_jian', 'player_text': '补偿明细的两个标准是怎么核对的？'})
        assert response.status_code == 200, response.text
        context = seen[0]
        profile = next(p for p in runtime.packages.get('pkg_gameplay_v3').npc_profiles if p.npc_id == 'npc_luo_jian')
        if day == 32:
            assert not context.unresolved_demands
            assert not context.visible_world_context['unresolved_demands']
            assert all(word not in context.role_setting for word in ('监测', '血铅', '化验', '患儿', '复印件'))
            assert '补偿' in context.role_setting and '县医院' in context.role_setting
            assert context.allowed_fact_ids == ('fact_false_signing',)
        else:
            assert context.role_setting == profile.role_setting
            assert any('患儿' in demand for demand in context.unresolved_demands)
            assert '化验' in context.conversation_opening
    finally:
        client.close()


def test_early_group_luo_does_not_receive_future_medical_persona():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('luo-group-stage')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32, known_fact_ids={'fact_false_signing'})
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.active_group_conversation = ForcedGroupConversation(
            conversation_id='luo-group-stage', conversation_type='cadre_meeting',
            initiator_npc_id='npc_sun_qiang', participant_ids=('npc_luo_jian', 'npc_sun_qiang'),
            agenda='核对补偿明细与经手材料', demands=('核对两个补偿标准',), urgency='high', story_day=32,
            status='active', followup_plan_id='followup_d10_county_reporting')
        runtime.sessions.save(session, expected_version=session.state_version)
        seen = []
        gateway = runtime.group_conversations._gateway
        original = gateway.run_night_turn
        def capture(context):
            seen.append(context)
            return original(context)
        with patch.object(gateway, 'run_night_turn', side_effect=capture):
            response = client.post(f'/api/game/session/{sid}/group-conversation/turn', headers=headers, json={
                'state_version': session.state_version, 'client_action_id': 'luo-group-turn',
                'player_text': '请罗健说明同年两个补偿标准的核对经过，孙强核对经手台账。'})
        assert response.status_code == 200, response.text
        luo = next(c for c in seen if c.npc_id == 'npc_luo_jian')
        assert all(word not in luo.role_setting for word in ('监测', '血铅', '化验', '患儿'))
        assert '补偿' in luo.role_setting
    finally:
        client.close()


@pytest.mark.parametrize('known_fact', ['fact_lead_census', 'fact_lead_287'])
def test_known_medical_evidence_keeps_real_demand_without_unlocking_full_future_profile(known_fact):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('luo-known-medical')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32, known_fact_ids={known_fact})
        package = runtime.packages.get('pkg_gameplay_v3')
        luo = next(p for p in package.npc_profiles if p.npc_id == 'npc_luo_jian')
        before_profile = asdict(luo)
        before_states = {key: dict(value) for key, value in session.npc_demand_states.items()}
        demand = next(d.description for d in package.npc_demands if d.npc_id == luo.npc_id)
        assert stage_unresolved_demands(session, package, luo.npc_id) == (demand,)
        assert '监测' not in stage_role_setting(session, luo)
        assert session.known_fact_ids == {known_fact}
        assert asdict(luo) == before_profile and session.npc_demand_states == before_states
        for profile in package.npc_profiles:
            if profile.npc_id != 'npc_luo_jian':
                assert stage_role_setting(session, profile) == profile.role_setting
        session.game_state = replace(session.game_state, story_day=42)
        assert stage_role_setting(session, luo) == luo.role_setting
        assert stage_unresolved_demands(session, package, luo.npc_id) == (demand,)
        session.npc_demand_states['demand_luo_jian']['status'] = 'satisfied'
        assert stage_unresolved_demands(session, package, luo.npc_id) == ()
    finally:
        client.close()
