from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.disclosure_gate_service import DisclosureGateService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import RoleTurnContext, RoleTurnResult
from tests.test_doubles import DeterministicRoleLLMGateway
from serious_game_backend.infrastructure.repositories.codec import (
    decode_session,
    encode_session,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"


class FactDisclosureGateway(DeterministicRoleLLMGateway):
    def __init__(self, fact_id: str) -> None:
        super().__init__()
        self.fact_id = fact_id

    def run_turn(self, context: RoleTurnContext) -> RoleTurnResult:
        return RoleTurnResult(
            npc_id=context.npc_id,
            dialogue=f"我可以确认这项材料：{self.fact_id}。",
            disclosure_id=self.fact_id,
        )


class TestEveryClueAcquisitionPath:
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
        self.package = self.runtime.packages.get("pkg_gameplay_v3")
        assert self.package is not None
        self.account_id = "acct_all_clue_paths"
        self.headers = {"X-Account-ID": self.account_id}
        self.sequence = 0

    def _new_session(self) -> str:
        self.sequence += 1
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": f"all-clue-paths-{self.sequence:03d}",
                "package_id": "pkg_gameplay_v3",
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["session_id"]

    def _prepare_day(self, session_id: str, story_day: int, opportunity=None):
        session = self.runtime.sessions.get_owned(session_id, self.account_id)
        assert session is not None
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.game_state = replace(
            session.game_state,
            story_day=story_day,
            days_left=max(0, 90 - story_day),
            action_points=8,
        )
        if opportunity is not None:
            session.flags.update(opportunity.requires_flags)
            session.triggered_events.update(opportunity.requires_events)
            session.known_npc_ids.add(opportunity.npc_id)
            npc_state = session.npc_states[opportunity.npc_id]
            if npc_state.trust_score is not None:
                session.npc_states[opportunity.npc_id] = replace(
                    npc_state,
                    trust_score=100,
                )
        self.runtime.sessions.save(session, expected_version=session.state_version)
        return session

    def test_shi_usb_requires_and_accepts_the_registered_protection_protocol(self) -> None:
        session_id = self._new_session()
        self._prepare_day(session_id, 22)
        session = self.runtime.sessions.get_owned(session_id, self.account_id)
        assert session is not None
        opportunity = next(
            item for item in self.package.interaction_opportunities
            if item.opportunity_id == "opp_22_shi_wenbin_contact"
        )

        generic = DisclosureGateService().role_turn_boundary(
            session, self.package, opportunity,
            player_text="请把优盘交给我。",
        )
        protected = DisclosureGateService().role_turn_boundary(
            session, self.package, opportunity,
            player_text=(
                "我们换到保密安全地点谈；材料匿名登记，保护你和家人；"
                "优盘复制留痕并按正式交接清单封存。"
            ),
        )

        assert "fact_shi_usb" not in generic.gate.allowed_fact_ids
        assert "fact_shi_usb" in protected.gate.allowed_fact_ids
        assert "fact_shi_usb" in protected.required_disclosure_ids

    def test_dual_route_conversation_facts_have_targeted_first_acquisition_protocols(self) -> None:
        cases = (
            (
                "opp_16_zhao_jianguo_contact",
                "fact_connected_invoices",
                "请按发票号码逐笔核对经手人，并说明资金流向。",
            ),
            (
                "opp_16_zhao_jianguo_contact",
                "fact_two_million_fee",
                "请核对两百万协调费的原始凭证，并说明真实去处。",
            ),
            (
                "opp_20_liu_san_contact",
                "fact_original_vouchers",
                "请拿出原始凭证逐笔核对，我会保留核查底稿。",
            ),
            (
                "opp_22_shi_wenbin_contact",
                "fact_identical_reports",
                "请比较三年报告的重复数值，并说明改写经过。",
            ),
            (
                "opp_22_shi_wenbin_contact",
                "fact_eia_original",
                "请核对监测点位、采样时段和公示版本之间的差异。",
            ),
            (
                "opp_22_shi_wenbin_contact",
                "fact_lead_census",
                "我会保护受检者隐私，请核对普查人数和原始总表。",
            ),
        )
        session_id = self._new_session()
        self._prepare_day(session_id, 22)
        session = self.runtime.sessions.get_owned(session_id, self.account_id)
        assert session is not None

        for opportunity_id, fact_id, player_text in cases:
            opportunity = next(
                item for item in self.package.interaction_opportunities
                if item.opportunity_id == opportunity_id
            )
            boundary = DisclosureGateService().role_turn_boundary(
                session, self.package, opportunity, player_text=player_text,
            )
            assert fact_id in boundary.gate.allowed_fact_ids
            assert boundary.required_disclosure_ids == (fact_id,)

    def test_dual_route_conversation_facts_remain_gated_without_targeted_protocol(self) -> None:
        session_id = self._new_session()
        self._prepare_day(session_id, 22)
        session = self.runtime.sessions.get_owned(session_id, self.account_id)
        assert session is not None
        opportunity = next(
            item for item in self.package.interaction_opportunities
            if item.opportunity_id == "opp_22_shi_wenbin_contact"
        )

        boundary = DisclosureGateService().role_turn_boundary(
            session, self.package, opportunity,
            player_text="请把你知道的所有材料都告诉我。",
        )

        assert {
            "fact_identical_reports", "fact_eia_original", "fact_lead_census",
        }.isdisjoint(boundary.gate.allowed_fact_ids)

    def test_water_sample_is_acquired_only_by_registered_chain_of_custody_action(self) -> None:
        session_id = self._new_session()
        session = self._prepare_day(session_id, 22)
        parameters = {"sampling_protocol": "第三方见证并编号封存"}
        quote = self.client.post(
            f"/api/game/session/{session_id}/actions/quote",
            headers=self.headers,
            json={
                "state_version": session.state_version,
                "action_id": "third_party_water_test",
                "target_ids": [],
                "parameters": parameters,
            },
        )
        assert quote.status_code == 200, quote.text
        quotation = quote.json()
        response = self.client.post(
            f"/api/game/session/{session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "resource_action",
                "client_action_id": "water-chain-of-custody",
                "state_version": quotation["state_version"],
                "action_id": "third_party_water_test",
                "target_ids": [],
                "parameters": parameters,
                "quote_id": quotation["quote_id"],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["fact_acquisition_bindings"] == [{
            "fact_id": "fact_water_sample",
            "route_type": "action",
            "source_id": "third_party_water_test",
        }]

    def _archive_descriptor(self, session_id: str) -> dict:
        response = self.client.get(
            f"/api/game/session/{session_id}/actions",
            headers=self.headers,
        )
        assert response.status_code == 200, response.text
        return next(
            variant
            for action in response.json()["actions"]
            for variant in action["variants"]
            if variant["variant_id"] == "consult_county_archives"
        )

    def test_all_twelve_archive_paths_commit_once_and_survive_serialization(self) -> None:
        archives = {
            item.archive_id: item for item in self.package.archive_investigations
        }
        methods = [
            (fact.fact_id, method)
            for fact in self.package.facts.values()
            for method in fact.acquisition_methods
            if method["route_type"] == "archive"
        ]
        assert len(methods) == 12

        for fact_id, method in methods:
            archive = archives[str(method["source_id"])]
            session_id = self._new_session()
            before = self._prepare_day(session_id, int(method["unlock_day"]))
            descriptor = self._archive_descriptor(session_id)
            location_id = descriptor["location_choices"][0]["location_id"]
            response = self.client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=self.headers,
                json={
                    "state_version": before.state_version,
                    "action_kind": "inspect_archives",
                    "variant_id": descriptor["variant_id"],
                    "location_id": location_id,
                    "archive_ids": [archive.archive_id],
                },
            )
            assert response.status_code == 201, (fact_id, response.text)
            payload = response.json()
            learned = {
                item["fact_id"] for item in payload["newly_learned_facts"]
            }
            assert fact_id in learned, (fact_id, archive.archive_id)

            committed = self.runtime.sessions.get_owned(session_id, self.account_id)
            assert committed is not None
            assert fact_id in committed.known_fact_ids
            assert committed.state_version == before.state_version + 1
            assert committed.game_state.action_points == 8 - payload["cost_action_points"]
            assert committed.archive_records[archive.archive_id].read_at_days == [
                int(method["unlock_day"])
            ]

            frozen = encode_session(committed)
            restored = decode_session(frozen)
            assert fact_id in restored.known_fact_ids
            assert restored.archive_records[archive.archive_id].read_at_days == [
                int(method["unlock_day"])
            ]

            repeated = self.client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=self.headers,
                json={
                    "state_version": committed.state_version,
                    "action_kind": "inspect_archives",
                    "variant_id": descriptor["variant_id"],
                    "location_id": location_id,
                    "archive_ids": [archive.archive_id],
                },
            )
            assert repeated.status_code == 409, (fact_id, repeated.text)
            after_repeat = self.runtime.sessions.get_owned(session_id, self.account_id)
            assert after_repeat is not None
            assert encode_session(after_repeat) == frozen

    def test_all_fifteen_conversation_paths_bind_npc_and_commit_disclosure(self) -> None:
        opportunities = {
            item.opportunity_id: item
            for item in self.package.interaction_opportunities
        }
        methods = [
            (fact.fact_id, method)
            for fact in self.package.facts.values()
            for method in fact.acquisition_methods
            if method["route_type"] == "conversation"
        ]
        assert len(methods) == 15

        for fact_id, method in methods:
            opportunity = opportunities[str(method["source_id"])]
            session_id = self._new_session()
            self._prepare_day(
                session_id,
                int(method["unlock_day"]),
                opportunity,
            )
            opportunities_response = self.client.get(
                f"/api/game/session/{session_id}/opportunities",
                headers=self.headers,
            )
            assert opportunities_response.status_code == 200
            public = next(
                item
                for item in opportunities_response.json()["opportunities"]
                if item["opportunity_id"] == opportunity.opportunity_id
            )
            descriptor = public["canonical_action_descriptor"]
            assert descriptor is not None, (fact_id, opportunity.opportunity_id)

            current = self.runtime.sessions.get_owned(session_id, self.account_id)
            assert current is not None
            forged_target = next(
                item.npc_id
                for item in self.package.npc_profiles
                if item.npc_id != opportunity.npc_id
            )
            request = {
                "state_version": current.state_version,
                "action_kind": descriptor["action_id"],
                "variant_id": descriptor["variant_id"],
                "location_id": descriptor["preselected_location_id"],
                "target_ids": [opportunity.npc_id],
                "topic": descriptor["canonical_topic"],
                "opportunity_id": opportunity.opportunity_id,
            }
            before_forgery = encode_session(current)
            forged = self.client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=self.headers,
                json={**request, "target_ids": [forged_target]},
            )
            assert forged.status_code == 409, (fact_id, forged.text)
            after_forgery = self.runtime.sessions.get_owned(
                session_id, self.account_id
            )
            assert after_forgery is not None
            assert encode_session(after_forgery) == before_forgery

            started = self.client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=self.headers,
                json=request,
            )
            assert started.status_code == 201, (fact_id, started.text)
            action_id = started.json()["action"]["action_instance_id"]
            self.runtime.npc_turns._gateway = FactDisclosureGateway(fact_id)
            turn = self.client.post(
                (
                    f"/api/game/session/{session_id}/governance/actions/"
                    f"{action_id}/turn"
                ),
                headers=self.headers,
                json={
                    "state_version": started.json()["state_version"],
                    "player_text": "你好",
                },
            )
            assert turn.status_code == 200, (fact_id, turn.text)
            committed = self.runtime.sessions.get_owned(session_id, self.account_id)
            assert committed is not None
            assert fact_id in committed.known_fact_ids
            restored = decode_session(encode_session(committed))
            assert fact_id in restored.known_fact_ids

    def test_every_fact_lead_exposes_structured_current_route_without_future_ids(self) -> None:
        opportunities = {
            item.opportunity_id: item
            for item in self.package.interaction_opportunities
        }
        for fact in self.package.facts.values():
            first_day = min(
                int(method["unlock_day"])
                for method in fact.acquisition_methods
            )
            if first_day > 1:
                before_id = self._new_session()
                self._prepare_day(before_id, first_day - 1)
                before = self.client.get(
                    f"/api/game/session/{before_id}/knowledge",
                    headers=self.headers,
                )
                assert before.status_code == 200
                assert fact.fact_id not in {
                    item["fact_id"]
                    for item in before.json()["investigation_leads"]
                }

            first_methods = [
                method
                for method in fact.acquisition_methods
                if int(method["unlock_day"]) == first_day
            ]
            opportunity = next(
                (
                    opportunities[str(method["source_id"])]
                    for method in first_methods
                    if method["route_type"] == "conversation"
                ),
                None,
            )
            current_id = self._new_session()
            self._prepare_day(current_id, first_day, opportunity)
            response = self.client.get(
                f"/api/game/session/{current_id}/knowledge",
                headers=self.headers,
            )
            assert response.status_code == 200
            lead = next(
                item
                for item in response.json()["investigation_leads"]
                if item["fact_id"] == fact.fact_id
            )
            assert {
                (method["fact_id"], method["route_type"], method["source_id"])
                for method in lead["methods"]
            } == {
                (fact.fact_id, str(method["route_type"]), str(method["source_id"]))
                for method in first_methods
            }
            serialized = json.dumps(lead, ensure_ascii=False)
            assert "requires_flags" not in serialized
            assert "requires_events" not in serialized
            assert all(
                int(method["unlock_day"]) <= first_day
                for method in lead["methods"]
            )
