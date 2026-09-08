"""Regression cases from independent six-chapter editorial review."""
from tools.build_story_integrity_candidate import revise
from tests.test_story_integrity_mechanics import baseline

def test_original_is_not_resurrected_on_day78():
    docs,_ = revise(baseline())
    d = next(d for d in docs['decisions.json']['decisions'] if d['decision_id']=='dp6_03')
    assert 'lead_roster_disposition' not in d['options'][2]['effects']['state_assignments']

def test_all_sorting_feedback_preserves_every_order_position():
    docs,_ = revise(baseline())
    for d in docs['decisions.json']['decisions']:
        if d.get('input_kind') != 'sorting': continue
        labels=d['input_schema']['labels']
        for o in d['options']:
            sequence='、'.join(labels[k] for k in o['option_id'].split('_'))
            assert sequence in o['consequence'], (d['decision_id'],o['option_id'])

def test_named_character_and_material_boundaries():
    docs,_ = revise(baseline())
    ds={d['decision_id']:d for d in docs['decisions.json']['decisions']}
    bs={b['story_day']:b for b in docs['story_beats.json']['beats']}
    assert '孙强' not in str(ds['ev5_03'])
    assert '真实数字是零' not in ds['dp2_07']['prompt']
    assert '这几年的交情' not in str(ds['dp5_10'])
    assert '第一次进入' not in str(bs[42])
    assert '带回省里' not in str(bs[60])
    assert '重新录入' in ds['dp4_08']['options'][2]['consequence']
    assert '前期协调' in ds['dp4_09']['presentation_blocks'][0]['text']
    assert '手写' in ds['dp5_05']['presentation_blocks'][0]['text']
    assert '复印件放在桌上' not in ds['dp3_08']['options'][1]['consequence']
    assert '去向' in bs[83]['opening_blocks'][0]['text']
    assert all(len(o['consequence'])>60 for o in ds['dp4_roster_disposition']['options'][:3])
    assert '复印件' in ds['dp4_09']['options'][3]['consequence']
    assert '夹页复印件' in ds['dp4_09']['options'][4]['consequence']
    assert '复制这一条' in ds['dp5_05_recovery']['presentation_blocks'][0]['text']
    assert '原始凭证摊在班子会上' not in ds['dp6_04']['options'][0]['consequence']
    assert '原件保住了，却还没有进入正式核查' not in ds['dp6_04']['options'][2]['consequence']
    assert '核查却尚未展开' not in ds['dp6_05']['options'][2]['consequence']
    assert '宏达化工那几座锈红色的旧厂房' not in str(bs[1])
    assert '四十一户' not in str(bs[49])
    assert '四十一个孩子' in str(bs[49])
