"""Regression checks for independent story-review findings ST-01 through ST-03."""
from dataclasses import replace
import json
from unittest.mock import patch

import pytest
from tests import test_story_review_round1 as helpers
from serious_game_backend.application.evidence_guidance import source_opportunity
from serious_game_backend.application.luo_evidence import LUO_COPY_ID, is_copy_inquiry, luo_copy_context, record_luo_copy_inquiry
from serious_game_backend.domain.conversation import ActiveConversation
from serious_game_backend.application.reference_documents import meeting_display_title
from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord, MeetingRecord
from serious_game_backend.infrastructure.repositories.codec import encode_session, decode_session, dumps


def test_hearing_labels_survive_actual_sorted_json_save_and_another_same_day_record():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('review-hearing-roundtrip')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 50)
        for mid in ('meeting_ffffffffffffffffffff', 'meeting_11111111111111111111'):
            session.meetings[mid] = MeetingRecord(mid, 'a_'+mid, 50, '旧案听证', ('npc_tan_laoliu',), 'consensus', 'npc_tan_laoliu')
        before = {k: meeting_display_title(session, m) for k, m in session.meetings.items()}
        restored = decode_session(json.loads(dumps(encode_session(session))))
        after = {k: meeting_display_title(restored, m) for k, m in restored.meetings.items()}
        assert before == after
        assert len(set(before.values())) == 2
        assert all('记录号' in title and '次' not in title for title in before.values())
        restored.meetings['meeting_00000000000000000000'] = replace(next(iter(restored.meetings.values())), meeting_id='meeting_00000000000000000000')
        assert {k: meeting_display_title(restored, restored.meetings[k]) for k in before} == before
    finally:
        client.close()


@pytest.mark.parametrize('text', [
    '留底的事先别说，好吗？', '我今天不想讨论留底，可以吗？', '先不谈复印件，行吗？',
    '请问这箱子多少钱？', '厨房箱子在哪？', '复印件回头再谈，行吗？', '复印件不用给我看，可以吗？',
    '以后再核对底稿好吗？', '别再提那份副本，行吗？', '复印件是什么颜色？',
    '我今天不打算看留底材料，行吗？', '我知道你有复印件',
])
def test_declining_postponing_or_unrelated_material_words_do_not_acquire(text):
    assert not is_copy_inquiry(text)
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('review-no-copy')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32, flags={'见过原件'})
        for eid in ('one', 'two'):
            assert not record_luo_copy_inquiry(session, 'npc_luo_jian', text, eid)
        assert '罗健留底' not in session.flags
        assert not any(x.get('type') == 'luo_material_inquiry' for x in session.logs)
    finally:
        client.close()


@pytest.mark.parametrize('text', ['为什么留着箱子？', '你为什么还留着这个箱子？', '箱子里的复印件还留着吗？',
    '请问补偿明细的副本在哪里？', '能把补偿副本给我看吗？', '留底是谁保存的？', '你有副本吗？'])
def test_source_material_inquiries_remain_supported(text):
    assert is_copy_inquiry(text)


@pytest.mark.parametrize('day', [32, 42])
@pytest.mark.parametrize('text', [
    '血铅检测报告的复印件还留着吗？', '化验传真的副本在哪里？',
    '环评报告的底稿是谁保存的？', '儿童检测名册的复印件还在吗？',
    '房屋图纸的副本有没有留着？', '医院病历的复印件在哪里？',
    '补偿明细先放着，血铅报告的副本在哪里？',
])
def test_other_material_inquiry_neither_grants_compensation_copy_nor_changes_npc_topic(day, text):
    assert not is_copy_inquiry(text)
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('review-other-material')
    try:
        session = helper.reset_to_day(runtime, sid, headers, day, flags={'见过原件'})
        assert luo_copy_context(session, 'npc_luo_jian', text) == {}
        for eid in ('one', 'two'):
            assert not record_luo_copy_inquiry(session, 'npc_luo_jian', text, eid)
        assert '罗健留底' not in session.flags and LUO_COPY_ID not in session.archive_records
        assert not any(x.get('type') == 'luo_material_inquiry' for x in session.logs)
    finally:
        client.close()


@pytest.mark.parametrize('conversation_kind', ['ordinary', 'governance'])
def test_d42_compensation_copy_requires_named_material_or_immediate_same_conversation_reference(conversation_kind):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('review-d42-material-scope')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 42, flags={'见过原件'})
        ambiguous = '那份副本还留着吗？'
        assert luo_copy_context(session, 'npc_luo_jian', '今天收到化验传真了吗？') == {}
        assert luo_copy_context(session, 'npc_luo_jian', ambiguous) == {}
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', ambiguous, 'ambiguous')
        named = '补偿明细的复印件还留着吗？'
        # Older untyped inquiry logs do not prove which document was discussed.
        session.logs.append({'type': 'luo_material_inquiry', 'event_id': 'legacy', 'story_day': 42})
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', named, 'compensation-one')
        if conversation_kind == 'ordinary':
            conversation = ActiveConversation('luo-current', 'opp_31_luo_jian_contact', 'npc_luo_jian', 42)
            session.active_conversation = conversation
            player_key = 'speaker'
        else:
            conversation = GovernanceActionRecord('luo-current', 'cadre_interview', 42, ('npc_luo_jian',), ('1.1',))
            session.governance_actions[conversation.action_instance_id] = conversation
            player_key = 'speaker_type'
        # A previous accepted inquiry alone cannot establish the current topic.
        conversation.transcript.append({player_key: 'player', 'text': '血铅报告的副本还留着吗？'})
        assert luo_copy_context(session, 'npc_luo_jian', ambiguous) == {}
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', ambiguous, 'wrong-reference')
        conversation.transcript.append({player_key: 'player', 'text': '今天天气如何？'})
        assert luo_copy_context(session, 'npc_luo_jian', ambiguous) == {}
        conversation.transcript.append({player_key: 'player', 'text': named})
        assert luo_copy_context(session, 'npc_luo_jian', ambiguous)['confirm_copy_this_turn']
        assert record_luo_copy_inquiry(session, 'npc_luo_jian', ambiguous, 'compensation-two')
        assert '罗健留底' in session.flags and LUO_COPY_ID in session.archive_records
        assert luo_copy_context(session, 'npc_luo_jian', '化验报告的副本在哪里？') == {}
        assert not record_luo_copy_inquiry(session, 'npc_luo_jian', ambiguous, 'compensation-two')
    finally:
        client.close()


def test_early_luo_source_context_is_consistent_in_start_turn_exit_and_later_fax_window():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('review-early-luo')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 32)
        session.pending_decision = None
        runtime.sessions.save(session, expected_version=session.state_version)
        package = runtime.packages.get('pkg_gameplay_v3')
        original_opportunity = next(o for o in package.interaction_opportunities if o.opportunity_id == 'opp_31_luo_jian_contact')
        early = next(o for o in runtime.opportunities.list_available(session, package)
                     if o.opportunity_id == original_opportunity.opportunity_id)
        assert runtime.opportunities.require_available(original_opportunity.opportunity_id, session, package) == early
        assert '补偿明细' in early.opening_narrative and '化验' not in early.opening_narrative
        assert '补偿明细' in early.conversation_goal
        assert early.allowed_fact_ids == ('fact_false_signing',)
        started = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
            'input_mode':'conversation_start','client_action_id':'review-luo-start','state_version':session.state_version,
            'opportunity_id':early.opportunity_id,'target_npc_id':'npc_luo_jian'})
        assert started.status_code == 200, started.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        cid = session.active_conversation.conversation_id
        seen = []
        gateway = runtime.npc_turns._gateway
        run = gateway.run_turn
        def role(context):
            seen.append(context)
            return replace(run(context), input_relevance='relevant', conversation_state='continue')
        with patch.object(gateway, 'run_turn', side_effect=role):
            turn = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
                'input_mode':'free_text','client_action_id':'review-luo-first','state_version':session.state_version,
                'conversation_id':cid,'opportunity_id':early.opportunity_id,'target_npc_id':'npc_luo_jian',
                'player_text':'为什么留着箱子？'})
        assert turn.status_code == 200, turn.text
        assert seen[0].conversation_opening == early.opening_narrative
        assert seen[0].conversation_goal == early.conversation_goal
        assert set(seen[0].allowed_fact_ids) <= {'fact_false_signing'}
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        ended = client.post(f'/api/game/session/{sid}/action', headers=headers, json={
            'input_mode':'conversation_end','client_action_id':'review-luo-exit','state_version':session.state_version,
            'conversation_id':cid})
        assert ended.status_code == 200, ended.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        assert any(o.opportunity_id == early.opportunity_id for o in runtime.opportunities.list_available(session, package))
        session.game_state = replace(session.game_state, story_day=42)
        assert source_opportunity(original_opportunity, session) == original_opportunity
        assert runtime.opportunities.require_available(original_opportunity.opportunity_id, session, package) == original_opportunity
    finally:
        client.close()
