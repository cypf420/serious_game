"""T4 editorial unit tests; these are not legal-route or browser evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from serious_game_backend.application import ending_service as runtime
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.game_state import GameState

BACKEND = Path(__file__).resolve().parents[1]
CURRENT = BACKEND / 'content/packages/pkg_gameplay_v3/ending_rules.json'
BASELINE = BACKEND.parents[1] / 'output/story-integrity/20260908-implementation/baseline-package/ending_rules.json'
SIDECAR = BACKEND / 'content/editorial/story_integrity_endings.py'


def editorial():
    assert SIDECAR.is_file(), 'T4 pure transformation has not been implemented'
    spec = importlib.util.spec_from_file_location('t4_endings', SIDECAR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=[CURRENT, BASELINE], ids=['current', 'baseline'])
def document(request):
    return json.loads(request.param.read_text(encoding='utf-8'))


def texts(document):
    return {r.get('ending_id', r.get('sub_ending_id')): r['text']
            for key in ('main_endings', 'sub_endings') for r in document[key]}


def test_only_text_changes_and_input_is_independent(document):
    saved = deepcopy(document)
    revised = editorial().apply_endings(document)
    assert document == saved
    assert revised is not document
    assert [len(revised[k]) for k in ('main_endings', 'sub_endings')] == [24, 95]
    for key in ('main_endings', 'sub_endings'):
        for old, new in zip(saved[key], revised[key], strict=True):
            assert {k: v for k, v in old.items() if k != 'text'} == {
                k: v for k, v in new.items() if k != 'text'}
            new['text'] = old['text']
    assert revised == saved  # includes axes, predicates, priorities and appendices
    revised['main_endings'][0]['condition'].clear()
    assert document == saved


@pytest.mark.parametrize('sub_id,forbidden,positive', [
    ('16a', '项目没有站住', '站在你身后'),
    ('16b', '项目停在半路上', '文件到你桌上'),
    ('16c', '项目烂在最后一段', '材料摔在桌上'),
    ('17a', '事没成', '记者'),
    ('17c', '事没有办完', '稿子摁了下去'),
])
def test_success_combinations_retain_relationship_consequences(document, sub_id, forbidden, positive):
    t = texts(editorial().apply_endings(document))
    sub = t['ending_' + sub_id]
    assert forbidden not in sub
    assert '达线' in sub and positive in sub
    assert '达线' in t['ending_' + sub_id[:2]]


@pytest.mark.parametrize('main_id,forbidden', [
    ('09', '排污口没人再提'), ('10', '被这份漂亮台账盖了过去'),
    ('11', '河下游浇不得地的那几亩'), ('18', '排污口从来没真关过'),
    ('16', '你手下这套班子，事是办成了，人也'),
    ('17', '你没接触过，也没顾上'),
])
def test_mains_leave_free_axis_open(document, main_id, forbidden):
    assert forbidden not in texts(editorial().apply_endings(document))['ending_' + main_id]


def test_arrest_destination_and_legal_voice(document):
    t = texts(editorial().apply_endings(document))
    assert '数字漂亮，签约达线，程序完整' not in t['ending_01']
    assert '头一天晚上你被带走了' not in t['ending_01c']
    assert '九点四十分' in t['ending_01'] and '当天上午' in t['ending_01c']
    assert '市里一个没有实权' not in t['ending_13'] and '县政协' in t['ending_13a']
    assert '市里某个部门的副职' not in t['ending_14'] and '邻县' in t['ending_14a']
    assert '赵局长' not in t['ending_13']
    assert '这些都不违法。' not in t['ending_15']
    assert '它们都合规' not in t['ending_15']
    assert '你告诉自己' in t['ending_15'] and '核查' in t['ending_15']


def test_no_unearned_completion_or_erased_knowledge(document):
    all_text = '\n'.join(texts(editorial().apply_endings(document)).values())
    for phrase in ('全部搬迁完成', '人都搬走了', '村子已经空了', '村子腾空了',
                   '一个不落地清完了', '人都住进了安置区', '孩子的病治了',
                   '没有一份检测单摆到你面前', '化验单你从来没见过',
                   '四十一个孩子', '四十一个血铅', '本局再也'):
        assert phrase not in all_text, phrase


@pytest.mark.parametrize('count', [30, 31, 33, 34, 35, 36])
def test_count_bands_do_not_claim_all_households_or_fulfillment(document, count):
    t = texts(editorial().apply_endings(document))
    suffix = 'c' if count <= 31 else 'd' if count <= 33 else 'e'
    for main in ('01', '02', '03', '05'):
        rendered = runtime.EndingService._render_sub_text(t[f'ending_{main}{suffix}'], count)
        assert '三十六户全签' not in rendered
        assert '三十户，' not in rendered and '三十户是够了' not in rendered
        assert '一个不落' not in rendered and '空村子' not in rendered


def test_all_registered_combinations_have_explanations(document):
    module = editorial()
    reviews = module.ending_reviews(document)
    expected = set(texts(document))
    assert len(reviews) == 119
    assert {r['ending_id'] for r in reviews} == expected
    assert all(r['reason'] and r['fixed_facts'] and r['free_axis'] and r['ledger_boundary'] for r in reviews)
    assert {r['disposition'] for r in reviews} <= {'keep', 'rewrite'}
    revised = module.apply_endings(document)
    assert module.apply_endings(revised) == revised


def test_changed_source_clause_is_rejected_without_mutating_input(document):
    document['sub_endings'][0]['text'] = 'An unreviewed replacement.'
    saved = deepcopy(document)
    with pytest.raises(ValueError, match='ending_01a'):
        editorial().apply_endings(document)
    assert document == saved


def test_review_02d_speaker_order_matches_main(document):
    t = texts(editorial().apply_endings(document))
    assert '赵建国先开的口' in t['ending_02']
    assert '最后是蒋崇岳' in t['ending_02']
    assert '蒋崇岳第一个开口' not in t['ending_02d']
    assert '轮到蒋崇岳' in t['ending_02d']


def test_review_21_support_and_corruption_are_not_denied(document):
    t = texts(editorial().apply_endings(document))
    assert '一纸决议' in t['ending_21a']
    for phrase in ('然后什么都没有发生', '没人接', '没人替你把话接下去',
                   '那条牵着赵建国的线也没人去动', '钱伟看着你'):
        assert phrase not in t['ending_21'], phrase
    assert '治理仍未落实' in t['ending_21']
    assert '腐败线' in t['ending_21'] and '另有卷宗' in t['ending_21']


def test_review_24_applause_is_left_to_credit_branch(document):
    t = texts(editorial().apply_endings(document))
    assert '听完鼓了掌' in t['ending_24c']
    assert '没有掌声' not in t['ending_24']


def test_review_09_dinner_quote_names_its_speaker(document):
    t = texts(editorial().apply_endings(document))
    assert '钱伟曾跟人吃饭时说，云溪县这一届，会做事' in t['ending_09']
    assert '他跟人吃饭时说' not in t['ending_09']


def test_review_16_phone_scene_has_one_closing_sentence(document):
    t = texts(editorial().apply_endings(document))
    assert t['ending_16'].count('那些村里人的号码，此刻没有一个拨得出去。') == 1
    assert '未兑现的约定要继续办理' in t['ending_16']


@pytest.mark.parametrize('flags', [
    {'旧账已交巡察组', '掩盖真相'},
    {'两百万已移交立案', '铁盒封存'},
    {'旧账已交巡察组', '账目揭发'},
])
def test_iron_appendix_does_not_destroy_transferred_originals(flags):
    text = appendices(flags)[1]['text']
    assert '原件被销毁' not in text and '原件已不存在' not in text


@pytest.mark.parametrize('flags', [
    {'旧账已交巡察组', '掩盖真相'},
    {'两百万已移交立案', '铁盒封存'},
])
def test_iron_appendix_does_not_erase_prior_receiving_unit_custody(flags):
    text = appendices(flags)[1]['text']
    assert '没有进入最终的案卷' not in text and '却没有见光' not in text
    assert '己方尚存' in text and '接收单位' in text


def session(flags=(), disposition='未获取'):
    return GameSession(session_id='t4', account_id='unit', package_id='unit',
                       package_version='1', package_content_hash='unit', random_seed='t4',
                       game_state=GameState(), origin_id='unit', flags=set(flags),
                       state_values={'lead_roster_disposition': disposition})


def appendices(flags=(), disposition='未获取'):
    data = json.loads(CURRENT.read_text(encoding='utf-8'))
    package = SimpleNamespace(ending_appendices=[SimpleNamespace(**r) for r in data['appendices']])
    return runtime.EndingService._appendices(session(flags, disposition), package)


def test_runtime_constants_are_single_source_with_twelve_candidates():
    for name, size in [('ROSTER_APPENDIX_TEXTS', 5), ('IRON_APPENDIX_TEXTS', 4), ('ROPE_APPENDIX_TEXTS', 3)]:
        assert hasattr(runtime, name), name
        assert len(getattr(runtime, name)) == size


@pytest.mark.parametrize('disposition', ['未获取', '己方封存', '呈交上级', '交给记者', '被销毁'])
def test_roster_runtime_uses_shared_text(disposition, monkeypatch):
    assert hasattr(runtime, 'ROSTER_APPENDIX_TEXTS')
    assert appendices(disposition=disposition)[0]['text'] is runtime.ROSTER_APPENDIX_TEXTS[disposition]
    monkeypatch.setitem(runtime.ROSTER_APPENDIX_TEXTS, disposition, 'shared roster sentinel')
    assert appendices(disposition=disposition)[0]['text'] == 'shared roster sentinel'


def test_not_acquired_does_not_erase_detection_or_other_archives():
    value = appendices(flags={'掌握血铅'})[0]['text']
    assert '没能落进任何一份档案' not in value
    assert '原件' in value and '检测' in value


@pytest.mark.parametrize('flags,key', [
    ([], '未入卷'), (['收受贿赂'], '收受贿赂'),
    (['铁盒封存', '收受贿赂'], '铁盒封存'),
    (['账目揭发', '铁盒封存', '收受贿赂'], '账目揭发'),
])
def test_iron_priority_and_shared_source(flags, key, monkeypatch):
    assert hasattr(runtime, 'IRON_APPENDIX_TEXTS')
    assert appendices(flags)[1]['text'] is runtime.IRON_APPENDIX_TEXTS[key]
    monkeypatch.setitem(runtime.IRON_APPENDIX_TEXTS, key, 'shared iron sentinel')
    assert appendices(flags)[1]['text'] == 'shared iron sentinel'


@pytest.mark.parametrize('flags,key', [
    ([], '未激化'), (['秀英寒心'], '失信'), (['越级上访'], '失信'),
    (['暴力驱逐', '秀英寒心', '越级上访'], '暴力驱逐'),
])
def test_rope_priority_and_shared_source(flags, key, monkeypatch):
    assert hasattr(runtime, 'ROPE_APPENDIX_TEXTS')
    assert appendices(flags)[2]['text'] is runtime.ROPE_APPENDIX_TEXTS[key]
    monkeypatch.setitem(runtime.ROPE_APPENDIX_TEXTS, key, 'shared rope sentinel')
    assert appendices(flags)[2]['text'] == 'shared rope sentinel'
