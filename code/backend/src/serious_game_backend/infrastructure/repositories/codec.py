from __future__ import annotations

from dataclasses import asdict
import json

from serious_game_backend.domain.enums import (
    AvailabilityMode,
    DecisionState,
    NPCStateTier,
    OperationStatus,
    SessionStatus,
)
from serious_game_backend.domain.events import (
    PendingDecision,
    VisibleDecisionOption,
    VisibleEvent,
)
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.conversation import (
    ActiveConversation,
    CompletedConversation,
    ForcedGroupConversation,
)
from serious_game_backend.domain.game_state import GameState
from serious_game_backend.domain.household_settlement import (
    D75SettlementSnapshot,
    HouseholdSettlementEntry,
)
from serious_game_backend.domain.gameplay_governance import (
    AdministrativeDocument,
    ArchiveRecord,
    ContractBatch,
    ContractVersion,
    GovernanceActionRecord,
    HouseholdContract,
    MeetingRecord,
    ResourceReservation,
)
from serious_game_backend.domain.npc_state import NPCState
from serious_game_backend.domain.operation import OperationRecord
from serious_game_backend.domain.story import VisibleNarrativeEntry


def dumps(value: dict) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def encode_session(session: GameSession) -> dict:
    pending = None
    if session.pending_decision is not None:
        pending = {
            "event_instance_id": session.pending_decision.event_instance_id,
            "decision_id": session.pending_decision.decision_id,
            "option_ids": list(session.pending_decision.option_ids),
            "state": session.pending_decision.state.value,
            "presented_state_version": (
                session.pending_decision.presented_state_version
            ),
            "visible_title": session.pending_decision.visible_title,
            "visible_text": session.pending_decision.visible_text,
            "scene_id": session.pending_decision.scene_id,
            "options": [asdict(item) for item in session.pending_decision.options],
            "input_kind": session.pending_decision.input_kind,
            "input_schema": session.pending_decision.input_schema,
            "context": session.pending_decision.context,
            "presentation_entry_id": (
                session.pending_decision.presentation_entry_id
            ),
        }
    return {
        "schema_version": 12,
        "session_id": session.session_id,
        "account_id": session.account_id,
        "package_id": session.package_id,
        "package_version": session.package_version,
        "package_content_hash": session.package_content_hash,
        "random_seed": session.random_seed,
        "origin_id": session.origin_id,
        "timeline_id": session.timeline_id,
        "loaded_from_snapshot_id": session.loaded_from_snapshot_id,
        "environment": session.environment,
        "consent_record_id": session.consent_record_id,
        "research_subject_id": session.research_subject_id,
        "experiment_id": session.experiment_id,
        "experiment_group_id": session.experiment_group_id,
        "game_state": asdict(session.game_state),
        "npc_states": {
            npc_id: {
                "npc_id": item.npc_id,
                "state_tier": item.state_tier.value,
                "availability_mode": item.availability_mode.value,
                "profile_id": item.profile_id,
                "trust_score": item.trust_score,
                "trust_locked": item.trust_locked,
                "trust_effects_applied": sorted(item.trust_effects_applied),
                "attitude_score": item.attitude_score,
                "anxiety_score": item.anxiety_score,
                "memory_id": item.memory_id,
                "chapter_disclosure_used": item.chapter_disclosure_used,
                "known_fact_ids": sorted(item.known_fact_ids),
                "owned_evidence_ids": sorted(item.owned_evidence_ids),
                "special_flags": sorted(item.special_flags),
            }
            for npc_id, item in session.npc_states.items()
        },
        "status": session.status.value,
        "state_version": session.state_version,
        "processing_action_id": session.processing_action_id,
        "pending_decision": pending,
        "pending_decision_queue": list(session.pending_decision_queue),
        "flags": sorted(session.flags),
        "state_values": session.state_values,
        "triggered_events": sorted(session.triggered_events),
        "visible_events": [asdict(item) for item in session.visible_events],
        "story_beat_id": session.story_beat_id,
        "narrative_feed": [asdict(item) for item in session.narrative_feed],
        "rendered_content_ids": sorted(session.rendered_content_ids),
        "next_feed_cursor": session.next_feed_cursor,
        "known_fact_ids": sorted(session.known_fact_ids),
        "known_npc_ids": sorted(session.known_npc_ids),
        "encountered_npc_ids": sorted(session.encountered_npc_ids),
        "contactable_npc_ids": sorted(session.contactable_npc_ids),
        "relationship_edges": session.relationship_edges,
        "night_logs": session.night_logs,
        "ending_result": session.ending_result,
        "decision_parameters": session.decision_parameters,
        "npc_demand_states": session.npc_demand_states,
        "active_conversation": (
            asdict(session.active_conversation)
            if session.active_conversation is not None else None
        ),
        "completed_conversations": [
            asdict(item) for item in session.completed_conversations
        ],
        "active_group_conversation": (
            asdict(session.active_group_conversation)
            if session.active_group_conversation is not None else None
        ),
        "group_conversation_queue": [
            asdict(item) for item in session.group_conversation_queue
        ],
        "completed_group_conversations": session.completed_group_conversations,
        "d75_settlement_snapshot": (
            asdict(session.d75_settlement_snapshot)
            if session.d75_settlement_snapshot is not None else None
        ),
        "household_settlement_entries": [
            asdict(item) for item in session.household_settlement_entries
        ],
        "governance_actions": {
            key: asdict(item) for key, item in session.governance_actions.items()
        },
        "archive_records": {
            key: asdict(item) for key, item in session.archive_records.items()
        },
        "meetings": {
            key: asdict(item) for key, item in session.meetings.items()
        },
        "administrative_documents": {
            key: asdict(item)
            for key, item in session.administrative_documents.items()
        },
        "contract_batches": {
            key: asdict(item) for key, item in session.contract_batches.items()
        },
        "household_contracts": {
            key: asdict(item) for key, item in session.household_contracts.items()
        },
        "resource_reservations": [
            asdict(item) for item in session.resource_reservations
        ],
        "resource_ledger_entries": session.resource_ledger_entries,
        "logs": session.logs,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


def decode_session(value: dict) -> GameSession:
    pending_value = value.get("pending_decision")
    pending = None
    if pending_value is not None:
        pending = PendingDecision(
            event_instance_id=str(pending_value["event_instance_id"]),
            decision_id=str(pending_value["decision_id"]),
            option_ids=tuple(pending_value["option_ids"]),
            state=DecisionState(pending_value["state"]),
            presented_state_version=int(
                pending_value["presented_state_version"]
            ),
            visible_title=str(pending_value["visible_title"]),
            visible_text=str(pending_value["visible_text"]),
            scene_id=pending_value.get("scene_id"),
            options=tuple(
                VisibleDecisionOption(**item)
                for item in pending_value.get("options", [])
            ),
            input_kind=str(pending_value.get("input_kind", "choice")),
            input_schema=pending_value.get("input_schema"),
            context=dict(pending_value.get("context", {})),
            presentation_entry_id=pending_value.get("presentation_entry_id"),
        )
    npc_states = {
        npc_id: NPCState(
            npc_id=str(item["npc_id"]),
            state_tier=NPCStateTier(item["state_tier"]),
            availability_mode=AvailabilityMode(item["availability_mode"]),
            profile_id=item.get("profile_id"),
            trust_score=item.get("trust_score"),
            trust_locked=bool(item.get("trust_locked", False)),
            trust_effects_applied=frozenset(
                item.get("trust_effects_applied", [])
            ),
            attitude_score=item.get("attitude_score"),
            anxiety_score=item.get("anxiety_score"),
            memory_id=item.get("memory_id"),
            chapter_disclosure_used=bool(
                item.get("chapter_disclosure_used", False)
            ),
            known_fact_ids=frozenset(item.get("known_fact_ids", [])),
            owned_evidence_ids=frozenset(
                item.get("owned_evidence_ids", [])
            ),
            special_flags=frozenset(item.get("special_flags", [])),
        )
        for npc_id, item in value.get("npc_states", {}).items()
    }
    return GameSession(
        session_id=str(value["session_id"]),
        account_id=str(value["account_id"]),
        package_id=str(value["package_id"]),
        package_version=str(value["package_version"]),
        package_content_hash=str(value["package_content_hash"]),
        random_seed=str(value["random_seed"]),
        game_state=_decode_current_game_state(value["game_state"]),
        origin_id=str(value["origin_id"]),
        timeline_id=str(
            value.get("timeline_id") or f"timeline_{value['session_id']}"
        ),
        loaded_from_snapshot_id=value.get("loaded_from_snapshot_id"),
        environment=str(value.get("environment", "sandbox")),
        consent_record_id=value.get("consent_record_id"),
        research_subject_id=value.get("research_subject_id"),
        experiment_id=value.get("experiment_id"),
        experiment_group_id=value.get("experiment_group_id"),
        npc_states=npc_states,
        status=SessionStatus(value["status"]),
        state_version=int(value["state_version"]),
        processing_action_id=value.get("processing_action_id"),
        pending_decision=pending,
        pending_decision_queue=list(value.get("pending_decision_queue", [])),
        flags=set(value.get("flags", [])),
        state_values=dict(
            value.get("state_values", {"lead_roster_disposition": "未获取"})
        ),
        triggered_events=set(value.get("triggered_events", [])),
        visible_events=[
            VisibleEvent(**item) for item in value.get("visible_events", [])
        ],
        story_beat_id=value.get("story_beat_id"),
        narrative_feed=[
            VisibleNarrativeEntry(**item)
            for item in value.get("narrative_feed", [])
        ],
        rendered_content_ids=set(value.get("rendered_content_ids", [])),
        next_feed_cursor=int(value.get("next_feed_cursor", 1)),
        known_fact_ids=set(value.get("known_fact_ids", [])),
        known_npc_ids=set(value.get("known_npc_ids", [])),
        encountered_npc_ids=set(value.get("encountered_npc_ids", [])),
        contactable_npc_ids=set(value.get("contactable_npc_ids", [])),
        relationship_edges=[
            dict(item) for item in value.get("relationship_edges", [])
        ],
        night_logs=list(value.get("night_logs", [])),
        ending_result=value.get("ending_result"),
        decision_parameters=dict(value.get("decision_parameters", {})),
        npc_demand_states={
            str(key): dict(item)
            for key, item in value.get("npc_demand_states", {}).items()
        },
        active_conversation=(
            ActiveConversation(**value["active_conversation"])
            if value.get("active_conversation") is not None else None
        ),
        completed_conversations=[
            CompletedConversation(**{
                **item,
                "transcript": tuple(
                    dict(turn) for turn in item.get("transcript", ())
                ),
            })
            for item in value.get("completed_conversations", [])
        ],
        active_group_conversation=(
            ForcedGroupConversation(**{
                **{
                    key: item
                    for key, item in value["active_group_conversation"].items()
                    if key != "max_turns"
                },
                "participant_ids": tuple(
                    value["active_group_conversation"].get(
                        "participant_ids", ()
                    )
                ),
                "demands": tuple(
                    value["active_group_conversation"].get("demands", ())
                ),
            })
            if value.get("active_group_conversation") is not None else None
        ),
        group_conversation_queue=[
            ForcedGroupConversation(**{
                **{key: entry for key, entry in item.items() if key != "max_turns"},
                "participant_ids": tuple(item.get("participant_ids", ())),
                "demands": tuple(item.get("demands", ())),
            })
            for item in value.get("group_conversation_queue", [])
        ],
        completed_group_conversations=list(
            value.get("completed_group_conversations", [])
        ),
        d75_settlement_snapshot=(
            D75SettlementSnapshot(**value["d75_settlement_snapshot"])
            if value.get("d75_settlement_snapshot") is not None
            else None
        ),
        household_settlement_entries=[
            HouseholdSettlementEntry(**item)
            for item in value.get("household_settlement_entries", [])
        ],
        governance_actions={
            key: GovernanceActionRecord(**{
                **item,
                "target_ids": tuple(item.get("target_ids", ())),
                "required_permissions": tuple(
                    item.get("required_permissions", ())
                ),
                "archive_ids": tuple(item.get("archive_ids", ())),
            })
            for key, item in value.get("governance_actions", {}).items()
        },
        archive_records={
            key: ArchiveRecord(**{
                **item,
                "related_npc_ids": tuple(item.get("related_npc_ids", ())),
            })
            for key, item in value.get("archive_records", {}).items()
        },
        meetings={
            key: MeetingRecord(**{
                **item,
                "participant_ids": tuple(item.get("participant_ids", ())),
                "lead_npc_id": item.get("lead_npc_id") or next(
                    iter(item.get("participant_ids", ())), ""
                ),
            })
            for key, item in value.get("meetings", {}).items()
        },
        administrative_documents={
            key: AdministrativeDocument(**{
                **item,
                "required_countersign_ids": tuple(
                    item.get("required_countersign_ids", ())
                ),
                "countersigned_by": tuple(item.get("countersigned_by", ())),
                "public_scope": tuple(item.get("public_scope", ())),
            })
            for key, item in value.get("administrative_documents", {}).items()
        },
        contract_batches={
            key: ContractBatch(**{
                **item,
                "household_ids": tuple(item.get("household_ids", ())),
                "contract_ids": tuple(item.get("contract_ids", ())),
            })
            for key, item in value.get("contract_batches", {}).items()
        },
        household_contracts={
            key: HouseholdContract(**{
                **item,
                "versions": [
                    ContractVersion(**{
                        **version,
                        "warnings": tuple(version.get("warnings", ())),
                    })
                    for version in item.get("versions", [])
                ],
            })
            for key, item in value.get("household_contracts", {}).items()
        },
        resource_reservations=[
            ResourceReservation(**item)
            for item in value.get("resource_reservations", [])
        ],
        resource_ledger_entries=[
            dict(item) for item in value.get("resource_ledger_entries", [])
        ],
        logs=list(value.get("logs", [])),
        created_at=str(value["created_at"]),
        updated_at=str(value["updated_at"]),
    )


def encode_operation(operation: OperationRecord) -> dict:
    return {
        "operation_id": operation.operation_id,
        "account_id": operation.account_id,
        "session_id": operation.session_id,
        "client_action_id": operation.client_action_id,
        "request_hash": operation.request_hash,
        "status": operation.status.value,
        "attempt_count": operation.attempt_count,
        "response": operation.response,
        "error": operation.error,
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
        "lease_token": operation.lease_token,
    }


def decode_operation(value: dict) -> OperationRecord:
    return OperationRecord(
        operation_id=str(value["operation_id"]),
        account_id=str(value["account_id"]),
        session_id=value.get("session_id"),
        client_action_id=str(value["client_action_id"]),
        request_hash=str(value["request_hash"]),
        status=OperationStatus(value["status"]),
        attempt_count=int(value.get("attempt_count", 1)),
        response=value.get("response"),
        error=value.get("error"),
        created_at=str(value["created_at"]),
        updated_at=str(value["updated_at"]),
        lease_token=str(value.get("lease_token", "")),
    )


def _decode_current_game_state(value: dict) -> GameState:
    # Retired mechanics are stripped when loading, without rewriting the saved record.
    values = dict(value)
    for key in ("fatigue", "overtime_points_today", "overtime_used_today", "consecutive_full_load_days", "chapter_overtime_count"):
        values.pop(key, None)
    old_cap = int(values.get("daily_action_point_cap", 8))
    values["action_points"] = min(8, max(0, int(values.get("action_points", 8)) + max(0, 8 - old_cap)))
    values["daily_action_point_cap"] = 8
    return GameState(**values)
