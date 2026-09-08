"""Author-approved continuity through player-facing API, using isolated test sessions."""
import pytest

from tests.test_story_source_restoration import game, choose, feed


@pytest.mark.parametrize('day', [38, 53])
def test_settled_old_debt_is_not_presented_as_unpaid(game, day):
    h, r, c, sid, headers = game
    h.reset_to_day(r, sid, headers, day, flags={'旧案了结'})
    text = '\n'.join(b['text'] for b in feed(game))
    assert '十一万八' in text and '已' in text
    assert '履约' in text
    assert '差出来的钱至今没影' not in text
    assert '多年未解决的占地材料' not in text


@pytest.mark.parametrize('flags,facts,want,success', [
    (set(), set(), '没有核实', False),
    ({'旧账缺口已坐实'}, set(), '尚未支付', True),
    (set(), {'fact_original_vouchers'}, '没有核实', False),
    (set(), {'fact_tan_land_arrears'}, '尚未支付', True),
    ({'旧案了结'}, set(), '已经收到', True),
    ({'旧案了结','旧账缺口已坐实'}, {'fact_tan_land_arrears'}, '已经收到', True),
])
def test_day53_reply_matches_evidence_without_payment_or_auto_contract(game, flags, facts, want, success):
    h, r, c, sid, headers = game
    s = h.reset_to_day(r, sid, headers, 53, flags=flags, known_fact_ids=facts)
    assert 'a' in s.pending_decision.option_ids
    before = (s.game_state.budget_remaining, s.game_state.signed_households)
    s = choose(game, 'dp4_06', 'a')
    text = '\n'.join(b['text'] for b in feed(game) if b['kind'] == 'consequence')
    assert want in text
    assert '谭老六' in text and '你说' in text
    assert ('谭老六已安抚' in s.flags) == success
    assert ('谭老六被空口应付' in s.flags) == (not success)
    assert (s.game_state.budget_remaining, s.game_state.signed_households) == before
    assert s.pending_decision is None
    assert feed(game) == c.get(f'/api/game/session/{sid}/view?after=0', headers=headers).json()['feed']['items']


@pytest.mark.parametrize('day,did,option', [(38,'dp3_06',o) for o in 'abcd'] + [(53,'dp4_06',o) for o in 'bcd'])
def test_all_settled_followups_retain_settlement(game, day, did, option):
    h, r, _, sid, headers = game
    h.reset_to_day(r, sid, headers, day, flags={'旧案了结'})
    s = choose(game, did, option)
    text = '\n'.join(b['text'] for b in feed(game) if b['kind'] == 'consequence')
    assert '履约' in text
    assert '那笔旧账没有解决' not in text
    assert '旧案了结' in s.flags


def test_day11_ill_husband_does_not_work_away_from_home(game):
    h, r, _, sid, headers = game
    h.reset_to_day(r, sid, headers, 11)
    s = choose(game, 'dp1_06', 'a')
    text = '\n'.join(b['text'] for b in feed(game) if b['kind'] == 'consequence')
    assert '卧床' in text and '照护' in text
    assert '外头做工' not in text
    assert '袁桂兰已建立信任' in s.flags


def test_reading_actual_old_land_archive_while_pending_enables_evidenced_reply(game):
    h, r, c, sid, headers = game
    s = h.reset_to_day(r, sid, headers, 53)
    before_points = s.game_state.action_points
    payload = dict(state_version=s.state_version, action_kind='inspect_archives',
                   variant_id='consult_county_archives', location_id='loc_county_government',
                   archive_ids=['archive_tan_land_arrears'])
    response = c.post(f'/api/game/session/{sid}/governance/actions', headers=headers, json=payload)
    assert response.status_code == 201, response.text
    s = r.sessions.get_owned(sid, headers['X-Account-ID'])
    assert s.game_state.action_points == before_points - 2
    assert 'fact_tan_land_arrears' in s.known_fact_ids
    assert s.pending_decision.decision_id == 'dp4_06'
    response = c.get(f'/api/game/session/{sid}/governance/archives/archive_tan_land_arrears', headers=headers)
    assert response.status_code == 200, response.text
    s = r.sessions.get_owned(sid, headers['X-Account-ID'])
    assert s.game_state.action_points == before_points - 2
    choose(game, 'dp4_06', 'a')
    assert any('尚未支付' in b['text'] for b in feed(game) if b['kind']=='consequence')


@pytest.mark.parametrize('flags,facts', [({'旧案了结'},set()),(set(),{'fact_tan_land_arrears'})])
def test_action_response_and_refresh_show_same_branch(game, flags, facts):
    h, r, c, sid, headers = game
    s = h.reset_to_day(r, sid, headers, 53, flags=flags, known_fact_ids=facts)
    response = c.post(f'/api/game/session/{sid}/action', headers=headers, json={
        'input_mode':'decision','client_action_id':'author-reply-consistency',
        'state_version':s.state_version,'decision_id':'dp4_06','option_id':'a'})
    assert response.status_code == 200, response.text
    result = next(b['text'] for b in feed(game) if b['kind']=='consequence')
    assert response.json()['narrative'] == result


def test_day59_city_reply_is_not_assigned_to_county_finance_chief(game):
    h, r, _, sid, headers = game
    s = h.reset_to_day(r, sid, headers, 59)
    option = next(o for o in s.pending_decision.options if o.option_id == 'd')
    assert '市里回复' in option.text and '冯敬之' not in option.text


@pytest.mark.parametrize('flags,want', [(set(),'市里定的中口径'),({'两百万抹平'},'市里定的松口径'),({'宏达行贿在录'},'市里定的紧口径'),({'宏达行贿在录','两百万抹平'},'市里定的紧口径')])
def test_city_reply_sets_exactly_one_actual_response(game, flags, want):
    h, r, _, sid, headers = game
    h.reset_to_day(r, sid, headers, 59, flags=flags)
    s = choose(game, 'dp4_10', 'd')
    assert s.flags & {'市里定的中口径','市里定的松口径','市里定的紧口径'} == {want}


def test_ending18_does_not_backdate_suppression(game):
    _, r, _, _, _ = game
    p = r.packages.get('pkg_gameplay_v3')
    text = next(e.text for e in p.main_endings if e.ending_id == 'ending_18')
    assert '第八十一天' not in text and '连面都没再见' not in text
    assert '压稿之后' in text


def test_ending20_retains_received_reports(game):
    _, r, _, _, _ = game
    p = r.packages.get('pkg_gameplay_v3')
    text = next(e.text for e in p.main_endings if e.ending_id == 'ending_20')
    assert '第二十二日' in text and '体检汇总' in text
    assert '你先写个材料' not in text and '在楼道里堵住你' not in text


def test_conflict_appendix_uses_actual_conflict_not_unintroduced_prop(game):
    from serious_game_backend.application.ending_service import EndingService
    from types import SimpleNamespace
    for flags in [{'暴力驱逐'}, {'秀英寒心'}, set()]:
        session = SimpleNamespace(flags=flags, state_values={})
        # Exercise actual appendix selection, not a comparison with the constants.
        items = EndingService._appendices(session, game[1].packages.get('pkg_gameplay_v3'))
        assert all('那根绳子' not in str(item) for item in items)


def test_package_source_pin_identifies_the_edited_script(game):
    import hashlib
    from content.editorial.story_author_revision import source_path
    package = game[1].packages.get('pkg_gameplay_v3')
    assert package.source_sha256 == 'sha256:' + hashlib.sha256(source_path().read_bytes()).hexdigest()


def test_all_approved_ending_paragraphs_reach_runtime(game):
    import json
    from content.editorial.story_author_revision import REGISTRY
    rows = json.loads(REGISTRY.read_text(encoding='utf8'))['replacements']
    endings = {e.ending_id:e.text for e in game[1].packages.get('pkg_gameplay_v3').main_endings}
    for row in rows:
        if 12480 <= row['line'] <= 12680:
            ending = 'ending_18' if row['line'] < 12600 else 'ending_20'
            assert row['after'] in endings[ending], (ending, row['line'])
