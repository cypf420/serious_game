"""Server-only contract evidence; never project this mapping as a player checklist.

Text from a player, a draft, or an LLM is not evidence of completed work.
The two recording helpers are called only by successful application actions.
"""
from __future__ import annotations

FACT_KEYS = ("authorization_confirmed", "real_unit_viewed", "ledger_disclosed",
             "old_case_resolved", "prior_payment_verified")


def _household(package, household_id):
    return next((h for h in package.households if h.household_id == household_id), None)


def resolve_contract_facts(session, package, contract) -> dict[str, bool]:
    """Derive facts in this household's scope, ignoring all submitted booleans."""
    result = dict.fromkeys(FACT_KEYS, False)
    household = _household(package, contract.household_id)
    if household is None:
        return result
    flags = session.flags
    # These story outcomes concern specific households, not every contract.
    if household.representative_npc == "npc_zhou_mancang":
        result["ledger_disclosed"] = "村账已摊" in flags
    if household.representative_npc == "npc_tan_laoliu":
        result["old_case_resolved"] = bool(flags.intersection({
            "旧案了结", "谭老六核心矛盾已缓解"}))
    if contract.household_id == "MIAO-01":
        result["prior_payment_verified"] = "补偿口径已澄清" in flags
    for event in session.logs:
        if (event.get("type") == "contract_signatory_contact"
                and event.get("household_id") == contract.household_id
                and event.get("contract_id") == contract.contract_id
                and event.get("signatory_name") == contract.signatory_name):
            result["authorization_confirmed"] = True
    housing_id = (contract.term_sheet or {}).get("housing_resource_id")
    for action in session.governance_actions.values():
        if (action.action_kind != "household_visit"
                or action.status not in {"active", "completed"}
                or household.representative_npc not in action.target_ids):
            continue
        for outcome in action.hard_outcomes:
            if (outcome.get("kind") == "contract_fact"
                    and outcome.get("id") == "real_unit_viewed"
                    and outcome.get("household_id") == contract.household_id
                    and outcome.get("housing_resource_id") == housing_id
                    and outcome.get("location") == "安置小区"
                    and outcome.get("authoritative_ids") == [action.action_instance_id]):
                result["real_unit_viewed"] = True
    # dp6_02(b) records a general viewing of completed units in building 3.
    # It contains no authoritative resource-pool ID or individual unit mapping,
    # so it cannot certify the dwelling selected in this contract (or a later
    # replacement). That story remains in narrative/history; only the scoped
    # application viewing outcome above proves the current contractual choice.
    return result


def record_contract_signatory_contact(session, package, contract) -> bool:
    """Stage canonical principal contact inside a dedicated review transaction.

    The service may stage this before invoking the dedicated signatory model
    so hard-condition evaluation can distinguish personal from proxy signing.
    Persist it only when that review transaction succeeds; a failed model call
    or failed signing transaction must discard the detached session entirely.
    Do not call for a representative conversation or a document-generation call.
    A verified principal participating personally does not need proxy authority.
    This helper validates the canonical principal; it does not infer identity
    from an NPC's prose. The caller owns the transaction/version check.
    """
    if session.household_contracts.get(contract.contract_id) is not contract:
        return False
    household = _household(package, contract.household_id)
    if household is None:
        return False
    limited = package.limited_signatory_for(contract.household_id)
    if limited is not None:
        valid = contract.signatory_name == limited.name and contract.signatory_npc_id is None
    else:
        profile = next((p for p in package.npc_profiles
                        if p.npc_id == household.representative_npc), None)
        valid = (profile is not None and contract.signatory_name == profile.name
                 and contract.signatory_npc_id == profile.npc_id)
    if not valid:
        return False
    if any(e.get("type") == "contract_signatory_contact"
           and e.get("contract_id") == contract.contract_id for e in session.logs):
        return True
    session.logs.append({"type": "contract_signatory_contact",
                         "contract_id": contract.contract_id,
                         "household_id": contract.household_id,
                         "signatory_name": contract.signatory_name,
                         "story_day": session.game_state.story_day})
    return True


def conduct_household_viewing(session, package, action, *, household_id: str,
                              housing_resource_id: str, invitation: str,
                              npc_accepted: bool) -> dict | None:
    """Execute a mutually accepted, explicit present-tense viewing during a visit.

    Caller supplies acceptance of THIS invitation from the targeted NPC turn,
    not an inferred claim that viewing happened previously. Uses the already
    paid visit, spends/reserves no housing, and returns an auditable scene result.
    No public endpoint should expose this helper as an arbitrary fact setter.
    """
    household = _household(package, household_id)
    if (household is None or npc_accepted is not True
            or session.governance_actions.get(action.action_instance_id) is not action
            or action.action_kind != "household_visit" or action.status != "active"
            or action.variant_id == "contract_negotiation"
            or tuple(action.target_ids) != (household.representative_npc,)
            or household.is_shadow_household):
        return None
    # Requests to perform an action are distinct from self-reported completion.
    if (not any(word in invitation for word in ("现在去看", "一起去看", "带你去看", "带您去看", "现场看房"))
            or any(word in invitation for word in ("不去", "不用", "不必", "已经", "之前", "明天", "下次"))):
        return None
    pool = next((p for p in (package.governance_config or {}).get("resource_pools", [])
                 if p["resource_id"] == housing_resource_id and p["category"] == "housing"), None)
    if pool is None or int(pool["available_day"]) > session.game_state.story_day:
        return None
    used = sum(r.quantity for r in session.resource_reservations
               if r.resource_id == housing_resource_id
               and r.status in {"reserved", "committed", "delivered", "allocated"})
    if used >= int(pool["capacity"]):
        return None
    existing = next((o for o in action.hard_outcomes
                     if o.get("kind") == "contract_fact" and o.get("id") == "real_unit_viewed"
                     and o.get("household_id") == household_id
                     and o.get("housing_resource_id") == housing_resource_id), None)
    if existing:
        return existing
    outcome = {"kind": "contract_fact", "id": "real_unit_viewed",
               "household_id": household_id, "housing_resource_id": housing_resource_id,
               "location": "安置小区", "story_day": session.game_state.story_day,
               "authoritative_ids": [action.action_instance_id],
               "summary": f"双方到安置小区查看了可交付的{pool['name']}，实际看房已记录。"}
    action.hard_outcomes.append(outcome)
    return outcome
