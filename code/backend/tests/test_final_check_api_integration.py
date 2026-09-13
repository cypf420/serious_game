"""Run from integrated backend cwd with PYTHONPATH=src;.; controlled role only."""
from dataclasses import replace
from unittest.mock import patch

from tests import test_story_review_round1 as fixtures
from serious_game_backend.application.archive_investigation_service import ORIGINAL_ARCHIVE_ID
from serious_game_backend.application.luo_evidence import LUO_COPY_ID


def test_normal_original_read_then_luo_followup_through_real_api():
    helper = fixtures.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('final-integrated-original-luo')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32, known_fact_ids={'fact_false_signing'})
        base = f'/api/game/session/{sid}'
        assert '见过原件' not in session.flags
        locked = next(o for o in session.pending_decision.options if o.option_id == 'a')
        assert not locked.available and locked.next_steps[0]['archive_id'] == ORIGINAL_ARCHIVE_ID
        actions = client.get(base+'/actions', headers=headers).json()['actions']
        variant = next(v for a in actions for v in a['variants']
                       if any(t.get('target_id') == ORIGINAL_ARCHIVE_ID for t in v['target_choices']))
        read = client.post(base+'/governance/actions', headers=headers, json={
            'state_version':session.state_version, 'action_kind':'inspect_archives',
            'variant_id':variant['variant_id'], 'location_id':variant['location_choices'][0]['location_id'],
            'archive_ids':[ORIGINAL_ARCHIVE_ID]})
        assert read.status_code == 201, read.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        assert '见过原件' in session.flags
        assert 'a' in read.json()['visible_state']['pending_decision']['option_ids']
        chosen = client.post(base+'/action', headers=headers, json={
            'input_mode':'decision', 'client_action_id':'final-integrated-choice',
            'state_version':session.state_version, 'decision_id':'dp3_02','option_id':'a'})
        assert chosen.status_code == 200, chosen.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        descriptors = client.get(base+'/opportunities', headers=headers).json()['person_actions']
        descriptor = next(d for d in descriptors if d['npc_id']=='npc_luo_jian' and d['action_id']=='cadre_interview')
        started = client.post(base+'/governance/actions', headers=headers, json={
            'state_version':session.state_version, 'action_kind':descriptor['action_id'],
            'variant_id':descriptor['variant_id'], 'location_id':descriptor['legal_location_ids'][0],
            'target_ids':['npc_luo_jian'], 'topic':'核对柳林村补偿明细和经手材料'})
        assert started.status_code == 201, started.text
        aid = started.json()['action']['action_instance_id']
        service = runtime.gameplay_governance
        gateway = service._npc_turns._gateway
        original = gateway.run_turn
        contexts = []
        def role(context):
            contexts.append(context)
            confirm = context.visible_world_context.get('compensation_evidence', {}).get('confirm_copy_this_turn')
            return replace(original(context), input_relevance='relevant',
                           dialogue='我家中还留有一份复印件。' if confirm else '表上都写着，你具体问。')
        for n, text in enumerate(('为什么留着箱子？','不用找副本','箱子里的复印件还留着吗？')):
            session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
            before_version = session.state_version
            with patch.object(gateway,'run_turn',side_effect=role):
                result = client.post(base+f'/governance/actions/{aid}/turn', headers=headers,
                    json={'state_version':before_version,'player_text':text})
            assert result.status_code == 200, result.text
            session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
            assert ('罗健留底' in session.flags) == (n==2)
        assert LUO_COPY_ID in session.archive_records
        assert contexts[-1].visible_world_context['compensation_evidence']['confirm_copy_this_turn']
        assert len([l for l in session.logs if l.get('type')=='luo_material_inquiry']) == 2
        retry = client.post(base+f'/governance/actions/{aid}/turn', headers=headers,
                    json={'state_version':before_version,'player_text':'箱子里的复印件还留着吗？'})
        # The turn lease replays an already committed identical request.
        assert retry.status_code == 200
        assert retry.json() == result.json()
        after = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        assert after.archive_records == session.archive_records
        assert after.game_state == session.game_state
    finally:
        client.close()
