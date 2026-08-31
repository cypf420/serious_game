from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from typing import Mapping, Sequence


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from serious_game_backend.bootstrap import build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import RoleLLMUnavailableError
from serious_game_backend.infrastructure.llm.openai_compatible import Transport
from serious_game_backend.infrastructure.llm.player_configuration import Resolver
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tools.full_acceptance.ending_witnesses import (
    EndingWitness,
    load_contract_terms,
    load_witnesses,
    validate_witnesses,
)
from tools.full_acceptance.persuasion import credible_group_replies
from tools.run_story_routes_v3_isolated import (
    build_run_metadata,
    repository_root_for_backend,
)


PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"
PROFILE_PATH = PACKAGE_ROOT / "acceptance_route_profiles.json"
RUN_METADATA_NAME = "route-run-metadata.json"


def select_route_profiles(
    profiles: tuple[EndingWitness, ...],
    route_id_arguments: Sequence[str] | None,
) -> tuple[tuple[int, EndingWitness], ...]:
    """Resolve an optional repeated/comma-separated selection against the catalog."""

    if route_id_arguments is None:
        return tuple(enumerate(profiles))
    route_ids = [
        route_id.strip()
        for argument in route_id_arguments
        for route_id in argument.split(",")
        if route_id.strip()
    ]
    if not route_ids:
        raise ValueError("--route-ids requires at least one route ID")
    duplicates = sorted(
        route_id for route_id, count in Counter(route_ids).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate route ID: {', '.join(duplicates)}")
    indexed = {profile.route_id: (index, profile) for index, profile in enumerate(profiles)}
    unknown = sorted(set(route_ids) - indexed.keys())
    if unknown:
        raise ValueError(f"unknown route ID: {', '.join(unknown)}")
    return tuple(indexed[route_id] for route_id in route_ids)


def build_route_run_metadata(
    *,
    selected_route_ids: Sequence[str],
    catalog_profile_count: int,
    provenance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scope": (
            "full_catalog"
            if len(selected_route_ids) == catalog_profile_count
            else "selected_subset"
        ),
        "catalog_profile_count": catalog_profile_count,
        "selected_route_ids": list(selected_route_ids),
        "git_sha": provenance["git_sha"],
        "workspace_fingerprint": provenance["workspace_fingerprint"],
        "v3_hash": provenance["v3_hash"],
    }


def validate_resume_metadata(
    stored: Mapping[str, object], current: Mapping[str, object]
) -> None:
    if dict(stored) != dict(current):
        raise ValueError("resume selection or provenance mismatch")


def build_route_summary(
    *,
    profiles: Sequence[EndingWitness],
    selected_route_ids: Sequence[str],
    routes: Sequence[Mapping[str, object]],
    provider: str,
    model: str,
    no_archive_route: Mapping[str, object] | None,
    provenance: Mapping[str, object],
) -> dict[str, object]:
    is_full = len(selected_route_ids) == len(profiles)
    return {
        "scope": "full_catalog" if is_full else "selected_subset",
        "catalog_profile_count": len(profiles),
        "executed_count": len(routes),
        "selected_route_ids": list(selected_route_ids),
        "not_full_acceptance": not is_full,
        "provider": provider,
        "model": model,
        # Kept for existing consumers; in subset mode it deliberately means executed.
        "profile_count": len(routes),
        "main_ending_count": len({item["main_ending_id"] for item in routes}),
        "sub_ending_count": len({item["sub_ending_id"] for item in routes}),
        "fake_calls": sum(int(item["fake_calls"]) for item in routes),
        "no_archive_route": no_archive_route,
        "git_sha": provenance["git_sha"],
        "workspace_fingerprint": provenance["workspace_fingerprint"],
        "v3_hash": provenance["v3_hash"],
        "routes": list(routes),
    }


def execute_route_profiles(
    *,
    selected_profiles: Sequence[tuple[int, EndingWitness]],
    completed: Mapping[str, dict[str, object]],
    runner,
    root: Path,
    route_root: Path,
    contract_terms: Mapping[str, object],
) -> list[dict[str, object]]:
    """Execute or resume exactly the selected catalog profiles, in requested order."""

    routes: list[dict[str, object]] = []
    for index, profile in selected_profiles:
        route = completed.get(profile.route_id)
        if route is not None:
            routes.append(route)
            print(f"reused verified {profile.route_id}", file=sys.stderr, flush=True)
            continue
        database_path = root / f"route-{index}.sqlite"
        if database_path.exists():
            database_path.unlink()
        route = runner.run_profile(index, profile, contract_terms)
        routes.append(route)
        (route_root / f"{profile.route_id}.json").write_text(
            json.dumps(route, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return routes


def validate_real_runner_settings(settings: Settings, *, api_key: str) -> None:
    """Refuse any acceptance run that could use a non-real model."""

    if settings.role_llm_provider != "openai_compatible":
        raise SystemExit("real route acceptance requires openai_compatible")
    if settings.role_llm_fallback_to_fake:
        raise SystemExit("real route acceptance refuses Fake fallback")
    if not api_key.strip():
        raise SystemExit("configured real API key is missing")


def prepare_output_run(output_dir: Path, *, run_id: str | None = None) -> Path:
    """Create one immutable evidence directory; never append to an old run."""

    if run_id is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        run_id = f"routes-{stamp}-{os.getpid()}"
    run_root = output_dir / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    return run_root


def load_completed_route_evidence(
    route_root: Path,
    profiles: tuple[EndingWitness, ...],
) -> dict[str, dict[str, object]]:
    """Load only route evidence that still passes the full route contract."""

    completed: dict[str, dict[str, object]] = {}
    profile_by_id = {profile.route_id: profile for profile in profiles}
    if not route_root.exists():
        return completed
    for path in sorted(route_root.glob("route-*.json")):
        route_id = path.stem
        profile = profile_by_id.get(route_id)
        if profile is None:
            raise ValueError(f"resume evidence contains unknown route: {route_id}")
        result = json.loads(path.read_text(encoding="utf-8"))
        validate_route_result(profile, result)
        completed[route_id] = result
    return completed


def validate_profile_catalog(profiles: tuple[EndingWitness, ...], package) -> None:
    coverage = validate_witnesses(profiles, package)
    if len(profiles) != 95:
        raise ValueError(
            f"real acceptance requires exactly 95 profiles, got {len(profiles)}"
        )
    if len(coverage.main_ending_ids) != 24 or len(coverage.sub_ending_ids) != 95:
        raise ValueError(
            "profile catalog must cover 24 main endings and 95 sub endings; "
            f"got {len(coverage.main_ending_ids)}/{len(coverage.sub_ending_ids)}"
        )
    if not coverage.is_complete:
        raise ValueError(f"invalid profile catalog: {coverage}")


def validate_route_result(profile: EndingWitness, result: dict[str, object]) -> None:
    if result.get("main_ending_id") not in profile.target_main_ending_ids:
        raise AssertionError(
            f"main ending mismatch for {profile.route_id}: {result.get('main_ending_id')}"
        )
    if result.get("sub_ending_id") not in profile.target_sub_ending_ids:
        raise AssertionError(
            f"sub ending mismatch for {profile.route_id}: {result.get('sub_ending_id')}"
        )
    if result.get("status") != "ended" or result.get("story_day") != 90:
        raise AssertionError(f"D1-D90 route incomplete for {profile.route_id}")
    if result.get("visited_days") != list(range(1, 91)):
        raise AssertionError(f"D1-D90 evidence is not contiguous for {profile.route_id}")
    if int(result.get("llm_audits", 0)) <= 0:
        raise AssertionError(f"model audit evidence missing for {profile.route_id}")
    providers = dict(result.get("providers", {}))
    if "openai_compatible" not in providers or any(
        "fake" in str(key).casefold() for key in providers
    ):
        raise AssertionError(f"Fake provider found for {profile.route_id}")
    for field, label in (
        ("fake_calls", "Fake"),
        ("template_fallback_count", "template fallback"),
        ("silent_fallback_count", "silent fallback"),
        ("partial_commit_count", "partial commit"),
    ):
        if int(result.get(field, 0)) != 0:
            raise AssertionError(f"{label} evidence found for {profile.route_id}")
    if result.get("mutation_interface") != "http_api_only":
        raise AssertionError(f"direct state evidence found for {profile.route_id}")
    if any(
        not isinstance(item, dict) or item.get("state_restored") is not True
        for item in result.get("failed_calls", ())
    ):
        raise AssertionError(
            f"failed call has no state restoration evidence for {profile.route_id}"
        )


def build_ending_operation_record(
    profile: EndingWitness,
    result: dict[str, object],
) -> dict[str, object]:
    """Project one real route into an auditable, player-action operation guide."""

    sources = (
        ("decision", "decision_choices", "story_day"),
        ("archive", "archive_reads", "story_day"),
        ("conversation", "conversations", "story_day"),
        ("governance_action", "governance_actions", "story_day"),
        ("meeting", "meetings", "story_day"),
        ("contract", "contracts", "signed_day"),
        ("document", "administrative_documents", "story_day"),
        ("forced_night_conversation", "group_conversations", "story_day"),
    )
    mechanism_order = {name: index for index, (name, _, _) in enumerate(sources)}
    operation_sequence: list[dict[str, object]] = []
    for mechanism, result_key, day_key in sources:
        values = result.get(result_key, ())
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            operation_sequence.append({
                "story_day": int(value.get(day_key) or value.get("story_day") or 0),
                "mechanism": mechanism,
                "operation": dict(value),
            })
    operation_sequence.sort(key=lambda item: (
        int(item["story_day"]), mechanism_order[str(item["mechanism"])]
    ))

    contracts = [
        item for item in result.get("contracts", ()) if isinstance(item, dict)
    ]
    documents = [
        item for item in result.get("administrative_documents", ())
        if isinstance(item, dict)
    ]
    known_facts = sorted(map(str, result.get("known_fact_ids", ())))
    return {
        "route_id": profile.route_id,
        "target_main_ending_ids": list(profile.target_main_ending_ids),
        "target_sub_ending_ids": list(profile.target_sub_ending_ids),
        "actual_main_ending_id": result.get("main_ending_id"),
        "actual_sub_ending_id": result.get("sub_ending_id"),
        "origin_id": profile.origin_id,
        "operation_sequence": operation_sequence,
        "mechanism_effects": {
            "investigation": {
                "known_fact_ids": known_facts,
                "archive_read_count": len(result.get("archive_reads", ())),
            },
            "conversations": {
                "completed_count": len(result.get("conversations", ())),
                "forced_night_count": len(result.get("group_conversations", ())),
            },
            "governance": {
                "action_count": len(result.get("governance_actions", ())),
                "decision_count": len(result.get("decision_choices", ())),
            },
            "contracts": {
                "signed_households": sorted(
                    str(item.get("household_id"))
                    for item in contracts if item.get("status") == "signed"
                ),
            },
            "red_head_documents": {
                "published_count": sum(
                    item.get("status") == "published" for item in documents
                ),
                "documents": documents,
            },
            "night_followups": list(result.get("night_logs", ())),
        },
        "ending_state": {
            "story_day": result.get("story_day"),
            "axes": result.get("axes", {}),
            "signed_households": result.get("ledger", {}),
        },
    }


def _public_state_fingerprint(payload: dict) -> str:
    state = payload.get("visible_state", payload.get("state", payload))
    critical = {
        "state_version": payload.get("state_version", state.get("state_version")),
        "status": state.get("status"),
        "story": state.get("story"),
        "ledger": state.get("ledger"),
        "pending_decision": state.get("pending_decision"),
        "active_conversation": state.get("active_conversation"),
        "active_governance_action": state.get("active_governance_action"),
        "active_group_conversation": state.get("active_group_conversation"),
        "ending": state.get("ending"),
    }
    return hashlib.sha256(
        json.dumps(critical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _is_retryable_model_failure(response) -> bool:
    error = response.json().get("error", {}) if response.content else {}
    return (
        response.status_code == 503
        and error.get("code") in {
            "ROLE_LLM_RESPONSE_RETRYABLE",
            "ROLE_LLM_UNAVAILABLE",
        }
    )


def _load_story_route_test_case():
    test_path = Path(__file__).resolve().parents[1] / "tests" / "test_story_routes_v3.py"
    spec = importlib.util.spec_from_file_location("serious_game_story_routes_v3", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load route driver: {test_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.StoryRoutesV3Tests


StoryRoutesV3Tests = _load_story_route_test_case()

EVIDENCE_ARCHIVE_IDS = {
    "archive_household_registry",
    "archive_coordination_fee_index",
    "archive_village_social_excerpt",
    "archive_invoice_number_index",
    "archive_original_vouchers",
    "archive_environmental_report_versions",
    "archive_signing_ledger_comparison",
    "archive_lead_census_master",
    "archive_eia_raw_data",
    "archive_inspection_schedule",
    "archive_resettlement_acceptance_sample",
}


class RealRouteRunner(StoryRoutesV3Tests):
    def __init__(
        self,
        base_settings: Settings,
        root: Path,
        *,
        stop_day: int = 90,
        player_llm_transport: Transport | None = None,
        player_llm_resolver: Resolver | None = None,
        retry_delays: tuple[float, ...] = (0, 0, 0, 0, 0),
    ) -> None:
        super().__init__(methodName="test_three_distinct_fake_routes_reach_d90_without_semantic_leaks")
        self.base_settings = base_settings
        self.root = root
        self.stop_day = stop_day
        self.player_llm_transport = player_llm_transport
        self.player_llm_resolver = player_llm_resolver
        self.retry_delays = retry_delays
        self.archive_reads_by_session: dict[str, list[dict]] = {}
        self.operation_retries_by_session: dict[str, list[dict]] = {}
        self.visited_days_by_session: dict[str, list[int]] = {}
        self.capability_probe_retries: list[dict[str, object]] = []

    def build_real_runner_with_retry(self, route_index: int):
        """Retry transient provider outages while probing a fresh account."""

        max_attempts = len(self.retry_delays) + 1
        for attempt in range(1, max_attempts + 1):
            try:
                return self.build_real_runner(route_index)
            except RoleLLMUnavailableError:
                if attempt >= max_attempts:
                    raise
                self.capability_probe_retries.append({
                    "route_index": route_index,
                    "attempt": attempt,
                    "error_code": "ROLE_LLM_UNAVAILABLE",
                })
                print(
                    f"route-{route_index}-capability-probe: transient real-model "
                    "failure, retrying fresh configuration",
                    file=sys.stderr,
                    flush=True,
                )
                delay = self.retry_delays[attempt - 1]
                if delay > 0:
                    time.sleep(delay)
        raise AssertionError("unreachable capability-probe retry loop")

    def _request_model_write(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        *,
        method: str,
        path: str,
        payload: dict,
        operation: str,
        supports_retry_field: bool,
    ):
        baseline = client.get(
            f"/api/game/session/{session_id}", headers=headers
        )
        if baseline.status_code != 200:
            raise AssertionError(
                f"{operation}: could not capture pre-operation state: "
                f"{baseline.status_code}: {baseline.text}"
            )
        baseline_payload = baseline.json()
        response = None
        max_attempts = len(self.retry_delays) + 1
        for attempt in range(1, max_attempts + 1):
            attempt_payload = dict(payload)
            if supports_retry_field:
                attempt_payload["retry"] = attempt > 1
            response = getattr(client, method)(
                path, headers=headers, json=attempt_payload
            )
            if response.status_code == 200:
                return response
            if (
                not _is_retryable_model_failure(response)
                or attempt >= max_attempts
            ):
                return response
            current = client.get(
                f"/api/game/session/{session_id}", headers=headers
            )
            state_restored = (
                current.status_code == 200
                and _public_state_fingerprint(current.json())
                == _public_state_fingerprint(baseline_payload)
            )
            error_code = response.json().get("error", {}).get("code")
            self.operation_retries_by_session.setdefault(session_id, []).append({
                "operation": operation,
                "attempt": attempt,
                "state_version": payload["state_version"],
                "state_restored": state_restored,
                "error_code": error_code,
            })
            if not state_restored:
                raise AssertionError(
                    f"{operation}: real-model failure changed public state"
                )
            print(
                f"{operation}: retryable real-model failure, retrying unchanged state",
                file=sys.stderr,
                flush=True,
            )
            delay = self.retry_delays[attempt - 1]
            if delay > 0:
                time.sleep(delay)
        assert response is not None
        return response

    def action(self, client, session_id, headers, payload: dict) -> dict:
        response = self._request_model_write(
            client,
            session_id,
            headers,
            method="post",
            path=f"/api/game/session/{session_id}/action",
            payload=payload,
            operation=str(payload.get("client_action_id", "conversation-action")),
            supports_retry_field=True,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def review_contract_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        contract_id: str,
        draft_body: dict,
    ):
        return self._request_model_write(
            client,
            session_id,
            headers,
            method="post",
            path=(
                f"/api/game/session/{session_id}/governance/contracts/"
                f"{contract_id}/review"
            ),
            payload={"state_version": draft_body["state_version"]},
            operation=f"contract-review:{contract_id}",
            supports_retry_field=False,
        )

    def governance_turn_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        action_id: str,
        started_body: dict,
        *,
        player_text: str,
        client_action_id: str,
    ):
        return self._request_model_write(
            client,
            session_id,
            headers,
            method="post",
            path=(
                f"/api/game/session/{session_id}/governance/actions/"
                f"{action_id}/turn"
            ),
            payload={
                "state_version": started_body["state_version"],
                "player_text": player_text,
                "client_action_id": client_action_id,
            },
            operation=client_action_id,
            supports_retry_field=True,
        )

    def set_contract_terms_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        contract_id: str,
        *,
        state_version: int,
        terms: dict,
    ):
        return self._request_model_write(
            client,
            session_id,
            headers,
            method="put",
            path=(
                f"/api/game/session/{session_id}/governance/contracts/"
                f"{contract_id}/terms"
            ),
            payload={"state_version": state_version, **terms},
            operation=f"contract-terms:{contract_id}",
            supports_retry_field=False,
        )

    def group_conversation_turn_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        body: dict,
    ):
        return self._request_model_write(
            client,
            session_id,
            headers,
            method="post",
            path=f"/api/game/session/{session_id}/group-conversation/turn",
            payload=body,
            operation=str(body["client_action_id"]),
            supports_retry_field=True,
        )

    def build_real_runner(
        self, route_index: int
    ) -> tuple[object, TestClient, str, dict[str, str]]:
        account_id = f"acct_real_route_{route_index}"
        settings = replace(
            self.base_settings,
            environment="test",
            default_package_id="pkg_gameplay_v3",
            repository="sqlite",
            database_path=self.root / f"route-{route_index}.sqlite",
            auth_required=False,
            allow_self_registration=False,
            role_llm_provider="openai_compatible",
            role_llm_fallback_to_fake=False,
        )
        settings.validate()
        container = build_container(
            settings,
            player_llm_transport=self.player_llm_transport,
            player_llm_resolver=self.player_llm_resolver,
        )
        if route_index % 2 == 1:
            api_key = os.getenv(settings.role_llm_api_key_env, "").strip()
            container.player_llm_configs.use_personal(
                account_id,
                base_url=settings.role_llm_base_url,
                api_key=api_key,
                model=settings.role_llm_model,
            )
            mode = "personal"
        else:
            container.player_llm_configs.use_server_default(account_id)
            mode = "server_default"
        client = TestClient(create_app(settings, container=container))
        client.__enter__()
        headers = {"X-Account-ID": account_id}
        status = client.get("/api/ai/config", headers=headers)
        self.assertEqual(200, status.status_code, status.text)
        self.assertEqual(mode, status.json()["mode"])
        self.assertEqual("compatible", status.json()["compatibility_status"])
        response = client.post(
            "/api/game/session",
            headers=headers,
            json={
                "client_request_id": f"real-story-route-{route_index}",
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        session_id = response.json()["session_id"]
        self.visited_days_by_session[session_id] = [1]
        return container, client, session_id, headers

    def run_profile(
        self,
        route_index: int,
        profile: EndingWitness,
        contract_terms: dict[str, dict],
    ) -> dict[str, object]:
        """Replay one published witness against a fresh real-model session."""

        container, client, session_id, headers = self.build_real_runner_with_retry(
            route_index
        )
        started = time.perf_counter()
        try:
            witness = self._replay_published_witness(
                container,
                client,
                session_id,
                headers,
                profile,
                contract_terms,
            )
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            if stored is None:
                raise AssertionError("route session disappeared before evidence collection")
            audits = container.llm_audits.list_for_session(session_id)
            providers = Counter(item.provider for item in audits)
            statuses = Counter(item.status for item in audits)
            decisions = [
                {
                    key: item.get(key)
                    for key in ("story_day", "decision_id", "option_id")
                    if key in item
                }
                for item in stored.logs
                if item.get("type") == "decision"
            ]
            actions = [
                {
                    "action_instance_id": item.action_instance_id,
                    "action_kind": item.action_kind,
                    "story_day": item.story_day,
                    "target_ids": list(item.target_ids),
                    "variant_id": item.variant_id,
                    "location_id": item.location_id,
                    "opportunity_id": item.opportunity_id,
                    "map_entry_id": item.map_entry_id,
                    "status": item.status,
                    "cost_status": item.cost_status,
                    "result_ids": list(item.result_ids),
                    "hard_outcomes": list(item.hard_outcomes),
                }
                for item in stored.governance_actions.values()
            ]
            conversations = [
                {
                    "conversation_id": item.conversation_id,
                    "opportunity_id": item.opportunity_id,
                    "npc_id": item.npc_id,
                    "story_day": item.story_day,
                    "completion_status": item.completion_status,
                    "turn_count": len(item.transcript) // 2,
                    "transcript_hash": "sha256:"
                    + hashlib.sha256(
                        json.dumps(
                            item.transcript,
                            ensure_ascii=False,
                            sort_keys=True,
                        ).encode("utf-8")
                    ).hexdigest(),
                }
                for item in stored.completed_conversations
            ]
            night_logs = [
                {
                    "story_day": item.get("story_day"),
                    "agent_exchange_count": len(item.get("agent_exchanges", ())),
                    "created_followup_plan_ids": sorted(
                        str(decision.get("plan_id"))
                        for decision in item.get("followup_decisions", ())
                        if decision.get("created") and decision.get("plan_id")
                    ),
                }
                for item in stored.night_logs
            ]
            contracts = [
                {
                    "contract_id": item.contract_id,
                    "batch_id": item.batch_id,
                    "household_id": item.household_id,
                    "signatory_npc_id": item.signatory_npc_id,
                    "created_day": item.created_day,
                    "signed_day": item.signed_day,
                    "status": item.status,
                    "review_decision": item.review_decision,
                    "term_sheet": item.term_sheet,
                }
                for item in stored.household_contracts.values()
            ]
            meetings = [
                {
                    "meeting_id": item.meeting_id,
                    "story_day": item.story_day,
                    "topic": item.topic,
                    "participant_ids": list(item.participant_ids),
                    "lead_npc_id": item.lead_npc_id,
                    "proposed_document_type": item.proposed_document_type,
                    "status": item.status,
                    "resolution": item.resolution,
                }
                for item in stored.meetings.values()
            ]
            administrative_documents = [
                {
                    "document_id": item.document_id,
                    "document_type": item.document_type,
                    "title": item.title,
                    "story_day": item.story_day,
                    "status": item.status,
                    "version": item.version,
                    "source_meeting_id": item.source_meeting_id,
                    "resolution_snapshot": item.resolution_snapshot,
                    "required_countersign_ids": list(item.required_countersign_ids),
                    "countersigned_by": list(item.countersigned_by),
                    "public_scope": list(item.public_scope),
                    "review_status": item.review_status,
                    "issued_day": item.issued_day,
                    "archive_id": item.archive_id,
                }
                for item in stored.administrative_documents.values()
            ]
            group_conversations = [
                {
                    key: item.get(key)
                    for key in (
                        "conversation_id", "followup_plan_id", "conversation_type",
                        "initiator_npc_id", "participant_ids", "agenda", "phase",
                        "participant_states", "closure_summary", "transcript",
                        "story_day",
                    )
                    if key in item
                }
                for item in stored.completed_group_conversations
            ]
            result: dict[str, object] = {
                **witness,
                "session_id": session_id,
                "mode": "personal" if route_index % 2 == 1 else "server_default",
                "status": stored.status.value,
                "visited_days": self.visited_days_by_session.get(session_id, []),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "llm_audits": len(audits),
                "audit_statuses": dict(statuses),
                "providers": dict(providers),
                "fake_calls": sum(
                    count
                    for provider, count in providers.items()
                    if "fake" in provider.casefold()
                ),
                "template_fallback_count": sum(
                    1
                    for item in audits
                    if "template" in (item.error_code or "").casefold()
                ),
                "silent_fallback_count": sum(
                    count for provider, count in providers.items()
                    if provider != "openai_compatible"
                ),
                "partial_commit_count": sum(
                    item.get("state_restored") is not True
                    for item in self.operation_retries_by_session.get(session_id, ())
                ),
                "mutation_interface": "http_api_only",
                "failed_calls": self.operation_retries_by_session.get(session_id, []),
                "archive_reads": self.archive_reads_by_session.get(session_id, []),
                "decision_choices": decisions,
                "governance_actions": actions,
                "conversations": conversations,
                "meetings": meetings,
                "contracts": contracts,
                "administrative_documents": administrative_documents,
                "group_conversations": group_conversations,
                "known_fact_ids": sorted(stored.known_fact_ids),
                "night_logs": night_logs,
                "recovered_operation_retries": self.operation_retries_by_session.get(
                    session_id, []
                ),
            }
            result["operation_record"] = build_ending_operation_record(profile, result)
            validate_route_result(profile, result)
            return result
        finally:
            client.__exit__(None, None, None)

    def end_day(self, client, session_id, headers, result: dict, key: str) -> dict:
        for attempt in range(1, 4):
            print(f"{key}: submitting", file=sys.stderr, flush=True)
            response = client.post(
                f"/api/game/session/{session_id}/end-day",
                headers=headers,
                json={
                    "client_action_id": key,
                    "state_version": result["state_version"],
                    "retry": attempt > 1,
                },
            )
            if response.status_code == 200:
                payload = response.json()
                day = int(payload["visible_state"]["story"]["day"])
                visited = self.visited_days_by_session.setdefault(session_id, [])
                if not visited or visited[-1] != day:
                    visited.append(day)
                return payload
            if (
                _is_retryable_model_failure(response)
                and attempt < 3
            ):
                current = client.get(
                    f"/api/game/session/{session_id}", headers=headers
                )
                state_restored = (
                    current.status_code == 200
                    and _public_state_fingerprint(current.json())
                    == _public_state_fingerprint(result)
                )
                self.operation_retries_by_session.setdefault(session_id, []).append(
                    {
                        "operation": key,
                        "attempt": attempt,
                        "state_version": result["state_version"],
                        "state_restored": state_restored,
                    }
                )
                print(
                    f"{key}: retryable real-model failure, retrying unchanged state",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            raise AssertionError(
                f"{key}: expected 200, received {response.status_code}: {response.text}"
            )
        raise AssertionError(f"{key}: exhausted retry loop")

    def inspect_available_evidence(
        self,
        client: TestClient,
        session_id: str,
        headers: dict[str, str],
        result: dict,
        key: str,
    ) -> dict:
        """Read every newly available investigation archive, one transaction at a time."""
        if result.get("visible_state", {}).get("pending_decision"):
            return result
        while True:
            catalog = client.get(
                f"/api/game/session/{session_id}/actions", headers=headers
            )
            self.assertEqual(200, catalog.status_code, catalog.text)
            archive_variant = next(
                variant
                for action in catalog.json()["actions"]
                if action["action_id"] == "inspect_archives"
                for variant in action["variants"]
                if variant["variant_id"] == "consult_county_archives"
            )
            available = [
                item["target_id"]
                for item in archive_variant.get("target_choices", ())
                if item["target_id"] in EVIDENCE_ARCHIVE_IDS
            ]
            if not available:
                return result
            archive_id = available[0]
            response = client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=headers,
                json={
                    "state_version": result["state_version"],
                    "action_kind": "inspect_archives",
                    "variant_id": archive_variant["variant_id"],
                    "location_id": archive_variant["location_choices"][0]["location_id"],
                    "archive_ids": [archive_id],
                },
            )
            self.assertEqual(201, response.status_code, response.text)
            result = response.json()
            self.archive_reads_by_session.setdefault(session_id, []).append(
                {
                    "story_day": result["visible_state"]["story"]["day"],
                    "archive_id": archive_id,
                    "new_fact_ids": [
                        item["fact_id"]
                        for item in result.get("newly_learned_facts", ())
                    ],
                }
            )
            print(f"{key}: read {archive_id}", file=sys.stderr, flush=True)

    def reach_day_three(
        self, container, client, session_id, headers, route_index: int
    ) -> tuple[dict, int]:
        """Reach D3 through a real conversation that actually satisfies D2."""
        session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        result = {
            "state_version": session.state_version,
            "visible_state": {
                "pending_decision": {
                    "decision_id": session.pending_decision.decision_id,
                    "input_kind": session.pending_decision.input_kind,
                    "input_schema": session.pending_decision.input_schema,
                    "options": [
                        {"option_id": item.option_id, "available": item.available}
                        for item in session.pending_decision.options
                    ],
                }
            },
        }
        result, decision_index = self.drain_decisions(
            container, client, session_id, headers, result, route_index, 0
        )
        if route_index == 0:
            result = self.inspect_available_evidence(
                client, session_id, headers, result, "real-route-0-d1"
            )
        result = self.end_day(
            client, session_id, headers, result, f"real-route-{route_index}-end-d1"
        )
        result, decision_index = self.drain_decisions(
            container, client, session_id, headers, result, route_index, decision_index
        )
        if route_index == 0:
            result = self.inspect_available_evidence(
                client, session_id, headers, result, "real-route-0-d2"
            )

        prompts = (
            "请明确说明周氏宗族、散姓和关键村民之间的关系，不要只说笼统顾虑。",
            "请把周氏宗族在村里的权力关系和散姓住户的处境逐项说清楚。",
            "这次接触必须核实村里宗族力量分布，请给出你确认的关系脉络。",
        )
        conversation_id = None
        disclosed = False
        for attempt, player_text in enumerate(prompts, start=1):
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            if stored.active_conversation is None:
                started = self.action(
                    client,
                    session_id,
                    headers,
                    {
                        "input_mode": "conversation_start",
                        "client_action_id": f"real-route-{route_index}-wu-start-{attempt}",
                        "state_version": result["state_version"],
                        "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                        "target_npc_id": "npc_wu_xiuying",
                    },
                )
                result = started
                conversation_id = started["conversation"]["conversation_id"]
            else:
                conversation_id = stored.active_conversation.conversation_id
            result = self.action(
                client,
                session_id,
                headers,
                {
                    "input_mode": "free_text",
                    "client_action_id": f"real-route-{route_index}-wu-talk-{attempt}",
                    "state_version": result["state_version"],
                    "conversation_id": conversation_id,
                    "opportunity_id": "opp_d02_wu_xiuying_first_talk",
                    "target_npc_id": "npc_wu_xiuying",
                    "player_text": player_text,
                },
            )
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            disclosed = any(
                item.get("type") == "conversation_turn"
                and item.get("conversation_id") == conversation_id
                and item.get("disclosure_id") == "fact_clan_power_map"
                for item in stored.logs
            )
            if disclosed or "flag_wu_first_talk_completed" in stored.flags:
                break
        self.assertTrue(disclosed, "real D2 conversation did not disclose clan map")
        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        if stored.active_conversation is not None:
            result = self.action(
                client,
                session_id,
                headers,
                {
                    "input_mode": "conversation_end",
                    "client_action_id": f"real-route-{route_index}-wu-end",
                    "state_version": result["state_version"],
                    "conversation_id": stored.active_conversation.conversation_id,
                },
            )
            self.assertEqual("completed", result.get("completion_status"))
        return (
            self.end_day(
                client,
                session_id,
                headers,
                result,
                f"real-route-{route_index}-end-d2",
            ),
            decision_index,
        )

    def run_route(self, route_index: int) -> dict:
        container, client, session_id, headers = self.build_real_runner(route_index)
        started = time.perf_counter()
        result, decision_index = self.reach_day_three(
            container, client, session_id, headers, route_index
        )
        visited_days = [3]
        group_records: list[dict] = []
        for story_day in range(3, 91):
            if result["visible_state"]["status"] == "ended":
                break
            while result["visible_state"].get("active_group_conversation"):
                group = dict(result["visible_state"]["active_group_conversation"])
                resolved = group.get("phase") == "resolved"
                payload = {
                    "state_version": result["state_version"],
                    "client_action_id": (
                        f"real-route-{route_index}-group-{story_day:02d}-"
                        f"{len(group_records) + 1:02d}"
                    ),
                }
                if resolved:
                    response = client.post(
                        f"/api/game/session/{session_id}/group-conversation/finish",
                        headers=headers,
                        json=payload,
                    )
                else:
                    replies = credible_group_replies(group)
                    payload["player_text"] = replies[
                        len(group_records) % len(replies)
                    ]
                    response = self.group_conversation_turn_for_route(
                        client,
                        session_id,
                        headers,
                        payload,
                    )
                self.assertEqual(200, response.status_code, response.text)
                result = response.json()
                group_records.append({
                    "story_day": story_day,
                    "conversation_id": group.get("conversation_id"),
                    "conversation_type": group.get("conversation_type"),
                    "participant_ids": group.get("participant_ids", []),
                    "agenda": group.get("agenda"),
                    "round_after": (
                        result["visible_state"].get("active_group_conversation") or {}
                    ).get("round_index"),
                })
            result, decision_index = self.drain_decisions(
                container,
                client,
                session_id,
                headers,
                result,
                route_index,
                decision_index,
            )
            if route_index == 0:
                result = self.inspect_available_evidence(
                    client,
                    session_id,
                    headers,
                    result,
                    f"real-route-0-d{story_day:02d}",
                )
            if result["visible_state"]["story"]["day"] >= self.stop_day:
                break
            result = self.end_day(
                client,
                session_id,
                headers,
                result,
                f"real-route-{route_index}-end-{story_day:02d}",
            )
            visited_days.append(result["visible_state"]["story"]["day"])

        if self.stop_day == 90:
            self.assertEqual("ended", result["visible_state"]["status"])
            self.assertEqual(90, result["visible_state"]["story"]["day"])
        else:
            self.assertGreaterEqual(
                result["visible_state"]["story"]["day"], self.stop_day
            )
        stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        audits = container.llm_audits.list_for_session(session_id)
        statuses = Counter(item.status for item in audits)
        providers = Counter(item.provider for item in audits)
        night_plans = [
            {
                "story_day": record["story_day"],
                "created_plan_ids": [
                    item.get("plan_id")
                    for item in record.get("followup_decisions", ())
                    if item.get("created")
                ],
                "agent_exchange_count": len(record.get("agent_exchanges", ())),
            }
            for record in stored.night_logs
            if record.get("followup_decisions")
        ]
        return {
            "route_index": route_index,
            "session_id": session_id,
            "mode": "personal" if route_index == 1 else "server_default",
            "story_day": stored.game_state.story_day,
            "status": stored.status.value,
            "ending_id": (stored.ending_result or {}).get("main_ending_id"),
            "visited_days": visited_days,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "llm_audits": len(audits),
            "audit_statuses": dict(statuses),
            "providers": dict(providers),
            "fake_calls": sum(
                count for provider, count in providers.items()
                if "fake" in provider.casefold()
            ),
            "archive_mode": "evidence_investigation" if route_index == 0 else "ignore_archives",
            "archive_reads": self.archive_reads_by_session.get(session_id, []),
            "recovered_operation_retries": self.operation_retries_by_session.get(session_id, []),
            "group_turns": group_records,
            "night_followups": night_plans,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, default=PROFILE_PATH)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--route-ids",
        action="append",
        help=(
            "run only these catalog route IDs; may be repeated or comma-separated "
            "(this is not full acceptance)"
        ),
    )
    parser.add_argument(
        "--resume-run",
        type=Path,
        help="resume one existing evidence root after validating every completed route",
    )
    args = parser.parse_args()
    base_settings = Settings.from_env()
    package = FileScriptPackageLoader().load(PACKAGE_ROOT)
    profiles = load_witnesses(args.profiles)
    validate_profile_catalog(profiles, package)
    try:
        selected_profiles = select_route_profiles(profiles, args.route_ids)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    api_key = os.getenv(base_settings.role_llm_api_key_env, "").strip()
    validate_real_runner_settings(base_settings, api_key=api_key)
    selected_route_ids = [profile.route_id for _index, profile in selected_profiles]
    raw_provenance = build_run_metadata(
        repo_root=repository_root_for_backend(BACKEND_ROOT),
        backend_root=BACKEND_ROOT,
        route_ids=selected_route_ids,
    )
    provenance = {
        key: raw_provenance[key]
        for key in ("git_sha", "workspace_fingerprint", "v3_hash")
    }
    run_metadata = build_route_run_metadata(
        selected_route_ids=selected_route_ids,
        catalog_profile_count=len(profiles),
        provenance=provenance,
    )
    contract_terms = load_contract_terms(args.profiles)
    if args.resume_run is not None:
        root = args.resume_run.resolve()
        if not root.is_dir():
            raise SystemExit(f"resume evidence root does not exist: {root}")
        metadata_path = root / RUN_METADATA_NAME
        if not metadata_path.is_file():
            raise SystemExit(f"resume metadata is missing: {metadata_path}")
        try:
            validate_resume_metadata(
                json.loads(metadata_path.read_text(encoding="utf-8")), run_metadata
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    else:
        root = prepare_output_run(args.output_dir, run_id=args.run_id)
        (root / RUN_METADATA_NAME).write_text(
            json.dumps(run_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"evidence_dir={root}", file=sys.stderr, flush=True)
    runner = RealRouteRunner(
        base_settings,
        root,
        stop_day=90,
        retry_delays=(2, 5, 15, 30, 60),
    )
    route_root = root / "routes"
    route_root.mkdir(exist_ok=args.resume_run is not None)
    execution_profiles = tuple(profile for _index, profile in selected_profiles)
    completed = load_completed_route_evidence(route_root, execution_profiles)
    routes = execute_route_profiles(
        selected_profiles=selected_profiles,
        completed=completed,
        runner=runner,
        root=root,
        route_root=route_root,
        contract_terms=contract_terms,
    )
    no_archive_route = None
    if len(selected_profiles) == len(profiles):
        no_archive_route = runner.run_route(10_000)
        if (
            no_archive_route["status"] != "ended"
            or no_archive_route["story_day"] != 90
            or no_archive_route["archive_reads"]
            or no_archive_route["fake_calls"]
        ):
            raise AssertionError(
                f"real no-archive route did not legally reach D90: {no_archive_route}"
            )
        (route_root / "no-archive-baseline.json").write_text(
            json.dumps(no_archive_route, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    report = build_route_summary(
        profiles=profiles,
        selected_route_ids=selected_route_ids,
        routes=routes,
        provider="openai_compatible",
        model=base_settings.role_llm_model,
        no_archive_route=no_archive_route,
        provenance=provenance,
    )
    (root / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
