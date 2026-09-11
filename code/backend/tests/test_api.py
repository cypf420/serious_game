from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(settings)
        self.client = TestClient(create_app(settings, self.runtime))
        self.headers = {"X-Account-ID": "acct_api"}

    def _new_session(self) -> dict:
        response = self.client.post(
            "/api/game/session",
            json={
                "client_request_id": "api-new-game-0001",
                "origin_id": "technical",
            },
            headers=self.headers,
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_health_and_new_game(self) -> None:
        health = self.client.get("/health/live")
        self.assertEqual(200, health.status_code)
        self.assertEqual(
            "text-gameplay-v3",
            health.json()["terminal_protocol_version"],
        )
        result = self._new_session()
        self.assertEqual(1, result["state_version"])
        self.assertEqual(8, result["ledger"]["action_points"]["remaining"])
        self.assertEqual(
            "ev1_01_reception_bag",
            result["pending_decision"]["decision_id"],
        )
        self.assertEqual(4, len(result["pending_decision"]["options"]))
        self.assertEqual("mayor", result["story"]["origin"]["origin_id"])
        self.assertNotIn("env_clue", result)

        origins = self.client.get("/api/game/origins", headers=self.headers)
        self.assertEqual(200, origins.status_code, origins.text)
        self.assertFalse(origins.json()["selection_required"])
        self.assertEqual([], origins.json()["origins"])

        desk = self.client.get(
            f"/api/game/session/{result['session_id']}/desk", headers=self.headers
        )
        self.assertEqual(200, desk.status_code, desk.text)
        desk_body = desk.json()
        self.assertEqual(5, len(desk_body["dossiers"]))
        self.assertEqual(
            {
                "household_visit",
                "cadre_interview",
                "leadership_meeting",
                "inspect_archives",
            },
            {item["action_id"] for item in desk_body["tools"]},
        )
        budget = desk_body["compensation_policy"]["current_budget"]
        self.assertEqual(7800, budget["remaining"])
        self.assertEqual(8000, budget["base_authorized"])
        self.assertEqual(200, budget["precoord_suspense"])
        self.assertIn("已签发", desk_body["compensation_policy"]["status"])
        self.assertTrue(all("description" in item for item in desk_body["tools"]))

    def test_lists_all_account_sessions_in_recent_first_order(self) -> None:
        created = []
        for suffix in ("first", "second"):
            response = self.client.post(
                "/api/game/session",
                json={"client_request_id": f"api-session-list-{suffix}"},
                headers=self.headers,
            )
            self.assertEqual(201, response.status_code, response.text)
            created.append(response.json()["session_id"])

        response = self.client.get("/api/game/sessions", headers=self.headers)
        self.assertEqual(200, response.status_code, response.text)
        sessions = response.json()["sessions"]
        self.assertEqual(set(created), {item["session_id"] for item in sessions})
        self.assertEqual(created[-1], sessions[0]["session_id"])
        self.assertTrue(all(item["story_day"] == 1 for item in sessions))
        self.assertTrue(all(item["loadable"] is True for item in sessions))
        self.assertTrue(all(item["unavailable_reason"] is None for item in sessions))

    def test_content_mismatch_is_unavailable_not_review_only_across_read_contracts(self) -> None:
        created = self._new_session()
        session_id = created["session_id"]
        stored = self.runtime.sessions.get_owned(session_id, "acct_api")
        stored.package_content_hash = "sha256:old-content-no-longer-installed"
        self.runtime.sessions.save(stored, expected_version=stored.state_version)

        listed = self.client.get("/api/game/sessions", headers=self.headers)
        self.assertEqual(200, listed.status_code, listed.text)
        summary = next(
            item for item in listed.json()["sessions"]
            if item["session_id"] == session_id
        )
        self.assertFalse(summary["content_available"])
        self.assertFalse(summary["review_available"])
        self.assertFalse(summary["loadable"])
        self.assertEqual("content_unavailable", summary["mode"])
        self.assertTrue(summary["unavailable_reason"])

        expected_contract = {
            "mode": "content_unavailable",
            "content_available": False,
            "review_available": False,
            "loadable": False,
            "unavailable_reason": summary["unavailable_reason"],
        }
        for suffix in ("", "/view", "/review"):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    f"/api/game/session/{session_id}{suffix}", headers=self.headers
                )
                self.assertEqual(503, response.status_code, response.text)
                error = response.json()["error"]
                self.assertEqual("SESSION_CONTENT_UNAVAILABLE", error["code"])
                self.assertEqual(expected_contract, error["details"])
                self.assertNotIn("expected_hash", response.text)
                self.assertNotIn("actual_hash", response.text)

    def test_missing_locked_package_uses_the_same_unavailable_contract(self) -> None:
        created = self._new_session()
        session_id = created["session_id"]
        stored = self.runtime.sessions.get_owned(session_id, "acct_api")
        stored.package_id = "pkg_removed_from_runtime"
        self.runtime.sessions.save(stored, expected_version=stored.state_version)

        summary = self.client.get(
            "/api/game/sessions", headers=self.headers
        ).json()["sessions"][0]
        self.assertEqual("content_unavailable", summary["mode"])
        self.assertFalse(summary["content_available"])
        self.assertFalse(summary["review_available"])
        review = self.client.get(
            f"/api/game/session/{session_id}/review", headers=self.headers
        )
        self.assertEqual(503, review.status_code, review.text)
        self.assertEqual(
            {key: summary[key] for key in (
                "mode", "content_available", "review_available", "loadable",
                "unavailable_reason",
            )},
            review.json()["error"]["details"],
        )

    def test_llm_action_endpoint_runs_outside_event_loop(self) -> None:
        route = next(
            item for item in self.client.app.routes
            if getattr(item, "path", None) == "/api/game/session/{session_id}/action"
        )
        self.assertFalse(inspect.iscoroutinefunction(route.endpoint))

    def test_action_contract_and_ownership(self) -> None:
        session = self._new_session()
        session_id = session["session_id"]
        response = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-action-0001",
                "state_version": 1,
                "decision_id": "ev1_01_reception_bag",
                "option_id": "a_reject_on_site",
            },
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(2, response.json()["state_version"])
        self.assertIsNone(response.json()["visible_state"]["pending_decision"])
        self.assertEqual(
            8,
            response.json()["visible_state"]["ledger"]["action_points"]["remaining"],
        )

        other = self.client.get(
            f"/api/game/session/{session_id}", headers={"X-Account-ID": "acct_other"}
        )
        self.assertEqual(404, other.status_code)

    def test_manual_save_history_and_timeline_load(self) -> None:
        session = self._new_session()
        session_id = session["session_id"]

        initial = self.client.get(
            f"/api/game/session/{session_id}/manual-saves",
            headers=self.headers,
        )
        self.assertEqual(200, initial.status_code, initial.text)
        self.assertEqual(1, len(initial.json()["recent_snapshots"]))
        initial_timeline = initial.json()["timeline_id"]

        first_save = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            json={
                "client_action_id": "api-manual-save-slot-1",
                "state_version": 1,
                "slot_number": 1,
                "display_name": "开局",
                "overwrite": False,
            },
            headers=self.headers,
        )
        self.assertEqual(200, first_save.status_code, first_save.text)
        initial_snapshot_id = first_save.json()["snapshot_id"]
        replay = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            json={
                "client_action_id": "api-manual-save-slot-1",
                "state_version": 1,
                "slot_number": 1,
                "display_name": "开局",
                "overwrite": False,
            },
            headers=self.headers,
        )
        self.assertEqual(first_save.json(), replay.json())
        self.assertEqual(
            2,
            len(self.runtime.snapshots.list_history("acct_api", session_id)),
        )

        action = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-save-action-0001",
                "state_version": 1,
                "decision_id": "ev1_01_reception_bag",
                "option_id": "a_reject_on_site",
            },
            headers=self.headers,
        )
        self.assertEqual(200, action.status_code, action.text)
        self.assertEqual(
            3,
            len(self.runtime.snapshots.list_history("acct_api", session_id)),
        )

        conflict = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            json={
                "client_action_id": "api-manual-save-conflict",
                "state_version": 2,
                "slot_number": 1,
                "display_name": "行动后",
                "overwrite": False,
            },
            headers=self.headers,
        )
        self.assertEqual(409, conflict.status_code, conflict.text)

        overwritten = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            json={
                "client_action_id": "api-manual-save-overwrite",
                "state_version": 2,
                "slot_number": 1,
                "display_name": "行动后",
                "overwrite": True,
            },
            headers=self.headers,
        )
        self.assertEqual(200, overwritten.status_code, overwritten.text)
        self.assertNotEqual(initial_snapshot_id, overwritten.json()["snapshot_id"])
        self.assertIsNotNone(
            self.runtime.snapshots.get_owned(
                "acct_api", session_id, initial_snapshot_id
            )
        )

        unconfirmed = self.client.post(
            f"/api/game/session/{session_id}/load-snapshot",
            json={
                "client_action_id": "api-load-unconfirmed",
                "state_version": 2,
                "snapshot_id": initial_snapshot_id,
                "confirmed": False,
            },
            headers=self.headers,
        )
        self.assertEqual(422, unconfirmed.status_code, unconfirmed.text)

        loaded = self.client.post(
            f"/api/game/session/{session_id}/load-snapshot",
            json={
                "client_action_id": "api-load-snapshot-0001",
                "state_version": 2,
                "snapshot_id": initial_snapshot_id,
                "confirmed": True,
            },
            headers=self.headers,
        )
        self.assertEqual(200, loaded.status_code, loaded.text)
        self.assertEqual(3, loaded.json()["state_version"])
        self.assertNotEqual(initial_timeline, loaded.json()["timeline_id"])
        self.assertEqual(initial_snapshot_id, loaded.json()["loaded_from_snapshot_id"])
        self.assertEqual(
            5,
            len(self.runtime.snapshots.list_history("acct_api", session_id)),
        )

        stale = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-stale-after-load",
                "state_version": 2,
                "decision_id": "ev1_01_reception_bag",
                "option_id": "a_reject_on_site",
            },
            headers=self.headers,
        )
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual(
            5,
            len(self.runtime.snapshots.list_history("acct_api", session_id)),
        )

        loaded_replay = self.client.post(
            f"/api/game/session/{session_id}/load-snapshot",
            json={
                "client_action_id": "api-load-snapshot-0001",
                "state_version": 2,
                "snapshot_id": initial_snapshot_id,
                "confirmed": True,
            },
            headers=self.headers,
        )
        self.assertEqual(loaded.json(), loaded_replay.json())

        other = self.client.get(
            f"/api/game/session/{session_id}/manual-saves",
            headers={"X-Account-ID": "acct_other"},
        )
        self.assertEqual(404, other.status_code)

    def test_manual_save_owns_payload_and_rejects_same_version_semantic_drift(
        self,
    ) -> None:
        first = self._new_session()
        session_id = first["session_id"]
        automatic = self.runtime.snapshots.current_for_session(
            self.runtime.sessions.get_owned(session_id, "acct_api")
        )
        self.assertIsNotNone(automatic)

        saved = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            headers=self.headers,
            json={
                "client_action_id": "manual-owned-payload-0001",
                "state_version": 1,
                "slot_number": 1,
                "display_name": "独立手动存档",
                "overwrite": False,
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertNotEqual(automatic.snapshot_id, saved.json()["snapshot_id"])
        manual = self.runtime.snapshots.get_owned(
            "acct_api", session_id, saved.json()["snapshot_id"]
        )
        self.assertEqual("manual", manual.snapshot_type)
        self.assertEqual(automatic.snapshot_id, manual.parent_snapshot_id)

        drifted = self.runtime.sessions.get_owned(session_id, "acct_api")
        drifted.game_state = replace(
            drifted.game_state,
            action_points=drifted.game_state.action_points - 1,
        )
        self.runtime.sessions.save(drifted, expected_version=drifted.state_version)
        rejected = self.client.post(
            f"/api/game/session/{session_id}/manual-saves",
            headers=self.headers,
            json={
                "client_action_id": "manual-drift-rejected-0001",
                "state_version": 1,
                "slot_number": 2,
                "display_name": "不得保存混合状态",
                "overwrite": False,
            },
        )
        self.assertEqual(409, rejected.status_code, rejected.text)
        self.assertEqual("SNAPSHOT_STATE_MISMATCH", rejected.json()["error"]["code"])
        self.assertEqual(
            [1],
            [
                item[0].slot_number
                for item in self.runtime.snapshots.list_manual_slots(
                    "acct_api", session_id
                )
            ],
        )

    def test_free_text_stays_closed_until_opportunity_package_is_ready(self) -> None:
        session = self._new_session()
        response = self.client.post(
            f"/api/game/session/{session['session_id']}/action",
            json={
                "input_mode": "conversation_start",
                "client_action_id": "api-free-text-1",
                "state_version": 1,
                "opportunity_id": "opp_missing",
                "target_npc_id": "npc_zhou_dashan",
            },
            headers=self.headers,
        )
        self.assertEqual(409, response.status_code)
        self.assertEqual("DECISION_REQUIRED", response.json()["error"]["code"])

    def test_request_contract_rejects_unknown_fields(self) -> None:
        session = self._new_session()
        response = self.client.post(
            f"/api/game/session/{session['session_id']}/action",
            json={
                "input_mode": "tool",
                "client_action_id": "api-action-extra-1",
                "state_version": 1,
                "action_id": "home_visit",
                "opportunity_id": "opp_missing",
                "unexpected_hidden_delta": 99,
            },
            headers=self.headers,
        )
        self.assertEqual(422, response.status_code)

    def test_conversation_contract_rejects_mixed_mode_fields(self) -> None:
        session = self._new_session()
        response = self.client.post(
            f"/api/game/session/{session['session_id']}/action",
            json={
                "input_mode": "conversation_start",
                "client_action_id": "api-conversation-mixed-1",
                "state_version": 1,
                "opportunity_id": "opp_missing",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "不应在开始请求中出现",
            },
            headers=self.headers,
        )
        self.assertEqual(422, response.status_code)

    def test_tool_contract_requires_opportunity_id(self) -> None:
        session = self._new_session()
        response = self.client.post(
            f"/api/game/session/{session['session_id']}/action",
            json={
                "input_mode": "tool",
                "client_action_id": "api-tool-no-opportunity-1",
                "state_version": 1,
                "action_id": "home_visit",
            },
            headers=self.headers,
        )
        self.assertEqual(422, response.status_code)

    def test_operation_query_is_scoped_to_owned_session(self) -> None:
        session = self._new_session()
        session_id = session["session_id"]
        self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-operation-1",
                "state_version": 1,
                "decision_id": "ev1_01_reception_bag",
                "option_id": "c_return_next_day",
            },
            headers=self.headers,
        )
        own = self.client.get(
            f"/api/game/session/{session_id}/operations/api-operation-1",
            headers=self.headers,
        )
        self.assertEqual(200, own.status_code)
        other = self.client.get(
            f"/api/game/session/{session_id}/operations/api-operation-1",
            headers={"X-Account-ID": "acct_other"},
        )
        self.assertEqual(404, other.status_code)

    def test_m1_incremental_vertical_slice_reaches_d3(self) -> None:
        session = self._new_session()
        session_id = session["session_id"]

        opening = self.client.get(
            f"/api/game/session/{session_id}/view?after=0",
            headers=self.headers,
        )
        self.assertEqual(200, opening.status_code, opening.text)
        opening_body = opening.json()
        self.assertTrue(opening_body["commands"]["can_choose"])
        self.assertFalse(opening_body["commands"]["can_act"])
        self.assertFalse(opening_body["commands"]["can_end_day"])
        self.assertGreater(len(opening_body["feed"]["items"]), 0)
        opening_cursor = opening_body["feed"]["cursor"]

        action_catalog = self.client.get(
            f"/api/game/session/{session_id}/actions",
            headers=self.headers,
        )
        self.assertEqual(200, action_catalog.status_code, action_catalog.text)
        catalog_actions = action_catalog.json()["actions"]
        self.assertTrue(
            next(item for item in catalog_actions
                 if item["action_id"] == "inspect_archives")["available"]
        )
        self.assertTrue(all(
            not item["available"]
            for item in catalog_actions
            if item["action_id"] != "inspect_archives"
        ))
        self.assertTrue(all(
            item["unavailable_reason"] == "必须先处理当前决策"
            for item in catalog_actions
            if item["action_id"] != "inspect_archives"
        ))

        decision = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-d1-decision-1",
                "state_version": 1,
                "decision_id": "ev1_01_reception_bag",
                "option_id": "b_file_with_discipline",
            },
            headers=self.headers,
        )
        self.assertEqual(200, decision.status_code, decision.text)

        consequence = self.client.get(
            f"/api/game/session/{session_id}/feed?after={opening_cursor}",
            headers=self.headers,
        )
        self.assertEqual(200, consequence.status_code, consequence.text)
        # The retired generic followup is absent in both the saved editorial
        # baseline and current package; do not require filler to reappear.
        self.assertEqual(["consequence"], [
            item["kind"] for item in consequence.json()["items"]
        ])
        consequence_cursor = consequence.json()["cursor"]

        continued_d1 = self.client.post(
            f"/api/game/session/{session_id}/story/continue",
            json={"client_action_id": "api-d1-story", "state_version": decision.json()["state_version"]},
            headers=self.headers,
        )
        self.assertEqual(200, continued_d1.status_code, continued_d1.text)
        self.assertEqual(1, continued_d1.json()["visible_state"]["story"]["day"])
        ended = self.client.post(
            f"/api/game/session/{session_id}/end-day",
            json={
                "client_action_id": "api-d1-end-day-1",
                "state_version": continued_d1.json()["state_version"],
                "active_rest": False,
            },
            headers=self.headers,
        )
        self.assertEqual(200, ended.status_code, ended.text)
        self.assertEqual(2, ended.json()["visible_state"]["story"]["day"])

        day_two = self.client.get(
            f"/api/game/session/{session_id}/view?after={consequence_cursor}",
            headers=self.headers,
        )
        self.assertEqual(200, day_two.status_code, day_two.text)
        day_two_body = day_two.json()
        self.assertEqual(2, day_two_body["state"]["story"]["day"])
        self.assertFalse(day_two_body["commands"]["can_act"])
        self.assertFalse(day_two_body["commands"]["can_end_day"])
        self.assertTrue(day_two_body["commands"]["can_choose"])
        self.assertEqual(
            "dp1_01_taskforce_faction_map",
            day_two_body["state"]["pending_decision"]["decision_id"],
        )
        self.assertIn("night", [item["kind"] for item in day_two_body["feed"]["items"]])
        self.assertIn("morning", [item["kind"] for item in day_two_body["feed"]["items"]])
        night_texts = {
            item["text"]
            for item in day_two_body["feed"]["items"]
            if item["kind"] == "night"
        }
        morning_texts = {
            item["text"]
            for item in day_two_body["feed"]["items"]
            if item["kind"] == "morning_card"
        }
        self.assertFalse(night_texts & morning_texts)
        structured_items = [
            item
            for item in day_two_body["feed"]["items"]
            if item["kind"] in {"night", "morning_card", "narration", "dialogue"}
        ]
        self.assertTrue(
            all(item["content_instance_id"] for item in structured_items)
        )

        taskforce = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "decision",
                "client_action_id": "api-d2-taskforce-1",
                "state_version": ended.json()["state_version"],
                "decision_id": "dp1_01_taskforce_faction_map",
                "option_id": "c_public_rules_covert_check",
            },
            headers=self.headers,
        )
        self.assertEqual(200, taskforce.status_code, taskforce.text)

        opportunities = self.client.get(
            f"/api/game/session/{session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, opportunities.status_code, opportunities.text)
        self.assertIn(
            "opp_d02_wu_xiuying_first_talk",
            {
                item["opportunity_id"]
                for item in opportunities.json()["opportunities"]
            },
        )
        first_opportunity = next(
            item for item in opportunities.json()["opportunities"]
            if item["opportunity_id"] == "opp_d02_wu_xiuying_first_talk"
        )
        self.assertEqual("吴秀英", first_opportunity["npc_name"])
        self.assertEqual("村民代表，退休教师", first_opportunity["npc_title"])
        self.assertIn("退休教师", first_opportunity["npc_introduction"])
        self.assertEqual("入户走访", first_opportunity["action_name"])
        self.assertIn("剧情后续交谈", first_opportunity["conversation_context"])
        self.assertEqual(
            ["云溪县柳林村整体搬迁补偿安置方案"],
            [item["title"] for item in first_opportunity["related_materials"]],
        )
        knowledge = self.client.get(
            f"/api/game/session/{session_id}/knowledge", headers=self.headers
        ).json()
        wu_lead = next(
            item for item in knowledge["investigation_leads"]
            if item["fact_id"] == "fact_wu_independent_voice"
        )
        self.assertEqual(
            {
                "fact_id": "fact_wu_independent_voice",
                "route_type": "conversation",
                "source_id": "opp_d02_wu_xiuying_first_talk",
            },
            {
                key: wu_lead["methods"][0][key]
                for key in ("fact_id", "route_type", "source_id")
            },
        )

        started = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "conversation_start",
                "client_action_id": "api-d2-wu-start-1",
                "state_version": taskforce.json()["state_version"],
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
            },
            headers=self.headers,
        )
        self.assertEqual(200, started.status_code, started.text)
        self.assertEqual("active", started.json()["conversation"]["status"])
        self.assertIn("菜", started.json()["narrative"])
        conversation_id = started.json()["conversation"]["conversation_id"]
        self.assertEqual(
            8,
            started.json()["visible_state"]["ledger"]["action_points"]["remaining"],
        )

        talk = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "free_text",
                "client_action_id": "api-d2-wu-talk-1",
                "state_version": started.json()["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "吴老师，我想先听听村里人真正担心什么。",
            },
            headers=self.headers,
        )
        self.assertEqual(200, talk.status_code, talk.text)
        self.assertEqual(started.json()["state_version"] + 1, talk.json()["state_version"])
        self.assertIn("谁的话在谁面前好使", talk.json()["npc_reply"]["text"])
        self.assertEqual("active", talk.json()["conversation"]["status"])
        self.assertEqual(
            7,
            talk.json()["visible_state"]["ledger"]["action_points"]["remaining"],
        )
        active_opportunity = self.client.get(
            f"/api/game/session/{session_id}/opportunities", headers=self.headers
        ).json()["opportunities"][0]
        self.assertEqual(
            ["柳林村宗族权力图", "云溪县柳林村整体搬迁补偿安置方案"],
            [item["title"] for item in active_opportunity["related_materials"]],
        )

        second_talk = self.client.post(
            f"/api/game/session/{session_id}/action",
            json={
                "input_mode": "free_text",
                "client_action_id": "api-d2-wu-talk-2",
                "state_version": talk.json()["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "你必须配合，马上签。",
            },
            headers=self.headers,
        )
        self.assertEqual(200, second_talk.status_code, second_talk.text)
        self.assertEqual("ended", second_talk.json()["conversation"]["status"])
        self.assertEqual("npc", second_talk.json()["conversation"]["ended_by"])
        self.assertIn("提起菜篮", second_talk.json()["conversation"]["exit_narrative"])
        self.assertEqual(
            7,
            second_talk.json()["visible_state"]["ledger"]["action_points"]["remaining"],
        )
        self.assertIn(
            {
                "fact_id": "fact_wu_independent_voice",
                "route_type": "conversation",
                "source_id": "opp_d02_wu_xiuying_first_talk",
            },
            second_talk.json()["fact_acquisition_bindings"],
        )
        ended_feed = self.client.get(
            f"/api/game/session/{session_id}/feed?after=0", headers=self.headers
        ).json()["items"]
        ended_text = "\n".join(item["text"] for item in ended_feed)
        self.assertIn("提起菜篮转身下坡", ended_text)
        self.assertNotIn("拎着菜篮子径自走了", ended_text)

        knowledge = self.client.get(
            f"/api/game/session/{session_id}/knowledge",
            headers=self.headers,
        )
        self.assertEqual(2, len(knowledge.json()["facts"]))
        self.assertEqual([], knowledge.json()["clues"])
        self.assertEqual([], knowledge.json()["evidence"])
        self.assertIn("周姓11户", knowledge.json()["facts"][0]["text"])
        self.assertIn("可用于", knowledge.json()["facts"][0]["use_hint"])

        continued_d2 = self.client.post(
            f"/api/game/session/{session_id}/story/continue",
            json={"client_action_id": "api-d2-story", "state_version": second_talk.json()["state_version"]},
            headers=self.headers,
        )
        self.assertEqual(200, continued_d2.status_code, continued_d2.text)
        self.assertEqual(2, continued_d2.json()["visible_state"]["story"]["day"])
        ended_d2 = self.client.post(
            f"/api/game/session/{session_id}/end-day",
            json={
                "client_action_id": "api-d2-end-day-1",
                "state_version": continued_d2.json()["state_version"],
                "active_rest": False,
            },
            headers=self.headers,
        )
        self.assertEqual(200, ended_d2.status_code, ended_d2.text)
        self.assertEqual(3, ended_d2.json()["visible_state"]["story"]["day"])

        next_opportunity = self.client.get(
            f"/api/game/session/{session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual([], next_opportunity.json()["opportunities"])
        self.assertEqual(
            "必须先处理当前决策",
            next_opportunity.json()["blocked_reason"],
        )
        state = self.client.get(
            f"/api/game/session/{session_id}", headers=self.headers
        ).json()
        self.assertEqual(
            "dp1_02", state["pending_decision"]["decision_id"]
        )
        latest = self.client.get(
            "/api/game/session/latest-active", headers=self.headers
        )
        self.assertEqual(session_id, latest.json()["session_id"])
        self.assertEqual(3, latest.json()["story"]["day"])


if __name__ == "__main__":
    unittest.main()
