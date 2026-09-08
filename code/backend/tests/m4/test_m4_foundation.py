from __future__ import annotations

import base64
from pathlib import Path
import os
import shutil
from types import SimpleNamespace
import tempfile
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.auth_service import AuthService
from serious_game_backend.application.consent_service import ConsentService
from serious_game_backend.application.experiment_assignment_service import (
    ExperimentAssignmentService,
)
from serious_game_backend.application.model_input_policy import ModelInputPolicy
from serious_game_backend.application.research_projection_service import (
    ResearchProjectionService,
)
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.action import ActionCommand
from serious_game_backend.domain.consent import (
    SCOPE_RESEARCH_RAW_TEXT,
    SCOPE_RESEARCH_STRUCTURED,
    SCOPE_THIRD_PARTY_MODEL,
    ConsentDocument,
)
from serious_game_backend.domain.enums import ActionInputMode
from serious_game_backend.domain.errors import (
    AuthenticationRequiredError,
    ConsentRequiredError,
    CSRFValidationError,
)
from serious_game_backend.domain.identity import ADMIN, PLAYER
from serious_game_backend.domain.research import ResearchSubject
from serious_game_backend.infrastructure.crypto import FieldCipher
from serious_game_backend.infrastructure.migrations import (
    MigrationError,
    SqliteMigrationRunner,
)
from serious_game_backend.infrastructure.privacy import PIIRedactor
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryAccountRepository,
    InMemoryAuthSessionRepository,
    InMemoryConsentRepository,
    InMemoryExperimentAssignmentRepository,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def consent_service() -> tuple[ConsentService, InMemoryConsentRepository]:
    repository = InMemoryConsentRepository()
    service = ConsentService(
        repository,
        active_version="study-v1",
        active_document_hash="sha256:study-v1",
    )
    service.publish(ConsentDocument(
        consent_version="study-v1",
        document_hash="sha256:study-v1",
        model_provider="test-provider",
        processing_region="test-region",
        retention_days_raw_text=30,
    ))
    return service, repository


class M4FoundationTests(unittest.TestCase):
    def test_auth_session_csrf_rbac_and_revocation(self) -> None:
        accounts = InMemoryAccountRepository()
        sessions = InMemoryAuthSessionRepository()
        service = AuthService(accounts, sessions, session_ttl_seconds=3600)
        service.create_account(
            account_id="acct_admin", username="admin", password="correct horse battery",
            roles=frozenset({PLAYER, ADMIN}),
        )
        token, csrf, principal, _ = service.login("admin", "correct horse battery")
        self.assertEqual("acct_admin", service.authenticate(token).account_id)
        self.assertIn("system:admin", principal.permissions)
        service.verify_csrf(principal, csrf)
        with self.assertRaises(CSRFValidationError):
            service.verify_csrf(principal, "wrong")
        service.logout(token)
        with self.assertRaises(AuthenticationRequiredError):
            service.authenticate(token)

    def test_consent_gate_withdrawal_and_pii_minimization(self) -> None:
        service, _ = consent_service()
        policy = ModelInputPolicy(
            service, PIIRedactor(), require_model_consent=True
        )
        with self.assertRaises(ConsentRequiredError):
            policy.prepare("acct_1", "联系我 13800138000")
        record = service.sign(
            account_id="acct_1", consent_version="study-v1",
            scopes=frozenset({SCOPE_THIRD_PARTY_MODEL}),
        )
        prepared = policy.prepare(
            "acct_1", "电话 13800138000，邮箱 player@example.com"
        )
        self.assertEqual(record.consent_record_id, prepared.consent_record_id)
        self.assertNotIn("13800138000", prepared.text)
        self.assertNotIn("player@example.com", prepared.text)
        self.assertEqual(("email", "phone"), prepared.pii_types)
        service.withdraw(account_id="acct_1", reason="退出")
        with self.assertRaises(ConsentRequiredError):
            policy.prepare("acct_1", "再次发送")

    def test_field_cipher_binds_purpose_and_round_trips(self) -> None:
        key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
        cipher = FieldCipher(key, key_id="test-key-v1")
        envelope = cipher.encrypt_text("敏感原文", purpose="research_player_text")
        self.assertNotIn("敏感原文", envelope)
        self.assertEqual(
            "敏感原文",
            cipher.decrypt_text(envelope, purpose="research_player_text"),
        )
        with self.assertRaises(ValueError):
            cipher.decrypt_text(envelope, purpose="npc_memory")

    def test_experiment_assignment_is_server_side_and_immutable(self) -> None:
        repository = InMemoryExperimentAssignmentRepository()
        service = ExperimentAssignmentService(
            repository, enabled=True, experiment_id="exp_1",
            groups=("control", "treatment"), assignment_salt="server-secret",
        )
        subject = ResearchSubject("rs_1", "acct_1")
        first = service.assign(
            subject, environment="production", package_content_hash="sha256:pkg",
            model_id="qwen3.6-plus", prompt_version="role-turn-v1",
        )
        second = service.assign(
            subject, environment="production", package_content_hash="sha256:other",
            model_id="other", prompt_version="other",
        )
        self.assertEqual(first, second)
        self.assertIn(first.experiment_group_id, {"control", "treatment"})
        self.assertEqual("sha256:pkg", first.package_content_hash)

    def test_research_projection_never_writes_plain_raw_text(self) -> None:
        service, _ = consent_service()
        service.sign(
            account_id="acct_1", consent_version="study-v1",
            scopes=frozenset({SCOPE_RESEARCH_STRUCTURED}),
        )
        cipher = FieldCipher(
            base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"), key_id="test"
        )
        projection = ResearchProjectionService(
            service, public_id_salt="public-id-salt", field_cipher=cipher
        )
        session = SimpleNamespace(
            research_subject_id="rs_1", account_id="acct_1", session_id="sess_private",
            experiment_id="exp_1", experiment_group_id="control",
            game_state=SimpleNamespace(story_day=2),
        )
        command = ActionCommand(
            input_mode=ActionInputMode.FREE_TEXT,
            client_action_id="action-0001", state_version=1,
            opportunity_id="opp", target_npc_id="npc", player_text="我的真名是某某",
        )
        event = projection.build_action_event(session, command, {"kind": "free_text"})
        self.assertIsNone(event.raw_text_ciphertext)
        self.assertNotIn("acct_1", event.session_public_id)
        service.withdraw(account_id="acct_1")
        service.sign(
            account_id="acct_1", consent_version="study-v1",
            scopes=frozenset({SCOPE_RESEARCH_STRUCTURED, SCOPE_RESEARCH_RAW_TEXT}),
        )
        event = projection.build_action_event(session, command, {"kind": "free_text"})
        self.assertIsNotNone(event.raw_text_ciphertext)
        self.assertNotIn(command.player_text, event.raw_text_ciphertext)

    def test_sqlite_migrations_have_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migrations = root / "migrations"
            shutil.copytree(BACKEND_ROOT / "migrations" / "sqlite", migrations)
            database = root / "test.db"
            SqliteMigrationRunner(database, migrations).migrate()
            migration = migrations / "0003_research_outbox.sql"
            migration.write_text(
                migration.read_text(encoding="utf-8") + "\n-- changed", encoding="utf-8"
            )
            with self.assertRaises(MigrationError):
                SqliteMigrationRunner(database, migrations).migrate()

    def test_production_cookie_auth_and_csrf_middleware(self) -> None:
        runtime_settings = Settings(
            environment="test", content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory", role_llm_provider="none",
        )
        runtime = build_container(runtime_settings)
        runtime.auth.create_account(
            account_id="acct_player", username="player",
            password="correct horse battery", roles=frozenset({PLAYER}),
        )
        production_view = Settings(
            environment="production", content_root=runtime_settings.content_root,
            repository="memory", role_llm_provider="none", auth_cookie_secure=True,
        )
        client = TestClient(
            create_app(production_view, runtime), base_url="https://testserver"
        )
        login = client.post(
            "/api/auth/login",
            json={"username": "player", "password": "correct horse battery"},
        )
        self.assertEqual(200, login.status_code, login.text)
        self.assertEqual("acct_player", client.get("/api/auth/me").json()["account_id"])
        denied = client.post(
            "/api/game/session",
            json={"client_request_id": "m4-session-001", "origin_id": "technical"},
        )
        self.assertEqual(403, denied.status_code)
        configured = client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json={"mode": "server_default"},
        )
        self.assertEqual(200, configured.status_code, configured.text)
        allowed = client.post(
            "/api/game/session",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json={"client_request_id": "m4-session-001", "origin_id": "technical"},
        )
        self.assertEqual(201, allowed.status_code, allowed.text)

        # Logout is an idempotent recovery boundary: an expired or already
        # revoked cookie must still be cleared instead of trapping the client
        # behind authentication middleware.
        runtime.auth.logout(client.cookies.get(production_view.auth_cookie_name))
        logged_out = client.post("/api/auth/logout")
        self.assertEqual(204, logged_out.status_code, logged_out.text)
        self.assertIsNone(client.cookies.get(production_view.auth_cookie_name))

    def test_local_sqlite_registration_login_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                environment="test", content_root=BACKEND_ROOT / "content" / "packages",
                repository="sqlite", database_path=Path(directory) / "auth.db",
                auth_required=True, allow_self_registration=True,
                auth_cookie_secure=False, role_llm_provider="none",
            )
            client = TestClient(create_app(settings), base_url="http://testserver")
            too_short = client.post("/api/auth/register", json={
                "username": "short-password", "password": "1234567",
            })
            self.assertEqual(422, too_short.status_code)
            registered = client.post("/api/auth/register", json={
                "username": "local-player", "password": "pass1234",
            })
            self.assertEqual(201, registered.status_code, registered.text)
            self.assertEqual(["player"], registered.json()["roles"])
            duplicate = TestClient(
                create_app(settings), base_url="http://testserver"
            ).post("/api/auth/register", json={
                "username": "LOCAL-PLAYER", "password": "pass1234",
            })
            self.assertEqual(409, duplicate.status_code)
            denied = client.post("/api/game/session", json={
                "client_request_id": "local-auth-session", "origin_id": "technical",
            })
            self.assertEqual(403, denied.status_code)
            allowed = client.post(
                "/api/game/session",
                headers={"X-CSRF-Token": registered.json()["csrf_token"]},
                json={"client_request_id": "local-auth-session", "origin_id": "technical"},
            )
            self.assertEqual(201, allowed.status_code, allowed.text)

            restarted = TestClient(create_app(settings), base_url="http://testserver")
            login = restarted.post("/api/auth/login", json={
                "username": "local-player", "password": "pass1234",
            })
            self.assertEqual(200, login.status_code, login.text)
            latest = restarted.get("/api/game/session/latest-active")
            self.assertEqual(allowed.json()["session_id"], latest.json()["session_id"])


if __name__ == "__main__":
    unittest.main()
