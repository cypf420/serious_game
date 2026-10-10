from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from serious_game_backend.domain.events import PendingDecision, VisibleEvent
from serious_game_backend.domain.game_state import GameState
from serious_game_backend.domain.npc_state import NPCState
from serious_game_backend.domain.enums import SessionStatus
from serious_game_backend.domain.story import VisibleNarrativeEntry
from serious_game_backend.domain.conversation import (
    ActiveConversation,
    CompletedConversation,
    ForcedGroupConversation,
)
from serious_game_backend.domain.household_settlement import (
    D75SettlementSnapshot,
    HouseholdSettlementEntry,
)
from serious_game_backend.domain.gameplay_governance import (
    AdministrativeDocument,
    ArchiveRecord,
    ContractBatch,
    GovernanceActionRecord,
    HouseholdContract,
    MeetingRecord,
    ResourceReservation,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class GameSession:
    session_id: str
    account_id: str
    package_id: str
    package_version: str
    package_content_hash: str
    random_seed: str
    game_state: GameState
    origin_id: str
    timeline_id: str = ""
    loaded_from_snapshot_id: str | None = None
    environment: str = "sandbox"
    consent_record_id: str | None = None
    research_subject_id: str | None = None
    experiment_id: str | None = None
    experiment_group_id: str | None = None
    npc_states: dict[str, NPCState] = field(default_factory=dict)
    status: SessionStatus = SessionStatus.ACTIVE
    state_version: int = 1
    processing_action_id: str | None = None
    pending_decision: PendingDecision | None = None
    pending_decision_queue: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    state_values: dict[str, str] = field(
        default_factory=lambda: {"lead_roster_disposition": "未获取"}
    )
    triggered_events: set[str] = field(default_factory=set)
    visible_events: list[VisibleEvent] = field(default_factory=list)
    story_beat_id: str | None = None
    narrative_feed: list[VisibleNarrativeEntry] = field(default_factory=list)
    rendered_content_ids: set[str] = field(default_factory=set)
    next_feed_cursor: int = 1
    known_fact_ids: set[str] = field(default_factory=set)
    known_npc_ids: set[str] = field(default_factory=set)
    encountered_npc_ids: set[str] = field(default_factory=set)
    contactable_npc_ids: set[str] = field(default_factory=set)
    relationship_edges: list[dict] = field(default_factory=list)
    night_logs: list[dict] = field(default_factory=list)
    ending_result: dict | None = None
    decision_parameters: dict[str, dict] = field(default_factory=dict)
    npc_demand_states: dict[str, dict] = field(default_factory=dict)
    active_conversation: ActiveConversation | None = None
    completed_conversations: list[CompletedConversation] = field(default_factory=list)
    active_group_conversation: ForcedGroupConversation | None = None
    group_conversation_queue: list[ForcedGroupConversation] = field(
        default_factory=list
    )
    completed_group_conversations: list[dict] = field(default_factory=list)
    d75_settlement_snapshot: D75SettlementSnapshot | None = None
    household_settlement_entries: list[HouseholdSettlementEntry] = field(
        default_factory=list
    )
    governance_actions: dict[str, GovernanceActionRecord] = field(
        default_factory=dict
    )
    archive_records: dict[str, ArchiveRecord] = field(default_factory=dict)
    meetings: dict[str, MeetingRecord] = field(default_factory=dict)
    administrative_documents: dict[str, AdministrativeDocument] = field(
        default_factory=dict
    )
    contract_batches: dict[str, ContractBatch] = field(default_factory=dict)
    household_contracts: dict[str, HouseholdContract] = field(default_factory=dict)
    resource_reservations: list[ResourceReservation] = field(default_factory=list)
    resource_ledger_entries: list[dict] = field(default_factory=list)
    logs: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def touch(self) -> None:
        self.updated_at = now_iso()

    def append_narrative(
        self,
        *,
        story_day: int,
        kind: str,
        text: str,
        speaker: str | None = None,
        content_instance_id: str | None = None,
        block_id: str | None = None,
        beat_id: str | None = None,
        decision_id: str | None = None,
        scene_id: str | None = None,
        presentation_phase: str = "scene",
        read_gate: str = "advance",
    ) -> bool:
        if (
            content_instance_id is not None
            and content_instance_id in self.rendered_content_ids
        ):
            return False
        day_sequence = 1 + sum(
            1 for item in self.narrative_feed if item.story_day == story_day
        )
        self.narrative_feed.append(VisibleNarrativeEntry(
            cursor=self.next_feed_cursor,
            story_day=story_day,
            kind=kind,
            text=text,
            speaker=speaker,
            content_instance_id=content_instance_id,
            block_id=block_id,
            beat_id=beat_id,
            decision_id=decision_id,
            scene_id=scene_id,
            presentation_phase=presentation_phase,
            day_sequence=day_sequence,
            read_gate=read_gate,
        ))
        if content_instance_id is not None:
            self.rendered_content_ids.add(content_instance_id)
        self.next_feed_cursor += 1
        return True

    def audited_signed_households(self) -> int:
        """D75 后以冻结快照加逐笔收口事件重建真实签约数。"""
        if self.d75_settlement_snapshot is None:
            return self.game_state.signed_households
        return (
            self.d75_settlement_snapshot.first_batch_signed_count
            + sum(
                item.household_count
                for item in self.household_settlement_entries
                if item.validity_status == "valid"
                and item.entry_batch != "first_batch"
            )
        )

    def signing_batch_summary(self) -> dict[str, int | bool]:
        snapshot = self.d75_settlement_snapshot
        if snapshot is None:
            return {
                "roster_locked": False,
                "first_batch": self.game_state.signed_households,
                "acceptance_confirmed": 0,
                "unsigned": self.game_state.total_households
                - self.game_state.signed_households,
            }
        acceptance_confirmed = sum(
            item.household_count
            for item in self.household_settlement_entries
            if item.validity_status == "valid"
            and item.entry_batch != "first_batch"
        )
        signed = snapshot.first_batch_signed_count + acceptance_confirmed
        return {
            "roster_locked": True,
            "first_batch": snapshot.first_batch_signed_count,
            "acceptance_confirmed": acceptance_confirmed,
            "unsigned": self.game_state.total_households - signed,
        }
