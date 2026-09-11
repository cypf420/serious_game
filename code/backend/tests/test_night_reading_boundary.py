from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from tests import test_story_review_round1 as helpers
from serious_game_backend.domain.conversation import ActiveConversation, ForcedGroupConversation
from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord

_beats = json.loads((helpers.PACKAGE_DIR / "story_beats.json").read_text(encoding="utf-8"))["beats"]
_night_cases = [(b["story_day"], block) for b in _beats for block in b["night_blocks"]
                if block.get("presentation_phase") != "morning"]


@pytest.mark.parametrize("blocker", ["decision", "conversation", "group", "governance"])
def test_story_continuation_cannot_skip_an_unfinished_interaction(blocker):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f"continuation-gate-{blocker}")
    try:
        session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
        if blocker != "decision":
            session = helper.reset_to_day(runtime, sid, headers, 8)
        if blocker == "conversation":
            session.active_conversation = ActiveConversation(
                conversation_id="DEMO-conversation", opportunity_id="DEMO-opportunity",
                npc_id="npc_wu_xiuying", story_day=8,
            )
        elif blocker == "group":
            session.active_group_conversation = ForcedGroupConversation(
                conversation_id="DEMO-group", conversation_type="petition",
                initiator_npc_id="npc_wu_xiuying", participant_ids=("npc_wu_xiuying",),
                agenda="核对补偿方案", demands=(), urgency="normal", story_day=8,
            )
        elif blocker == "governance":
            session.governance_actions["DEMO-action"] = GovernanceActionRecord(
                action_instance_id="DEMO-action", action_kind="household_visit",
                story_day=8, target_ids=("npc_zhou_dashan",), required_permissions=("1.1",),
            )
        runtime.sessions.save(session, expected_version=session.state_version)
        before = deepcopy(session)
        base = f"/api/game/session/{sid}"
        view = client.get(base + "/view", headers=headers)
        assert view.status_code == 200, view.text
        assert view.json()["commands"]["can_continue_story"] is False
        response = client.post(base + "/story/continue", headers=headers, json={
            "state_version": session.state_version, "client_action_id": "blocked-continuation",
        })
        assert response.status_code == 409, response.text
        assert runtime.sessions.get_owned(sid, headers["X-Account-ID"]) == before
        assert runtime.operations.get(headers["X-Account-ID"], sid, "blocked-continuation") is None
    finally:
        client.close()


@pytest.mark.parametrize("day,block", _night_cases, ids=[block["block_id"] for _, block in _night_cases])
def test_every_conditional_night_block_is_available_before_its_day_ends(day, block):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f"night-block-{block['block_id']}")
    try:
        flags = set(block.get("required_flags", []))
        flags.update(block.get("required_any_flags", [])[:1])
        flags.update(runtime.packages.get("pkg_gameplay_v3").story_day(day).end_day_requires_flags)
        session = helper.reset_to_day(runtime, sid, headers, day, flags=flags)
        session.pending_decision = None
        session.pending_decision_queue.clear()
        runtime.sessions.save(session, expected_version=session.state_version)
        view = client.get(f"/api/game/session/{sid}/view", headers=headers).json()
        assert view["commands"]["can_continue_story"] is True
        assert view["commands"]["can_end_day"] is False
        response = client.post(f"/api/game/session/{sid}/story/continue", headers=headers, json={
            "state_version": session.state_version, "client_action_id": "conditional-night",
        })
        assert response.status_code == 200, response.text
        assert response.json()["phase"] == "story_continued"
        saved = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
        assert saved.game_state.story_day == day
        assert any(i.block_id == block["block_id"] and i.story_day == day for i in saved.narrative_feed)
    finally:
        client.close()


@pytest.mark.parametrize("day", range(1, 90))
def test_every_day_presents_night_before_advancing_and_settles_once(day):
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api(f"night-boundary-{day}")
    try:
        package = runtime.packages.get("pkg_gameplay_v3")
        beat = package.story_day(day)
        session = helper.reset_to_day(runtime, sid, headers, day, flags=set(beat.end_day_requires_flags))
        session.pending_decision = None
        session.pending_decision_queue.clear()
        runtime.sessions.save(session, expected_version=session.state_version)
        before_state = deepcopy(session.game_state)
        before_cursor = session.next_feed_cursor
        expected = [b.block_id for b in beat.night_blocks
                    if b.presentation_phase != "morning"
                    and b.is_visible(origin_id=session.origin_id, flags=session.flags)]
        base = f"/api/game/session/{sid}"
        body = {"state_version": session.state_version,
                "client_action_id": f"read-night-{day}"}
        with patch.object(runtime.end_days._nights, "run_night", wraps=runtime.end_days._nights.run_night) as settle:
            if expected:
                before = deepcopy(runtime.sessions.get_owned(sid, headers["X-Account-ID"]))
                for legacy_option in ({}, {"read_night_first": True}):
                    early = client.post(base + "/end-day", headers=headers, json={**body, **legacy_option})
                    assert early.status_code == 409, early.text
                    assert "STORY_CONTINUATION_REQUIRED" in early.text
                    assert runtime.sessions.get_owned(sid, headers["X-Account-ID"]) == before
                response = client.post(base + "/story/continue", headers=headers, json=body)
                assert response.status_code == 200, response.text
                current = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
                assert response.json()["phase"] == "story_continued"
                assert current.game_state == before_state
                assert settle.call_count == 0
                added = [i for i in current.narrative_feed if i.cursor >= before_cursor]
                assert [i.block_id for i in added] == expected
                assert all(i.story_day == day for i in added)
                # A reload receives the same day and persisted night; retries do
                # not silently advance or charge the settlement twice.
                view = client.get(base + "/view", headers=headers).json()
                assert view["state"]["story"]["day"] == day
                repeated = client.post(base + "/story/continue", headers=headers, json=body)
                assert repeated.json() == response.json()
                assert settle.call_count == 0
                stale = client.post(base + "/story/continue", headers=headers,
                                    json={**body, "client_action_id": f"stale-night-{day}"})
                assert stale.status_code == 409
                body = {**body, "state_version": current.state_version,
                        "client_action_id": f"advance-night-{day}"}
            response = client.post(base + "/end-day", headers=headers, json=body)
            assert response.status_code == 200, response.text
            current = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
            assert current.game_state.story_day == day + 1
            assert settle.call_count == 1
            repeated = client.post(base + "/end-day", headers=headers, json=body)
            assert repeated.json() == response.json()
            assert settle.call_count == 1
            ids = [i.block_id for i in current.narrative_feed if i.block_id in expected]
            assert ids == expected
    finally:
        client.close()


def test_arrival_night_is_split_at_dawn_without_losing_or_repeating_prose():
    helper = helpers.StoryReviewRound1Tests()
    runtime, client, sid, headers = helper.build_api("arrival-dawn-boundary")
    try:
        package = runtime.packages.get("pkg_gameplay_v3")
        session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
        original = next(b.text for b in package.story_day(1).night_blocks if b.block_id == "d01_night")
        runtime.story_flow.append_night(session, package)
        night = next(i for i in session.narrative_feed if i.block_id == "d01_night")
        assert night.story_day == 1
        assert "天蒙蒙亮" not in night.text
        session.game_state = replace(session.game_state, story_day=2)
        runtime.story_flow.enter_current_day(session, package)
        dawn = next(i for i in session.narrative_feed if i.block_id == "d02_arrival_dawn")
        morning = next(i for i in session.narrative_feed if i.block_id == "d02_morning_call")
        assert dawn.story_day == 2
        assert dawn.cursor < morning.cursor
        assert night.text + dawn.text == original
        runtime.story_flow.enter_current_day(session, package)
        assert sum(i.block_id == "d02_arrival_dawn" for i in session.narrative_feed) == 1
    finally:
        client.close()
