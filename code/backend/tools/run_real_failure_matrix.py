from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
from threading import RLock, Thread
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import SelectionOption, SelectionTask
from serious_game_backend.infrastructure.llm.openai_compatible import (
    OpenAICompatibleRoleLLMGateway,
)
from serious_game_backend.infrastructure.llm.player_configuration import (
    PlayerLLMConfigurationRegistry,
)
from serious_game_backend.infrastructure.repositories.codec import dumps, encode_session
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryLLMCallAuditRepository,
)
from tools.run_real_v3_routes import RealRouteRunner, validate_real_runner_settings


FAULTS = ("timeout", "disconnect", "truncated_json", "invalid_auth")


def validate_failure_report(report: dict) -> None:
    if report.get("provider") != "openai_compatible":
        raise ValueError("failure matrix did not use the real provider")
    if int(report.get("fake_calls", 0)):
        raise ValueError("Fake calls are forbidden in the real failure matrix")
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("failure cases are missing")
    by_fault = {str(item.get("fault")): item for item in cases}
    missing = sorted(set(FAULTS) - set(by_fault))
    if missing:
        raise ValueError("missing fault cases: " + ", ".join(missing))
    for fault in FAULTS:
        item = by_fault[fault]
        if not item.get("failed_without_state_change"):
            raise ValueError(f"partial state commit detected for {fault}")
        if not item.get("retry_committed_once"):
            raise ValueError(f"retry did not commit exactly once for {fault}")
        if int(item.get("api_key_leaks", 0)):
            raise ValueError(f"credential leak detected for {fault}")
    isolation = report.get("account_isolation") or {}
    if int(isolation.get("server_default_requests", 0)) <= 0:
        raise ValueError("server-default account was not exercised")
    if int(isolation.get("personal_requests", 0)) <= 0:
        raise ValueError("personal account was not exercised")
    if int(isolation.get("mixed_requests", 0)):
        raise ValueError("account gateways were mixed")


class FaultProxy:
    """Local fault injector. It never synthesizes a successful model response."""

    def __init__(self, upstream_base_url: str, *, timeout_delay: float) -> None:
        self.upstream = upstream_base_url.rstrip("/") + "/chat/completions"
        self.timeout_delay = timeout_delay
        self.mode = "pass"
        self.path_counts: Counter[str] = Counter()
        self._lock = RLock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                length = int(self.headers.get("Content-Length", "0"))
                payload = self.rfile.read(length)
                label = self.path.strip("/").split("/", 1)[0] or "unlabeled"
                with owner._lock:
                    owner.path_counts[label] += 1
                    mode = owner.mode
                if mode == "disconnect":
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
                if mode == "timeout":
                    time.sleep(owner.timeout_delay)
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    self.connection.close()
                    return
                authorization = self.headers.get("Authorization", "")
                if mode == "invalid_auth":
                    authorization = "Bearer deliberately-invalid-acceptance-credential"
                request = Request(
                    owner.upstream,
                    data=payload,
                    headers={
                        "Authorization": authorization,
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=120) as response:
                        status = response.status
                        body = response.read()
                        content_type = response.headers.get("Content-Type", "application/json")
                except HTTPError as exc:
                    status = exc.code
                    body = exc.read()
                    content_type = exc.headers.get("Content-Type", "application/json")
                if mode == "truncated_json" and 200 <= status < 300:
                    body = body[:max(1, len(body) // 2)]
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FaultProxy":
        self.thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def base_url(self, label: str) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}/{label}/v1"

    def set_mode(self, mode: str) -> None:
        if mode not in {*FAULTS, "pass"}:
            raise ValueError(f"unknown proxy mode: {mode}")
        with self._lock:
            self.mode = mode


def _digest(value: object) -> str:
    return "sha256:" + sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def transaction_snapshot(container, session_id: str, account_id: str) -> dict:
    session = container.sessions.get_owned(session_id, account_id)
    if session is None:
        raise RuntimeError("acceptance session disappeared")
    encoded = encode_session(session)
    snapshots = [
        item.snapshot_id
        for item in container.snapshots.list_history(account_id, session_id)
    ]
    return {
        "_payload": encoded,
        "semantic_hash": _digest(encoded),
        "state_version": session.state_version,
        "action_points": session.game_state.action_points,
        "active_conversation_turns": (
            len(session.active_conversation.transcript)
            if session.active_conversation is not None else 0
        ),
        "contracts_hash": _digest(encoded["household_contracts"]),
        "documents_hash": _digest(encoded["administrative_documents"]),
        "flags_hash": _digest(encoded["flags"]),
        "snapshot_ids": snapshots,
    }


def changed_paths(before: object, after: object, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        paths: list[str] = []
        for key in sorted(set(before) | set(after)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                paths.append(child)
            else:
                paths.extend(changed_paths(before[key], after[key], child))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return []
        return [prefix]
    return [] if before == after else [prefix]


def public_snapshot(snapshot: dict) -> dict:
    return {key: value for key, value in snapshot.items() if key != "_payload"}


def is_semantically_unchanged(paths: list[str]) -> bool:
    """A failed attempt may touch wall-clock metadata, never gameplay state."""

    return set(paths) <= {"updated_at"}


def _selection(account_id: str, operation_id: str) -> SelectionTask:
    return SelectionTask(
        task_id="account-isolation",
        role_id="npc_wu_xiuying",
        role_name="吴秀英",
        instruction="从合法候选中选择一个。",
        options=(SelectionOption("verify", "核对台账"), SelectionOption("explain", "解释政策")),
        session_id=f"failure-{account_id}",
        account_id=account_id,
        operation_id=operation_id,
        story_day=3,
    )


def run_account_isolation(settings: Settings, api_key: str, proxy: FaultProxy) -> dict:
    audits = InMemoryLLMCallAuditRepository()
    server_settings = replace(settings, role_llm_base_url=proxy.base_url("server"))
    server_gateway = OpenAICompatibleRoleLLMGateway(server_settings, api_key, audits)

    def personal_transport(_base: str, key: str, body: dict, timeout: float) -> dict:
        return OpenAICompatibleRoleLLMGateway._http_transport(
            proxy.base_url("personal"), key, body, timeout
        )

    registry = PlayerLLMConfigurationRegistry(
        server_settings,
        audits,
        server_gateway,
        transport=personal_transport,
        resolver=lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ],
    )
    before = Counter(proxy.path_counts)
    registry.use_server_default("account-server")
    registry.use_personal(
        "account-personal",
        base_url="https://personal-acceptance.example/v1",
        api_key=api_key,
        model=settings.role_llm_model,
    )

    def invoke(scope: str, operation: str) -> None:
        with registry.bind(scope, require_selection=True):
            frozen = registry.freeze_current()
            with registry.bind_frozen(frozen):
                registry.current_gateway().select(_selection(scope, operation))

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda item: invoke(*item), (
            ("account-server", "isolation-server"),
            ("account-personal", "isolation-personal"),
        )))
    after = Counter(proxy.path_counts)
    server_count = after["server"] - before["server"]
    personal_count = after["personal"] - before["personal"]
    return {
        "server_default_requests": server_count,
        "personal_requests": personal_count,
        "mixed_requests": 0 if server_count > 0 and personal_count > 0 else 1,
    }


def run_failure_cases(settings: Settings, api_key: str, root: Path, proxy: FaultProxy) -> tuple[list[dict], int]:
    runtime_root = root / "transaction-runtime"
    runtime_root.mkdir()
    runner_settings = replace(
        settings,
        environment="test",
        repository="sqlite",
        default_package_id="pkg_gameplay_v3",
        role_llm_max_retries=0,
        role_llm_timeout_seconds=max(5, int(settings.role_llm_timeout_seconds)),
    )
    def fault_transport(_base: str, key: str, body: dict, timeout: float) -> dict:
        return OpenAICompatibleRoleLLMGateway._http_transport(
            proxy.base_url("server"), key, body, timeout
        )

    runner = RealRouteRunner(
        runner_settings,
        runtime_root,
        stop_day=3,
        player_llm_transport=fault_transport,
        player_llm_resolver=lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )
    container, client, session_id, headers = runner.build_real_runner(991)
    try:
        result, decision_index = runner.reach_day_three(
            container, client, session_id, headers, 991
        )
        result, _decision_index = runner.drain_decisions(
            container,
            client,
            session_id,
            headers,
            result,
            991,
            decision_index,
        )
        started = runner.action(client, session_id, headers, {
            "input_mode": "conversation_start",
            "client_action_id": "failure-matrix-start-zhou",
            "state_version": result["state_version"],
            "opportunity_id": "opp_d03_zhou_dashan_first_talk",
            "target_npc_id": "npc_zhou_dashan",
        })
        conversation_id = started["conversation"]["conversation_id"]
        cases: list[dict] = []
        for index, fault in enumerate(FAULTS):
            operation_id = f"failure-matrix-{fault}-{index}"
            body = {
                "input_mode": "free_text",
                "client_action_id": operation_id,
                "state_version": container.sessions.get_owned(
                    session_id, headers["X-Account-ID"]
                ).state_version,
                "conversation_id": conversation_id,
                "opportunity_id": "opp_d03_zhou_dashan_first_talk",
                "target_npc_id": "npc_zhou_dashan",
                "player_text": "请只说明你目前能够确认的公开事实和具体担忧。",
            }
            before = transaction_snapshot(
                container, session_id, headers["X-Account-ID"]
            )
            proxy.set_mode(fault)
            leaked_text = ""
            try:
                failed = client.post(
                    f"/api/game/session/{session_id}/action",
                    headers=headers,
                    json=body,
                )
                failed_status = failed.status_code
                leaked_text = failed.text
            except Exception as exc:  # transport faults may abort the in-process client
                failed_status = 599
                leaked_text = f"{type(exc).__name__}: {exc}"
            after_failure = transaction_snapshot(
                container, session_id, headers["X-Account-ID"]
            )
            payload_changes = changed_paths(before["_payload"], after_failure["_payload"])
            unchanged = is_semantically_unchanged(payload_changes)
            proxy.set_mode("pass")
            if fault == "invalid_auth":
                container.player_llm_configs.use_personal(
                    headers["X-Account-ID"],
                    base_url=settings.role_llm_base_url,
                    api_key=api_key,
                    model=settings.role_llm_model,
                )
            retry = client.post(
                f"/api/game/session/{session_id}/action",
                headers=headers,
                json={
                    **body,
                    "client_action_id": (
                        f"{operation_id}-reconfigured"
                        if fault == "invalid_auth" else operation_id
                    ),
                    "retry": True,
                },
            )
            after_retry = transaction_snapshot(
                container, session_id, headers["X-Account-ID"]
            )
            committed_once = (
                retry.status_code == 200
                and after_retry["state_version"] == before["state_version"] + 1
                and after_retry["active_conversation_turns"] == before["active_conversation_turns"] + 2
            )
            cases.append({
                "fault": fault,
                "failed_status": failed_status,
                "failure_code": (
                    (failed.json().get("error") or {}).get("code")
                    if failed_status != 599 else "transport_aborted"
                ),
                "before": public_snapshot(before),
                "after_failure": public_snapshot(after_failure),
                "after_retry": public_snapshot(after_retry),
                "failure_changed_paths": payload_changes,
                "retry_status": retry.status_code,
                "retry_code": (
                    (retry.json().get("error") or {}).get("code")
                    if retry.status_code >= 400 else None
                ),
                "failed_without_state_change": unchanged,
                "retry_committed_once": committed_once,
                "api_key_leaks": int(api_key in leaked_text),
            })
        audits = container.llm_audits.list_for_session(session_id)
        fake_calls = sum(1 for item in audits if "fake" in item.provider.casefold())
        return cases, fake_calls
    finally:
        proxy.set_mode("pass")
        client.__exit__(None, None, None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    api_key = os.getenv(settings.role_llm_api_key_env, "").strip()
    validate_real_runner_settings(settings, api_key=api_key)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with FaultProxy(
        settings.role_llm_base_url,
        timeout_delay=max(6.0, float(settings.role_llm_timeout_seconds) + 1.0),
    ) as proxy:
        proxy.set_mode("pass")
        cases, fake_calls = run_failure_cases(settings, api_key, args.output_dir, proxy)
        isolation = run_account_isolation(settings, api_key, proxy)
        report = {
            "provider": "openai_compatible",
            "model": settings.role_llm_model,
            "fake_calls": fake_calls,
            "cases": cases,
            "account_isolation": isolation,
            "proxy_request_counts": dict(proxy.path_counts),
        }
    (args.output_dir / "failure-matrix.json").write_text(
        dumps(report), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    try:
        validate_failure_report(report)
    except ValueError as exc:
        print(f"failure matrix gate failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
