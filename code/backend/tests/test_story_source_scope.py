"""The source-restoration authorization must not admit unrelated mechanics."""
from copy import deepcopy

import pytest

from tools.story_revision import apply_operations


def fixture():
    def block(identity, text):
        return {'block_id': identity, 'kind': 'narration', 'text': text,
                'scene_id': 'C01_S06', 'presentation_phase': 'followup'}
    old = [block('intro', '交谈'), block('reference', '这句话')]
    new = [old[0], {**block('source_restore_l2554', '谁的话在谁面前好使'),
                    'kind': 'dialogue', 'speaker': '吴秀英'}, old[1]]
    docs = {'decisions.json': {'decisions': [
        {'decision_id': 'dp1_01_taskforce_faction_map', 'story_day': 2, 'followup_blocks': old}]}}
    op = {'file': 'decisions.json', 'pointer': '/decisions/0/followup_blocks',
          'op': 'replace', 'before': deepcopy(old), 'after': deepcopy(new),
          'node_id': 'dp1_01_taskforce_faction_map', 'category': 'story_consistency'}
    return docs, op


def test_approved_quote_can_be_inserted_without_reordering_existing_prose():
    docs, op = fixture()
    result = apply_operations(docs, [op], consistency_authorizations=[deepcopy(op)])
    ids = [b['block_id'] for b in result['decisions.json']['decisions'][0]['followup_blocks']]
    assert ids == ['intro', 'source_restore_l2554', 'reference']
    assert len(docs['decisions.json']['decisions'][0]['followup_blocks']) == 2


@pytest.mark.parametrize('mutation', ['new_id', 'effect', 'guard', 'reorder', 'kind', 'other_node',
                                    'night', 'unknown_phase', 'scene', 'speaker'])
def test_source_approval_rejects_unregistered_blocks_and_mechanisms(mutation):
    docs, op = fixture()
    if mutation == 'new_id': op['after'][1]['block_id'] = 'unreviewed_scene'
    if mutation == 'effect': op['after'][1]['effects'] = {'open_flags': ['money']}
    if mutation == 'guard': op['after'][1]['required_flags'] = ['money']
    if mutation == 'reorder': op['after'] = list(reversed(op['after']))
    if mutation == 'kind': op['after'][1]['kind'] = 'internal'
    if mutation == 'night': op['after'][1]['presentation_phase'] = 'night'
    if mutation == 'unknown_phase': op['after'][1]['presentation_phase'] = 'unregistered-phase'
    if mutation == 'scene': op['after'][1]['scene_id'] = 'C04_S07'
    if mutation == 'speaker': op['after'][1]['speaker'] = '钱伟'
    if mutation == 'other_node':
        docs['decisions.json']['decisions'][0]['decision_id'] = op['node_id'] = 'unreviewed_node'
    with pytest.raises(ValueError):
        apply_operations(docs, [op], consistency_authorizations=[deepcopy(op)])


def test_only_return_template_can_use_the_existing_no_original_press_choice():
    docs = {'acceptance_route_profiles.json': {'decision_policy_templates': {
        'unknown': {'dp4_01': 'e', 'dp6_06': 'a'}}}}
    op = {'file': 'acceptance_route_profiles.json',
          'pointer': '/decision_policy_templates/unknown/dp6_06',
          'op': 'replace', 'before': 'a', 'after': 'b', 'category': 'story_consistency'}
    result = apply_operations(docs, [op], consistency_authorizations=[deepcopy(op)])
    assert result['acceptance_route_profiles.json']['decision_policy_templates']['unknown'] == {
        'dp4_01': 'e', 'dp6_06': 'b'}
    for invalid in ('a', 'c', 'd', 'e'):
        changed = {**op, 'after': invalid}
        with pytest.raises(ValueError):
            apply_operations(docs, [changed], consistency_authorizations=[deepcopy(changed)])
