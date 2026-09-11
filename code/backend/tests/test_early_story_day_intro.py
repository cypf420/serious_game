from copy import deepcopy
from dataclasses import replace

import pytest
from tests import test_story_review_round1 as helpers


@pytest.mark.parametrize('day,flag,decision', [(19,'压下账目','dp2_03'),(21,'已立项审计','dp2_04')])
@pytest.mark.parametrize('triggered',[False,True])
def test_free_day_hint_accounts_for_early_story(day,flag,decision,triggered):
    helper = helpers.StoryReviewRound1Tests()
    runtime,client,sid,headers = helper.build_api(f'early-{day}-{triggered}')
    try:
        session=helper.reset_to_day(runtime,sid,headers,day,flags={flag} if triggered else set())
        intro=next(x for x in session.narrative_feed if x.content_instance_id==f'day:{day}:intro')
        assert ('可以自由安排行动' in intro.text) is (not triggered)
        if triggered:
            assert session.pending_decision.decision_id==decision
            assert intro.read_gate=='advance'
        else:
            assert session.pending_decision is None
            assert intro.read_gate=='free_action'
    finally:
        client.close()


@pytest.mark.parametrize('day,flag',[(19,'压下账目'),(21,'已立项审计')])
def test_legacy_free_hint_is_hidden_without_rewriting_save_or_cursor(day,flag):
    helper=helpers.StoryReviewRound1Tests()
    runtime,client,sid,headers=helper.build_api(f'legacy-early-{day}')
    try:
        session=helper.reset_to_day(runtime,sid,headers,day,flags={flag})
        session.narrative_feed[0]=replace(session.narrative_feed[0],text='今天没有必须处理的主线事项，可以自由安排行动。',read_gate='free_action')
        before=deepcopy(session)
        feed=runtime.story_flow.feed_since(session,0)
        assert not any('可以自由安排行动' in x['text'] for x in feed['items'])
        assert any(x['presentation_phase']=='decision' for x in feed['items'])
        assert feed['cursor']==session.next_feed_cursor-1
        assert [x['cursor'] for x in feed['items']]==[x.cursor for x in session.narrative_feed]
        assert session==before
    finally:
        client.close()
