"""Check reviewed ending copy and old-save rendering without changing selection."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re

from serious_game_backend.application.ending_prose import revise_ending_prose
from serious_game_backend.application.ending_service import EndingService
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.game_state import GameState


def test_all_119_endings_have_no_repeated_complete_sentences_after_revision():
    path = Path(__file__).resolve().parents[1] / "content/packages/pkg_gameplay_v3/ending_rules.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["main_endings"]) == 24
    assert len(data["sub_endings"]) == 95
    changed = set()
    for item in data["main_endings"] + data["sub_endings"]:
        identity = item.get("ending_id", item.get("sub_ending_id"))
        revised = revise_ending_prose(item["text"])
        if revised != item["text"]:
            changed.add(identity)
        sentences = [s.strip() for s in re.findall(r"[^。！？\n]+[。！？]?", revised) if s.strip()]
        assert not {s: n for s, n in Counter(sentences).items() if n > 1}, identity
        assert revise_ending_prose(revised) == revised
        assert revised.count("\n\n") == item["text"].count("\n\n")
        assert revise_ending_prose(EndingService._render_sub_text(item["text"], 30)) == EndingService._render_sub_text(item["text"], 30)
    assert changed == {"ending_03", "ending_08", "ending_14", "ending_15", "ending_21"}


def test_saved_ending_and_feed_apply_revision_without_mutating_history():
    original = "你说我知道。他不说话了。他到最后也没弄明白。"
    session = GameSession(session_id="copy-test", account_id="test", package_id="test", package_version="1", package_content_hash="test", random_seed="test", origin_id="technical", game_state=GameState())
    session.ending_result = {"main_ending_id": "ending_08", "main_text": original, "sub_text": "余波。", "sub_ending_title": "原副标题"}
    session.append_narrative(story_day=90, kind="ending", text=original, content_instance_id="ending:final")
    saved = deepcopy(session.ending_result)
    assert EndingService.project_result(session)["main_text"] == "你说我知道。他到最后也没弄明白。"
    assert original not in StoryFlowService.feed_since(session, 0)["items"][0]["text"]
    assert session.ending_result == saved
    assert session.narrative_feed[-1].text == original


def test_unrelated_repeated_dialogue_is_not_removed():
    text = "他不说话了。\n\n他不说话了。"
    assert revise_ending_prose(text) == text
