from __future__ import annotations

from dataclasses import dataclass, field

from serious_game_backend.domain.enums import AvailabilityMode, NPCStateTier


@dataclass(frozen=True, slots=True)
class NPCState:
    npc_id: str
    state_tier: NPCStateTier
    availability_mode: AvailabilityMode = AvailabilityMode.CLOSED
    profile_id: str | None = None
    trust_score: int | None = None
    trust_locked: bool = False
    trust_effects_applied: frozenset[str] = frozenset()
    attitude_score: int | None = None
    anxiety_score: int | None = None
    memory_id: str | None = None
    chapter_disclosure_used: bool = False
    known_fact_ids: frozenset[str] = frozenset()
    owned_evidence_ids: frozenset[str] = frozenset()
    special_flags: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.npc_id:
            raise ValueError("npc_id must not be empty")
        numeric_values = (self.trust_score, self.attitude_score, self.anxiety_score)
        if self.state_tier is NPCStateTier.DEEP:
            if any(value is None for value in numeric_values):
                raise ValueError("deep NPC state requires trust, attitude, and anxiety")
        elif any(value is not None for value in numeric_values):
            raise ValueError("limited and ambient NPCs must not carry numeric state")
        for value in numeric_values:
            if value is not None and not 0 <= value <= 100:
                raise ValueError("NPC numeric state must be between 0 and 100")
        if self.trust_locked and self.trust_score != 0:
            raise ValueError("locked trust must remain zero")
