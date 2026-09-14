"""Feedback 30/31/33: real API boundaries with an explicitly injected test model double."""
from dataclasses import replace
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord


class FeedbackActionTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(environment="test", repository="memory", role_llm_provider="none",
            content_root=Path(__file__).resolve().parents[1] / "content/packages",
            default_package_id="pkg_gameplay_v3")
        self.runtime = build_container(settings)
        self.client = TestClient(create_app(settings, self.runtime))
        self.headers = {"X-Account-ID": "feedback-actions"}
        response = self.client.post("/api/game/session", headers=self.headers,
            json={"client_request_id": "feedback-actions-session"})
        self.assertEqual(201, response.status_code, response.text)
        self.sid = response.json()["session_id"]
        self.base = f"/api/game/session/{self.sid}"
        s = self.session()
        s.pending_decision = None
        s.pending_decision_queue.clear()
        s.game_state = replace(s.game_state, story_day=10, action_points=8)
        s.known_npc_ids.update({"npc_zhou_dashan", "npc_tan_laoliu"})
        s.encountered_npc_ids.update({"npc_zhou_dashan", "npc_tan_laoliu"})
        self.save(s)

    def session(self):
        return self.runtime.sessions.get_owned(self.sid, self.headers["X-Account-ID"])

    def save(self, session):
        self.runtime.sessions.save(session, expected_version=session.state_version)

    def get(self, path):
        r = self.client.get(self.base + path, headers=self.headers)
        self.assertEqual(200, r.status_code, r.text)
        return r.json()

    def post(self, path, body=None, status=200):
        body = {"state_version": self.session().state_version, **(body or {})}
        r = self.client.post(self.base + path, headers=self.headers, json=body)
        self.assertEqual(status, r.status_code, r.text)
        return r.json()

    def start(self, npc="npc_zhou_dashan"):
        d = next(x for x in self.get("/opportunities")["person_actions"]
                 if x["npc_id"] == npc and x["action_id"] == "household_visit")
        return self.post("/governance/actions", {
            "action_kind": d["action_id"], "variant_id": d["variant_id"],
            "location_id": d["legal_location_ids"][0], "target_ids": [npc],
            "topic": "核对各户诉求和协议办理条件"}, status=201)["action"]["action_instance_id"]

    def test_people_and_actions_share_targets_costs_and_gates(self):
        for points in (8, 0):
            s = self.session()
            s.game_state = replace(s.game_state, action_points=points)
            self.save(s)
            variants = [v for a in self.get("/actions")["actions"]
                        if a["action_id"] in {"household_visit", "cadre_interview"}
                        for v in a["variants"]]
            people = self.get("/opportunities")["person_actions"]
            expected = {(v["variant_id"], t["target_id"]) for v in variants for t in v["target_choices"]}
            self.assertEqual(expected, {(p["variant_id"], p["npc_id"]) for p in people})
            self.assertTrue(people)
            for p in people:
                v = next(v for v in variants if v["variant_id"] == p["variant_id"])
                for key in ("cost_action_points", "available", "unavailable_reason", "legal_location_ids"):
                    self.assertEqual(v[key], p[key], key)
                if points == 0 and p["cost_action_points"] > 0:
                    self.assertFalse(p["available"])
                if p["variant_id"] == "contract_negotiation":
                    self.assertEqual(0, p["cost_action_points"])
                    self.assertTrue(p["available"])
        self.assertNotIn("npc_wang_fang", {p["npc_id"] for p in people})

    def test_explicit_contract_preparation_is_idempotent_and_does_not_sign_or_spend(self):
        action = self.start()
        before = self.session()
        first = self.post(f"/governance/actions/{action}/prepare-contracts")
        second = self.post(f"/governance/actions/{action}/prepare-contracts")
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.session().contract_batches))
        self.assertEqual(before.game_state.action_points, self.session().game_state.action_points)
        self.assertEqual(before.game_state.signed_households, self.session().game_state.signed_households)
        confirmed = self.post(f"/governance/contract-batches/{first['batch']['batch_id']}/confirm", {"confirmed": True})
        self.assertTrue(confirmed["contracts"])
        self.assertTrue(all(c["status"] == "awaiting_terms" for c in confirmed["contracts"]))
        self.assertEqual(0, self.session().game_state.signed_households)
        r = self.client.post(self.base + f"/governance/actions/{action}/prepare-contracts",
            headers=self.headers, json={"state_version": self.session().state_version})
        self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual(1, len(self.session().contract_batches))

    def test_preparation_rejects_missing_action_stale_version_and_foreign_owner(self):
        r = self.client.post(self.base + "/governance/actions/missing/prepare-contracts",
            headers=self.headers, json={"state_version": self.session().state_version})
        self.assertGreaterEqual(r.status_code, 400)
        action = self.start()
        version = self.session().state_version
        for headers, sent_version in ((self.headers, version - 1), ({"X-Account-ID": "another-account"}, version)):
            r = self.client.post(self.base + f"/governance/actions/{action}/prepare-contracts",
                headers=headers, json={"state_version": sent_version})
            self.assertGreaterEqual(r.status_code, 400)
        self.assertEqual({}, self.session().contract_batches)

    def test_tan_can_prepare_without_hidden_story_gate_but_completed_action_cannot(self):
        action = self.start("npc_tan_laoliu")
        before = self.session()
        response = self.post(f"/governance/actions/{action}/prepare-contracts")
        self.assertTrue(response["batch"])
        after = self.session()
        self.assertEqual(before.game_state.signed_households, after.game_state.signed_households)
        self.assertEqual(before.game_state.budget_remaining, after.game_state.budget_remaining)
        self.assertEqual(before.resource_reservations, after.resource_reservations)
        after.governance_actions[action].status = "completed"
        self.save(after)
        response = self.client.post(self.base + f"/governance/actions/{action}/prepare-contracts",
            headers=self.headers, json={"state_version": after.state_version})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertEqual(1, len(self.session().contract_batches))

    def test_free_action_guide_persists_after_day_three_until_actual_completion(self):
        self.assertFalse(self.get("/view")["state"]["onboarding"]["free_action_completed"])
        action = self.start()
        self.assertFalse(self.get("/view")["state"]["onboarding"]["free_action_completed"])
        self.post(f"/governance/actions/{action}/finish")
        self.assertTrue(self.get("/view")["state"]["onboarding"]["free_action_completed"])

    def test_every_working_day_allows_free_work_after_required_scenes(self):
        package = self.runtime.packages.get("pkg_gameplay_v3")
        self.assertTrue(all(package.story_day(d).allow_actions for d in range(1, 90)))
        s = self.session()
        s.game_state = replace(s.game_state, story_day=51)
        self.runtime.story_flow.enter_current_day(s, package)
        self.save(s)
        self.assertIsNotNone(s.pending_decision)
        self.assertFalse(self.get("/view")["commands"]["can_act"])
        self.assertTrue(all(not p["available"] for p in self.get("/opportunities")["person_actions"]))

    def test_day_two_required_opportunity_is_returned_from_authoritative_state(self):
        package = self.runtime.packages.get("pkg_gameplay_v3")
        s = self.session()
        s.pending_decision = None
        s.pending_decision_queue.clear()
        s.flags = {"flag_clan_map"}
        s.known_npc_ids.add("npc_wu_xiuying")
        s.game_state = replace(s.game_state, story_day=2, action_points=8)
        self.save(s)

        view = self.get("/view")
        required = view["commands"]["required_opportunity"]
        self.assertIsNotNone(required)
        self.assertEqual("opp_d02_wu_xiuying_first_talk", required["opportunity_id"])
        self.assertEqual("npc_wu_xiuying", required["npc_id"])
        self.assertEqual("寻找会谈", required["entry_description"])
        self.assertIn("村庄关系", required["reason"])

        actions = self.get("/actions")
        self.assertEqual(required, actions["required_opportunity"])

    def test_ordinary_action_resolves_first_unlocked_location_when_picker_omits_it(self):
        descriptor = next(
            item for item in self.get("/opportunities")["person_actions"]
            if item["npc_id"] == "npc_zhou_dashan"
            and item["action_id"] == "household_visit"
        )
        choices = descriptor["location_choices"]
        self.assertTrue(choices)
        payload = self.post(
            "/governance/actions",
            {
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "target_ids": ["npc_zhou_dashan"],
                "topic": "核对各户诉求和协议办理条件",
            },
            status=201,
        )
        self.assertEqual(choices[0]["location_id"], payload["action"]["location_id"])
