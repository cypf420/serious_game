from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
from threading import Thread
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.bootstrap import build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import (
    GovernanceLLMContext,
    NightAgentContext,
    RoleTurnContext,
)
from serious_game_backend.domain.errors import (
    RoleLLMResponseError,
    RoleLLMUnavailableError,
)
from serious_game_backend.infrastructure.llm.openai_compatible import (
    OpenAICompatibleRoleLLMGateway,
)
from serious_game_backend.infrastructure.llm.player_configuration import (
    _PinnedHTTPSConnection,
)
from tests.test_doubles import DeterministicRoleLLMGateway


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def tiny_protocol_response(prompt: str) -> dict:
    if "你只负责把已经确认的业务选择写成自然语言" in prompt:
        return {"text": "已按确认事项形成简短、明确的公开表述。"}
    matched = re.search(r"合法候选：(\[.*?\])\n选择数量：最少(\d+)，最多", prompt, re.S)
    if not matched:
        raise AssertionError(f"unexpected protocol prompt: {prompt[:160]}")
    options = json.loads(matched.group(1))
    minimum = int(matched.group(2))
    ids = [str(item["choice_id"]) for item in options]
    if '只返回 JSON：{"choice_ids"' in prompt:
        return {"choice_ids": ids[:minimum]}
    return {"choice_id": ids[0]}


class PlayerLLMConfigurationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            auth_required=True,
            allow_self_registration=True,
            auth_cookie_secure=False,
            role_llm_provider="none",
        )
        self.transport_mode = "valid"
        self.transport_calls: list[dict] = []

        def transport(base_url: str, api_key: str, body: dict, timeout: float) -> dict:
            self.transport_calls.append({
                "base_url": base_url,
                "api_key": api_key,
                "model": body.get("model"),
                "timeout": timeout,
            })
            if self.transport_mode == "invalid":
                return {"choices": [{"message": {"content": "not-json"}}]}
            system = "\n".join(
                str(item.get("content", "")) for item in body.get("messages", [])
            )
            content = tiny_protocol_response(system)
            return {
                "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            }

        def resolver(host: str, port: int, **_kwargs) -> list[tuple]:
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ]

        self.runtime = build_container(
            self.settings,
            player_llm_transport=transport,
            player_llm_resolver=resolver,
            server_role_llm=DeterministicRoleLLMGateway(),
        )
        self.client = TestClient(
            create_app(self.settings, self.runtime), base_url="http://testserver"
        )
        registered = self.client.post(
            "/api/auth/register",
            json={"username": "model-player", "password": "pass1234"},
        )
        self.assertEqual(201, registered.status_code, registered.text)
        self.csrf = registered.json()["csrf_token"]
        self.account_id = registered.json()["account_id"]

    def test_session_llm_audit_endpoint_is_owned_and_secret_free(self) -> None:
        created = self.client.post(
            "/api/game/session",
            headers={"X-CSRF-Token": self.csrf},
            json={"client_request_id": "audit-export-session"},
        )
        self.assertEqual(201, created.status_code, created.text)
        session_id = created.json()["session_id"]
        gateway = OpenAICompatibleRoleLLMGateway(
            replace(
                self.settings, role_llm_provider="openai_compatible",
                role_llm_base_url="https://api.example.test/v1?private=never-export",
                role_llm_model="model-safe", role_llm_max_retries=0,
            ),
            "sentinel-secret-key", self.runtime.llm_audits,
            config_version="cfg_safe",
            transport=lambda *_args: {
                "choices": [{"message": {"content": '{"choice_id":"a"}'}}],
                "usage": {},
            },
        )
        from serious_game_backend.domain.llm import SelectionOption, SelectionTask
        gateway.select(SelectionTask(
            task_id="audit-safe", role_id="npc-safe", role_name="NPC",
            instruction="select", options=(SelectionOption("a", "A"),),
            selection_mode="single", minimum_choices=1, maximum_choices=1,
            session_id=session_id, account_id=self.account_id,
            operation_id="operation-safe", story_day=1,
        ))

        response = self.client.get(
            f"/api/game/session/{session_id}/ai/audits?limit=50"
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({
            "audit_id", "operation_id", "provider", "model", "endpoint_host",
            "config_version", "status", "error_code", "timestamp", "run_id",
            "session_id",
        }, set(response.json()["audits"][0]))
        self.assertNotIn("sentinel-secret-key", response.text)
        self.assertNotIn("never-export", response.text)

        other = TestClient(create_app(self.settings, self.runtime), base_url="http://testserver")
        registered = other.post(
            "/api/auth/register",
            json={"username": "audit-intruder", "password": "pass1234"},
        )
        self.assertEqual(201, registered.status_code, registered.text)
        forbidden = other.get(f"/api/game/session/{session_id}/ai/audits")
        self.assertEqual(404, forbidden.status_code, forbidden.text)

    def test_authenticated_player_can_select_explicit_server_default(self) -> None:
        before = self.client.get("/api/ai/config")
        self.assertEqual(200, before.status_code, before.text)
        self.assertEqual("unconfigured", before.json()["mode"])
        self.assertFalse(before.json()["active"])
        self.assertTrue(before.json()["server_default_available"])
        self.assertNotIn("api_key", before.text.casefold())

        selected = self.client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": self.csrf},
            json={"mode": "server_default"},
        )
        self.assertEqual(200, selected.status_code, selected.text)
        self.assertEqual("server_default", selected.json()["mode"])
        self.assertTrue(selected.json()["active"])

    def test_authenticated_identity_returns_username_for_account_center(self) -> None:
        current = self.client.get("/api/auth/me")
        self.assertEqual(200, current.status_code, current.text)
        self.assertEqual("model-player", current.json()["username"])

    def test_personal_endpoint_rejects_non_public_url_without_partial_change(self) -> None:
        response = self.client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "mode": "personal",
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "secret-must-never-echo",
                "model": "local-model",
            },
        )
        self.assertEqual(422, response.status_code, response.text)
        self.assertNotIn("secret-must-never-echo", response.text)
        status = self.client.get("/api/ai/config")
        self.assertEqual("unconfigured", status.json()["mode"])
        self.assertFalse(status.json()["active"])

    def test_personal_endpoint_rejects_every_unsafe_url_shape(self) -> None:
        unsafe_urls = (
            "https://127.0.0.1/v1",
            "https://user:password@model.example/v1",
            "https://model.example/v1?token=secret",
            "https://model.example/v1#fragment",
        )
        for index, base_url in enumerate(unsafe_urls):
            with self.subTest(base_url=base_url):
                response = self.client.put(
                    "/api/ai/config",
                    headers={"X-CSRF-Token": self.csrf},
                    json={
                        "mode": "personal",
                        "base_url": base_url,
                        "api_key": f"secret-{index}",
                        "model": "player-model",
                    },
                )
                self.assertEqual(422, response.status_code, response.text)
                self.assertNotIn(f"secret-{index}", response.text)
        self.assertEqual("unconfigured", self.client.get("/api/ai/config").json()["mode"])

    def test_http_transport_refuses_redirects_before_sending_key_to_new_host(self) -> None:
        followed = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length:
                    self.rfile.read(content_length)
                if self.path == "/v1/chat/completions":
                    self.send_response(302)
                    self.send_header("Location", "/captured")
                    self.end_headers()
                    return
                followed.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices": []}')

            def do_GET(self) -> None:  # noqa: N802 - redirect follow-up
                followed.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices": []}')

            def log_message(self, _format: str, *_args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(RoleLLMResponseError):
                OpenAICompatibleRoleLLMGateway._http_transport(
                    f"http://127.0.0.1:{server.server_port}/v1",
                    "redirect-secret",
                    {"model": "test"},
                    2.0,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual([], followed)

    def test_http_transport_maps_non_json_provider_output_to_safe_response_error(self) -> None:
        class InvalidJsonHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b"provider debug page must not escape"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), InvalidJsonHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(RoleLLMResponseError, "结构化响应"):
                OpenAICompatibleRoleLLMGateway._http_transport(
                    f"http://127.0.0.1:{server.server_port}/v1",
                    "provider-key-must-not-escape",
                    {"model": "test"},
                    2.0,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_transport_enforces_an_absolute_response_deadline(self) -> None:
        class DripHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = b'{"choices":[{"message":{"content":"{}"}}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for byte in body:
                        self.wfile.write(bytes((byte,)))
                        self.wfile.flush()
                        time.sleep(0.03)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

            def log_message(self, _format: str, *_args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), DripHandler)
        server.daemon_threads = True
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.perf_counter()
        elapsed = float("inf")
        try:
            with self.assertRaises(RoleLLMUnavailableError):
                OpenAICompatibleRoleLLMGateway._http_transport(
                    f"http://127.0.0.1:{server.server_port}/v1",
                    "deadline-secret",
                    {"model": "test"},
                    0.12,
                )
            elapsed = time.perf_counter() - started
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertLess(elapsed, 0.8)

    def test_personal_https_connection_uses_only_the_prevalidated_ip(self) -> None:
        raw_socket = object()

        class FakeContext:
            def wrap_socket(self, sock, *, server_hostname):
                self.server_hostname = server_hostname
                return sock

        connection = _PinnedHTTPSConnection(
            "rebind.example",
            443,
            validated_addresses=("93.184.216.34",),
            timeout=3.0,
        )
        fake_context = FakeContext()
        connection._context = fake_context
        with patch(
            "serious_game_backend.infrastructure.llm.player_configuration.socket.create_connection",
            return_value=raw_socket,
        ) as create_connection:
            connection.connect()

        create_connection.assert_called_once_with(
            ("93.184.216.34", 443), 3.0, None
        )
        self.assertEqual("rebind.example", fake_context.server_hostname)
        self.assertIs(raw_socket, connection.sock)

    def test_personal_configuration_is_tested_masked_and_failed_replacement_is_atomic(self) -> None:
        calls_before = len(self.transport_calls)
        configured = self.client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "mode": "personal",
                "base_url": "https://model-a.example/v1",
                "api_key": "player-key-a",
                "model": "player-model-a",
            },
        )
        self.assertEqual(200, configured.status_code, configured.text)
        self.assertEqual({
            "mode": "personal",
            "active": True,
            "endpoint": "model-a.example",
            "model": "player-model-a",
        }, {key: configured.json()[key] for key in (
            "mode", "active", "endpoint", "model",
        )})
        self.assertNotIn("player-key-a", configured.text)
        self.assertEqual("compatible", configured.json()["compatibility_status"])
        self.assertIsNotNone(configured.json()["tested_at"])
        self.assertEqual(
            {
                "single_choice",
                "multiple_choice",
                "expression",
                "night_followup",
                "contract_rendering",
                "document_rendering",
            },
            {
                capability
                for capability, result in configured.json()["capabilities"].items()
                if result == "passed"
            },
        )
        self.assertEqual("player-key-a", self.transport_calls[-1]["api_key"])
        self.assertEqual("player-model-a", self.transport_calls[-1]["model"])
        self.assertEqual(calls_before + 6, len(self.transport_calls))

        self.transport_mode = "invalid"
        failed_calls_before = len(self.transport_calls)
        rejected = self.client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "mode": "personal",
                "base_url": "https://model-b.example/v1",
                "api_key": "player-key-b-must-not-echo",
                "model": "player-model-b",
            },
        )
        self.assertEqual(422, rejected.status_code, rejected.text)
        self.assertNotIn("player-key-b-must-not-echo", rejected.text)
        current = self.client.get("/api/ai/config").json()
        self.assertEqual("personal", current["mode"])
        self.assertEqual("player-model-a", current["model"])
        self.assertEqual(configured.json()["tested_at"], current["tested_at"])
        self.assertNotIn("player-key-a", json.dumps(current))
        self.assertEqual(failed_calls_before + 3, len(self.transport_calls))

    def test_configuration_is_isolated_per_login_and_logout_clears_only_that_login(self) -> None:
        first = self.client.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": self.csrf},
            json={
                "mode": "personal",
                "base_url": "https://first.example/v1",
                "api_key": "first-login-key",
                "model": "first-model",
            },
        )
        self.assertEqual(200, first.status_code, first.text)

        second = TestClient(
            create_app(self.settings, self.runtime), base_url="http://testserver"
        )
        login = second.post("/api/auth/login", json={
            "username": "model-player", "password": "pass1234",
        })
        self.assertEqual(200, login.status_code, login.text)
        second_status = second.get("/api/ai/config")
        self.assertEqual("unconfigured", second_status.json()["mode"])
        selected = second.put(
            "/api/ai/config",
            headers={"X-CSRF-Token": login.json()["csrf_token"]},
            json={"mode": "server_default"},
        )
        self.assertEqual("server_default", selected.json()["mode"])
        self.assertEqual("personal", self.client.get("/api/ai/config").json()["mode"])

        logged_out = self.client.post("/api/auth/logout")
        self.assertEqual(204, logged_out.status_code, logged_out.text)
        relogin = self.client.post("/api/auth/login", json={
            "username": "model-player", "password": "pass1234",
        })
        self.assertEqual(200, relogin.status_code, relogin.text)
        self.assertEqual("unconfigured", self.client.get("/api/ai/config").json()["mode"])
        self.assertEqual("server_default", second.get("/api/ai/config").json()["mode"])

    def test_frozen_personal_gateway_covers_role_night_and_governance_tasks(self) -> None:
        calls: list[tuple[str, str]] = []

        def adaptive_transport(_base_url: str, api_key: str, body: dict, _timeout: float) -> dict:
            system = "\n".join(
                str(item.get("content", "")) for item in body.get("messages", [])
            )
            calls.append((api_key, str(body.get("model"))))
            content = tiny_protocol_response(system)
            return {
                "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

        runtime = build_container(
            self.settings,
            player_llm_transport=adaptive_transport,
            player_llm_resolver=lambda host, port, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ],
        )
        runtime.player_llm_configs.use_personal(
            "login-scope-a",
            base_url="https://personal.example/v1",
            api_key="personal-key",
            model="personal-model",
        )
        with runtime.player_llm_configs.bind("login-scope-a", require_selection=True):
            frozen = runtime.player_llm_configs.freeze_current()

        with runtime.player_llm_configs.bind_frozen(frozen):
            role = runtime.role_llm.run_turn(RoleTurnContext(
                session_id="session-role", account_id="account-a",
                operation_id="operation-role", story_day=2,
                npc_id="npc_role", npc_name="测试人物",
                player_text="请回应", opportunity_id="opportunity-role",
                role_setting="公开测试人物", prompt_template="返回严格 JSON",
            ))
            night = runtime.role_llm.run_night_turn(NightAgentContext(
                session_id="session-night", account_id="account-a",
                operation_id="operation-night", story_day=2,
                scene_id="scene-night", phase="dialogue",
                npc_id="npc_night", npc_name="夜间人物",
                role_setting="公开夜间人物", big_five={}, counterpart_ids=(),
                model_id="package-model-must-not-win",
            ))
            governance = runtime.role_llm.run_governance_task(GovernanceLLMContext(
                session_id="session-governance", account_id="account-a",
                operation_id="operation-governance", story_day=2,
                task="review_input", actor_id="npc_role", actor_name="测试人物",
                actor_profile="公开测试人物", payload={"player_text": "继续讨论"},
            ))

        self.assertEqual("npc_role", role.npc_id)
        self.assertEqual("npc_night", night.npc_id)
        self.assertEqual("review_input", governance.task)
        self.assertEqual(
            [("personal-key", "personal-model")] * 10,
            calls,
        )

    def test_frozen_request_keeps_one_gateway_while_same_login_reconfigures(self) -> None:
        self.runtime.player_llm_configs.use_personal(
            "stable-request",
            base_url="https://first.example/v1",
            api_key="first-key",
            model="first-model",
        )
        with self.runtime.player_llm_configs.bind(
            "stable-request", require_selection=True
        ):
            frozen = self.runtime.player_llm_configs.freeze_current()
        self.runtime.player_llm_configs.use_personal(
            "stable-request",
            base_url="https://second.example/v1",
            api_key="second-key",
            model="second-model",
        )
        with self.runtime.player_llm_configs.bind_frozen(frozen):
            self.runtime.role_llm.run_turn(RoleTurnContext(
                session_id="frozen-session", account_id="account-a",
                operation_id="frozen-operation", story_day=1,
                npc_id="connection_test_npc", npc_name="接口测试角色",
                player_text="继续", opportunity_id="frozen-opportunity",
                role_setting="公开测试", prompt_template="返回严格 JSON",
            ))
        with self.runtime.player_llm_configs.bind(
            "stable-request", require_selection=True
        ):
            self.runtime.role_llm.run_turn(RoleTurnContext(
                session_id="next-session", account_id="account-a",
                operation_id="next-operation", story_day=1,
                npc_id="connection_test_npc", npc_name="接口测试角色",
                player_text="继续", opportunity_id="next-opportunity",
                role_setting="公开测试", prompt_template="返回严格 JSON",
            ))
        self.assertEqual(
            ["first-key", "first-key", "second-key", "second-key"],
            [item["api_key"] for item in self.transport_calls[-4:]],
        )

    def test_server_can_run_without_default_gateway_until_player_configures_one(self) -> None:
        settings = Settings(
            environment="sandbox",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            auth_required=False,
            role_llm_provider="none",
        )
        runtime = build_container(
            settings,
            player_llm_transport=lambda *_args: {},
            player_llm_resolver=lambda host, port, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))
            ],
        )
        client = TestClient(create_app(settings, runtime), base_url="http://testserver")
        status = client.get("/api/ai/config", headers={"X-Account-ID": "sandbox-a"})
        self.assertEqual(200, status.status_code, status.text)
        self.assertFalse(status.json()["server_default_available"])
        rejected = client.put(
            "/api/ai/config",
            headers={"X-Account-ID": "sandbox-a"},
            json={"mode": "server_default"},
        )
        self.assertEqual(422, rejected.status_code, rejected.text)

    def test_unconfigured_login_cannot_create_or_mutate_an_active_game(self) -> None:
        settings = Settings(
            environment="sandbox",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            auth_required=True,
            allow_self_registration=True,
            auth_cookie_secure=False,
            role_llm_provider="none",
        )
        runtime = build_container(settings, server_role_llm=DeterministicRoleLLMGateway())
        client = TestClient(create_app(settings, runtime), base_url="http://testserver")
        registered = client.post("/api/auth/register", json={
            "username": "needs-model", "password": "pass1234",
        })
        self.assertEqual(201, registered.status_code, registered.text)
        headers = {"X-CSRF-Token": registered.json()["csrf_token"]}
        created = client.post("/api/game/session", headers=headers, json={
            "client_request_id": "config-required-session",
        })
        self.assertEqual(409, created.status_code, created.text)
        self.assertEqual("ROLE_LLM_CONFIGURATION_REQUIRED", created.json()["error"]["code"])
        self.assertEqual((), runtime.sessions.list_for_account(registered.json()["account_id"]))

        configured = client.put(
            "/api/ai/config",
            headers=headers,
            json={"mode": "server_default"},
        )
        self.assertEqual(200, configured.status_code, configured.text)
        created = client.post("/api/game/session", headers=headers, json={
            "client_request_id": "configured-session",
        })
        self.assertEqual(201, created.status_code, created.text)
        session_id = created.json()["session_id"]
        cleared = client.delete("/api/ai/config", headers=headers)
        self.assertEqual(200, cleared.status_code, cleared.text)
        decided = client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json={
                "input_mode": "decision",
                "client_action_id": "config-required-decision",
                "state_version": created.json()["state_version"],
                "decision_id": created.json()["pending_decision"]["decision_id"],
                "option_id": created.json()["pending_decision"]["options"][0]["option_id"],
            },
        )
        self.assertEqual(409, decided.status_code, decided.text)
        self.assertEqual("ROLE_LLM_CONFIGURATION_REQUIRED", decided.json()["error"]["code"])
        stored = runtime.sessions.get_owned(session_id, registered.json()["account_id"])
        self.assertEqual(created.json()["state_version"], stored.state_version)

    def test_clearing_configuration_before_an_existing_stream_has_no_partial_commit(self) -> None:
        settings = Settings(
            environment="test",
            content_root=BACKEND_ROOT / "content" / "packages",
            repository="memory",
            auth_required=True,
            allow_self_registration=True,
            auth_cookie_secure=False,
            role_llm_provider="none",
        )
        runtime = build_container(settings)
        client = TestClient(create_app(settings, runtime), base_url="http://testserver")
        registered = client.post("/api/auth/register", json={
            "username": "stream-needs-model", "password": "pass1234",
        })
        self.assertEqual(201, registered.status_code, registered.text)
        headers = {"X-CSRF-Token": registered.json()["csrf_token"]}
        created = client.post("/api/game/session", headers=headers, json={
            "client_request_id": "stream-configured-session",
        })
        self.assertEqual(201, created.status_code, created.text)
        session_id = created.json()["session_id"]
        decided = client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json={
                "input_mode": "decision",
                "client_action_id": "stream-configured-decision",
                "state_version": created.json()["state_version"],
                "decision_id": created.json()["pending_decision"]["decision_id"],
                "option_id": created.json()["pending_decision"]["options"][0]["option_id"],
            },
        )
        self.assertEqual(200, decided.status_code, decided.text)
        started = client.post(
            f"/api/game/session/{session_id}/governance/actions",
            headers=headers,
            json={
                "state_version": decided.json()["state_version"],
                "action_kind": "cadre_interview",
                "variant_id": "interview_cadre",
                "location_id": "loc_county_government",
                "target_ids": ["npc_zhao_jianguo"],
                "topic": "核实搬迁程序",
            },
        )
        self.assertEqual(201, started.status_code, started.text)
        action_id = started.json()["action"]["action_instance_id"]
        stream = client.post(
            f"/api/game/session/{session_id}/governance/actions/{action_id}/turn/stream",
            headers=headers,
            json={
                "state_version": started.json()["state_version"],
                "client_action_id": "config-required-turn",
                "player_text": "请说明当前最需要解决的问题。",
            },
        )
        self.assertEqual(200, stream.status_code, stream.text)
        self.assertIn("ROLE_LLM_CONFIGURATION_REQUIRED", stream.text)
        stored = runtime.sessions.get_owned(session_id, registered.json()["account_id"])
        self.assertEqual(started.json()["state_version"], stored.state_version)
        self.assertEqual("pending", stored.governance_actions[action_id].cost_status)
        self.assertEqual([], stored.governance_actions[action_id].transcript)

    def test_expired_login_scope_drops_its_ephemeral_configuration(self) -> None:
        self.runtime.player_llm_configs.use_server_default(
            "expired-login",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        status = self.runtime.player_llm_configs.status("expired-login")
        self.assertEqual("unconfigured", status.mode)
        self.assertFalse(status.active)

    def test_real_failure_matrix_rejects_partial_commit_or_missing_faults(self) -> None:
        from tools.run_real_failure_matrix import (
            is_semantically_unchanged,
            validate_failure_report,
        )

        self.assertTrue(is_semantically_unchanged(["updated_at"]))
        self.assertFalse(is_semantically_unchanged(["game_state.action_points"]))

        passing = {
            "provider": "openai_compatible",
            "fake_calls": 0,
            "cases": [
                {
                    "fault": fault,
                    "failed_without_state_change": True,
                    "retry_committed_once": True,
                    "api_key_leaks": 0,
                }
                for fault in ("timeout", "disconnect", "truncated_json", "invalid_auth")
            ],
            "account_isolation": {
                "server_default_requests": 1,
                "personal_requests": 1,
                "mixed_requests": 0,
            },
        }
        validate_failure_report(passing)
        broken = json.loads(json.dumps(passing))
        broken["cases"][0]["failed_without_state_change"] = False
        with self.assertRaisesRegex(ValueError, "partial"):
            validate_failure_report(broken)
        missing = json.loads(json.dumps(passing))
        missing["cases"] = missing["cases"][:-1]
        with self.assertRaisesRegex(ValueError, "invalid_auth"):
            validate_failure_report(missing)


if __name__ == "__main__":
    unittest.main()
