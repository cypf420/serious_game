import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / 'content/packages/pkg_gameplay_v3'

def decisions():
    return json.loads((PACKAGE / 'decisions.json').read_text(encoding='utf-8'))['decisions']

def option(decision_id, option_id):
    return next(o for d in decisions() if d['decision_id'] == decision_id for o in d['options'] if o['option_id'] == option_id)

def test_d5_b_has_response():
    text = option('dp1_03', 'b')['consequence']
    assert '袁桂兰' in text and '道谢' in text
    assert '最稳的一票' not in text

def test_all_options_have_distinct_outcomes_not_headings():
    rows = decisions()
    assert len(rows) == 81
    assert sum(len(d['options']) for d in rows) == 688
    for d in rows:
        for o in d['options']:
            assert o['consequence'] != o['text'], (d['decision_id'], o['option_id'])
            assert not o['consequence'].rstrip().endswith(('：', ':')), (d['decision_id'], o['option_id'])

def test_d84_all_permutations_have_complete_arrangements():
    d = next(d for d in decisions() if d['decision_id'] == 'dp6_07')
    assert len(d['options']) == 120
    for o in d['options']:
        assert '郑向东' in o['consequence']
        assert '后续' in o['consequence']

def test_late_character_continuity():
    d = next(d for d in decisions() if d['decision_id'] == 'dp6_09')
    assert '十一个' in d['options'][1]['text']
    assert '这些年' not in d['options'][3]['text']
