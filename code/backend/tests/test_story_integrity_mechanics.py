"""Independent whitelist for mechanisms the editorial build is forbidden to alter."""
from copy import deepcopy
import json
from pathlib import Path

from tools.build_story_integrity_candidate import revise

B = Path(__file__).resolve().parents[1]
BASELINE = B.parents[1] / 'output/story-integrity/20260908-implementation/baseline-package'

def baseline():
    return {p.name:json.loads(p.read_text(encoding='utf-8-sig')) for p in BASELINE.glob('*.json')}

def test_revision_preserves_every_effect_except_registered_original_handoff():
    before = baseline()
    after, reviews = revise(before)
    assert len(reviews) == 688
    for old,new in zip(before['decisions.json']['decisions'],after['decisions.json']['decisions']):
        assert old['decision_id'] == new['decision_id']
        assert old['action_point_cost'] == new['action_point_cost']
        assert old['skippable'] == new['skippable']
        assert new['story_day'] == (44 if old['decision_id']=='dp3_08' else old['story_day'])
        assert len(old['options']) == len(new['options'])
        for oo,nn in zip(old['options'],new['options']):
            assert oo['option_id'] == nn['option_id']
            expected = deepcopy(oo['effects'])
            if old['decision_id']=='dp4_07' and oo['option_id']=='a':
                expected['state_assignments']['lead_roster_disposition'] = '交给记者'
            if old['decision_id']=='dp6_03' and oo['option_id']=='c':
                expected['state_assignments'].pop('lead_roster_disposition')
            if old['decision_id']=='dp4_06' and oo['option_id']=='a':
                success = deepcopy(expected)
                success['close_flags'] = ['谭老六被空口应付']
                expected = dict(metric_deltas={},ledger_deltas={},open_flags=['谭老六被空口应付'],close_flags=[],state_assignments={})
                conditions = [dict(required_flags=['旧案了结']),
                    dict(required_flags=['旧账缺口已坐实'],forbidden_flags=['旧案了结']),
                    dict(required_fact_ids=['fact_tan_land_arrears'],forbidden_flags=['旧案了结','旧账缺口已坐实'])]
                assert nn['conditional_effects'] == [dict(**c,replace_base=True,effects=success) for c in conditions]
            elif old['decision_id']=='dp4_10' and oo['option_id']=='d':
                expected['open_flags'] = ['口径已上交','市里定的中口径']
                conditions = [(dict(required_flags=['宏达行贿在录']),'市里定的紧口径'),
                    (dict(required_flags=['两百万抹平'],forbidden_flags=['宏达行贿在录']),'市里定的松口径')]
                branches = []
                for condition,flag in conditions:
                    effect = deepcopy(expected)
                    effect['open_flags'] = ['口径已上交',flag]
                    branches.append(dict(**condition,replace_base=True,effects=effect))
                assert nn['conditional_effects'] == branches
            else:
                assert nn.get('conditional_effects') == oo.get('conditional_effects')
            assert nn['effects'] == expected
    for old,new in zip(before['story_beats.json']['beats'],after['story_beats.json']['beats']):
        assert old.get('night_effects') == new.get('night_effects')
        assert old.get('night_conditional_effects') == new.get('night_conditional_effects')
    expected_profiles = deepcopy(before['acceptance_route_profiles.json'])
    expected_profiles['decision_policy_templates']['unknown']['dp6_06'] = 'b'
    assert after['acceptance_route_profiles.json'] == expected_profiles
    for file in ('numbers.json','households.json','household_signatories.json',
                 'action_rules.json','resource_actions.json','flags.json','story_calendar.json'):
        assert before[file] == after[file], file

def test_independent_authority_rejects_unreviewed_copy_even_with_valid_package_hash(tmp_path):
    import shutil
    import pytest
    from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader
    from serious_game_backend.domain.errors import ContentValidationError
    candidate = tmp_path/'pkg_gameplay_v3'
    shutil.copytree(B/'content/packages/pkg_gameplay_v3',candidate)
    doc = json.loads((candidate/'story_beats.json').read_text(encoding='utf8'))
    next(b for b in doc['beats'] if b['story_day']==13)['opening_blocks'][0]['text'] += '未经审定的改写。'
    (candidate/'story_beats.json').write_text(json.dumps(doc,ensure_ascii=False),encoding='utf8')
    manifest = json.loads((candidate/'package_manifest.json').read_text(encoding='utf8'))
    manifest['content_hash'] = FileScriptPackageLoader.compute_content_hash(candidate)
    (candidate/'package_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf8')
    with pytest.raises(ContentValidationError,match='独立母稿锚点'):
        FileScriptPackageLoader().load(candidate)
