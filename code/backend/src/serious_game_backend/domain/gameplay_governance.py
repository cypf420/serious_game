from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def governance_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


BASE_ACTION_PERMISSIONS = {
    "household_visit": ("1.1",),
    "cadre_interview": ("1.1", "1.3"),
    "leadership_meeting": ("1.1", "1.2", "1.3", "1.4"),
    "inspect_archives": ("1.3",),
}

VARIANT_HARD_OUTCOME_REFERENCES = {
    "household_visit": frozenset({
        ("follow_up", "governance_action_record"),
    }),
    "cadre_interview": frozenset({
        ("follow_up", "governance_action_record"),
    }),
    "leadership_meeting": frozenset({
        ("document", "meeting_record"),
    }),
    "inspect_archives": frozenset({
        ("document", "archive_read_record"),
    }),
}


@dataclass(slots=True)
class GovernanceActionRecord:
    action_instance_id: str
    action_kind: str
    story_day: int
    target_ids: tuple[str, ...]
    required_permissions: tuple[str, ...]
    variant_id: str | None = None
    location_id: str | None = None
    opportunity_id: str | None = None
    map_entry_id: str | None = None
    display_title: str | None = None
    cost_action_points: int = 0
    cost_status: str = "committed"
    cost_committed_at: str | None = None
    status: str = "active"
    topic: str = ""
    archive_ids: tuple[str, ...] = ()
    transcript: list[dict] = field(default_factory=list)
    result_ids: list[str] = field(default_factory=list)
    hard_outcomes: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=governance_now_iso)
    completed_at: str | None = None


@dataclass(slots=True)
class ArchiveRecord:
    archive_id: str
    category: str
    title: str
    content: str
    source_type: str
    source_id: str
    acquired_day: int
    acquired_via: str
    evidence_level: str = "E0"
    confidentiality: str = "internal"
    status: str = "available"
    read_at_days: list[int] = field(default_factory=list)
    related_npc_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=governance_now_iso)


@dataclass(slots=True)
class MeetingRecord:
    meeting_id: str
    action_instance_id: str
    story_day: int
    topic: str
    participant_ids: tuple[str, ...]
    decision_mode: str
    lead_npc_id: str
    proposed_document_type: str | None = None
    transcript: list[dict] = field(default_factory=list)
    positions: dict[str, dict] = field(default_factory=dict)
    resolution: dict | None = None
    status: str = "discussion"
    created_at: str = field(default_factory=governance_now_iso)
    resolved_at: str | None = None


@dataclass(slots=True)
class AdministrativeDocument:
    document_id: str
    document_type: str
    title: str
    status: str
    version: int
    content: str
    story_day: int
    policy_version: str
    source_meeting_id: str | None = None
    resolution_snapshot: dict = field(default_factory=dict)
    required_countersign_ids: tuple[str, ...] = ()
    countersigned_by: tuple[str, ...] = ()
    public_scope: tuple[str, ...] = ()
    publication_records: list[dict] = field(default_factory=list)
    content_hash: str | None = None
    issued_day: int | None = None
    archive_id: str | None = None
    review_status: str = "not_reviewed"
    review_summary: str = ""
    review_model_id: str | None = None
    reviewed_at: str | None = None
    review_history: list[dict] = field(default_factory=list)
    revision_history: list[dict] = field(default_factory=list)
    version_history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=governance_now_iso)
    updated_at: str = field(default_factory=governance_now_iso)


@dataclass(slots=True)
class ResourceReservation:
    reservation_id: str
    owner_type: str
    owner_id: str
    resource_id: str
    quantity: int
    status: str
    reserved_day: int
    expires_day: int | None = None
    committed_day: int | None = None
    delivered_day: int | None = None


@dataclass(slots=True)
class ContractBatch:
    batch_id: str
    representative_npc_id: str
    story_day: int
    household_ids: tuple[str, ...]
    status: str
    player_request: str
    intent_reason: str
    contract_ids: tuple[str, ...] = ()
    created_at: str = field(default_factory=governance_now_iso)
    confirmed_at: str | None = None


@dataclass(slots=True)
class ContractVersion:
    version: int
    text: str
    term_hash: str
    text_hash: str
    created_by: str
    warnings: tuple[str, ...] = ()
    audit_status: str = "pending"
    audit_result: dict = field(default_factory=dict)
    audit_model_id: str | None = None
    audited_at: str | None = None
    created_at: str = field(default_factory=governance_now_iso)


@dataclass(slots=True)
class HouseholdContract:
    contract_id: str
    batch_id: str
    household_id: str
    signatory_name: str
    signatory_npc_id: str | None
    created_day: int
    status: str = "awaiting_terms"
    term_sheet: dict | None = None
    versions: list[ContractVersion] = field(default_factory=list)
    current_version: int = 0
    review_decision: str | None = None
    review_reason: str = ""
    counteroffer: dict = field(default_factory=dict)
    review_history: list[dict] = field(default_factory=list)
    reserved_until_day: int | None = None
    signed_day: int | None = None
    signed_hash: str | None = None
    archive_id: str | None = None
    fulfillment: dict = field(default_factory=dict)
    created_at: str = field(default_factory=governance_now_iso)
    updated_at: str = field(default_factory=governance_now_iso)
