from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
import unittest

from fastapi.testclient import TestClient
from tests.story_reading import read_available_story

from serious_game_backend.api.app import create_app
from serious_game_backend.api.schemas import ActionRequest
from serious_game_backend.application.action_service import ActionService
from serious_game_backend.application.ending_service import EndingAxisProjector
from serious_game_backend.application.night_simulation_service import (
    NightSimulationService,
)
from serious_game_backend.application.night_turn_safety import (
    validate_night_turn_result,
)
from serious_game_backend.application.scripted_delta_resolver import (
    ScriptedDeltaResolver,
)
from serious_game_backend.application.scripted_effect_service import (
    ScriptedEffectService,
)
from serious_game_backend.application.stream_lifecycle import StreamCancellation
from serious_game_backend.application.trust_derivation_service import TrustDerivationService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.enums import ActionInputMode, OperationStatus
from serious_game_backend.domain.errors import (
    ContentValidationError,
    RoleLLMResponseError,
    RoleLLMResponseRetryableError,
    SessionBusyError,
    StateVersionConflictError,
)
from serious_game_backend.domain.llm import NightAgentResult
from serious_game_backend.domain.fact_markers import (
    FACT_DISCLOSURE_MARKERS,
    forbidden_fact_signatures,
)
from serious_game_backend.domain.conversation import ForcedGroupConversation
from serious_game_backend.domain.story import ScriptedEffects
from serious_game_backend.infrastructure.repositories.codec import (
    decode_session,
    encode_session,
)
from tests.test_doubles import DeterministicRoleLLMGateway


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class GameplayV2Tests(unittest.TestCase):
    def test_night_turn_safety_covers_fact_id_title_text_alias_and_shape(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        fact = package.facts["fact_shi_usb"]
        forbidden = forbidden_fact_signatures(package.facts, set())
        candidates = (
            fact.fact_id,
            fact.title,
            fact.text,
            *FACT_DISCLOSURE_MARKERS[fact.fact_id],
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(RoleLLMResponseError):
                    validate_night_turn_result(
                        NightAgentResult(
                            npc_id="npc_shi_hongmei",
                            model_id="malicious",
                            dialogue=candidate,
                        ),
                        expected_npc_id="npc_shi_hongmei",
                        forbidden_fact_signatures=forbidden,
                    )
        for fact_id, aliases in FACT_DISCLOSURE_MARKERS.items():
            for alias in aliases:
                if len(alias) >= 4:
                    continue
                with self.subTest(short_alias=(fact_id, alias)):
                    with self.assertRaises(RoleLLMResponseError):
                        validate_night_turn_result(
                            NightAgentResult(
                                npc_id="npc_shi_hongmei",
                                model_id="malicious",
                                rationale=alias,
                            ),
                            expected_npc_id="npc_shi_hongmei",
                            forbidden_fact_signatures=forbidden,
                        )
        with self.assertRaises(RoleLLMResponseError):
            validate_night_turn_result(
                replace(
                    NightAgentResult(
                        npc_id="npc_shi_hongmei", model_id="malicious"
                    ),
                    demands="优盘",
                ),
                expected_npc_id="npc_shi_hongmei",
                forbidden_fact_signatures={},
            )
        allowed = forbidden_fact_signatures(package.facts, {fact.fact_id})
        result = validate_night_turn_result(
            NightAgentResult(
                npc_id="npc_shi_hongmei",
                model_id="legal",
                dialogue=fact.text,
            ),
            expected_npc_id="npc_shi_hongmei",
            forbidden_fact_signatures=allowed,
        )
        self.assertEqual(fact.text, result.dialogue)

    def test_night_turn_safety_allows_unverified_player_claim_only_in_private_memory(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        fact = package.facts["fact_shi_usb"]
        forbidden = forbidden_fact_signatures(package.facts, set())

        result = validate_night_turn_result(
            NightAgentResult(
                npc_id="npc_shi_hongmei",
                model_id="real-model",
                dialogue="这件事我还要继续核实。",
                memory_candidate=f"玩家声称：{fact.text}，尚未验证。",
            ),
            expected_npc_id="npc_shi_hongmei",
            forbidden_fact_signatures=forbidden,
            allow_unverified_memory_claims=True,
        )

        self.assertIn("尚未验证", result.memory_candidate or "")

    def setUp(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v2",
            repository="memory",
            role_llm_provider="none",
        )
        self.container = build_container(settings)
        self.client = TestClient(create_app(settings, self.container))
        self.headers = {"X-Account-ID": "acct_gameplay_v2"}
        response = self.client.post(
            "/api/game/session",
            json={
                "client_request_id": "gameplay-v2-new-0001",
                "origin_id": "technical",
            },
            headers=self.headers,
        )
        self.assertEqual(201, response.status_code, response.text)
        self.state = response.json()
        self.session_id = self.state["session_id"]

    def action(self, payload: dict) -> dict:
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            json=payload,
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def resolve_d1(self) -> dict:
        pending = self.state["pending_decision"]
        self.state = self.action({
            "input_mode": "decision",
            "client_action_id": "gameplay-v2-d1-decision",
            "state_version": self.state["state_version"],
            "decision_id": pending["decision_id"],
            "option_id": pending["option_ids"][0],
        })["visible_state"]
        return self.state

    def reach_d2_open(self) -> dict:
        self.resolve_d1()
        self.state = read_available_story(self.client, self.session_id, self.headers, "v2-d1")["visible_state"]
        response = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            json={
                "client_action_id": "gameplay-v2-d1-end",
                "state_version": self.state["state_version"],
                "active_rest": False,
            },
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        self.state = response.json()["visible_state"]
        pending = self.state["pending_decision"]
        self.state = self.action({
            "input_mode": "decision",
            "client_action_id": "gameplay-v2-d2-decision",
            "state_version": self.state["state_version"],
            "decision_id": pending["decision_id"],
            "option_id": pending["option_ids"][0],
        })["visible_state"]
        return self.state

    def test_resource_action_quote_and_atomic_execution(self) -> None:
        self.resolve_d1()
        quote = self.client.post(
            f"/api/game/session/{self.session_id}/actions/quote",
            json={
                "state_version": self.state["state_version"],
                "action_id": "convene_leadership_meeting",
                "target_ids": [],
                "parameters": {"topic": "搬迁进度"},
            },
            headers=self.headers,
        )
        self.assertEqual(200, quote.status_code, quote.text)
        quotation = quote.json()
        self.assertEqual(2, quotation["cost_action_points"])
        self.assertEqual(0, quotation["direct_budget_cost"])
        payload = {
            "input_mode": "resource_action",
            "client_action_id": "gameplay-v2-resource-0001",
            "state_version": quotation["state_version"],
            "action_id": "convene_leadership_meeting",
            "target_ids": [],
            "parameters": {"topic": "搬迁进度"},
            "quote_id": quotation["quote_id"],
        }
        first = self.action(payload)
        second = self.action(payload)
        self.assertEqual(first, second)
        self.assertEqual(6, first["visible_state"]["ledger"]["action_points"]["remaining"])
        self.assertEqual(7800, first["visible_state"]["ledger"]["budget"]["remaining"])
        stale = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            json={**payload, "client_action_id": "gameplay-v2-resource-stale-0001"},
            headers=self.headers,
        )
        self.assertEqual(409, stale.status_code, stale.text)
        unchanged = self.client.get(
            f"/api/game/session/{self.session_id}", headers=self.headers
        ).json()
        self.assertEqual(6, unchanged["ledger"]["action_points"]["remaining"])
        self.assertEqual(7800, unchanged["ledger"]["budget"]["remaining"])
        review = self.client.get(
            f"/api/game/session/{self.session_id}/review", headers=self.headers
        ).json()
        self.assertEqual("召开班子会", review["action_timeline"][0]["name"])

    def test_v2_conversation_cannot_be_completed_by_tool_or_zero_turn_exit(self) -> None:
        self.reach_d2_open()
        points_before = self.state["ledger"]["action_points"]["remaining"]
        bypass = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            json={
                "input_mode": "tool",
                "client_action_id": "gameplay-v2-bypass-0001",
                "state_version": self.state["state_version"],
                "action_id": "home_visit",
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            },
            headers=self.headers,
        )
        self.assertEqual(409, bypass.status_code, bypass.text)
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-wu-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        ended = self.action({
            "input_mode": "conversation_end",
            "client_action_id": "gameplay-v2-wu-end-0001",
            "state_version": started["state_version"],
            "conversation_id": started["conversation"]["conversation_id"],
        })
        self.assertEqual("incomplete", ended["completion_status"])
        self.assertEqual(
            points_before,
            ended["visible_state"]["ledger"]["action_points"]["remaining"],
        )
        internal = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertNotIn("flag_wu_first_talk_completed", internal.flags)
        blocked = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            json={
                "client_action_id": "gameplay-v2-d2-blocked-end",
                "state_version": ended["state_version"],
            },
            headers=self.headers,
        )
        self.assertEqual(409, blocked.status_code, blocked.text)

    def test_single_npc_conversation_streams_and_commits_once(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-stream-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        with self.client.stream(
            "POST",
            f"/api/game/session/{self.session_id}/action/stream",
            headers=self.headers,
            json={
                "input_mode": "free_text",
                "client_action_id": "gameplay-v2-stream-turn-0001",
                "state_version": started["state_version"],
                "conversation_id": started["conversation"]["conversation_id"],
                "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                "target_npc_id": "npc_wu_xiuying",
                "player_text": "我会先核对公开底账，请告诉我你最担心的问题。",
            },
        ) as response:
            self.assertEqual(200, response.status_code)
            events = [json.loads(line) for line in response.iter_lines() if line]
        self.assertEqual(
            [
                "stream_start",
                "npc_thinking_start",
                "npc_thinking_end",
                "npc_start",
            ],
            [item["type"] for item in events[:4]],
        )
        self.assertEqual("npc_end", events[-2]["type"])
        self.assertEqual("complete", events[-1]["type"])
        deltas = [item["delta"] for item in events if item["type"] == "npc_delta"]
        result = events[-1]["result"]
        self.assertEqual(result["npc_reply"]["text"], "".join(deltas))
        self.assertEqual(started["state_version"] + 1, result["state_version"])
        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(1, stored.active_conversation.turn_count)

    def test_thinking_start_is_observable_while_model_call_is_still_running(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-live-thinking-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        entered = Event()
        release = Event()
        original = self.container.actions._npc_turns._gateway

        class BlockingGateway:
            def run_turn(inner_self, context):
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("test did not release model")
                return original.run_turn(context)

        self.container.actions._npc_turns._gateway = BlockingGateway()
        received: Queue[dict] = Queue()
        failure: Queue[BaseException] = Queue()

        def consume() -> None:
            try:
                command = ActionRequest(
                    input_mode="free_text",
                    client_action_id="gameplay-v2-live-thinking-turn-0001",
                    state_version=started["state_version"],
                    conversation_id=started["conversation"]["conversation_id"],
                    opportunity_id="opp_d02_wu_xiuying_first_talk",
                    target_npc_id="npc_wu_xiuying",
                    player_text="请说明你现在最担心的搬迁问题。",
                ).to_command()
                self.container.actions.execute(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    command=command,
                    stream_event=received.put,
                )
            except BaseException as exc:  # pragma: no cover - reported below
                failure.put(exc)

        worker = Thread(target=consume, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2), "model call was not reached")
            first = received.get(timeout=1)
            self.assertEqual("npc_thinking_start", first["type"])
            self.assertEqual("npc_wu_xiuying", first["npc_id"])
            self.assertFalse(release.is_set(), "thinking start arrived only after release")
        finally:
            release.set()
            worker.join(5)
            self.container.actions._npc_turns._gateway = original
        if not failure.empty():
            raise failure.get()

    def test_stream_disconnect_cancels_unacked_worker_without_partial_commit(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-disconnect-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        before = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        cancelled = Event()
        events: Queue[dict] = Queue()
        failure: Queue[BaseException] = Queue()

        def emit(event: dict) -> None:
            events.put(event)
            if event["type"] == "_npc_reply_ready":
                cancelled.set()

        def consume() -> None:
            try:
                command = ActionRequest(
                    input_mode="free_text",
                    client_action_id="gameplay-v2-disconnect-turn-0001",
                    state_version=started["state_version"],
                    conversation_id=started["conversation"]["conversation_id"],
                    opportunity_id="opp_d02_wu_xiuying_first_talk",
                    target_npc_id="npc_wu_xiuying",
                    player_text="请说明你现在最担心的搬迁问题。",
                ).to_command()
                self.container.actions.execute(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    command=command,
                    stream_event=emit,
                    stream_cancelled=cancelled.is_set,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                failure.put(exc)

        worker = Thread(target=consume, daemon=True)
        worker.start()
        worker.join(1)
        self.assertFalse(worker.is_alive(), "disconnected stream worker leaked")
        error = failure.get_nowait()
        self.assertIsInstance(error, ConnectionAbortedError)
        self.assertEqual(
            ["npc_thinking_start", "npc_thinking_end", "_npc_reply_ready"],
            [event["type"] for event in list(events.queue)],
        )
        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(before.state_version, stored.state_version)
        self.assertEqual(before.game_state.action_points, stored.game_state.action_points)
        self.assertEqual(0, stored.active_conversation.turn_count)
        self.assertIsNone(stored.processing_action_id)

    def test_disconnect_during_blocked_model_releases_reservation_and_fences_late_worker(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-blocked-disconnect-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        before = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        original = self.container.actions._npc_turns._gateway
        entered = Event()
        release = Event()
        cancelled = Event()
        events: Queue[dict] = Queue()
        failure: Queue[BaseException] = Queue()
        client_action_id = "gameplay-v2-blocked-disconnect-turn-0001"

        class BlockingGateway:
            def run_turn(inner_self, context):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release blocked model")
                return original.run_turn(context)

        self.container.actions._npc_turns._gateway = BlockingGateway()

        def consume() -> None:
            try:
                command = ActionRequest(
                    input_mode="free_text",
                    client_action_id=client_action_id,
                    state_version=started["state_version"],
                    conversation_id=started["conversation"]["conversation_id"],
                    opportunity_id="opp_d02_wu_xiuying_first_talk",
                    target_npc_id="npc_wu_xiuying",
                    player_text="请说明你现在最担心的搬迁问题。",
                ).to_command()
                self.container.actions.execute(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    command=command,
                    stream_event=events.put,
                    stream_cancelled=cancelled.is_set,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                failure.put(exc)

        worker = Thread(target=consume, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2), "model call was not reached")
            self.assertEqual("npc_thinking_start", events.get(timeout=1)["type"])
            reserved = self.container.sessions.get_owned(
                self.session_id, "acct_gameplay_v2"
            )
            operation_id = reserved.processing_action_id
            self.assertIsNotNone(operation_id)
            operation = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            self.assertEqual(OperationStatus.PROCESSING, operation.status)

            cancelled.set()
            released = self.container.actions.abort_stream_operation(
                account_id="acct_gameplay_v2",
                session_id=self.session_id,
                client_action_id=client_action_id,
            )
            self.assertTrue(released)
            self.assertTrue(worker.is_alive(), "test model must still be blocked")
            aborted = self.container.sessions.get_owned(
                self.session_id, "acct_gameplay_v2"
            )
            self.assertIsNone(aborted.processing_action_id)
            self.assertEqual(before.state_version, aborted.state_version)
            self.assertEqual(
                before.game_state.action_points,
                aborted.game_state.action_points,
            )
            self.assertEqual(0, aborted.active_conversation.turn_count)
            operation = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            self.assertEqual(OperationStatus.FAILED_RETRYABLE, operation.status)

            late_session = reserved
            late_session.processing_action_id = None
            late_session.state_version += 1
            with self.assertRaises(StateVersionConflictError):
                self.container.actions._transactions.finish_operation(
                    late_session,
                    expected_version=before.state_version,
                    operation=replace(
                        operation,
                        status=OperationStatus.SUCCEEDED,
                        response={"late": True},
                    ),
                )

            follow_up = self.container.actions.execute(
                account_id="acct_gameplay_v2",
                session_id=self.session_id,
                command=ActionRequest(
                    input_mode="conversation_end",
                    client_action_id="gameplay-v2-after-abort-end-0001",
                    state_version=aborted.state_version,
                    conversation_id=started["conversation"]["conversation_id"],
                ).to_command(),
            )
            self.assertEqual(OperationStatus.SUCCEEDED.value, follow_up["status"])
            self.assertEqual(aborted.state_version + 1, follow_up["state_version"])
        finally:
            release.set()
            worker.join(3)
            self.container.actions._npc_turns._gateway = original

        self.assertFalse(worker.is_alive(), "late model worker did not unwind")
        self.assertIsInstance(failure.get_nowait(), ConnectionAbortedError)
        after_late_return = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(follow_up["state_version"], after_late_return.state_version)
        self.assertEqual(
            before.game_state.action_points,
            after_late_return.game_state.action_points,
        )
        self.assertIsNone(after_late_return.active_conversation)
        self.assertIsNone(after_late_return.processing_action_id)
        operation = self.container.operations.get(
            "acct_gameplay_v2", self.session_id, client_action_id
        )
        self.assertEqual(OperationStatus.FAILED_RETRYABLE, operation.status)

    def test_retry_lease_survives_old_worker_aba_cleanup_and_settles_once(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-aba-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        before = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        original = self.container.actions._npc_turns._gateway
        old_entered = Event()
        old_release = Event()
        old_cancelled = StreamCancellation()
        retry_entered = Event()
        retry_release = Event()
        old_failure: Queue[BaseException] = Queue()
        retry_failure: Queue[BaseException] = Queue()
        retry_result: Queue[dict] = Queue()
        call_lock = Lock()
        call_count = 0
        client_action_id = "gameplay-v2-aba-turn-0001"

        class TwoAttemptBlockingGateway:
            def run_turn(inner_self, context):
                nonlocal call_count
                with call_lock:
                    call_count += 1
                    attempt = call_count
                if attempt == 1:
                    old_entered.set()
                    if not old_release.wait(5):
                        raise TimeoutError("test did not release old model")
                elif attempt == 2:
                    retry_entered.set()
                    if not retry_release.wait(5):
                        raise TimeoutError("test did not release retry model")
                else:  # pragma: no cover - duplicate settlement guard
                    raise AssertionError(f"unexpected model attempt {attempt}")
                return original.run_turn(context)

        def command(*, retry: bool):
            return ActionRequest(
                input_mode="free_text",
                client_action_id=client_action_id,
                state_version=started["state_version"],
                conversation_id=started["conversation"]["conversation_id"],
                opportunity_id="opp_d02_wu_xiuying_first_talk",
                target_npc_id="npc_wu_xiuying",
                player_text="请说明你现在最担心的搬迁问题。",
                retry=retry,
            ).to_command()

        def old_consume() -> None:
            try:
                self.container.actions.execute(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    command=command(retry=False),
                    stream_event=lambda event: None,
                    stream_cancelled=old_cancelled.is_set,
                    stream_cancel_register=old_cancelled.add_callback,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                old_failure.put(exc)

        def retry_consume() -> None:
            try:
                retry_result.put(self.container.actions.execute(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    command=command(retry=True),
                    stream_event=lambda event: (
                        event.get("acknowledged").set()
                        if event.get("acknowledged") is not None else None
                    ),
                ))
            except BaseException as exc:  # pragma: no cover - asserted below
                retry_failure.put(exc)

        self.container.actions._npc_turns._gateway = TwoAttemptBlockingGateway()
        old_worker = Thread(target=old_consume, daemon=True)
        retry_worker = Thread(target=retry_consume, daemon=True)
        old_worker.start()
        try:
            self.assertTrue(old_entered.wait(2), "old model call was not reached")
            old_operation = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            old_cancelled.cancel()
            aborted_operation = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            self.assertEqual(
                OperationStatus.FAILED_RETRYABLE, aborted_operation.status
            )

            retry_worker.start()
            self.assertTrue(retry_entered.wait(2), "retry model call was not reached")
            retried_operation = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            retry_reservation = self.container.sessions.get_owned(
                self.session_id, "acct_gameplay_v2"
            ).processing_action_id
            self.assertEqual(old_operation.operation_id, retried_operation.operation_id)

            old_release.set()
            old_worker.join(2)
            self.assertFalse(old_worker.is_alive(), "old worker did not unwind")
            self.assertIsInstance(old_failure.get_nowait(), ConnectionAbortedError)

            still_processing = self.container.operations.get(
                "acct_gameplay_v2", self.session_id, client_action_id
            )
            still_reserved = self.container.sessions.get_owned(
                self.session_id, "acct_gameplay_v2"
            )
            self.assertEqual(OperationStatus.PROCESSING, still_processing.status)
            self.assertEqual(retry_reservation, still_reserved.processing_action_id)

            retry_release.set()
            retry_worker.join(3)
        finally:
            old_release.set()
            retry_release.set()
            old_worker.join(1)
            retry_worker.join(1)
            self.container.actions._npc_turns._gateway = original

        self.assertFalse(retry_worker.is_alive(), "retry worker did not finish")
        self.assertTrue(retry_failure.empty(), list(retry_failure.queue))
        result = retry_result.get_nowait()
        after = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(OperationStatus.SUCCEEDED.value, result["status"])
        self.assertEqual(before.state_version + 1, after.state_version)
        self.assertEqual(
            before.game_state.action_points - 1,
            after.game_state.action_points,
        )
        self.assertEqual(1, after.active_conversation.turn_count)
        self.assertEqual(2, call_count)

    def test_stream_model_error_ends_thinking_and_does_not_commit_partial_turn(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-error-stream-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        before = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        original = self.container.actions._npc_turns._gateway

        class FailingGateway:
            def run_turn(inner_self, context):
                raise ConnectionError("private provider detail must not escape")

        self.container.actions._npc_turns._gateway = FailingGateway()
        try:
            with self.client.stream(
                "POST",
                f"/api/game/session/{self.session_id}/action/stream",
                headers=self.headers,
                json={
                    "input_mode": "free_text",
                    "client_action_id": "gameplay-v2-error-stream-turn-0001",
                    "state_version": started["state_version"],
                    "conversation_id": started["conversation"]["conversation_id"],
                    "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                    "target_npc_id": "npc_wu_xiuying",
                    "player_text": "请说明你现在最担心的搬迁问题。",
                },
            ) as response:
                self.assertEqual(200, response.status_code)
                events = [json.loads(line) for line in response.iter_lines() if line]
        finally:
            self.container.actions._npc_turns._gateway = original
        self.assertEqual(
            ["stream_start", "npc_thinking_start", "npc_thinking_end", "error"],
            [event["type"] for event in events],
        )
        self.assertEqual("NPC_RESPONSE_UNAVAILABLE", events[-1]["code"])
        self.assertEqual("对方暂时无法回应，请稍后重试。", events[-1]["message"])
        self.assertNotIn("private provider", json.dumps(events, ensure_ascii=False))
        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(before.state_version, stored.state_version)
        self.assertEqual(before.game_state.action_points, stored.game_state.action_points)
        self.assertEqual(0, stored.active_conversation.turn_count)
        self.assertIsNone(stored.processing_action_id)

    def test_night_dialogues_keeps_scripted_night_and_morning_brief(self) -> None:
        self.resolve_d1()
        self.state = read_available_story(self.client, self.session_id, self.headers, "v2-night-d1")["visible_state"]
        response = self.client.post(
            f"/api/game/session/{self.session_id}/end-day",
            json={
                "client_action_id": "gameplay-v2-night-brief-0001",
                "state_version": self.state["state_version"],
                "active_rest": False,
            },
            headers=self.headers,
        )
        self.assertEqual(200, response.status_code, response.text)
        night_response = self.client.get(
            f"/api/game/session/{self.session_id}/night-dialogues",
            headers=self.headers,
        )
        self.assertEqual(200, night_response.status_code, night_response.text)
        nights = night_response.json()["nights"]
        self.assertEqual(1, len(nights))
        self.assertTrue(nights[0]["morning_brief"])
        self.assertLessEqual(len(nights[0]["morning_brief"]), 3)
        self.assertEqual({"story_day", "morning_brief"}, set(nights[0]))
        self.assertNotIn("agent_exchanges", nights[0])

    def test_unrelated_player_text_is_rejected_without_advancing_conversation(self) -> None:
        self.reach_d2_open()
        started = self.action({
            "input_mode": "conversation_start",
            "client_action_id": "gameplay-v2-review-start-0001",
            "state_version": self.state["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        before = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        ).npc_states["npc_wu_xiuying"]
        rejected = self.action({
            "input_mode": "free_text",
            "client_action_id": "gameplay-v2-review-turn-0001",
            "state_version": started["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
            "conversation_id": started["conversation"]["conversation_id"],
            "player_text": "请给我写一段代码",
        })

        self.assertEqual("请输入与本游戏相关的话语", rejected["narrative"])
        self.assertEqual(0, rejected["conversation"]["turn_count"])
        internal = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(before, internal.npc_states["npc_wu_xiuying"])
        self.assertFalse(any(
            item.get("type") == "conversation_turn"
            and item.get("conversation_id") == started["conversation"]["conversation_id"]
            for item in internal.logs
        ))

    def test_overtime_requires_zero_points_and_is_once_per_day(self) -> None:
        internal = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        internal.pending_decision = None
        internal.game_state = replace(
            internal.game_state,
            action_points=0,
            points_spent_today=8,
        )
        self.container.sessions.save(internal, expected_version=internal.state_version)
        response = self.client.post(
            f"/api/game/session/{self.session_id}/action",
            json={"input_mode": "overtime", "client_action_id": "retired-overtime-0001",
                  "state_version": internal.state_version, "parameters": {"points": 3}},
            headers=self.headers,
        )
        self.assertEqual(409, response.status_code, response.text)
        self.assertIn("加班机制已取消", response.text)
        stored = self.container.sessions.get_owned(self.session_id, "acct_gameplay_v2")
        self.assertEqual(0, stored.game_state.action_points)

    def test_flag_trust_derivation_is_once_only_and_hidden(self) -> None:
        internal = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        internal.flags.add("flag_wu_alliance")
        service = TrustDerivationService()
        service.apply(internal, package)
        first = internal.npc_states["npc_wu_xiuying"].trust_score
        service.apply(internal, package)
        self.assertEqual(70, first)
        self.assertEqual(first, internal.npc_states["npc_wu_xiuying"].trust_score)
        visible = self.client.get(
            f"/api/game/session/{self.session_id}", headers=self.headers
        )
        self.assertNotIn("trust_score", visible.text)

    def test_zhang_li_uses_all_registered_chapter_three_explicit_effects(self) -> None:
        internal = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        service = TrustDerivationService()
        original = internal.npc_states["npc_zhang_li"]

        def derived(
            decision_id: str,
            option_id: str,
            *,
            flags: set[str] | None = None,
            story_day: int = 31,
        ) -> int:
            internal.game_state = replace(internal.game_state, story_day=story_day)
            internal.logs = [{
                "type": "decision",
                "story_day": story_day,
                "decision_id": decision_id,
                "option_id": option_id,
            }]
            internal.flags = set(flags or ())
            internal.npc_states["npc_zhang_li"] = replace(
                original,
                trust_score=40,
                trust_locked=False,
                trust_effects_applied=frozenset(),
            )
            service.apply(internal, package)
            return internal.npc_states["npc_zhang_li"].trust_score

        self.assertTrue(50 <= derived("dp3_01", "a") <= 55)
        self.assertTrue(35 <= derived("dp3_01", "b") <= 37)
        self.assertTrue(43 <= derived("dp3_08", "a") <= 45)
        self.assertTrue(
            55 <= derived("dp3_08", "a", flags={"孙强倒戈"}) <= 62
        )
        self.assertTrue(
            28
            <= derived("dp3_02", "c", flags={"自查落空"}, story_day=32)
            <= 36
        )

        sorting = package.trust_rules["explicit_decision_effects"]["npc_zhang_li"]
        sorting = {
            key: value for key, value in sorting.items()
            if key.startswith("dp3_07:")
        }
        self.assertEqual(24, len(sorting))
        for key, bounds in sorting.items():
            position = key.split(":", 1)[1].split("_").index("a")
            self.assertEqual(
                ([8, 12], [3, 5], [-8, -5], [-18, -12])[position],
                bounds,
            )

        # D45 撤离后不再接受新的显式结算。
        self.assertEqual(40, derived("dp3_10", "a", story_day=46))

    def test_d43_tea_disposition_is_a_required_auditable_scene(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        day = package.story_day(43)
        self.assertIn("dp3_tea_disposition", day.decision_ids)
        decision = package.decisions["dp3_tea_disposition"]
        self.assertEqual({"a", "b", "c"}, {
            item.option_id for item in decision.options
        })
        self.assertIn("收下茶叶", decision.option("b").effects.open_flags)
        self.assertEqual(
            (8, 12),
            decision.option("c").effects.metric_deltas["cadre_discontent"],
        )
        self.assertEqual(
            [3, 5],
            package.trust_rules["explicit_decision_effects"]["npc_zhang_li"][
                "dp3_tea_disposition:c"
            ],
        )

    def test_household_registry_is_closed_and_household_actions_reject_npc_ids(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        self.assertTrue(all(
            package.resource_actions[item.action_id].executor_kind == "conversation"
            for item in package.interaction_opportunities
        ))
        self.assertEqual(36, len(package.households))
        self.assertEqual(23, len(package.limited_household_signatories))
        self.assertEqual(
            23,
            len({item.name for item in package.limited_household_signatories}),
        )
        wu_batch = package.contract_batch_for_representative("npc_wu_xiuying")
        self.assertEqual(
            ["WU-01", "WU-02", "WU-03", "WU-04", "WU-05", "WU-06"],
            [item.household_id for item in wu_batch],
        )
        self.assertFalse(wu_batch[0].is_shadow_household)
        self.assertTrue(all(item.is_shadow_household for item in wu_batch[1:]))
        self.assertEqual(
            "刘玉芬",
            package.limited_signatory_for("WU-02").name,
        )
        self.assertIsNone(package.limited_signatory_for("WU-01"))
        self.assertEqual(122, sum(item.registered_population for item in package.households))
        self.assertEqual(106, sum(item.actual_residents for item in package.households))
        self.assertEqual(
            4745, sum(item.legal_residential_area_m2 for item in package.households)
        )
        desk = self.client.get(
            f"/api/game/session/{self.session_id}/desk", headers=self.headers
        )
        self.assertEqual(200, desk.status_code, desk.text)
        self.assertEqual(36, len(desk.json()["household_registry"]))
        registry = {
            item["household_id"]: item
            for item in desk.json()["household_registry"]
        }
        self.assertEqual("吴秀英", registry["WU-01"]["signatory_name"])
        self.assertEqual("刘玉芬", registry["WU-02"]["signatory_name"])
        self.assertNotIn("representative_group", desk.text)
        self.assertNotIn("signing_lock_flag", desk.text)
        self.assertNotIn("refusal_trigger", desk.text)

        self.resolve_d1()
        quote = self.client.post(
            f"/api/game/session/{self.session_id}/actions/quote",
            json={
                "state_version": self.state["state_version"],
                "action_id": "party_member_demonstration",
                "target_ids": ["NING-01"],
                "parameters": {"public_matter": "政策公示"},
            },
            headers=self.headers,
        )
        self.assertEqual(200, quote.status_code, quote.text)
        invalid = self.client.post(
            f"/api/game/session/{self.session_id}/actions/quote",
            json={
                "state_version": self.state["state_version"],
                "action_id": "party_member_demonstration",
                "target_ids": ["npc_ning_dehai"],
                "parameters": {"public_matter": "政策公示"},
            },
            headers=self.headers,
        )
        self.assertEqual(409, invalid.status_code, invalid.text)

    def test_npc_contact_windows_follow_first_visible_story_appearance(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        by_id = {
            item.opportunity_id: item
            for item in package.interaction_opportunities
        }
        expected_windows = {
            "opp_31_zhang_li_contact": (31, 45),
            "opp_03_zhou_kuiyuan_contact": (51, 75),
            "opp_03_zhou_mancang_contact": (48, 69),
            "opp_03_he_tiezhu_contact": (56, 89),
            "opp_03_tan_laoliu_contact": (26, 60),
            "opp_03_ma_changshun_contact": (15, 75),
            "opp_03_ning_dehai_contact": (70, 71),
            "opp_03_yuan_guilan_contact": (5, 60),
            "opp_03_yang_bo_contact": (54, 60),
            "opp_03_lao_juetou_contact": (77, 77),
            "opp_03_miao_xiwang_contact": (78, 78),
            "opp_03_deng_shouben_contact": (84, 84),
            "opp_03_zheng_xiangdong_contact": (1, 89),
            "opp_16_feng_jingzhi_contact": (17, 80),
            "opp_46_he_xingbang_contact": (78, 83),
            "opp_59_cui_guanglin_contact": (38, 45),
        }
        for opportunity_id, expected in expected_windows.items():
            item = by_id[opportunity_id]
            self.assertEqual(expected, (item.day_min, item.day_max))

        self.assertEqual(
            {"opp_d03_zhou_dashan_first_talk"},
            {
                item.opportunity_id
                for item in package.interaction_opportunities
                if item.day_min == 3
            },
        )
        self.assertEqual(
            frozenset({"民生优先"}),
            by_id["opp_03_deng_shouben_contact"].requires_flags,
        )

        self.assertIn("第二十四日", package.story_day(24).opening_blocks[0].text)
        self.assertIn("何铁柱", package.story_day(42).opening_blocks[0].text)
        self.assertIn("周奎元", package.story_day(51).opening_blocks[0].text)
        self.assertIn("杨波", package.story_day(54).opening_blocks[0].text)
        self.assertIn("何铁柱", package.story_day(56).opening_blocks[0].text)
        self.assertIn("顾克明", package.story_day(59).opening_blocks[0].text)
        self.assertNotIn("还有十三天", package.story_day(59).opening_blocks[0].text)
        self.assertIn("再次", package.story_day(74).opening_blocks[0].text)
        self.assertIn("老倔头", package.story_day(77).opening_blocks[0].text)
        self.assertIn("邓守本", package.story_day(84).opening_blocks[0].text)

    def test_d75_night_settles_ma_before_freezing_first_batch(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=75,
            days_left=16,
            signed_households=3,
        )
        session.flags.add("马长顺待自然触发")
        effects = ScriptedEffectService(ScriptedDeltaResolver())

        NightSimulationService(effects).run_night(session, package)

        self.assertEqual(3, session.game_state.signed_households)
        self.assertEqual(
            3, session.d75_settlement_snapshot.first_batch_signed_count
        )
        self.assertTrue(any(
            item.get("type") == "scripted_signing_intent"
            for item in session.logs
        ))
        self.assertNotIn(
            "ma_changshun",
            session.d75_settlement_snapshot.pending_group_limits,
        )
        self.assertTrue(
            session.signing_batch_summary()["roster_locked"]
        )

    def test_d29_night_agents_talk_choose_and_settle_once(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=29,
            days_left=62,
        )
        effects = ScriptedEffectService(ScriptedDeltaResolver())
        service = NightSimulationService(
            effects,
            night_llm=DeterministicRoleLLMGateway(),
        )

        record = service.run_night(session, package)

        exchange = record["agent_exchanges"][0]
        self.assertEqual(4, len(record["contact_selections"]))
        self.assertEqual(
            2,
            sum(bool(item["contact_ids"]) for item in record["contact_selections"]),
        )
        self.assertEqual(2, len(record["contact_responses"]))
        self.assertTrue(all(
            item["response"] == "accept"
            for item in record["contact_responses"]
        ))
        self.assertEqual(4, len(exchange["transcript"]))
        self.assertEqual(
            {"npc_qian_wei", "npc_zhao_jianguo"},
            {item["speaker_npc_id"] for item in exchange["transcript"]},
        )
        self.assertTrue(all(item["model_id"] for item in exchange["transcript"]))
        self.assertEqual(2, len(exchange["action_proposals"]))
        self.assertEqual(
            ["night_unify_story"], exchange["executed_action_ids"]
        )
        self.assertIn("协调对外说法", exchange["public_summary"])
        morning_text = "\n".join(record["morning_card"])
        self.assertIn("夜间动向：", morning_text)
        self.assertIn("相互掩护迹象", morning_text)
        for private_detail in (
            "钱伟",
            "赵建国",
            "这件事不能再有两套说法",
        ):
            self.assertNotIn(private_detail, morning_text)
        self.assertIn("攻守同盟已成", session.flags)
        self.assertIs(record, service.run_night(session, package))
        self.assertEqual(1, len(session.night_logs))
        self.container.sessions.save(
            session, expected_version=session.state_version
        )
        debug_response = self.client.get(
            f"/api/game/session/{self.session_id}/night-dialogues",
            headers=self.headers,
        )
        self.assertEqual(200, debug_response.status_code)
        public_night = debug_response.json()["nights"][0]
        self.assertEqual({"story_day", "morning_brief"}, set(public_night))
        self.assertNotIn("agent_exchanges", public_night)
        self.assertNotIn("contact_selections", public_night)
        review_response = self.client.get(
            f"/api/game/session/{self.session_id}/review",
            headers=self.headers,
        )
        self.assertNotIn("agent_exchanges", review_response.text)
        self.assertNotIn("contact_selections", review_response.text)
        self.assertNotIn("contact_responses", review_response.text)
        forbidden = self.client.get(
            f"/api/game/session/{self.session_id}/night-dialogues",
            headers={"X-Account-ID": "acct_other"},
        )
        self.assertEqual(404, forbidden.status_code)

    def test_d29_technical_night_failure_keeps_day_state_retryable_and_uncommitted(
        self,
    ) -> None:
        class InvalidNightGateway:
            def run_night_turn(self, context):
                raise RoleLLMResponseError("测试用非法夜间响应")

        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        session.pending_decision = None
        session.story_beat_id = "beat_d29_m2"
        session.game_state = replace(
            session.game_state,
            story_day=29,
            days_left=62,
        )
        self.container.sessions.save(
            session, expected_version=session.state_version
        )
        self.container.end_days._nights = NightSimulationService(
            ScriptedEffectService(ScriptedDeltaResolver()),
            night_llm=InvalidNightGateway(),
        )

        read_available_story(self.client, self.session_id, self.headers, "v2-night-d29")
        session = self.container.sessions.get_owned(self.session_id, "acct_gameplay_v2")

        before_game_state = session.game_state
        before_flags = set(session.flags)
        before_feed = list(session.narrative_feed)
        with self.assertRaises(RoleLLMResponseRetryableError):
            self.container.end_days.end_day(
                account_id="acct_gameplay_v2",
                session_id=self.session_id,
                client_action_id="test-d29-invalid-night-end-day",
                state_version=session.state_version,
            )

        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        self.assertEqual(before_game_state, stored.game_state)
        self.assertEqual(before_flags, set(stored.flags))
        self.assertEqual(before_feed, stored.narrative_feed)
        self.assertEqual([], stored.night_logs)
        self.assertIsNone(stored.processing_action_id)
        operation = self.container.operations.get(
            "acct_gameplay_v2",
            self.session_id,
            "test-d29-invalid-night-end-day",
        )
        self.assertIsNotNone(operation)
        self.assertEqual(OperationStatus.FAILED_RETRYABLE, operation.status)

    def test_d29_npc_can_choose_zero_to_multiple_contacts(self) -> None:
        class MultiContactGateway(DeterministicRoleLLMGateway):
            def run_night_turn(self, context):
                if context.phase == "contact_selection":
                    contacts = (
                        ("npc_zhao_jianguo", "npc_sun_qiang")
                        if context.npc_id == "npc_qian_wei"
                        else ()
                    )
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="fake-multi",
                        contact_ids=contacts,
                        rationale="按当前风险决定联系人数量。",
                    )
                return super().run_night_turn(context)

        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=29,
            days_left=62,
        )
        service = NightSimulationService(
            ScriptedEffectService(ScriptedDeltaResolver()),
            night_llm=MultiContactGateway(),
        )

        record = service.run_night(session, package)

        self.assertEqual(
            ["npc_zhao_jianguo", "npc_sun_qiang"],
            record["contact_selections"][0]["contact_ids"],
        )
        self.assertTrue(all(
            not item["contact_ids"]
            for item in record["contact_selections"][1:]
        ))
        self.assertEqual(
            3, len(record["agent_exchanges"][0]["participant_ids"])
        )
        self.assertEqual(6, len(record["agent_exchanges"][0]["transcript"]))

    def test_rejected_night_invitation_does_not_force_npc_into_dialogue(self) -> None:
        class RejectingGateway(DeterministicRoleLLMGateway):
            def run_night_turn(self, context):
                if context.phase == "contact_selection":
                    contacts = (
                        ("npc_zhao_jianguo", "npc_sun_qiang")
                        if context.npc_id == "npc_qian_wei"
                        else ()
                    )
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="fake-response",
                        contact_ids=contacts,
                        rationale="尝试召集相关人员。",
                    )
                if (
                    context.phase == "contact_response"
                    and context.npc_id == "npc_sun_qiang"
                ):
                    return NightAgentResult(
                        npc_id=context.npc_id,
                        model_id="fake-response",
                        contact_response="reject",
                        rationale="今晚见面会让自己过早暴露。",
                    )
                return super().run_night_turn(context)

        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=29,
            days_left=62,
        )
        record = NightSimulationService(
            ScriptedEffectService(ScriptedDeltaResolver()),
            night_llm=RejectingGateway(),
        ).run_night(session, package)

        responses = {
            item["invited_npc_id"]: item["response"]
            for item in record["contact_responses"]
        }
        self.assertEqual("accept", responses["npc_zhao_jianguo"])
        self.assertEqual("reject", responses["npc_sun_qiang"])
        self.assertEqual(
            ["npc_qian_wei", "npc_zhao_jianguo"],
            record["agent_exchanges"][0]["participant_ids"],
        )
        self.assertNotIn(
            "npc_sun_qiang",
            {
                item["speaker_npc_id"]
                for item in record["agent_exchanges"][0]["transcript"]
            },
        )

    def test_forced_group_rejects_unknown_fact_before_stream_or_transcript(self) -> None:
        delegate = self.container.group_conversations._gateway
        package = self.container.packages.get("pkg_gameplay_v2")
        secret = package.facts["fact_lead_287"].text

        class LeakingGateway:
            def __getattr__(self, name):
                return getattr(delegate, name)

            def run_night_turn(self, context):
                result = delegate.run_night_turn(context)
                return replace(result, dialogue=secret)

        self.container.group_conversations._gateway = LeakingGateway()
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        assert session is not None
        session.pending_decision = None
        session.active_group_conversation = ForcedGroupConversation(
            conversation_id="group_security_boundary",
            conversation_type="cadre_meeting",
            initiator_npc_id="npc_zhao_jianguo",
            participant_ids=("npc_zhao_jianguo", "npc_sun_qiang"),
            agenda="讨论次日公开工作安排",
            demands=("明确责任",),
            urgency="high",
            story_day=session.game_state.story_day,
            status="active",
        )
        self.container.sessions.save(session, expected_version=session.state_version)

        with self.client.stream(
            "POST",
            f"/api/game/session/{self.session_id}/group-conversation/turn/stream",
            headers=self.headers,
            json={
                "client_action_id": "group-secret-boundary-0001",
                "state_version": session.state_version,
                "player_text": "请说明公开工作安排。",
            },
        ) as response:
            self.assertEqual(200, response.status_code)
            events = [json.loads(line) for line in response.iter_lines() if line]
        public = json.dumps(events, ensure_ascii=False)
        self.assertNotIn(secret, public)
        self.assertFalse(any(item["type"] == "npc_start" for item in events))
        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        assert stored is not None and stored.active_group_conversation is not None
        self.assertEqual([], stored.active_group_conversation.transcript)
        self.assertIsNone(stored.processing_action_id)

    def test_group_turn_disconnect_retry_fences_late_worker_without_ghost_reply(self) -> None:
        delegate = self.container.group_conversations._gateway
        first_started = Event()
        retry_started = Event()
        release_first = Event()
        release_retry = Event()
        counter_lock = Lock()
        calls = 0

        class TwoAttemptGateway:
            def __getattr__(self, name):
                return getattr(delegate, name)

            def run_night_turn(self, context):
                nonlocal calls
                with counter_lock:
                    calls += 1
                    call_number = calls
                if call_number == 1:
                    first_started.set()
                    release_first.wait(5)
                elif call_number == 2:
                    retry_started.set()
                    release_retry.wait(5)
                return replace(
                    delegate.run_night_turn(context),
                    dialogue=f"第{call_number}次尝试的公开答复。",
                )

        self.container.group_conversations._gateway = TwoAttemptGateway()
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        assert session is not None
        session.pending_decision = None
        session.active_group_conversation = ForcedGroupConversation(
            conversation_id="group_attempt_lease",
            conversation_type="cadre_meeting",
            initiator_npc_id="npc_zhao_jianguo",
            participant_ids=("npc_zhao_jianguo",),
            agenda="讨论次日公开工作安排",
            demands=("明确责任",),
            urgency="high",
            story_day=session.game_state.story_day,
            status="active",
        )
        initial_version = session.state_version
        self.container.sessions.save(session, expected_version=initial_version)
        client_action_id = "group-attempt-lease-0001"
        abort_callbacks = []
        first_events: list[dict] = []
        retry_events: list[dict] = []
        outcomes: dict[str, object] = {}

        def emit(target: list[dict], event: dict) -> None:
            target.append(event)
            acknowledged = event.get("acknowledged")
            if acknowledged is not None:
                acknowledged.set()

        def first_worker() -> None:
            try:
                outcomes["first"] = self.container.group_conversations.reply(
                    account_id="acct_gameplay_v2",
                    session_id=self.session_id,
                    client_action_id=client_action_id,
                    state_version=initial_version,
                    player_text="请说明公开安排。",
                    stream_event=lambda event: emit(first_events, event),
                    stream_cancel_register=abort_callbacks.append,
                )
            except Exception as exc:
                outcomes["first_error"] = exc

        first_thread = Thread(target=first_worker)
        first_thread.start()
        self.assertTrue(first_started.wait(2))
        duplicate = self.container.group_conversations.reply(
            account_id="acct_gameplay_v2",
            session_id=self.session_id,
            client_action_id=client_action_id,
            state_version=initial_version,
            player_text="请说明公开安排。",
        )
        self.assertEqual("processing", duplicate["status"])
        with self.assertRaises((SessionBusyError, StateVersionConflictError)):
            self.container.group_conversations.reply(
                account_id="acct_gameplay_v2",
                session_id=self.session_id,
                client_action_id="group-competing-key-0001",
                state_version=initial_version,
                player_text="另一项并发请求。",
            )
        self.assertEqual(1, len(abort_callbacks))
        self.assertTrue(abort_callbacks[0]())

        def retry_worker() -> None:
            outcomes["retry"] = self.container.group_conversations.reply(
                account_id="acct_gameplay_v2",
                session_id=self.session_id,
                client_action_id=client_action_id,
                state_version=initial_version,
                player_text="请说明公开安排。",
                retry=True,
                stream_event=lambda event: emit(retry_events, event),
            )

        retry_thread = Thread(target=retry_worker)
        retry_thread.start()
        self.assertTrue(retry_started.wait(2))
        release_retry.set()
        retry_thread.join(5)
        self.assertFalse(retry_thread.is_alive())
        release_first.set()
        first_thread.join(5)
        self.assertFalse(first_thread.is_alive())

        self.assertIn("first_error", outcomes)
        self.assertEqual("succeeded", outcomes["retry"]["status"])
        self.assertFalse(any(
            item.get("type") == "_npc_reply_ready" for item in first_events
        ))
        self.assertEqual(1, sum(
            item.get("type") == "_npc_reply_ready" for item in retry_events
        ))
        stored = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        assert stored is not None and stored.active_group_conversation is not None
        self.assertEqual(initial_version + 1, stored.state_version)
        self.assertIsNone(stored.processing_action_id)
        self.assertEqual(1, stored.active_group_conversation.turn_count)
        self.assertEqual(2, len(stored.active_group_conversation.transcript))
        operation = self.container.operations.get(
            "acct_gameplay_v2", self.session_id, client_action_id
        )
        assert operation is not None
        self.assertEqual(OperationStatus.SUCCEEDED, operation.status)
        self.assertEqual(2, operation.attempt_count)
        self.assertEqual(stored.state_version, operation.response["state_version"])
        snapshot = self.container.snapshots.current_for_session(stored)
        assert snapshot is not None
        self.assertEqual(stored.state_version, snapshot.state_version)

    def test_post75_story_progress_does_not_create_unsigned_contracts(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.pending_decision = None
        session.game_state = replace(
            session.game_state,
            story_day=75,
            days_left=16,
            signed_households=20,
        )
        effects = ScriptedEffectService(ScriptedDeltaResolver())
        effects.freeze_d75_roster(session, package)
        session.game_state = replace(
            session.game_state,
            story_day=77,
            days_left=14,
        )
        option = package.decisions["dp6_02"].option("b")
        settlement = ActionService._effective_effects(option, session.flags)

        effects.apply(
            session,
            package,
            settlement,
            source_id="dp6_02:b",
        )
        self.assertEqual(20, session.game_state.signed_households)
        self.assertEqual(20, session.audited_signed_households())
        self.assertEqual([], session.household_settlement_entries)

        restored = decode_session(encode_session(session))
        self.assertEqual(20, restored.audited_signed_households())
        self.assertEqual([], restored.household_settlement_entries)

    def test_post75_script_nodes_cannot_replace_individual_contracts(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.game_state = replace(
            session.game_state,
            story_day=75,
            days_left=16,
            signed_households=20,
        )
        effects = ScriptedEffectService(ScriptedDeltaResolver())
        effects.freeze_d75_roster(session, package)
        illegal = ScriptedEffects(
            ledger_deltas={"signed_households": (1, 1)}
        )
        session.game_state = replace(
            session.game_state,
            story_day=80,
            days_left=11,
        )
        effects.apply(
            session,
            package,
            illegal,
            source_id="unregistered_late_signing",
        )
        self.assertEqual(20, session.game_state.signed_households)
        session.game_state = replace(
            session.game_state,
            story_day=90,
            days_left=1,
        )
        effects.apply(
            session,
            package,
            illegal,
            source_id="dp6_02:b",
        )
        self.assertEqual(20, session.game_state.signed_households)

    def test_d86_zhou_recovery_requires_willing_to_wait(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        branches = package.story_day(86).night_conditional_effects
        zhou_without_prepay = branches[2]

        self.assertFalse(
            zhou_without_prepay.matches(set(), {}, {"signed_households": 20})
        )
        self.assertTrue(
            zhou_without_prepay.matches(
                {"周大山肯等"}, {}, {"signed_households": 20}
            )
        )
        self.assertFalse(
            zhou_without_prepay.matches(
                {"周大山已寒心"}, {}, {"signed_households": 20}
            )
        )

    def test_d75_registers_he_only_when_a_prior_unresolved_path_exists(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.game_state = replace(
            session.game_state,
            story_day=75,
            days_left=16,
            signed_households=20,
        )
        effects = ScriptedEffectService(ScriptedDeltaResolver())
        session.flags.add("血铅补实")
        snapshot = effects.freeze_d75_roster(session, package)
        self.assertNotIn("he_tiezhu", snapshot.pending_group_limits)

        session.d75_settlement_snapshot = None
        session.flags.add("何铁柱肯再谈")
        snapshot = effects.freeze_d75_roster(session, package)
        self.assertEqual(4, snapshot.pending_group_limits["he_tiezhu"])

    def test_d90_projection_rejects_aggregate_ledger_mismatch(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        session.game_state = replace(
            session.game_state,
            story_day=75,
            days_left=16,
            signed_households=20,
        )
        ScriptedEffectService(ScriptedDeltaResolver()).freeze_d75_roster(
            session, package
        )
        session.game_state = replace(
            session.game_state,
            story_day=90,
            days_left=0,
            signed_households=21,
        )
        with self.assertRaises(ContentValidationError):
            EndingAxisProjector().project(session)

    def test_resource_writes_require_player_or_contract_provenance(self) -> None:
        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        package = self.container.packages.get("pkg_gameplay_v2")
        service = ScriptedEffectService(ScriptedDeltaResolver())
        spend = ScriptedEffects(
            ledger_deltas={"budget_remaining": (-100, -100)}
        )
        budget_before = session.game_state.budget_remaining

        with self.assertRaises(ContentValidationError):
            service.apply(
                session,
                package,
                spend,
                source_id="night:npc_action:test",
            )
        self.assertEqual(budget_before, session.game_state.budget_remaining)

        service.apply(
            session,
            package,
            spend,
            source_id="dp_test:a",
            resource_authority="player_choice",
            resource_reference="dp_test:a",
        )
        self.assertEqual(
            budget_before - 100, session.game_state.budget_remaining
        )
        self.assertEqual(300, session.game_state.budget_paid)
        entry = session.resource_ledger_entries[-1]
        self.assertEqual("player_choice", entry["source_type"])
        self.assertEqual("dp_test:a", entry["source_id"])
        self.assertEqual(-100, entry["delta"])

        restored = decode_session(encode_session(session))
        self.assertEqual(
            session.resource_ledger_entries,
            restored.resource_ledger_entries,
        )

    def test_tan_and_yuan_recovery_only_unlock_contract_negotiation(self) -> None:
        package = self.container.packages.get("pkg_gameplay_v2")
        opportunities = {
            item.opportunity_id: item
            for item in package.interaction_opportunities
        }
        expected = {
            "opp_d53_tan_laoliu_paid_recovery": {
                "谭老六愿意进入拟约",
                "谭老六核心矛盾已缓解",
                "谭老六合同批次可发起",
            },
            "opp_d55_yuan_guilan_paid_recovery": {
                "袁桂兰愿意进入拟约",
                "袁桂兰核心矛盾已缓解",
                "袁桂兰合同批次可发起",
            },
        }
        for opportunity_id, flags in expected.items():
            effects = opportunities[opportunity_id].completion_effects
            self.assertNotIn("signed_households", effects.ledger_deltas)
            self.assertTrue(flags.issubset(effects.open_flags))
            self.assertFalse(any(
                flag.endswith(("已入账", "已签"))
                for flag in effects.open_flags
            ))

        for decision_id, option_id in (("dp4_06", "a"), ("ev4_01", "a")):
            option = package.decisions[decision_id].option(option_id)
            for branch in option.conditional_effects:
                self.assertNotIn(
                    "signed_households", branch.effects.ledger_deltas
                )
                self.assertFalse(any(
                    flag.endswith(("已入账", "已签"))
                    for flag in branch.effects.open_flags
                ))

        session = self.container.sessions.get_owned(
            self.session_id, "acct_gameplay_v2"
        )
        ScriptedEffectService(ScriptedDeltaResolver()).apply(
            session,
            package,
            ScriptedEffects(open_flags=frozenset({"谭老六已入账"})),
            source_id="legacy_tan_recovery",
        )
        self.assertNotIn("谭老六已入账", session.flags)


if __name__ == "__main__":
    unittest.main()
