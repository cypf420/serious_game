import json
from pathlib import Path

import pytest

from serious_game_backend.application.player_text_policy import player_visible_sentence
from serious_game_backend.application.story_flow_service import StoryFlowService
from tools.audit_story_punctuation import PATTERNS, quote_issues
from tools.story_revision import enumerate_visible_records


@pytest.mark.parametrize("text", [
    "周满仓：「大山叔是族长，我叫他叔。可他那口井在坡上，我那口在坡下。他说话算他那一房的，不算我这一房的。」",
    "周满仓：「我要看的是原始的单子。」",
    "周满仓：「对不上，你说什么我都不信。」",
    "“姓周的在柳林村是十一户。”他说，“我能替他们说话的，只有这六户。”",
    "“我在祠堂里坐了一夜。”老人说，“这两支不听我的，我不能拿他们的名字换你的话。我周大山这辈子没替人做过主。”",
    "他说：“她问‘核实了吗？’”",
    "他说：「她喊『等等！』」",
    "他说：“我想……”",
])
def test_completed_quoted_narration_does_not_gain_another_period(text):
    assert player_visible_sentence(text) == text
    assert StoryFlowService.public_text(text) == text


@pytest.mark.parametrize(("text", "expected"), [
    ("", ""), ("手续已核实", "手续已核实。"),
    ("手续已核实，", "手续已核实。"),
    ("这叫“先核实”", "这叫“先核实”。"),
    ("他说：“先核实。”随后起身", "他说：“先核实。”随后起身。"),
])
def test_unfinished_narration_still_gets_its_sentence_ending(text, expected):
    assert player_visible_sentence(text) == expected


@pytest.mark.parametrize(("text", "expected"), [
    ("他说：“材料齐了。”开启旗标。", "他说：“材料齐了。”"),
    ("开启旗标。他问：“核实了吗？”", "他问：“核实了吗？”"),
    ("他说：「先核实。再签字！」本节点完成。", "他说：「先核实。再签字！」"),
    ("他说：“本节点完成。继续。”随后起身。", "随后起身。"),
    ("先核实。\n开启旗标。\n再签字。", "先核实。\n再签字。"),
])
def test_internal_metadata_filter_preserves_sentence_and_quote_boundaries(text, expected):
    assert StoryFlowService.public_text(text) == expected


def test_all_authored_story_blocks_keep_completed_quote_endings():
    package = Path(__file__).resolve().parents[1] / "content/packages/pkg_gameplay_v3/story_beats.json"
    data = json.loads(package.read_text(encoding="utf-8"))
    checked = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "text" and isinstance(child, str):
                    text = child.strip()
                    if text.endswith(tuple('”’」』')) and text.rstrip('”’」』').endswith(("。", "！", "？", "…")):
                        assert player_visible_sentence(text) == text
                        checked.append(text)
                elif isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(data)
    assert checked, "The corpus check must exercise authored quoted dialogue"


def test_all_registered_player_copy_has_paired_quotes_and_no_corrupt_punctuation():
    package = Path(__file__).resolve().parents[1] / "content/packages/pkg_gameplay_v3"
    records = enumerate_visible_records(package)
    assert records
    for record in records:
        text = record["text"]
        assert not quote_issues(text), record["review_id"]
        for issue in ("redundant_period_after_quote", "repeated_punctuation", "replacement_character", "ascii_punctuation", "short_ellipsis"):
            assert not PATTERNS[issue].search(text), (record["review_id"], issue)
        if record["file"] in {"story_beats.json", "decisions.json", "ending_rules.json"} and record["kind"] in {"text", "prompt", "consequence"}:
            displayed = StoryFlowService.public_text(text)
            assert not quote_issues(displayed), record["review_id"]
            assert not PATTERNS["redundant_period_after_quote"].search(displayed), record["review_id"]
