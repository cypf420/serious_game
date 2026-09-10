"""Guard fixed prose against repeated sentences and pasted blocks, not branch reuse."""
from collections import Counter, defaultdict
from pathlib import Path
import re

from serious_game_backend.application.ending_prose import revise_ending_prose
from tools.export_player_story import build_export, runtime_records
from tools.story_revision import enumerate_visible_records

PACKAGE = Path(__file__).resolve().parents[1] / 'content/packages/pkg_gameplay_v3'


def test_same_day_story_blocks_do_not_repeat_long_sentences():
    occurrences = defaultdict(list)
    for record in enumerate_visible_records(PACKAGE):
        if record['file'] != 'story_beats.json' or record['kind'] != 'text':
            continue
        sentences = {s.strip() for s in re.findall(r'[^。！？\n]+[。！？]?', record['text'])}
        for sentence in sentences:
            if len(sentence) >= 25:
                occurrences[record['day'], sentence].append(record['pointer'])
    assert not {key: paths for key, paths in occurrences.items() if len(paths) > 1}


def test_all_registered_fixed_prose_has_no_repeated_sentences_or_long_spans():
    records = enumerate_visible_records(PACKAGE)
    assert len(records) == 4048
    texts = [(r['review_id'], revise_ending_prose(r['text'])
              if r['file'] == 'ending_rules.json' else r['text']) for r in records]
    texts.extend(runtime_records())
    for identity, text in texts:
        sentences = [s.strip() for s in re.findall(r'[^。！？\n]+[。！？]?', text)]
        repeated = [s for s, count in Counter(sentences).items() if count > 1 and len(s) >= 12]
        assert not repeated, (identity, repeated)
        spans = [text[i:i + 60] for i in range(max(0, len(text) - 59))]
        assert len(spans) == len(set(spans)), identity


def test_export_uses_corrected_endings_without_altering_other_story_text():
    markdown, _ = build_export(PACKAGE)
    corrected = set()
    for record in enumerate_visible_records(PACKAGE):
        raw = record['text']
        expected = revise_ending_prose(raw) if record['file'] == 'ending_rules.json' else raw
        section = markdown.split(f"来源：`{record['file']}{record['pointer']}`", 1)[1].split('\n### ', 1)[0]
        assert expected in section, record['review_id']
        if raw != expected:
            corrected.add(record['node_id'])
            assert raw not in section
    assert corrected == {'ending_03', 'ending_08', 'ending_14', 'ending_15', 'ending_21'}
