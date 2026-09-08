from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.config import Settings
from serious_game_backend.domain.conversation import ForcedGroupConversation
from serious_game_backend.domain.llm import NightAgentResult
from tests.test_doubles import build_test_container


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _runtime(account_id: str):
    settings = Settings(
        environment="test",
        content_root=BACKEND_ROOT / "content" / "packages",
        default_package_id="pkg_gameplay_v3",
        repository="memory",
        role_llm_provider="none",
    )
    runtime = build_test_container(settings)
    client = TestClient(create_app(settings, runtime))
    headers = {"X-Account-ID": account_id}
    response = client.post(
        "/api/game/session",
        headers=headers,
        json={
            "client_request_id": f"{account_id}-session-0001",
            "package_id": "pkg_gameplay_v3",
            "origin_id": "technical",
        },
    )
    assert response.status_code == 201, response.text
    return runtime, client, headers, response.json()


def test_pending_decision_allows_only_archive_inspection_and_keeps_decision() -> None:
    runtime, client, headers, state = _runtime("acct-pending-inspect")
    session_id = state["session_id"]

    view = client.get(f"/api/game/session/{session_id}/view", headers=headers)
    assert view.status_code == 200, view.text
    assert view.json()["commands"]["can_act"] is False
    assert view.json()["commands"]["can_inspect_archives"] is True

    actions = client.get(f"/api/game/session/{session_id}/actions", headers=headers)
    assert actions.status_code == 200, actions.text
    inspect = next(
        item for item in actions.json()["actions"]
        if item["action_id"] == "inspect_archives"
    )
    assert inspect["available"] is True
    variant = next(
        item for item in inspect["variants"]
        if item["variant_id"] == "consult_county_archives"
    )
    archive_id = variant["target_choices"][0]["target_id"]

    map_view = client.get(f"/api/game/session/{session_id}/map", headers=headers)
    assert map_view.status_code == 200, map_view.text
    county = next(
        item for item in map_view.json()["locations"]
        if item["location_id"] == "loc_county_government"
    )
    archive_card = next(
        item for item in county["entry_cards"]
        if item["action_id"] == "inspect_archives"
    )
    assert archive_card["available"] is True

    before_points = state["ledger"]["action_points"]["remaining"]
    read = client.post(
        f"/api/game/session/{session_id}/governance/actions",
        headers=headers,
        json={
            "state_version": state["state_version"],
            "action_kind": "inspect_archives",
            "variant_id": "consult_county_archives",
            "location_id": "loc_county_government",
            "archive_ids": [archive_id],
        },
    )
    assert read.status_code == 201, read.text
    payload = read.json()
    assert payload["action"]["status"] == "completed"
    assert payload["read_status"] == "read"
    assert payload["visible_state"]["pending_decision"]["decision_id"] == (
        state["pending_decision"]["decision_id"]
    )
    assert payload["visible_state"]["ledger"]["action_points"]["remaining"] == (
        before_points - 1
    )
    stored = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert stored is not None
    assert stored.pending_decision is not None
    assert stored.archive_records[archive_id].read_at_days == [1]

    blocked = client.post(
        f"/api/game/session/{session_id}/governance/actions",
        headers=headers,
        json={
            "state_version": payload["state_version"],
            "action_kind": "cadre_interview",
            "variant_id": "interview_cadre",
            "location_id": "loc_county_government",
            "target_ids": ["npc_zhao_jianguo"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert "必须先处理当前决策" in blocked.text

    quote = client.post(
        f"/api/game/session/{session_id}/actions/quote",
        headers=headers,
        json={
            "state_version": payload["state_version"],
            "action_id": "field_visit",
            "target_ids": ["loc_liulin_village"],
        },
    )
    assert quote.status_code == 400, quote.text


def test_resolved_group_conversation_allows_unlimited_followup_without_state_transition() -> None:
    runtime, client, headers, state = _runtime("acct-resolved-followup")
    session_id = state["session_id"]
    session = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert session is not None
    session.pending_decision = None
    session.pending_decision_queue.clear()
    session.game_state = replace(session.game_state, action_points=0)
    session.active_group_conversation = ForcedGroupConversation(
        conversation_id="group-resolved-followup",
        conversation_type="cadre_meeting",
        initiator_npc_id="npc_zhao_jianguo",
        participant_ids=("npc_zhao_jianguo", "npc_sun_qiang"),
        agenda="核对首阶段签约落差与后续核验安排",
        demands=("说明核验安排",),
        urgency="high",
        story_day=11,
        # Compatibility fixture: an older snapshot marked the resolved state
        # in status while still carrying the default phase value.
        status="resolved",
        phase="active",
        closure_summary="在场人物暂时停止追问；承诺仍待事实核验。",
    )
    for participant in session.active_group_conversation.participant_states.values():
        participant.update(status="settled", public_summary="暂时接受，仍在旁听")
    runtime.sessions.save(session, expected_version=session.state_version)

    delegate = runtime.group_conversations._gateway
    seen_contexts = []

    class FollowupGateway:
        def __getattr__(self, name):
            return getattr(delegate, name)

        def run_night_turn(self, context):
            seen_contexts.append(context)
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id="test-followup-model",
                dialogue=f"{context.npc_name}补充回应了这句会后交流。",
                rationale="符合人物身份的会后补充回应",
                dialogue_act="close",  # Must be ignored in follow-up mode.
                topic_settled=True,
                memory_candidate="玩家补充说明了一个尚待核验的情况。",
            )

    runtime.group_conversations._gateway = FollowupGateway()
    before = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert before is not None and before.active_group_conversation is not None
    states_before = before.active_group_conversation.participant_states.copy()
    flags_before = set(before.flags)
    points_before = before.game_state.action_points
    transcript_before = len(before.active_group_conversation.transcript)

    first = client.post(
        f"/api/game/session/{session_id}/group-conversation/turn",
        headers=headers,
        json={
            "client_action_id": "resolved-followup-turn-0001",
            "state_version": before.state_version,
            "player_text": "今天辛苦了，最近村里的天气还好吧？",
        },
    )
    assert first.status_code == 200, first.text
    first_payload = first.json()
    assert first_payload["resolved"] is True
    assert first_payload["completed"] is False
    assert first_payload["dialogue_mode"] == "followup"
    assert all(item["dialogue_mode"] == "followup" for item in first_payload["turn_dialogues"])

    after_first = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert after_first is not None and after_first.active_group_conversation is not None
    assert after_first.active_group_conversation.phase == "resolved"
    assert after_first.active_group_conversation.participant_states == states_before
    assert after_first.flags == flags_before
    assert after_first.game_state.action_points == points_before
    assert len(after_first.active_group_conversation.transcript) == transcript_before + 3
    assert all(context.phase == "resolved_group_followup" for context in seen_contexts)

    second = client.post(
        f"/api/game/session/{session_id}/group-conversation/turn",
        headers=headers,
        json={
            "client_action_id": "resolved-followup-turn-0002",
            "state_version": first_payload["state_version"],
            "player_text": "那就早点休息，明天再见。",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["dialogue_mode"] == "followup"

    duplicate = client.post(
        f"/api/game/session/{session_id}/group-conversation/turn",
        headers=headers,
        json={
            "client_action_id": "resolved-followup-turn-0002",
            "state_version": second.json()["state_version"] - 1,
            "player_text": "那就早点休息，明天再见。",
        },
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == second.json()

    final = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert final is not None and final.active_group_conversation is not None
    assert final.active_group_conversation.phase == "resolved"
    assert final.game_state.action_points == points_before
    assert final.flags == flags_before

    finish = client.post(
        f"/api/game/session/{session_id}/group-conversation/finish",
        headers=headers,
        json={
            "client_action_id": "resolved-followup-finish",
            "state_version": final.state_version,
        },
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["completed"] is True
    stored = runtime.sessions.get_owned(session_id, headers["X-Account-ID"])
    assert stored is not None
    assert stored.active_group_conversation is None
    assert stored.completed_group_conversations[-1]["transcript"][-1]["dialogue_mode"] == "followup"
