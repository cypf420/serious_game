from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.night_simulation_service import (
    NightSimulationService,
)
from serious_game_backend.application.scripted_delta_resolver import (
    ScriptedDeltaResolver,
)
from serious_game_backend.application.scripted_effect_service import (
    ScriptedEffectService,
)
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import (
    RoleLLMResponseRetryableError,
    RoleLLMUnavailableError,
)
from serious_game_backend.domain.llm import NightAgentResult
from tests.test_doubles import DeterministicRoleLLMGateway
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tools.run_real_night_matrix import (
    FOLLOWUP_PLAN_IDS,
    STRATEGIES,
    validate_night_matrix_report,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"


class NightAgentV3ConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = FileScriptPackageLoader().load(PACKAGE_DIR)

    def test_registers_five_bounded_relationship_subnetworks(self) -> None:
        expected = {
            "county_government",
            "corporate_corruption",
            "village_clan",
            "environmental_evidence",
            "external_oversight",
        }

        self.assertEqual(expected, set(self.package.relationship_subnetworks))
        for subnetwork_id, subnetwork in self.package.relationship_subnetworks.items():
            self.assertEqual(subnetwork_id, subnetwork["subnetwork_id"])
            self.assertTrue(subnetwork["edge_ids"])
            self.assertTrue(subnetwork["allowed_propagation_topics"])
            self.assertTrue(subnetwork["relationship_visibility_requirements"])
            self.assertTrue(subnetwork["night_action_ids"])
            for edge_id in subnetwork["edge_ids"]:
                edge = next(
                    item
                    for item in self.package.npc_relationships
                    if item["edge_id"] == edge_id
                )
                self.assertEqual(subnetwork_id, edge["subnetwork"])
                self.assertNotEqual(edge["source_npc_id"], edge["target_npc_id"])
                self.assertTrue(edge["allowed_propagation_topics"])
                self.assertTrue(edge["visibility_requirements"])
                self.assertTrue(edge["night_action_ids"])

    def test_has_an_eligible_dynamic_scene_in_each_story_stage(self) -> None:
        stages = ((1, 15), (16, 30), (31, 45), (46, 60), (61, 75), (76, 89))
        scenes = self.package.night_agent_scenes

        for start, end in stages:
            matching = [
                scene
                for scene in scenes
                if start <= int(scene["story_day"]) <= end
            ]
            self.assertTrue(matching, f"missing dynamic night scene for D{start}-D{end}")
            self.assertTrue(all(scene["selection_mode"] == "autonomous" for scene in matching))
        participating = {
            subnetwork_id
            for scene in scenes
            for subnetwork_id in scene["subnetwork_ids"]
        }
        self.assertEqual(set(self.package.relationship_subnetworks), participating)

    def test_declares_exactly_the_six_published_forced_followup_plans(self) -> None:
        forced_plan_ids = {
            str(plan["plan_id"])
            for scene in self.package.night_agent_scenes
            for plan in scene.get("followup_plans", ())
            if plan.get("required_when")
        }

        self.assertEqual(
            {
                "followup_d10_county_reporting",
                "followup_d29_zhao_protection",
                "followup_d40_village_mediation",
                "followup_d55_environment",
                "followup_d70_public_oversight",
                "followup_d84_final_inspection",
            },
            forced_plan_ids,
        )
        for scene in self.package.night_agent_scenes:
            for plan in scene.get("followup_plans", ()):
                if plan.get("plan_id") not in forced_plan_ids:
                    continue
                self.assertTrue(plan.get("persuasion_context"))
                self.assertEqual(
                    set(plan.get("participant_ids", ())),
                    set(plan.get("participant_guidance", {})),
                )
                if plan.get("plan_id") == "followup_d40_village_mediation":
                    self.assertIn(
                        "不要求玩家给出剧本未提供的具体旧例名称",
                        plan["persuasion_context"],
                    )

    def test_real_matrix_contract_requires_all_six_plans_and_four_strategies(self) -> None:
        cases = [
            {
                "plan_id": plan_id,
                "strategy": strategy,
                "provider": "openai_compatible",
                "fake_calls": 0,
                "template_fallback_count": 0,
                "silent_fallback_count": 0,
                "partial_commit_count": 0,
                "triggered_legally": True,
                "model_audits": 1,
                "failed_model_audit_count": 0,
                "failed_model_audit_error_codes": {},
                "failed_calls": [],
                "transcript": [{"speaker_type": "npc", "text": "已记录。"}],
                "participant_states": [{"npc_id": "npc", "status": "active"}],
                "morning_card": "夜间结算完成。",
                "memory_check": True,
                "memory_count": 1,
                "resolved": strategy == "credible",
                "finished": strategy == "credible",
                "resolved_after_turn": 2 if strategy == "credible" else None,
            }
            for plan_id in FOLLOWUP_PLAN_IDS
            for strategy in STRATEGIES
        ]
        report = {
            "provider": "openai_compatible",
            "fake_calls": 0,
            "failed_model_audit_count": 0,
            "failed_model_audit_error_codes": {},
            "cases": cases,
            "ordinary_contact_combinations": ["scene:a->b"],
            "legal_no_contact_count": 1,
            "technical_failure_count": 1,
            "technical_failure_partial_commits": 0,
        }

        validate_night_matrix_report(report)
        with self.assertRaisesRegex(AssertionError, "24"):
            validate_night_matrix_report({**report, "cases": cases[:-1]})
        unresolved_credible = deepcopy(report)
        unresolved_credible["cases"][0]["resolved"] = False
        with self.assertRaisesRegex(AssertionError, "credible.*resolve"):
            validate_night_matrix_report(unresolved_credible)
        forgotten = deepcopy(report)
        forgotten["cases"][0]["memory_count"] = 0
        with self.assertRaisesRegex(AssertionError, "memory"):
            validate_night_matrix_report(forgotten)
        injected = deepcopy(report)
        injected_case = next(
            item for item in injected["cases"] if item["strategy"] == "injection"
        )
        injected_case["resolved"] = True
        injected_case["resolved_after_turn"] = 1
        with self.assertRaisesRegex(AssertionError, "injection"):
            validate_night_matrix_report(injected)

        rejected_injection = deepcopy(report)
        rejected_case = next(
            item
            for item in rejected_injection["cases"]
            if item["strategy"] == "injection"
        )
        rejected_case["transcript"] = []
        rejected_case["input_rejected"] = True
        rejected_case["input_rejection_message"] = "请输入与本游戏相关的话语"
        validate_night_matrix_report(rejected_injection)

        rejected_vague = deepcopy(report)
        vague_case = next(
            item for item in rejected_vague["cases"] if item["strategy"] == "vague"
        )
        vague_case["transcript"] = []
        vague_case["input_rejected"] = True
        vague_case["input_rejection_message"] = "请输入与本游戏相关的话语"
        with self.assertRaisesRegex(AssertionError, "vague.*must enter NPC judgment"):
            validate_night_matrix_report(rejected_vague)


class RecordingNightGateway(DeterministicRoleLLMGateway):
    def __init__(self, *, night_fixture: str = "legal") -> None:
        super().__init__(night_fixture=night_fixture)
        self.contexts = []

    def run_night_turn(self, context):
        self.contexts.append(context)
        return super().run_night_turn(context)


class NightAgentV3SettlementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            environment="test",
            content_root=PACKAGE_DIR.parent,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        self.runtime = build_container(self.settings)
        self.client = TestClient(create_app(self.settings, self.runtime))
        self.headers = {"X-Account-ID": "acct_night_v3"}
        response = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "night-v3-session",
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.session_id = response.json()["session_id"]
        self.package = self.runtime.packages.get("pkg_gameplay_v3")

    @staticmethod
    def _service(gateway) -> NightSimulationService:
        return NightSimulationService(
            ScriptedEffectService(ScriptedDeltaResolver()),
            night_llm=gateway,
        )

    def _session_on(self, day: int):
        session = self.runtime.sessions.get_owned(self.session_id, "acct_night_v3")
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.game_state = replace(
            session.game_state,
            story_day=day,
            days_left=91 - day,
        )
        return session

    def test_candidate_contacts_and_actions_are_derived_from_directed_one_hop_edges(self) -> None:
        gateway = RecordingNightGateway()
        session = self._session_on(10)

        self._service(gateway).run_night(session, self.package)

        contexts = {
            item.npc_id: item
            for item in gateway.contexts
            if item.phase == "contact_selection"
        }
        self.assertEqual(("npc_zhao_jianguo",), contexts["npc_sun_qiang"].counterpart_ids)
        self.assertEqual((), contexts["npc_zhao_jianguo"].counterpart_ids)
        self.assertEqual(("county_reporting",), contexts["npc_sun_qiang"].allowed_topics)
        self.assertEqual(
            ("night_hold_position",),
            tuple(item["action_id"] for item in contexts["npc_sun_qiang"].allowed_actions),
        )
        self.assertTrue(all(
            "effects" not in item and "hard_outcome_ids" not in item
            for context in contexts.values()
            for item in context.allowed_actions
        ))

    def test_required_d10_followup_uses_package_plan_and_blocks_until_completed(self) -> None:
        session = self._session_on(10)
        record = self._service(DeterministicRoleLLMGateway()).run_night(
            session, self.package
        )
        created = [item for item in record["followup_decisions"] if item["created"]]
        self.assertEqual(1, len(created))
        self.assertEqual("followup_d10_county_reporting", created[0]["plan_id"])
        self.assertEqual(1, len(session.group_conversation_queue))
        self._service(DeterministicRoleLLMGateway()).activate_next_group_conversation(session)
        self.assertIsNotNone(session.active_group_conversation)
        self.assertEqual(
            ("npc_zhao_jianguo", "npc_sun_qiang"),
            session.active_group_conversation.participant_ids,
        )
        self.assertEqual(
            "核对首阶段签约落差、县镇汇报口径和下一步责任。",
            session.active_group_conversation.agenda,
        )

    def test_package_conditions_create_required_followups_at_all_key_nights(self) -> None:
        cases = (
            (29, {"赵建国翻供"}, "followup_d29_zhao_protection"),
            (29, {"与钱伟撕破脸"}, "followup_d29_zhao_protection"),
            (40, set(), "followup_d40_village_mediation"),
            (55, set(), "followup_d55_environment"),
            (70, {"记者结盟"}, "followup_d70_public_oversight"),
            (84, set(), "followup_d84_final_inspection"),
        )
        for day, flags, plan_id in cases:
            with self.subTest(day=day):
                session = self._session_on(day)
                session.flags.update(flags)
                session.night_logs.clear()
                session.group_conversation_queue.clear()
                session.active_group_conversation = None
                record = self._service(DeterministicRoleLLMGateway()).run_night(
                    session, self.package
                )
                created = [
                    item for item in record["followup_decisions"]
                    if item["created"]
                ]
                self.assertTrue(
                    any(item["plan_id"] == plan_id for item in created),
                    (day, created, record["followup_decisions"]),
                )

    def test_d29_without_turncoat_condition_keeps_private_action_optional(self) -> None:
        session = self._session_on(29)
        record = self._service(DeterministicRoleLLMGateway()).run_night(
            session, self.package
        )
        self.assertFalse(any(
            item["created"] and item.get("plan_id") == "followup_d29_zhao_protection"
            for item in record["followup_decisions"]
        ))

    def test_d29_break_with_qian_requires_protection_followup_even_when_agents_hold(self) -> None:
        class HoldGateway(DeterministicRoleLLMGateway):
            def run_night_turn(self, context):
                if context.phase == "action":
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="hold-only",
                        action_id="night_hold_position",
                        topic_ids=context.allowed_topics[:1],
                        rationale="暂不改变现有安排。",
                    )
                return super().run_night_turn(context)

        session = self._session_on(29)
        session.flags.add("与钱伟撕破脸")
        record = self._service(HoldGateway()).run_night(session, self.package)

        self.assertTrue(any(
            item["created"] and item.get("plan_id") == "followup_d29_zhao_protection"
            for item in record["followup_decisions"]
        ))

    def test_legal_consensus_settles_registered_outcome_and_audits_idempotently(self) -> None:
        gateway = RecordingNightGateway()
        session = self._session_on(29)
        before = session.game_state.corruption_evidence
        service = self._service(gateway)

        first = service.run_night(session, self.package)
        second = service.run_night(session, self.package)

        exchange = first["agent_exchanges"][0]
        self.assertIs(first, second)
        self.assertEqual(1, len(session.night_logs))
        self.assertEqual(["night_unify_story"], exchange["executed_action_ids"])
        self.assertEqual(
            ["outcome_unify_story"], exchange["resolved_hard_outcome_ids"]
        )
        self.assertGreater(session.game_state.corruption_evidence, before)
        audits = exchange["private_audit"]
        self.assertEqual(2, len(audits))
        self.assertTrue(all(item["validation_verdict"] == "accepted" for item in audits))
        self.assertTrue(all(item["original_proposal"] for item in audits))
        self.assertTrue(all(item["model_audit_reference"] for item in audits))
        self.assertTrue(all(item["resolved_hard_outcome_ids"] == ["outcome_unify_story"] for item in audits))

    def test_scene_execution_limit_rejects_later_legal_proposal_before_settlement(self) -> None:
        class SplitActionGateway(DeterministicRoleLLMGateway):
            def run_night_turn(self, context):
                if context.phase != "action":
                    return super().run_night_turn(context)
                if context.npc_id == "npc_zhao_jianguo":
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="fake-split-actions",
                        action_id="night_move_originals",
                        topic_ids=("evidence_custody",),
                        rationale="只处理本人经手的材料。",
                    )
                return NightAgentResult(
                    npc_id=context.npc_id,
                    model_id="fake-split-actions",
                    action_id="night_cut_off_counterpart",
                    target_ids=("npc_zhao_jianguo",),
                    topic_ids=("investigation_risk",),
                    rationale="停止互相掩护。",
                )

        session = self._session_on(29)
        session.flags.update({"与钱伟撕破脸", "秘密摸底"})

        record = self._service(SplitActionGateway()).run_night(
            session, self.package
        )

        exchange = record["agent_exchanges"][0]
        self.assertEqual(1, len(exchange["executed_action_ids"]))
        qian = next(
            item
            for item in exchange["action_proposals"]
            if item["npc_id"] == "npc_qian_wei"
        )
        self.assertEqual("night_hold_position", qian["action_id"])
        self.assertTrue(qian["fallback"])
        self.assertEqual("scene_execution_limit", qian["reason"])
        qian_audit = next(
            item
            for item in exchange["private_audit"]
            if item["phase"] == "action" and item["npc_id"] == "npc_qian_wei"
        )
        self.assertEqual("rejected", qian_audit["validation_verdict"])
        self.assertEqual(["outcome_hold_position"], qian_audit["resolved_hard_outcome_ids"])

    def test_unmet_consensus_falls_back_without_applying_consensus_outcome(self) -> None:
        class SplitConsensusGateway(DeterministicRoleLLMGateway):
            def run_night_turn(self, context):
                if context.phase != "action":
                    return super().run_night_turn(context)
                action_id = (
                    "night_unify_story"
                    if context.npc_id == "npc_qian_wei"
                    else "night_hold_position"
                )
                target_ids = (
                    ("npc_zhao_jianguo",)
                    if action_id == "night_unify_story" else ()
                )
                return NightAgentResult(
                    npc_id=context.npc_id,
                    model_id="fake-split-consensus",
                    action_id=action_id,
                    target_ids=target_ids,
                    topic_ids=("investigation_risk",),
                    rationale="双方尚未形成共同决定。",
                )

        session = self._session_on(29)
        session.game_state = replace(session.game_state, corruption_evidence=0)

        record = self._service(SplitConsensusGateway()).run_night(
            session, self.package
        )

        exchange = record["agent_exchanges"][0]
        self.assertEqual(["night_hold_position"], exchange["executed_action_ids"])
        self.assertEqual(0, session.game_state.corruption_evidence)
        qian = next(
            item for item in exchange["action_proposals"]
            if item["npc_id"] == "npc_qian_wei"
        )
        self.assertEqual("night_hold_position", qian["action_id"])
        self.assertEqual("consensus_not_reached", qian["reason"])
        qian_audit = next(
            item
            for item in exchange["private_audit"]
            if item["phase"] == "action" and item["npc_id"] == "npc_qian_wei"
        )
        self.assertEqual("rejected", qian_audit["validation_verdict"])
        self.assertEqual("consensus_not_reached", qian_audit["rejection_reason"])

    def test_review_night_timeline_uses_player_safe_field_whitelist(self) -> None:
        session = self._session_on(29)
        self._service(RecordingNightGateway()).run_night(session, self.package)
        self.runtime.sessions.save(session, expected_version=session.state_version)

        response = self.client.get(
            f"/api/game/session/{self.session_id}/review",
            headers=self.headers,
        )

        self.assertEqual(200, response.status_code, response.text)
        night = response.json()["night_timeline"][0]
        self.assertEqual(
            {
                "story_day",
                "beat_id",
                "lines",
                "summary",
                "morning_card",
                "propagation_count",
            },
            set(night),
        )
        for private_key in (
            "private_audit",
            "agent_failures",
            "original_proposal",
            "rationale",
            "rejection_reason",
            "model_audit_reference",
        ):
            self.assertNotIn(private_key, response.text)

    def test_review_group_conversation_preserves_its_story_day(self) -> None:
        session = self._session_on(11)
        session.completed_group_conversations.append({
            "conversation_id": "group_review_day_11",
            "conversation_type": "cadre_meeting",
            "initiator_npc_id": "npc_zhao_jianguo",
            "participant_ids": ["npc_zhao_jianguo", "npc_sun_qiang"],
            "agenda": "明确次日汇报口径与责任分工",
            "demands": ["明确责任人"],
            "story_day": 11,
            "turn_count": 3,
            "transcript": [],
        })
        self.runtime.sessions.save(session, expected_version=session.state_version)

        response = self.client.get(
            f"/api/game/session/{self.session_id}/review",
            headers=self.headers,
        )

        self.assertEqual(200, response.status_code, response.text)
        group = response.json()["group_conversation_timeline"][0]
        self.assertEqual(11, group["story_day"])

    def test_illegal_contact_aborts_without_hold_or_partial_settlement(self) -> None:
        session = self._session_on(29)
        session.game_state = replace(session.game_state, corruption_evidence=0)
        service = self._service(
            RecordingNightGateway(night_fixture="illegal_contact")
        )

        before = deepcopy(session)
        with self.assertRaises(RoleLLMResponseRetryableError):
            service.run_night(session, self.package)

        self.assertEqual([], session.night_logs)
        self.assertEqual(0, session.game_state.corruption_evidence)
        self.assertNotIn("攻守同盟已成", session.flags)
        self.assertEqual(before.flags, session.flags)
        self.assertEqual(before.game_state, session.game_state)

    def test_illegal_action_aborts_without_hold_or_partial_settlement(self) -> None:
        session = self._session_on(29)
        before = deepcopy(session)
        with self.assertRaises(RoleLLMResponseRetryableError):
            self._service(
                RecordingNightGateway(night_fixture="illegal_action")
            ).run_night(session, self.package)
        self.assertEqual([], session.night_logs)
        self.assertEqual(before.flags, session.flags)
        self.assertEqual(before.game_state, session.game_state)

    def test_model_failure_reports_safe_night_phase_without_hidden_payload(self) -> None:
        class UnavailableGateway:
            def run_night_turn(self, _context):
                raise RoleLLMUnavailableError("供应商暂时不可用")

        session = self._session_on(29)
        with self.assertRaises(RoleLLMResponseRetryableError) as caught:
            self._service(UnavailableGateway()).run_night(session, self.package)

        details = caught.exception.details
        self.assertEqual("ROLE_LLM_UNAVAILABLE", details["cause_code"])
        self.assertIn(details["phase"], {
            "contact_selection", "invitation_response", "dialogue", "action",
        })
        self.assertTrue(details["scene_id"])
        self.assertTrue(details["npc_id"])
        self.assertTrue(details["operation_id"])
        self.assertNotIn("original_proposal", details)
        self.assertNotIn("response", details)

    def test_legal_no_contact_commits_a_morning_card_without_a_failure_fallback(self) -> None:
        delegate = DeterministicRoleLLMGateway()

        class NoContactGateway:
            def __getattr__(self, name):
                return getattr(delegate, name)

            def run_night_turn(self, context):
                if context.phase == "contact_selection":
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="no-contact-choice",
                        contact_ids=(),
                        contact_response="今晚不主动联系任何人。",
                        rationale="人物明确选择保持沉默。",
                    )
                return delegate.run_night_turn(context)

        session = self._session_on(29)
        record = self._service(NoContactGateway()).run_night(session, self.package)

        self.assertEqual(1, len(session.night_logs))
        self.assertEqual([], record["agent_failures"])
        self.assertTrue(record["morning_card"])
        self.assertTrue(record["contact_selections"])
        self.assertTrue(all(
            item["contact_ids"] == [] for item in record["contact_selections"]
        ))
        self.assertFalse(any(
            proposal.get("fallback")
            for exchange in record["agent_exchanges"]
            for proposal in exchange.get("action_proposals", ())
        ))

    def test_legal_fixture_is_repeatable_for_same_seed(self) -> None:
        first_session = self._session_on(29)
        first_session.random_seed = "night-v3-repeatable-seed"
        first = self._service(DeterministicRoleLLMGateway()).run_night(
            first_session, self.package
        )

        created = self.client.post(
            "/api/game/session",
            headers=self.headers,
            json={
                "client_request_id": "night-v3-repeat-session",
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        second_session = self.runtime.sessions.get_owned(
            created.json()["session_id"], "acct_night_v3"
        )
        second_session.pending_decision = None
        second_session.pending_decision_queue.clear()
        second_session.random_seed = "night-v3-repeatable-seed"
        second_session.game_state = replace(
            second_session.game_state, story_day=29, days_left=62
        )
        second = self._service(DeterministicRoleLLMGateway()).run_night(
            second_session, self.package
        )

        first_exchange = first["agent_exchanges"][0]
        second_exchange = second["agent_exchanges"][0]
        for key in (
            "participant_ids",
            "action_proposals",
            "executed_action_ids",
            "resolved_hard_outcome_ids",
            "public_summary",
        ):
            self.assertEqual(first_exchange[key], second_exchange[key])
        self.assertEqual(first_session.flags, second_session.flags)
        self.assertEqual(first_session.game_state, second_session.game_state)


class NightAgentV3FullPlaybackTests(unittest.TestCase):
    def test_fake_playback_reaches_d90_with_89_unique_night_settlements(self) -> None:
        from tests.test_m2_runtime import M2RuntimeTests

        runner = M2RuntimeTests()
        settings = Settings(
            environment="test",
            content_root=PACKAGE_DIR.parent,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        runner.container = build_container(settings)
        runner.client = TestClient(create_app(settings, runner.container))
        runner.headers = {"X-Account-ID": "acct_night_v3_playback"}
        created = runner.client.post(
            "/api/game/session",
            headers=runner.headers,
            json={
                "client_request_id": "night-v3-full-playback",
                "origin_id": "technical",
                "package_id": "pkg_gameplay_v3",
            },
        )
        runner.assertEqual(201, created.status_code, created.text)
        runner.session_id = created.json()["session_id"]
        session = runner.container.sessions.get_owned(
            runner.session_id, "acct_night_v3_playback"
        )
        session.random_seed = "night-v3-d1-d90-seed"
        runner.container.sessions.save(
            session, expected_version=session.state_version
        )

        result = runner.reach_d3()
        for index in range(100):
            if result["visible_state"]["status"] == "ended":
                break
            group_round = 0
            while result["visible_state"].get("active_group_conversation"):
                group_round += 1
                active_group = result["visible_state"]["active_group_conversation"]
                resolved = active_group.get("phase") == "resolved"
                endpoint = (
                    "finish" if resolved else "turn"
                )
                body = {
                    "state_version": result["state_version"],
                    "client_action_id": (
                        f"night-v3-group-{index:02d}-{group_round:02d}"
                    ),
                }
                if not resolved:
                    body["player_text"] = "请各位只围绕已经确认的议题逐项说明。"
                response = runner.client.post(
                    f"/api/game/session/{runner.session_id}/group-conversation/{endpoint}",
                    headers=runner.headers,
                    json=body,
                )
                runner.assertEqual(200, response.status_code, response.text)
                result = response.json()
            result = runner.drain_decisions(result, f"night-v3-stop-{index:02d}")
            result = runner.end_day(
                result["state_version"], f"night-v3-end-{index:02d}"
            )

        self.assertEqual("ended", result["visible_state"]["status"])
        self.assertEqual(90, result["visible_state"]["story"]["day"])
        stored = runner.container.sessions.get_owned(
            runner.session_id, "acct_night_v3_playback"
        )
        settled_days = [item["story_day"] for item in stored.night_logs]
        self.assertEqual(list(range(1, 90)), settled_days)
        self.assertEqual(89, len(set(settled_days)))
        self.assertTrue(any(
            item.get("private_audit") for item in stored.night_logs
        ))


if __name__ == "__main__":
    unittest.main()
