"""Deterministic player-path audit for the published gameplay package.

This is intentionally an API-level runner: it only uses commands available to
the player and stops with diagnostics if the visible flow cannot advance.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from tests.test_doubles import build_test_container as build_container  # noqa: E402
ACCOUNT_ID = "acct_player_experience_audit"
HEADERS = {"X-Account-ID": ACCOUNT_ID}
PREFERRED_WORDS = (
    "公开", "核查", "依法", "独立", "第三方", "复检", "暂停", "备案", "审计",
)


def choose_option(pending: dict) -> str:
    options = [
        item for item in pending["options"]
        if item.get("available", True)
    ]
    for word in PREFERRED_WORDS:
        for option in options:
            if word in option["text"]:
                return option["option_id"]
    return options[0]["option_id"]


def run(max_steps: int = 3000) -> dict:
    settings = Settings(
        environment="test",
        content_root=BACKEND_ROOT / "content" / "packages",
        repository="memory",
        role_llm_provider="none",
    )
    runtime = build_container(settings)
    client = TestClient(create_app(settings, runtime))
    started = client.post(
        "/api/game/session",
        headers=HEADERS,
        json={"client_request_id": "player-experience-audit-0001"},
    )
    started.raise_for_status()
    state = started.json()
    session_id = state["session_id"]
    sequence = 0
    decisions: list[dict] = []
    conversations: list[dict] = []
    groups: list[dict] = []
    day_summaries: list[dict] = []
    blockers: list[dict] = []
    visited_days: Counter[int] = Counter()
    opportunity_attempts: Counter[str] = Counter()
    last_reported_day = 0

    def action(payload: dict) -> dict:
        response = client.post(
            f"/api/game/session/{session_id}/action",
            headers=HEADERS,
            json=payload,
        )
        if response.status_code != 200:
            raise RuntimeError(f"action {response.status_code}: {response.text}")
        return response.json()

    for _step in range(max_steps):
        day = int(state["story"]["day"])
        if day != last_reported_day:
            print(f"[player-audit] entered D{day}", flush=True)
            last_reported_day = day
        visited_days[day] += 1
        if state["status"] == "ended" or day >= 90:
            break
        if state["pending_decision"] is not None:
            pending = state["pending_decision"]
            option_id = choose_option(pending)
            parameters = {}
            ordered_option_ids: list[str] = []
            if pending.get("input_kind") == "allocation":
                fields = list(pending["input_schema"]["fields"])
                total = int(pending["input_schema"]["total"])
                base, remainder = divmod(total, len(fields))
                parameters = {
                    "allocations": {
                        field: base + (1 if index < remainder else 0)
                        for index, field in enumerate(fields)
                    }
                }
            elif pending.get("input_kind") == "sorting":
                ordered_option_ids = list(
                    pending["input_schema"]["items"]
                )
            sequence += 1
            result = action({
                "input_mode": "decision",
                "client_action_id": f"audit-decision-{sequence:04d}",
                "state_version": state["state_version"],
                "decision_id": pending["decision_id"],
                "option_id": option_id,
                "parameters": parameters,
                "ordered_option_ids": ordered_option_ids,
            })
            decisions.append({
                "day": day,
                "decision_id": pending["decision_id"],
                "option_id": option_id,
            })
            state = result["visible_state"]
            continue
        if state["active_group_conversation"] is not None:
            group = state["active_group_conversation"]
            response = client.post(
                f"/api/game/session/{session_id}/group-conversation/turn",
                headers=HEADERS,
                json={
                    "state_version": state["state_version"],
                    "player_text": (
                        "请各方把事实依据、资源需求和不可接受的底线逐项说清，"
                        "我会把可兑现事项写入正式记录。"
                    ),
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"group {response.status_code}: {response.text}"
                )
            groups.append({
                "day": day,
                "conversation_id": group["conversation_id"],
                "participants": group["participant_ids"],
            })
            state = response.json()["visible_state"]
            continue
        if state["active_conversation"] is not None:
            current = state["active_conversation"]
            sequence += 1
            if int(current["turn_count"]) >= 3:
                result = action({
                    "input_mode": "conversation_end",
                    "client_action_id": f"audit-leave-{sequence:04d}",
                    "state_version": state["state_version"],
                    "conversation_id": current["conversation_id"],
                })
                conversations.append({
                    "day": day,
                    "opportunity_id": current["opportunity_id"],
                    "phase": "leave",
                    "status": result["conversation"]["status"],
                })
                state = result["visible_state"]
                continue
            result = action({
                "input_mode": "free_text",
                "client_action_id": f"audit-talk-{sequence:04d}",
                "state_version": state["state_version"],
                "conversation_id": current["conversation_id"],
                "opportunity_id": current["opportunity_id"],
                "target_npc_id": current["npc_id"],
                "player_text": (
                    "请只谈柳林村搬迁：你最担心什么，需要哪份材料或哪项"
                    "可核验资源才愿意继续推进？"
                ),
            })
            conversations.append({
                "day": day,
                "opportunity_id": current["opportunity_id"],
                "phase": "turn",
                "status": result["conversation"]["status"],
            })
            state = result["visible_state"]
            continue

        view = client.get(
            f"/api/game/session/{session_id}/view", headers=HEADERS
        ).json()
        if view["commands"]["can_end_day"]:
            sequence += 1
            response = client.post(
                f"/api/game/session/{session_id}/end-day",
                headers=HEADERS,
                json={
                    "client_action_id": f"audit-end-day-{sequence:04d}",
                    "state_version": state["state_version"],
                },
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"end-day {response.status_code}: {response.text}"
                )
            next_state = response.json()["visible_state"]
            day_summaries.append({
                "day": day,
                "next_day": next_state["story"]["day"],
                "fatigue": next_state["ledger"]["fatigue"]["label"],
                "action_points_remaining": (
                    state["ledger"]["action_points"]["remaining"]
                ),
                "signed": next_state["ledger"]["signed_households"]["signed"],
                "budget_remaining": next_state["ledger"]["budget"]["remaining"],
            })
            state = next_state
            continue

        available = client.get(
            f"/api/game/session/{session_id}/opportunities",
            headers=HEADERS,
        ).json()["opportunities"]
        unattempted = [
            item for item in available
            if opportunity_attempts[item["opportunity_id"]] == 0
        ]
        if unattempted:
            opportunity = unattempted[0]
            opportunity_attempts[opportunity["opportunity_id"]] += 1
            sequence += 1
            result = action({
                "input_mode": "conversation_start",
                "client_action_id": f"audit-start-talk-{sequence:04d}",
                "state_version": state["state_version"],
                "opportunity_id": opportunity["opportunity_id"],
                "target_npc_id": opportunity["npc_id"],
            })
            conversations.append({
                "day": day,
                "opportunity_id": opportunity["opportunity_id"],
                "phase": "start",
                "status": result["conversation"]["status"],
            })
            state = result["visible_state"]
            continue

        session = runtime.sessions.get_owned(session_id, ACCOUNT_ID)
        package = runtime.packages.get(session.package_id)
        beat = package.story_day(day) if package is not None else None
        blockers.append({
            "day": day,
            "state_version": state["state_version"],
            "missing_end_day_flags": sorted(
                (beat.end_day_requires_flags - session.flags) if beat else ()
            ),
            "available_governance_actions": [
                item["action_id"]
                for item in client.get(
                    f"/api/game/session/{session_id}/actions",
                    headers=HEADERS,
                ).json()["actions"]
                if item["available"]
            ],
        })
        break
    else:
        blockers.append({"reason": "step_limit"})

    final_state = client.get(
        f"/api/game/session/{session_id}", headers=HEADERS
    ).json()
    return {
        "session_id": session_id,
        "final_day": final_state["story"]["day"],
        "status": final_state["status"],
        "decision_count": len(decisions),
        "conversation_starts": sum(
            item["phase"] == "start" for item in conversations
        ),
        "conversation_turns": sum(
            item["phase"] == "turn" for item in conversations
        ),
        "group_turns": len(groups),
        "signed_households": (
            final_state["ledger"]["signed_households"]["signed"]
        ),
        "budget_remaining": final_state["ledger"]["budget"]["remaining"],
        "fatigue": final_state["ledger"]["fatigue"]["label"],
        "decisions": decisions,
        "day_summaries": day_summaries,
        "blockers": blockers,
        "high_loop_days": {
            str(day): count for day, count in visited_days.items()
            if count >= 10
        },
    }


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(json.dumps(run(limit), ensure_ascii=False, indent=2))
