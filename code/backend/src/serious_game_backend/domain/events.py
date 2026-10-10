from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from serious_game_backend.domain.enums import DecisionState


@dataclass(frozen=True, slots=True)
class VisibleDecisionOption:
    option_id: str
    text: str
    available: bool = True
    unavailable_reason: str | None = None
    unlock_requirements: tuple[dict[str, str], ...] = ()
    next_steps: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingDecision:
    event_instance_id: str
    decision_id: str
    option_ids: tuple[str, ...]
    state: DecisionState = DecisionState.PENDING_DECISION
    presented_state_version: int = 1
    visible_title: str = ""
    visible_text: str = ""
    scene_id: str | None = None
    options: tuple[VisibleDecisionOption, ...] = ()
    input_kind: str = "choice"
    input_schema: dict | None = None
    context: dict = field(default_factory=dict)
    presentation_entry_id: str | None = None


@dataclass(frozen=True, slots=True)
class VisibleEvent:
    event_id: str
    story_day: int
    title: str
    summary: str
