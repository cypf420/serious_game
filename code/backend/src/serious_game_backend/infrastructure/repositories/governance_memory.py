from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from serious_game_backend.domain.governance import (
    DataSubjectRequest, ExportJob, PrivilegedAccessAudit, RetentionResult,
)
from serious_game_backend.domain.research import ResearchEvent


class InMemoryGovernanceRepository:
    def __init__(self, research_events=None) -> None:
        self.exports: dict[str, ExportJob] = {}
        self.requests: dict[str, DataSubjectRequest] = {}
        self.audits: list[PrivilegedAccessAudit] = []
        self._research_events = research_events

    def create_export(self, job: ExportJob) -> None:
        if job.export_job_id in self.exports: raise ValueError("duplicate export")
        self.exports[job.export_job_id] = deepcopy(job)

    def get_export(self, export_job_id: str) -> ExportJob | None:
        return deepcopy(self.exports.get(export_job_id))

    def save_export(self, job: ExportJob) -> None:
        if job.export_job_id not in self.exports: raise ValueError("export not found")
        self.exports[job.export_job_id] = deepcopy(job)

    def research_export_rows(self, conditions: dict) -> tuple[dict, ...]:
        values = tuple(getattr(self._research_events, "_items", ()))
        rows = []
        for item in values:
            row = {
                "research_subject_id": item.research_subject_id,
                "experiment_id": item.experiment_id,
                "experiment_group_id": item.experiment_group_id,
                "event_type": item.event_type, "story_day": item.story_day,
                "created_at": item.created_at,
                "structured_payload": deepcopy(item.structured_payload),
            }
            if all(row.get(key) == value for key, value in conditions.items() if value is not None):
                rows.append(row)
        return tuple(rows)

    def create_subject_request(self, request: DataSubjectRequest) -> None:
        self.requests[request.request_id] = deepcopy(request)

    def get_subject_request(self, request_id: str) -> DataSubjectRequest | None:
        return deepcopy(self.requests.get(request_id))

    def save_subject_request(self, request: DataSubjectRequest) -> None:
        if request.request_id not in self.requests: raise ValueError("subject request not found")
        self.requests[request.request_id] = deepcopy(request)

    def subject_data(self, account_id: str) -> dict:
        return {"account_id": account_id, "portable_copy": True}

    def erase_subject(self, account_id: str) -> dict:
        removed = 0
        if self._research_events is not None:
            before = len(self._research_events._items)
            self._research_events._items = [item for item in self._research_events._items if item.research_subject_id != account_id]
            removed = before - len(self._research_events._items)
        return {"erased": True, "research_events_removed": removed}

    def append_privileged_audit(self, audit: PrivilegedAccessAudit) -> None:
        self.audits.append(deepcopy(audit))

    def apply_retention(self, *, cutoff_at: str, policy_version: str) -> RetentionResult:
        removed = 0
        if self._research_events is not None:
            rewritten: list[ResearchEvent] = []
            for item in self._research_events._items:
                if item.created_at < cutoff_at and item.raw_text_ciphertext:
                    item = replace(item, raw_text_ciphertext=None); removed += 1
                rewritten.append(item)
            self._research_events._items = rewritten
        return RetentionResult(policy_version, cutoff_at, removed, 0)
