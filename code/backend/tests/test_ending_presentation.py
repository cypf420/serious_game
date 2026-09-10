"""Ending DTO/read compatibility; fixtures are not legal gameplay route evidence."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import re

import pytest

from serious_game_backend.application.ending_service import EndingAxisProjector, EndingService
from serious_game_backend.application.review_service import ReviewService
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.domain.enums import SessionStatus
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.game_state import GameState
from serious_game_backend.domain.household_settlement import D75SettlementSnapshot, HouseholdSettlementEntry
from serious_game_backend.infrastructure.repositories.codec import encode_session, decode_session
from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader

COUNTS = [0, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36]
AXES = ["溃败", "溃败", "差一两户", "差一两户", "压线", "压线", "宽裕", "宽裕", "全额", "全额", "全额"]


@pytest.fixture(scope="module", params=["pkg_backend_dev_v1", "pkg_gameplay_v2", "pkg_gameplay_v3"])
def ending_package(request):
    return FileScriptPackageLoader().load(
        Path(__file__).resolve().parents[1] / "content/packages" / request.param
    )


def make_session(package, count):
    session = GameSession(
        session_id="ending-test", account_id="test", package_id=package.package_id,
        package_version=package.package_version, package_content_hash=package.content_hash,
        random_seed="ending-test", origin_id="technical",
        game_state=GameState(story_day=90, signed_households=count),
    )
    first = min(count, 27)
    session.d75_settlement_snapshot = D75SettlementSnapshot(75, first)
    if count > first:
        session.household_settlement_entries.append(HouseholdSettlementEntry(
            entry_id="test-entry", household_group_id="test-group", household_count=count-first,
            signed_day=89, entry_batch="post75_confirmation", entry_type="contract",
            source_node_id="test", policy_version="test", eligibility_registered_day=75,
        ))
    # A void entry must not inflate the audited total.
    session.household_settlement_entries.append(HouseholdSettlementEntry(
        entry_id="void-entry", household_group_id="void-group", household_count=1,
        signed_day=89, entry_batch="post75_confirmation", entry_type="contract",
        source_node_id="test", policy_version="test", eligibility_registered_day=75,
        validity_status="void",
    ))
    return session


@pytest.mark.parametrize("count,axis", zip(COUNTS, AXES))
def test_new_ending_uses_audited_count_and_preserves_axis_boundaries(ending_package, count, axis):
    session = make_session(ending_package, count)
    service = EndingService(EndingAxisProjector())
    result = service.finalize(session, ending_package)
    assert (result["signed_households"], result["total_households"], result["target_signed_households"]) == (count, 36, 30)
    assert result["axes"]["A"] == axis
    assert ("最后一公里攻坚成功" in session.flags) == (count >= 30)
    assert session.status == SessionStatus.ENDED
    assert result["main_text"] in session.narrative_feed[-1].text
    assert result["sub_text"] in session.narrative_feed[-1].text
    saved = encode_session(session)
    assert service.finalize(session, ending_package) == result
    assert encode_session(session) == saved


@pytest.mark.parametrize("count", COUNTS)
@pytest.mark.parametrize("has_snapshot", [True, False])
def test_old_ending_read_projections_are_consistent_and_do_not_mutate_save(ending_package, count, has_snapshot):
    session = make_session(ending_package, count)
    if not has_snapshot:
        session.d75_settlement_snapshot = None
    else:
        # Old aggregate fields may disagree: projection must use the audited value.
        session.game_state = replace(session.game_state, signed_households=0)
    session.status = SessionStatus.ENDED
    session.ending_result = {
        "main_ending_id": "ending_01", "sub_ending_id": "ending_01a",
        "main_text": "原结局正文", "sub_text": "台账没有超过 27/36 户。",
        "axes": {"A": "溃败"}, "appendices": [{"title": "旧附录", "text": "原文"}],
    }
    session = decode_session(encode_session(session))
    before = deepcopy(encode_session(session))
    projector = VisibleStateProjector()
    state = projector.project(session, ending_package)
    review = ReviewService(projector).build(session, ending_package)
    assert state["ledger"]["signed_households"]["signed"] == count
    assert state["ending"]["signed_households"] == count
    assert state["ending"]["total_households"] == 36
    assert state["ending"]["target_signed_households"] == 30
    assert state["ending"] == review["ending"] == review["final_visible_state"]["ending"]
    assert f"{count}/36 户" in state["ending"]["sub_text"]
    for key in ("main_ending_id", "sub_ending_id", "axes", "appendices"):
        assert state["ending"][key] == before["ending_result"][key]
    assert encode_session(session) == before


@pytest.mark.parametrize("count", COUNTS)
def test_all_configured_ending_texts_render_actual_counts(ending_package, count):
    assert (len(ending_package.main_endings), len(ending_package.sub_endings)) == (24, 95)
    before = deepcopy(ending_package)
    for item in (*ending_package.main_endings, *ending_package.sub_endings):
        rendered = EndingService._render_sub_text(item.text, count)
        assert all(int(n) == count for n in re.findall(r"(\d+)/36", rendered))
        assert "三十六户全签" not in rendered
        assert "台账还是没过" not in rendered
        assert EndingService._render_sub_text(rendered, count) == rendered
    assert ending_package == before


def test_finalization_still_rejects_unaudited_aggregate(ending_package):
    session = make_session(ending_package, 29)
    session.game_state = replace(session.game_state, signed_households=30)
    with pytest.raises(ContentValidationError, match="不一致"):
        EndingService(EndingAxisProjector()).finalize(session, ending_package)
    assert session.ending_result is None


def test_unfinished_session_has_no_ending(ending_package):
    session = make_session(ending_package, 0)
    assert EndingService.project_result(session) is None
    assert ReviewService(VisibleStateProjector()).build(session, ending_package)["ending"] is None


@pytest.mark.parametrize("count", COUNTS)
def test_old_final_feed_uses_projected_ending_without_changing_other_entries(ending_package, count):
    session = make_session(ending_package, count)
    session.ending_result = {
        "sub_ending_title": "原结局标题", "main_text": "原主文",
        "sub_text": "台账没有超过 27/36 户。",
    }
    session.append_narrative(story_day=89, kind="narrative", text="历史台账 27/36 户。", content_instance_id="old-scene")
    session.append_narrative(story_day=90, kind="ending", text="旧的结局 27/36 户。", content_instance_id="ending:final")
    session.append_narrative(story_day=90, kind="ending", text="另一条结案历史。", content_instance_id="ending:other")
    before = deepcopy(encode_session(session))
    result = EndingService.project_result(session)
    feed = StoryFlowService.feed_since(session, 0)
    assert feed["items"][0]["text"] == "历史台账 27/36 户。"
    assert feed["items"][1]["text"] == f"余波：原结局标题\n\n原主文\n\n{result['sub_text']}"
    assert feed["items"][2]["text"] == "另一条结案历史。"
    assert StoryFlowService.feed_since(session, 1)["items"] == feed["items"][1:]
    assert StoryFlowService.feed_since(session, 3)["items"] == []
    assert StoryFlowService.feed_since(session, 0) == feed
    assert encode_session(session) == before


def test_count_rendering_does_not_rewrite_unrelated_ratios():
    text = "此前的纸上写着 29/36 户。三十户是目标线。"
    assert EndingService._render_sub_text(text, 28) == text
    text = "台账最终停在 29/36 户，离三十户差一个门牌号。"
    result = EndingService._render_sub_text(text, 28)
    assert result == "台账最终签到了 28/36 户，离三十户还差 2 户。"
    assert EndingService._render_sub_text(result, 28) == result


@pytest.mark.parametrize("count", [0, 28, 31, 35])
def test_ending_read_endpoints_share_readonly_projection(count):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from serious_game_backend.api.app import create_app
    from serious_game_backend.config import Settings
    from tests.test_doubles import build_test_container

    settings = Settings(environment="test", repository="memory", role_llm_provider="none",
                        default_package_id="pkg_gameplay_v3",
                        content_root=Path(__file__).resolve().parents[1] / "content/packages")
    runtime = build_test_container(settings)
    client = TestClient(create_app(settings, runtime))
    headers = {"X-Account-ID": "ending-read-test"}
    created = client.post("/api/game/session", headers=headers, json={"client_request_id": "ending-read"})
    assert created.status_code == 201
    sid = created.json()["session_id"]
    package = runtime.packages.get("pkg_gameplay_v3")
    session = make_session(package, count)
    session.session_id = sid
    session.account_id = "ending-read-test"
    session.status = SessionStatus.ENDED
    session.ending_result = {
        "main_ending_id": "ending_01", "sub_ending_id": "ending_01a",
        "sub_ending_title": "旧结局", "main_text": "旧主文",
        "sub_text": "台账没有超过 27/36 户。", "axes": {"A": "溃败"},
    }
    session.append_narrative(story_day=90, kind="ending", text="旧的结局 27/36 户。", content_instance_id="ending:final")
    runtime.sessions.save(session, expected_version=session.state_version)
    before = encode_session(runtime.sessions.get_owned(sid, "ending-read-test"))
    with patch.object(runtime.sessions, "save", side_effect=AssertionError("GET must not save")):
        status = client.get(f"/api/game/session/{sid}", headers=headers)
        view = client.get(f"/api/game/session/{sid}/view", headers=headers)
        feed = client.get(f"/api/game/session/{sid}/feed", headers=headers)
        review = client.get(f"/api/game/session/{sid}/review", headers=headers)
    assert (view.status_code, feed.status_code, review.status_code) == (200, 200, 200)
    state = view.json()["state"]
    assert status.status_code == 200
    assert status.json()["ending"] == state["ending"]
    assert state["ending"]["signed_households"] == count
    assert state["ledger"]["signed_households"]["signed"] == count
    assert review.json()["ending"] == state["ending"]
    assert view.json()["feed"]["items"] == feed.json()["items"]
    assert f"{count}/36 户" in feed.json()["items"][0]["text"]
    assert encode_session(runtime.sessions.get_owned(sid, "ending-read-test")) == before
