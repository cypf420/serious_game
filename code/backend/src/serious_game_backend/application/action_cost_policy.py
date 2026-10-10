from __future__ import annotations

from dataclasses import dataclass

from serious_game_backend.domain.game_session import GameSession


@dataclass(frozen=True, slots=True)
class CostResult:
    base_cost: int
    friction: int
    discount: int
    final_cost: int
    reasons: tuple[str, ...]


PEOPLE_ACTIONS = {
    "home_visit", "heart_to_heart", "relay_via_opinion_leader",
    "party_member_demonstration", "public_hearing", "field_visit",
    "clan_leader_campaign", "household_visit",
}
MEDIA_ACTIONS = {"contact_reporter", "public_hearing", "publish_document"}
CROSS_DEPARTMENT_ACTIONS = {
    "convene_leadership_meeting", "establish_relocation_taskforce",
    "initiate_accountability", "liaise_zhang_li", "leadership_meeting",
}
POLITICAL_CREDIT_LOCKED_ACTIONS = {
    "raise_overall_compensation", "initiate_accountability",
}


def quote_cost(
    session: GameSession,
    action_id: str,
    base_cost: int,
    *,
    target_npc_ids: tuple[str, ...] = (),
) -> CostResult:
    """最终剧本中的固定费用是唯一费用来源。"""

    del session, action_id, target_npc_ids
    fixed = max(0, int(base_cost))
    return CostResult(fixed, 0, 0, fixed, ())


def political_credit_block_reason(session: GameSession, action_id: str) -> str | None:
    del session, action_id
    return None
