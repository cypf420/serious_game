from __future__ import annotations

from dataclasses import replace
import re
from pathlib import Path

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.application.archive_investigation_service import investigation_definitions


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"


class TestArchiveInvestigationTransactionsV3:
    def setup_method(self) -> None:
        settings = Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(settings)
        self.client = TestClient(create_app(settings, self.runtime))
        self.account_id = "acct_archive_investigation"
        self.headers = {"X-Account-ID": self.account_id}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "archive-investigation-session-0001",
                "package_id": "pkg_gameplay_v3",
            },
        )
        assert response.status_code == 201, response.text
        self.session_id = response.json()["session_id"]
        self._set_day(2)

    def _set_day(self, story_day: int, *, action_points: int = 8) -> None:
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=story_day,
            action_points=action_points,
        )
        self.runtime.sessions.save(session, expected_version=session.state_version)

    def _archive_variant(self) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/actions",
            headers=self.headers,
        )
        assert response.status_code == 200, response.text
        return next(
            variant
            for action in response.json()["actions"]
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )

    def _inspect(self, archive_ids: list[str], *, state_version: int | None = None):
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        variant = self._archive_variant()
        return self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version if state_version is None else state_version,
                "action_kind": "inspect_archives",
                "variant_id": variant["variant_id"],
                "location_id": variant["location_choices"][0]["location_id"],
                "archive_ids": archive_ids,
            },
        )

    def test_day_unlocks_only_unread_archives_and_public_dto_explains_value(self) -> None:
        variant = self._archive_variant()
        choices = {item["target_id"]: item for item in variant["target_choices"]}

        assert {
            "archive_household_registry",
            "archive_coordination_fee_index",
            "archive_village_social_excerpt",
        }.issubset(choices)
        assert "archive_invoice_number_index" not in choices
        assert variant["participant_rules"] == {"minimum": 1, "maximum": 1}
        for archive_id in (
            "archive_household_registry",
            "archive_coordination_fee_index",
            "archive_village_social_excerpt",
        ):
            choice = choices[archive_id]
            assert choice["read_status"] == "unread"
            assert choice["first_read_cost_action_points"] == 1
            assert choice["result_fact_count"] == 1
            assert choice["strategic_uses"]

    def test_knowledge_lists_each_currently_reachable_unknown_fact_without_future_spoilers(self) -> None:
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        session.known_npc_ids.add("npc_wu_xiuying")
        session.flags.add("flag_clan_map")
        self.runtime.sessions.save(session, expected_version=session.state_version)

        response = self.client.get(
            f"/api/game/session/{self.session_id}/knowledge",
            headers=self.headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        leads = {item["fact_id"]: item for item in payload["investigation_leads"]}

        assert "fact_total_households" in leads
        assert "fact_two_million_fee" in leads
        assert "fact_clan_power_map" in leads
        assert "fact_wu_independent_voice" in leads
        assert "fact_connected_invoices" not in leads
        assert all(item["methods"] for item in leads.values())
        assert all(
            method["unlock_day"] <= 2
            for item in leads.values()
            for method in item["methods"]
        )
        assert all(
            method["fact_id"] == item["fact_id"]
            and method["source_id"]
            and method["route_type"] in {"archive", "conversation", "action"}
            for item in leads.values()
            for method in item["methods"]
        )

    def test_first_read_atomically_spends_ap_unlocks_fact_and_supports_free_reread(self) -> None:
        before = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert before is not None
        before_version = before.state_version

        response = self._inspect(["archive_coordination_fee_index"])
        assert response.status_code == 201, response.text
        payload = response.json()
        assert payload["cost_action_points"] == 1
        assert payload["read_status"] == "read"
        assert payload["strategic_uses"]
        assert [item["fact_id"] for item in payload["newly_learned_facts"]] == [
            "fact_two_million_fee"
        ]
        assert payload["fact_acquisition_bindings"] == [{
            "fact_id": "fact_two_million_fee",
            "route_type": "archive",
            "source_id": "archive_coordination_fee_index",
        }]
        assert payload["archives"][0]["read_status"] == "read"
        assert payload["archives"][0]["player_sections"]

        stored = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert stored is not None
        assert stored.game_state.action_points == 7
        assert stored.state_version == before_version + 1
        assert "fact_two_million_fee" in stored.known_fact_ids
        assert stored.archive_records[
            "archive_coordination_fee_index"
        ].read_at_days == [2]

        reread = self.client.get(
            (
                f"/api/game/session/{self.session_id}/governance/archives/"
                "archive_coordination_fee_index"
            ),
            headers=self.headers,
        )
        assert reread.status_code == 200, reread.text
        assert reread.json()["state_version"] == stored.state_version
        assert reread.json()["archive"]["read_status"] == "read"
        after_reread = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert after_reread is not None
        assert after_reread.game_state.action_points == 7
        assert after_reread.state_version == stored.state_version

    def test_household_registry_names_every_household_and_uses_player_units(self) -> None:
        response = self._inspect(["archive_household_registry"])
        assert response.status_code == 201, response.text

        sections = response.json()["archives"][0]["player_sections"]
        assert len(sections) == 36
        assert sections[0] == {
            "heading": "1. 周大山（户号 ZDS-01）",
            "body": (
                "登记4人，安置4人。合法住宅260平方米，认定宅基地240平方米，"
                "承包地4亩。权属情况：超建部分待认定。"
            ),
            "kind": "household",
        }
        assert sections[1]["heading"] == "2. 周有福（户号 ZDS-02）"
        assert sections[-1]["heading"] == "36. 邓守本（户号 DENG-01）"

        player_text = "\n".join(
            f"{section['heading']}\n{section['body']}" for section in sections
        )
        assert "260.0" not in player_text
        assert "overbuild_partly_recognized" not in player_text
        assert "registered_population" not in player_text
        assert "representative_group" not in player_text

    def test_every_authoritative_investigation_archive_returns_plain_chinese_prose(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        assert package is not None

        for definition in investigation_definitions(package):
            self._set_day(max(2, definition.unlock_day), action_points=8)
            response = self._inspect([definition.archive_id])
            assert response.status_code == 201, (
                definition.archive_id,
                response.text,
            )
            sections = response.json()["archives"][0]["player_sections"]
            assert sections, definition.archive_id
            for section in sections:
                assert section["heading"].strip(), definition.archive_id
                assert section["body"].strip(), definition.archive_id
                assert not re.search(
                    r"\b[a-z]+(?:_[a-z0-9]+)+\b",
                    f"{section['heading']} {section['body']}",
                ), (definition.archive_id, section)
                assert not re.search(
                    r"(?<![A-Za-z])\d+\.0(?!\d)",
                    f"{section['heading']} {section['body']}",
                ), (definition.archive_id, section)

    def test_repeat_and_multi_archive_requests_have_no_partial_commit(self) -> None:
        first = self._inspect(["archive_household_registry"])
        assert first.status_code == 201, first.text
        committed = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert committed is not None
        committed_points = committed.game_state.action_points
        committed_version = committed.state_version
        committed_actions = set(committed.governance_actions)

        repeated = self._inspect(
            ["archive_household_registry"], state_version=committed_version
        )
        assert repeated.status_code == 409, repeated.text
        after_repeat = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert after_repeat is not None
        assert after_repeat.game_state.action_points == committed_points
        assert after_repeat.state_version == committed_version
        assert set(after_repeat.governance_actions) == committed_actions

        multi = self._inspect(
            ["archive_coordination_fee_index", "archive_village_social_excerpt"],
            state_version=committed_version,
        )
        assert multi.status_code == 409, multi.text
        after_multi = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert after_multi is not None
        assert after_multi.game_state.action_points == committed_points
        assert after_multi.state_version == committed_version
        assert "fact_two_million_fee" not in after_multi.known_fact_ids
        assert "fact_clan_power_map" not in after_multi.known_fact_ids

    def test_sensitive_and_acceptance_period_first_read_costs_two_points(self) -> None:
        self._set_day(31)
        sensitive = self._inspect(["archive_signing_ledger_comparison"])
        assert sensitive.status_code == 201, sensitive.text
        assert sensitive.json()["cost_action_points"] == 2

        self._set_day(60, action_points=8)
        acceptance = self._inspect(["archive_resettlement_acceptance_sample"])
        assert acceptance.status_code == 201, acceptance.text
        assert acceptance.json()["cost_action_points"] == 2
