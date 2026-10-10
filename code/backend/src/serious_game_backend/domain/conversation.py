from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def conversation_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ActiveConversation:
    conversation_id: str
    opportunity_id: str
    npc_id: str
    story_day: int
    turn_count: int = 0
    quoted_cost: int = 0
    cost_charged: bool = False
    transcript: list[dict[str, str]] = field(default_factory=list)
    started_at: str = field(default_factory=conversation_now_iso)
    start_reason: str = "interaction_opportunity"

    def add_turn(self, player_text: str, npc_text: str) -> None:
        self.transcript.extend((
            {"speaker": "player", "text": player_text},
            {"speaker": "npc", "text": npc_text},
        ))
        self.turn_count += 1


@dataclass(frozen=True, slots=True)
class CompletedConversation:
    conversation_id: str
    opportunity_id: str
    npc_id: str
    story_day: int
    start_reason: str
    end_reason: str
    completion_status: str
    transcript: tuple[dict[str, str], ...]
    started_at: str
    ended_at: str = field(default_factory=conversation_now_iso)


@dataclass(slots=True)
class ForcedGroupConversation:
    conversation_id: str
    conversation_type: str
    initiator_npc_id: str
    participant_ids: tuple[str, ...]
    agenda: str
    demands: tuple[str, ...]
    urgency: str
    story_day: int
    turn_count: int = 0
    transcript: list[dict] = field(default_factory=list)
    status: str = "pending"
    phase: str = "active"
    participant_states: dict[str, dict[str, str]] = field(default_factory=dict)
    closure_summary: str = ""
    memory_ids: list[str] = field(default_factory=list)
    followup_plan_id: str = ""
    persuasion_context: str = ""
    participant_guidance: dict[str, dict] = field(default_factory=dict)
    started_at: str = field(default_factory=conversation_now_iso)

    def __post_init__(self) -> None:
        for npc_id in self.participant_ids:
            self.participant_states.setdefault(
                npc_id,
                {"status": "active", "public_summary": "仍在追问"},
            )

    def add_player_turn(self, text: str) -> None:
        self.transcript.append({"speaker_type": "player", "text": text})

    def add_npc_turn(
        self,
        *,
        npc_id: str,
        npc_name: str,
        model_id: str,
        text: str,
        dialogue_act: str = "press",
        stance: str = "guarded",
    ) -> None:
        self.transcript.append({
            "speaker_type": "npc",
            "npc_id": npc_id,
            "npc_name": npc_name,
            "model_id": model_id,
            "text": text,
            "dialogue_act": dialogue_act,
            "stance": stance,
        })
