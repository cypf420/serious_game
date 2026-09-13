import pytest
from tests import test_story_review_round1 as helpers

@pytest.mark.parametrize('day,decision,option',[(22,'dp2_04','c'),(28,'dp2_08','a_b_c_d')])
def test_decision_reload_retry_and_day_end(day,decision,option):
    helper=helpers.StoryReviewRound1Tests()
    runtime,client,sid,headers=helper.build_api(f'feedback33-{day}')
    try:
        session=helper.reset_to_day(runtime,sid,headers,day)
        path=f'/api/game/session/{sid}'
        before=client.get(path+'/view',headers=headers).json()
        assert before['state']['pending_decision']['decision_id']==decision
        assert before['commands']['can_end_day'] is False
        assert client.get(path+'/view',headers=headers).json()==before
        result=helper.submit_decision(client,sid,headers,session,decision,option)
        after=client.get(path+'/view',headers=headers).json()
        assert (after['state'].get('pending_decision') or {}).get('decision_id') == ('dp2_09' if day == 28 else None)
        # Exact idempotent retry cannot duplicate consequence entries or effects.
        helper.submit_decision(client,sid,headers,session,decision,option)
        assert client.get(path+'/view',headers=headers).json()==after
        ids=[x['content_instance_id'] for x in helper.feed(client,sid,headers)]
        assert len(ids)==len(set(ids))
        if day == 28:
            pending=after['state']['pending_decision']
            next_session=runtime.sessions.get_owned(sid,headers['X-Account-ID'])
            next_option=next(x['option_id'] for x in pending['options'] if x['available'])
            result=helper.submit_decision(client,sid,headers,next_session,'dp2_09',next_option)
        entered=helper.end_day(client,sid,headers,result['state_version'],f'feedback33-{day}')
        assert entered['visible_state']['story']['day']==day+1
    finally:
        client.close()
