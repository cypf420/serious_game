from copy import deepcopy
from dataclasses import replace

import pytest
from tests import test_story_review_round1 as helpers
from serious_game_backend.application.story_prose_round_two import secretary_opportunity


@pytest.mark.parametrize('day,phrases', [
    (31, ['下面请李县长代表县政府表个态', '笔尖悬在本子上方']),
    (32, ['问了就没下文了', '小罗，你这个箱子放回去', '下午三点']),
    (34, ['前天下午查账的事', '巡察组半个月就走', '第34天县长办公会']),
    (36, ['手里提着一只保温桶', '五百四十个家', '程序要走多久']),
    (64, ['五百米核心控制区', '你要动那道坡', '我今天就是来说清楚的']),
    (67, ['自家院门口劈柴', '把斧子放下', '到了村委会']),
    (71, ['英雄钢笔', '我没核过的，我不签', '现在有人替我认了']),
    (73, ['塑料皮的本子', '全村人一天要进来三回', '现在到底签了多少家']),
    (74, ['不是买药的', '就替我孙子把这笔账销了']),
    (75, ['首批进度名册', '书记办公室', '汇总表不能替代它']),
    (87, ['桌上那一圈人会先看他', '电话声', '你可以推门']),
    (88, ['装订机在办公室里响了一下午', '一份一份对得上']),
])
def test_restored_scenes_are_ordered_and_read_only(day, phrases):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f'round-two-{day}')
    try:
        session = helper.reset_to_day(runtime, sid, headers, day)
        before = deepcopy(session)
        items = runtime.story_flow.feed_since(session, 0)['items']
        prose = '\n'.join(x['text'] for x in items)
        positions = [prose.index(p) for p in phrases]
        assert positions == sorted(positions)
        assert session == before
        if day == 74:
            assert '一年四个疗程' not in prose
            assert '上回全村筛查那事,县里没瞒着' not in prose
        if day == 75:
            assert '进出七年' not in prose
        if day == 88:
            assert '明天不管怎么样，材料是真的' not in prose
    finally:
        client.close()


def test_day33_actual_conversation_prevents_day34_repeat():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('secretary-voluntary')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 33)
        session.contactable_npc_ids.add('npc_jiang_chongyue')
        session.known_npc_ids.add('npc_jiang_chongyue')
        runtime.sessions.save(session, expected_version=session.state_version)
        url = f'/api/game/session/{sid}/action'
        response = client.post(url, headers=headers, json={
            'input_mode':'conversation_start', 'client_action_id':'visit-secretary',
            'state_version':session.state_version,
            'opportunity_id':'opp_33_jiang_chongyue_contact', 'target_npc_id':'npc_jiang_chongyue',
        })
        assert response.status_code == 200, response.text
        session = runtime.sessions.get_owned(sid, headers['X-Account-ID'])
        text = '\n'.join(x['text'] for x in runtime.story_flow.feed_since(session,0)['items'])
        assert text.count('巡察组半个月就走') == 1
        opportunity = next(x for x in runtime.packages.get('pkg_gameplay_v3').interaction_opportunities
                           if x.opportunity_id == 'opp_33_jiang_chongyue_contact')
        assert '巡察组半个月就走' in secretary_opportunity(opportunity,session).opening_narrative
        assert secretary_opportunity(opportunity,session,starting=True) == opportunity
        session.active_conversation = None
        session.game_state = replace(session.game_state,story_day=34)
        runtime.story_flow.enter_current_day(session,runtime.packages.get('pkg_gameplay_v3'))
        items = runtime.story_flow.feed_since(session,0)['items']
        assert not any(x['block_id'] == 'd34_secretary_summons_1' for x in items)
        assert '\n'.join(x['text'] for x in items).count('巡察组半个月就走') == 1
    finally:
        client.close()


def test_day34_fallback_is_free_once_and_legacy_projection_keeps_cursors():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('secretary-fallback')
    try:
        session = helper.reset_to_day(runtime,sid,headers,34)
        before = deepcopy(session.game_state)
        runtime.story_flow.enter_current_day(session,runtime.packages.get('pkg_gameplay_v3'))
        assert session.game_state == before
        text = '\n'.join(x['text'] for x in runtime.story_flow.feed_since(session,0)['items'])
        assert text.count('巡察组半个月就走') == 1
        session.narrative_feed[:] = [x for x in session.narrative_feed if not (x.block_id or '').startswith('d34_secretary_summons_')]
        before = deepcopy(session)
        items = runtime.story_flow.feed_since(session,0)['items']
        meeting = next(x for x in items if x['block_id']=='d34_meeting')
        assert '巡察组半个月就走' in meeting['text']
        assert [x['cursor'] for x in items] == [x.cursor for x in session.narrative_feed]
        assert session == before
    finally:
        client.close()
