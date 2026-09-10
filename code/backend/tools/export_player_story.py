"""Export registered player prose without executing routes or altering a save."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.story_revision import enumerate_visible_records
from serious_game_backend.application.ending_prose import revise_ending_prose

CONDITIONS = ('origin_ids','required_flags','required_any_flags','forbidden_flags',
              'required_state_values','forbidden_state_values','required_fact_ids',
              'required_any_fact_ids','minimum_ledger_values','maximum_ledger_values',
              'condition','axis_value','free_axis')

def runtime_records():
    from serious_game_backend.application import ending_service as endings
    from serious_game_backend.application.scripted_effect_service import ScriptedEffectService
    from serious_game_backend.application.story_flow_service import PERMIT_ALREADY_ISSUED_TEXT, REPEATED_MONEY_OPTION_TEXTS
    records = []
    for family, values in (
        ('roster', endings.ROSTER_APPENDIX_TEXTS),
        ('iron', endings.IRON_APPENDIX_TEXTS),
        ('rope', endings.ROPE_APPENDIX_TEXTS),
    ):
        for key, text in values.items():
            records.append((f'ending:{family}:{key}',text))
    for key, text in ScriptedEffectService._POST75_NARRATIVES.items():
        records.append((f'contract:{key}',text))
    records.append(('permit:already-issued',PERMIT_ALREADY_ISSUED_TEXT))
    for count,text in REPEATED_MONEY_OPTION_TEXTS.items():
        records.append((f'decision:dp4_04:b:round-{count+1}',text))
    return records

def conditions_for(document, pointer):
    value = document
    found = []
    for token in pointer.lstrip('/').split('/'):
        if isinstance(value, dict):
            conditions = {k:value[k] for k in CONDITIONS if k in value and value[k]}
            if conditions and conditions not in found: found.append(conditions)
        token = token.replace('~1','/').replace('~0','~')
        value = value[int(token)] if isinstance(value,list) else value[token]
    return found

def build_export(package_dir: Path) -> tuple[str,dict]:
    package_dir = Path(package_dir)
    documents = {p.name:json.loads(p.read_text(encoding='utf-8-sig')) for p in package_dir.glob('*.json')}
    records = enumerate_visible_records(package_dir)
    manifest = documents['package_manifest.json']
    chunks = ['# 当前游戏剧情全文·完整性修订复审稿', '',
        f'内容版本：{manifest["package_version"]}；内容哈希：{manifest["content_hash"]}', '',
        '本稿为全部固定玩家可见文字的注册清单，不是单条实际游玩路线。条件分支互斥，不能把并列列出的文字理解成同一玩家都会看到。决策后果保留全文；内部规则仅作为审核条件注释，不是游戏旁白。动态AI回复不属于固定剧本。', '']
    current_group = None
    def export_order(record):
        pointer=record['pointer']
        natural=tuple((0,int(t)) if t.isdecimal() else (1,t) for t in pointer.split('/'))
        phase=0 if record['file']=='story_beats.json' else 1 if record['file']=='decisions.json' else 2
        if record['file']=='story_beats.json' and '/night_blocks/' in pointer: phase=3
        # Numeric pointer order keeps option 2 before option 10 in large permutations.
        return (record['day'] if record['day'] is not None else 1000,phase,record['file'],natural)
    for record in sorted(records, key=export_order):
        group = f'第{record["day"]}日' if record['day'] is not None else record['file']
        if group != current_group:
            chunks.extend([f'## {group}',''])
            current_group = group
        chunks.extend([f'### {record["node_id"] or record["file"]} · {record["kind"]}'
                       + (f' · 选项 {record["option_id"]}' if record['option_id'] else ''),
                       '',f'来源：`{record["file"]}{record["pointer"]}`',''])
        conditions = conditions_for(documents[record['file']],record['pointer'])
        if conditions: chunks.extend(['审核条件：`'+json.dumps(conditions,ensure_ascii=False)+'`',''])
        if record['file'] == 'interaction_opportunities.json':
            if '/completion_blocks/' in record['pointer']:
                chunks.extend(['播放时机：满足该会谈的完成条件，并由玩家正常结束后播放；NPC 主动离场时不叠加此固定收尾，采用实际会谈经校验的离场叙事。', ''])
            elif record['pointer'].endswith('/opening_narrative'):
                chunks.extend(['播放时机：玩家开始对应互动会谈时。此后回复由真实 LLM 生成，不属于固定正文。', ''])
        text = revise_ending_prose(record['text']) if record['file'] == 'ending_rules.json' else record['text']
        chunks.extend([text,''])
    chunks.extend(['说明：模拟回复不属于本剧情；本文只导出正式注册的固定文本及其播放条件，不收录自动化测试替身的台词。', '', '## 运行时固定附录与办理反馈',''])
    runtime = runtime_records()
    for rid, text in runtime:
        chunks.extend([f'### {rid}','',text,''])
    decisions = documents['decisions.json']['decisions']
    endings = documents['ending_rules.json']
    coverage = {
        'package_version':manifest['package_version'],'content_hash':manifest['content_hash'],
        'package_ids':[r['review_id'] for r in records],
        'runtime_ids':[rid for rid,_ in runtime],
        'counts':{'days':len(documents['story_beats.json']['beats']),'decisions':len(decisions),
                  'options':sum(len(d['options']) for d in decisions),
                  'main_endings':len(endings['main_endings']),'sub_endings':len(endings['sub_endings'])},
    }
    return '\n'.join(chunks), coverage

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    markdown, coverage = build_export(args.package_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as stream: stream.write(markdown)
    with args.output.with_suffix('.coverage.json').open('x',encoding='utf8') as stream:
        json.dump(coverage,stream,ensure_ascii=False,indent=2)
    print(json.dumps(coverage['counts'],ensure_ascii=False))

if __name__ == '__main__': main()
