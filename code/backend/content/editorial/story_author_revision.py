"""User-approved source edition; historical imports remain hash-pinned and reversible."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

REGISTRY = Path(__file__).with_name('story_author_source_20260908.json')
REPO = Path(__file__).resolve().parents[4]


def read_source_edition(raw):
    registry = json.loads(REGISTRY.read_text(encoding='utf8'))
    text = raw.decode('utf-8-sig').replace('\r\n', '\n')
    appendix = registry['appendix']
    # apply_patch may preserve the original terminal newline before the appendix.
    marker = '\n\n## 2026-09-08 连贯性统修：条件正文与入库对照'
    if text.count(marker) != 1:
        raise ValueError('Authored source edition marker missing or duplicated')
    body, tail = text.split(marker)
    if (marker + tail).strip() != appendix.strip():
        raise ValueError('Authored source appendix differs from approved registry')
    for row in registry['replacements']:
        if body.count(row['after']) != 1:
            raise ValueError(f'Authored source paragraph drift: {row["line"]}')
        body = body.replace(row['after'], row['before'], 1)
    candidates = [body.rstrip('\n') + '\n' * n for n in range(3)]
    historical = next((candidate for normalized in candidates
                       for candidate in (normalized, normalized.replace('\n','\r\n'))
                       if hashlib.sha256(candidate.encode('utf8')).hexdigest() == registry['historical_sha256']), None)
    if historical is None:
        raise ValueError('Unregistered source change: historical SHA-256 does not reconstruct')
    slots = dict(re.findall(r'<!-- story:([^ ]+) -->\s*\n(.*?)(?=<!-- story:)', appendix, re.S))
    return historical.splitlines(), {k:v.strip() for k,v in slots.items()}


def source_path():
    source = REPO.parent / 'backend-0c15d36' / '最终剧本.md'
    if not source.exists():
        source = REPO / '最终剧本.md'
    return source


def authored_texts():
    return read_source_edition(source_path().read_bytes())[1]


def apply_author_revision(docs):
    t = authored_texts()
    docs['content_catalog.json']['source_sha256'] = 'sha256:' + hashlib.sha256(source_path().read_bytes()).hexdigest()
    ds = {d['decision_id']:d for d in docs['decisions.json']['decisions']}
    bs = {b['story_day']:b for b in docs['story_beats.json']['beats']}
    source_edits = {r['line']: r['after'] for r in json.loads(REGISTRY.read_text(encoding='utf8'))['replacements']}
    wu = ds['dp1_01_taskforce_faction_map']
    for b in wu['followup_blocks']:
        if b['block_id'] == 'd02_wu_bridge':
            b['text'] = source_edits[2552]
        elif b['block_id'] == 'd02_wu_encounter':
            b['text'] = source_edits[2556]
    docs['interaction_opportunities.json']['conversation_contexts']['opp_d02_wu_xiuying_first_talk']['opening_narrative'] = source_edits[2558].split('固定开场：', 1)[1]
    ds['dp1_06']['options'][0]['consequence'] = t['d11a']
    ds['dp4_10']['options'][3]['text'] = t['d59option_d']
    city = ds['dp4_10']['options'][3]
    city['effects']['open_flags'] = ['口径已上交','市里定的中口径']
    city['conditional_effects'] = []
    for condition, reply in ((dict(required_flags=['宏达行贿在录']), '市里定的紧口径'),
                             (dict(required_flags=['两百万抹平'],forbidden_flags=['宏达行贿在录']), '市里定的松口径')):
        effects = deepcopy(city['effects'])
        effects['open_flags'] = ['口径已上交',reply]
        city['conditional_effects'].append(dict(**condition,replace_base=True,effects=effects))
    for day, did in ((38,'dp3_06'), (53,'dp4_06')):
        beat, decision = bs[day], ds[did]
        # Existing IDs and prose remain on the unpaid route; settlement is exclusive.
        opening = beat['opening_blocks'][1:] if day == 38 else beat['opening_blocks'][:-1]
        for block in [*opening, *decision['presentation_blocks']]:
            block['forbidden_flags'] = ['旧案了结']
        keys = ['d38settled'] if day == 38 else ['d53settled', *[f'd53settled_{n}' for n in range(2,6)]]
        for key in keys:
            beat['opening_blocks'].append(dict(block_id=key,kind='narration',text=t[key],
                scene_id=decision['scene_id'],presentation_phase='scene',required_flags=['旧案了结']))
        key = 'd38settled_setup' if day == 38 else 'd53settled_setup'
        decision['presentation_blocks'].append(dict(block_id=key+'_decision',kind='narration',text=t[key],
            scene_id=decision['scene_id'],presentation_phase='decision_setup',required_flags=['旧案了结']))
        consequences = {o:t[f'd38settled_{o}'] if day == 38 else t['d53paid' if o=='a' else f'd53paid_{o}'] for o in 'abcd'}
        variant = dict(variant_id=f'd{day}_settled_reply', required_flags=['旧案了结'],
                       title='旧案之后的履约',option_consequences=consequences)
        if day == 53:
            variant['option_texts'] = {o:t[f'd53paid_option_{o}'] for o in 'abcd'}
        decision.setdefault('text_variants', []).insert(0,variant)
    bs[53]['opening_blocks'][2]['text'] = t['d53unpaid_history']
    a = ds['dp4_06']['options'][0]
    success = deepcopy(a['effects'])
    success['close_flags'] = [*success['close_flags'], '谭老六被空口应付']
    a['consequence'] = t['d53weak']
    a.pop('required_fact_ids', None)
    a.pop('unlock_requirements', None)
    a['effects'] = dict(metric_deltas={},ledger_deltas={},open_flags=['谭老六被空口应付'],close_flags=[],state_assignments={})
    conditions = [dict(required_flags=['旧案了结']),
                  dict(required_flags=['旧账缺口已坐实'],forbidden_flags=['旧案了结']),
                  dict(required_fact_ids=['fact_tan_land_arrears'],forbidden_flags=['旧案了结','旧账缺口已坐实'])]
    a['conditional_effects'] = [dict(**c, replace_base=True, effects=deepcopy(success)) for c in conditions]
    for n, condition in enumerate(conditions[1:],1):
        ds['dp4_06']['text_variants'].append(dict(variant_id=f'd53_verified_{n}', **condition,
            option_consequences={'a':t['d53verified']}))
    ds['dp4_06']['options'][2]['text'] = '只将旧案与本次搬迁切开，不安排统一承接，结束这次协商。'
    docs['archive_investigations.json']['archives'].append(dict(
        archive_id='archive_tan_land_arrears', title=t['old_land_title'], category='旧案与履约',
        unlock_day=38, content=t['old_land_content'], evidence_level='E2',confidentiality='内部',
        result_fact_ids=['fact_tan_land_arrears'],strategic_uses=[t['old_land_use']]))
    docs['facts.json']['facts'].append(dict(fact_id='fact_tan_land_arrears',title=t['old_land_title'],
        text=t['old_land_content'],category='evidence',source_label='县档案旧占地卷宗',
        source_line=7072, related_npc_ids=['npc_tan_laoliu','npc_liu_san'],
        acquisition_methods=[dict(route_type='archive',source_id='archive_tan_land_arrears',
            unlock_day=38,label='查阅《二〇一九年占地尾款卷宗》',instructions='第38日起在行动—查阅档案中核对该卷；第53日待决策期间也可查阅。')],
        use_hint=t['old_land_use']))
    next(row for row in docs['story_acceptance_matrix.json']['days'] if row['story_day']==38)['archive_unlock_ids'].append('archive_tan_land_arrears')


def apply_author_endings(doc):
    from content.editorial.story_integrity_endings import _PATCHES
    registry = json.loads(REGISTRY.read_text(encoding='utf8'))
    rows = [r for r in registry['replacements'] if 12480 <= r['line'] <= 12680]
    for ending in doc['main_endings']:
        if ending['ending_id'] not in {'ending_18','ending_20'}:
            continue
        for row in rows:
            target = 'ending_18' if row['line'] < 12600 else 'ending_20'
            if ending['ending_id'] != target:
                continue
            previous = row['before']
            for before, after in _PATCHES[target.removeprefix('ending_')]:
                for clause in (before if isinstance(before, tuple) else (before,)):
                    previous = previous.replace(clause,after)
            paragraphs = ending['text'].split('\n\n')
            matches = [i for i,p in enumerate(paragraphs) if p in {row['before'],previous,row['after']}]
            if len(matches) != 1:
                raise ValueError(f'Authored ending paragraph must match exactly once: {target}:{row["line"]}')
            paragraphs[matches[0]] = row['after']
            ending['text'] = '\n\n'.join(paragraphs)
    for appendix in doc['appendices']:
        if appendix['source'] == 'coercion_flags':
            appendix['title'] = '冲突留下的痕迹'
    return doc
