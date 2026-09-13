"""AC-04 resource proof, conditional on the explicitly listed story prerequisites.

This validates a simultaneous 36-household allocation; it is not a proof that
all prerequisite story branches can be reached in a single playthrough.
"""
from collections import Counter
from dataclasses import replace

from tests import test_contract_accounting as fixtures
from serious_game_backend.application.contract_facts import record_contract_signatory_contact
from serious_game_backend.domain.gameplay_governance import HouseholdContract, GovernanceActionRecord


def feasible_allocation():
    game = fixtures.ContractAccountingTests(); game.setUp()
    session = game.session(); package = game.runtime.packages.get(session.package_id)
    service = game.runtime.gameplay_governance
    session.game_state = replace(session.game_state, story_day=60)
    prerequisites = set(package.governance_config["contract_batch_gate_flags"].values())
    prerequisites.update(h.signing_lock_flag for h in package.households if h.signing_lock_flag)
    prerequisites.update({"村账已摊", "旧案了结", "补偿口径已澄清"})
    session.flags.update(prerequisites)
    pools = {r["resource_id"]: r for r in package.governance_config["resource_pools"]}
    available = {rid: r["capacity"] for rid, r in pools.items() if r["category"] == "housing"}
    rows = []
    households = sorted(package.households,
                        key=lambda h: ("low_floor" not in h.resettlement_preference, -h.resettlement_population, h.household_id))
    for household in households:
        area = {2: 80, 3: 100, 4: 120, 5: 140}[household.resettlement_population]
        accessible = "low_floor" in household.resettlement_preference
        candidates = [r for rid, r in pools.items() if rid in available and available[rid] > 0
                      and r["attributes"]["area_m2"] >= area
                      and (not accessible or r["attributes"].get("accessible"))]
        assert candidates, household.household_id
        selected = min(candidates, key=lambda r: (r["attributes"]["area_m2"], r["available_day"], r["resource_id"]))
        rid = selected["resource_id"]; available[rid] -= 1
        allocations = {}
        if household.grave_or_shrine_profile not in {"none", "clan_follower", "clan_accounting"}:
            allocations["grave_relocation_service"] = 1
        if household.medical_tags:
            allocations["lead_recheck_slot"] = 1
        if "school_continuity" in household.employment_startup_tags:
            allocations["school_transition_seat"] = 1
        followup = None
        if household.household_id == "HE-02":
            allocations["stable_job_slot"] = 1
            followup = {"medical_provider": "县医院", "recheck_interval_days": 30,
                        "employment_receiver": "就业服务中心", "medical_fee_arrangement": "allocated_medical_service"}
        limited = package.limited_signatory_for(household.household_id)
        principal = next(p for p in package.npc_profiles if p.npc_id == household.representative_npc)
        contract = HouseholdContract("proof_" + household.household_id, "proof", household.household_id,
            limited.name if limited else principal.name, None if limited else principal.npc_id, 60)
        session.household_contracts[contract.contract_id] = contract
        record_contract_signatory_contact(session, package, contract)
        if household.household_id == "LAO-01":
            action = GovernanceActionRecord("proof_viewing", "household_visit", 60, (principal.npc_id,), (),
                variant_id="field_visit", status="completed")
            action.hard_outcomes.append({"kind": "contract_fact", "id": "real_unit_viewed",
                "household_id": household.household_id, "housing_resource_id": rid,
                "location": "安置小区", "authoritative_ids": [action.action_instance_id]})
            session.governance_actions[action.action_instance_id] = action
        terms = {"policy_document_id": "doc_compensation_policy_v1", "cash_amount": service._standard_cash(package, household, months=0, reward=True),
            "budget_envelope": "property_land", "housing_resource_id": rid, "service_allocations": allocations,
            "payment_day": 60, "move_out_day": 80, "housing_delivery_day": 80, "transition_months": 0,
            "public_window_reward": True, "approval_document_ids": [], "followup_plan": followup}
        contract.term_sheet = service._validate_term_sheet(session, package, contract, terms)
        assert service._missing_hard_conditions(session, package, contract) == [], household.household_id
        service._allocate_signed_contract_resources(session, package, contract)
        rows.append({"household_id": household.household_id, "population": household.resettlement_population,
            "minimum_area": area, "accessible_required": accessible, "housing": rid,
            "housing_name": selected["name"], "available_day": selected["available_day"],
            "services": allocations, "cash": terms["cash_amount"],
            "story_prerequisites": sorted(prerequisites.intersection({household.signing_lock_flag,
                package.governance_config["contract_batch_gate_flags"].get(household.representative_npc)})),
            "evidence_prerequisite": household.ownership_status,
            "viewing_required": household.household_id == "LAO-01"})
    return rows, session, pools, prerequisites


def test_all_36_households_have_simultaneous_legal_resource_allocation():
    rows, session, pools, _ = feasible_allocation()
    assert len(rows) == 36
    used = Counter()
    for row in rows:
        used[row["housing"]] += 1
        used.update(row["services"])
    assert all(quantity <= pools[rid]["capacity"] for rid, quantity in used.items())
    assert session.game_state.budget_remaining >= 0
    assert len([r for r in rows if r["accessible_required"]]) == 2
