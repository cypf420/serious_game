"""Server-owned schedule and transition supplement for simplified schemes."""
from decimal import Decimal, ROUND_CEILING
from serious_game_backend.domain.errors import ActionUnavailableError


def arrange_contract(session, package, contract, value):
    value = dict(value)
    config = package.governance_config or {}
    household = next(h for h in package.households if h.household_id == contract.household_id)
    housing = next((p for p in config.get("resource_pools", [])
                    if p["resource_id"] == value.get("housing_resource_id") and p.get("category") == "housing"), None)
    if value.get("housing_resource_id") and housing is None:
        raise ActionUnavailableError("请选择有效安置房源。")
    move_day = min(90, session.game_state.story_day + 20)
    delivery_day = max(move_day, int(housing["available_day"])) if housing else move_day
    months = (delivery_day - move_day + 29) // 30
    rate = Decimal(str(config["compensation_rates"]["transition_per_person_month"]))
    supplement = int((rate * household.resettlement_population * months).to_integral_value(rounding=ROUND_CEILING))
    base = int(value["cash_amount"])
    value.update(budget_envelope="property_land", payment_day=session.game_state.story_day,
                 move_out_day=move_day, housing_delivery_day=delivery_day, transition_months=months,
                 cash_amount=base + supplement, public_window_reward=None)
    return value, {"version": 1, "base_cash_amount": base, "transition_cash_amount": supplement,
                   "budget_allocations": {"property_land": base, "moving_transition_reward": supplement}}
