from __future__ import annotations

from serious_game_backend.application.scripted_delta_resolver import ScriptedDeltaResolver
from serious_game_backend.domain.llm import RoleTurnResult, ValidatedRoleTurn
from serious_game_backend.domain.npc_state import NPCState
from serious_game_backend.domain.enums import NPCStateTier


ATTITUDE_BANDS = {"none": 0, "micro": 5, "medium": 15, "heavy": 30}
ANXIETY_BANDS = {"none": (0, 0), "light": (5, 10), "medium": (15, 25), "heavy": (30, 30)}


class StateDeltaValidator:
    def __init__(self, resolver: ScriptedDeltaResolver) -> None:
        self._resolver = resolver

    def validate_role_turn(
        self,
        result: RoleTurnResult,
        npc_state: NPCState,
        *,
        random_seed: str,
        source_id: str,
    ) -> ValidatedRoleTurn:
        if npc_state.state_tier is not NPCStateTier.DEEP:
            if result.attitude_band != "none" or result.anxiety_band != "none":
                raise ValueError("limited and ambient NPCs cannot receive numeric LLM deltas")
        attitude = self._signed(
            ATTITUDE_BANDS[result.attitude_band], result.attitude_direction
        )
        anxiety_range = ANXIETY_BANDS[result.anxiety_band]
        anxiety_value = self._resolver.resolve(
            *anxiety_range,
            random_seed=random_seed,
            source_id=f"{source_id}:anxiety",
        )
        anxiety = self._signed(anxiety_value, result.anxiety_direction)
        return ValidatedRoleTurn(
            npc_id=result.npc_id,
            dialogue=result.dialogue,
            portrait_state=result.portrait_state,
            attitude_delta=attitude,
            anxiety_delta=anxiety,
            input_relevance=result.input_relevance,
            disclosure_id=result.disclosure_id,
            memory_candidate=result.memory_candidate,
            will_share_with=result.will_share_with,
            risk_notes=result.risk_notes,
            conversation_state=result.conversation_state,
            exit_narrative=result.exit_narrative,
        )

    @staticmethod
    def _signed(value: int, direction: str) -> int:
        if direction == "increase":
            return value
        if direction == "decrease":
            return -value
        if direction == "none" and value == 0:
            return 0
        raise ValueError("non-zero band requires increase or decrease direction")
