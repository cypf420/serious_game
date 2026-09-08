from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.application.governance_service import GovernanceService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import PermissionDeniedError
from serious_game_backend.domain.identity import ADMIN, RESEARCHER, ROLE_PERMISSIONS, Principal
from serious_game_backend.domain.research import ResearchEvent
from serious_game_backend.infrastructure.repositories.governance_memory import InMemoryGovernanceRepository
from serious_game_backend.infrastructure.repositories.memory import InMemoryResearchEventRepository
from serious_game_backend.infrastructure.repositories.codec import dumps
from serious_game_backend.infrastructure.repositories.research_outbox import SqliteResearchOutboxRepository
from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore


def principal(account_id: str, roles: frozenset[str]) -> Principal:
    permissions: set[str] = set()
    for role in roles:
        permissions.update(ROLE_PERMISSIONS[role])
    return Principal(account_id, roles, frozenset(permissions), "auth")


class GovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events = InMemoryResearchEventRepository()
        for index in range(6):
            self.events.append(ResearchEvent(
                research_event_id=f"event_{index}", research_subject_id=f"rs_{index}",
                experiment_id="study", experiment_group_id="control",
                session_public_id=f"public_{index}", event_type="action",
                story_day=1, structured_payload={"accepted": True},
            ))
        self.repository = InMemoryGovernanceRepository(self.events)
        self.service = GovernanceService(self.repository, audit_salt="secret")
        self.researcher = principal("researcher_1", frozenset({RESEARCHER}))
        self.admin = principal("admin_1", frozenset({ADMIN}))

    def test_export_requires_independent_approval_and_whitelist(self) -> None:
        job = self.service.request_export(
            self.researcher, purpose="analysis", fields=("event_type", "story_day"),
            conditions={"experiment_id": "study"}, minimum_cell_size=5,
        )
        with self.assertRaises(PermissionDeniedError):
            self.service.approve_export(self.admin.__class__(
                self.researcher.account_id, self.admin.roles,
                self.admin.permissions, self.admin.auth_session_hash,
            ), job.export_job_id, purpose="approval")
        approved = self.service.approve_export(
            self.admin, job.export_job_id, purpose="ethics approval"
        )
        result = self.service.materialize_export(
            self.admin, approved.export_job_id, purpose="approved analysis"
        )
        self.assertEqual(6, result["row_count"])
        self.assertEqual({"event_type", "story_day"}, set(result["rows"][0]))
        self.assertEqual(3, len(self.repository.audits))

    def test_small_cells_are_suppressed(self) -> None:
        job = self.service.request_export(
            self.researcher, purpose="analysis", fields=("event_type",),
            conditions={}, minimum_cell_size=10,
        )
        self.service.approve_export(self.admin, job.export_job_id, purpose="approval")
        result = self.service.materialize_export(self.admin, job.export_job_id, purpose="download")
        self.assertEqual(0, result["row_count"])

    def test_subject_request_and_retention_are_audited(self) -> None:
        request = self.service.request_subject_action("acct_1", "access", "portable copy")
        completed = self.service.process_subject_action(
            self.admin, request.request_id, purpose="subject rights"
        )
        self.assertEqual("completed", completed.status)
        old = self.events._items[0]
        self.events._items[0] = old.__class__(**{
            **asdict(old), "raw_text_ciphertext": "cipher", "created_at": "2020-01-01T00:00:00+00:00"
        })
        result = self.service.apply_retention(
            self.admin, cutoff_at="2021-01-01T00:00:00+00:00",
            policy_version="retention-v1", purpose="scheduled cleanup",
        )
        self.assertEqual(1, result.raw_research_text_removed)
        self.assertIsNone(self.events._items[0].raw_text_ciphertext)

    def test_sqlite_outbox_is_idempotently_projected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteRuntimeStore(Path(directory) / "runtime.db")
            event = ResearchEvent(
                research_event_id="event_outbox", research_subject_id="rs_outbox",
                experiment_id="study", experiment_group_id="control",
                session_public_id="public", event_type="action", story_day=3,
                structured_payload={"ok": True},
            )
            with store.connect() as c:
                c.execute("insert into runtime_accounts values(?,?,?,?,?,?)", (
                    "acct", "player", 0, event.created_at, event.created_at,
                    dumps({"account_id":"acct","username":"player","password_hash":"x","roles":["player"],"disabled":False,"created_at":event.created_at,"updated_at":event.created_at}),
                ))
                c.execute("insert into runtime_research_subjects values(?,?,?,?)", (
                    "rs_outbox", "acct", None,
                    dumps({"research_subject_id":"rs_outbox","account_id":"acct","created_at":event.created_at,"retired_at":None}),
                ))
                c.execute("insert into runtime_research_outbox values(?,?,?,0,?,?)", (
                    event.research_event_id, event.research_subject_id, "pending",
                    event.created_at, dumps(asdict(event)),
                ))
            outbox = SqliteResearchOutboxRepository(store)
            self.assertEqual(1, outbox.drain())
            self.assertEqual(0, outbox.drain())
            with store.connect() as c:
                self.assertEqual(1, c.execute("select count(*) from runtime_research_events").fetchone()[0])

    def test_research_mysql_must_be_physically_separate(self) -> None:
        settings = Settings(
            repository="mysql", mysql_url="mysql://u:p@host/business",
            research_mysql_url="mysql://u:p@host/business", research_enabled=True,
            experiment_id="study", experiment_groups=("a",),
            experiment_assignment_salt="secret",
        )
        with self.assertRaisesRegex(ValueError, "physically separate"):
            settings.validate()

    def test_governance_api_requires_cookie_csrf_and_two_people(self) -> None:
        backend_root = Path(__file__).resolve().parents[2]
        runtime_settings = Settings(
            environment="test", content_root=backend_root / "content" / "packages",
            repository="memory", governance_audit_salt="secret",
        )
        runtime = build_container(runtime_settings)
        runtime.auth.create_account(
            account_id="researcher", username="researcher", password="correct horse battery",
            roles=frozenset({RESEARCHER}),
        )
        runtime.auth.create_account(
            account_id="admin", username="admin", password="correct horse battery",
            roles=frozenset({ADMIN}),
        )
        for index in range(5):
            runtime.research_events.append(ResearchEvent(
                research_event_id=f"api_event_{index}", research_subject_id=f"rs_{index}",
                experiment_id="study", experiment_group_id="control",
                session_public_id=f"public_{index}", event_type="action", story_day=1,
                structured_payload={"ok": True},
            ))
        production_view = Settings(
            environment="production", content_root=runtime_settings.content_root,
            repository="memory", role_llm_provider="none",
        )
        app = create_app(production_view, runtime)
        researcher = TestClient(app, base_url="https://testserver")
        admin = TestClient(app, base_url="https://testserver")
        r_login = researcher.post("/api/auth/login", json={
            "username":"researcher", "password":"correct horse battery"
        }).json()
        denied = researcher.post("/api/admin/research/exports", json={
            "purpose":"analysis", "fields":["event_type"], "conditions":{},
            "minimum_cell_size":5,
        })
        self.assertEqual(403, denied.status_code)
        requested = researcher.post(
            "/api/admin/research/exports", headers={"X-CSRF-Token":r_login["csrf_token"]},
            json={"purpose":"analysis", "fields":["event_type"], "conditions":{}, "minimum_cell_size":5},
        )
        self.assertEqual(202, requested.status_code, requested.text)
        export_id = requested.json()["export_job_id"]
        a_login = admin.post("/api/auth/login", json={
            "username":"admin", "password":"correct horse battery"
        }).json()
        approved = admin.post(
            f"/api/admin/research/exports/{export_id}/approve",
            headers={"X-CSRF-Token":a_login["csrf_token"]}, json={"purpose":"approval"},
        )
        self.assertEqual(200, approved.status_code, approved.text)
        materialized = admin.post(
            f"/api/admin/research/exports/{export_id}/materialize",
            headers={"X-CSRF-Token":a_login["csrf_token"]}, json={"purpose":"download"},
        )
        self.assertEqual(5, materialized.json()["row_count"])


if __name__ == "__main__":
    unittest.main()
