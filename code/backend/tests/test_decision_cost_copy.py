from types import SimpleNamespace

import pytest

from serious_game_backend.application.story_flow_service import StoryFlowService


@pytest.mark.parametrize('text,expected', [
    ('依礼迁坟迁祠（0 点）', '依礼迁坟迁祠。'),
    ('压缩仪程，先把坟起了（0 点）', '压缩仪程，先把坟起了。'),
    ('下强制清场的令，连夜动手（强制清场 6 点）', '下强制清场的令，连夜动手。'),
    ('让坟户原地留守，坟不动，人也不动（0 点）', '让坟户原地留守，坟不动，人也不动。'),
    ('把祖坟的事交回族里自决（0 点）', '把祖坟的事交回族里自决。'),
])
def test_grave_decision_does_not_display_obsolete_costs(text, expected):
    decision = SimpleNamespace(decision_id='dp5_03', action_point_cost=0,
                               visible_option_text=lambda *_: text)
    session = SimpleNamespace(flags=set(), known_fact_ids=set(), package_id='pkg_gameplay_v3')
    assert StoryFlowService._visible_option_text(decision, SimpleNamespace(option_id='a'), session, {}) == expected
