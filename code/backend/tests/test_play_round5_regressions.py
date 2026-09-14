from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.progress_broadcast_policy import progress_broadcast
from serious_game_backend.application.story_flow_service import StoryFlowService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import ContentValidationError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"


class PlayRound5ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(self.settings)
        self.client = TestClient(create_app(self.settings, self.runtime))
        self.headers = {"X-Account-ID": "acct_play_round5"}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "play-round5-session",
                "package_id": "pkg_gameplay_v3",
                "origin_id": "technical",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]

    def _enter_day(self, day: int, *, flags: set[str] | None = None) -> dict:
        session = self.runtime.sessions.get_owned(self.session_id, "acct_play_round5")
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.logs.clear()
        session.narrative_feed.clear()
        session.next_feed_cursor = 1
        session.flags = set(flags or ())
        session.game_state = replace(
            session.game_state,
            story_day=day,
            days_left=90 - day,
            action_points=8,
        )
        package = self.runtime.packages.get("pkg_gameplay_v3")
        self.runtime.story_flow.enter_current_day(session, package)
        self.runtime.sessions.save(session, expected_version=session.state_version)
        return self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()

    def _choose(self, view: dict, option_id: str, key: str) -> dict:
        pending = view["state"]["pending_decision"]
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "decision",
                "client_action_id": f"round5-{key}",
                "state_version": view["state"]["state_version"],
                "decision_id": pending["decision_id"],
                "option_id": option_id,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        return self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()

    def test_d51_listen_repeat_has_a_new_visible_decision_and_reaches_d52(self) -> None:
        view = self._enter_day(51)
        original_ids = {item["content_instance_id"] for item in view["feed"]["items"]}

        repeated = self._choose(view, "a", "d51-listen")
        pending = repeated["state"]["pending_decision"]
        self.assertIsNotNone(pending)
        self.assertTrue(repeated["commands"]["can_choose"])
        self.assertNotIn(pending["presentation_entry_id"], original_ids)
        self.assertEqual(
            pending["presentation_entry_id"],
            repeated["feed"]["items"][-1]["content_instance_id"],
        )

        resolved = self._choose(repeated, "c", "d51-resolve")
        self.assertIsNone(resolved["state"]["pending_decision"])
        self.assertTrue(resolved["commands"]["can_end_day"])
        ended = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            headers=self.headers,
            json={
                "client_action_id": "round5-d51-end",
                "state_version": resolved["state"]["state_version"],
            },
        )
        self.assertEqual(200, ended.status_code, ended.text)
        self.assertEqual(52, ended.json()["visible_state"]["story"]["day"])

    def test_d51_other_options_close_or_repeat_without_losing_the_decision(self) -> None:
        for option_id, choices in {
            "b": ("b", "b", "b"),
            "c": ("c",),
            "d": ("d",),
            "e": ("e",),
        }.items():
            with self.subTest(option_id=option_id):
                view = self._enter_day(51)
                seen_ids = {item["content_instance_id"] for item in view["feed"]["items"]}
                for index, choice in enumerate(choices):
                    view = self._choose(view, choice, f"d51-{option_id}-{index}")
                    pending = view["state"]["pending_decision"]
                    if pending is not None:
                        self.assertNotIn(pending["presentation_entry_id"], seen_ids)
                        seen_ids.add(pending["presentation_entry_id"])
                self.assertIsNone(view["state"]["pending_decision"])
                self.assertTrue(view["commands"]["can_end_day"])

    def test_d55_paid_recovery_has_strict_descriptor_and_starts_from_people(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        configured = next(
            item for item in package.interaction_opportunities
            if item.opportunity_id == "opp_d55_yuan_guilan_paid_recovery"
        )
        view = self._enter_day(55, flags=set(configured.requires_flags))
        session = self.runtime.sessions.get_owned(self.session_id, "acct_play_round5")
        session.pending_decision = None
        session.pending_decision_queue.clear()
        # A real D55 run has known Yuan Guilan since her D5 story window.  The
        # focused day-jump fixture must preserve that discovery history.
        session.known_npc_ids.add(configured.npc_id)
        self.runtime.sessions.save(session, expected_version=session.state_version)
        view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities", headers=self.headers
        )
        self.assertEqual(200, response.status_code, response.text)
        opportunity = next(
            item for item in response.json()["opportunities"]
            if item["opportunity_id"] == "opp_d55_yuan_guilan_paid_recovery"
        )
        descriptor = opportunity["canonical_action_descriptor"]
        self.assertTrue(opportunity["cta_available"])
        self.assertEqual("household_visit", descriptor["action_id"])
        self.assertEqual("field_visit", descriptor["variant_id"])
        self.assertEqual("loc_county_hospital", descriptor["preselected_location_id"])
        self.assertEqual(["npc_yuan_guilan"], descriptor["preselected_npc_ids"])
        self.assertIn("医疗复查", descriptor["canonical_topic"])
        stored_before = self.runtime.sessions.get_owned(
            self.session_id, "acct_play_round5"
        )
        action_points_before = stored_before.game_state.action_points

        tampered = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": view["state"]["state_version"],
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": descriptor["preselected_location_id"],
                "target_ids": descriptor["preselected_npc_ids"],
                "topic": "改成与医疗复查无关的任意事项",
                "opportunity_id": opportunity["opportunity_id"],
                "archive_ids": [],
            },
        )
        self.assertEqual(409, tampered.status_code, tampered.text)
        unchanged = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        self.assertEqual(view["state"]["state_version"], unchanged["state"]["state_version"])
        stored_after = self.runtime.sessions.get_owned(
            self.session_id, "acct_play_round5"
        )
        self.assertEqual(action_points_before, stored_after.game_state.action_points)
        self.assertFalse(stored_after.governance_actions)

        started = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": view["state"]["state_version"],
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": descriptor["preselected_location_id"],
                "target_ids": descriptor["preselected_npc_ids"],
                "topic": descriptor["canonical_topic"],
                "opportunity_id": opportunity["opportunity_id"],
                "archive_ids": [],
            },
        )
        self.assertEqual(201, started.status_code, started.text)

    def test_every_published_opportunity_has_a_player_action_descriptor(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        for configured in package.interaction_opportunities:
            with self.subTest(opportunity_id=configured.opportunity_id):
                self.assertNotEqual("closed", configured.availability_mode.value)
                self._enter_day(
                    configured.day_min,
                    flags=set(configured.requires_flags),
                )
                session = self.runtime.sessions.get_owned(
                    self.session_id, "acct_play_round5"
                )
                session.pending_decision = None
                session.pending_decision_queue.clear()
                session.known_npc_ids.add(configured.npc_id)
                session.triggered_events = set(configured.requires_events)
                self.runtime.sessions.save(
                    session, expected_version=session.state_version
                )
                response = self.client.get(
                    f"/api/game/session/{self.session_id}/opportunities",
                    headers=self.headers,
                )
                self.assertEqual(200, response.status_code, response.text)
                visible = next(
                    item for item in response.json()["opportunities"]
                    if item["opportunity_id"] == configured.opportunity_id
                )
                descriptor = visible["canonical_action_descriptor"]
                self.assertIsNotNone(descriptor)
                self.assertTrue(visible["cta_available"])
                self.assertIsNone(visible["no_cta_reason"])
                self.assertEqual(
                    configured.opportunity_id, descriptor["opportunity_id"]
                )
                self.assertEqual(
                    [configured.npc_id], descriptor["preselected_npc_ids"]
                )
                self.assertTrue(descriptor["canonical_topic"].strip())

    def test_tan_laoliu_recovery_is_reachable_after_the_player_follows_the_old_money(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        recovery = next(
            item
            for item in package.interaction_opportunities
            if item.opportunity_id == "opp_d53_tan_laoliu_paid_recovery"
        )
        self.assertEqual(
            {"谭老六被强压", "白条线已启动"},
            set(recovery.requires_flags),
        )
        follow_money = next(
            item
            for item in package.decisions["dp4_06"].options
            if item.option_id == "d"
        )
        self.assertIn("白条线已启动", follow_money.effects.open_flags)
        self.assertTrue(
            set(recovery.requires_flags).isdisjoint(recovery.closes_on_flags)
        )

    def test_zhou_mancang_conversation_unlocks_the_ledger_order_decision_and_recovery(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        contact = next(
            item
            for item in package.interaction_opportunities
            if item.opportunity_id == "opp_03_zhou_mancang_contact"
        )
        self.assertEqual(
            {"fact_zhou_ledger_order"},
            set(contact.required_disclosure_ids),
        )
        self.assertIn("村账在手", contact.completion_flags)
        negotiation = package.decisions["dp5_04"]
        self.assertEqual({"村账在手"}, set(negotiation.required_flags))
        restart = next(
            item
            for item in package.interaction_opportunities
            if item.opportunity_id == "opp_d69_zhou_mancang_restart"
        )
        self.assertIn("周满仓已冷", restart.requires_flags)


class PlayRound5PolicyTests(unittest.TestCase):
    def test_runtime_rejects_hidden_metric_ranges_but_allows_amounts_and_households(self) -> None:
        with self.assertRaises(ContentValidationError):
            StoryFlowService.public_text("政治资本 +5 到 +10。")
        with self.assertRaises(ContentValidationError):
            StoryFlowService.public_text("群众信任-3至-1。")
        with self.assertRaises(ContentValidationError):
            StoryFlowService.public_text("焦虑 + 2。")
        self.assertEqual(
            "补偿三十万元，涉及九户。",
            StoryFlowService.public_text("补偿三十万元，涉及九户。"),
        )

    def test_every_v3_story_output_has_clean_terminal_punctuation(self) -> None:
        package = build_container(Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )).packages.get("pkg_gameplay_v3")
        texts = []
        for beat in package.story_days.values():
            texts.append(f"第{beat.story_day}日，{StoryFlowService.public_text(beat.title)}")
            texts.extend(StoryFlowService.public_text(item.text) for item in beat.opening_blocks)
            texts.extend(StoryFlowService.public_text(item.text) for item in beat.night_blocks)
        for decision in package.decisions.values():
            texts.extend((
                StoryFlowService.public_text(decision.title),
                StoryFlowService.public_text(decision.prompt),
                *(StoryFlowService.public_text(item.text) for item in decision.options),
                *(StoryFlowService.public_text(item.consequence) for item in decision.options),
                *(StoryFlowService.public_text(item.text) for item in decision.followup_blocks),
            ))
        for text in texts:
            self.assertIsNone(re.search(r"[，。；：！？]{2,}", text), text)
            self.assertRegex(text, r"[。！？…][」』”’）】]*$", text)

    def test_d30_d40_d50_zero_progress_is_always_reported_behind_reference(self) -> None:
        package = build_container(Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )).packages.get("pkg_gameplay_v3")
        from serious_game_backend.domain.game_session import GameSession
        from serious_game_backend.domain.game_state import GameState
        for day in (30, 40, 50):
            with self.subTest(day=day):
                state = replace(
                    GameState.new_game(package.initial_state),
                    story_day=day,
                    days_left=90 - day,
                    signed_households=0,
                )
                session = GameSession(
                    session_id=f"progress-{day}", account_id="acct",
                    package_id=package.package_id,
                    package_version=package.package_version,
                    package_content_hash=package.content_hash,
                    random_seed="seed", game_state=state, origin_id="technical",
                )
                broadcast = progress_broadcast(session)
                rendered = "".join((
                    broadcast["headline"], broadcast["message"], *broadcast["signals"]
                ))
                self.assertIn("还差", rendered)
                self.assertTrue(any(word in rendered for word in ("落后", "补进度", "失速")))
                self.assertNotIn("没有明显失速", rendered)
                self.assertNotIn("领先", rendered)


if __name__ == "__main__":
    unittest.main()
