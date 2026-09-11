"""Memory API transactions and stubbed selection transport, not live semantic accuracy."""
from dataclasses import replace
import json
from unittest.mock import patch

import pytest

from tests import test_story_review_round1 as fixtures
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import RoleLLMUnavailableError
from serious_game_backend.domain.llm import GovernanceLLMContext, GovernanceLLMResult
from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
from serious_game_backend.infrastructure.repositories.memory import InMemoryLLMCallAuditRepository


ARCHIVE = "archive_tan_case_index"


def start_visit(npc="npc_tan_laoliu", action_kind="household_visit", archive_id=ARCHIVE):
    harness = fixtures.StoryReviewRound1Tests()
    runtime, client, sid, headers = harness.build_api("archive-delivery")
    session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    session.game_state = replace(session.game_state, story_day=35, action_points=8)
    session.pending_decision = None
    session.pending_decision_queue.clear()
    session.known_npc_ids.add(npc)
    session.encountered_npc_ids.add(npc)
    session.archive_records.pop(archive_id, None)
    runtime.sessions.save(session, expected_version=session.state_version)
    base = f"/api/game/session/{sid}"
    descriptors = client.get(base + "/opportunities", headers=headers).json()["person_actions"]
    descriptor = next(d for d in descriptors if d["npc_id"] == npc and d["action_id"] == action_kind)
    response = client.post(base + "/governance/actions", headers=headers, json={
        "state_version": session.state_version, "action_kind": action_kind,
        "variant_id": descriptor["variant_id"], "location_id": descriptor["legal_location_ids"][0],
        "target_ids": [npc], "topic": "了解旧案年份与项目名"})
    assert response.status_code == 201, response.text
    aid = response.json()["action"]["action_instance_id"]
    return runtime, client, sid, headers, aid, base


def send_turn(game, text, reply, decision="none", fail=False):
    runtime, client, sid, headers, aid, base = game
    service = runtime.gameplay_governance
    governance = service._gateway.run_governance_task
    role = service._npc_turns._gateway.run_turn
    seen = []
    def task(context):
        if context.task == "confirm_archive_delivery":
            seen.append(context)
            if fail:
                raise RoleLLMUnavailableError("stub confirmation unavailable")
            return GovernanceLLMResult(task=context.task, data={"decision": decision}, model_id="test-stub")
        return governance(context)
    def npc_turn(context):
        return replace(role(context), dialogue=reply, input_relevance="relevant")
    session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    with patch.object(service._gateway, "run_governance_task", side_effect=task), patch.object(
        service._npc_turns._gateway, "run_turn", side_effect=npc_turn
    ):
        response = client.post(base + f"/governance/actions/{aid}/turn", headers=headers,
            json={"state_version": session.state_version, "player_text": text})
    return response, seen


@pytest.mark.parametrize("text,reply", [
    ("我不是来索要旧案年份材料的。", "那我们只聊聊近况。"),
    ("只讨论旧案年份，不拿材料。", "可以，先谈问题。"),
    ("请给我旧案年份和项目名索引。", "这份材料我现在不能给你。"),
    ("请给我旧案年份和项目名索引。", "等你把程序理清楚以后，我再给你。"),
])
def test_negative_discussion_refusal_or_future_does_not_acquire(text, reply):
    game = start_visit()
    response, seen = send_turn(game, text, reply)
    assert response.status_code == 200, response.text
    assert len(seen) == 1
    assert seen[0].payload["player_text"] == text
    assert seen[0].payload["npc_reply"] == reply
    runtime, _, sid, headers, aid, _ = game
    session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert ARCHIVE not in session.archive_records
    assert not any(item["kind"] == "archive_delivery" for item in session.governance_actions[aid].hard_outcomes)


def test_confirmed_delivery_acquires_once_and_records_npc_event():
    game = start_visit()
    response, seen = send_turn(game, "请给我旧案年份和项目名索引。", "我现在就把这份索引交给你。", "deliver")
    assert response.status_code == 200, response.text
    assert seen[0].actor_id == "npc_tan_laoliu"
    runtime, _, sid, headers, aid, _ = game
    first = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert first.archive_records[ARCHIVE].source_id == aid
    events = [e for e in first.governance_actions[aid].hard_outcomes if e["kind"] == "archive_delivery"]
    assert len(events) == 1 and events[0]["npc_id"] == "npc_tan_laoliu"
    response, seen = send_turn(game, "再给我旧案年份索引。", "刚才已经给你了。", "deliver")
    assert response.status_code == 200, response.text
    assert not seen
    second = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert second.archive_records[ARCHIVE] == first.archive_records[ARCHIVE]
    assert [e for e in second.governance_actions[aid].hard_outcomes if e["kind"] == "archive_delivery"] == events


def test_wrong_npc_cannot_deliver_tan_archive_even_with_delivery_decision():
    game = start_visit("npc_zhou_dashan")
    response, seen = send_turn(game, "请给我旧案年份和项目名索引。", "我现在把材料交给你。", "deliver")
    assert response.status_code == 200, response.text
    assert not seen
    runtime, _, sid, headers, _, _ = game
    assert ARCHIVE not in runtime.sessions.get_owned(sid, headers["X-Account-ID"]).archive_records


@pytest.mark.parametrize("npc,kind,archive_id,player_text", [
    ("npc_feng_jingzhi", "cadre_interview", "archive_finance_2m_ledger", "请现在给我200万元专账复制件。"),
    ("npc_ke_qinian", "cadre_interview", "archive_formal_eia_approval", "请现在给我环评批复副本。"),
    ("npc_zhou_kuiyuan", "household_visit", "archive_1983_grave_index", "请现在给我1983年迁坟先例索引。"),
    ("npc_tan_laoliu", "household_visit", ARCHIVE, "请现在给我旧案年份和项目名索引。"),
])
def test_each_archive_path_can_deliver_in_its_legal_api_conversation(npc, kind, archive_id, player_text):
    game = start_visit(npc, kind, archive_id)
    response, seen = send_turn(game, player_text, "我同意，现在就把你要的这份材料交给你。", "deliver")
    assert response.status_code == 200, response.text
    assert len(seen) == 1 and seen[0].actor_id == npc
    assert seen[0].payload["archive_id"] == archive_id
    runtime, _, sid, headers, aid, _ = game
    session = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert session.archive_records[archive_id].source_id == aid
    assert session.archive_records[archive_id].acquired_via == kind
    assert session.archive_records[archive_id].related_npc_ids == (npc,)
    assert len([e for e in session.governance_actions[aid].hard_outcomes
                if e["kind"] == "archive_delivery" and e["id"] == archive_id]) == 1


def test_failed_delivery_confirmation_leaves_no_business_changes():
    game = start_visit()
    runtime, _, sid, headers, aid, _ = game
    before = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    response, seen = send_turn(game, "请给我旧案年份和项目名索引。", "我现在把索引交给你。", fail=True)
    assert response.status_code >= 400, response.text
    assert len(seen) == 1
    after = runtime.sessions.get_owned(sid, headers["X-Account-ID"])
    assert after.archive_records == before.archive_records
    assert after.governance_actions[aid] == before.governance_actions[aid]
    assert after.game_state == before.game_state
    assert after.flags == before.flags
    assert after.processing_action_id is None


@pytest.mark.parametrize("decision", ["none", "deliver"])
def test_production_delivery_task_uses_bounded_selection_with_both_utterances(decision):
    prompts = []
    def transport(_url, _key, body, _timeout):
        prompts.append("\n".join(str(m["content"]) for m in body["messages"]))
        return {"choices": [{"message": {"content": json.dumps({"choice_id": decision})}}], "usage": {}}
    gateway = OpenAICompatibleRoleLLMGateway(Settings(environment="test", role_llm_provider="openai_compatible"),
        "test-key", InMemoryLLMCallAuditRepository(), transport=transport)
    with patch.object(gateway, "select", wraps=gateway.select) as select, patch.object(
        gateway, "express", side_effect=AssertionError("delivery confirmation must not express another decision")
    ):
        result = gateway.run_governance_task(GovernanceLLMContext(
            session_id="delivery-test", account_id="delivery-test", operation_id="delivery-test", story_day=35,
            task="confirm_archive_delivery", actor_id="npc_tan_laoliu", actor_name="谭老六", actor_profile="旧案当事人",
            payload={"archive_id": ARCHIVE, "archive_title": "旧案索引", "player_text": "请给我旧案年份索引。",
                     "npc_reply": "我现在把索引交给你。"}))
    assert [option.choice_id for option in select.call_args.args[0].options] == ["none", "deliver"]
    assert result.data == {"decision": decision}
    assert len(prompts) == 1
    assert "请给我旧案年份索引。" in prompts[0] and "我现在把索引交给你。" in prompts[0]
    assert "未来承诺" in prompts[0] and "不得执行" in prompts[0]
    assert "旧案索引" in prompts[0]
