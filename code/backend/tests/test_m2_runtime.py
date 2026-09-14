from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.story_reading import read_available_story
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class M2RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v2",
            repository="memory",
            role_llm_provider="none",
        )
        self.container = build_container(settings)
        self.client = TestClient(create_app(settings, container=self.container))
        self.headers = {"X-Account-ID": "acct_m2"}
        created = self.client.post(
            "/api/game/session",
            json={
                "client_request_id": "m2-new-game-0001",
                "origin_id": "technical",
            },
            headers=self.headers,
        )
        self.assertEqual(201, created.status_code)
        self.session_id = created.json()["session_id"]

    def action(self, payload: dict) -> dict:
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def end_day(self, version: int, key: str) -> dict:
        current = self.client.get(f"/api/game/session/{self.session_id}/view", headers=self.headers).json()
        self.assertEqual(version, current["state"]["state_version"])
        read = read_available_story(self.client, self.session_id, self.headers, key)
        response = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            json={"client_action_id": key, "state_version": read["state_version"]},
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def drain_decisions(self, result: dict, prefix: str) -> dict:
        index = 0
        pending = result["visible_state"].get("pending_decision")
        while pending is not None:
            parameters = {}
            if pending.get("input_kind") == "allocation":
                fields = pending["input_schema"]["fields"]
                parameters = {
                    "allocations": {
                        field: (150 if position == 0 else 0)
                        for position, field in enumerate(fields)
                    }
                }
            result = self.action({
                "input_mode": "decision",
                "client_action_id": f"{prefix}-decision-{index:03d}",
                "state_version": result["state_version"],
                "decision_id": pending["decision_id"],
                "option_id": next(
                    item["option_id"] for item in pending["options"]
                    if item.get("available", True)
                ),
                "parameters": parameters,
            })
            index += 1
            pending = result["visible_state"].get("pending_decision")
        return result

    def reach_d3(self) -> dict:
        first = self.action({
            "input_mode": "decision",
            "client_action_id": "m2-d1-decision",
            "state_version": 1,
            "decision_id": "ev1_01_reception_bag",
            "option_id": "a_reject_on_site",
        })
        d2 = self.end_day(first["state_version"], "m2-end-d1")
        taskforce = self.action({
            "input_mode": "decision",
            "client_action_id": "m2-d2-decision",
            "state_version": d2["state_version"],
            "decision_id": "dp1_01_taskforce_faction_map",
            "option_id": "c_public_rules_covert_check",
        })
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "m2-d2-start",
            "state_version": taskforce["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        conversation_id = started["conversation"]["conversation_id"]
        talk = self.action({
            "input_mode": "free_text",
            "client_action_id": "m2-d2-talk",
            "state_version": started["state_version"],
            "conversation_id": conversation_id,
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
            "player_text": "我想先听您说真话。",
        })
        closed = self.action({
            "input_mode": "conversation_end",
            "client_action_id": "m2-d2-close",
            "state_version": talk["state_version"],
            "conversation_id": conversation_id,
        })
        return self.end_day(closed["state_version"], "m2-end-d2")

    def test_full_story_clock_reaches_d90_and_builds_review(self) -> None:
        result = self.reach_d3()
        self.assertEqual(3, result["visible_state"]["story"]["day"])
        stops = []
        for index in range(100):
            if result["visible_state"]["status"] == "ended":
                break
            result = self.drain_decisions(result, f"m2-stop-{index:02d}")
            result = self.end_day(
                result["state_version"], f"m2-auto-end-{index:02d}"
            )
            stops.append(result["visible_state"]["story"]["day"])
        self.assertEqual(list(range(4, 91)), stops)
        self.assertEqual("ended", result["visible_state"]["status"])
        self.assertEqual(0, result["visible_state"]["ledger"]["days_left"])
        self.assertIsNotNone(result["ending"])

        review = self.client.get(
            f"/api/game/session/{self.session_id}/review", headers=self.headers
        )
        self.assertEqual(200, review.status_code)
        document = review.json()
        self.assertEqual(89, len(document["night_timeline"]))
        self.assertTrue(all(
            0 <= len(item.get("morning_card", [])) <= 3
            for item in document["night_timeline"]
        ))
        event_ids = {item["event_id"] for item in document["visible_events"]}
        self.assertTrue({
            "event_d31_municipal_inspection_arrival",
            "event_d45_municipal_inspection_departure",
            "event_d59_environmental_reception_arrival",
            "event_d90_final_acceptance",
        }.issubset(event_ids))
        self.assertEqual(result["ending"], document["ending"])
        self.assertEqual(76, len(document["decision_timeline"]))
        allocation = next(
            item for item in document["decision_timeline"]
            if item["decision_id"] == "dp2_10"
        )
        self.assertEqual(150, sum(allocation["parameters"].values()))
        feed = self.client.get(
            f"/api/game/session/{self.session_id}/feed?after=0",
            headers=self.headers,
        )
        self.assertEqual(200, feed.status_code, feed.text)
        feed_items = feed.json()["items"]
        content_ids = [
            item["content_instance_id"]
            for item in feed_items
            if item.get("content_instance_id")
        ]
        self.assertEqual(len(content_ids), len(set(content_ids)))
        self.assertFalse(
            {
                item["text"] for item in feed_items if item["kind"] == "night"
            }
            & {
                item["text"]
                for item in feed_items
                if item["kind"] == "morning_card"
            }
        )
        for marker in (
            "开启旗标", "关闭旗标", "本节点", "状态量", "结局轴",
            "代码照此算", "行动点重置", "轴 T", "flag_",
        ):
            self.assertNotIn(marker, feed.text)

    def test_map_and_complete_package_validation_are_player_safe(self) -> None:
        result = self.reach_d3()
        map_response = self.client.get(
            f"/api/game/session/{self.session_id}/map", headers=self.headers
        )
        self.assertEqual(200, map_response.status_code)
        locations = {
            item["location_id"]: item for item in map_response.json()["locations"]
        }
        # Pending decisions pause ordinary actions; map entries remain visible
        # for context but are no longer executable until the decision is read.
        self.assertEqual("known", locations["loc_liulin_village"]["visual_state"])
        self.assertNotIn("trust_score", map_response.text)
        self.assertNotIn("opportunity_ids", map_response.text)
        for suffix in ("map", "review"):
            forbidden = self.client.get(
                f"/api/game/session/{self.session_id}/{suffix}",
                headers={"X-Account-ID": "acct_other"},
            )
            self.assertEqual(404, forbidden.status_code)

        validation = self.client.get(
            "/api/game/package/validation", headers=self.headers
        )
        self.assertEqual(200, validation.status_code)
        report = validation.json()
        self.assertTrue(report["valid"])
        self.assertEqual(90, report["counts"]["story_days"])
        self.assertEqual(62, report["counts"]["decision_catalog"])
        self.assertEqual(14, report["counts"]["event_catalog"])
        self.assertEqual(24, report["counts"]["main_endings"])
        self.assertEqual(95, report["counts"]["sub_endings"])
        self.assertEqual(29, report["counts"]["npc_role_profiles"])
        self.assertEqual(18, report["counts"]["facts_and_clues"])
        self.assertEqual(32, report["counts"]["interaction_opportunities"])
        self.assertEqual(3, report["gameplay_schema_version"])
        self.assertEqual(31, report["counts"]["resource_action_definitions"])
        self.assertEqual(36, report["counts"]["households"])
        self.assertEqual(122, report["counts"]["household_registered_population"])
        self.assertEqual(122, report["counts"]["household_resettlement_population"])
        self.assertEqual(5, report["counts"]["sorting_decisions"])
        self.assertEqual(1, report["counts"]["allocation_decisions"])
        self.assertEqual(81, report["counts"]["runtime_decisions"])
        self.assertEqual(29, report["counts"]["source_night_blocks"])
        self.assertEqual(9, report["counts"]["conditional_night_rules"])
        locked_package = FileScriptPackageLoader().load(
            BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v2"
        )
        self.assertEqual(locked_package.source_sha256, report["source_sha256"])
        self.assertEqual(3, result["visible_state"]["story"]["day"])


if __name__ == "__main__":
    unittest.main()
