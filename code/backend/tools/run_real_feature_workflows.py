from __future__ import annotations

from collections.abc import Iterator
from collections import Counter
from dataclasses import asdict, fields, is_dataclass, replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from tools.run_real_v3_routes import (
    RealRouteRunner,
    credible_group_replies,
)
from tools.run_real_v3_routes import PROFILE_PATH
from tools.full_acceptance.ending_witnesses import load_contract_terms, load_witnesses
from serious_game_backend.config import Settings
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.llm_runtime import LLMCallAudit
from serious_game_backend.domain.game_session import GameSession
from tools.real_run_provenance import validate_published_package_identity


EXPECTED_GOVERNANCE_FAMILIES = {
    "inspect_archives",
    "household_visit",
    "cadre_interview",
    "leadership_meeting",
}
PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True, text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def capture_run_provenance(repository: Path) -> dict[str, object]:
    """Bind a run to clean tracked bytes and the published v3 manifest."""

    commit = _git(repository, "rev-parse", "HEAD")
    tracked_changes = _git(
        repository, "status", "--porcelain", "--untracked-files=no",
    ).splitlines()
    if tracked_changes:
        raise RuntimeError(
            "real feature evidence refuses a dirty tracked workspace: "
            + ", ".join(line[:200] for line in tracked_changes)
        )
    digest = hashlib.sha256()
    for relative in _git(repository, "ls-files").splitlines():
        path = repository / relative
        if not path.is_file():
            continue
        digest.update(relative.replace("\\", "/").encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "git_commit": commit,
        "tracked_workspace_clean": True,
        "workspace_fingerprint": digest.hexdigest(),
        **validate_published_package_identity(PACKAGE_DIR),
    }


def semantic_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=lambda item: getattr(item, "__dict__", repr(item)),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _contains_exact(value: object, expected: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_exact(item, expected) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_exact(item, expected) for item in value)
    return value == expected


_ENTITY_FIELDS = {
    "action_instance_id", "archive_id", "audit_status", "batch_id",
    "completion_status", "contract_id", "current_version", "document_id",
    "evidence_id", "household_id", "location_id", "meeting_id", "npc_id",
    "opportunity_id", "read_at_days", "signed_day", "state_version", "status",
}
_ALLOWED_EVIDENCE_KINDS = {
    "archives": {"server_entity_transition"},
    "fact_acquisition_paths": {"authoritative_reachability"},
    "opportunities": {"server_entity_transition"},
    "npcs": {"authoritative_reachability"},
    "map_locations": {"server_entity_transition"},
    "households": {"server_entity_transition"},
}
_REACHABILITY_SELECTORS = {
    "fact_acquisition_paths": "fact_acquisition_path_ids",
    "npcs": "npc_ids",
}


def _response_id_whitelist(value: object) -> list[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_id") and isinstance(item, str):
                values.add(item)
            elif key.endswith("_ids") and isinstance(item, list):
                values.update(str(entry) for entry in item if isinstance(entry, str))
            else:
                values.update(_response_id_whitelist(item))
    elif isinstance(value, list):
        for item in value:
            values.update(_response_id_whitelist(item))
    return sorted(values)


def _fact_acquisition_bindings(value: object) -> list[str]:
    """Extract only explicit fact/route/source triples from one formal DTO."""

    bindings: set[str] = set()
    if isinstance(value, dict):
        for item in value.get("fact_acquisition_bindings", ()):
            if not isinstance(item, dict):
                continue
            parts = (item.get("fact_id"), item.get("route_type"), item.get("source_id"))
            if all(isinstance(part, str) and part for part in parts):
                bindings.add(":".join(parts))
        for lead in value.get("investigation_leads", ()):
            if not isinstance(lead, dict):
                continue
            for method in lead.get("methods", ()):
                if not isinstance(method, dict):
                    continue
                parts = (
                    method.get("fact_id"), method.get("route_type"),
                    method.get("source_id"),
                )
                if method.get("fact_id") != lead.get("fact_id"):
                    continue
                if all(isinstance(part, str) and part for part in parts):
                    bindings.add(":".join(parts))
        for key, item in value.items():
            if key not in {"fact_acquisition_bindings", "investigation_leads"}:
                bindings.update(_fact_acquisition_bindings(item))
    elif isinstance(value, list):
        for item in value:
            bindings.update(_fact_acquisition_bindings(item))
    return sorted(bindings)


def _reachability_supported(
    selector: str, evidence_id: str, response_ids: set[str],
    fact_bindings: set[str],
) -> bool:
    if selector == "npcs":
        return evidence_id in response_ids
    if selector == "fact_acquisition_paths":
        return evidence_id in fact_bindings
    return False


def _attach_authority_projections(workflows: list[dict]) -> None:
    for workflow in workflows:
        workflow_key = f"{workflow['account']}:{workflow['session_id']}"
        sources = []
        for trace in workflow.get("api_traces", ()):
            if int(trace.get("status_code", 0)) not in range(200, 300):
                continue
            if not isinstance(trace.get("server_state_version_before"), int):
                continue
            if not isinstance(trace.get("server_state_version_after"), int):
                continue
            response = trace.get("response")
            sources.append({
                "path": trace["path"],
                "status_code": trace["status_code"],
                "state_version_before": trace["server_state_version_before"],
                "state_version_after": trace["server_state_version_after"],
                "session_id": workflow["session_id"],
                "response_ids": _response_id_whitelist(response),
                "fact_acquisition_bindings": _fact_acquisition_bindings(response),
                "response_whitelist_hash": semantic_hash(
                    _response_id_whitelist(trace.get("response"))
                ),
            })
        projection = {
            "workflow_key": workflow_key,
            "session_id": workflow["session_id"],
            "run_provenance": {
                "account_mode": workflow["account"],
                "story_day": workflow["story_day"],
            },
            "sources": sources,
            "items": {
                selector: [
                    {"evidence_id": str(item), "status": "completed"}
                    for item in workflow["coverage"].get(coverage_field, ())
                ]
                for selector, coverage_field in _REACHABILITY_SELECTORS.items()
            },
        }
        source_ids = {
            item for source in sources for item in source["response_ids"]
        }
        fact_bindings = {
            item for source in sources
            for item in source["fact_acquisition_bindings"]
        }
        for selector, items in projection["items"].items():
            missing = [
                item["evidence_id"] for item in items
                if not _reachability_supported(
                    selector, item["evidence_id"], source_ids, fact_bindings
                )
            ]
            if missing:
                raise AssertionError(
                    f"{selector} lacks formal HTTP DTO reachability: {missing[:3]}"
                )
        workflow["workflow_key"] = workflow_key
        workflow["authority_projection"] = projection
        workflow["authority_projection_hash"] = semantic_hash(projection)


def _find_entity_projections(
    value: object, evidence_id: str
) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        if any(
            key.endswith("_id") and item == evidence_id
            for key, item in value.items()
        ):
            projection = {
                key: item for key, item in value.items()
                if key in _ENTITY_FIELDS and not isinstance(item, (dict, list))
            }
            if "read_at_days" in value:
                projection["read_at_days"] = list(value["read_at_days"])
            yield projection
        for item in value.values():
            yield from _find_entity_projections(item, evidence_id)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _find_entity_projections(item, evidence_id)


def _validate_entity_projection(category: str, evidence_id: str, entity: dict) -> None:
    if not _contains_exact(entity, evidence_id):
        raise AssertionError(f"{category} readback entity ID is missing")
    if category == "households" and entity.get("status") != "signed":
        raise AssertionError("households readback entity is not signed")
    if category == "archives" and not entity.get("read_at_days"):
        raise AssertionError("archives readback entity was not read")
    if category == "opportunities" and entity.get("completion_status") != "completed":
        raise AssertionError("opportunities readback entity is not completed")
    if category == "map_locations" and entity.get("status") != "completed":
        raise AssertionError("map location action is not completed")


def _validated_entity_projection(
    category: str, evidence_id: str, trace: dict
) -> dict | None:
    for readback in trace.get("readbacks", ()):
        for projection in _find_entity_projections(
            readback.get("payload"), evidence_id
        ):
            try:
                _validate_entity_projection(category, evidence_id, projection)
            except AssertionError:
                continue
            return projection
    return None


def _response_links_entity(
    response: object, evidence_id: str, entity_projection: dict
) -> bool:
    if _contains_exact(response, evidence_id):
        return True
    stable_ids = {
        value
        for key, value in entity_projection.items()
        if key.endswith("_id") and key != "location_id" and isinstance(value, str)
    }
    return any(_contains_exact(response, value) for value in stable_ids)


class _ApiEvidenceRecorder:
    """Capture authoritative API transition triples without changing the API."""

    def __init__(self, client: TestClient, session_id: str, headers: dict[str, str]):
        self.client = client
        self.session_id = session_id
        self.headers = headers
        self.records: list[dict[str, object]] = []
        self._request = client.request

    def install(self) -> None:
        self.client.request = self.request  # type: ignore[method-assign]

    def request(self, method: str, url, **kwargs):
        method_upper = method.upper()
        path = urlsplit(str(url)).path
        mutation = method_upper in {"POST", "PUT", "PATCH", "DELETE"}
        belongs = f"/api/game/session/{self.session_id}" in path
        before = None
        if mutation and belongs:
            response = self._request(
                "GET", f"/api/game/session/{self.session_id}", headers=self.headers
            )
            if response.status_code == 200:
                before = response.json()
        result = self._request(method, url, **kwargs)
        try:
            response_body = result.json()
        except Exception:
            response_body = None
        if (
            not mutation
            and belongs
            and path.endswith("/knowledge")
            and result.status_code in range(200, 300)
        ):
            state_version = (
                response_body.get("state_version")
                if isinstance(response_body, dict) else None
            )
            if isinstance(state_version, int):
                self.records.append({
                    "method": method_upper,
                    "path": path,
                    "request_hash": semantic_hash({}),
                    "client_trace_id": None,
                    "status_code": result.status_code,
                    "server_state_version_before": state_version,
                    "server_state_version_after": state_version,
                    "response": response_body,
                    "readback_effect_hash": semantic_hash(response_body),
                    "readback_state_version": state_version,
                    "readbacks": [],
                    "partial_commit": False,
                })
        if mutation and belongs:
            request_body = kwargs.get("json") or {}
            readback_endpoints = [f"/api/game/session/{self.session_id}"]
            readback_endpoints.append(
                f"/api/game/session/{self.session_id}/review"
            )
            if "/governance" in path:
                readback_endpoints.append(
                    f"/api/game/session/{self.session_id}/governance"
                )
            if "/map" in path or "/governance/actions" in path:
                readback_endpoints.append(f"/api/game/session/{self.session_id}/map")
            conversation = (
                response_body.get("conversation", {})
                if isinstance(response_body, dict) else {}
            )
            if (
                isinstance(response_body, dict)
                and (
                    response_body.get("completion_status") == "completed"
                    or conversation.get("status") == "ended"
                )
            ):
                readback_endpoints.append(
                    f"/api/game/session/{self.session_id}/conversations?limit=100"
                )
            for archive_id in request_body.get("archive_ids", ()):
                readback_endpoints.append(
                    f"/api/game/session/{self.session_id}/governance/archives/"
                    f"{archive_id}"
                )
            readbacks = []
            for endpoint in readback_endpoints:
                candidate = self._request("GET", endpoint, headers=self.headers)
                if candidate.status_code == 200:
                    readbacks.append({"endpoint": endpoint, "payload": candidate.json()})
            readback = readbacks[0]["payload"] if readbacks else None
            self.records.append({
                "method": method_upper,
                "path": path,
                "request_hash": semantic_hash(request_body),
                "client_trace_id": request_body.get("client_action_id"),
                "status_code": result.status_code,
                "server_state_version_before": (
                    before.get("state_version") if isinstance(before, dict) else None
                ),
                "server_state_version_after": (
                    response_body.get("state_version")
                    if isinstance(response_body, dict) else None
                ),
                "response": response_body,
                "readback_effect_hash": (
                    semantic_hash(readback) if readback is not None else None
                ),
                "readback_state_version": (
                    readback.get("state_version")
                    if isinstance(readback, dict) else None
                ),
                "readbacks": readbacks,
                "partial_commit": (
                    result.status_code == 409
                    and before is not None
                    and readback is not None
                    and semantic_hash(before) != semantic_hash(readback)
                ),
            })
        return result


def _coverage_operation_records(workflows: list[dict]) -> dict[str, list[dict]]:
    mapping = {
        "archives": "archive_ids",
        "fact_acquisition_paths": "fact_acquisition_path_ids",
        "opportunities": "opportunity_ids",
        "npcs": "npc_ids",
        "map_locations": "map_location_ids",
        "households": "household_ids",
    }
    result: dict[str, list[dict]] = {}
    for category, coverage_field in mapping.items():
        records = []
        all_ids = sorted({
            str(value)
            for workflow in workflows
            for value in workflow["coverage"].get(coverage_field, ())
        })
        for evidence_id in all_ids:
            candidate = next((
                (trace, entity_projection)
                for workflow in workflows
                for trace in workflow.get("api_traces", ())
                if "server_entity_transition" in _ALLOWED_EVIDENCE_KINDS[category]
                if int(trace.get("status_code", 0)) in range(200, 300)
                and not str(trace.get("path", "")).endswith("/cancel")
                and (
                    category != "map_locations"
                    or str(trace.get("path", "")).endswith(("/finish", "/resolve"))
                )
                and (
                    category != "households"
                    or str(trace.get("path", "")).endswith("/review")
                )
                and isinstance(trace.get("server_state_version_before"), int)
                and isinstance(trace.get("server_state_version_after"), int)
                and trace.get("readback_effect_hash")
                if (
                    entity_projection := _validated_entity_projection(
                        category, evidence_id, trace
                    )
                ) is not None
                if _response_links_entity(
                    trace.get("response"), evidence_id, entity_projection
                )
            ), None)
            if candidate is not None:
                trace, entity_projection = candidate
                audit_ids = [
                    audit["audit_id"]
                    for workflow in workflows
                    for audit in workflow["audit"]["records"]
                    if evidence_id in str(audit["operation_id"])
                    or (
                        trace.get("client_trace_id")
                        and audit["operation_id"] == trace["client_trace_id"]
                    )
                ]
                records.append({
                    "evidence_id": evidence_id,
                    "evidence_kind": "server_entity_transition",
                    "request_hash": trace["request_hash"],
                    "server_state_version_before": trace["server_state_version_before"],
                    "server_state_version_after": trace["server_state_version_after"],
                    "response_entity_id": evidence_id,
                    "readback_effect_hash": trace["readback_effect_hash"],
                    "readback_state_version": trace["readback_state_version"],
                    "entity_projection": entity_projection,
                    "entity_projection_hash": semantic_hash(entity_projection),
                    "status": "succeeded",
                    "audit_ids": audit_ids,
                })
            else:
                if "authoritative_reachability" not in _ALLOWED_EVIDENCE_KINDS[category]:
                    response_mentions_id = any(
                        _contains_exact(trace.get("response"), evidence_id)
                        and int(trace.get("status_code", 0)) in range(200, 300)
                        for workflow in workflows
                        for trace in workflow.get("api_traces", ())
                    )
                    if response_mentions_id:
                        raise AssertionError(
                            f"{category} transition has no formal GET readback "
                            f"entity in valid state: {evidence_id}"
                        )
                    raise AssertionError(
                        f"{category} requires a server entity transition trace: {evidence_id}"
                    )
                workflow = next(
                    item for item in workflows
                    if evidence_id in item["coverage"].get(coverage_field, ())
                )
                records.append({
                    "evidence_id": evidence_id,
                    "evidence_kind": "authoritative_reachability",
                    "source_workflow_key": workflow["workflow_key"],
                    "source_projection_hash": workflow["authority_projection_hash"],
                    "source_item_selector": category,
                    "status": "succeeded",
                    "audit_ids": [],
                })
        result[category] = records
    return result


def _business_semantic_projection(session) -> dict[str, object]:
    """Stable business state restored by manual save/load; excludes lease metadata."""

    def plain(value):
        if is_dataclass(value):
            return {key: plain(item) for key, item in asdict(value).items()}
        if isinstance(value, dict):
            return {str(key): plain(item) for key, item in value.items()}
        if isinstance(value, (set, frozenset)):
            return sorted((plain(item) for item in value), key=repr)
        if isinstance(value, (list, tuple)):
            return [plain(item) for item in value]
        return value

    excluded_technical_fields = {
        # A load creates a new optimistic-concurrency revision and records its
        # source. These fields describe the restore transaction, not gameplay.
        "state_version", "processing_action_id", "loaded_from_snapshot_id",
        "timeline_id", "created_at", "updated_at",
    }
    authoritative_fields = {item.name for item in fields(GameSession)}
    required_business_fields = authoritative_fields - excluded_technical_fields
    missing = required_business_fields - set(asdict(session))
    if missing:
        raise AssertionError(
            "save/load semantic projection is missing authoritative fields: "
            + ", ".join(sorted(missing))
        )
    projection = {
        name: plain(getattr(session, name))
        for name in sorted(required_business_fields)
    }
    projection["logs"] = [
        item for item in projection["logs"]
        if not (
            item.get("type") == "snapshot_loaded"
            and item.get("visible_to_player") is False
            and isinstance(item.get("source_snapshot_id"), str)
            and isinstance(item.get("from_timeline_id"), str)
        )
    ]
    return projection


def assert_required_api_evidence_capabilities() -> None:
    """Stop instead of synthesizing per-call gateway provenance."""

    available = {item.name for item in fields(LLMCallAudit)}
    required = {"endpoint_host", "config_version"}
    missing = sorted(required - available)
    if missing:
        raise RuntimeError(
            "final real feature evidence gap: LLMCallAudit does not expose per-call "
            + " and ".join(missing)
            + "; refusing to infer or fabricate gateway isolation evidence"
        )


def _with_recovery_decision_policy(profile):
    """Keep exploratory routes playable when they unlock mistake-recovery scenes."""

    return replace(
        profile,
        decision_policy={
            **profile.decision_policy,
            "dp5_04_recovery": "a",
            "dp5_05_recovery": "b",
        },
    )


def validate_feature_workflow_report(report: dict[str, object]) -> None:
    """Fail closed unless every published system has real execution evidence."""

    if report.get("provider") != "openai_compatible":
        raise AssertionError("feature workflow did not use openai_compatible")
    for field in (
        "fake_calls", "template_fallback_count", "silent_fallback_count",
        "partial_commit_count",
    ):
        if field not in report or int(report[field]) != 0:
            raise AssertionError(f"{field} must be present and equal zero")
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise AssertionError("provenance is missing")
    if not _GIT_SHA.fullmatch(str(provenance.get("git_commit", ""))):
        raise AssertionError("provenance git_commit is not a full Git SHA")
    if provenance.get("tracked_workspace_clean") is not True:
        raise AssertionError("tracked workspace was not clean")
    if not re.fullmatch(
        r"[0-9a-f]{64}", str(provenance.get("workspace_fingerprint", ""))
    ):
        raise AssertionError("workspace fingerprint is missing or malformed")
    declared = str(provenance.get("v3_manifest_hash", ""))
    raw = str(provenance.get("v3_raw_hash", ""))
    portable = str(provenance.get("v3_portable_hash", ""))
    if (
        not _SHA256.fullmatch(declared)
        or not _SHA256.fullmatch(raw)
        or not _SHA256.fullmatch(portable)
        or provenance.get("v3_package_identity_verified") is not True
    ):
        raise AssertionError("v3 published package identity is not verified")
    if int(report.get("server_default_accounts", 0)) < 1:
        raise AssertionError("server-default account evidence is missing")
    if int(report.get("personal_api_accounts", 0)) < 1:
        raise AssertionError("personal API account evidence is missing")
    if report.get("account_gateway_isolation") is not True:
        raise AssertionError("account gateway isolation was not demonstrated")
    requirements = (
        ("archive_ids", 11, "11 archives"),
        ("fact_acquisition_path_ids", 27, "27 fact acquisition paths"),
        ("opportunity_ids", 32, "32 opportunities"),
        ("npc_ids", 29, "29 NPCs"),
        ("map_location_ids", 8, "8 map locations"),
        ("household_ids", 36, "36 households"),
    )
    for field, expected, label in requirements:
        values = {str(item) for item in report.get(field, ())}
        if len(values) != expected:
            raise AssertionError(f"expected {label}, got {len(values)}")
    records = report.get("operation_records")
    if not isinstance(records, dict):
        raise AssertionError("operation_records are missing")
    workflow_values = report.get("workflows")
    if not isinstance(workflow_values, list) or not workflow_values:
        raise AssertionError("workflow authority projections are missing")
    workflow_authorities: dict[str, dict] = {}
    for workflow in workflow_values:
        if not isinstance(workflow, dict):
            raise AssertionError("workflow authority projection is malformed")
        key = str(workflow.get("workflow_key", ""))
        projection = workflow.get("authority_projection")
        if (
            not key
            or not isinstance(projection, dict)
            or projection.get("workflow_key") != key
            or projection.get("session_id") != workflow.get("session_id")
            or workflow.get("authority_projection_hash") != semantic_hash(projection)
        ):
            raise AssertionError("workflow authority projection provenance is invalid")
        sources = projection.get("sources")
        if not isinstance(sources, list) or not sources:
            raise AssertionError("workflow authority HTTP sources are missing")
        for source in sources:
            if (
                not str(source.get("path", "")).startswith("/api/game/session/")
                and not str(source.get("path", "")).startswith("/formal/")
            ):
                raise AssertionError("workflow authority HTTP path is invalid")
            if int(source.get("status_code", 0)) not in range(200, 300):
                raise AssertionError("workflow authority HTTP status is invalid")
            if (
                not isinstance(source.get("state_version_before"), int)
                or not isinstance(source.get("state_version_after"), int)
                or source["state_version_after"] < source["state_version_before"]
            ):
                raise AssertionError("workflow authority HTTP state version is invalid")
            if source.get("session_id") != workflow.get("session_id"):
                raise AssertionError("workflow authority HTTP session is inconsistent")
            if source.get("response_whitelist_hash") != semantic_hash(
                source.get("response_ids", [])
            ):
                raise AssertionError("workflow authority response hash is invalid")
        workflow_authorities[key] = projection
    record_requirements = {
        "archives": (11, "archive_ids"),
        "fact_acquisition_paths": (27, "fact_acquisition_path_ids"),
        "opportunities": (32, "opportunity_ids"),
        "npcs": (29, "npc_ids"),
        "map_locations": (8, "map_location_ids"),
        "households": (36, "household_ids"),
    }
    for category, (expected, coverage_field) in record_requirements.items():
        items = records.get(category)
        if not isinstance(items, list) or len(items) != expected:
            raise AssertionError(
                f"expected {expected} {category} operation records"
            )
        evidence_ids = set()
        for item in items:
            required = {"evidence_id", "evidence_kind", "status", "audit_ids"}
            if not isinstance(item, dict) or not required <= item.keys():
                raise AssertionError(f"{category} operation record is incomplete")
            if item["status"] != "succeeded":
                raise AssertionError(f"{category} operation did not succeed")
            if not isinstance(item["audit_ids"], list):
                raise AssertionError(f"{category} audit IDs are malformed")
            if item["evidence_kind"] not in _ALLOWED_EVIDENCE_KINDS[category]:
                raise AssertionError(f"{category} evidence kind is not allowed")
            if item["evidence_kind"] == "server_entity_transition":
                transition_fields = {
                    "request_hash", "server_state_version_before",
                    "server_state_version_after", "response_entity_id",
                    "readback_effect_hash", "readback_state_version",
                    "entity_projection", "entity_projection_hash",
                }
                if not transition_fields <= item.keys():
                    raise AssertionError(f"{category} transition evidence is incomplete")
                if int(item["server_state_version_after"]) <= int(
                    item["server_state_version_before"]
                ):
                    raise AssertionError(f"{category} operation version did not advance")
                if item["readback_state_version"] != item["server_state_version_after"]:
                    raise AssertionError(f"{category} readback version is inconsistent")
                if item["response_entity_id"] != item["evidence_id"]:
                    raise AssertionError(f"{category} response entity is inconsistent")
                if not _SHA256.fullmatch(str(item["request_hash"])) or not _SHA256.fullmatch(
                    str(item["readback_effect_hash"])
                ):
                    raise AssertionError(f"{category} transition hashes are malformed")
                _validate_entity_projection(
                    category, item["evidence_id"], item["entity_projection"]
                )
                if item["entity_projection_hash"] != semantic_hash(
                    item["entity_projection"]
                ):
                    raise AssertionError(f"{category} entity projection hash is invalid")
            elif item["evidence_kind"] == "authoritative_reachability":
                reachability_fields = {
                    "source_workflow_key", "source_projection_hash",
                    "source_item_selector",
                }
                if not reachability_fields <= item.keys():
                    raise AssertionError(f"{category} reachability evidence is incomplete")
                selector = item["source_item_selector"]
                projection = workflow_authorities.get(item["source_workflow_key"])
                if (
                    not isinstance(projection, dict)
                    or selector != category
                    or selector not in _REACHABILITY_SELECTORS
                    or item["source_projection_hash"] != semantic_hash(projection)
                ):
                    raise AssertionError(f"{category} reachability projection is invalid")
                selected_items = projection.get("items", {}).get(selector)
                if not isinstance(selected_items, list) or not any(
                    candidate.get("evidence_id") == item["evidence_id"]
                    and candidate.get("status") == "completed"
                    for candidate in selected_items
                    if isinstance(candidate, dict)
                ):
                    raise AssertionError(f"{category} reachability selector did not match")
            else:
                raise AssertionError(f"{category} evidence kind is unsupported")
            evidence_ids.add(str(item["evidence_id"]))
        if len(evidence_ids) != expected:
            raise AssertionError(f"{category} operation records are not unique")
        if evidence_ids != {str(item) for item in report[coverage_field]}:
            raise AssertionError(f"{category} operation records do not match coverage")
        if category in _REACHABILITY_SELECTORS:
            projected_ids = {
                str(item.get("evidence_id"))
                for projection in workflow_authorities.values()
                for item in projection.get("items", {}).get(category, ())
                if isinstance(item, dict) and item.get("status") == "completed"
            }
            if projected_ids != evidence_ids:
                raise AssertionError(
                    f"{category} workflow projection does not match coverage"
                )
    meeting_record = report.get("meeting_document_record")
    if not isinstance(meeting_record, dict):
        raise AssertionError("meeting/document operation record is missing")
    if meeting_record.get("source_meeting_id") != meeting_record.get("meeting_id"):
        raise AssertionError("document source_meeting_id does not match its meeting")
    if not meeting_record.get("resolution_snapshot"):
        raise AssertionError("document resolution_snapshot is missing")
    if meeting_record.get("document_status") != "issued":
        raise AssertionError("meeting document was not issued")
    steps = meeting_record.get("steps")
    expected_steps = ("meeting", "turn", "resolve", "countersign", "issue")
    if not isinstance(steps, list) or tuple(
        item.get("name") for item in steps if isinstance(item, dict)
    ) != expected_steps:
        raise AssertionError("meeting/document step records are incomplete")
    for item in steps:
        identity_fields = {
            "server_operation": "server_operation_id",
            "client_request": "client_request_id",
            "persistent_entity": "persistent_entity_id",
        }
        identity_field = identity_fields.get(item.get("evidence_type"))
        if not identity_field or not item.get(identity_field) or not {
            "before_version", "after_version",
        } <= item.keys():
            raise AssertionError("meeting/document operation identity is missing")
        if int(item["after_version"]) <= int(item["before_version"]):
            raise AssertionError("meeting/document state version did not advance")
    for previous, current in zip(steps, steps[1:]):
        if previous["after_version"] != current["before_version"]:
            raise AssertionError("meeting/document state version chain is broken")
    if meeting_record.get("resolution_hash") != semantic_hash(
        meeting_record["resolution_snapshot"]
    ):
        raise AssertionError("meeting resolution hash does not match snapshot")
    if not meeting_record.get("llm_audit_ids"):
        raise AssertionError("meeting LLM audit IDs are missing")
    gateway = report.get("gateway_audit")
    gateway_records = gateway.get("records") if isinstance(gateway, dict) else None
    if not isinstance(gateway_records, list) or gateway.get("interleaved") is not True:
        raise AssertionError("account gateway interleaving evidence is missing")
    modes = {item.get("mode") for item in gateway_records if isinstance(item, dict)}
    accounts = {item.get("account_id") for item in gateway_records if isinstance(item, dict)}
    sessions = {item.get("session_id") for item in gateway_records if isinstance(item, dict)}
    required_gateway = {
        "account_id", "session_id", "mode", "endpoint_host", "model",
        "config_version",
    }
    account_modes: dict[str, set[str]] = {}
    session_accounts: dict[str, set[str]] = {}
    for item in gateway_records:
        account_modes.setdefault(str(item.get("account_id")), set()).add(
            str(item.get("mode"))
        )
        session_accounts.setdefault(str(item.get("session_id")), set()).add(
            str(item.get("account_id"))
        )
    if (
        modes != {"server_default", "personal"}
        or len(accounts) < 2 or len(sessions) < 2
        or any(len(value) != 1 for value in account_modes.values())
        or any(len(value) != 1 for value in session_accounts.values())
        or any(not required_gateway <= item.keys() for item in gateway_records)
        or any(
            not item.get("endpoint_host")
            or not item.get("model")
            or not item.get("config_version")
            for item in gateway_records
        )
        or any(
            not any(
                item.get("mode") == mode and item.get("status") in {"succeeded", "cached"}
                for item in gateway_records
            )
            for mode in modes
        )
    ):
        raise AssertionError("account gateway isolation evidence is inconsistent")
    gateway_audit_ids = {
        str(item.get("audit_id")) for item in gateway_records if item.get("audit_id")
    }
    if not set(map(str, meeting_record["llm_audit_ids"])) <= gateway_audit_ids:
        raise AssertionError("meeting audit IDs are absent from gateway evidence")
    linked_operation_audits = {
        str(audit_id)
        for items in records.values()
        for item in items
        for audit_id in item["audit_ids"]
    }
    if not linked_operation_audits <= gateway_audit_ids:
        raise AssertionError("operation audit IDs are absent from gateway evidence")
    save_load = report.get("save_load_record")
    if not isinstance(save_load, dict) or not {
        "before_semantic_hash", "after_semantic_hash", "save_operation_id",
        "load_operation_id",
    } <= save_load.keys():
        raise AssertionError("save/load semantic record is missing")
    if (
        save_load["before_semantic_hash"] != save_load["after_semantic_hash"]
        or not _SHA256.fullmatch(str(save_load["before_semantic_hash"]))
    ):
        raise AssertionError("save/load semantic hashes do not match")
    families = {str(item) for item in report.get("governance_action_families", ())}
    if families != EXPECTED_GOVERNANCE_FAMILIES:
        raise AssertionError(
            "four governance action families were not all exercised: "
            f"{sorted(families)}"
        )
    for field, label in (
        ("meeting_completed", "meeting"),
        ("contract_completed", "contract"),
        ("document_completed", "document"),
        ("save_load_completed", "save/load"),
        ("review_completed", "review"),
    ):
        if report.get(field) is not True:
            raise AssertionError(f"{label} workflow evidence is missing")
    review_statuses = {
        str(item) for item in report.get("contract_review_statuses", ())
    }
    if "signed" not in review_statuses or "accepted" in review_statuses:
        raise AssertionError(
            "contract review must finish in signed state without a second sign step"
        )


def collect_session_coverage(
    session,
    package: ScriptPackage,
    *,
    map_location_ids: set[str] | None = None,
    api_traces: list[dict] | None = None,
) -> dict[str, list[str]]:
    """Derive coverage only from persisted, player-reachable transaction records."""

    archive_ids = {
        archive_id
        for archive_id, record in session.archive_records.items()
        if record.read_at_days
        and archive_id
        in {item.archive_id for item in package.archive_investigations}
    }
    completed = {
        item.opportunity_id
        for item in session.completed_conversations
        if item.completion_status == "completed"
    }
    opportunity_ids = {
        item.opportunity_id
        for item in package.interaction_opportunities
        if item.opportunity_id in completed
    }
    npc_ids = {
        item.npc_id
        for item in session.completed_conversations
        if item.completion_status == "completed"
    }
    path_ids = {
        binding
        for trace in (api_traces or ())
        for binding in _fact_acquisition_bindings(trace.get("response"))
    }
    household_ids = {
        contract.household_id
        for contract in session.household_contracts.values()
        if contract.status == "signed"
    }
    action_families = {
        item.action_kind for item in session.governance_actions.values()
    }
    return {
        "archive_ids": sorted(archive_ids),
        "fact_acquisition_path_ids": sorted(path_ids),
        "opportunity_ids": sorted(opportunity_ids),
        "npc_ids": sorted(npc_ids),
        "map_location_ids": sorted(map_location_ids or set()),
        "household_ids": sorted(household_ids),
        "governance_action_families": sorted(action_families),
    }


def _expect(response, status: int = 200) -> dict:
    if response.status_code != status:
        raise AssertionError(
            f"expected HTTP {status}, received {response.status_code}: {response.text}"
        )
    return response.json()


def _governance_action(
    client: TestClient, session_id: str, headers: dict[str, str], payload: dict
) -> dict:
    return _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/actions",
            headers=headers,
            json=payload,
        ),
        201,
    )


def _finish_action(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    action_id: str,
    state_version: int,
) -> dict:
    return _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/actions/{action_id}/finish",
            headers=headers,
            json={"state_version": state_version},
        )
    )


def _drain_group_conversations(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    result: dict,
    key: str,
    runner: RealRouteRunner | None = None,
) -> dict:
    turn = 0
    while result["visible_state"].get("active_group_conversation"):
        turn += 1
        if turn > 40:
            raise AssertionError("forced conversation did not settle after 40 real turns")
        group = result["visible_state"]["active_group_conversation"]
        resolved = group.get("phase") == "resolved"
        payload = {
            "state_version": result["state_version"],
            "client_action_id": f"{key}-{turn:02d}",
        }
        if resolved:
            response = client.post(
                f"/api/game/session/{session_id}/group-conversation/finish",
                headers=headers,
                json=payload,
            )
        else:
            replies = credible_group_replies(group)
            payload["player_text"] = replies[(turn - 1) % len(replies)]
            if runner is None:
                response = client.post(
                    f"/api/game/session/{session_id}/group-conversation/turn",
                    headers=headers,
                    json=payload,
                )
            else:
                response = runner.group_conversation_turn_for_route(
                    client,
                    session_id,
                    headers,
                    payload,
                )
        result = _expect(response)
    return result


def _audit_summary(container, session_id: str) -> dict:
    audits = container.llm_audits.list_for_session(session_id)
    providers = Counter(item.provider for item in audits)
    statuses = Counter(item.status for item in audits)
    return {
        "calls": len(audits),
        "statuses": dict(statuses),
        "providers": dict(providers),
        "fake_calls": sum(
            count for provider, count in providers.items()
            if "fake" in provider.casefold()
        ),
        "template_fallback_count": sum(
            "template" in str(item.error_code or "").casefold() for item in audits
        ),
        "silent_fallback_count": sum(
            item.provider != "openai_compatible" for item in audits
        ),
        "records": [{
            "audit_id": item.audit_id,
            "operation_id": item.operation_id,
            "account_id": item.account_id,
            "session_id": item.session_id,
            "provider": item.provider,
            "model": item.model_id,
            "endpoint_host": item.endpoint_host,
            "config_version": item.config_version,
            "status": item.status,
            "error_code": item.error_code,
            "timestamp": item.created_at,
        } for item in audits],
    }


def _start_and_talk(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    *,
    state_version: int,
    action_kind: str,
    target_id: str,
    topic: str,
    player_text: str,
) -> dict:
    action_catalog = _expect(
        client.get(f"/api/game/session/{session_id}/actions", headers=headers)
    )["actions"]
    action_descriptor = next(
        item for item in action_catalog if item["action_id"] == action_kind
    )
    variant = next(
        (
            item
            for item in action_descriptor["variants"]
            if not item.get("target_choices")
            or target_id
            in {choice["target_id"] for choice in item["target_choices"]}
        ),
        action_descriptor["variants"][0],
    )
    started = _governance_action(
        client,
        session_id,
        headers,
        {
            "state_version": state_version,
            "action_kind": action_kind,
            "variant_id": variant["variant_id"],
            "location_id": variant["location_choices"][0]["location_id"],
            "target_ids": [target_id],
            "topic": topic,
        },
    )
    action_id = started["action"]["action_instance_id"]
    turn = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/actions/{action_id}/turn",
            headers=headers,
            json={
                "state_version": started["state_version"],
                "player_text": player_text,
                "client_action_id": f"feature-turn-{action_id}",
            },
        )
    )
    return {
        "started": started,
        "turn": turn,
        "action_id": action_id,
    }


def _acquire_targeted_conversation_facts(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    result: dict,
    *,
    opportunity_id: str,
    npc_id: str,
    prompts: tuple[tuple[str, str], ...],
    key: str,
) -> dict:
    """Prove first acquisition from one formal conversation, fact by fact."""

    initial_knowledge = _expect(
        client.get(f"/api/game/session/{session_id}/knowledge", headers=headers)
    )
    already_known = set(initial_knowledge.get("known_fact_ids", ()))
    requested_ids = {fact_id for fact_id, _player_text in prompts}
    collision = requested_ids & already_known
    if collision:
        raise AssertionError(
            "target fact already known before conversation: "
            f"{sorted(collision)}"
        )
    started = _expect(client.post(
        f"/api/game/session/{session_id}/action",
        headers=headers,
        json={
            "input_mode": "conversation_start",
            "client_action_id": f"{key}-start",
            "state_version": result["state_version"],
            "opportunity_id": opportunity_id,
            "target_npc_id": npc_id,
        },
    ))
    conversation_id = started["conversation"]["conversation_id"]
    current = started
    for index, (fact_id, player_text) in enumerate(prompts, start=1):
        before = set(_expect(client.get(
            f"/api/game/session/{session_id}/knowledge", headers=headers
        )).get("known_fact_ids", ()))
        if fact_id in before:
            raise AssertionError(
                f"target fact already known before conversation turn: {fact_id}"
            )
        current = _expect(client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json={
                "input_mode": "free_text",
                "client_action_id": f"{key}-turn-{index:02d}",
                "state_version": current["state_version"],
                "conversation_id": conversation_id,
                "opportunity_id": opportunity_id,
                "target_npc_id": npc_id,
                "player_text": player_text,
            },
        ))
        expected_binding = f"{fact_id}:conversation:{opportunity_id}"
        bindings = set(_fact_acquisition_bindings(current))
        after = set(_expect(client.get(
            f"/api/game/session/{session_id}/knowledge", headers=headers
        )).get("known_fact_ids", ()))
        if fact_id not in after - before or expected_binding not in bindings:
            raise AssertionError(
                "targeted conversation lacked first-acquisition transition and exact "
                f"binding: {expected_binding}"
            )
    if current.get("visible_state", {}).get("active_conversation") is not None:
        current = _expect(client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json={
                "input_mode": "conversation_end",
                "client_action_id": f"{key}-end",
                "state_version": current["state_version"],
                "conversation_id": conversation_id,
            },
        ))
    return current


def _server_default_workflow(
    runner: RealRouteRunner, root: Path
) -> dict:
    container, client, session_id, headers = runner.build_real_runner(0)
    recorder = _ApiEvidenceRecorder(client, session_id, headers)
    recorder.install()
    result, decision_index = runner.reach_day_three(
        container, client, session_id, headers, 0
    )
    result, decision_index = runner.drain_decisions(
        container,
        client,
        session_id,
        headers,
        result,
        0,
        decision_index,
    )
    ap_before = result["visible_state"]["ledger"]["action_points"]["remaining"]

    actions = _expect(
        client.get(f"/api/game/session/{session_id}/actions", headers=headers)
    )["actions"]
    archive = next(
        variant
        for action in actions
        for variant in action["variants"]
        if variant["variant_id"] == "consult_county_archives"
    )
    archived = result
    for archive_id in ("archive:doc_compensation_policy_v1",):
        archived = _governance_action(
            client,
            session_id,
            headers,
            {
                "state_version": archived["state_version"],
                "action_kind": archive["action_id"],
                "variant_id": archive["variant_id"],
                "location_id": archive["location_choices"][0]["location_id"],
                "archive_ids": [archive_id],
            },
        )

    household = _start_and_talk(
        client,
        session_id,
        headers,
        state_version=archived["state_version"],
        action_kind="household_visit",
        target_id="npc_zhou_dashan",
        topic="核实搬迁程序与逐户顾虑",
        player_text="请只说明已经确认的搬迁顾虑、程序依据和需要落实的下一步。",
    )
    finished_household = _finish_action(
        client,
        session_id,
        headers,
        household["action_id"],
        household["turn"]["state_version"],
    )

    cadre = _start_and_talk(
        client,
        session_id,
        headers,
        state_version=finished_household["state_version"],
        action_kind="cadre_interview",
        target_id="npc_zheng_xiangdong",
        topic="核实财政边界与公开口径",
        player_text="请按现有文件说明财政边界、公开口径和责任期限。",
    )
    finished_cadre = _finish_action(
        client,
        session_id,
        headers,
        cadre["action_id"],
        cadre["turn"]["state_version"],
    )

    meeting_action = next(
        item for item in actions if item["action_id"] == "leadership_meeting"
    )
    meeting_variant = meeting_action["variants"][0]
    meeting = _governance_action(
        client,
        session_id,
        headers,
        {
            "state_version": finished_cadre["state_version"],
            "action_kind": "leadership_meeting",
            "variant_id": meeting_variant["variant_id"],
            "location_id": meeting_variant["location_choices"][0]["location_id"],
            "target_ids": ["npc_zhao_jianguo", "npc_sun_qiang"],
            "lead_npc_id": "npc_zhao_jianguo",
            "topic": "搬迁材料自查与责任分工",
            "archive_ids": ["archive:doc_compensation_policy_v1"],
            "proposed_document_type": "investigation_notice",
        },
    )
    meeting_id = meeting["meeting"]["meeting_id"]
    meeting_turn = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/meetings/{meeting_id}/turn",
            headers=headers,
            json={
                "state_version": meeting["state_version"],
                "player_text": "请分别表态，并明确材料自查、责任人、期限和公开范围。",
                "client_action_id": f"feature-meeting-turn-{meeting_id}",
            },
        )
    )
    resolved = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/meetings/{meeting_id}/resolve",
            headers=headers,
            json={
                "state_version": meeting_turn["state_version"],
                "adopt": True,
                "resolution": {
                    "decision": "启动搬迁材料专项自查并公开办理节点",
                    "target_scope": "搬迁项目现有材料",
                    "resources": {},
                    "resource_mode": "authorization_ceiling",
                    "responsible_ids": ["npc_zhao_jianguo", "npc_sun_qiang"],
                    "deadline_day": 10,
                    "public_scope": ["全村36户"],
                    "document_title": "柳林村搬迁材料专项调查通知",
                },
            },
        )
    )
    document = resolved["document"]
    countersigned = resolved
    countersign_attempts = 0
    countersign_before_version = resolved["state_version"]
    while countersign_attempts < 3:
        countersign_attempts += 1
        countersigned = _expect(
            client.post(
                f"/api/game/session/{session_id}/governance/documents/{document['document_id']}/countersign",
                headers=headers,
                json={
                    "state_version": countersigned["state_version"],
                    "npc_id": "npc_zhao_jianguo",
                },
            )
        )
        if countersigned.get("accepted"):
            break
    if not countersigned.get("accepted"):
        raise AssertionError(
            "document countersigner rejected three explicit player attempts"
        )
    issued = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/documents/{document['document_id']}/issue",
            headers=headers,
            json={"state_version": countersigned["state_version"]},
        )
    )

    pre_save = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if pre_save is None:
        raise AssertionError("session disappeared before manual save")
    before_semantic_hash = semantic_hash(_business_semantic_projection(pre_save))
    save_client_action_id = "feature-server-manual-save"
    saved = _expect(
        client.post(
            f"/api/game/session/{session_id}/manual-saves",
            headers=headers,
            json={
                "client_action_id": save_client_action_id,
                "state_version": issued["state_version"],
                "slot_number": 1,
                "display_name": "真实接口全功能节点",
                "overwrite": False,
            },
        )
    )
    before_load = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    load_client_action_id = "feature-server-manual-load"
    loaded = _expect(
        client.post(
            f"/api/game/session/{session_id}/load-snapshot",
            headers=headers,
            json={
                "client_action_id": load_client_action_id,
                "state_version": saved["state_version"],
                "snapshot_id": saved["snapshot_id"],
                "confirmed": True,
            },
        )
    )
    after_load = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if before_load is None or after_load is None:
        raise AssertionError("session disappeared during save/load workflow")
    after_semantic_hash = semantic_hash(_business_semantic_projection(after_load))
    semantic_equal = before_semantic_hash == after_semantic_hash
    if not semantic_equal:
        raise AssertionError("manual load did not restore the saved business state")
    _expect(client.get(
        f"/api/game/session/{session_id}/knowledge", headers=headers
    ))
    audit = _audit_summary(container, session_id)
    recovered_retries = len(runner.operation_retries_by_session.get(session_id, ()))
    if (
        audit["fake_calls"]
        or any(
            item.get("state_restored") is not True
            for item in runner.operation_retries_by_session.get(session_id, ())
        )
    ):
        raise AssertionError(f"real server workflow audit failed: {audit}")
    package = container.packages.get("pkg_gameplay_v3")
    if package is None:
        raise AssertionError("v3 package disappeared during server workflow")
    coverage = collect_session_coverage(
        after_load, package, api_traces=recorder.records
    )
    save_operation = _expect(client.get(
        f"/api/game/session/{session_id}/operations/{save_client_action_id}",
        headers=headers,
    ))
    load_operation = _expect(client.get(
        f"/api/game/session/{session_id}/operations/{load_client_action_id}",
        headers=headers,
    ))
    meeting_audits = [
        item for item in audit["records"]
        if meeting_id in item["operation_id"]
        or document["document_id"] in item["operation_id"]
    ]
    payload = {
        "account": "server_default",
        "session_id": session_id,
        "story_day": after_load.game_state.story_day,
        "action_points_before": ap_before,
        "action_points_after": after_load.game_state.action_points,
        "four_action_families": [
            "inspect_archives",
            "household_visit",
            "cadre_interview",
            "leadership_meeting",
        ],
        "meeting_npc_order": [
            item["npc_id"]
            for item in meeting_turn["transcript"]
            if item["speaker_type"] == "npc"
        ],
        "document_status": issued["document"]["status"],
        "countersign_attempts": countersign_attempts,
        "manual_save_load_semantic_equal": semantic_equal,
        "save_load_record": {
            "before_semantic_hash": before_semantic_hash,
            "after_semantic_hash": after_semantic_hash,
            "save_client_request_id": save_client_action_id,
            "load_client_request_id": load_client_action_id,
            "save_operation_id": save_operation["operation_id"],
            "load_operation_id": load_operation["operation_id"],
            "save_status": save_operation["status"],
            "load_status": load_operation["status"],
            "save_state_version_before": issued["state_version"],
            "save_state_version_after": saved["state_version"],
            "load_state_version_before": saved["state_version"],
            "load_state_version_after": loaded["state_version"],
        },
        "meeting_document_record": {
            "meeting_id": meeting_id,
            "source_meeting_id": issued["document"]["source_meeting_id"],
            "resolution_snapshot": issued["document"]["resolution_snapshot"],
            "resolution_hash": semantic_hash(
                issued["document"]["resolution_snapshot"]
            ),
            "document_id": document["document_id"],
            "document_status": issued["document"]["status"],
            "llm_audit_ids": [item["audit_id"] for item in meeting_audits],
            "steps": [
                {
                    "name": "meeting",
                    "evidence_type": "persistent_entity",
                    "persistent_entity_id": meeting["action"]["action_instance_id"],
                    "before_version": finished_cadre["state_version"],
                    "after_version": meeting["state_version"],
                    "audit_ids": [],
                },
                {
                    "name": "turn",
                    "evidence_type": "client_request",
                    "client_request_id": f"feature-meeting-turn-{meeting_id}",
                    "before_version": meeting["state_version"],
                    "after_version": meeting_turn["state_version"],
                    "audit_ids": [item["audit_id"] for item in meeting_audits],
                },
                {
                    "name": "resolve",
                    "evidence_type": "persistent_entity",
                    "persistent_entity_id": meeting_id,
                    "before_version": meeting_turn["state_version"],
                    "after_version": resolved["state_version"],
                    "audit_ids": [],
                },
                {
                    "name": "countersign",
                    "evidence_type": "persistent_entity",
                    "persistent_entity_id": document["document_id"],
                    "before_version": countersign_before_version,
                    "after_version": countersigned["state_version"],
                    "audit_ids": [
                        item["audit_id"] for item in meeting_audits
                        if "countersign" in item["operation_id"]
                    ],
                },
                {
                    "name": "issue",
                    "evidence_type": "persistent_entity",
                    "persistent_entity_id": document["document_id"],
                    "before_version": countersigned["state_version"],
                    "after_version": issued["state_version"],
                    "audit_ids": [],
                },
            ],
        },
        "recovered_operation_retries": recovered_retries,
        "audit": audit,
        "coverage": coverage,
        "coverage_effect_hash": semantic_hash(_business_semantic_projection(after_load)),
        "api_traces": recorder.records,
    }
    client.__exit__(None, None, None)
    return payload


def _personal_contract_workflow(
    runner: RealRouteRunner, root: Path
) -> dict:
    container, client, session_id, headers = runner.build_real_runner(1)
    recorder = _ApiEvidenceRecorder(client, session_id, headers)
    recorder.install()
    result, decision_index = runner.reach_day_three(
        container, client, session_id, headers, 1
    )
    result, decision_index = runner.drain_decisions(
        container,
        client,
        session_id,
        headers,
        result,
        1,
        decision_index,
    )
    conversation = _start_and_talk(
        client,
        session_id,
        headers,
        state_version=result["state_version"],
        action_kind="household_visit",
        target_id="npc_wu_xiuying",
        topic="逐户合同与公开签约",
        player_text=(
            "我明确向你代表的每一户分别发起合同，请逐户签约，并按公开政策逐项核对。"
        ),
    )
    proposal = conversation["turn"].get("contract_batch_proposal")
    if not proposal:
        raise AssertionError("real household conversation did not create contract batch")
    confirmed = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/contract-batches/{proposal['batch_id']}/confirm",
            headers=headers,
            json={
                "state_version": conversation["turn"]["state_version"],
                "confirmed": True,
            },
        )
    )
    contract = next(
        item for item in confirmed["contracts"] if item["household_id"] == "WU-01"
    )
    terms = _expect(
        client.put(
            f"/api/game/session/{session_id}/governance/contracts/{contract['contract_id']}/terms",
            headers=headers,
            json={
                "state_version": confirmed["state_version"],
                "policy_document_id": "doc_compensation_policy_v1",
                "cash_amount": 50,
                "budget_envelope": "property_land",
                "housing_resource_id": "housing_d1_80",
                "service_allocations": {"grave_relocation_service": 1},
                "payment_day": 5,
                "move_out_day": 20,
                "housing_delivery_day": 20,
                "transition_months": 0,
                "public_window_reward": False,
                "approval_document_ids": [],
                "authorization_confirmed": False,
                "real_unit_viewed": False,
                "ledger_disclosed": False,
                "old_case_resolved": False,
                "prior_payment_verified": False,
            },
        )
    )
    if (terms["contract"]["audit_status"] != "not_required"
            or not terms["contract"]["contract_text"]
            or not terms["contract"].get("can_review")):
        raise AssertionError("saved proposal did not produce a reviewable contract preview")
    reviewed = _expect(
        client.post(
            f"/api/game/session/{session_id}/governance/contracts/{contract['contract_id']}/review",
            headers=headers,
            json={"state_version": terms["state_version"]},
        )
    )
    if reviewed["contract"]["status"] != "signed":
        raise AssertionError(
            "accepted review did not immediately sign the contract: "
            f"{reviewed['contract']['review_history']}"
        )
    result = _finish_action(
        client,
        session_id,
        headers,
        conversation["action_id"],
        reviewed["state_version"],
    )
    result = runner.end_day(
        client, session_id, headers, result, "feature-personal-end-d3"
    )
    for day in range(4, 46):
        result = _drain_group_conversations(
            client, session_id, headers, result,
            f"feature-personal-group-{day}",
            runner,
        )
        result, decision_index = runner.drain_decisions(
            container,
            client,
            session_id,
            headers,
            result,
            1,
            decision_index,
        )
        result = runner.end_day(
            client,
            session_id,
            headers,
            result,
            f"feature-personal-end-d{day}",
        )
    result = _drain_group_conversations(
        client, session_id, headers, result, "feature-personal-group-46", runner
    )
    result, decision_index = runner.drain_decisions(
        container,
        client,
        session_id,
        headers,
        result,
        1,
        decision_index,
    )
    map_document = _expect(
        client.get(f"/api/game/session/{session_id}/map", headers=headers)
    )
    map_records = []
    for location_id in (
        "loc_liulin_village",
        "loc_hongda_factory",
        "loc_county_hospital",
    ):
        location = next(
            item for item in map_document["locations"]
            if item["location_id"] == location_id
        )
        card = next(
            item for item in location["entry_cards"]
            if item["variant_id"] == "field_visit" and item["available"]
        )
        minimum = int(card["participant_rules"]["minimum"])
        selected_targets = list(card["preselected_npc_ids"])
        if len(selected_targets) < minimum:
            selected_targets = [
                item["target_id"] for item in card["target_choices"][:minimum]
            ]
        before = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        if before is None:
            raise AssertionError("map workflow session disappeared")
        started = _governance_action(
            client,
            session_id,
            headers,
            {
                "state_version": before.state_version,
                "action_kind": card["action_id"],
                "variant_id": card["variant_id"],
                "location_id": card["preselected_location_id"],
                "map_entry_id": card["map_entry_id"],
                "target_ids": selected_targets,
                "topic": f"在{location['name']}核实公开事项和办理进度",
            },
        )
        if started["action"]["location_id"] != location_id:
            raise AssertionError("map action did not preserve its locked location")
        if started["visible_state"]["ledger"]["action_points"]["remaining"] != before.game_state.action_points:
            raise AssertionError("map action charged AP before the first successful turn")
        cancelled = _expect(
            client.post(
                f"/api/game/session/{session_id}/governance/actions/"
                f"{started['action']['action_instance_id']}/cancel",
                headers=headers,
                json={"state_version": started["state_version"]},
            )
        )
        map_records.append({
            "location_id": location_id,
            "location_name": location["name"],
            "map_entry_id": card["map_entry_id"],
            "location_locked": card["location_locked"],
            "cancelled_without_cost": (
                cancelled["visible_state"]["ledger"]["action_points"]["remaining"]
                == before.game_state.action_points
            ),
        })
    stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if stored is None:
        raise AssertionError("personal workflow session disappeared")
    audit = _audit_summary(container, session_id)
    recovered_retries = len(runner.operation_retries_by_session.get(session_id, ()))
    if (
        audit["fake_calls"]
        or any(
            item.get("state_restored") is not True
            for item in runner.operation_retries_by_session.get(session_id, ())
        )
    ):
        raise AssertionError(f"real personal workflow audit failed: {audit}")
    package = container.packages.get("pkg_gameplay_v3")
    if package is None:
        raise AssertionError("v3 package disappeared during personal workflow")
    coverage = collect_session_coverage(
        stored,
        package,
        map_location_ids={item["location_id"] for item in map_records},
        api_traces=recorder.records,
    )
    payload = {
        "account": "personal",
        "session_id": session_id,
        "story_day": stored.game_state.story_day,
        "contract_batch_households": len(confirmed["contracts"]),
        "signed_contract_id": contract["contract_id"],
        "signed_households": stored.game_state.signed_households,
        "contract_audit_status": terms["contract"]["audit_status"],
        "contract_review_status": reviewed["contract"]["status"],
        "map_locations": map_records,
        "recovered_operation_retries": recovered_retries,
        "audit": audit,
        "coverage": coverage,
        "coverage_effect_hash": semantic_hash(_business_semantic_projection(stored)),
        "api_traces": recorder.records,
    }
    client.__exit__(None, None, None)
    return payload


def _complete_map_action(
    client: TestClient,
    *,
    runner: RealRouteRunner | None,
    session_id: str,
    headers: dict[str, str],
    started: dict,
    location_name: str,
    location_id: str,
) -> dict:
    """Complete one map action through its published player-facing workflow."""

    action = started["action"]
    if action["action_kind"] == "leadership_meeting":
        meeting = started["meeting"]
        meeting_id = meeting["meeting_id"]
        turned = _expect(client.post(
            f"/api/game/session/{session_id}/governance/meetings/{meeting_id}/turn",
            headers=headers,
            json={
                "state_version": started["state_version"],
                "player_text": f"请逐项核实{location_name}公开事项、风险和办理进度。",
                "client_action_id": f"feature-map-{location_id}",
            },
        ))
        participants = list(meeting["participant_ids"])
        resolved = _expect(client.post(
            f"/api/game/session/{session_id}/governance/meetings/{meeting_id}/resolve",
            headers=headers,
            json={
                "state_version": turned["state_version"],
                "adopt": False,
                "resolution": {
                    "decision": f"完成{location_name}事项核实，本次不形成执行决议",
                    "target_scope": location_name,
                    "resources": {},
                    "resource_mode": "authorization_ceiling",
                    "responsible_ids": participants[:1],
                    "deadline_day": started["visible_state"]["story"]["day"],
                    "public_scope": [location_name],
                    "document_title": f"{location_name}事项核实会议纪要",
                },
            },
        ))
        if resolved["meeting"]["status"] not in {"resolved", "rejected"}:
            raise AssertionError(f"map meeting did not settle at {location_id}")
        return resolved

    if runner is None:
        raise AssertionError("ordinary map actions require a real route runner")
    action_id = action["action_instance_id"]
    turned = _expect(runner.governance_turn_for_route(
        client,
        session_id,
        headers,
        action_id,
        started,
        player_text=f"请核实{location_name}当前公开事项并形成正式记录。",
        client_action_id=f"feature-map-{location_id}",
    ))
    return _finish_action(
        client, session_id, headers, action_id, turned["state_version"]
    )


def _exercise_all_available_map_locations(
    client: TestClient,
    container,
    runner: RealRouteRunner,
    session_id: str,
    headers: dict[str, str],
    result: dict,
    covered: set[str],
) -> dict:
    document = _expect(client.get(f"/api/game/session/{session_id}/map", headers=headers))
    for location in document["locations"]:
        location_id = location["location_id"]
        if location_id in covered:
            continue
        card = next(
            (item for item in location["entry_cards"] if item.get("available")),
            None,
        )
        if card is None:
            continue
        minimum = int(card["participant_rules"]["minimum"])
        selected = list(card.get("preselected_npc_ids", ()))
        if len(selected) < minimum:
            selected = [
                item["target_id"] for item in card.get("target_choices", ())[:minimum]
            ]
        before = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        if before is None:
            raise AssertionError("map inventory session disappeared")
        started = _governance_action(
            client,
            session_id,
            headers,
            {
                "state_version": result["state_version"],
                "action_kind": card["action_id"],
                "variant_id": card["variant_id"],
                "location_id": card["preselected_location_id"],
                "map_entry_id": card["map_entry_id"],
                "target_ids": selected,
                "topic": f"在{location['name']}核实公开事项和办理进度",
            },
        )
        if started["action"]["location_id"] != location_id:
            raise AssertionError(f"map location lock failed for {location_id}")
        finished = _complete_map_action(
            client,
            runner=runner,
            session_id=session_id,
            headers=headers,
            started=started,
            location_name=location["name"],
            location_id=location_id,
        )
        if finished["state_version"] <= started["state_version"]:
            raise AssertionError(f"map action did not complete at {location_id}")
        result = finished
        covered.add(location_id)
        # One completed field action per day keeps the authoritative AP budget legal.
        break
    return result


def _published_inventory_workflow(runner: RealRouteRunner) -> dict:
    """Exercise every currently compatible published inventory in one legal route."""

    container, client, session_id, headers = runner.build_real_runner(2)
    recorder = _ApiEvidenceRecorder(client, session_id, headers)
    recorder.install()
    package = container.packages.get("pkg_gameplay_v3")
    if package is None:
        raise AssertionError("v3 package disappeared during inventory workflow")
    profiles = load_witnesses(PROFILE_PATH)
    profile = _with_recovery_decision_policy(profiles[0])
    contract_terms = load_contract_terms(PROFILE_PATH)
    _expect(client.get(
        f"/api/game/session/{session_id}/knowledge", headers=headers
    ))
    result, serial = runner.reach_day_three_with_profile(
        container, client, session_id, headers, profile
    )
    all_opportunities = {
        item.opportunity_id for item in package.interaction_opportunities
    }
    all_demands = frozenset(item.demand_id for item in package.npc_demands)
    processed_representatives: set[str] = set()
    map_location_ids: set[str] = set()
    for story_day in range(3, 91):
        if result["visible_state"]["status"] == "ended":
            break
        _expect(client.get(
            f"/api/game/session/{session_id}/knowledge", headers=headers
        ))
        exclusive_by_source: dict[str, list[str]] = {}
        for fact_id, fact in package.facts.items():
            if fact_id == "fact_wu_independent_voice":
                continue
            methods = tuple(fact.acquisition_methods)
            if {str(method["route_type"]) for method in methods} != {"conversation"}:
                continue
            method = methods[0]
            if int(method["unlock_day"]) <= story_day:
                exclusive_by_source.setdefault(str(method["source_id"]), []).append(fact_id)
        known = set(_expect(client.get(
            f"/api/game/session/{session_id}/knowledge", headers=headers
        ))["known_fact_ids"])
        if story_day >= 22 and "fact_water_sample" not in known:
            quote = _expect(client.post(
                f"/api/game/session/{session_id}/actions/quote",
                headers=headers,
                json={
                    "state_version": result["state_version"],
                    "action_id": "third_party_water_test",
                    "target_ids": [],
                    "parameters": {
                        "sampling_protocol": "第三方见证并编号封存",
                    },
                },
            ))
            result = runner.action(client, session_id, headers, {
                "input_mode": "resource_action",
                "client_action_id": f"feature-water-sample-{serial:04d}",
                "state_version": quote["state_version"],
                "action_id": "third_party_water_test",
                "target_ids": [],
                "parameters": {
                    "sampling_protocol": "第三方见证并编号封存",
                },
                "quote_id": quote["quote_id"],
            })
            serial += 1
            known.add("fact_water_sample")
        available = {
            item["opportunity_id"]: item
            for item in _expect(client.get(
                f"/api/game/session/{session_id}/opportunities", headers=headers
            ))["opportunities"]
        }
        for opportunity_id, fact_ids in exclusive_by_source.items():
            missing = [fact_id for fact_id in fact_ids if fact_id not in known]
            opportunity = available.get(opportunity_id)
            if not missing or opportunity is None:
                continue
            started = runner.action(client, session_id, headers, {
                "input_mode": "conversation_start",
                "client_action_id": f"feature-exclusive-{serial:04d}-start",
                "state_version": result["state_version"],
                "opportunity_id": opportunity_id,
                "target_npc_id": opportunity["npc_id"],
            })
            serial += 1
            result = started
            conversation_id = started["conversation"]["conversation_id"]
            for fact_id in missing:
                fact = package.facts[fact_id]
                for attempt in range(1, 4):
                    if result["conversation"]["status"] != "active":
                        break
                    before_known = set(_expect(client.get(
                        f"/api/game/session/{session_id}/knowledge", headers=headers
                    ))["known_fact_ids"])
                    result = runner.action(client, session_id, headers, {
                        "input_mode": "free_text",
                        "client_action_id": (
                            f"feature-exclusive-{serial:04d}-{attempt}"
                        ),
                        "state_version": result["state_version"],
                        "conversation_id": conversation_id,
                        "opportunity_id": opportunity_id,
                        "target_npc_id": opportunity["npc_id"],
                        "player_text": (
                            "我们换到保密安全地点谈；材料匿名登记，保护你和家人；"
                            "优盘复制留痕并按正式交接清单封存，请把优盘交给我。"
                            if fact_id == "fact_shi_usb" else
                            f"请只围绕“{fact.title}”给出你亲自掌握的具体事实、"
                            "时间、地点和可核验细节；在说清前先不要结束谈话。"
                        ),
                    })
                    serial += 1
                    after_known = set(_expect(client.get(
                        f"/api/game/session/{session_id}/knowledge", headers=headers
                    ))["known_fact_ids"])
                    if fact_id in after_known - before_known:
                        known.update(after_known)
                        break
                if fact_id not in known:
                    raise AssertionError(
                        "conversation-only fact did not make a formal known-fact "
                        f"transition: {fact_id}:{opportunity_id}"
                    )
            if result["conversation"]["status"] == "active":
                result = runner.action(client, session_id, headers, {
                    "input_mode": "conversation_end",
                    "client_action_id": f"feature-exclusive-{serial:04d}-end",
                    "state_version": result["state_version"],
                    "conversation_id": conversation_id,
                })
                serial += 1
        result = _drain_group_conversations(
            client,
            session_id,
            headers,
            result,
            f"feature-inventory-d{story_day:02d}",
            runner,
        )
        result, serial = runner.drain_profile_decisions(
            container, client, session_id, headers, result, profile, serial
        )
        result, serial = runner.drain_optional_opportunities(
            container,
            client,
            session_id,
            headers,
            result,
            profile,
            serial,
            all_opportunities,
        )
        while True:
            overview = _expect(
                client.get(
                    f"/api/game/session/{session_id}/governance",
                    headers=headers,
                )
            )
            candidates = [
                item for item in overview["npc_demands"]
                if item["demand_id"] in all_demands
                and set(item.get("allowed_transitions", ()))
                & {"acknowledged", "lawfully_refused"}
            ]
            if not candidates:
                break
            demand = candidates[0]
            allowed = set(demand["allowed_transitions"])
            transition = (
                "lawfully_refused"
                if "lawfully_refused" in allowed else "acknowledged"
            )
            disposed = _expect(
                client.post(
                    f"/api/game/session/{session_id}/governance/npc-demands/"
                    f"{demand['demand_id']}/dispose",
                    headers=headers,
                    json={
                        "state_version": result["state_version"],
                        "transition": transition,
                    },
                )
            )
            result = {**result, "state_version": disposed["state_version"]}
        result = runner.inspect_all_available_archives(
            client, session_id, headers, result
        )
        result = runner.sign_contracts_toward_target(
            client,
            session_id,
            headers,
            result,
            target_signed=36,
            contract_terms=contract_terms,
            processed_representatives=processed_representatives,
        )
        if story_day >= 46:
            result = _exercise_all_available_map_locations(
                client,
                container,
                runner,
                session_id,
                headers,
                result,
                map_location_ids,
            )
        result = runner.end_day(
            client,
            session_id,
            headers,
            result,
            f"feature-inventory-end-d{story_day:02d}",
        )
    stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if stored is None:
        raise AssertionError("inventory workflow session disappeared")
    conversation_only_fact_ids = {
        fact_id for fact_id, fact in package.facts.items()
        if {str(method["route_type"]) for method in fact.acquisition_methods}
        == {"conversation"}
    }
    learned_conversation_fact_ids = {
        binding.split(":", 2)[0]
        for trace in recorder.records
        for binding in _fact_acquisition_bindings(trace.get("response"))
        if ":conversation:" in binding
    }
    missing_conversation_transitions = (
        conversation_only_fact_ids - learned_conversation_fact_ids
    )
    if missing_conversation_transitions:
        raise AssertionError(
            "conversation-only facts lack formal known-fact transitions: "
            f"{sorted(missing_conversation_transitions)}"
        )
    review = _expect(client.get(f"/api/game/session/{session_id}/review", headers=headers))
    audit = _audit_summary(container, session_id)
    coverage = collect_session_coverage(
        stored, package, map_location_ids=map_location_ids,
        api_traces=recorder.records,
    )
    payload = {
        "account": "server_default",
        "session_id": session_id,
        "story_day": stored.game_state.story_day,
        "review_available": bool(review),
        "audit": audit,
        "coverage": coverage,
        "coverage_effect_hash": semantic_hash(_business_semantic_projection(stored)),
        "api_traces": recorder.records,
    }
    client.__exit__(None, None, None)
    return payload


def _recovery_opportunity_workflow(runner: RealRouteRunner) -> dict:
    """Reach both mistake-recovery conversations through legal player choices."""

    container, client, session_id, headers = runner.build_real_runner(4)
    recorder = _ApiEvidenceRecorder(client, session_id, headers)
    recorder.install()
    package = container.packages.get("pkg_gameplay_v3")
    if package is None:
        raise AssertionError("v3 package disappeared during recovery workflow")
    base_profile = load_witnesses(PROFILE_PATH)[0]
    profile = _with_recovery_decision_policy(replace(
        base_profile,
        route_id="feature-recovery-opportunities",
        decision_policy={
            **base_profile.decision_policy,
            "dp3_06": "c",
            "dp4_06": "d",
            "dp5_04": "d",
        },
    ))
    result, serial = runner.reach_day_three_with_profile(
        container, client, session_id, headers, profile
    )
    recovery_ids = {
        "opp_d53_tan_laoliu_paid_recovery",
        "opp_d69_zhou_mancang_restart",
    }
    recovery_prerequisite_ids = {
        *recovery_ids,
        "opp_03_zhou_mancang_contact",
    }
    for story_day in range(3, 70):
        result = _drain_group_conversations(
            client,
            session_id,
            headers,
            result,
            f"feature-recovery-group-d{story_day:02d}",
            runner,
        )
        result, serial = runner.drain_profile_decisions(
            container, client, session_id, headers, result, profile, serial
        )
        result, serial = runner.drain_optional_opportunities(
            container,
            client,
            session_id,
            headers,
            result,
            profile,
            serial,
            recovery_prerequisite_ids,
        )
        result = runner.inspect_all_available_archives(
            client, session_id, headers, result
        )
        result = runner.end_day(
            client,
            session_id,
            headers,
            result,
            f"feature-recovery-end-d{story_day:02d}",
        )
    stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if stored is None:
        raise AssertionError("recovery workflow session disappeared")
    completed = {
        item.opportunity_id
        for item in stored.completed_conversations
        if item.completion_status == "completed"
    }
    missing = recovery_ids - completed
    if missing:
        raise AssertionError(
            f"legal recovery workflow did not complete: {sorted(missing)}"
        )
    audit = _audit_summary(container, session_id)
    if (
        audit["fake_calls"]
        or any(
            item.get("state_restored") is not True
            for item in runner.operation_retries_by_session.get(session_id, ())
        )
    ):
        raise AssertionError(f"real recovery workflow audit failed: {audit}")
    coverage = collect_session_coverage(
        stored, package, api_traces=recorder.records
    )
    payload = {
        "account": "server_default",
        "session_id": session_id,
        "story_day": stored.game_state.story_day,
        "completed_recovery_opportunity_ids": sorted(recovery_ids),
        "audit": audit,
        "coverage": coverage,
        "coverage_effect_hash": semantic_hash(_business_semantic_projection(stored)),
        "api_traces": recorder.records,
    }
    client.__exit__(None, None, None)
    return payload


def _dual_route_conversation_workflow(runner: RealRouteRunner) -> dict:
    """Acquire dual-route facts by conversation before any archive read."""

    container, client, session_id, headers = runner.build_real_runner(5)
    recorder = _ApiEvidenceRecorder(client, session_id, headers)
    recorder.install()
    package = container.packages.get("pkg_gameplay_v3")
    if package is None:
        raise AssertionError("v3 package disappeared during dual-route workflow")
    base_profile = load_witnesses(PROFILE_PATH)[0]
    profile = replace(base_profile, route_id="feature-dual-conversation-first")
    session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if session is None or session.pending_decision is None:
        raise AssertionError("dual-route workflow lacks initial decision")
    pending = session.pending_decision
    result = {
        "state_version": session.state_version,
        "visible_state": {"pending_decision": {
            "decision_id": pending.decision_id,
            "input_kind": pending.input_kind,
            "input_schema": pending.input_schema,
            "options": [
                {"option_id": item.option_id, "available": item.available}
                for item in pending.options
            ],
        }},
    }
    result, serial = runner.drain_profile_decisions(
        container, client, session_id, headers, result, profile, 0
    )
    result = runner.end_day(
        client, session_id, headers, result, "feature-dual-end-d01"
    )
    result, serial = runner.drain_profile_decisions(
        container, client, session_id, headers, result, profile, serial
    )
    result = _acquire_targeted_conversation_facts(
        client, session_id, headers, result,
        opportunity_id="opp_d02_wu_xiuying_first_talk",
        npc_id="npc_wu_xiuying",
        prompts=((
            "fact_clan_power_map",
            "请把柳林村各户真正担心的事和宗族关系告诉我。",
        ),),
        key="feature-dual-wu",
    )
    result = runner.end_day(
        client, session_id, headers, result, "feature-dual-end-d02"
    )
    targets = {
        16: (
            "opp_16_zhao_jianguo_contact", "npc_zhao_jianguo", (
                ("fact_connected_invoices", "请按发票号码逐笔核对经手人，并说明资金流向。"),
                ("fact_two_million_fee", "请核对两百万协调费的原始凭证，并说明真实去处。"),
            ),
        ),
        20: (
            "opp_20_liu_san_contact", "npc_liu_san", (
                ("fact_original_vouchers", "请拿出原始凭证逐笔核对，我会保留核查底稿。"),
            ),
        ),
        22: (
            "opp_22_shi_wenbin_contact", "npc_shi_wenbin", (
                ("fact_identical_reports", "请比较三年报告的重复数值，并说明改写经过。"),
                ("fact_eia_original", "请核对监测点位、采样时段和公示版本之间的差异。"),
                ("fact_lead_census", "我会保护受检者隐私，请核对普查人数和原始总表。"),
            ),
        ),
    }
    for story_day in range(3, 23):
        result = _drain_group_conversations(
            client, session_id, headers, result,
            f"feature-dual-group-d{story_day:02d}", runner,
        )
        result, serial = runner.drain_profile_decisions(
            container, client, session_id, headers, result, profile, serial
        )
        if story_day in targets:
            opportunity_id, npc_id, prompts = targets[story_day]
            result = _acquire_targeted_conversation_facts(
                client, session_id, headers, result,
                opportunity_id=opportunity_id,
                npc_id=npc_id,
                prompts=prompts,
                key=f"feature-dual-d{story_day:02d}",
            )
        if story_day < 22:
            result = runner.end_day(
                client, session_id, headers, result,
                f"feature-dual-end-d{story_day:02d}",
            )
    stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
    if stored is None:
        raise AssertionError("dual-route workflow session disappeared")
    if any(item.read_at_days for item in stored.archive_records.values()):
        raise AssertionError("dual-route conversation-first workflow read an archive")
    coverage = collect_session_coverage(
        stored, package, api_traces=recorder.records
    )
    expected = {
        f"{fact_id}:conversation:{opportunity_id}"
        for opportunity_id, _npc_id, prompts in targets.values()
        for fact_id, _player_text in prompts
    }
    missing = expected - set(coverage["fact_acquisition_path_ids"])
    if missing:
        raise AssertionError(
            f"dual-route conversation-first evidence missing: {sorted(missing)}"
        )
    audit = _audit_summary(container, session_id)
    if audit["fake_calls"]:
        raise AssertionError(f"real dual-route workflow audit failed: {audit}")
    payload = {
        "account": "server_default",
        "session_id": session_id,
        "story_day": stored.game_state.story_day,
        "conversation_first_fact_ids": sorted(
            fact_id for _opportunity_id, _npc_id, prompts in targets.values()
            for fact_id, _player_text in prompts
        ),
        "audit": audit,
        "coverage": coverage,
        "coverage_effect_hash": semantic_hash(_business_semantic_projection(stored)),
        "api_traces": recorder.records,
    }
    client.__exit__(None, None, None)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repository = BACKEND_ROOT.parents[1]
    # Both gates deliberately run before settings validation, output creation, or
    # any TestClient/real-model call.  A failed run therefore cannot be confused
    # with partial feature evidence.
    provenance = capture_run_provenance(repository)
    assert_required_api_evidence_capabilities()
    settings = Settings.from_env()
    if settings.role_llm_provider != "openai_compatible":
        raise SystemExit("real feature workflow requires openai_compatible")
    if not os.getenv(settings.role_llm_api_key_env, "").strip():
        raise SystemExit("configured real API key is missing")
    root = args.output_dir / f"workflows-{int(time.time())}"
    root.mkdir(parents=True, exist_ok=False)
    runner = RealRouteRunner(settings, root, stop_day=3)
    started = time.perf_counter()
    workflows = [
        _server_default_workflow(runner, root),
        _personal_contract_workflow(runner, root),
        _published_inventory_workflow(runner),
        _recovery_opportunity_workflow(runner),
        _dual_route_conversation_workflow(runner),
    ]
    _attach_authority_projections(workflows)
    coverage_fields = (
        "archive_ids",
        "fact_acquisition_path_ids",
        "opportunity_ids",
        "npc_ids",
        "map_location_ids",
        "household_ids",
        "governance_action_families",
    )
    gateway_records = [
        {**record, "mode": item["account"]}
        for item in workflows
        for record in item["audit"]["records"]
    ]
    gateway_mode_sequence = [item["mode"] for item in gateway_records]
    gateway_mode_transitions = sum(
        current != previous
        for previous, current in zip(
            gateway_mode_sequence, gateway_mode_sequence[1:]
        )
    )
    operation_records = _coverage_operation_records(workflows)
    published_workflows = [
        {key: value for key, value in item.items() if key != "api_traces"}
        for item in workflows
    ]
    report = {
        "provider": "openai_compatible",
        "model": settings.role_llm_model,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "fake_calls": sum(item["audit"]["fake_calls"] for item in workflows),
        "template_fallback_count": sum(
            item["audit"]["template_fallback_count"] for item in workflows
        ),
        "silent_fallback_count": sum(
            item["audit"]["silent_fallback_count"] for item in workflows
        ),
        "partial_commit_count": sum(
            record.get("state_restored") is not True
            for records in runner.operation_retries_by_session.values()
            for record in records
        ) + sum(
            trace.get("partial_commit") is True
            for item in workflows
            for trace in item.get("api_traces", ())
        ),
        "provenance": provenance,
        "gateway_audit": {
            "interleaved": gateway_mode_transitions >= 2,
            "records": gateway_records,
        },
        "save_load_record": next(
            item["save_load_record"]
            for item in workflows
            if item.get("save_load_record")
        ),
        "meeting_document_record": next(
            item["meeting_document_record"]
            for item in workflows
            if item.get("meeting_document_record")
        ),
        "operation_records": operation_records,
        "server_default_accounts": sum(
            item["account"] == "server_default" for item in workflows
        ),
        "personal_api_accounts": sum(
            item["account"] == "personal" for item in workflows
        ),
        "account_gateway_isolation": (
            len({item["session_id"] for item in workflows}) == len(workflows)
            and {item["account"] for item in workflows}
            == {"server_default", "personal"}
        ),
        **{
            field: sorted({
                value
                for item in workflows
                for value in item["coverage"].get(field, ())
            })
            for field in coverage_fields
        },
        "meeting_completed": any(item.get("meeting_npc_order") for item in workflows),
        "contract_completed": any(item.get("signed_contract_id") for item in workflows),
        "document_completed": any(item.get("document_status") == "issued" for item in workflows),
        "save_load_completed": any(
            item.get("manual_save_load_semantic_equal") is True for item in workflows
        ),
        "review_completed": any(
            item.get("contract_review_status") == "signed"
            or item.get("review_available") is True
            for item in workflows
        ),
        "contract_review_statuses": sorted({
            str(item["contract_review_status"])
            for item in workflows
            if item.get("contract_review_status")
        }),
        "workflows": published_workflows,
    }
    validate_feature_workflow_report(report)
    (root / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
