import json
from pathlib import Path

from tools.export_player_story import build_export
from tools.story_revision import enumerate_visible_records
from serious_game_backend.application.ending_prose import revise_ending_prose

PACKAGE = Path(__file__).resolve().parents[1] / 'content/packages/pkg_gameplay_v3'

def test_every_registered_player_string_and_runtime_appendix_is_exported():
    markdown, coverage = build_export(PACKAGE)
    expected = enumerate_visible_records(PACKAGE)
    assert set(coverage['package_ids']) == {r['review_id'] for r in expected}
    assert len(coverage['package_ids']) == len(expected)
    assert len(set(coverage['runtime_ids'])) == len(coverage['runtime_ids'])
    assert len([i for i in coverage['runtime_ids'] if i.startswith('ending:')]) == 12
    for record in expected:
        text = revise_ending_prose(record['text']) if record['file'] == 'ending_rules.json' else record['text']
        assert text in markdown, record['review_id']

def test_source_option_and_ending_counts_independent_of_exporter():
    markdown, coverage = build_export(PACKAGE)
    docs = json.loads((PACKAGE/'decisions.json').read_text(encoding='utf8'))
    assert sum(len(d['options']) for d in docs['decisions']) == 688
    assert coverage['counts'] == {'days':90,'decisions':81,'options':688,'main_endings':24,'sub_endings':95}
    for decision in docs['decisions']:
        for option in decision['options']:
            assert option['consequence'] in markdown
    assert '注册清单，不是单条实际游玩路线' in markdown
    assert '周满仓核心矛盾已缓解' in markdown

def test_runtime_repeated_offer_copy_is_not_missing_from_export():
    markdown,coverage=build_export(PACKAGE)
    assert '见他没有还价，你把补偿数又往上提了一次。' in markdown
    assert '你把补偿数提到第三次，要求他当场给个答复。' in markdown
    assert {'decision:dp4_04:b:round-2','decision:dp4_04:b:round-3'} <= set(coverage['runtime_ids'])


def test_fixed_conversation_closure_export_explains_its_actual_playback_gate():
    markdown, _ = build_export(PACKAGE)
    marker = 'interaction_opportunities.json/opportunities/0/completion_blocks/0/text'
    section = markdown.split(marker, 1)[1].split('### ', 1)[0]
    assert '玩家正常结束' in section
    assert 'NPC 主动离场时不叠加' in section
    assert '模拟回复不属于本剧情' in markdown
