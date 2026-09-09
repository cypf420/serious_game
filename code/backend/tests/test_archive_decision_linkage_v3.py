from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import pytest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.story_flow_service import StoryFlowService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"


class TestArchiveDecisionLinkageV3:
    @pytest.mark.parametrize("decision_id", ["dp2_01", "dp2_04", "dp3_02", "dp4_01", "dp4_08", "dp4_10", "dp5_06", "dp6_09", "dp6_10"])
    def test_reading_required_archives_refreshes_pending_options(self, decision_id):
        session, package = self._session_package()
        session.pending_decision = None
        session.known_fact_ids = set()
        target = next(o for o in package.decisions[decision_id].options if o.required_fact_ids)
        session.flags.update(target.required_flags | target.required_any_flags)
        session.game_state = replace(session.game_state, story_day=package.decisions[decision_id].story_day, action_points=8)
        StoryFlowService()._present_decision_id(session, package, decision_id)
        pending = session.pending_decision
        self.runtime.sessions.save(session, expected_version=session.state_version)
        original_logs = len(session.logs)
        assert target.option_id not in pending.option_ids
        for fact_id in sorted(target.required_fact_ids):
            actions = self.client.get(f"/api/game/session/{self.session_id}/actions", headers=self.headers).json()["actions"]
            archive = next(a for a in package.archive_investigations if fact_id in a.result_fact_ids)
            variant = next(v for a in actions if a["action_id"] == "inspect_archives" for v in a["variants"] if any(t["target_id"] == archive.archive_id for t in v["target_choices"]))
            response = self.client.post(f"/api/game/session/{self.session_id}/governance/actions", headers=self.headers, json={
                "state_version": session.state_version,
                "action_kind": "inspect_archives", "variant_id": variant["variant_id"],
                "location_id": variant["location_choices"][0]["location_id"],
                "archive_ids": [archive.archive_id],
            })
            assert response.status_code == 201, response.text
            session, _ = self._session_package()
            if not target.required_fact_ids.issubset(session.known_fact_ids):
                assert target.option_id not in response.json()["visible_state"]["pending_decision"]["option_ids"]
        updated = response.json()["visible_state"]["pending_decision"]
        assert target.option_id in updated["option_ids"]
        assert next(o for o in updated["options"] if o["option_id"] == target.option_id)["available"]
        assert updated["event_instance_id"] == pending.event_instance_id
        assert updated["presentation_entry_id"] == pending.presentation_entry_id
        assert len([log for log in session.logs[original_logs:] if log.get("type") == "decision_presented"]) == 0
        accepted = self.client.post(f"/api/game/session/{self.session_id}/action", headers=self.headers, json={
            "input_mode": "decision", "client_action_id": f"archive-unlock-{decision_id}",
            "state_version": session.state_version, "decision_id": decision_id, "option_id": target.option_id,
        })
        assert accepted.status_code == 200, accepted.text

    @pytest.mark.parametrize("read_view", [False, True])
    def test_existing_save_with_stale_pending_snapshot_accepts_known_evidence(self, read_view):
        session, package = self._session_package()
        session.pending_decision = None
        session.known_fact_ids = set()
        session.game_state = replace(session.game_state, story_day=57)
        StoryFlowService()._present_decision_id(session, package, "dp4_08")
        assert "a" not in session.pending_decision.option_ids
        session.known_fact_ids.add("fact_lead_census")
        self.runtime.sessions.save(session, expected_version=session.state_version)
        if read_view:
            view = self.client.get(f"/api/game/session/{self.session_id}/view", headers=self.headers)
            assert view.status_code == 200, view.text
            assert "a" in view.json()["state"]["pending_decision"]["option_ids"]
            stored, _ = self._session_package()
            assert "a" not in stored.pending_decision.option_ids  # GET remains pure.
        result = self.client.post(f"/api/game/session/{self.session_id}/action", headers=self.headers, json={
            "input_mode": "decision", "client_action_id": "old-save-unlock-0001",
            "state_version": session.state_version, "decision_id": "dp4_08", "option_id": "a",
        })
        assert result.status_code == 200, result.text

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
        self.account_id = "acct_archive_linkage"
        self.headers = {"X-Account-ID": self.account_id}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "archive-linkage-session-0001",
                "package_id": "pkg_gameplay_v3",
            },
        )
        assert response.status_code == 201, response.text
        self.session_id = response.json()["session_id"]

    def _session_package(self):
        session = self.runtime.sessions.get_owned(self.session_id, self.account_id)
        assert session is not None
        package = self.runtime.packages.get("pkg_gameplay_v3")
        return session, package

    def _present(self, decision_id: str, *, known_fact_ids: set[str]) -> object:
        session, package = self._session_package()
        decision = package.decisions[decision_id]
        session.pending_decision = None
        session.known_fact_ids = set(known_fact_ids)
        session.game_state = replace(
            session.game_state,
            story_day=decision.story_day,
        )
        StoryFlowService()._present_decision_id(session, package, decision_id)
        assert session.pending_decision is not None
        return session.pending_decision

    def test_evidence_option_stays_visible_with_safe_archive_requirement(self) -> None:
        pending = self._present("dp2_01", known_fact_ids=set())
        option = next(item for item in pending.options if item.option_id == "a")

        assert option.available is False
        assert "a" not in pending.option_ids
        assert option.unlock_requirements == ({
            "archive_name": "发票登记与编号索引",
            "reason": "专项审计需要先形成连号发票的书面依据；也可通过正式接触取得同一事实。",
        },)
        assert "《发票登记与编号索引》" in option.unavailable_reason
        assert "正式接触" in option.unavailable_reason
        assert any(item.available for item in pending.options)

    def test_same_fact_from_archive_or_formal_contact_unlocks_option(self) -> None:
        pending = self._present(
            "dp2_01",
            known_fact_ids={"fact_connected_invoices"},
        )
        option = next(item for item in pending.options if item.option_id == "a")

        assert option.available is True
        assert option.unavailable_reason is None
        assert "a" in pending.option_ids

    def test_known_archive_fact_is_available_as_conversation_material(self) -> None:
        session, package = self._session_package()
        session.known_fact_ids.add("fact_clan_power_map")
        session.flags.add("flag_clan_map")
        session.pending_decision = None
        session.game_state = replace(session.game_state, story_day=2)
        session.known_npc_ids.add("npc_wu_xiuying")
        session.encountered_npc_ids.add("npc_wu_xiuying")
        session.contactable_npc_ids.add("npc_wu_xiuying")
        self.runtime.sessions.save(session, expected_version=session.state_version)

        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        assert response.status_code == 200, response.text
        opportunity = next(
            item
            for item in response.json()["opportunities"]
            if item["npc_id"] == "npc_wu_xiuying"
        )
        materials = opportunity["related_materials"]

        assert any(
            item["fact_id"] == "fact_clan_power_map" for item in materials
        )
        assert all(
            item["fact_id"] in session.known_fact_ids for item in materials
            if "fact_id" in item
        )

    def test_meeting_rejects_unread_archive_then_accepts_it_after_read(self) -> None:
        session, _package = self._session_package()
        session.pending_decision = None
        session.game_state = replace(session.game_state, story_day=2, action_points=8)
        session.known_npc_ids.update({"npc_feng_jingzhi", "npc_zhao_jianguo"})
        session.encountered_npc_ids.update({"npc_feng_jingzhi", "npc_zhao_jianguo"})
        session.contactable_npc_ids.update({"npc_feng_jingzhi", "npc_zhao_jianguo"})
        self.runtime.sessions.save(session, expected_version=session.state_version)

        unread_id = "archive:doc_compensation_policy_v1"
        meeting_payload = {
            "action_kind": "leadership_meeting",
            "variant_id": "convene_leadership_meeting",
            "location_id": "loc_county_government",
            "target_ids": ["npc_feng_jingzhi", "npc_zhao_jianguo"],
            "lead_npc_id": "npc_feng_jingzhi",
            "topic": "补偿政策执行边界",
            "archive_ids": [unread_id],
            "proposed_document_type": "implementation_notice",
        }
        blocked = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={"state_version": session.state_version, **meeting_payload},
        )
        assert blocked.status_code == 409, blocked.text
        assert "查阅" in blocked.json()["error"]["message"]

        actions = self.client.get(
            f"/api/game/session/{self.session_id}/actions",
            headers=self.headers,
        ).json()["actions"]
        archive_variant = next(
            variant
            for action in actions
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )
        read = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_kind": "inspect_archives",
                "variant_id": archive_variant["variant_id"],
                "location_id": archive_variant["location_choices"][0]["location_id"],
                "archive_ids": [unread_id],
            },
        )
        assert read.status_code == 201, read.text

        accepted = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={"state_version": read.json()["state_version"], **meeting_payload},
        )
        assert accepted.status_code == 201, accepted.text
