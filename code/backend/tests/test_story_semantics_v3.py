from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.player_text_policy import validate_player_visible_text
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.api.app import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"


class StorySemanticsV3Tests(unittest.TestCase):
    def test_story_does_not_repeat_long_player_visible_blocks_verbatim(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        occurrences: dict[str, list[str]] = {}
        for day in range(1, 91):
            beat = package.story_day(day)
            for block in (*beat.opening_blocks, *beat.night_blocks):
                text = block.text.strip()
                if len(text) >= 40:
                    occurrences.setdefault(text, []).append(f"D{day}:{block.block_id}")
        duplicates = {text: locations for text, locations in occurrences.items() if len(locations) > 1}
        self.assertEqual({}, duplicates)

    def test_d1_dossiers_present_evidence_without_spoiling_hidden_routes(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        dossier_text = "\n".join(
            block.text for block in package.story_day(1).opening_blocks
            if block.block_id.startswith("d01_briefing_dossier_")
        )
        for authorial_label in ("贪腐线", "隐瞒线", "三条暗线", "第一个扣子", "最危险的一颗雷"):
            self.assertNotIn(authorial_label, dossier_text)
        self.assertIn("两百万", dossier_text)
        self.assertIn("涉铅遗留", dossier_text)

    def test_six_forced_followups_define_character_persuasion_guidance(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        plans = [
            plan
            for scene in package.night_agent_scenes
            for plan in scene.get("followup_plans", ())
        ]
        self.assertEqual(6, len(plans))
        for plan in plans:
            self.assertTrue(str(plan.get("persuasion_context", "")).strip())
            guidance = plan.get("participant_guidance")
            self.assertEqual(set(plan["participant_ids"]), set(guidance or {}))
            for npc_id in plan["participant_ids"]:
                item = guidance[npc_id]
                self.assertTrue(item.get("core_concerns"))
                self.assertTrue(item.get("convincing_signals"))
                self.assertTrue(item.get("suspicion_signals"))
                self.assertTrue(str(item.get("questioning_style", "")).strip())

    def test_night_followup_plans_are_complete_package_owned_candidates(self) -> None:
        def mutate(document: dict) -> None:
            scene = next(
                item for item in document["night_agent_scenes"]
                if item["scene_id"] == "night_d84_inspection_followup"
            )
            scene["followup_plans"][0]["participant_ids"] = ["npc_missing"]

        package_dir = self.mutate_package("social_rules.json", mutate)
        with self.assertRaises(ContentValidationError) as raised:
            FileScriptPackageLoader().load(package_dir)
        self.assertIn("follow-up", raised.exception.message)

    def test_followup_rejects_missing_participant_persuasion_guidance(self) -> None:
        def mutate(document: dict) -> None:
            scene = next(
                item for item in document["night_agent_scenes"]
                if item["scene_id"] == "night_d84_inspection_followup"
            )
            scene["followup_plans"][0]["participant_guidance"].pop(
                "npc_zhang_li"
            )

        package_dir = self.mutate_package("social_rules.json", mutate)
        with self.assertRaises(ContentValidationError) as raised:
            FileScriptPackageLoader().load(package_dir)
        self.assertIn("劝服策略", raised.exception.message)

    def test_player_visible_text_rejects_ascii_comma_in_chinese_context_only(self) -> None:
        with self.assertRaises(ContentValidationError):
            validate_player_visible_text("他点了头,转身离开。")
        validate_player_visible_text("fact_id,debug")
        validate_player_visible_text("alpha,beta")

    def test_d74_and_d75_package_copy_has_no_chinese_ascii_comma(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        for day in (74, 75):
            beat = package.story_day(day)
            values = [item.text for item in (*beat.opening_blocks, *beat.night_blocks)]
            for decision in package.decisions.values():
                if decision.story_day != day:
                    continue
                values.extend((decision.title, decision.prompt))
                values.extend(item.text for item in decision.options)
                values.extend(item.consequence for item in decision.options)
                values.extend(item.text for item in decision.presentation_blocks)
                values.extend(item.text for item in decision.followup_blocks)
            self.assertFalse(
                any(re.search(r"(?<=[\u3400-\u9fff]),|,(?=[\u3400-\u9fff])", value) for value in values),
                f"D{day} still contains an ASCII comma in Chinese player copy",
            )

    def test_v3_loader_applies_player_text_policy_to_endings(self) -> None:
        def mutate(document: dict) -> None:
            document["main_endings"][0]["text"] = "他点了头,转身离开。"

        package_dir = self.mutate_package("ending_rules.json", mutate)
        with self.assertRaises(ContentValidationError):
            FileScriptPackageLoader().load(package_dir)
    def mutate_package(self, filename: str, mutate) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        package_dir = Path(temporary.name) / "pkg_gameplay_v3"
        shutil.copytree(PACKAGE_DIR, package_dir)
        manifest_path = package_dir / "package_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "draft"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        path = package_dir / filename
        document = json.loads(path.read_text(encoding="utf-8"))
        mutate(document)
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return package_dir

    def assert_validation_context(
        self,
        package_dir: Path,
        *,
        day: int,
        node: str,
        field: str,
    ) -> ContentValidationError:
        with self.assertRaises(ContentValidationError) as raised:
            FileScriptPackageLoader().load(package_dir)
        error = raised.exception
        self.assertEqual("pkg_gameplay_v3", error.details.get("package"))
        self.assertEqual(day, error.details.get("day"))
        self.assertEqual(node, error.details.get("node"))
        self.assertEqual(field, error.details.get("field"))
        self.assertTrue(error.message.strip())
        return error

    def test_unknown_visible_speaker_is_rejected_with_actionable_context(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 17)
            beat["opening_blocks"][1]["speaker"] = "不存在的人"

        package_dir = self.mutate_package("story_beats.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=17,
            node="d17_feng_words",
            field="speaker",
        )
        self.assertIn("人物", error.message)

    def test_proactive_target_cannot_open_before_the_character_is_introduced(self) -> None:
        def mutate(document: dict) -> None:
            opportunity = next(
                item
                for item in document["opportunities"]
                if item["opportunity_id"] == "opp_31_luo_jian_contact"
            )
            opportunity["day_min"] = 1

        package_dir = self.mutate_package("interaction_opportunities.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=1,
            node="opp_31_luo_jian_contact",
            field="npc_id",
        )
        self.assertIn("介绍", error.message)

    def test_missing_scene_asset_is_rejected_at_the_referencing_block(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 17)
            beat["opening_blocks"][0]["scene_id"] = "C99_S99"

        package_dir = self.mutate_package("story_beats.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=17,
            node="d17_feng_arrival",
            field="scene_id",
        )
        self.assertIn("场景", error.message)

    def test_missing_decision_prerequisite_is_rejected_with_decision_context(self) -> None:
        def mutate(document: dict) -> None:
            decision = next(
                item for item in document["decisions"] if item["decision_id"] == "dp2_01"
            )
            decision["presentation_blocks"] = []

        package_dir = self.mutate_package("decisions.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=17,
            node="dp2_01",
            field="presentation_blocks",
        )
        self.assertIn("铺垫", error.message)

    def test_blank_non_story_day_requires_an_explicit_free_action_prompt(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 19)
            beat["day_mode"] = "playable"

        package_dir = self.mutate_package("story_beats.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=19,
            node="beat_d19_m2",
            field="day_mode",
        )
        self.assertIn("自由行动", error.message)

    def test_duplicate_scheduled_decision_is_rejected_at_transition_reference(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 28)
            beat["decision_ids"].append("dp2_08")

        package_dir = self.mutate_package("story_beats.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=28,
            node="beat_d28_m2",
            field="decision_ids",
        )
        self.assertIn("重复", error.message)

    def test_hidden_metric_delta_in_player_consequence_is_rejected_at_load(self) -> None:
        def mutate(document: dict) -> None:
            decision = next(
                item for item in document["decisions"] if item["decision_id"] == "dp2_07"
            )
            decision["options"][0]["consequence"] = "政治资本 +5 到 +10。"

        package_dir = self.mutate_package("decisions.json", mutate)
        with self.assertRaises(ContentValidationError):
            FileScriptPackageLoader().load(package_dir)

    def test_adjacent_player_punctuation_is_rejected_at_load(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 13)
            beat["opening_blocks"][0]["text"] = "首轮攻坚已经排定，。"

        package_dir = self.mutate_package("story_beats.json", mutate)
        with self.assertRaises(ContentValidationError):
            FileScriptPackageLoader().load(package_dir)

    def test_d13_to_d30_decisions_use_event_specific_premises_and_followups(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        generic_fragments = (
            "现场的事实、人物立场和时间压力已经摆到你面前",
            "决定已经写入当天案卷",
            "请根据已经展开的现场信息作出决定",
        )

        for decision in package.decisions.values():
            if not 13 <= decision.story_day <= 30:
                continue
            visible_text = "\n".join((
                decision.prompt,
                *(item.text for item in decision.presentation_blocks),
                *(item.text for item in decision.followup_blocks),
            ))
            self.assertFalse(
                any(fragment in visible_text for fragment in generic_fragments),
                f"D{decision.story_day}/{decision.decision_id} still uses a generic premise",
            )

    def test_d18_premise_does_not_contradict_the_same_day_opening(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        normal_opening = "\n".join(
            item.text
            for item in package.story_day(18).opening_blocks
            if item.is_visible(origin_id="technical", flags=set())
        )
        normal_premise = "\n".join(
            item.text
            for item in package.decisions["dp2_02"].presentation_blocks
            if item.is_visible(origin_id="technical", flags=set())
        )
        broken_flags = {"与钱伟撕破脸"}
        phone_opening = "\n".join(
            item.text
            for item in package.story_day(18).opening_blocks
            if item.is_visible(origin_id="technical", flags=broken_flags)
        )
        phone_premise = "\n".join(
            item.text
            for item in package.decisions["dp2_02"].presentation_blocks
            if item.is_visible(origin_id="technical", flags=broken_flags)
        )

        self.assertIn("钱伟坐在你办公室", normal_opening)
        self.assertIn("茶叶盒里压着", normal_premise)
        self.assertNotIn("钱伟没有登门", normal_premise)
        self.assertIn("钱伟没有登门", phone_opening)
        self.assertIn("赵建国", phone_premise)
        self.assertNotIn("钱伟坐在你办公室", phone_opening)

    def test_every_emitted_story_entry_has_a_stable_content_instance_id(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)
        from serious_game_backend.application.game_session_service import (
            GameSessionService,
        )
        from serious_game_backend.application.event_service import EventService
        from serious_game_backend.infrastructure.repositories.memory import (
            InMemoryGameSessionRepository,
            InMemoryRuntimeTransactionRepository,
            InMemoryScriptPackageRepository,
            InMemorySessionRequestRepository,
        )

        sessions = InMemoryGameSessionRepository()
        requests = InMemorySessionRequestRepository()
        service = GameSessionService(
            sessions,
            requests,
            InMemoryRuntimeTransactionRepository(sessions, None, requests),
            InMemoryScriptPackageRepository([package]),
            StoryFlowService(),
            EventService(),
        )
        session = service.start_session(
            account_id="acct_story_semantics",
            package_id="pkg_gameplay_v3",
            client_request_id="story-semantics-session",
            origin_id="technical",
        )
        flow = StoryFlowService()
        flow.resolve_decision(
            session,
            package,
            decision_id="ev1_01_reception_bag",
            option_id="a_reject_on_site",
        )

        self.assertTrue(session.narrative_feed)
        self.assertTrue(
            all(item.content_instance_id for item in session.narrative_feed),
            "retry/replay dedupe requires every emitted story entry to have an ID",
        )

    def test_schema4_requires_a_complete_d1_d90_acceptance_matrix(self) -> None:
        package = FileScriptPackageLoader().load(PACKAGE_DIR)

        matrix = package.story_acceptance_matrix
        self.assertEqual(list(range(1, 91)), [item["story_day"] for item in matrix])
        required_fields = {
            "story_day",
            "state",
            "node_id",
            "previous_settlement_dependency",
            "opening_block_ids",
            "scene_ids",
            "visible_speakers",
            "introduced_npc_ids",
            "prerequisite_narrative_ids",
            "decision_ids",
            "decision_display_node_ids",
            "outcome_transition_ids",
            "free_action_prompt",
            "required_story_entry_ids",
            "decision_presentation_order",
            "npc_discovery_transitions",
            "archive_unlock_ids",
            "forced_conversation_plan_ids",
        }
        archive_ids = {
            item.archive_id for item in package.archive_investigations
        }
        followup_plan_ids = {
            str(plan["plan_id"])
            for scene in package.night_agent_scenes
            for plan in scene.get("followup_plans", ())
        }
        npc_ids = {item.npc_id for item in package.npc_profiles}
        for row in matrix:
            self.assertTrue(required_fields.issubset(row), f"D{row['story_day']} matrix fields")
            if row["state"] == "free_action":
                self.assertTrue(row["free_action_prompt"].strip())
            else:
                self.assertTrue(row["opening_block_ids"] or row["decision_ids"])
            self.assertEqual(
                row["opening_block_ids"],
                row["required_story_entry_ids"],
            )
            self.assertEqual(
                row["decision_ids"],
                [item["decision_id"] for item in row["decision_presentation_order"]],
            )
            self.assertTrue(
                set(row["archive_unlock_ids"]).issubset(archive_ids)
            )
            self.assertTrue(
                set(row["forced_conversation_plan_ids"]).issubset(
                    followup_plan_ids
                )
            )
            self.assertTrue(
                all(
                    item["npc_id"] in npc_ids
                    and item["state"] in {
                        "mentioned", "encountered", "contactable"
                    }
                    for item in row["npc_discovery_transitions"]
                )
            )

    def test_acceptance_matrix_rejects_a_wrong_decision_display_reference(self) -> None:
        def mutate(document: dict) -> None:
            row = next(item for item in document["days"] if item["story_day"] == 17)
            row["decision_display_node_ids"] = ["missing_display_node"]

        package_dir = self.mutate_package("story_acceptance_matrix.json", mutate)

        error = self.assert_validation_context(
            package_dir,
            day=17,
            node="beat_d17_m2",
            field="decision_display_node_ids",
        )
        self.assertIn("决策", error.message)

    def test_acceptance_matrix_rejects_unknown_runtime_transition_ids(self) -> None:
        cases = (
            ("archive_unlock_ids", "archive_not_registered"),
            ("forced_conversation_plan_ids", "followup_not_registered"),
            (
                "npc_discovery_transitions",
                [{"npc_id": "npc_not_registered", "state": "mentioned"}],
            ),
        )
        for field, value in cases:
            with self.subTest(field=field):
                def mutate(document: dict, *, field=field, value=value) -> None:
                    row = document["days"][0]
                    row[field] = value if isinstance(value, list) else [value]

                package_dir = self.mutate_package(
                    "story_acceptance_matrix.json", mutate
                )
                error = self.assert_validation_context(
                    package_dir,
                    day=1,
                    node="beat_d01_arrival_and_reception",
                    field=field,
                )
                self.assertIn("验收矩阵", error.message)

    def test_v3_is_the_default_and_v2_is_runtime_retired_without_file_edits(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            defaults = Settings.from_env()
        self.assertEqual("pkg_gameplay_v3", defaults.default_package_id)

        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        container = build_container(settings)
        self.assertEqual("retired", container.packages.get("pkg_gameplay_v2").status)
        self.assertNotEqual("retired", container.packages.get("pkg_gameplay_v3").status)

    def test_existing_v2_session_is_review_only_and_rejects_writes(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v2",
            repository="memory",
            role_llm_provider="none",
        )
        container = build_container(settings)
        client = TestClient(create_app(settings, container=container))
        headers = {"X-Account-ID": "acct_existing_v2"}
        created = client.post(
            "/api/game/session",
            headers=headers,
            json={"client_request_id": "existing-v2", "package_id": "pkg_gameplay_v2"},
        )
        self.assertEqual(201, created.status_code, created.text)
        session_id = created.json()["session_id"]
        legacy = container.packages.get("pkg_gameplay_v2")
        container.packages._items[legacy.package_id] = replace(legacy, status="retired")

        sessions = client.get("/api/game/sessions", headers=headers)
        summary = next(
            item for item in sessions.json()["sessions"] if item["session_id"] == session_id
        )
        self.assertEqual("review_only", summary["mode"])
        self.assertEqual(
            200,
            client.get(f"/api/game/session/{session_id}", headers=headers).status_code,
        )
        stored = container.sessions.get_owned(session_id, "acct_existing_v2")
        write = client.post(
            f"/api/game/session/{session_id}/end-day",
            headers=headers,
            json={
                "client_action_id": "existing-v2-write",
                "state_version": stored.state_version,
            },
        )
        self.assertEqual(409, write.status_code, write.text)
        self.assertEqual("PACKAGE_RETIRED", write.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
