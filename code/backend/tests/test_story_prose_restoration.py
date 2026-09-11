from copy import deepcopy
from dataclasses import replace

import pytest

from tests.test_story_review_round1 import StoryReviewRound1Tests


@pytest.mark.parametrize('day,phrases', [
    (2, ['你走到门口时', '他在背后又说了一句']),
    (5, ['连给娃看病的落脚地都没了', '低头去收碗']),
    (7, ['上一任领导都是放手让下面办的', '会议室里好几双眼睛']),
    (11, ['谁先签谁是明白人', '今天这场我盯着']),
    (13, ['跑岔了，好心也能办出乱子']),
    (17, ['我在这个位置上坐了九年', '送到您手里，我就干净了']),
    (18, ['规矩我懂。我不是来要活的', '先给后拿', '赵县长上个礼拜说']),
    (20, ['您去不去，我都不往外说', '他的手在抖', '烟灰落在他的裤子上']),
    (22, ['我只负责送', '人还站在里面', '约两公里']),
    (89, ['你坐在他右手边第一个位子', '十几双眼睛同时转过来']),
])
def test_restored_prose_precedes_decisions_without_changing_state(day, phrases):
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f'prose-{day}')
    try:
        session = helper.reset_to_day(runtime, sid, headers, day)
        before = deepcopy(session)
        response = client.get(f'/api/game/session/{sid}/view', headers=headers)
        assert response.status_code == 200, response.text
        items = response.json()['feed']['items']
        text = '\n'.join(item['text'] for item in items)
        for phrase in phrases:
            assert phrase in text
            if session.pending_decision:
                gate = next(i for i, x in enumerate(items) if x['presentation_phase'] == 'decision')
                assert any(phrase in x['text'] for x in items[:gate])
        assert runtime.sessions.get_owned(sid, headers['X-Account-ID']) == before
        if day == 17:
            assert text.index('送到您手里，我就干净了') < text.index('窗外有车进院')
        if day == 22:
            assert '十二公里' not in text and '二零一九年建的' not in text
    finally:
        client.close()


def test_day18_phone_branch_never_gains_an_office_visit():
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('prose-phone')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 18, flags={'与钱伟撕破脸'})
        items = runtime.story_flow.feed_since(session, 0)['items']
        assert any(item['block_id'] == 'd18_phone_pressure' for item in items)
        assert not any(item['block_id'] in {'d18_qian_arrival', 'd18_qian_offer', 'd18_box'} for item in items)
        assert '先给后拿' not in '\n'.join(item['text'] for item in items)
    finally:
        client.close()


def test_day62_first_visit_is_before_day63_and_is_not_duplicated():
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('prose-first-visit')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 62)
        package = runtime.packages.get('pkg_gameplay_v3')
        before = deepcopy(session.game_state)
        runtime.story_flow.enter_current_day(session, package)
        assert session.game_state == before
        items = runtime.story_flow.feed_since(session, 0)['items']
        text = '\n'.join(item['text'] for item in items)
        assert text.count('我不是谁的叔') == 1
        assert text.count('可以自由安排行动') == 1
        assert text.index('我不是谁的叔') < text.index('可以自由安排行动')
        assert all(item['story_day'] == 62 for item in items)
        assert session.pending_decision is None
        session.game_state = replace(session.game_state, story_day=63)
        runtime.story_flow.enter_current_day(session, package)
        text = '\n'.join(item['text'] for item in runtime.story_flow.feed_since(session, 0)['items'])
        assert text.index('我不是谁的叔') < text.index('你又去了祠堂')
        assert text.count('我不是谁的叔') == 1
    finally:
        client.close()


def test_old_day62_feed_is_projected_without_cursor_or_save_mutation():
    helper = StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api('prose-old-save')
    try:
        session = helper.reset_to_day(runtime, sid, headers, 62)
        session.narrative_feed[:] = [replace(session.narrative_feed[0], text='第62日，今天没有必须处理的主线事项，可以自由安排行动。')]
        session.next_feed_cursor = 2
        before = deepcopy(session)
        feed = runtime.story_flow.feed_since(session, 0)
        assert len(feed['items']) == 1 and feed['cursor'] == 1
        item = feed['items'][0]
        assert item['cursor'] == 1 and item['content_instance_id'] == 'day:62:intro'
        assert '我不是谁的叔' in item['text'] and item['kind'] == 'narration'
        assert item['scene_id'] == 'C04_S04'
        assert runtime.story_flow.feed_since(session, 1)['items'] == []
        assert session == before
    finally:
        client.close()
