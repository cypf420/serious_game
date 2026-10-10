from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import secrets

from serious_game_backend.application.ports import GovernanceRepository
from serious_game_backend.domain.errors import PermissionDeniedError
from serious_game_backend.domain.governance import (
    DataSubjectRequest,
    ExportJob,
    PrivilegedAccessAudit,
    RetentionResult,
    governance_now_iso,
)
from serious_game_backend.domain.identity import (
    PERMISSION_RESEARCH_APPROVE,
    PERMISSION_RESEARCH_EXPORT,
    PERMISSION_RESEARCH_READ,
    Principal,
)


EXPORT_FIELDS = frozenset({
    "research_subject_id", "experiment_id", "experiment_group_id", "event_type",
    "story_day", "created_at", "structured_payload",
})
EXPORT_CONDITIONS = frozenset({"experiment_id", "experiment_group_id", "event_type"})


class GovernanceService:
    """M4 governance boundary: two-person export, subject rights, retention and audit."""

    def __init__(self, repository: GovernanceRepository, *, audit_salt: str) -> None:
        if not audit_salt:
            raise ValueError("audit salt is required")
        self._repository = repository
        self._audit_salt = audit_salt

    def request_export(
        self, principal: Principal, *, purpose: str, fields: tuple[str, ...],
        conditions: dict, minimum_cell_size: int = 5,
    ) -> ExportJob:
        self._require(principal, PERMISSION_RESEARCH_EXPORT)
        unknown = set(fields) - EXPORT_FIELDS
        if unknown or not fields:
            raise ValueError(f"invalid export fields: {sorted(unknown)}")
        if minimum_cell_size < 5:
            raise ValueError("minimum_cell_size must be at least 5")
        unknown_conditions = set(conditions) - EXPORT_CONDITIONS
        if unknown_conditions:
            raise ValueError(f"invalid export conditions: {sorted(unknown_conditions)}")
        job = ExportJob(
            export_job_id=f"exp_{secrets.token_hex(16)}",
            requested_by=principal.account_id,
            purpose=purpose.strip(), field_whitelist=tuple(dict.fromkeys(fields)),
            query_conditions=dict(conditions), minimum_cell_size=minimum_cell_size,
        )
        if not job.purpose:
            raise ValueError("export purpose is required")
        self._repository.create_export(job)
        self._audit(principal, PERMISSION_RESEARCH_EXPORT, purpose, "export", job.export_job_id, "requested")
        return job

    def approve_export(self, principal: Principal, export_job_id: str, *, purpose: str) -> ExportJob:
        self._require(principal, PERMISSION_RESEARCH_APPROVE)
        job = self._required_export(export_job_id)
        if job.requested_by == principal.account_id:
            raise PermissionDeniedError("导出申请人与审批人必须是不同账号")
        if job.status != "pending_approval":
            raise ValueError("export is not pending approval")
        approved = replace(job, status="approved", approved_by=principal.account_id, updated_at=governance_now_iso())
        self._repository.save_export(approved)
        self._audit(principal, PERMISSION_RESEARCH_APPROVE, purpose, "export", export_job_id, "approved")
        return approved

    def materialize_export(self, principal: Principal, export_job_id: str, *, purpose: str) -> dict:
        self._require(principal, PERMISSION_RESEARCH_READ)
        job = self._required_export(export_job_id)
        if job.status not in {"approved", "completed"}:
            raise PermissionDeniedError("导出尚未通过双人审批")
        rows = self._repository.research_export_rows(job.query_conditions)
        groups: dict[tuple, int] = {}
        for row in rows:
            key = (row.get("experiment_id"), row.get("experiment_group_id"), row.get("event_type"))
            groups[key] = groups.get(key, 0) + 1
        safe = [row for row in rows if groups[(row.get("experiment_id"), row.get("experiment_group_id"), row.get("event_type"))] >= job.minimum_cell_size]
        projected = [{field: row.get(field) for field in job.field_whitelist} for row in safe]
        encoded = json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
        version = "dataset:" + hashlib.sha256((job.export_job_id + digest).encode()).hexdigest()[:16]
        completed = replace(job, status="completed", dataset_version=version, file_hash=digest, updated_at=governance_now_iso())
        self._repository.save_export(completed)
        self._audit(principal, PERMISSION_RESEARCH_READ, purpose, "export", export_job_id, "downloaded")
        return {"job": asdict(completed), "row_count": len(projected), "rows": projected}

    def request_subject_action(self, account_id: str, request_type: str, reason: str | None = None) -> DataSubjectRequest:
        if request_type not in {"access", "erase"}:
            raise ValueError("request_type must be access or erase")
        request = DataSubjectRequest(
            request_id=f"dsr_{secrets.token_hex(16)}", account_id=account_id,
            request_type=request_type, reason=reason,
        )
        self._repository.create_subject_request(request)
        return request

    def process_subject_action(self, principal: Principal, request_id: str, *, purpose: str) -> DataSubjectRequest:
        self._require(principal, PERMISSION_RESEARCH_APPROVE)
        request = self._repository.get_subject_request(request_id)
        if request is None or request.status != "pending":
            raise ValueError("subject request not found or already processed")
        result = (self._repository.subject_data(request.account_id)
                  if request.request_type == "access"
                  else self._repository.erase_subject(request.account_id))
        now = governance_now_iso()
        completed = replace(request, status="completed", result=result, updated_at=now, completed_at=now)
        self._repository.save_subject_request(completed)
        self._audit(principal, PERMISSION_RESEARCH_APPROVE, purpose, "data_subject_request", request_id, "completed")
        return completed

    def apply_retention(self, principal: Principal, *, cutoff_at: str, policy_version: str, purpose: str) -> RetentionResult:
        self._require(principal, PERMISSION_RESEARCH_APPROVE)
        result = self._repository.apply_retention(cutoff_at=cutoff_at, policy_version=policy_version)
        self._audit(principal, PERMISSION_RESEARCH_APPROVE, purpose, "retention", policy_version, "completed")
        return result

    def _required_export(self, export_job_id: str) -> ExportJob:
        job = self._repository.get_export(export_job_id)
        if job is None:
            raise ValueError("export not found")
        return job

    @staticmethod
    def _require(principal: Principal, permission: str) -> None:
        if not principal.can(permission):
            raise PermissionDeniedError("当前账号没有执行该治理操作的权限")

    def _audit(self, principal: Principal, permission: str, purpose: str, target_type: str, target_id: str, outcome: str) -> None:
        target_hash = "sha256:" + hashlib.sha256((self._audit_salt + target_id).encode()).hexdigest()
        self._repository.append_privileged_audit(PrivilegedAccessAudit(
            audit_id=f"pa_{secrets.token_hex(16)}", actor_account_id=principal.account_id,
            permission=permission, purpose=purpose, target_type=target_type,
            target_id_hash=target_hash, outcome=outcome,
        ))
