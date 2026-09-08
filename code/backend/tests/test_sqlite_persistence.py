from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from dataclasses import replace
import sqlite3
from unittest.mock import patch
from contextlib import contextmanager

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.application.hashing import canonical_request_hash
from serious_game_backend.config import Settings
from serious_game_backend.domain.action import ActionCommand
from serious_game_backend.domain.enums import ActionInputMode, OperationStatus
from serious_game_backend.domain.errors import StateVersionConflictError
from serious_game_backend.domain.operation import OperationRecord
from serious_game_backend.infrastructure.repositories.sqlite import (
    SqliteRuntimeStore,
    SqliteRuntimeTransactionRepository,
)
from serious_game_backend.infrastructure.repositories.mysql import MySQLSnapshotRepository
from serious_game_backend.infrastructure.repositories.codec import (
    decode_operation,
    encode_operation,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class SqlitePersistenceTests(unittest.TestCase):
    def test_memory_governance_commit_is_atomic_and_success_snapshot_matches(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        runtime = build_container(settings)
        session = runtime.game_sessions.start_session(
            account_id="acct_memory_atomic",
            package_id="pkg_gameplay_v3",
            client_request_id="memory-atomic-session",
            origin_id="mayor",
        )
        updated = runtime.sessions.get_owned(session.session_id, "acct_memory_atomic")
        assert updated is not None
        updated.state_version += 1
        updated.flags.add("flag_atomic_effect")
        updated.touch()
        history_before = runtime.snapshots.list_history(
            "acct_memory_atomic", session.session_id
        )
        with patch.object(
            runtime.snapshots,
            "_insert_snapshot",
            side_effect=RuntimeError("injected memory snapshot failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected memory"):
                runtime.snapshots.commit_session_snapshot(
                    updated,
                    expected_version=session.state_version,
                    snapshot_type="auto",
                    reason="governance_operation_committed",
                )
        failed = runtime.sessions.get_owned(session.session_id, "acct_memory_atomic")
        assert failed is not None
        self.assertEqual(session.state_version, failed.state_version)
        self.assertNotIn("flag_atomic_effect", failed.flags)
        self.assertEqual(
            [item.snapshot_id for item in history_before],
            [
                item.snapshot_id for item in runtime.snapshots.list_history(
                    "acct_memory_atomic", session.session_id
                )
            ],
        )
        snapshot = runtime.snapshots.commit_session_snapshot(
            updated,
            expected_version=session.state_version,
            snapshot_type="auto",
            reason="governance_operation_committed",
        )
        stored = runtime.sessions.get_owned(session.session_id, "acct_memory_atomic")
        assert stored is not None
        self.assertEqual(stored.state_version, snapshot.state_version)
        self.assertEqual(snapshot.snapshot_id, runtime.snapshots.current_for_session(stored).snapshot_id)

    def test_mysql_governance_adapter_uses_one_transaction_for_session_and_snapshot(self) -> None:
        class Cursor:
            def __init__(self, store):
                self.store = store
                self.rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params):
                normalized = " ".join(sql.split()).lower()
                self.store.statements.append(normalized)
                if normalized.startswith("select snapshot_id"):
                    self._row = None
                    self.rowcount = 0
                elif normalized.startswith("update game_sessions"):
                    self.rowcount = 1
                    self.store.staged["version"] = params[1]
                    self.store.staged["session_payload"] = params[8]
                elif normalized.startswith("insert into game_snapshots"):
                    self.store.staged["snapshot_versions"] = [params[7]]
                    if self.store.fail_insert:
                        raise RuntimeError("injected mysql snapshot failure")

            def fetchone(self):
                return self._row

        class Connection:
            def __init__(self, store):
                self.store = store

            def cursor(self):
                return Cursor(self.store)

        class Store:
            def __init__(self, fail_insert):
                self.fail_insert = fail_insert
                self.state = {"version": 1, "snapshot_versions": []}
                self.staged = {}
                self.statements = []
                self.commits = 0
                self.rollbacks = 0

            def protect_json(self, value, *, purpose):
                return {"purpose": purpose, "value": value}

            @contextmanager
            def connect(self):
                self.staged = {}
                try:
                    yield Connection(self)
                    self.state.update(self.staged)
                    self.commits += 1
                except Exception:
                    self.staged = {}
                    self.rollbacks += 1
                    raise

        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        runtime = build_container(settings)
        session = runtime.game_sessions.start_session(
            account_id="acct_mysql_adapter",
            package_id="pkg_gameplay_v3",
            client_request_id="mysql-adapter-session",
            origin_id="mayor",
        )
        session.state_version = 2
        session.flags.add("flag_atomic_effect")
        session.touch()
        failing_store = Store(True)
        with self.assertRaisesRegex(RuntimeError, "injected mysql"):
            MySQLSnapshotRepository(failing_store).commit_session_snapshot(
                session,
                expected_version=1,
                snapshot_type="auto",
                reason="governance_operation_committed",
            )
        self.assertEqual({"version": 1, "snapshot_versions": []}, failing_store.state)
        self.assertEqual(0, failing_store.commits)
        self.assertEqual(1, failing_store.rollbacks)
        self.assertTrue(any(sql.startswith("update game_sessions") for sql in failing_store.statements))
        self.assertTrue(any(sql.startswith("insert into game_snapshots") for sql in failing_store.statements))

        success_store = Store(False)
        snapshot = MySQLSnapshotRepository(success_store).commit_session_snapshot(
            session,
            expected_version=1,
            snapshot_type="auto",
            reason="governance_operation_committed",
        )
        self.assertEqual(1, success_store.commits)
        self.assertEqual(2, success_store.state["version"])
        self.assertEqual([2], success_store.state["snapshot_versions"])
        self.assertEqual(2, snapshot.state_version)

    def test_governance_commit_rolls_back_session_when_snapshot_insert_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "governance-atomic.db"
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                default_package_id="pkg_gameplay_v3",
                repository="sqlite",
                database_path=database,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            client = TestClient(create_app(settings, runtime))
            headers = {"X-Account-ID": "acct_governance_atomic"}
            created = client.post(
                "/api/game/session",
                headers=headers,
                json={"client_request_id": "governance-atomic-session"},
            )
            self.assertEqual(201, created.status_code, created.text)
            session_id = created.json()["session_id"]
            before = runtime.sessions.get_owned(session_id, "acct_governance_atomic")
            assert before is not None
            before.pending_decision = None
            before.flags = {"flag_clan_map"}
            before.known_fact_ids.add("fact_clan_power_map")
            before.game_state = replace(
                before.game_state, story_day=2, days_left=89, action_points=8
            )
            runtime.sessions.save(before, expected_version=before.state_version)
            before = runtime.sessions.get_owned(session_id, "acct_governance_atomic")
            assert before is not None
            action = next(
                variant
                for family in client.get(
                    f"/api/game/session/{session_id}/actions", headers=headers
                ).json()["actions"]
                for variant in family["variants"]
                if variant["variant_id"] == "consult_county_archives"
            )
            payload = {
                "state_version": before.state_version,
                "action_kind": action["action_id"],
                "variant_id": action["variant_id"],
                "location_id": action["location_choices"][0]["location_id"],
                "archive_ids": [action["target_choices"][0]["target_id"]],
            }
            history_before = runtime.snapshots.list_history(
                "acct_governance_atomic", session_id
            )
            with patch(
                "serious_game_backend.infrastructure.repositories.sqlite._insert_snapshot",
                side_effect=RuntimeError("injected snapshot insert failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected snapshot"):
                    client.post(
                        f"/api/game/session/{session_id}/governance/actions",
                        headers=headers,
                        json=payload,
                    )
            failed = runtime.sessions.get_owned(session_id, "acct_governance_atomic")
            assert failed is not None
            self.assertEqual(before.state_version, failed.state_version)
            self.assertEqual(before.game_state.action_points, failed.game_state.action_points)
            self.assertEqual(before.governance_actions, failed.governance_actions)
            self.assertEqual(
                [item.snapshot_id for item in history_before],
                [
                    item.snapshot_id for item in runtime.snapshots.list_history(
                        "acct_governance_atomic", session_id
                    )
                ],
            )

            succeeded = client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=headers,
                json=payload,
            )
            self.assertEqual(201, succeeded.status_code, succeeded.text)
            stored = runtime.sessions.get_owned(session_id, "acct_governance_atomic")
            assert stored is not None
            self.assertEqual(1, len(stored.governance_actions))
            snapshot = runtime.snapshots.current_for_session(stored)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(stored.state_version, snapshot.state_version)

    def test_old_operation_payload_defaults_to_stable_reservation_owner(self) -> None:
        operation = OperationRecord(
            operation_id="legacy-operation",
            account_id="acct_legacy",
            session_id="session_legacy",
            client_action_id="legacy-action",
            request_hash="legacy-hash",
        )
        payload = encode_operation(operation)
        payload.pop("lease_token")

        restored = decode_operation(payload)

        self.assertEqual("", restored.lease_token)
        self.assertEqual(restored.operation_id, restored.reservation_id)

    def test_sqlite_finish_cas_rejects_old_lease_after_same_operation_retry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attempt-lease-cas.db"
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=database_path,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            session = runtime.game_sessions.start_session(
                account_id="acct_attempt_cas",
                package_id="pkg_backend_dev_v1",
                client_request_id="attempt-cas-new-game",
                origin_id="technical",
            )
            transactions = SqliteRuntimeTransactionRepository(
                SqliteRuntimeStore(database_path)
            )
            old = OperationRecord(
                operation_id="stable-operation-id",
                account_id="acct_attempt_cas",
                session_id=session.session_id,
                client_action_id="stable-client-action",
                request_hash="stable-hash",
                lease_token="old-attempt",
            )
            old_reserved = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            old_reserved.processing_action_id = old.reservation_id
            transactions.reserve_operation(
                old_reserved,
                expected_version=1,
                operation=old,
                create_operation=True,
            )
            aborted = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            aborted.processing_action_id = None
            transactions.finish_operation(
                aborted,
                expected_version=1,
                operation=replace(
                    old,
                    status=OperationStatus.FAILED_RETRYABLE,
                    error={"code": "DISCONNECTED"},
                ),
            )

            retried = replace(
                old,
                status=OperationStatus.PROCESSING,
                attempt_count=2,
                error=None,
                lease_token="new-attempt",
            )
            retry_reserved = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            retry_reserved.processing_action_id = retried.reservation_id
            transactions.reserve_operation(
                retry_reserved,
                expected_version=1,
                operation=retried,
                create_operation=False,
            )

            stale_completion = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            stale_completion.processing_action_id = None
            stale_completion.state_version = 2
            with self.assertRaises(StateVersionConflictError):
                transactions.finish_operation(
                    stale_completion,
                    expected_version=1,
                    operation=replace(
                        old,
                        status=OperationStatus.SUCCEEDED,
                        response={"stale": True},
                    ),
                )

            protected_session = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            protected_operation = runtime.operations.get(
                "acct_attempt_cas", session.session_id, "stable-client-action"
            )
            self.assertEqual(
                retried.reservation_id, protected_session.processing_action_id
            )
            self.assertEqual(OperationStatus.PROCESSING, protected_operation.status)
            self.assertEqual("new-attempt", protected_operation.lease_token)

            completed = runtime.sessions.get_owned(
                session.session_id, "acct_attempt_cas"
            )
            completed.processing_action_id = None
            completed.state_version = 2
            transactions.finish_operation(
                completed,
                expected_version=1,
                operation=replace(
                    retried,
                    status=OperationStatus.SUCCEEDED,
                    response={"state_version": 2},
                ),
            )
            self.assertEqual(
                OperationStatus.SUCCEEDED,
                runtime.operations.get(
                    "acct_attempt_cas", session.session_id, "stable-client-action"
                ).status,
            )

    def test_startup_recovers_expired_operation_lease_for_explicit_retry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "lease.db"
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=database,
                role_llm_provider="none",
                operation_lease_seconds=300,
            )
            runtime = build_container(settings)
            session = runtime.game_sessions.start_session(
                account_id="acct_lease",
                package_id="pkg_backend_dev_v1",
                client_request_id="lease-new-session",
                origin_id="technical",
            )
            command = ActionCommand(
                input_mode=ActionInputMode.DECISION,
                client_action_id="lease-action-0001",
                state_version=1,
                decision_id="ev1_01_reception_bag",
                option_id="a_reject_on_site",
            )
            operation = OperationRecord(
                operation_id="act_expired_lease",
                account_id="acct_lease",
                session_id=session.session_id,
                client_action_id=command.client_action_id,
                request_hash=canonical_request_hash(
                    {"session_id": session.session_id, **command.canonical_payload()}
                ),
                updated_at="2000-01-01T00:00:00+00:00",
            )
            reserved = runtime.sessions.get_owned(session.session_id, "acct_lease")
            reserved.processing_action_id = operation.operation_id
            transactions = SqliteRuntimeTransactionRepository(
                SqliteRuntimeStore(database)
            )
            transactions.reserve_operation(
                reserved,
                expected_version=1,
                operation=operation,
                create_operation=True,
            )

            restarted = build_container(settings)
            recovered_session = restarted.sessions.get_owned(
                session.session_id, "acct_lease"
            )
            self.assertIsNone(recovered_session.processing_action_id)
            recovered_operation = restarted.operations.get(
                "acct_lease", session.session_id, command.client_action_id
            )
            self.assertEqual(
                OperationStatus.FAILED_RETRYABLE, recovered_operation.status
            )
            retried = restarted.actions.execute(
                account_id="acct_lease",
                session_id=session.session_id,
                command=replace(command, retry=True),
            )
            self.assertEqual(2, retried["state_version"])
            self.assertEqual(
                2,
                len(
                    restarted.snapshots.list_history(
                        "acct_lease", session.session_id
                    )
                ),
            )

    def test_snapshot_history_manual_slot_and_load_survive_restart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "snapshots.db"
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=database,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            session = runtime.game_sessions.start_session(
                account_id="acct_snapshot_restart",
                package_id="pkg_backend_dev_v1",
                client_request_id="snapshot-restart-new",
                origin_id="technical",
            )
            first_save = runtime.saves.create_manual_save(
                account_id="acct_snapshot_restart",
                session_id=session.session_id,
                client_action_id="snapshot-manual-save-1",
                state_version=1,
                slot_number=1,
                display_name="开局",
                overwrite=False,
            )
            action = runtime.actions.execute(
                account_id="acct_snapshot_restart",
                session_id=session.session_id,
                command=ActionCommand(
                    input_mode=ActionInputMode.DECISION,
                    client_action_id="snapshot-action-1",
                    state_version=1,
                    decision_id="ev1_01_reception_bag",
                    option_id="a_reject_on_site",
                ),
            )
            runtime.saves.create_manual_save(
                account_id="acct_snapshot_restart",
                session_id=session.session_id,
                client_action_id="snapshot-manual-overwrite",
                state_version=action["state_version"],
                slot_number=1,
                display_name="行动后",
                overwrite=True,
            )

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    4,
                    connection.execute(
                        "select count(*) from runtime_game_snapshots"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

            restarted = build_container(settings)
            saves = restarted.saves.list_manual_saves(
                account_id="acct_snapshot_restart",
                session_id=session.session_id,
            )
            self.assertEqual(1, len(saves["manual_saves"]))
            self.assertEqual("行动后", saves["manual_saves"][0]["display_name"])
            restored_before_load = restarted.sessions.get_owned(
                session.session_id, "acct_snapshot_restart"
            )
            feed_count = len(restored_before_load.narrative_feed)
            package = restarted.packages.get(restored_before_load.package_id)
            restarted.story_flow.enter_current_day(restored_before_load, package)
            self.assertEqual(feed_count, len(restored_before_load.narrative_feed))
            loaded = restarted.saves.load_snapshot(
                account_id="acct_snapshot_restart",
                session_id=session.session_id,
                client_action_id="snapshot-load-1",
                state_version=2,
                snapshot_id=first_save["snapshot_id"],
                confirmed=True,
            )
            self.assertEqual(3, loaded["state_version"])
            self.assertEqual(first_save["snapshot_id"], loaded["loaded_from_snapshot_id"])

            after_second_restart = build_container(settings)
            restored = after_second_restart.game_sessions.get_owned(
                session.session_id, "acct_snapshot_restart"
            )
            self.assertEqual(3, restored.state_version)
            self.assertEqual(loaded["timeline_id"], restored.timeline_id)
            self.assertEqual(first_save["snapshot_id"], restored.loaded_from_snapshot_id)
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    5,
                    connection.execute(
                        "select count(*) from runtime_game_snapshots"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_restart_restores_m2_pending_decision_queue(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=Path(temp_dir) / "m2-queue.db",
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            session = runtime.game_sessions.start_session(
                account_id="acct_m2_restart",
                package_id="pkg_backend_dev_v1",
                client_request_id="m2-restart-new",
                origin_id="technical",
            )
            def choose(version, key, decision_id, option_id):
                return runtime.actions.execute(
                    account_id="acct_m2_restart",
                    session_id=session.session_id,
                    command=ActionCommand(
                        input_mode=ActionInputMode.DECISION,
                        client_action_id=key,
                        state_version=version,
                        decision_id=decision_id,
                        option_id=option_id,
                    ),
                )

            first = choose(1, "m2-r-d1", "ev1_01_reception_bag", "a_reject_on_site")
            d2 = runtime.end_days.end_day(
                account_id="acct_m2_restart", session_id=session.session_id,
                client_action_id="m2-r-end1", state_version=first["state_version"],
            )
            taskforce = choose(
                d2["state_version"], "m2-r-d2", "dp1_01_taskforce_faction_map",
                "c_public_rules_covert_check",
            )
            started = runtime.actions.execute(
                account_id="acct_m2_restart",
                session_id=session.session_id,
                command=ActionCommand(
                    input_mode=ActionInputMode.CONVERSATION_START,
                    client_action_id="m2-r-start",
                    state_version=taskforce["state_version"],
                    opportunity_id="opp_d02_wu_xiuying_first_talk",
                    target_npc_id="npc_wu_xiuying",
                ),
            )
            conversation_id = started["conversation"]["conversation_id"]
            talk = runtime.actions.execute(
                account_id="acct_m2_restart",
                session_id=session.session_id,
                command=ActionCommand(
                    input_mode=ActionInputMode.FREE_TEXT,
                    client_action_id="m2-r-talk",
                    state_version=started["state_version"],
                    conversation_id=conversation_id,
                    opportunity_id="opp_d02_wu_xiuying_first_talk",
                    target_npc_id="npc_wu_xiuying",
                    player_text="我先听您说。",
                ),
            )
            closed = runtime.actions.execute(
                account_id="acct_m2_restart",
                session_id=session.session_id,
                command=ActionCommand(
                    input_mode=ActionInputMode.CONVERSATION_END,
                    client_action_id="m2-r-close",
                    state_version=talk["state_version"],
                    conversation_id=conversation_id,
                ),
            )
            d3 = runtime.end_days.end_day(
                account_id="acct_m2_restart", session_id=session.session_id,
                client_action_id="m2-r-end2", state_version=closed["state_version"],
            )
            resolved = choose(
                d3["state_version"], "m2-r-dp102", "dp1_02", "a"
            )
            d5 = runtime.end_days.end_day(
                account_id="acct_m2_restart", session_id=session.session_id,
                client_action_id="m2-r-end3", state_version=resolved["state_version"],
            )
            self.assertEqual(
                "dp1_03",
                d5["visible_state"]["pending_decision"]["decision_id"],
            )

            restored_runtime = build_container(settings)
            restored = restored_runtime.sessions.get_owned(
                session.session_id, "acct_m2_restart"
            )
            self.assertEqual("dp1_03", restored.pending_decision.decision_id)
            self.assertEqual([], restored.pending_decision_queue)
            self.assertEqual(
                "未获取", restored.state_values["lead_roster_disposition"]
            )

    def test_operation_failure_rolls_back_session_and_operation_together(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "atomic.db"
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=database_path,
                role_llm_provider="none",
            )
            runtime = build_container(settings)
            session = runtime.game_sessions.start_session(
                account_id="acct_atomic",
                package_id="pkg_backend_dev_v1",
                client_request_id="atomic-new-game-1",
                origin_id="technical",
            )
            operation = OperationRecord(
                operation_id="atomic-operation-1",
                account_id="acct_atomic",
                session_id=session.session_id,
                client_action_id="atomic-client-action-1",
                request_hash="hash-1",
            )
            store = SqliteRuntimeStore(database_path)
            transactions = SqliteRuntimeTransactionRepository(store)
            reserved = runtime.sessions.get_owned(session.session_id, "acct_atomic")
            reserved.processing_action_id = operation.operation_id
            reserved.touch()
            transactions.reserve_operation(
                reserved,
                expected_version=1,
                operation=operation,
                create_operation=True,
            )

            with store.connect() as connection:
                connection.execute(
                    "delete from runtime_operations where operation_id = ?",
                    (operation.operation_id,),
                )
            completed = runtime.sessions.get_owned(session.session_id, "acct_atomic")
            completed.processing_action_id = None
            completed.state_version = 2
            completed.touch()
            completed_operation = replace(
                operation,
                status=OperationStatus.SUCCEEDED,
                response={"state_version": 2},
            )

            with self.assertRaisesRegex(ValueError, "operation does not exist"):
                transactions.finish_operation(
                    completed,
                    expected_version=1,
                    operation=completed_operation,
                )

            after_failure = runtime.sessions.get_owned(
                session.session_id, "acct_atomic"
            )
            self.assertEqual(1, after_failure.state_version)
            self.assertEqual(operation.operation_id, after_failure.processing_action_id)

    def test_restart_restores_session_operation_and_new_game_idempotency(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                environment="test",
                content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite",
                database_path=Path(temp_dir) / "runtime.db",
                role_llm_provider="none",
            )
            first_runtime = build_container(settings)
            session = first_runtime.game_sessions.start_session(
                account_id="acct_persistent",
                package_id="pkg_backend_dev_v1",
                client_request_id="persistent-new-game-1",
                origin_id="grassroots",
            )
            decision = ActionCommand(
                input_mode=ActionInputMode.DECISION,
                client_action_id="persistent-action-1",
                state_version=1,
                decision_id="ev1_01_reception_bag",
                option_id="c_return_next_day",
            )
            first_result = first_runtime.actions.execute(
                account_id="acct_persistent",
                session_id=session.session_id,
                command=decision,
            )
            self.assertEqual(2, first_result["state_version"])

            second_runtime = build_container(settings)
            restored = second_runtime.game_sessions.get_owned(
                session.session_id, "acct_persistent"
            )
            self.assertEqual(2, restored.state_version)
            self.assertEqual("grassroots", restored.origin_id)
            self.assertIsNone(restored.pending_decision)
            self.assertIn("flag_integrity_self_control", restored.flags)
            self.assertGreater(len(restored.narrative_feed), 0)

            replay = second_runtime.actions.execute(
                account_id="acct_persistent",
                session_id=session.session_id,
                command=decision,
            )
            self.assertEqual(first_result, replay)

            repeated_new = second_runtime.game_sessions.start_session(
                account_id="acct_persistent",
                package_id="pkg_backend_dev_v1",
                client_request_id="persistent-new-game-1",
                origin_id="grassroots",
            )
            self.assertEqual(session.session_id, repeated_new.session_id)
            latest = second_runtime.game_sessions.latest_active("acct_persistent")
            self.assertEqual(session.session_id, latest.session_id)


if __name__ == "__main__":
    unittest.main()
