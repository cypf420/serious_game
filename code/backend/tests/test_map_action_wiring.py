from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class MapActionWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v2",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(settings)
        self.client = TestClient(create_app(settings, self.runtime))
        self.headers = {"X-Account-ID": "acct_map_wiring"}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={"client_request_id": "map-wiring-session-0001"},
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]

    def _map_action(self, location_id: str, title: str) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/map",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        location = next(
            item for item in response.json()["locations"]
            if item["location_id"] == location_id
        )
        return next(
            item for item in location["entry_cards"]
            if item["title"] == title
        )

    def test_map_uses_authoritative_backend_target_choices(self) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_map_wiring"
        )
        session.pending_decision = None
        session.pending_decision_queue.clear()
        self.runtime.sessions.save(
            session, expected_version=session.state_version
        )
        action = self._map_action("loc_liulin_village", "请党员户示范带头")
        self.assertTrue(action["available"])
        self.assertEqual(36, len(action["target_choices"]))
        self.assertEqual(
            {"target_id", "label"}, set(action["target_choices"][0])
        )

    def test_map_reflects_daily_cap_and_half_day_guards_before_click(self) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_map_wiring"
        )
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            daily_action_counts={"field_visit": 1},
        )
        self.runtime.sessions.save(
            session, expected_version=session.state_version
        )
        action = self._map_action("loc_liulin_village", "下乡进村")
        self.assertFalse(action["available"])
        self.assertEqual("今日次数已用尽", action["unavailable_reason"])

        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_map_wiring"
        )
        session.game_state = replace(
            session.game_state,
            daily_action_counts={},
            half_day_action_used=True,
        )
        self.runtime.sessions.save(
            session, expected_version=session.state_version
        )
        action = self._map_action("loc_liulin_village", "下乡进村")
        self.assertFalse(action["available"])
        self.assertEqual("今日半日行程已占用", action["unavailable_reason"])


if __name__ == "__main__":
    unittest.main()
