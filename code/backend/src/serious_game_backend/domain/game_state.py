"""最终剧本口径的 v2 权威游戏状态。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


SCORE_FIELDS = (
    "public_trust",
    "social_stability",
    "political_credit",
    "media_pressure",
    "env_clue",
    "integrity",
    "cadre_discontent",
    "corruption_evidence",
)


@dataclass(frozen=True, slots=True)
class GameState:
    story_day: int = 1
    days_left: int = 90
    action_points: int = 8
    daily_action_point_cap: int = 8
    budget_remaining: int = 8000
    budget_unit: str = "万元"
    budget_base_authorized: int = 8000
    budget_approved_adjustments: int = 0
    budget_precoord_suspense: int = 0
    budget_committed: int = 0
    budget_paid: int = 0
    signed_households: int = 0
    reported_signed_households: int = 0
    total_households: int = 36
    public_trust: int = 50
    social_stability: int = 70
    political_credit: int = 70
    media_pressure: int = 30
    env_clue: int = 0
    integrity: int = 100
    cadre_discontent: int = 30
    stability_low_water: int = 70
    field_visit_count: int = 0
    lead_roster_disposition: str = "neutral"
    corruption_evidence: int = 0
    points_spent_today: int = 0
    half_day_action_used: bool = False
    daily_action_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.story_day <= 90:
            raise ValueError("story_day must be between 1 and 90")
        if not 0 <= self.days_left <= 90:
            raise ValueError("days_left must be between 0 and 90")
        if not 0 <= self.action_points <= self.daily_action_point_cap:
            raise ValueError("action_points is outside the daily allowance")
        if self.daily_action_point_cap != 8:
            raise ValueError("daily_action_point_cap must be 8")
        if self.budget_remaining < 0:
            raise ValueError("budget_remaining must not be negative")
        if any(value < 0 for value in (
            self.budget_base_authorized,
            self.budget_precoord_suspense,
            self.budget_committed,
            self.budget_paid,
        )):
            raise ValueError("budget ledger values must not be negative")
        if not 0 <= self.signed_households <= self.total_households:
            raise ValueError("signed_households is outside the household range")
        if not 0 <= self.reported_signed_households <= self.total_households:
            raise ValueError("reported_signed_households is outside the household range")
        for name in SCORE_FIELDS:
            value = getattr(self, name)
            if not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.field_visit_count < 0:
            raise ValueError("field_visit_count must not be negative")
        if self.lead_roster_disposition not in {"neutral", "supportive", "hostile", "detached"}:
            raise ValueError("invalid lead_roster_disposition")

    @classmethod
    def new_game(cls, initial_state: dict | None = None) -> "GameState":
        values = dict(initial_state or {})
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in allowed})

    def spend_action_points(
        self,
        action_id: str,
        cost: int,
        *,
        half_day: bool = False,
    ) -> "GameState":
        if cost < 0:
            raise ValueError("action point cost must not be negative")
        if cost > self.action_points:
            raise ValueError("not enough action points")
        counts = dict(self.daily_action_counts)
        counts[action_id] = counts.get(action_id, 0) + 1
        return replace(
            self,
            action_points=self.action_points - cost,
            points_spent_today=self.points_spent_today + cost,
            half_day_action_used=self.half_day_action_used or half_day,
            daily_action_counts=counts,
            field_visit_count=(
                self.field_visit_count + 1
                if action_id == "field_visit"
                else self.field_visit_count
            ),
        )

    def reset_for_day(
        self,
        *,
        story_day: int,
        days_left: int,
        action_point_cap: int,
    ) -> "GameState":
        return replace(
            self,
            story_day=story_day,
            days_left=days_left,
            action_points=action_point_cap,
            daily_action_point_cap=action_point_cap,
            points_spent_today=0,
            half_day_action_used=False,
            daily_action_counts={},
        )
