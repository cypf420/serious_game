from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def governance_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ExportJob:
    export_job_id: str
    requested_by: str
    purpose: str
    field_whitelist: tuple[str, ...]
    query_conditions: dict
    minimum_cell_size: int
    status: str = "pending_approval"
    approved_by: str | None = None
    dataset_version: str | None = None
    file_hash: str | None = None
    created_at: str = field(default_factory=governance_now_iso)
    updated_at: str = field(default_factory=governance_now_iso)


@dataclass(frozen=True, slots=True)
class DataSubjectRequest:
    request_id: str
    account_id: str
    request_type: str
    status: str = "pending"
    reason: str | None = None
    result: dict | None = None
    created_at: str = field(default_factory=governance_now_iso)
    updated_at: str = field(default_factory=governance_now_iso)
    completed_at: str | None = None


@dataclass(frozen=True, slots=True)
class PrivilegedAccessAudit:
    audit_id: str
    actor_account_id: str
    permission: str
    purpose: str
    target_type: str
    target_id_hash: str
    outcome: str
    request_id: str | None = None
    created_at: str = field(default_factory=governance_now_iso)


@dataclass(frozen=True, slots=True)
class RetentionResult:
    policy_version: str
    cutoff_at: str
    raw_research_text_removed: int
    auth_sessions_removed: int

