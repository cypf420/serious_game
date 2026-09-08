from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class ConsentPlayerContractTests(unittest.TestCase):
    def test_ready_and_current_consent_expose_player_requirements(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            role_llm_provider="none",
            require_model_consent=True,
            consent_version="consent-v1",
            consent_document_hash="sha256:player-consent-v1",
            consent_model_provider="测试角色模型",
            consent_processing_region="中国境内测试区",
            raw_text_retention_days=30,
        )
        runtime = build_container(settings)
        client = TestClient(create_app(settings, runtime))
        headers = {"X-Account-ID": "acct_consent_player"}

        ready = client.get("/health/ready", headers=headers)
        self.assertEqual(200, ready.status_code, ready.text)
        self.assertTrue(ready.json()["model_consent_required"])

        current = client.get("/api/consent/current", headers=headers)
        self.assertEqual(200, current.status_code, current.text)
        self.assertEqual("consent-v1", current.json()["required_version"])
        self.assertEqual(30, current.json()["retention_days_raw_text"])
        self.assertTrue(current.json()["model_consent_required"])

        signed = client.post(
            "/api/consent",
            headers=headers,
            json={
                "consent_version": "consent-v1",
                "scopes": ["service_storage", "third_party_model"],
            },
        )
        self.assertEqual(200, signed.status_code, signed.text)
        self.assertIn("third_party_model", signed.json()["scopes"])


if __name__ == "__main__":
    unittest.main()
