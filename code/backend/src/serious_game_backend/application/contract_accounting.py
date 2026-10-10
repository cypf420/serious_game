"""One-time compatibility for the retired promise/late-payment accounting.

Call only on a detached session inside an existing write transaction, or from
the explicit offline migration tool. Reads must never persist a migration.
"""
from dataclasses import replace

from serious_game_backend.domain.errors import ActionUnavailableError


ACCOUNTING_VERSION = "signature_allocation_v1"
CONSUMED_STATUSES = frozenset({"reserved", "committed", "delivered", "allocated"})


def migrate_contract_accounting(session) -> bool:
    if session.state_values.get("contract_accounting") == ACCOUNTING_VERSION:
        return False
    signed = [c for c in session.household_contracts.values()
              if c.status == "signed" and c.term_sheet is not None]
    unpaid = [c for c in signed if not c.fulfillment.get("cash_paid")]
    required = sum(int(c.term_sheet["cash_amount"]) for c in unpaid)
    if required > session.game_state.budget_remaining:
        raise ActionUnavailableError(
            "旧合同未付款总额超过财政余额，无法安全转换账务；原进度未改变",
            details={"required": required, "remaining": session.game_state.budget_remaining})
    # Preflight complete before any mutation. Missing old allocations are an
    # inconsistent save, not permission to invent inventory or silently refund.
    for contract in signed:
        terms = contract.term_sheet
        expected = {f"budget:{terms['budget_envelope']}": int(terms["cash_amount"])}
        if terms.get("housing_resource_id"):
            expected[terms["housing_resource_id"]] = 1
        expected.update(terms.get("service_allocations", {}))
        actual = {}
        for entry in session.resource_reservations:
            if (entry.owner_type == "contract" and entry.owner_id == contract.contract_id
                    and entry.status in CONSUMED_STATUSES):
                actual[entry.resource_id] = actual.get(entry.resource_id, 0) + entry.quantity
        if {k: v for k, v in expected.items() if v} != {k: v for k, v in actual.items() if v}:
            raise ActionUnavailableError("旧合同资源记录不完整，原进度未改变",
                                         details={"contract_id": contract.contract_id})
    day = session.game_state.story_day
    for contract in unpaid:
        cash = int(contract.term_sheet["cash_amount"])
        state = session.game_state
        session.game_state = replace(state, budget_remaining=state.budget_remaining - cash,
                                     budget_paid=state.budget_paid + cash)
        session.resource_ledger_entries.append({
            "entry_id": f"migration:signature:{contract.contract_id}",
            "story_day": day, "change_kind": "payment", "source_type": "contract_accounting_migration",
            "source_id": contract.contract_id, "resource_id": "budget_remaining",
            "quantity": cash, "delta": -cash, "before": state.budget_remaining,
            "after": state.budget_remaining - cash, "payment_status": "paid"})
    signed_ids = {c.contract_id for c in signed}
    for entry in session.resource_reservations:
        if entry.owner_type == "contract" and entry.owner_id in signed_ids:
            if entry.status in CONSUMED_STATUSES:
                entry.status = "allocated"
                entry.expires_day = None
        elif entry.status in {"reserved", "committed"} and entry.owner_type in {"contract", "npc_demand"}:
            entry.status = "released"
            session.resource_ledger_entries.append({
                "entry_id": f"migration:release:{entry.reservation_id}", "story_day": day,
                "change_kind": "release", "source_type": "contract_accounting_migration",
                "source_id": entry.owner_id, "resource_id": entry.resource_id,
                "quantity": entry.quantity, "reservation_id": entry.reservation_id,
                "release_reason": "独立承诺及未签合同预占机制移除"})
    for contract in signed:
        contract.fulfillment["cash_paid"] = True
        contract.fulfillment["resources_allocated"] = True
        contract.fulfillment["accounting_version"] = ACCOUNTING_VERSION
        contract.reserved_until_day = None
    for contract in session.household_contracts.values():
        if contract.status != "signed":
            contract.reserved_until_day = None
            if contract.status == "accepted":
                contract.status = "draft"
    session.state_values["contract_accounting"] = ACCOUNTING_VERSION
    session.logs.append({"type": "contract_accounting_migration", "version": ACCOUNTING_VERSION,
                         "story_day": day, "cash_paid": required})
    return True
