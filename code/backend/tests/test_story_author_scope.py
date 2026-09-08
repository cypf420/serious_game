"""The new approval permits only the seven authored repairs, not economic drift."""
from copy import deepcopy
import pytest
from tools.build_story_integrity_candidate import revise, diff_operations
from tools.story_revision import apply_operations
from tests.test_story_integrity_mechanics import baseline


def apply(before, after):
    ops = diff_operations(before, after)
    return apply_operations(before, ops, consistency_authorizations=[dict(o) for o in ops if o['category']=='story_consistency'])


def test_authored_branch_operations_reconstruct_candidate():
    before = baseline()
    after, _ = revise(before)
    assert apply(before, after) == after


@pytest.mark.parametrize('mutation', ['payment','success_without_evidence','block_condition','fact_gate','other_option','speaker','archive_early','archive_fact','city_multi'])
def test_author_approval_rejects_unrelated_or_unconditional_changes(mutation):
    before = baseline()
    after, _ = revise(before)
    d = next(d for d in after['decisions.json']['decisions'] if d['decision_id']=='dp4_06')
    if mutation == 'payment':
        d['options'][0]['conditional_effects'][0]['effects']['ledger_deltas']['budget_remaining'] = [-12,-12]
    elif mutation == 'success_without_evidence':
        d['options'][0]['conditional_effects'][0]['required_flags'] = []
    elif mutation == 'block_condition':
        d['presentation_blocks'][-1]['required_flags'] = []
    elif mutation == 'fact_gate':
        d['text_variants'][-1]['required_fact_ids'] = []
    elif mutation == 'speaker':
        d['presentation_blocks'][-1]['speaker'] = '周大山'
    elif mutation == 'archive_early':
        after['archive_investigations.json']['archives'][-1]['unlock_day'] = 1
    elif mutation == 'archive_fact':
        after['archive_investigations.json']['archives'][-1]['result_fact_ids'].append('fact_lead_census')
    elif mutation == 'city_multi':
        city = next(d for d in after['decisions.json']['decisions'] if d['decision_id']=='dp4_10')
        city['options'][3]['effects']['open_flags'].append('市里定的紧口径')
    else:
        d['options'][1]['effects']['open_flags'].append('旧案了结')
    with pytest.raises(ValueError):
        apply(before, after)


def test_source_rejects_unregistered_change():
    from content.editorial.story_author_revision import REPO, read_source_edition
    raw = (REPO/'最终剧本.md').read_bytes()
    historical, texts = read_source_edition(raw)
    assert texts and historical
    with pytest.raises(ValueError):
        read_source_edition(raw.replace('县政府'.encode(), '市政府'.encode(), 1))


def test_author_ending_transform_rejects_an_unmatched_paragraph():
    from content.editorial.story_author_revision import apply_author_endings
    from content.editorial.story_integrity_endings import apply_endings
    doc = apply_endings(baseline()['ending_rules.json'])
    ending = next(e for e in doc['main_endings'] if e['ending_id']=='ending_20')
    ending['text'] = ending['text'].replace('陈默那边，', '未经登记的陈默段，')
    with pytest.raises(ValueError):
        apply_author_endings(doc)
