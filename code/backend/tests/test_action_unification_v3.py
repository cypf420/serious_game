from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.domain.llm import RoleTurnResult
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"
ACTION_FAMILIES = {
    "household_visit",
    "cadre_interview",
    "leadership_meeting",
    "inspect_archives",
}


def _variant_config(base: dict) -> dict:
    config = dict(base)
    config["action_variants"] = [
        {
            "variant_id": "field_visit",
            "legacy_action_id": "field_visit",
            "action_id": "household_visit",
            "name": "现场走访",
            "enabled": True,
            "unlock_day": 1,
            "required_flags": [],
            "required_any_flags": [],
            "legal_location_ids": [
                "loc_liulin_village",
                "loc_hongda_factory",
                "loc_county_hospital",
            ],
            "target_kind": "household_representative",
            "legal_target_ids": list(base["household_representative_npc_ids"]),
            "action_point_costs": {"normal": 1, "sensitive": 2, "acceptance": 2},
            "resource_costs": [],
            "visible_result": "形成现场走访记录和待办事项。",
            "hard_outcomes": [{"kind": "follow_up", "id": "governance_action_record"}],
            "location_labels": {
                "loc_liulin_village": "入村走访",
                "loc_hongda_factory": "化工厂现场核查",
                "loc_county_hospital": "医院材料核验",
            },
        },
        {
            "variant_id": "interview_cadre",
            "legacy_action_id": "interview_cadre",
            "action_id": "cadre_interview",
            "name": "干部约谈",
            "enabled": True,
            "unlock_day": 1,
            "required_flags": [],
            "required_any_flags": [],
            "legal_location_ids": ["loc_county_government"],
            "target_kind": "cadre",
            "legal_target_ids": list(base["cadre_npc_ids"]),
            "action_point_costs": {"normal": 2, "sensitive": 3, "acceptance": 4},
            "resource_costs": [],
            "visible_result": "形成干部访谈记录和待核材料清单。",
            "hard_outcomes": [{"kind": "follow_up", "id": "governance_action_record"}],
        },
        {
            "variant_id": "convene_leadership_meeting",
            "legacy_action_id": "convene_leadership_meeting",
            "action_id": "leadership_meeting",
            "name": "班子会议",
            "enabled": True,
            "unlock_day": 1,
            "required_flags": [],
            "required_any_flags": [],
            "legal_location_ids": ["loc_county_government"],
            "target_kind": "meeting_participant",
            "legal_target_ids": list(base["leadership_meeting_npc_ids"]),
            "action_point_costs": {"normal": 3, "sensitive": 4, "acceptance": 5},
            "resource_costs": [],
            "visible_result": "形成会议记录及依法通过的决议或文件。",
            "hard_outcomes": [{"kind": "document", "id": "meeting_record"}],
        },
        {
            "variant_id": "public_hearing",
            "legacy_action_id": "public_hearing",
            "action_id": "leadership_meeting",
            "name": "公开听证",
            "enabled": True,
            "unlock_day": 1,
            "required_flags": [],
            "required_any_flags": [],
            "legal_location_ids": ["loc_county_government", "loc_liulin_village"],
            "target_kind": "meeting_participant",
            "legal_target_ids": [
                "npc_zhao_jianguo",
                "npc_feng_jingzhi",
                "npc_zhou_dashan",
                "npc_wu_xiuying",
                "npc_he_tiezhu",
                "npc_tan_laoliu",
                "npc_yuan_guilan",
                "npc_ning_dehai",
            ],
            "action_point_costs": {"normal": 3, "sensitive": 4, "acceptance": 5},
            "resource_cost_mode": "none",
            "resource_costs": [],
            "visible_result": "形成公开听证记录和程序性结论。",
            "hard_outcomes": [{"kind": "document", "id": "meeting_record"}],
        },
        {
            "variant_id": "clan_leader_campaign",
            "legacy_action_id": "clan_leader_campaign",
            "action_id": "leadership_meeting",
            "name": "宗族议事",
            "enabled": True,
            "unlock_day": 31,
            "required_flags": [],
            "required_any_flags": [],
            "legal_location_ids": ["loc_zhou_ancestral_hall"],
            "target_kind": "meeting_participant",
            "legal_target_ids": [
                "npc_zhou_dashan",
                "npc_zhou_kuiyuan",
                "npc_zhou_mancang",
            ],
            "action_point_costs": {"normal": 3, "sensitive": 4, "acceptance": 5},
            "resource_cost_mode": "none",
            "resource_costs": [],
            "visible_result": "形成宗族议事记录和后续事项。",
            "hard_outcomes": [{"kind": "document", "id": "meeting_record"}],
        },
        {
            "variant_id": "collect_blood_lead_report",
            "legacy_action_id": "collect_blood_lead_report",
            "action_id": "inspect_archives",
            "name": "调取血铅材料",
            "enabled": True,
            "unlock_day": 46,
            "required_flags": [],
            "required_any_flags": [
                "血铅疑云·初闻",
                "掌握血铅",
                "flag_blood_lead_known",
            ],
            "legal_location_ids": ["loc_county_hospital", "loc_liulin_village"],
            "target_kind": "available_archive",
            "legal_target_ids": ["available_archives"],
            "action_point_costs": {"normal": 1, "sensitive": 2, "acceptance": 2},
            "resource_cost_mode": "none",
            "resource_costs": [],
            "visible_result": "取得并登记符合授权条件的医院材料。",
            "hard_outcomes": [{"kind": "document", "id": "archive_read_record"}],
        },
    ]
    for variant in config["action_variants"]:
        if variant.get("enabled"):
            variant.setdefault("resource_cost_mode", "none")
    return config


class ActionUnificationV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v2",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(self.settings)
        base = self.runtime.packages.get("pkg_gameplay_v2")
        repaired = replace(
            base,
            package_id="pkg_action_unification_fixture",
            package_version="test-v4",
            content_hash="sha256:action-unification-fixture",
            gameplay_schema_version=4,
            governance_config=_variant_config(base.governance_config),
        )
        self.runtime.packages._items[repaired.package_id] = repaired
        self.client = TestClient(create_app(self.settings, self.runtime))
        self.headers = {"X-Account-ID": "acct_action_unification"}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "action-unification-session-0001",
                "package_id": repaired.package_id,
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]
        self._set_story_state(day=2)

    def _set_story_state(self, *, day: int, flags: set[str] | None = None) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        session.pending_decision = None
        session.flags = set(flags or ())
        session.game_state = replace(session.game_state, story_day=day)
        self.runtime.sessions.save(session, expected_version=session.state_version)

    def _actions(self) -> list[dict]:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/actions", headers=self.headers
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["actions"]

    def _mark_encountered(self, *npc_ids: str) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        session.known_npc_ids.update(npc_ids)
        session.encountered_npc_ids.update(npc_ids)
        self.runtime.sessions.save(session, expected_version=session.state_version)

    def _map(self) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/map", headers=self.headers
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_actions_expose_exactly_four_families_with_current_variants(self) -> None:
        actions = self._actions()
        self.assertEqual(ACTION_FAMILIES, {item["action_id"] for item in actions})
        self.assertEqual(4, len(actions))
        field_visit = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "field_visit"
        )
        self.assertEqual("household_visit", field_visit["action_id"])
        self.assertIn("visible_result", field_visit)
        self.assertEqual(
            {"minimum": 1, "maximum": 1},
            field_visit["participant_rules"],
        )
        self.assertIn(
            {"location_id": "loc_liulin_village", "label": "入村走访"},
            field_visit["location_choices"],
        )
        meeting_variant = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "public_hearing"
        )
        self.assertEqual(
            {"minimum": 2, "maximum": 8},
            meeting_variant["participant_rules"],
        )
        self.assertNotIn("resource_action", json.dumps(actions, ensure_ascii=False))

    def test_map_uses_non_executable_governance_descriptors(self) -> None:
        locations = self._map()["locations"]
        cards = [card for location in locations for card in location["entry_cards"]]
        self.assertTrue(cards)
        self.assertTrue(all(card["action_id"] in ACTION_FAMILIES for card in cards))
        self.assertTrue(all("preselected_location_id" in card for card in cards))
        self.assertTrue(all("preselected_npc_ids" in card for card in cards))
        self.assertTrue(all("participant_rules" in card for card in cards))
        self.assertTrue(all("target_choices" in card for card in cards))
        self.assertTrue(all(card["location_locked"] is True for card in cards))
        self.assertTrue(all(card["map_entry_id"].startswith("map:") for card in cards))
        self.assertEqual(len(cards), len({card["map_entry_id"] for card in cards}))
        self.assertTrue(all("submit" not in card for card in cards))
        self.assertTrue(all(card["entry_type"] != "resource_action" for card in cards))
        for location in locations:
            for card in location["entry_cards"]:
                self.assertEqual(
                    [{
                        "location_id": location["location_id"],
                        "label": location["name"],
                    }],
                    card["location_choices"],
                )

    def test_late_game_map_preselection_never_exceeds_participant_limit(self) -> None:
        self._set_story_state(day=46)
        cards = [
            card
            for location in self._map()["locations"]
            for card in location["entry_cards"]
        ]
        self.assertTrue(cards)
        for card in cards:
            self.assertLessEqual(
                len(card["preselected_npc_ids"]),
                card["participant_rules"]["maximum"],
                card["map_entry_id"],
            )
        village_visit = next(
            card
            for location in self._map()["locations"]
            if location["location_id"] == "loc_liulin_village"
            for card in location["entry_cards"]
            if card["variant_id"] == "field_visit"
        )
        if len(village_visit["target_choices"]) > 1:
            self.assertEqual([], village_visit["preselected_npc_ids"])

    def test_map_entry_locks_location_and_rejects_tampering_without_partial_state(
        self,
    ) -> None:
        self._set_story_state(day=3)
        self._mark_encountered("npc_zhou_dashan")
        factory = next(
            item for item in self._map()["locations"]
            if item["location_id"] == "loc_hongda_factory"
        )
        card = next(
            item for item in factory["entry_cards"]
            if item["variant_id"] == "field_visit"
        )
        target_id = card["target_choices"][0]["target_id"]
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        assert session is not None
        before_version = session.state_version
        before_points = session.game_state.action_points
        before_actions = dict(session.governance_actions)
        payload = {
            "state_version": before_version,
            "action_kind": card["action_id"],
            "variant_id": card["variant_id"],
            "location_id": card["preselected_location_id"],
            "map_entry_id": card["map_entry_id"],
            "target_ids": [target_id],
            "topic": "核查化工厂周边的搬迁与环境情况",
        }
        mutations = {
            "location": {"location_id": "loc_liulin_village"},
            "action": {"action_kind": "cadre_interview"},
            "variant": {"variant_id": "interview_cadre"},
            "entry": {"map_entry_id": "map:loc_hongda_factory:missing"},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                tampered = self.client.post(
                    f"/api/game/session/{self.session_id}/governance/actions",
                    headers=self.headers,
                    json={**payload, **mutation},
                )
                self.assertEqual(409, tampered.status_code, tampered.text)
                unchanged = self.runtime.sessions.get_owned(
                    self.session_id, "acct_action_unification"
                )
                assert unchanged is not None
                self.assertEqual(before_version, unchanged.state_version)
                self.assertEqual(before_points, unchanged.game_state.action_points)
                self.assertEqual(before_actions, unchanged.governance_actions)

        valid = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(201, valid.status_code, valid.text)
        self.assertEqual(card["map_entry_id"], valid.json()["action"]["map_entry_id"])
        self.assertEqual(card["title"], valid.json()["action"]["display_title"])
        self.assertEqual(
            "loc_hongda_factory", valid.json()["action"]["location_id"]
        )

    def test_people_entries_embed_a_legal_canonical_action_descriptor(self) -> None:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        opportunities = response.json()["opportunities"]
        self.assertTrue(opportunities)
        for opportunity in opportunities:
            descriptor = opportunity["canonical_action_descriptor"]
            self.assertIn(descriptor["action_id"], {
                "household_visit", "cadre_interview",
            })
            self.assertTrue(descriptor["variant_id"])
            self.assertEqual(
                [opportunity["npc_id"]],
                descriptor["preselected_npc_ids"],
            )
            self.assertIn(
                opportunity["npc_id"],
                {item["target_id"] for item in descriptor["target_choices"]},
            )
            self.assertIn(
                descriptor["preselected_location_id"],
                {item["location_id"] for item in descriptor["location_choices"]},
            )
            self.assertNotIn("submit", descriptor)

    def test_map_uses_contextual_field_labels_and_keeps_blood_lead_locked(self) -> None:
        def card(location_id: str, variant_id: str) -> dict:
            location = next(
                item for item in self._map()["locations"]
                if item["location_id"] == location_id
            )
            return next(
                item for item in location["entry_cards"]
                if item.get("variant_id") == variant_id
            )

        self.assertEqual("入村走访", card("loc_liulin_village", "field_visit")["title"])
        self.assertEqual("化工厂现场核查", card("loc_hongda_factory", "field_visit")["title"])
        self.assertEqual("医院材料核验", card("loc_county_hospital", "field_visit")["title"])

        self._set_story_state(day=45, flags={"掌握血铅"})
        self.assertFalse(card("loc_county_hospital", "collect_blood_lead_report")["available"])
        self._set_story_state(day=46)
        self.assertFalse(card("loc_county_hospital", "collect_blood_lead_report")["available"])
        self._set_story_state(day=46, flags={"掌握血铅"})
        self.assertTrue(card("loc_county_hospital", "collect_blood_lead_report")["available"])

    def test_meeting_variants_filter_their_own_legal_participants(self) -> None:
        self._set_story_state(day=31)
        self._mark_encountered(
            "npc_zhao_jianguo",
            "npc_qian_wei",
            "npc_sun_qiang",
            "npc_zhou_dashan",
            "npc_zhou_kuiyuan",
        )
        variants = {
            variant["variant_id"]: variant
            for action in self._actions()
            for variant in action["variants"]
        }
        package = self.runtime.packages.get("pkg_action_unification_fixture")
        leadership = {
            item["target_id"]
            for item in variants["convene_leadership_meeting"]["target_choices"]
        }
        hearing = {
            item["target_id"]
            for item in variants["public_hearing"]["target_choices"]
        }
        clan = {
            item["target_id"]
            for item in variants["clan_leader_campaign"]["target_choices"]
        }
        self.assertTrue(leadership)
        self.assertTrue(leadership.issubset(
            set(package.governance_config["leadership_meeting_npc_ids"])
        ))
        self.assertTrue(hearing)
        self.assertTrue(hearing.issubset({
                "npc_zhao_jianguo", "npc_feng_jingzhi", "npc_zhou_dashan",
                "npc_wu_xiuying", "npc_he_tiezhu", "npc_tan_laoliu",
                "npc_yuan_guilan", "npc_ning_dehai",
        }))
        self.assertTrue(clan)
        self.assertTrue(clan.issubset(
            {"npc_zhou_dashan", "npc_zhou_kuiyuan", "npc_zhou_mancang"}
        ))
        self.assertNotEqual(leadership, hearing)
        self.assertNotEqual(hearing, clan)

    def test_variant_targets_do_not_reveal_unintroduced_npcs(self) -> None:
        variants = {
            variant["variant_id"]: variant
            for action in self._actions()
            for variant in action["variants"]
        }
        leadership_ids = {
            item["target_id"]
            for item in variants["convene_leadership_meeting"]["target_choices"]
        }
        self.assertNotIn("npc_gu_keming", leadership_ids)

    def test_governance_submission_executes_selected_variant_context(self) -> None:
        self._mark_encountered("npc_zhao_jianguo", "npc_zhou_dashan")
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": "leadership_meeting",
                "variant_id": "public_hearing",
                "location_id": "loc_liulin_village",
                "target_ids": ["npc_zhao_jianguo", "npc_zhou_dashan"],
                "topic": "补偿程序",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual("public_hearing", response.json()["action"]["variant_id"])
        self.assertEqual("loc_liulin_village", response.json()["action"]["location_id"])
        meeting_id = response.json()["meeting"]["meeting_id"]
        self.assertEqual(
            [{
                "kind": "document",
                "id": "meeting_record",
                "authoritative_ids": [meeting_id],
            }],
            response.json()["action"]["hard_outcomes"],
        )
        stored = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        action_id = response.json()["action"]["action_instance_id"]
        self.assertEqual(
            response.json()["action"]["hard_outcomes"],
            stored.governance_actions[action_id].hard_outcomes,
        )

    def test_conversation_variant_persists_follow_up_action_record(self) -> None:
        self._mark_encountered("npc_zhou_dashan")
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": "household_visit",
                "variant_id": "field_visit",
                "location_id": "loc_liulin_village",
                "target_ids": ["npc_zhou_dashan"],
                "topic": "入户了解诉求",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        action = response.json()["action"]
        self.assertEqual(
            [{
                "kind": "follow_up",
                "id": "governance_action_record",
                "authoritative_ids": [action["action_instance_id"]],
            }],
            action["hard_outcomes"],
        )

    def test_governance_submission_rejects_targets_from_another_variant(self) -> None:
        self._set_story_state(day=31)
        self._mark_encountered("npc_zhao_jianguo", "npc_zhou_dashan")
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": "leadership_meeting",
                "variant_id": "clan_leader_campaign",
                "location_id": "loc_zhou_ancestral_hall",
                "target_ids": ["npc_zhao_jianguo", "npc_zhou_dashan"],
                "topic": "祖坟安排",
            },
        )
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual("ACTION_UNAVAILABLE", response.json()["error"]["code"])

    def test_schema_v4_governance_submission_requires_variant_and_location(self) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": "household_visit",
                "target_ids": ["npc_zhou_dashan"],
                "topic": "入户了解诉求",
            },
        )
        self.assertEqual(409, response.status_code, response.text)
        self.assertEqual("ACTION_UNAVAILABLE", response.json()["error"]["code"])


class GameplayV3PlayerRegressionTests(unittest.TestCase):
    """Player-facing regressions found through the production v3 API flow."""

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
        self.account_id = "acct_player_regressions"
        self.headers = {"X-Account-ID": self.account_id}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={"client_request_id": "player-regression-session-0001"},
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        self.assertIsNotNone(session)
        assert session is not None
        session.pending_decision = None
        session.flags = {"flag_clan_map"}
        session.known_fact_ids.add("fact_clan_power_map")
        session.game_state = replace(
            session.game_state,
            story_day=2,
            days_left=89,
            action_points=8,
        )
        self.runtime.sessions.save(session, expected_version=session.state_version)

    def _wu_descriptor(self) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return next(
            item
            for item in response.json()["opportunities"]
            if item["opportunity_id"] == "opp_d02_wu_xiuying_first_talk"
        )

    def _complete_wu_governance_visit(self) -> dict:
        opportunity = self._wu_descriptor()
        descriptor = opportunity["canonical_action_descriptor"]
        before = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        started = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": before["state"]["state_version"],
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": descriptor["preselected_location_id"],
                "target_ids": descriptor["preselected_npc_ids"],
                "topic": opportunity["conversation_goal"],
                "opportunity_id": opportunity["opportunity_id"],
            },
        )
        self.assertEqual(201, started.status_code, started.text)
        action_id = started.json()["action"]["action_instance_id"]
        turn = self.client.post(
            (
                f"/api/game/session/{self.session_id}/governance/actions/"
                f"{action_id}/turn"
            ),
            headers=self.headers,
            json={
                "state_version": started.json()["state_version"],
                "player_text": "吴老师，我想先听听村里人真正担心什么。",
            },
        )
        self.assertEqual(200, turn.status_code, turn.text)
        finished = self.client.post(
            (
                f"/api/game/session/{self.session_id}/governance/actions/"
                f"{action_id}/finish"
            ),
            headers=self.headers,
            json={"state_version": turn.json()["state_version"]},
        )
        self.assertEqual(200, finished.status_code, finished.text)
        return finished.json()

    def test_people_governance_visit_unlocks_required_d2_end_day_and_reaches_d3(
        self,
    ) -> None:
        blocked = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        )
        self.assertFalse(blocked.json()["commands"]["can_end_day"])

        finished = self._complete_wu_governance_visit()

        latest_view = None
        for action_points, overtime_used in (
            (8, False), (7, False), (0, False), (0, True),
        ):
            with self.subTest(
                action_points=action_points,
                overtime_used=overtime_used,
            ):
                stored = self.runtime.sessions.get_owned(
                    self.session_id, self.account_id
                )
                assert stored is not None
                stored.game_state = replace(
                    stored.game_state,
                    action_points=action_points,
                    overtime_used_today=overtime_used,
                    overtime_points_today=1 if overtime_used else 0,
                )
                self.runtime.sessions.save(
                    stored, expected_version=stored.state_version
                )
                latest_view = self.client.get(
                    f"/api/game/session/{self.session_id}/view",
                    headers=self.headers,
                )
                self.assertEqual(200, latest_view.status_code, latest_view.text)
                self.assertTrue(latest_view.json()["commands"]["can_end_day"])
        assert latest_view is not None
        ended = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            headers=self.headers,
            json={
                "client_action_id": "player-regression-d2-end-0001",
                "state_version": latest_view.json()["state"]["state_version"],
                "active_rest": False,
            },
        )
        self.assertEqual(200, ended.status_code, ended.text)
        self.assertEqual(3, ended.json()["visible_state"]["story"]["day"])

    def test_people_governance_turn_exposes_recent_qualitative_reason(self) -> None:
        before = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, before.status_code, before.text)
        before_person = next(
            item for item in before.json()["people"]
            if item["npc_id"] == "npc_wu_xiuying"
        )
        expected_topic = next(
            item["conversation_goal"]
            for item in before.json()["opportunities"]
            if item["opportunity_id"] == "opp_d02_wu_xiuying_first_talk"
        )
        self.assertTrue(before_person["recent_change_reasons"])
        self.assertLessEqual(len(before_person["recent_change_reasons"]), 3)
        self.assertEqual(
            {"trust", "attitude", "anxiety"},
            set(before_person["relationship_reasons"]),
        )
        self.assertTrue(all(
            before_person["relationship_reasons"][dimension].strip()
            for dimension in ("trust", "attitude", "anxiety")
        ))
        self.assertTrue(any(
            marker in "".join(before_person["recent_change_reasons"])
            for marker in ("名册", "剧情", "材料", "工作联系")
        ))

        self._complete_wu_governance_visit()
        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        person = next(
            item for item in response.json()["people"]
            if item["npc_id"] == "npc_wu_xiuying"
        )
        self.assertIn(
            person["trust_band"],
            {"closed", "guarded", "working", "trusted"},
        )
        self.assertIn(
            person["attitude_band"],
            {"hostile", "resistant", "neutral", "cooperative", "supportive"},
        )
        self.assertIn(
            person["anxiety_band"],
            {"calm", "uneasy", "worried", "strained", "critical"},
        )
        self.assertTrue(person["recent_change_reasons"])
        self.assertLessEqual(len(person["recent_change_reasons"]), 3)
        self.assertEqual(
            {"trust", "attitude", "anxiety"},
            set(person["relationship_reasons"]),
        )
        reasons = "".join(person["recent_change_reasons"])
        self.assertIn("本次会谈", reasons)
        self.assertIn(expected_topic, reasons)
        for hidden_marker in ("trust_score", "attitude_score", "anxiety_score"):
            self.assertNotIn(hidden_marker, reasons)

    def test_governance_write_can_be_saved_listed_and_loaded_without_409(self) -> None:
        view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        actions = self.client.get(
            f"/api/game/session/{self.session_id}/actions", headers=self.headers
        ).json()["actions"]
        archive = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )
        first_archive_id = archive["target_choices"][0]["target_id"]
        inspected = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": view["state"]["state_version"],
                "action_kind": archive["action_id"],
                "variant_id": archive["variant_id"],
                "location_id": archive["location_choices"][0]["location_id"],
                "archive_ids": [first_archive_id],
            },
        )
        self.assertEqual(201, inspected.status_code, inspected.text)
        saved = self.client.post(
            f"/api/game/session/{self.session_id}/manual-saves",
            headers=self.headers,
            json={
                "client_action_id": "player-regression-manual-save-0001",
                "state_version": inspected.json()["state_version"],
                "slot_number": 1,
                "display_name": "查档后的关键节点",
                "overwrite": False,
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        listed = self.client.get(
            f"/api/game/session/{self.session_id}/manual-saves",
            headers=self.headers,
        )
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertEqual(
            [saved.json()["snapshot_id"]],
            [item["snapshot_id"] for item in listed.json()["manual_saves"]],
        )
        loaded = self.client.post(
            f"/api/game/session/{self.session_id}/load-snapshot",
            headers=self.headers,
            json={
                "client_action_id": "player-regression-manual-load-0001",
                "state_version": listed.json()["state_version"],
                "snapshot_id": saved.json()["snapshot_id"],
                "confirmed": True,
            },
        )
        self.assertEqual(200, loaded.status_code, loaded.text)
        self.assertEqual(2, loaded.json()["story_day"])

    def test_d2_required_opportunity_manual_save_restores_complete_business_state(
        self,
    ) -> None:
        completed = self._complete_wu_governance_visit()
        completed_view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        completed_session = self.runtime.sessions.get_owned(
            self.session_id, self.account_id
        )
        assert completed_session is not None
        completed_points = completed_session.game_state.action_points
        completed_flags = set(completed_session.flags)
        self.assertTrue(completed_view["commands"]["can_end_day"])
        self.assertIn("flag_wu_first_talk_completed", completed_flags)

        saved = self.client.post(
            f"/api/game/session/{self.session_id}/manual-saves",
            headers=self.headers,
            json={
                "client_action_id": "d2-required-opportunity-save-0001",
                "state_version": completed["state_version"],
                "slot_number": 2,
                "display_name": "吴秀英会谈完成后",
                "overwrite": False,
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)

        actions = self.client.get(
            f"/api/game/session/{self.session_id}/actions", headers=self.headers
        ).json()["actions"]
        archive = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )
        mutated = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": saved.json()["state_version"],
                "action_kind": archive["action_id"],
                "variant_id": archive["variant_id"],
                "location_id": archive["location_choices"][0]["location_id"],
                "archive_ids": [archive["target_choices"][0]["target_id"]],
            },
        )
        self.assertEqual(201, mutated.status_code, mutated.text)
        self.assertNotEqual(
            completed_points,
            self.runtime.sessions.get_owned(
                self.session_id, self.account_id
            ).game_state.action_points,
        )

        loaded = self.client.post(
            f"/api/game/session/{self.session_id}/load-snapshot",
            headers=self.headers,
            json={
                "client_action_id": "d2-required-opportunity-load-0001",
                "state_version": mutated.json()["state_version"],
                "snapshot_id": saved.json()["snapshot_id"],
                "confirmed": True,
            },
        )
        self.assertEqual(200, loaded.status_code, loaded.text)
        restored = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert restored is not None
        self.assertEqual(completed_points, restored.game_state.action_points)
        self.assertEqual(completed_flags, set(restored.flags))
        self.assertEqual(2, restored.game_state.story_day)
        self.assertTrue(
            self.client.get(
                f"/api/game/session/{self.session_id}/view", headers=self.headers
            ).json()["commands"]["can_end_day"]
        )
        opportunities = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        ).json()["opportunities"]
        self.assertNotIn(
            "opp_d02_wu_xiuying_first_talk",
            {item["opportunity_id"] for item in opportunities},
        )

    def test_household_archive_localizes_ownership_enums(self) -> None:
        view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        actions = self.client.get(
            f"/api/game/session/{self.session_id}/actions", headers=self.headers
        ).json()["actions"]
        archive = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )
        households = next(
            item for item in archive["target_choices"]
            if "36户" in item["label"]
        )
        result = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": view["state"]["state_version"],
                "action_kind": archive["action_id"],
                "variant_id": archive["variant_id"],
                "location_id": archive["location_choices"][0]["location_id"],
                "archive_ids": [households["target_id"]],
            },
        )
        self.assertEqual(201, result.status_code, result.text)
        prose = json.dumps(result.json()["archives"][0]["player_sections"], ensure_ascii=False)
        for raw in (
            "overbuild_partly_recognized", "ledger_sensitive",
            "old_contract_sensitive", "clear",
        ):
            self.assertNotIn(raw, prose)
        self.assertIn("权属清晰", prose)
        self.assertIn("超建部分待认定", prose)

    def test_finished_people_governance_visit_is_in_conversation_history_once(
        self,
    ) -> None:
        self._complete_wu_governance_visit()
        history = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            params={"npc_id": "npc_wu_xiuying", "story_day": 2, "limit": 1},
            headers=self.headers,
        )
        self.assertEqual(200, history.status_code, history.text)
        self.assertEqual(1, len(history.json()["items"]))
        self.assertIsNone(history.json()["next_cursor"])
        record = history.json()["items"][0]
        self.assertEqual("npc_wu_xiuying", record["npc_id"])
        self.assertEqual(2, record["story_day"])
        self.assertEqual("completed", record["completion_status"])
        self.assertEqual(
            ["player", "npc"],
            [
                item["speaker_type"]
                for item in record["transcript"]
            ],
        )
        self.assertNotIn("npc_id", record["transcript"][0])
        self.assertEqual(
            "npc_wu_xiuying", record["transcript"][1]["npc_id"]
        )
        self.assertTrue(all(item["text"].strip() for item in record["transcript"]))
        for params in (
            {"npc_id": "npc_zhao_jianguo", "story_day": 2},
            {"npc_id": "npc_wu_xiuying", "story_day": 3},
        ):
            with self.subTest(params=params):
                empty = self.client.get(
                    f"/api/game/session/{self.session_id}/conversations",
                    params=params,
                    headers=self.headers,
                )
                self.assertEqual(200, empty.status_code, empty.text)
                self.assertEqual([], empty.json()["items"])

    def test_archive_api_strictly_projects_known_schema_and_drops_unknown_secrets(
        self,
    ) -> None:
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        archive = session.archive_records["archive_project_brief"]
        archive.content = json.dumps({
            "title": "云溪县搬迁治理任务书",
            "summary": "在期限内完成依法治理。",
            "hard_constraints": [{
                "key": "deadline",
                "label": "期限",
                "value": "90天",
                "detail": "到期按真实状态验收",
                "private_audit": "SECRET_NESTED_AUDIT",
            }],
            "private_audit": "SECRET_ROOT_AUDIT",
            "prompt": "SECRET_PROMPT",
            "debug_notes": {"summary": "SECRET_DEBUG_SUMMARY"},
            "unknown_scalar": "SECRET_UNKNOWN_SCALAR",
        }, ensure_ascii=False)
        self.runtime.sessions.save(session, expected_version=session.state_version)
        actions = self.client.get(
            f"/api/game/session/{self.session_id}/actions", headers=self.headers
        ).json()["actions"]
        variant = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": variant["action_id"],
                "variant_id": variant["variant_id"],
                "location_id": variant["location_choices"][0]["location_id"],
                "archive_ids": ["archive_project_brief"],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        rendered = json.dumps(
            response.json()["archives"][0]["player_sections"],
            ensure_ascii=False,
        )
        self.assertIn("90天", rendered)
        for secret in (
            "SECRET_NESTED_AUDIT", "SECRET_ROOT_AUDIT", "SECRET_PROMPT",
            "SECRET_DEBUG_SUMMARY", "SECRET_UNKNOWN_SCALAR", "private_audit",
            "debug_notes", "unknown_scalar",
        ):
            self.assertNotIn(secret, rendered)

    def test_opportunity_rejects_noncanonical_location_without_partial_state(
        self,
    ) -> None:
        opportunity = self._wu_descriptor()
        descriptor = opportunity["canonical_action_descriptor"]
        before = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert before is not None
        history_before = self.runtime.snapshots.list_history(
            self.account_id, self.session_id
        )
        response = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": before.state_version,
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": "loc_county_hospital",
                "target_ids": descriptor["preselected_npc_ids"],
                "topic": opportunity["conversation_goal"],
                "opportunity_id": opportunity["opportunity_id"],
            },
        )
        self.assertEqual(409, response.status_code, response.text)
        after = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert after is not None
        self.assertEqual(before.state_version, after.state_version)
        self.assertEqual(before.game_state.action_points, after.game_state.action_points)
        self.assertEqual(before.governance_actions, after.governance_actions)
        self.assertEqual(
            [item.snapshot_id for item in history_before],
            [
                item.snapshot_id for item in self.runtime.snapshots.list_history(
                    self.account_id, self.session_id
                )
            ],
        )

    def test_opportunity_rejects_every_tampered_canonical_field_without_partial_state(
        self,
    ) -> None:
        opportunity = self._wu_descriptor()
        descriptor = opportunity["canonical_action_descriptor"]
        valid = {
            "action_kind": descriptor["action_id"],
            "variant_id": descriptor["variant_id"],
            "location_id": descriptor["preselected_location_id"],
            "target_ids": descriptor["preselected_npc_ids"],
            "topic": descriptor["canonical_topic"],
            "opportunity_id": opportunity["opportunity_id"],
        }
        mutations = {
            "variant_id": "interview_cadre",
            "location_id": "loc_county_hospital",
            "target_ids": ["npc_zhao_jianguo"],
            "topic": "了解对方对搬迁安排的核心诉求与底线",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                before = self.runtime.sessions.get_owned(
                    self.session_id, self.account_id
                )
                assert before is not None
                history_before = self.runtime.snapshots.list_history(
                    self.account_id, self.session_id
                )
                response = self.client.post(
                    f"/api/game/session/{self.session_id}/governance/actions",
                    headers=self.headers,
                    json={
                        "state_version": before.state_version,
                        **valid,
                        field: value,
                    },
                )
                self.assertEqual(409, response.status_code, response.text)
                after = self.runtime.sessions.get_owned(
                    self.session_id, self.account_id
                )
                assert after is not None
                self.assertEqual(before.state_version, after.state_version)
                self.assertEqual(
                    before.game_state.action_points,
                    after.game_state.action_points,
                )
                self.assertEqual(before.governance_actions, after.governance_actions)
                self.assertEqual(
                    [item.snapshot_id for item in history_before],
                    [
                        item.snapshot_id
                        for item in self.runtime.snapshots.list_history(
                            self.account_id, self.session_id
                        )
                    ],
                )

    def _assert_governance_role_output_rejected(
        self,
        result: RoleTurnResult,
        *forbidden_values: str,
        forbidden_fact_id: str = "fact_two_million_fee",
    ) -> None:
        opportunity = self._wu_descriptor()
        descriptor = opportunity["canonical_action_descriptor"]
        view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        ).json()
        started = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": view["state"]["state_version"],
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": descriptor["preselected_location_id"],
                "target_ids": descriptor["preselected_npc_ids"],
                "topic": opportunity["conversation_goal"],
                "opportunity_id": opportunity["opportunity_id"],
            },
        )
        self.assertEqual(201, started.status_code, started.text)
        action_id = started.json()["action"]["action_instance_id"]

        class LeakingGateway:
            def run_turn(self, context):
                return replace(result, npc_id=context.npc_id)

        self.runtime.gameplay_governance._npc_turns._gateway = LeakingGateway()
        response = self.client.post(
            (
                f"/api/game/session/{self.session_id}/governance/actions/"
                f"{action_id}/turn/stream"
            ),
            headers=self.headers,
            json={
                "state_version": started.json()["state_version"],
                "player_text": "吴老师，请说说村里人的真实顾虑。",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"type": "error"', response.text)
        for forbidden in forbidden_values:
            self.assertNotIn(forbidden, response.text)
        stored = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert stored is not None
        self.assertEqual([], stored.governance_actions[action_id].transcript)
        self.assertNotIn(forbidden_fact_id, stored.known_fact_ids)
        durable = self.runtime.npc_memories._repository.active_for_npc(
            self.session_id, "npc_wu_xiuying", 2
        )
        self.assertEqual((), durable)
        review = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            headers=self.headers,
        )
        self.assertEqual(200, review.status_code, review.text)
        for forbidden in forbidden_values:
            self.assertNotIn(forbidden, review.text)

    def test_governance_rejects_forbidden_fact_title_in_reply(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="我知道两百万前期协调费的秘密安排。",
            ),
            "两百万前期协调费",
        )

    def test_governance_rejects_forbidden_fact_id_in_memory_candidate(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="我只能谈村里的公开顾虑。",
                memory_candidate="fact_two_million_fee",
            ),
            "fact_two_million_fee",
        )

    def test_governance_rejects_forbidden_fact_text_phrase_in_reply(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="那笔凭证需要说明真实去处。",
            ),
            "凭证需要说明真实去处",
        )

    def test_governance_rejects_forbidden_fact_alias_in_exit_narrative(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="今天先谈到这里。",
                conversation_state="end",
                exit_narrative="她拒绝再谈200万前期协调费。",
            ),
            "200万前期协调费",
        )

    def test_governance_rejects_registered_short_usb_alias_in_dialogue(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="我知道那个优盘的下落。",
            ),
            "优盘",
            forbidden_fact_id="fact_shi_usb",
        )

    def test_governance_rejects_plain_string_sequence_field_fail_safe(self) -> None:
        self._assert_governance_role_output_rejected(
            RoleTurnResult(
                npc_id="placeholder",
                dialogue="我只能谈村里的公开顾虑。",
                will_share_with="优盘",
            ),
            "优盘",
            forbidden_fact_id="fact_shi_usb",
        )

    def test_legacy_action_rejects_forbidden_memory_before_durable_write(self) -> None:
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        started = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "conversation_start",
                "client_action_id": "legacy-boundary-start-0001",
                "state_version": session.state_version,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
            },
        )
        self.assertEqual(200, started.status_code, started.text)
        conversation_id = started.json()["conversation"]["conversation_id"]

        class MemoryLeakGateway:
            def run_turn(self, context):
                return RoleTurnResult(
                    npc_id=context.npc_id,
                    dialogue="我只能谈村里的公开顾虑。",
                    memory_candidate="那笔凭证需要说明真实去处。",
                )

        self.runtime.npc_turns._gateway = MemoryLeakGateway()
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action/stream",
            headers=self.headers,
            json={
                "input_mode": "free_text",
                "client_action_id": "legacy-boundary-turn-0001",
                "state_version": started.json()["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "吴老师，请说说村里人的真实顾虑。",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn("凭证需要说明真实去处", response.text)
        stored = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert stored is not None
        self.assertEqual([], stored.active_conversation.transcript)
        self.assertEqual(
            (),
            self.runtime.npc_memories._repository.active_for_npc(
                self.session_id, "npc_wu_xiuying", 2
            ),
        )
        review = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            headers=self.headers,
        )
        self.assertNotIn("凭证需要说明真实去处", review.text)

    def test_legacy_action_rejects_short_usb_alias_before_durable_memory(self) -> None:
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        started = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "conversation_start",
                "client_action_id": "legacy-short-alias-start-0001",
                "state_version": session.state_version,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
            },
        )
        self.assertEqual(200, started.status_code, started.text)
        conversation_id = started.json()["conversation"]["conversation_id"]

        class MemoryLeakGateway:
            def run_turn(self, context):
                return RoleTurnResult(
                    npc_id=context.npc_id,
                    dialogue="我只能谈村里的公开顾虑。",
                    memory_candidate="优盘",
                )

        self.runtime.npc_turns._gateway = MemoryLeakGateway()
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action/stream",
            headers=self.headers,
            json={
                "input_mode": "free_text",
                "client_action_id": "legacy-short-alias-turn-0001",
                "state_version": started.json()["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "吴老师，请说说村里人的真实顾虑。",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"type": "error"', response.text)
        self.assertNotIn("优盘", response.text)
        stored = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert stored is not None
        self.assertEqual([], stored.active_conversation.transcript)
        self.assertNotIn("fact_shi_usb", stored.known_fact_ids)
        self.assertEqual(
            (),
            self.runtime.npc_memories._repository.active_for_npc(
                self.session_id, "npc_wu_xiuying", 2
            ),
        )
        review = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            headers=self.headers,
        )
        self.assertNotIn("优盘", review.text)


class ActionUnificationV3PackageLifecycleTests(unittest.TestCase):
    setUp = ActionUnificationV3Tests.setUp
    _set_story_state = ActionUnificationV3Tests._set_story_state

    def test_loader_rejects_unregistered_hard_outcome_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            shutil.copytree(PACKAGE_ROOT / "pkg_gameplay_v2", package_dir)
            manifest_path = package_dir / "package_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["package_id"] = "pkg_invalid_hard_outcome_reference"
            manifest["gameplay_schema_version"] = 4
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_path = package_dir / "governance_config.json"
            config = _variant_config(json.loads(config_path.read_text(encoding="utf-8")))
            config["action_variants"][0]["hard_outcomes"] = [
                {"kind": "document", "id": "not_registered"}
            ]
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentValidationError) as caught:
                FileScriptPackageLoader().load(package_dir)
            self.assertIn("hard outcome", str(caught.exception).lower())

    def test_loader_rejects_nonzero_variant_resource_cost_without_settlement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            shutil.copytree(PACKAGE_ROOT / "pkg_gameplay_v2", package_dir)
            manifest_path = package_dir / "package_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["package_id"] = "pkg_unsettled_variant_resource_cost"
            manifest["gameplay_schema_version"] = 4
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_path = package_dir / "governance_config.json"
            config = _variant_config(json.loads(config_path.read_text(encoding="utf-8")))
            config["action_variants"][0]["resource_costs"] = ["hearing_venue"]
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentValidationError) as caught:
                FileScriptPackageLoader().load(package_dir)
            self.assertIn("resource cost", str(caught.exception).lower())

    def test_loader_rejects_enabled_variant_without_hard_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            shutil.copytree(PACKAGE_ROOT / "pkg_gameplay_v2", package_dir)
            manifest_path = package_dir / "package_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["package_id"] = "pkg_invalid_variant"
            manifest["gameplay_schema_version"] = 4
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_path = package_dir / "governance_config.json"
            config = _variant_config(json.loads(config_path.read_text(encoding="utf-8")))
            config["action_variants"][0]["hard_outcomes"] = []
            config_path.write_text(
                json.dumps(config, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ContentValidationError) as caught:
                FileScriptPackageLoader().load(package_dir)
            self.assertIn("hard outcome", str(caught.exception).lower())

    def test_repaired_content_package_is_independent_and_loadable(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_ROOT / "pkg_gameplay_v3")
        self.assertEqual("pkg_gameplay_v3", package.package_id)
        self.assertEqual(4, package.gameplay_schema_version)
        self.assertEqual(ACTION_FAMILIES, {
            item["action_id"]
            for item in package.governance_config["action_variants"]
            if item["enabled"]
        })

    def _retire_fixture_package(self) -> None:
        package = self.runtime.packages.get("pkg_action_unification_fixture")
        self.runtime.packages._items[package.package_id] = replace(
            package, status="retired"
        )

    def test_retired_session_summary_is_review_only(self) -> None:
        self._retire_fixture_package()
        sessions = self.client.get("/api/game/sessions", headers=self.headers)
        self.assertEqual(200, sessions.status_code, sessions.text)
        summary = next(
            item for item in sessions.json()["sessions"]
            if item["session_id"] == self.session_id
        )
        self.assertEqual("review_only", summary["mode"])
        self.assertTrue(summary["content_available"])
        self.assertTrue(summary["review_available"])
        self.assertTrue(summary["loadable"])
        self.assertIsNone(summary["unavailable_reason"])

    def test_retired_session_view_feed_and_review_remain_readable(self) -> None:
        self._retire_fixture_package()
        for suffix in ("", "/feed", "/review"):
            response = self.client.get(
                f"/api/game/session/{self.session_id}{suffix}", headers=self.headers
            )
            self.assertEqual(200, response.status_code, (suffix, response.text))
        view = self.client.get(
            f"/api/game/session/{self.session_id}/view", headers=self.headers
        )
        self.assertEqual(200, view.status_code, view.text)
        self.assertEqual(
            {"can_choose": False, "can_act": False, "can_end_day": False, "can_talk": False},
            view.json()["commands"],
        )

    def test_retired_session_state_changes_fail_with_package_retired(self) -> None:
        self._retire_fixture_package()
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_action_unification"
        )
        write = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            headers=self.headers,
            json={
                "client_action_id": "retired-package-write-0001",
                "state_version": session.state_version,
            },
        )
        self.assertEqual(409, write.status_code, write.text)
        self.assertEqual("PACKAGE_RETIRED", write.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
