"""Build the reviewed 20260908 revision against its immutable snapshot.

This is an editorial build, not a general source-script importer. It never
changes the source package; output must be a fresh directory.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil

from content.editorial.story_integrity_copy import (
    RESTORE_LINES, SOURCE_REWRITES, REPEATED_OUTCOMES, EXACT_OUTCOMES,
    SORTING_LABELS, SORTING_RESPONSES,
)
from content.editorial.story_integrity_endings import apply_endings, ending_reviews
from content.editorial.story_author_revision import apply_author_revision, apply_author_endings, source_path as authored_source_path
from content.editorial.story_source_restoration import (
    SOURCE_SHA256, SOURCE_RESTORATIONS, UNRESOLVED_SOURCE_ISSUES,
    apply_source_restoration, source_lines,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
BASELINE = REPO / 'output/story-integrity/20260908-implementation'
BASELINE_INVENTORY_SHA256 = '1bac86be3de16f282df5ffc919f3e0c6a0624130ece284d05d103c433117fa4e'
BASELINE_AUTHORITY_SHA256 = 'dea9a173950dadd459940f6997e4c3ca7f52369cb428784b6f7ac5031e19c68c'

def file_hashes(package):
    from tools.story_revision import read_package
    _,raw = read_package(package)
    return {name:hashlib.sha256(value).hexdigest() for name,value in raw.items()}

def verify_baseline():
    actual=file_hashes(BASELINE/'baseline-package')
    digest=hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if digest != BASELINE_INVENTORY_SHA256:
        raise ValueError('Immutable baseline package fingerprint mismatch')
    if hashlib.sha256((BASELINE/'baseline-authority.json').read_bytes()).hexdigest() != BASELINE_AUTHORITY_SHA256:
        raise ValueError('Immutable baseline authority fingerprint mismatch')
    return actual

def verify_install_target(target, expected_hashes, authority_target, authority_expected,
                          editorial_target, editorial_expected):
    if file_hashes(target) != expected_hashes:
        raise ValueError('Current code package file inventory or content drift')
    if authority_target.read_bytes() != authority_expected.read_bytes():
        raise ValueError('Current code authority drift')
    if editorial_expected is None:
        if editorial_target.exists(): raise ValueError('Unexpected existing editorial registry')
    elif not editorial_target.exists() or editorial_target.read_bytes() != editorial_expected.read_bytes():
        raise ValueError('Current editorial registry drift')

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')

def narrative(block_id, text, scene='C01_S02', **conditions):
    return dict(block_id=block_id, kind='narration', text=text, scene_id=scene,
                presentation_phase='scene', **conditions)

DAY_TITLES = {
5:'坡上那间旧瓦房',6:'坡下的回程',7:'残缺底册与调度会',8:'渡口堵路',9:'茶杯里的试探',10:'深夜送医',
11:'首轮试签',12:'协议上的裂缝',13:'入户走访的次序',27:'上报的实数',28:'粮站外的求助',29:'周转金的去向',30:'三十日回望',
42:'患儿检测消息',48:'周满仓的账本与通报',49:'果篮里的条件',52:'祠堂那块地',53:'退回的旧诉',55:'门诊楼前',57:'病房与深夜敲门',
58:'铁盒归来与围堰险情',59:'市生态环境检查组进驻',60:'座谈桌上的记录',61:'未决名册',63:'祖坟的规矩',66:'迁坟安排核验',67:'先摊村账',
69:'核账的余波',71:'宁德海与汇总表',72:'门板上的复印件',73:'小卖部的那道坎',78:'十一名孩子的后续保障',81:'铁盒账册的去向',86:'搬迁现状核查',
}
DECISION_TITLES = {
'dp3_10':'撤离前的最后定向','dp4_09':'用途栏那四个字','ev4_03':'围堰险情','ev4_04':'先遣检查',
'dp4_10':'迎检说明','dp4_11':'座谈桌上的回答','dp5_03':'起灵与迁移安排','ev5_01':'冲突之后',
'dp5_04':'核账第一步','dp5_05':'核账第二步','dp5_05_recovery':'重新核对原始记录','dp5_06':'宁德海的汇总表',
'ev5_02':'门板上的复印件','dp5_07':'马长顺的比较','dp5_08':'何铁柱的实账','dp5_09':'祠堂用地手续',
'dp5_10':'向蒋崇岳说明','dp5_11':'给联络员的答复','dp5_12':'最后十五天的次序','ev5_03':'赵建国的夜间电话',
'dp6_01':'核对验收台账','dp6_02':'实房与样板间','dp6_03':'复检、治疗与费用','ev6_01':'台阶下的家属',
'dp6_04':'原始凭证','dp6_05':'整本账的去向','dp6_06':'记者的稿子','dp6_07':'整改清单的次序','dp6_08':'责任名单',
}

def revise(documents):
    docs = deepcopy(documents)
    decisions = docs['decisions.json']['decisions']
    beats = docs['story_beats.json']['beats']
    ds = {d['decision_id']: d for d in decisions}
    bs = {b['story_day']: b for b in beats}
    source_path = REPO.parent / 'backend-0c15d36' / '最终剧本.md'
    if not source_path.exists():
        source_path = REPO / '最终剧本.md'
    source = source_lines(source_path.read_bytes())
    settlements = [(n, m[1].strip()) for n, line in enumerate(source, 1)
                   if (m := re.search(r'后果叙事[：:](.*)', line))]
    reviews = []
    for d in decisions:
        for index, o in enumerate(d['options']):
            old = o['consequence']
            match = next(((n,t) for n,t in settlements if t.startswith(old+'。')), None)
            reason = '完整即时反馈，未发现首句、标题或选项回退；保留现有已审核机制表述。'
            disposition = 'keep'
            if match:
                n, raw = match
                if n in SOURCE_REWRITES:
                    o['consequence'] = SOURCE_REWRITES[n]
                    disposition = 'rewrite'
                    reason = '恢复人物回应；剔除作者说明、未发生的延后结果及旧机制承诺。'
                elif n in RESTORE_LINES:
                    o['consequence'] = re.split(r'连锁(?:反应)?[：:]', raw)[0].strip()
                    disposition = 'restore' if o['consequence'] != old+'。' else 'keep'
                    reason = '核对原稿完整公共后果；明确的内部连锁说明不进入正文。'
                else:
                    raise ValueError(f'Unreviewed source passage {n}: {d["decision_id"]}:{o["option_id"]}')
            if old in EXACT_OUTCOMES:
                o['consequence'] = EXACT_OUTCOMES[old]
                disposition, reason = 'rewrite', '补足非首句匹配候选的行为反馈和实际完成边界。'
            if old == o['text']:
                replacement = REPEATED_OUTCOMES[d['decision_id']][index]
                assert replacement, (d['decision_id'], index)
                o['consequence'] = replacement
                disposition, reason = 'rewrite', '原后果只重复选项，补写角色回应与待办边界。'
            if d['decision_id'] == 'dp6_07':
                order = o['option_id'].split('_')
                o['consequence'] = ('郑向东按你给出的次序逐项登记：'+ '、'.join(SORTING_LABELS[k] for k in order)+'。'
                                    + SORTING_RESPONSES[order[0]]+'后续事项按上述次序推进，未办完的仍列在清单上，不能因排了顺序就一并销号。')
                disposition, reason = 'rewrite', '120排列逐ID登记；现有结算按首位等价，文字仍保留全部位次，不虚构后置事项已经完成。'
            reviews.append(dict(review_id=f'decision:{d["decision_id"]}:{o["option_id"]}:consequence',
                                day=d['story_day'], disposition=disposition, reason=reason,
                                source={'file':'最终剧本.md','line':match[0]} if match else {'file':'content/editorial/story_integrity_copy.py'},
                                before=old, after=o['consequence'], test_ids=['test_all_options_have_distinct_outcomes_not_headings']))
        d['title'] = DECISION_TITLES.get(d['decision_id'], re.sub(r'^（[一二三四]）', '', d['title']))
    for day, title in DAY_TITLES.items():
        bs[day]['title'] = f'第{day}日·{title}'

    # Explicitly approved chronology and physical-original ownership changes.
    ds['dp3_08']['story_day'] = 44
    bs[43]['decision_ids'].remove('dp3_08')
    bs[44]['decision_ids'].insert(0, 'dp3_08')
    bs[43]['opening_blocks'][-1]['text'] = '血铅患儿的后续处置仍需核对。明早走进谈话室前，你要把材料、口径和自己的边界理清；已经作出的处置与尚待决定的事项分别登记。'
    old12 = bs[12]['opening_blocks'][0]
    old12['forbidden_flags'] = ['审慎缓签']
    bs[12]['opening_blocks'].append(narrative('d12_deferred_materials',
        '第十二日夜里，干事把尚未生效的拟签材料拿来核查。昨天你决定缓签，这些纸不能算正式协议。其中一份权属含糊，堂弟代签的名字已填上，日期还早于公示期满。干事说镇里想先按手印再补手续。你让他把材料摊开：接下来是补齐程序，还是认可这份有问题的草稿，必须说清。',
        scene='C06_S02', required_flags=['审慎缓签']))
    for b in bs[30]['opening_blocks']:
        b['text'] = b['text'].replace('三张连号发票、三份数字一模一样的环评报告、一本圈了红圈的学生名册、一张揉皱的烟盒纸、一份报出去的红头文件。',
            '关于连号发票和环评报告的核查记录、吴秀英展示旧名册时的走访笔记，以及这段时间形成的报送与交接记录。原件在谁手里、哪些只是看过或听说，你逐项注明，没有把走访笔记当成已经取得的原件。')
    bs[56]['opening_blocks'].append(narrative('d56_he_handoff',
        '你把何铁柱关于旧检结果的追问登记下来，要求卫健经办人核对当年的告知记录，另列当前治疗和费用事项。你没有在材料未齐时许下结论。他收好军装照，说等一个正式答复，随后下楼。郑向东送他出去，回来通报：陈默在外面等着核对报道材料。'))
    bs[58]['opening_blocks'].append(narrative('d58_box_return',
        '上午，刘三带着铁盒回到县政府。他说昨夜担心材料被拿走，换了地方保管，没敢给家里回信。郑向东先通知家属他已平安，再当面登记铁盒、页码与移交时间。你让刘三补写去向说明，账册逐页清点后才摊上案头。失联的疑点还需核实，眼下要处理的材料已有明确交接。'))
    bs[69]['opening_blocks'][0]['required_flags'] = ['周满仓核心矛盾已缓解']
    bs[69]['opening_blocks'].append(narrative('d69_unresolved',
        '第六十九日，你翻到周满仓的核账记录。此前没有谈妥的部分仍在，账本并未因日期到了就自动留下。若要继续谈，必须依照他提出的核账次序和现有补救安排重开会面，不能把未完成的协商填成成功。',
        scene='C01_S06', forbidden_flags=['周满仓核心矛盾已缓解','周满仓重启已付费']))
    bs[69]['opening_blocks'].append(narrative('d69_retry',
        '第六十九日，重新核账的准备已经完成。周满仓同意再坐下来，仍要求先村账、再原始检测记录、最后才谈补偿。你重新摆好材料，这只是再谈一次的机会，不是已经得到他的认可。',
        scene='C01_S06', required_flags=['周满仓重启已付费'], forbidden_flags=['周满仓核心矛盾已缓解']))
    original_option = ds['dp4_07']['options'][0]
    original_option['required_state_values'] = {'lead_roster_disposition':'己方封存'}
    original_option['unavailable_reason'] = '原始名册不在你手里，只能说明去向或通过现有渠道核验，不能重复交付原件。'
    original_option['effects']['state_assignments']['lead_roster_disposition'] = '交给记者'
    # D78 delivers a current follow-up dossier, not a second historic original.
    ds['dp6_03']['options'][2]['effects']['state_assignments'].pop('lead_roster_disposition')
    ds['dp6_03']['options'][2]['consequence'] += '这次留下的是当前复检安排资料，不改变早先原始名册已经登记的去向。'
    for o in ds['ev5_03']['options']:
        o['consequence'] = o['consequence'].replace('孙强', '赵建国')
    ds['dp2_07']['prompt'] = '红头文件最底下一栏要填已签约数，须与逐户台账核对；孙强提议先填名字、后换真手印。你报实数还是先把数做出来？本决定不消耗行动点。'
    ds['dp5_10']['options'][3]['text'] = ds['dp5_10']['options'][3]['text'].replace('这几年的交情', '这段时间的配合')
    bs[42]['opening_blocks'][0]['text'] = bs[42]['opening_blocks'][0]['text'].replace('何铁柱本人还没有露面，但这个名字和这个家庭第一次进入了你的案头。', '你到任时已经知道何铁柱和他的家庭，这次送来的是孙子的新检测消息；何铁柱本人尚未到县政府与你当面谈这份结果。')
    bs[60]['opening_blocks'][0]['text'] = bs[60]['opening_blocks'][0]['text'].replace('带回省里', '带回市里')
    ds['dp4_08']['options'][2]['consequence'] = '儿科主任说没有新检查依据，这个字他不能签。你仍要求经办人员重新录入，报送表上的数字被改了，主任没有在修改页签字。原始检验记录另有留存，改写报送数据不能改变孩子的实际检测结果，修改过程与责任也留下了痕迹。'
    ds['dp3_08']['options'][1]['consequence'] = '你向张立说明环评材料和排口排放的疑点，逐项交代哪些是已有记录、哪些是现场见闻，原始资料由谁保管。张立让记录员列出调取清单，要求沿正式渠道核验。谈话留下了线索，不等于你已持有并交出全部原始数据。'
    ds['dp4_09']['presentation_blocks'][0]['text'] = '刘三把真账翻到最底下，夹页是一张三年前两百万元拨款凭证的复印件，用途栏写着前期协调，经手人是赵建国。它与冒领补偿款不是同一叠材料，和技改账、白条之间的联系也仍待核对。铁盒里的账册原件、这张凭证复印件与后续取得的财政原始凭证必须分别登记，你现在决定怎样保管、上报或继续核验。'
    ds['dp4_09']['options'][3]['consequence'] = ds['dp4_09']['options'][3]['consequence'].replace('你把原件收回','你收回这张凭证复印件')
    ds['dp4_09']['options'][4]['consequence'] = ds['dp4_09']['options'][4]['consequence'].replace('先保管好原件','先保管好账册原件及夹页复印件')
    ds['dp5_05']['presentation_blocks'][0]['text'] = '村账已经摊开，周满仓指着一行手写小字追问经手人的名字。你让经办人当场标注所在页，核对字迹，并在他面前复印这一个条目，原账仍在桌上。接下来是继续对照原始检测记录、转谈补偿，还是把这一条交给他自行追问，顺序需要你明确。'
    ds['dp5_05_recovery']['presentation_blocks'][0]['text'] += '重新核账时，你请经办人按现有村账定位周满仓追问的手写条目，当面标注页码、核对字迹并复制这一条。新制的复印件与原账分开摆放，不把此前没有提供过的材料说成他已经拿到。'
    roster_copy = {
        'a':'你把整摞原件收入办公室保险柜，核对页数后登记保管位置，密码重新拨回。原件暂由己方封存，还没有交给上级或记者；后续若要调用，必须另行办理交接，不能把保管当作已经公开。',
        'b':'你核对原件页数，装入机要袋，封条当面压好，交给负责送件的工作人员并签下移交单。原件已进入呈交上级的渠道，不再留在你的保险柜里；接收单位的正式回执仍需跟进，不能提前写成已经办结。',
        'c':'你把牛皮纸袋重新扣好，登记页数后压回抽屉最底下。心里虽给记者留了一个去处，眼下并没有实际交付，原件仍由己方保管。何时提供、怎样保护孩子身份，都要等真正办理交接时说清。',
    }
    for o in ds['dp4_roster_disposition']['options']:
        if o['option_id'] in roster_copy: o['consequence'] = roster_copy[o['option_id']]
    # Later handling must never summon an original already lodged with investigators.
    bs[80]['opening_blocks'][0]['text'] = '第80日，铁盒夹页记载的款项终于与财政账的缺口对上。郑向东先核对交接目录：还在县里的原件按封存手续取用，已移交的由接收单位确认留存，并提供签认的核查工作副本。原件没有因再次谈处置就退回你手上；现在桌上是按来源分别标注的材料，赵建国的经手记录仍需逐项质证。'
    bs[80]['opening_blocks'][2]['text'] = '当众说明、要求补回、暂缓核查、接受交换，或追加移交，都会留下记录。已经交出的原件不能撤回掩埋，后续决定只能涉及己方留存材料和是否继续配合调查。'
    ds['dp6_04']['presentation_blocks'][0]['text'] = '原始凭证所载款项已与财政缺口对上，赵建国等着谈处置。先以交接目录确认原件所在；已交部分只能补充说明或申请调阅，不能重复交付、封存或销毁别处保管的原件。'
    bs[81]['opening_blocks'][0]['text'] += '郑向东把交接目录单列在旁：已移交部分仍由接收单位保存，县里能处置的只是剩余原件、核查工作副本和刘三新补的说明。之后无论上报还是封存，都按这份目录办理，不会把已经交出的账册算作重新回到县里。'
    ds['dp6_05']['presentation_blocks'][0]['text'] = '刘三对经手账目的说明已有进展。你只能处置己方尚存的材料；已经移交的原件不会返回。继续完整补报、限制上报范围、封存剩余材料或者毁弃自己所持部分，必须明确边界。'
    for did in ('dp6_04','dp6_05'):
        for o in ds[did]['options']:
            # The operative text refers only to the extant held material, never remote custody.
            o['text'] = o['text'].replace('这份材料原件','己方尚存材料及交接记录').replace('把原件','把尚存原件').replace('把账原样交出去，一张不留','把己方尚存的账目及补充说明完整交出去').replace('把铁盒封存归档','把己方尚存铁盒材料封存归档').replace('让这本账不存在','毁弃己方尚存的账目材料')
            o['consequence'] = o['consequence'].replace('原件列入移交目录','尚存原件与补充说明列入移交目录').replace('账册连同附件按原样移交','己方尚存账册材料连同补充说明按原样移交').replace('完整账册却不只这一个名字','完整账目记录却不只这一个名字').replace('仍留在原件里','仍可沿原有凭证继续核对').replace('铁盒封存归档','己方尚存的铁盒材料封存归档').replace('你让账册被销毁','你让己方尚存的账目材料被销毁').replace('眼前少了一本账','眼前少了一份可供核查的材料')
            o['consequence'] += '此次办理以现有交接目录为限，已经移交的原件仍在接收单位，不因你的决定而取回或消失。'
    ds['dp6_04']['options'][0]['consequence'] = ds['dp6_04']['options'][0]['consequence'].replace('原始凭证摊在班子会上','按目录取用的凭证材料摊在班子会上')
    ds['dp6_04']['options'][2]['consequence'] = ds['dp6_04']['options'][2]['consequence'].replace('原件保住了，却还没有进入正式核查','此次暂存己方材料，没有追加核查说明')
    ds['dp6_04']['options'][4]['consequence'] = ds['dp6_04']['options'][4]['consequence'].replace('尚存原件与补充说明','己方尚存材料及补充说明')
    ds['dp6_05']['options'][2]['consequence'] = ds['dp6_05']['options'][2]['consequence'].replace('核查却尚未展开','此次没有追加报送')
    bs[83]['opening_blocks'][0]['text'] = '第83日，陈默把尚未发表的稿子带到县政府。标题写着清江边的孩子，正文里有血铅、搬迁、环评和家属口述。他先核对此前名册的交接去向：已经拿到的继续查证，未取得的沿保管渠道申请核验，不能要求你再交一遍已经交出的原件。今天还要确认县里是否公开整改承诺。'
    # Every sorting decision retains the full permutation, not only its leading label.
    for d in decisions:
        if d.get('input_kind') != 'sorting': continue
        labels = d['input_schema']['labels']
        for o in d['options']:
            order = o['option_id'].split('_')
            sequence = '、'.join(labels[k] for k in order)
            if d['decision_id'] == 'dp6_07':
                o['consequence'] = '郑向东按你给出的次序逐项登记：'+sequence+'。'+SORTING_RESPONSES[order[0]]+'后续事项依次推进，未办完的仍列在清单上，不能因排了顺序就一并销号。'
            else:
                o['consequence'] = '郑向东依次记下：'+sequence+'。你先处理'+labels[order[0]]+'，其余事项按这个先后安排人手与交接，排在后面的不能写成已经办完。'
                flags = o['effects'].get('open_flags', [])
                if '水样封存' in flags: o['consequence'] += '排口取证在安排中赶上了时机，取得的水样已编号封存，后续检测另行核验。'
                if '错过水样' in flags: o['consequence'] += '轮到排口取证时已错过这次排放，没取得的水样不能补记为已封存。'
                if '失信于谭' in flags: o['consequence'] += '谭老六没有在约定时限得到卷宗答复，这次耽搁留下了失约记录。'
    phone = ds['dp2_02']['text_variants'][0]
    phone['option_consequences'] = {
        'a':'你在电话里明确回绝赵建国转达的施压，要求合作仍走公开程序。那头停了片刻，结束了通话。你记下接触经过，这一次没有收到任何实物。',
        'b':'电话里有人说漏一句，八千万的盘子里有六千万是钱伟早就算好的。你追问时，对方改了话题。通话结束，你把这句话和时间记下，作为仍待核实的线索。',
        'd':'电话结束，你没有把话说死，也没有作出明确承诺。赵建国说让你再想想。你留下通话记录，既没有收到实物，也不能把含糊的答复当作事情已经了结。',
    }
    ds['dp4_07']['options'][1]['consequence'] = '你整理出可核验的检测汇总，隐去姓名和具体住址，说明它不是原始名册，也不改变原件的保管去向。陈默逐项问过数字出处，记下仍需补核的地方。报道有了可对照的线索，未核部分不能写成定论。'
    # A refused interview request must not narrate agreement. Consequences read pre-choice flags.
    ds['dp4_07'].setdefault('text_variants', []).append({
        'variant_id':'press_request_after_clearance', 'required_flags':['门诊楼前被清场'],
        'option_consequences':{'e':'陈默没有答应压稿。他说自己看见了医院门前的清场，还要继续核实家属的说法。你提出的延后请求没有得到同意，他收好采访记录离开。'}})
    for day in (46,48):
        for b in bs[day]['night_blocks']:
            b['text'] = b['text'].replace('昨夜','今夜').replace('天亮了，','夜深了，').replace('天亮前被人围住','很快被人围住')
    # Night events are already prompted and resolved by the event queue before end-day.
    bs[58]['night_blocks'][0]['text'] = '夜深后，你回看围堰险情的值班记录：已下达的安排继续跟进，尚未落实的列入交接。办公室的电话暂时安静下来，现场情况仍要随时核实。'
    bs[75]['night_blocks'][0]['text'] = '夜里，你把今天的通话与办理记录归到案头。已说清的留下记录，未核实的继续待办。首批名册结转的时间到了，后续事项仍须按真实完成日期登记。'
    # Known facts: narrowly matched public-text replacements only.
    text_replacements = {
        '四十一户，一户十万，我出。':'四十一个孩子，每个孩子十万元的救助费，我出。',
        '宏达化工那几座锈红色的旧厂房撞进眼里':'已关停的旧冶炼厂那几座锈红色厂房撞进眼里',
        '门楣上宏达化工四个字的招牌，一角已经耷拉下来，在江风里一荡一荡。':'这里是已关停的旧冶炼厂遗址，不是当前仍在经营、拟扩建的宏达厂区。',
        '清江上游十二公里有一座冶炼厂。':'清江上游约两公里有一座已关停的旧冶炼厂。',
        '宏达化工六千万的补偿底线':'宏达化工承诺分期承担的六千万元',
        '化工厂两亿元的年税测算':'项目投产后两亿元的年税测算',
        '省城来的独立调查记者，三天前就到了云溪':'省城来的独立调查记者，这次于三天前再次回到云溪',
        '袁桂兰把孙子背回了村里':'袁桂兰把孩子抱回了村里',
        '讲那九个孩子':'讲那十一个孩子',
        '讲这些年你替他挡过什么':'讲这段时间你与他的配合',
        '讲这几年你替他':'讲这段时间你替他',
    }
    def public_replace(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('text','title','prompt','consequence','summary','detail','description') and isinstance(child,str):
                    for before, after in text_replacements.items(): child = child.replace(before, after)
                    value[key] = child
                else: public_replace(child)
        elif isinstance(value, list):
            for child in value: public_replace(child)
    for doc in docs.values(): public_replace(doc)
    for d in decisions:
        for o in d['options']:
            o['consequence'] = o['consequence'].replace(',', '，')
    apply_source_restoration(docs, source)
    apply_author_revision(docs)
    # Update only rows whose registered order/blocks changed. No thresholds,
    # action costs or route witness choices are regenerated.
    for row in docs['story_acceptance_matrix.json']['days']:
        day = row['story_day']
        opening_text = '\n'.join(b.get('speaker','')+'\n'+b['text'] for b in bs[day]['opening_blocks'])
        actual_ids = [n['npc_id'] for n in docs['npc_profiles.json']['npcs'] if n['name'] in opening_text]
        row['introduced_npc_ids'] = list(dict.fromkeys([n for n in row['introduced_npc_ids'] if n in actual_ids]+actual_ids))
        row['npc_discovery_transitions'] = ([{'npc_id':n,'state':'mentioned'} for n in row['introduced_npc_ids']]
            + [t for t in row['npc_discovery_transitions'] if t['state'] != 'mentioned'])
        if day not in (2,12,17,34,38,43,44,53,56,58,59,61,69):
            continue
        beat = bs[day]
        opening_ids = [b['block_id'] for b in beat['opening_blocks']]
        row['opening_block_ids'] = opening_ids
        row['required_story_entry_ids'] = list(opening_ids)
        if day == 43:
            row['decision_ids'].remove('dp3_08')
        if day == 44:
            row['decision_ids'].insert(0, 'dp3_08')
        day_decisions = [ds[did] for did in row['decision_ids']]
        blocks = [b for d in day_decisions for b in d.get('presentation_blocks', [])]
        row['prerequisite_narrative_ids'] = [b['block_id'] for b in blocks]
        row['decision_display_node_ids'] = [b['block_id'] for b in blocks]
        row['decision_presentation_order'] = [dict(decision_id=d['decision_id'], presentation_entry_ids=[b['block_id'] for b in d.get('presentation_blocks', [])]) for d in day_decisions]
        row['outcome_transition_ids'] = [b['block_id'] for d in day_decisions for b in d.get('followup_blocks', [])]
        all_blocks = [*beat['opening_blocks'], *(b for d in day_decisions for b in [*d.get('presentation_blocks', []), *d.get('followup_blocks', [])])]
        row['scene_ids'] = list(dict.fromkeys(b['scene_id'] for b in all_blocks if b.get('scene_id')))
        row['visible_speakers'] = list(dict.fromkeys(b['speaker'] for b in beat['opening_blocks'] if b.get('speaker')))
        if day == 61:
            profiles = {n['name']:n['npc_id'] for n in docs['npc_profiles.json']['npcs']}
            row['npc_discovery_transitions'] = (
                [{'npc_id':n,'state':'mentioned'} for n in row['introduced_npc_ids']]
                + [{'npc_id':profiles[name],'state':'encountered'} for name in row['visible_speakers']]
                + [t for t in row['npc_discovery_transitions'] if t['state']=='contactable'])
    # Registry reflects final prose, including fact-level fixes.
    for review in reviews:
        _, did, oid, _ = review['review_id'].split(':')
        review['after'] = next(o['consequence'] for o in ds[did]['options'] if o['option_id']==oid)
        if review['after'] != review['before'] and review['disposition'] == 'keep':
            review['disposition'] = 'rewrite'
            review['reason'] = '独立复审补正：完整排列、人物身份或资料交接边界，以最终登记正文为准。'
    docs['ending_rules.json'] = apply_author_endings(apply_endings(docs['ending_rules.json']))
    return docs, reviews

def diff_operations(before, after):
    from tools.story_revision import _context, _tokens, _child, _public_path
    result = []
    def visit(file, a, b, pointer=''):
        if a == b: return
        if isinstance(a,dict) and isinstance(b,dict):
            for key in a.keys() | b.keys():
                p = pointer+'/'+key.replace('~','~0').replace('/','~1')
                if key not in a: result.append(dict(file=file,pointer=p,op='add',after=b[key],category='story_consistency',issue_ids=['I09-I14']))
                elif key not in b: result.append(dict(file=file,pointer=p,op='remove',before=a[key],category='story_consistency',issue_ids=['I09-I14']))
                else: visit(file,a[key],b[key],p)
        elif isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
            for i,(x,y) in enumerate(zip(a,b)): visit(file,x,y,pointer+f'/{i}')
        else:
            result.append(dict(file=file,pointer=pointer,op='replace',before=a,after=b,
                               category='copy' if isinstance(a,str) and isinstance(b,str) else 'story_consistency',issue_ids=['I01-I14']))
    for file in sorted(before): visit(file,before[file],after[file])
    for op in result:
        tokens = _tokens(op['pointer'])
        value = before[op['file']]
        ancestors = [value]
        for token in tokens[:-1]:
            value = _child(value, token)
            ancestors.append(value)
        _, node_id, option_id = _context(ancestors)
        if len(tokens) >= 2 and tokens[-2] in ('option_texts','option_consequences'):
            option_id = tokens[-1]
        if tokens[0] == 'conversation_contexts' and len(tokens)>1: node_id=tokens[1]
        if node_id is not None: op['node_id']=node_id
        if option_id is not None: op['option_id']=option_id
        if not _public_path(op['file'],op['pointer']): op['category']='story_consistency'
    return result

def build(output: Path):
    output = output.resolve()
    if output.exists(): raise ValueError('Output must not exist')
    if BACKEND.resolve() == output or BACKEND.resolve().is_relative_to(output):
        raise ValueError('Output cannot contain source')
    baseline_hashes = verify_baseline()
    before = {p.name:read(p) for p in (BASELINE/'baseline-package').glob('*.json')}
    docs, reviews = revise(before)
    operations = diff_operations(before, docs)
    output.mkdir(parents=True)
    pkg = output/'packages/pkg_gameplay_v3'
    shutil.copytree(BASELINE/'baseline-package', pkg)
    for file, doc in docs.items():
        if doc != before[file]: dump(pkg/file,doc)
    authority = read(BASELINE/'baseline-authority.json')
    for row in authority['days']:
        day = row['story_day']
        day_decisions = deepcopy([d for d in docs['decisions.json']['decisions'] if d['story_day']==day])
        for d in day_decisions:
            for o in d['options']:
                for key in ('required_fact_ids','required_any_fact_ids','unlock_requirements'): o.pop(key,None)
        projection = {'beat':next(b for b in docs['story_beats.json']['beats'] if b['story_day']==day),'decisions':day_decisions}
        row['previous_sha256'] = row['sha256']
        row['sha256'] = hashlib.sha256(json.dumps(projection,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    authority['revision_source'] = 'content/editorial/story_integrity_20260908.json'
    dump(output/'story_authority_d13_d30.json',authority)
    manifest = docs['package_manifest.json']
    manifest['package_version'] = '3.5.17-fixed-story-continuity'
    manifest['source_version'] = '最终剧本_20260908_连贯性统修'
    manifest['source_sha256'] = 'sha256:' + hashlib.sha256(authored_source_path().read_bytes()).hexdigest()
    manifest['notes'] = manifest['notes'].replace('18项事实与线索', '19项事实与线索')
    manifest['notes'] += '；2026-09-08受控修订：恢复完整后果、正式标题、条件转场与结局一致性；不迁移旧存档。'
    manifest['notes'] += '；保留D2/D17/D34/D59/D61原稿回填及D46原件护栏；按用户确认的原稿统修解决七项遗留：旧案继承、完整答复、人物身份、请示层级、结局时序与冲突附记。'
    dump(pkg/'package_manifest.json',manifest)
    from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader
    manifest['content_hash'] = FileScriptPackageLoader.compute_content_hash(pkg)
    dump(pkg/'package_manifest.json',manifest)
    operations = diff_operations(before,docs)
    authorizations = [dict(op, approved_by='user-approved design + independent editorial review 2026-09-08')
                      for op in operations if op['category']=='story_consistency']
    from tools.story_revision import apply_operations, validate_operation_identities
    validate_operation_identities(before,operations)
    if apply_operations(before,operations,consistency_authorizations=authorizations) != docs:
        raise ValueError('Registered operations did not reconstruct the exact candidate')
    revision = dict(schema_version=1,base_package_id='pkg_gameplay_v3',base_package_version=before['package_manifest.json']['package_version'],
                    base_file_hashes=baseline_hashes,
                    reviews=reviews,ending_reviews=ending_reviews(before['ending_rules.json']),operations=operations,
                    consistency_authorizations=authorizations,
                    source_restoration=dict(source_sha256=hashlib.sha256(authored_source_path().read_bytes()).hexdigest(),
                        historical_source_sha256=SOURCE_SHA256,
                        source_file='.codex-worktrees/backend-0c15d36/最终剧本.md',
                        restored=SOURCE_RESTORATIONS, unresolved={},
                        authored_revision='content/editorial/story_author_source_20260908.json',
                        resolved_issues=list(UNRESOLVED_SOURCE_ISSUES)))
    dump(output/'story_integrity_20260908.json',revision)
    print(json.dumps({'candidate':str(output),'operations':len(operations),'options_reviewed':len(reviews)},ensure_ascii=False))

def install_code(candidate: Path, previous_candidate: Path | None = None):
    """Integrate this exact reviewed candidate into the isolated code worktree.

    Refuse drift; do not touch deployment, DBs, or unrelated working changes.
    """
    from unittest.mock import patch
    from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader
    candidate = candidate.resolve()
    verify_baseline()
    if not candidate.is_relative_to(BASELINE.resolve()):
        raise ValueError('Candidate must be within this revision evidence directory')
    pkg = candidate/'packages/pkg_gameplay_v3'
    with patch('serious_game_backend.infrastructure.script_packages.file_loader.STORY_AUTHORITY_CONTRACT', candidate/'story_authority_d13_d30.json'):
        FileScriptPackageLoader().load(pkg)
    target = BACKEND/'content/packages/pkg_gameplay_v3'
    revision = read(candidate/'story_integrity_20260908.json')
    expected_hashes = revision['base_file_hashes']
    expected_authority = BASELINE/'baseline-authority.json'
    expected_editorial = None
    if previous_candidate is not None:
        previous_candidate = previous_candidate.resolve()
        if not previous_candidate.is_relative_to(BASELINE.resolve()) or previous_candidate == candidate:
            raise ValueError('Previous candidate must be a distinct revision evidence directory')
        previous_package = previous_candidate/'packages/pkg_gameplay_v3'
        expected_hashes = {p.relative_to(previous_package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in previous_package.rglob('*') if p.is_file()}
        if set(expected_hashes) != set(revision['base_file_hashes']):
            raise ValueError('Previous candidate file inventory drift')
        expected_authority = previous_candidate/'story_authority_d13_d30.json'
        expected_editorial = previous_candidate/'story_integrity_20260908.json'
    verify_install_target(target, expected_hashes,
        BACKEND/'content/authority/story_authority_d13_d30.json', expected_authority,
        BACKEND/'content/editorial/story_integrity_20260908.json', expected_editorial)
    for file in pkg.rglob('*'):
        if file.is_file():
            name = file.relative_to(pkg)
            if file.read_bytes() != (target/name).read_bytes():
                shutil.copyfile(file, target/name)
    shutil.copyfile(candidate/'story_authority_d13_d30.json', BACKEND/'content/authority/story_authority_d13_d30.json')
    shutil.copyfile(candidate/'story_integrity_20260908.json', BACKEND/'content/editorial/story_integrity_20260908.json')
    FileScriptPackageLoader().load(target)
    print('Integrated verified candidate into isolated code worktree; deployment and saves untouched.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--install-code', type=Path)
    parser.add_argument('--previous-candidate', type=Path)
    args = parser.parse_args()
    if args.output: build(args.output)
    else: install_code(args.install_code, args.previous_candidate)
