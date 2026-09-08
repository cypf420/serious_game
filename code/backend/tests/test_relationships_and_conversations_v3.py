from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.npc_memory_service import NPCMemoryService
from serious_game_backend.application.npc_demand_service import NPCDemandService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.conversation import CompletedConversation
from serious_game_backend.domain.llm import RoleTurnContext
from tests.test_doubles import DeterministicRoleLLMGateway
from serious_game_backend.infrastructure.repositories.codec import (
    decode_session,
    encode_session,
)
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryNPCMemoryRepository,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"


def run_authoritative_wu_conversation(
    test: unittest.TestCase,
    *,
    runtime,
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    account_id: str,
    suffix: str,
) -> dict:
    session = runtime.sessions.get_owned(session_id, account_id)
    session.pending_decision = None
    session.pending_decision_queue.clear()
    session.flags.add("flag_clan_map")
    session.game_state = replace(session.game_state, story_day=2)
    session.npc_demand_states["demand_wu_xiuying"]["due_day"] = 60
    session.append_narrative(
        story_day=2,
        kind="narration",
        text="吴秀英已在本段剧情中正式出现。",
    )
    runtime.sessions.save(session, expected_version=session.state_version)

    started = client.post(
        f"/api/game/session/{session_id}/action",
        headers=headers,
        json={
            "input_mode": "conversation_start",
            "client_action_id": f"authoritative-start-{suffix}",
            "state_version": session.state_version,
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        },
    )
    test.assertEqual(200, started.status_code, started.text)
    conversation_id = started.json()["conversation"]["conversation_id"]
    turn = client.post(
        f"/api/game/session/{session_id}/action",
        headers=headers,
        json={
            "input_mode": "free_text",
            "client_action_id": f"authoritative-turn-{suffix}",
            "state_version": started.json()["state_version"],
            "conversation_id": conversation_id,
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
            "player_text": "请把村里的真实情况说清楚。",
        },
    )
    test.assertEqual(200, turn.status_code, turn.text)
    ended = client.post(
        f"/api/game/session/{session_id}/action",
        headers=headers,
        json={
            "input_mode": "conversation_end",
            "client_action_id": f"authoritative-end-{suffix}",
            "state_version": turn.json()["state_version"],
            "conversation_id": conversation_id,
        },
    )
    test.assertEqual(200, ended.status_code, ended.text)
    test.assertEqual("completed", ended.json()["completion_status"])
    return ended.json()


class RelationshipAndConversationV3Tests(unittest.TestCase):
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
        self.headers = {"X-Account-ID": "acct_relationship_v3"}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "relationship-v3-session-0001",
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]

    def _set_story_state(
        self,
        *,
        day: int,
        flags: set[str] | None = None,
        presented_names: tuple[str, ...] = (),
    ) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.flags = set(flags or ())
        session.game_state = replace(session.game_state, story_day=day)
        for name in presented_names:
            session.append_narrative(
                story_day=day,
                kind="narration",
                text=f"{name}已在本段剧情中正式出现。",
            )
        self.runtime.sessions.save(
            session, expected_version=session.state_version
        )

    def _opportunities(self) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/opportunities",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def _field_visit_variant(self) -> dict:
        response = self.client.get(
            f"/api/game/session/{self.session_id}/actions",
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return next(
            variant
            for action in response.json()["actions"]
            for variant in action["variants"]
            if variant["variant_id"] == "field_visit"
        )

    def _field_visit_targets(self) -> set[str]:
        field_visit = self._field_visit_variant()
        return {item["target_id"] for item in field_visit["target_choices"]}

    def test_dossier_mention_does_not_fake_contact_or_bypass_he_tiezhu_gate(
        self,
    ) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        session.pending_decision = None
        session.pending_decision_queue.clear()
        self.runtime.sessions.save(session, expected_version=session.state_version)

        body = self._opportunities()
        he = next(
            item for item in body["people"]
            if item["npc_id"] == "npc_he_tiezhu"
        )
        self.assertEqual("mentioned", he.get("discovery_state"))
        self.assertEqual("known", he["contact_state"])
        self.assertEqual(
            {"trust_band": "not_assessed", "attitude_band": "not_assessed", "anxiety_band": "not_assessed"},
            {key: he[key] for key in ("trust_band", "attitude_band", "anxiety_band")},
        )
        self.assertTrue(all(
            "尚未与此人直接接触" in reason
            for reason in he["relationship_reasons"].values()
        ))
        self.assertNotIn("npc_he_tiezhu", self._field_visit_targets())
        self.assertFalse(self._field_visit_variant()["available"])
        self.assertEqual(
            "尚无已经正式接触的可选对象",
            self._field_visit_variant()["unavailable_reason"],
        )

        before = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        rejected = self.client.post(
            f"/api/game/session/{self.session_id}/governance/actions",
            headers=self.headers,
            json={
                "state_version": before.state_version,
                "action_kind": "household_visit",
                "variant_id": "field_visit",
                "location_id": "loc_liulin_village",
                "target_ids": ["npc_he_tiezhu"],
                "topic": "第一日提前走访何铁柱",
            },
        )
        self.assertEqual(409, rejected.status_code, rejected.text)
        after = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        self.assertEqual(before.state_version, after.state_version)
        self.assertEqual(before.game_state.action_points, after.game_state.action_points)
        self.assertEqual(before.governance_actions, after.governance_actions)

        after.game_state = replace(after.game_state, story_day=15)
        package = self.runtime.packages.get("pkg_gameplay_v3")
        NPCDemandService.sync(after, package)
        self.runtime.sessions.save(after, expected_version=after.state_version)
        governance = self.client.get(
            f"/api/game/session/{self.session_id}/governance",
            headers=self.headers,
        )
        self.assertEqual(200, governance.status_code, governance.text)
        self.assertNotIn(
            "npc_he_tiezhu",
            {item["npc_id"] for item in governance.json()["npc_demands"]},
        )

        after = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        after.game_state = replace(after.game_state, story_day=56)
        self.runtime.sessions.save(after, expected_version=after.state_version)
        opened = self._opportunities()
        he = next(
            item for item in opened["people"]
            if item["npc_id"] == "npc_he_tiezhu"
        )
        self.assertEqual("contactable", he.get("discovery_state"))
        self.assertEqual("contactable", he["contact_state"])
        self.assertIn("npc_he_tiezhu", self._field_visit_targets())
        self.assertTrue(self._field_visit_variant()["available"])

    def _start_and_end_wu_conversation(self, suffix: str) -> str:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        started = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "conversation_start",
                "client_action_id": f"conversation-start-{suffix}",
                "state_version": session.state_version,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
            },
        )
        self.assertEqual(200, started.status_code, started.text)
        conversation_id = started.json()["conversation"]["conversation_id"]
        ended = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            headers=self.headers,
            json={
                "input_mode": "free_text",
                "client_action_id": f"conversation-turn-{suffix}",
                "state_version": started.json()["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "你必须配合，马上签。",
            },
        )
        self.assertEqual(200, ended.status_code, ended.text)
        self.assertEqual("ended", ended.json()["conversation"]["status"])
        return conversation_id

    def test_unknown_known_contactable_transitions_hide_every_target_surface(self) -> None:
        self._set_story_state(day=59)
        unknown = self._opportunities()
        self.assertNotIn("npc_gu_keming", json.dumps(unknown, ensure_ascii=False))
        map_body = self.client.get(
            f"/api/game/session/{self.session_id}/map", headers=self.headers
        ).json()
        governance = self.client.get(
            f"/api/game/session/{self.session_id}/governance",
            headers=self.headers,
        ).json()
        self.assertNotIn(
            "npc_gu_keming",
            json.dumps({"map": map_body, "governance": governance}, ensure_ascii=False),
        )

        self._set_story_state(day=58, presented_names=("顾克明",))
        known = self._opportunities()
        person = next(
            item for item in known["people"] if item["npc_id"] == "npc_gu_keming"
        )
        self.assertEqual("known", person["contact_state"])
        self.assertNotIn(
            "npc_gu_keming",
            {item["npc_id"] for item in known["opportunities"]},
        )

        self._set_story_state(day=59, presented_names=("顾克明",))
        contactable = self._opportunities()
        person = next(
            item
            for item in contactable["people"]
            if item["npc_id"] == "npc_gu_keming"
        )
        self.assertEqual("contactable", person["contact_state"])
        self.assertIn(
            "npc_gu_keming",
            {item["npc_id"] for item in contactable["opportunities"]},
        )

    def test_people_dto_uses_qualitative_bands_and_leaks_no_private_state(self) -> None:
        self._set_story_state(
            day=2,
            flags={"flag_clan_map"},
            presented_names=("吴秀英", "王芳"),
        )
        body = self._opportunities()
        self.assertIn("people", body)
        person = next(
            item for item in body["people"] if item["npc_id"] == "npc_wu_xiuying"
        )
        self.assertEqual("contactable", person["contact_state"])
        self.assertIn(person["trust_band"], {"closed", "guarded", "working", "trusted"})
        self.assertIn(
            person["attitude_band"],
            {"hostile", "resistant", "neutral", "cooperative", "supportive"},
        )
        self.assertIn(
            person["anxiety_band"],
            {"calm", "uneasy", "worried", "strained", "critical"},
        )
        self.assertLessEqual(len(person["recent_change_reasons"]), 3)
        media_contact = next(
            item for item in body["people"] if item["npc_id"] == "npc_wang_fang"
        )
        self.assertEqual("known", media_contact["contact_state"])
        self.assertEqual("not_assessed", media_contact["trust_band"])
        serialized = json.dumps(body, ensure_ascii=False)
        for forbidden in (
            "trust_score",
            "attitude_score",
            "anxiety_score",
            "big_five",
            "hidden_demand",
            "hidden_relation",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_fake_role_behavior_changes_with_safe_qualitative_context(self) -> None:
        gateway = DeterministicRoleLLMGateway()
        base = RoleTurnContext(
            session_id="sess_context",
            npc_id="npc_wu_xiuying",
            player_text="我想听听你的看法。",
            story_day=2,
            opportunity_id="opp_context",
        )
        guarded = gateway.run_turn(replace(
            base,
            visible_world_context={
                "relationship_context": {
                    "trust_band": "guarded",
                    "attitude_band": "resistant",
                    "anxiety_band": "worried",
                }
            },
        ))
        trusted = gateway.run_turn(replace(
            base,
            visible_world_context={
                "relationship_context": {
                    "trust_band": "trusted",
                    "attitude_band": "cooperative",
                    "anxiety_band": "calm",
                }
            },
        ))
        self.assertNotEqual(guarded.dialogue, trusted.dialogue)
        combined = guarded.dialogue + trusted.dialogue
        self.assertNotIn("40", combined)
        self.assertNotIn("trust_score", combined)

    def test_completed_conversations_paginate_filter_and_enforce_ownership(self) -> None:
        self._set_story_state(
            day=2,
            flags={"flag_clan_map"},
            presented_names=("吴秀英",),
        )
        ids = [
            self._start_and_end_wu_conversation("one"),
            self._start_and_end_wu_conversation("two"),
        ]
        first = self.client.get(
            f"/api/game/session/{self.session_id}/conversations?limit=1",
            headers=self.headers,
        )
        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual([ids[0]], [item["conversation_id"] for item in first.json()["items"]])
        self.assertIsNotNone(first.json()["next_cursor"])
        transcript = first.json()["items"][0]["transcript"]
        self.assertEqual(
            ["player", "npc"],
            [item["speaker_type"] for item in transcript],
        )

        second = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
            headers=self.headers,
        )
        self.assertEqual(200, second.status_code, second.text)
        self.assertEqual(ids[1], second.json()["items"][0]["conversation_id"])
        filtered = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            params={"npc_id": "npc_wu_xiuying", "story_day": 2},
            headers=self.headers,
        )
        self.assertEqual(2, len(filtered.json()["items"]))
        invalid = self.client.get(
            f"/api/game/session/{self.session_id}/conversations?cursor=not-a-cursor",
            headers=self.headers,
        )
        self.assertEqual(422, invalid.status_code, invalid.text)
        invalid_filter = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            params={"npc_id": "npc_not_in_this_package"},
            headers=self.headers,
        )
        self.assertEqual(422, invalid_filter.status_code, invalid_filter.text)
        other = self.client.get(
            f"/api/game/session/{self.session_id}/conversations",
            headers={"X-Account-ID": "acct_other"},
        )
        self.assertEqual(404, other.status_code, other.text)

    def test_commitment_memory_is_durable_while_episode_expires(self) -> None:
        repository = InMemoryNPCMemoryRepository()
        service = NPCMemoryService(
            repository,
            compression_threshold=3,
            ttl_days=2,
        )
        episode = service.record(
            session_id="sess_memory",
            account_id="acct_memory",
            npc_id="npc_wu_xiuying",
            operation_id="op_episode",
            story_day=2,
            candidate="吴秀英记得县长今天认真听完了她的意见。",
        )
        commitment = service.record(
            session_id="sess_memory",
            account_id="acct_memory",
            npc_id="npc_wu_xiuying",
            operation_id="op_commitment",
            story_day=2,
            candidate="吴秀英承诺在D60前介绍周大山，当前尚未兑现。",
        )
        disclosure = service.record(
            session_id="sess_memory",
            account_id="acct_memory",
            npc_id="npc_wu_xiuying",
            operation_id="op_disclosure",
            story_day=2,
            candidate="吴秀英披露了周家账本的存放位置。",
        )
        relationship = service.record(
            session_id="sess_memory",
            account_id="acct_memory",
            npc_id="npc_wu_xiuying",
            operation_id="op_relationship",
            story_day=2,
            candidate="吴秀英说明这次关系转折已经发生。",
        )
        self.assertEqual("episode", episode.memory_type)
        self.assertEqual("commitment", commitment.memory_type)
        self.assertEqual(90, commitment.expires_after_day)
        self.assertEqual("npc_wu_xiuying", commitment.actor_id)
        self.assertEqual(60, commitment.due_day)
        self.assertEqual("unresolved", commitment.resolution_state)
        self.assertEqual("disclosure", disclosure.memory_type)
        self.assertEqual(90, disclosure.expires_after_day)
        self.assertEqual("observed", disclosure.resolution_state)
        self.assertEqual("relationship", relationship.memory_type)
        self.assertEqual("observed", relationship.resolution_state)
        context = service.context(
            session_id="sess_memory",
            npc_id="npc_wu_xiuying",
            story_day=2,
            query="周大山",
        )
        self.assertEqual((commitment.content,), context["unresolved_commitments"])
        durable_at_d90 = service.retrieve(
            session_id="sess_memory",
            npc_id="npc_wu_xiuying",
            story_day=90,
            query="介绍周大山",
        )
        self.assertIn(commitment.content, durable_at_d90)
        self.assertIn(disclosure.content, durable_at_d90)
        self.assertIn(relationship.content, durable_at_d90)
        self.assertNotIn(episode.content, durable_at_d90)

        for index in range(2):
            service.record(
                session_id="sess_memory",
                account_id="acct_memory",
                npc_id="npc_wu_xiuying",
                operation_id=f"op_episode_{index}",
                story_day=2,
                candidate=f"第{index + 2}次交谈继续核对补偿规矩。",
            )
        summary = next(
            item
            for item in repository.active_for_npc(
                "sess_memory", "npc_wu_xiuying", 2
            )
            if item.memory_type == "summary"
        )
        self.assertEqual("npc_wu_xiuying", summary.actor_id)
        self.assertIn("内容:", summary.commitment_content)
        self.assertIsNone(summary.due_day)
        self.assertEqual("observed", summary.resolution_state)

    def test_snapshot_codec_defaults_and_round_trips_relationship_state(self) -> None:
        session = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        legacy = encode_session(session)
        legacy.pop("known_npc_ids", None)
        legacy.pop("encountered_npc_ids", None)
        legacy.pop("contactable_npc_ids", None)
        legacy.pop("relationship_edges", None)
        legacy.pop("completed_conversations", None)
        restored_legacy = decode_session(legacy)
        self.assertEqual(set(), restored_legacy.known_npc_ids)
        self.assertEqual(set(), restored_legacy.encountered_npc_ids)
        self.assertEqual(set(), restored_legacy.contactable_npc_ids)
        self.assertEqual([], restored_legacy.relationship_edges)
        self.assertEqual([], restored_legacy.completed_conversations)

        session.known_npc_ids = {"npc_wu_xiuying"}
        session.encountered_npc_ids = {"npc_wu_xiuying"}
        session.contactable_npc_ids = {"npc_wu_xiuying"}
        session.relationship_edges = [{
            "edge_id": "rel_wu_zhou",
            "source_npc_id": "npc_wu_xiuying",
            "target_npc_id": "npc_zhou_dashan",
            "visibility": "suspected",
            "discovery_reason": "吴秀英提到村庄关系",
            "discovery_day": 2,
        }]
        round_trip = decode_session(encode_session(session))
        self.assertEqual(session.known_npc_ids, round_trip.known_npc_ids)
        self.assertEqual(
            session.encountered_npc_ids, round_trip.encountered_npc_ids
        )
        self.assertEqual(session.contactable_npc_ids, round_trip.contactable_npc_ids)
        self.assertEqual(session.relationship_edges, round_trip.relationship_edges)

    def test_v3_config_registers_all_five_relationship_subnetworks(self) -> None:
        package = self.runtime.packages.get("pkg_gameplay_v3")
        subnetworks = {
            item.get("subnetwork") for item in package.npc_relationships
        }
        self.assertEqual(
            {
                "county_government",
                "corporate_corruption",
                "village_clan",
                "environmental_evidence",
                "external_oversight",
            },
            subnetworks,
        )

    def test_manual_save_load_restores_task2_state_and_durable_metadata(self) -> None:
        ended = run_authoritative_wu_conversation(
            self,
            runtime=self.runtime,
            client=self.client,
            headers=self.headers,
            session_id=self.session_id,
            account_id="acct_relationship_v3",
            suffix="manual-restore",
        )
        before = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        expected_known = set(before.known_npc_ids)
        expected_encountered = set(before.encountered_npc_ids)
        expected_contactable = set(before.contactable_npc_ids)
        expected_edges = [dict(item) for item in before.relationship_edges]
        expected_transcript = tuple(
            dict(item) for item in before.completed_conversations[0].transcript
        )
        self.assertIn("npc_wu_xiuying", expected_known)
        self.assertTrue(expected_contactable)
        self.assertTrue(any(
            item["edge_id"] == "rel_wu_zhou_village"
            and item["visibility"] == "confirmed"
            for item in expected_edges
        ))

        saved = self.client.post(
            f"/api/game/session/{self.session_id}/manual-saves",
            headers=self.headers,
            json={
                "client_action_id": "task2-manual-save-restore",
                "state_version": ended["state_version"],
                "slot_number": 1,
                "display_name": "Task 2 state",
                "overwrite": False,
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)

        before.known_npc_ids.clear()
        before.encountered_npc_ids.clear()
        before.contactable_npc_ids.clear()
        before.relationship_edges.clear()
        before.completed_conversations.clear()
        self.runtime.sessions.save(
            before, expected_version=before.state_version
        )
        loaded = self.client.post(
            f"/api/game/session/{self.session_id}/load-snapshot",
            headers=self.headers,
            json={
                "client_action_id": "task2-manual-load-restore",
                "state_version": ended["state_version"],
                "snapshot_id": saved.json()["snapshot_id"],
                "confirmed": True,
            },
        )
        self.assertEqual(200, loaded.status_code, loaded.text)
        restored = self.runtime.sessions.get_owned(
            self.session_id, "acct_relationship_v3"
        )
        self.assertEqual(expected_known, restored.known_npc_ids)
        self.assertEqual(expected_encountered, restored.encountered_npc_ids)
        self.assertEqual(expected_contactable, restored.contactable_npc_ids)
        self.assertEqual(expected_edges, restored.relationship_edges)
        self.assertEqual(
            expected_transcript,
            restored.completed_conversations[0].transcript,
        )
        durable = self.runtime.npc_memories._repository.active_for_npc(
            self.session_id, "npc_wu_xiuying", 90
        )
        self.assertEqual(
            {"disclosure", "relationship", "demand"},
            {item.memory_type for item in durable},
        )
        demand = next(item for item in durable if item.memory_type == "demand")
        self.assertEqual(60, demand.due_day)
        self.assertEqual("unresolved", demand.resolution_state)


class RelationshipSqliteRestartTests(unittest.TestCase):
    def test_authoritative_turn_memories_survive_through_d90_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "authoritative-memory.sqlite3"
            settings = Settings(
                environment="test",
                content_root=PACKAGE_ROOT,
                default_package_id="pkg_gameplay_v3",
                repository="sqlite",
                database_path=database_path,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            client = TestClient(create_app(settings, runtime))
            headers = {"X-Account-ID": "acct_authoritative_memory"}
            created = client.post(
                "/api/game/session",
                headers=headers,
                json={
                    "client_request_id": "authoritative-memory-session",
                    "package_id": "pkg_gameplay_v3",
                },
            )
            self.assertEqual(201, created.status_code, created.text)
            session_id = created.json()["session_id"]
            run_authoritative_wu_conversation(
                self,
                runtime=runtime,
                client=client,
                headers=headers,
                session_id=session_id,
                account_id="acct_authoritative_memory",
                suffix="sqlite-restart",
            )

            restarted = build_container(settings)
            durable = restarted.npc_memories._repository.active_for_npc(
                session_id, "npc_wu_xiuying", 90
            )
            self.assertEqual(
                {"disclosure", "relationship", "demand"},
                {item.memory_type for item in durable},
            )
            by_type = {item.memory_type: item for item in durable}
            self.assertTrue(all(item.expires_after_day == 90 for item in durable))
            self.assertTrue(all(
                item.actor_id == "npc_wu_xiuying" for item in durable
            ))
            self.assertIn("柳林村宗族权力图", by_type["disclosure"].content)
            self.assertEqual("observed", by_type["disclosure"].resolution_state)
            self.assertEqual("observed", by_type["relationship"].resolution_state)
            self.assertIn("公开底账", by_type["demand"].content)
            self.assertEqual(60, by_type["demand"].due_day)
            self.assertEqual("unresolved", by_type["demand"].resolution_state)

    def test_new_snapshot_fields_survive_sqlite_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "runtime.sqlite3"
            settings = Settings(
                environment="test",
                content_root=PACKAGE_ROOT,
                default_package_id="pkg_gameplay_v3",
                repository="sqlite",
                database_path=database_path,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            client = TestClient(create_app(settings, runtime))
            headers = {"X-Account-ID": "acct_sqlite_relationship"}
            created = client.post(
                "/api/game/session",
                headers=headers,
                json={
                    "client_request_id": "sqlite-relationship-session-0001",
                    "package_id": "pkg_gameplay_v3",
                },
            )
            self.assertEqual(201, created.status_code, created.text)
            session_id = created.json()["session_id"]
            session = runtime.sessions.get_owned(
                session_id, "acct_sqlite_relationship"
            )
            session.known_npc_ids = {"npc_wu_xiuying"}
            session.contactable_npc_ids = {"npc_wu_xiuying"}
            session.relationship_edges = [{
                "edge_id": "rel_restart",
                "source_npc_id": "npc_wu_xiuying",
                "target_npc_id": "npc_zhou_dashan",
                "visibility": "confirmed",
                "discovery_reason": "会谈确认",
                "discovery_day": 2,
            }]
            session.completed_conversations = [CompletedConversation(
                conversation_id="conv_restart",
                opportunity_id="opp_restart",
                npc_id="npc_wu_xiuying",
                story_day=2,
                start_reason="story_window",
                end_reason="player_exit",
                completion_status="completed",
                transcript=(
                    {"speaker": "player", "text": "请把情况讲完整。"},
                    {"speaker": "npc", "text": "我从头说。"},
                ),
                started_at="2026-01-01T00:00:00+00:00",
                ended_at="2026-01-01T00:01:00+00:00",
            )]
            runtime.sessions.save(session, expected_version=session.state_version)
            runtime.npc_memories.record(
                session_id=session_id,
                account_id="acct_sqlite_relationship",
                npc_id="npc_wu_xiuying",
                operation_id="op_memory_restart",
                story_day=2,
                candidate="吴秀英承诺在D60前介绍周大山，当前尚未兑现。",
            )

            restarted = build_container(settings)
            restored = restarted.sessions.get_owned(
                session_id, "acct_sqlite_relationship"
            )
            self.assertEqual({"npc_wu_xiuying"}, restored.known_npc_ids)
            self.assertEqual({"npc_wu_xiuying"}, restored.contactable_npc_ids)
            self.assertEqual("confirmed", restored.relationship_edges[0]["visibility"])
            self.assertEqual(
                "我从头说。",
                restored.completed_conversations[0].transcript[1]["text"],
            )
            durable = restarted.npc_memories._repository.active_for_npc(
                session_id, "npc_wu_xiuying", 90
            )
            self.assertEqual(1, len(durable))
            self.assertEqual("commitment", durable[0].memory_type)
            self.assertEqual(60, durable[0].due_day)
            self.assertEqual("unresolved", durable[0].resolution_state)


if __name__ == "__main__":
    unittest.main()
