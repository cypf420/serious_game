from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"
PACKAGE_DIR = PACKAGE_ROOT / "pkg_gameplay_v3"


class StoryReviewRound1Tests(unittest.TestCase):
    def build_api(self, suffix: str) -> tuple[object, TestClient, str, dict[str, str]]:
        settings = Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        container = build_container(settings)
        client = TestClient(create_app(settings, container=container))
        headers = {"X-Account-ID": f"acct_review_round1_{suffix}"}
        created = client.post(
            "/api/game/session",
            headers=headers,
            json={
                "client_request_id": f"review-round1-{suffix}",
                "origin_id": "technical",
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        return container, client, created.json()["session_id"], headers

    def reset_to_day(
        self,
        container,
        session_id: str,
        headers: dict[str, str],
        day: int,
        *,
        flags: set[str] | None = None,
        known_fact_ids: set[str] | None = None,
    ):
        session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        package = container.packages.get("pkg_gameplay_v3")
        session.game_state = replace(session.game_state, story_day=day)
        session.flags = set(flags or ())
        session.known_fact_ids = set(known_fact_ids or ())
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.narrative_feed.clear()
        session.next_feed_cursor = 1
        container.story_flow.enter_current_day(session, package)
        container.sessions.save(session, expected_version=session.state_version)
        return session

    def submit_decision(
        self,
        client: TestClient,
        session_id: str,
        headers: dict[str, str],
        session,
        decision_id: str,
        option_id: str,
        *,
        parameters: dict | None = None,
    ) -> dict:
        response = client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json={
                "input_mode": "decision",
                "client_action_id": f"review-{decision_id}-{option_id}",
                "state_version": session.state_version,
                "decision_id": decision_id,
                "option_id": option_id,
                "parameters": parameters or {},
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def end_day(
        self,
        client: TestClient,
        session_id: str,
        headers: dict[str, str],
        state_version: int,
        suffix: str,
    ) -> dict:
        response = client.post(
            f"/api/game/session/{session_id}/end-day",
            headers=headers,
            json={
                "client_action_id": f"review-end-{suffix}",
                "state_version": state_version,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def feed(self, client: TestClient, session_id: str, headers: dict[str, str]) -> list[dict]:
        response = client.get(
            f"/api/game/session/{session_id}/feed?after=0",
            headers=headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["items"]

    def test_d18_uses_phone_pressure_after_dp2_01_breaks_with_qian(self) -> None:
        container, client, session_id, headers = self.build_api("d18-break")
        session = self.reset_to_day(container, session_id, headers, 17)
        submitted = self.submit_decision(
            client, session_id, headers, session, "dp2_01", "d"
        )

        entered = self.end_day(
            client,
            session_id,
            headers,
            submitted["state_version"],
            "d17-break",
        )
        day18 = [item for item in self.feed(client, session_id, headers) if item["story_day"] == 18]
        visible_text = "\n".join(item["text"] for item in day18)
        pending = entered["visible_state"]["pending_decision"]

        self.assertIn("赵建国", visible_text)
        self.assertIn("电话", visible_text)
        self.assertIn("钱伟没有登门", visible_text)
        self.assertNotIn("钱伟坐在你办公室", visible_text)
        self.assertNotIn("茶叶盒里压着", visible_text)
        self.assertEqual("dp2_02", pending["decision_id"])
        option_by_id = {item["option_id"]: item for item in pending["options"]}
        self.assertFalse(option_by_id["c"]["available"])
        self.assertNotIn("追回", option_by_id["a"]["text"])
        self.assertNotIn("茶叶", option_by_id["d"]["text"])

        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        selected_label = next(
            item["text"] for item in pending["options"] if item["option_id"] == "a"
        )
        self.submit_decision(client, session_id, headers, stored, "dp2_02", "a")
        consequence = "\n".join(
            item["text"]
            for item in self.feed(client, session_id, headers)
            if item["story_day"] == 18 and item["kind"] == "consequence"
        )
        self.assertIn("电话", consequence)
        self.assertNotIn("追回", consequence)

        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        stored.game_state = replace(stored.game_state, story_day=90)
        container.sessions.save(stored, expected_version=stored.state_version)
        review = client.get(
            f"/api/game/session/{session_id}/review", headers=headers
        )
        self.assertEqual(200, review.status_code, review.text)
        recorded = next(
            item for item in review.json()["decision_timeline"]
            if item["decision_id"] == "dp2_02"
        )
        self.assertEqual(pending["title"], recorded["title"])
        self.assertEqual(selected_label, recorded["choice"])
        self.assertIn("赵建国", recorded["prompt"])
        self.assertEqual("C01_S08", recorded["scene_id"])

    def test_d18_keeps_qian_visit_when_dp2_01_does_not_break_with_him(self) -> None:
        container, client, session_id, headers = self.build_api("d18-visit")
        session = self.reset_to_day(
            container,
            session_id,
            headers,
            17,
            known_fact_ids={"fact_connected_invoices"},
        )
        submitted = self.submit_decision(
            client, session_id, headers, session, "dp2_01", "a"
        )

        entered = self.end_day(
            client,
            session_id,
            headers,
            submitted["state_version"],
            "d17-visit",
        )
        visible_text = "\n".join(
            item["text"]
            for item in self.feed(client, session_id, headers)
            if item["story_day"] == 18
        )
        options = {
            item["option_id"]: item
            for item in entered["visible_state"]["pending_decision"]["options"]
        }

        self.assertIn("钱伟坐在你办公室", visible_text)
        self.assertIn("茶叶盒里压着", visible_text)
        self.assertNotIn("钱伟没有登门", visible_text)
        self.assertTrue(options["c"]["available"])
        self.assertIn("追回", options["a"]["text"])

        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        selected_label = options["a"]["text"]
        self.submit_decision(client, session_id, headers, stored, "dp2_02", "a")
        review = client.get(
            f"/api/game/session/{session_id}/review", headers=headers
        )
        self.assertEqual(200, review.status_code, review.text)
        recorded = next(
            item for item in review.json()["decision_timeline"]
            if item["decision_id"] == "dp2_02"
        )
        self.assertEqual(
            entered["visible_state"]["pending_decision"]["title"],
            recorded["title"],
        )
        self.assertEqual(selected_label, recorded["choice"])
        self.assertEqual("C02_S01", recorded["scene_id"])

    def test_d74_second_decision_switches_from_pediatrics_to_ancestral_hall(self) -> None:
        container, client, session_id, headers = self.build_api("d74-scenes")
        session = self.reset_to_day(container, session_id, headers, 74)
        entered = client.get(
            f"/api/game/session/{session_id}/view", headers=headers
        ).json()
        self.assertEqual("dp5_08", entered["state"]["pending_decision"]["decision_id"])
        self.assertEqual("C05_S07", entered["state"]["pending_decision"]["scene_id"])

        result = self.submit_decision(
            client, session_id, headers, session, "dp5_08", "a"
        )
        pending = result["visible_state"]["pending_decision"]
        self.assertEqual("dp5_09", pending["decision_id"])
        self.assertEqual("祠堂用地手续。", pending["title"])
        self.assertEqual("C05_S02", pending["scene_id"])

    def test_multistage_decision_journals_each_presented_choice(self) -> None:
        container, client, session_id, headers = self.build_api("multistage-journal")
        session = self.reset_to_day(container, session_id, headers, 51)
        first = client.get(
            f"/api/game/session/{session_id}/view", headers=headers
        ).json()["state"]["pending_decision"]
        first_label = next(
            item["text"] for item in first["options"] if item["option_id"] == "a"
        )
        repeated = self.submit_decision(
            client, session_id, headers, session, "dp4_04", "a"
        )
        second = repeated["visible_state"]["pending_decision"]
        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        second_label = next(
            item["text"] for item in second["options"] if item["option_id"] == "c"
        )
        self.submit_decision(client, session_id, headers, stored, "dp4_04", "c")

        review = client.get(
            f"/api/game/session/{session_id}/review", headers=headers
        ).json()
        recorded = [
            item for item in review["decision_timeline"]
            if item["decision_id"] == "dp4_04"
        ]
        self.assertEqual([first_label, second_label], [item["choice"] for item in recorded])
        self.assertTrue(all(item["title"] == first["title"] for item in recorded))
        self.assertTrue(all(item["prompt"] == first["text"] for item in recorded))
        self.assertTrue(all(item["scene_id"] == first["scene_id"] for item in recorded))

    def test_d51_repeated_money_offer_has_distinct_round_copy_in_ui_and_review(self) -> None:
        container, client, session_id, headers = self.build_api("d51-money-round-copy")
        session = self.reset_to_day(container, session_id, headers, 51)
        visible_labels = []
        for round_index in range(3):
            pending = client.get(
                f"/api/game/session/{session_id}/view", headers=headers
            ).json()["state"]["pending_decision"]
            visible_labels.append(next(
                item["text"] for item in pending["options"]
                if item["option_id"] == "b"
            ))
            response = client.post(
                f"/api/game/session/{session_id}/action",
                headers=headers,
                json={
                    "input_mode": "decision",
                    "client_action_id": f"d51-money-round-{round_index}",
                    "state_version": session.state_version,
                    "decision_id": "dp4_04",
                    "option_id": "b",
                    "parameters": {},
                },
            )
            self.assertEqual(200, response.status_code, response.text)
            session = container.sessions.get_owned(
                session_id, headers["X-Account-ID"]
            )

        self.assertEqual([
            "当场给他许一个更高的补偿数。",
            "见他没有还价，你把补偿数又往上提了一次。",
            "你把补偿数提到第三次，要求他当场给个答复。",
        ], visible_labels)
        review = client.get(
            f"/api/game/session/{session_id}/review", headers=headers
        ).json()
        recorded = [
            item["choice"] for item in review["decision_timeline"]
            if item["decision_id"] == "dp4_04"
        ]
        self.assertEqual(visible_labels, recorded)

    def test_legacy_decision_log_uses_safe_base_copy_fallback(self) -> None:
        container, client, session_id, headers = self.build_api("legacy-journal")
        session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        session.logs = [{
            "type": "decision",
            "story_day": 18,
            "decision_id": "dp2_02",
            "option_id": "a",
            "visible_to_player": True,
        }]
        container.sessions.save(session, expected_version=session.state_version)
        package = container.packages.get("pkg_gameplay_v3")
        recorded = client.get(
            f"/api/game/session/{session_id}/review", headers=headers
        ).json()["decision_timeline"][0]
        self.assertEqual(package.decisions["dp2_02"].title, recorded["title"])
        self.assertEqual(package.decisions["dp2_02"].prompt, recorded["prompt"])
        self.assertEqual(package.decisions["dp2_02"].scene_id, recorded["scene_id"])
        self.assertEqual(package.decisions["dp2_02"].option("a").text, recorded["choice"])

    def test_d30_morning_card_uses_only_observed_d29_night_records(self) -> None:
        cases = (
            (
                "all-triggered",
                {"砸钱普涨"},
                ("县城茶楼昨晚有人订了包间，订到子夜。", "柳林村昨夜有人挨家串门，说的还是苗喜旺那笔钱。"),
            ),
            (
                "one-triggered",
                {"与钱伟撕破脸", "砸钱普涨"},
                ("柳林村昨夜有人挨家串门，说的还是苗喜旺那笔钱。",),
            ),
            (
                "none-triggered",
                {"与钱伟撕破脸"},
                ("县城昨夜无事。",),
            ),
        )
        for suffix, flags, expected in cases:
            with self.subTest(suffix=suffix):
                container, client, session_id, headers = self.build_api(f"d30-{suffix}")
                session = self.reset_to_day(
                    container, session_id, headers, 29, flags=flags
                )
                submitted = self.submit_decision(
                    client,
                    session_id,
                    headers,
                    session,
                    "dp2_10",
                    "submit",
                    parameters={
                        "allocations": {
                            "signing_compensation": 150,
                            "livelihood_support": 0,
                            "environmental_retest": 0,
                            "emergency_stability": 0,
                        }
                    },
                )
                self.end_day(
                    client,
                    session_id,
                    headers,
                    submitted["state_version"],
                    f"d29-{suffix}",
                )
                items = self.feed(client, session_id, headers)
                morning = tuple(
                    item["text"]
                    for item in items
                    if item["story_day"] == 30 and item["kind"] == "morning_card"
                )
                leaked_night = [
                    item
                    for item in items
                    if item["story_day"] == 29 and item["kind"] == "night"
                ]

                self.assertEqual(expected, morning)
                self.assertEqual([], leaked_night)
                all_day30 = "\n".join(
                    item["text"] for item in items if item["story_day"] == 30
                )
                for absent in {
                    "县城茶楼昨晚有人订了包间，订到子夜。",
                    "柳林村昨夜有人挨家串门，说的还是苗喜旺那笔钱。",
                    "县城昨夜无事。",
                } - set(expected):
                    self.assertNotIn(absent, all_day30)
                self.assertNotIn("外地口音", all_day30)

    def mutate_package(self, mutations: dict[str, object]) -> Path:
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
        for filename, mutate in mutations.items():
            path = package_dir / filename
            document = json.loads(path.read_text(encoding="utf-8"))
            mutate(document)
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return package_dir

    def assert_authority_failure(self, package_dir: Path, *, day: int, node: str) -> None:
        with self.assertRaises(ContentValidationError) as raised:
            FileScriptPackageLoader().load(package_dir)
        self.assertEqual("pkg_gameplay_v3", raised.exception.details.get("package"))
        self.assertEqual(day, raised.exception.details.get("day"))
        self.assertEqual(node, raised.exception.details.get("node"))
        self.assertEqual("authority_contract", raised.exception.details.get("field"))

    def test_authority_contract_rejects_a_synced_d18_person_mutation(self) -> None:
        def mutate(document: dict) -> None:
            decision = next(
                item for item in document["decisions"] if item["decision_id"] == "dp2_02"
            )
            option = next(item for item in decision["options"] if item["option_id"] == "a")
            option["consequence"] = option["consequence"].replace("钱伟", "郑向东")

        package_dir = self.mutate_package({"decisions.json": mutate})
        self.assert_authority_failure(package_dir, day=18, node="beat_d18_m2")

    def test_authority_contract_rejects_a_d18_number_or_fact_mutation(self) -> None:
        for old, new in (("三十万", "三千万元"), ("三十六户", "三百六十户")):
            with self.subTest(new=new):
                def mutate(document: dict, old=old, new=new) -> None:
                    beat = next(item for item in document["beats"] if item["story_day"] == 18)
                    for block in beat["opening_blocks"]:
                        block["text"] = block["text"].replace(old, new)

                package_dir = self.mutate_package({"story_beats.json": mutate})
                self.assert_authority_failure(package_dir, day=18, node="beat_d18_m2")

    def test_authority_contract_rejects_a_d18_condition_mutation(self) -> None:
        def mutate(document: dict) -> None:
            decision = next(
                item for item in document["decisions"] if item["decision_id"] == "dp2_02"
            )
            option = next(item for item in decision["options"] if item["option_id"] == "c")
            option["forbidden_flags"] = []

        package_dir = self.mutate_package({"decisions.json": mutate})
        self.assert_authority_failure(package_dir, day=18, node="beat_d18_m2")

    def test_duplicate_d18_block_reports_complete_runtime_context(self) -> None:
        def mutate(document: dict) -> None:
            beat = next(item for item in document["beats"] if item["story_day"] == 18)
            duplicate = dict(beat["opening_blocks"][0])
            beat["opening_blocks"].append(duplicate)

        package_dir = self.mutate_package({"story_beats.json": mutate})
        with self.assertRaises(ContentValidationError) as raised:
            FileScriptPackageLoader().load(package_dir)
        self.assertIn("重复", raised.exception.message)
        self.assertEqual(
            {
                "package": "pkg_gameplay_v3",
                "day": 18,
                "node": "d18_qian_arrival",
                "field": "block_id",
            },
            {
                key: raised.exception.details.get(key)
                for key in ("package", "day", "node", "field")
            },
        )

    def test_settings_constructor_and_environment_default_to_v3_but_allow_v2_override(self) -> None:
        self.assertEqual("pkg_gameplay_v3", Settings().default_package_id)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual("pkg_gameplay_v3", Settings.from_env().default_package_id)
        self.assertEqual(
            "pkg_gameplay_v2",
            Settings(default_package_id="pkg_gameplay_v2").default_package_id,
        )


if __name__ == "__main__":
    unittest.main()
