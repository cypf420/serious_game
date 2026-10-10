from __future__ import annotations

from serious_game_backend.domain.game_session import GameSession


def active_budget_holds(
    session: GameSession,
    *,
    statuses: frozenset[str] = frozenset({"reserved", "committed"}),
    exclude_owner_id: str | None = None,
) -> int:
    """Return unpaid cash that is already promised by an active reservation."""

    return sum(
        reservation.quantity
        for reservation in session.resource_reservations
        if reservation.resource_id.startswith("budget:")
        and reservation.status in statuses
        and (
            exclude_owner_id is None
            or reservation.owner_id != exclude_owner_id
        )
    )


def unencumbered_budget(
    session: GameSession,
    *,
    exclude_owner_id: str | None = None,
) -> int:
    """Cash a new player choice may spend without stealing an existing promise."""

    return max(
        0,
        session.game_state.budget_remaining
        - active_budget_holds(
            session,
            exclude_owner_id=exclude_owner_id,
        ),
    )
