from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GameSnapshot:
    snapshot_id: str
    session_id: str
    account_id: str
    timeline_id: str
    snapshot_type: str
    reason: str
    story_day: int
    state_version: int
    package_id: str
    package_version: str
    package_content_hash: str
    snapshot_hash: str
    parent_snapshot_id: str | None
    created_at: str
    session_payload: dict


@dataclass(frozen=True, slots=True)
class ManualSaveSlot:
    account_id: str
    session_id: str
    slot_number: int
    snapshot_id: str
    display_name: str
    updated_at: str
