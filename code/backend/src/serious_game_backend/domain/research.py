from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def research_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ResearchSubject:
    research_subject_id: str
    account_id: str
    created_at: str = field(default_factory=research_now_iso)
    retired_at: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentAssignment:
    assignment_id: str
    research_subject_id: str
    experiment_id: str
    experiment_group_id: str
    environment: str
    package_content_hash: str
    model_id: str
    prompt_version: str
    assigned_at: str = field(default_factory=research_now_iso)


@dataclass(frozen=True, slots=True)
class ResearchEvent:
    research_event_id: str
    research_subject_id: str
    experiment_id: str | None
    experiment_group_id: str | None
    session_public_id: str
    event_type: str
    story_day: int
    structured_payload: dict
    raw_text_ciphertext: str | None = None
    consent_record_id: str | None = None
    created_at: str = field(default_factory=research_now_iso)
