from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from serious_game_backend.application.action_cost_policy import (
    political_credit_block_reason,
    quote_cost,
)
from serious_game_backend.application.gameplay_governance_service import (
    GameplayGovernanceService,
)
from serious_game_backend.application.decision_tradeoff_policy import (
    player_facing_metric_deltas,
)
from serious_game_backend.application.npc_demand_service import NPCDemandService
from serious_game_backend.application.progress_broadcast_policy import (
    progress_broadcast,
)
from serious_game_backend.application.story_clock_service import StoryClockService
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.game_state import GameState
from serious_game_backend.domain.gameplay_governance import (
    ResourceReservation,
)
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryGameSessionRepository,
    InMemoryScriptPackageRepository,
)
from serious_game_backend.infrastructure.repositories.codec import (
    decode_session,
    encode_session,
)
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


PACKAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "content" / "packages" / "pkg_gameplay_v2"
)


@pytest.fixture(scope="module")
def package():
    return FileScriptPackageLoader().load(PACKAGE_DIR)


def new_session(package, **state_changes) -> GameSession:
    state = GameState.new_game(package.initial_state)
    if state_changes:
        state = replace(state, **state_changes)
    return GameSession(
        session_id="sess_demands",
        account_id="account",
        package_id=package.package_id,
        package_version=package.package_version,
        package_content_hash=package.content_hash,
        random_seed="seed",
        game_state=state,
        origin_id="technical",
    )


def demand_service(session, package):
    sessions = InMemoryGameSessionRepository()
    sessions.create(session)
    service = GameplayGovernanceService(
        sessions,
        InMemoryScriptPackageRepository([package]),
        None,
        None,
        VisibleStateProjector(),
        None,
    )
    return service, sessions


def test_progress_broadcast_only_appears_every_ten_days(package):
    assert progress_broadcast(new_session(package, story_day=9, days_left=81)) is None
    broadcast = progress_broadcast(new_session(
        package,
        story_day=10,
        days_left=80,
        signed_households=4,
    ))
    assert broadcast is not None
    assert broadcast["broadcast_id"] == "progress_d10"
    assert broadcast["tone"] == "encouraging"
    assert broadcast["progress"]["expected"] == 4


def test_progress_broadcast_turns_stern_when_governance_is_slipping(package):
    session = new_session(
        package,
        story_day=20,
        days_left=70,
        signed_households=1,
        public_trust=35,
        social_stability=30,
        media_pressure=70,
    )
    session.npc_demand_states["broken_promise"] = {"status": "breached"}
    broadcast = progress_broadcast(session)
    assert broadcast is not None
    assert broadcast["tone"] == "stern"
    assert "会议纪要" in broadcast["message"]
    assert not any("疲惫" in item for item in broadcast["signals"])
    assert not any("承诺违约" in item for item in broadcast["signals"])
    # Historical manual statuses no longer affect the ten-day assessment.
    session.npc_demand_states.clear()
    assert progress_broadcast(session) == broadcast


def test_progress_broadcast_uses_wry_nudge_for_a_small_delay(package):
    broadcast = progress_broadcast(new_session(
        package,
        story_day=10,
        days_left=80,
        signed_households=2,
    ))
    assert broadcast is not None
    assert broadcast["tone"] == "wry"
    assert "稳步推进" in broadcast["headline"]
    assert "行李不会" in broadcast["message"]


def test_visible_state_projects_the_current_progress_broadcast(package):
    session = new_session(
        package,
        story_day=30,
        days_left=60,
        signed_households=8,
    )
    visible = VisibleStateProjector().project(session, package)
    assert visible["progress_broadcast"]["story_day"] == 30


def test_every_npc_has_one_machine_readable_core_demand(package):
    assert len(package.npc_profiles) == 29
    assert len(package.npc_demands) == 29
    assert {item.npc_id for item in package.npc_demands} == {
        item.npc_id for item in package.npc_profiles
    }
    assert len({item.demand_id for item in package.npc_demands}) == 29
    for demand in package.npc_demands:
        assert all((
            demand.demand_id, demand.npc_id, demand.title, demand.category,
            demand.description, demand.legal_disposition,
        ))
        assert isinstance(demand.discover, dict)
        assert isinstance(demand.commit, dict)
        assert isinstance(demand.satisfy, dict)
        assert isinstance(demand.consequences, dict)


def test_illegal_private_demands_have_no_manual_disposition_buttons(package):
    dispositions = {
        item.npc_id: item.legal_disposition for item in package.npc_demands
    }
    assert dispositions["npc_qian_wei"] == "lawfully_refuse"
    assert dispositions["npc_zhou_dashan"] == "lawfully_refuse"
    assert dispositions["npc_zhao_jianguo"] == "lawfully_refuse"
    assert NPCDemandService.allowed_transitions(
        "acknowledged", "lawfully_refuse"
    ) == []


def test_private_demands_are_never_projected_as_an_omniscient_checklist(package):
    session = new_session(package)
    NPCDemandService.initialize(session, package)
    assert len(session.npc_demand_states) == 29
    for state in session.npc_demand_states.values():
        state["status"] = "acknowledged"
    assert NPCDemandService.public(session, package) == []

def test_formal_contact_records_contact_but_does_not_disclose_private_needs(package):
    session = new_session(package)
    NPCDemandService.initialize(session, package)
    demand = next(d for d in package.npc_demands if d.npc_id == "npc_wu_xiuying")
    session.logs.append({"type": "conversation_started", "npc_id": demand.npc_id, "story_day": 1})
    before = session.game_state
    NPCDemandService.sync(session, package)
    assert session.npc_demand_states[demand.demand_id]["status"] == "acknowledged"
    assert session.game_state == before
    assert NPCDemandService.public(session, package) == []
    assert NPCDemandService.allowed_transitions("acknowledged", demand.legal_disposition) == []

def test_legacy_save_defaults_to_empty_demand_state_and_can_be_initialized(package):
    session = new_session(package)
    payload = encode_session(session)
    payload.pop("npc_demand_states")
    restored = decode_session(payload)
    assert restored.npc_demand_states == {}
    NPCDemandService.initialize(restored, package)
    assert len(restored.npc_demand_states) == 29


@pytest.mark.parametrize("old_status", ["unknown", "discovered", "acknowledged", "committed", "satisfied", "lawfully_refused", "breached", "expired"])
@pytest.mark.parametrize("transition", ["acknowledged", "committed", "satisfied", "lawfully_refused", "breached", "expired"])
def test_retired_disposal_rejects_every_transition_without_mutation(package, old_status, transition):
    session = new_session(package)
    session.npc_demand_states["demand_wu_xiuying"] = {
        "npc_id": "npc_wu_xiuying", "status": old_status, "history": []}
    session.resource_reservations.append(ResourceReservation(
        "old-hold", "npc_demand", "demand_wu_xiuying", "audit_slot", 1, "committed", 1))
    service, sessions = demand_service(session, package)
    before = encode_session(session)
    with pytest.raises(ActionUnavailableError, match="已移除"):
        service.dispose_npc_demand(account_id=session.account_id, session_id=session.session_id,
            state_version=session.state_version, demand_id="demand_wu_xiuying", transition=transition)
    assert encode_session(sessions.get_owned(session.session_id, session.account_id)) == before

def test_old_commitment_does_not_auto_fulfill_on_the_next_day(package):
    session = new_session(package, story_day=2, days_left=88)
    demand = next(d for d in package.npc_demands if d.demand_id == "demand_zheng_xiangdong")
    session.npc_demand_states[demand.demand_id] = {
        "npc_id": demand.npc_id, "status": "committed", "updated_day": 1, "history": []}
    session.resource_reservations.append(ResourceReservation(
        "old-hold", "npc_demand", demand.demand_id, "legal_review_slot", 1,
        "committed", 1, committed_day=1))
    before_state = session.game_state
    before_resources = deepcopy(session.resource_reservations)
    NPCDemandService.sync(session, package)
    assert not NPCDemandService.can_fulfill(session, package, demand)
    assert session.npc_demand_states[demand.demand_id]["status"] == "committed"
    assert session.game_state == before_state
    assert session.resource_reservations == before_resources

def test_visible_projection_is_idempotent_and_does_not_sync_demands(package):
    session = new_session(package)
    before = encode_session(session)
    projector = VisibleStateProjector()

    first = projector.project(session, package)
    second = projector.project(session, package)

    assert first == second
    assert encode_session(session) == before
    assert session.state_version == before["state_version"]
    assert session.npc_demand_states == {}


def test_story_flag_sync_does_not_double_score_or_apply_retired_expiry_penalties(package):
    source = next(d for d in package.npc_demands if d.demand_id == "demand_zheng_xiangdong")
    flagged = replace(source, satisfy={"required_flags": ["proof_ready"]})
    flagged_package = replace(package, npc_demands=tuple(
        flagged if d.demand_id == flagged.demand_id else d for d in package.npc_demands))
    session = new_session(flagged_package)
    session.npc_demand_states[flagged.demand_id] = {
        "npc_id": flagged.npc_id, "status": "committed", "history": []}
    session.flags.add("proof_ready")
    before = session.game_state
    NPCDemandService.sync(session, flagged_package)
    NPCDemandService.sync(session, flagged_package)
    assert session.npc_demand_states[flagged.demand_id]["status"] == "satisfied"
    assert session.game_state == before
    expired = new_session(package, story_day=59, days_left=31)
    expired.npc_demand_states["demand_shi_wenbin"] = {
        "npc_id": "npc_shi_wenbin", "status": "committed", "updated_day": 58, "history": []}
    before = expired.game_state
    NPCDemandService.sync(expired, package)
    NPCDemandService.sync(expired, package)
    assert expired.npc_demand_states["demand_shi_wenbin"]["status"] == "committed"
    assert expired.game_state == before

def test_retired_resource_transfer_helpers_are_not_available():
    # Old-hold migration is covered by test_contract_accounting. No helper
    # remains that can create a new independent NPC commitment or transfer it.
    assert not hasattr(GameplayGovernanceService, "_commit_demand_resources")
    assert not hasattr(GameplayGovernanceService, "_reserve_contract_resources")

def test_cost_policy_preserves_final_script_fixed_prices(package):
    trust = new_session(package, public_trust=40)
    trust_quote = quote_cost(trust, "home_visit", 7)
    assert trust_quote.friction == 0
    assert trust_quote.final_cost == 7
    media = new_session(package, media_pressure=61)
    assert quote_cost(media, "contact_reporter", 2).final_cost == 2
    cadre = new_session(package, cadre_discontent=61)
    assert quote_cost(cadre, "leadership_meeting", 3).final_cost == 3
    credit = new_session(package, political_credit=20)
    assert political_credit_block_reason(credit, "initiate_accountability") is None
    assert package.action_rules["forced_clearance"].cost_for(
        package.action_cost_tier(90)
    ) == 8


def test_confirmed_demand_does_not_change_fixed_action_price(package):
    session = new_session(package)
    NPCDemandService.initialize(session, package)
    demand = next(
        item for item in package.npc_demands if item.npc_id == "npc_wu_xiuying"
    )
    session.npc_demand_states[demand.demand_id]["status"] = "acknowledged"

    untargeted = quote_cost(session, "home_visit", 2)
    matching = quote_cost(
        session,
        "home_visit",
        2,
        target_npc_ids=("npc_wu_xiuying",),
    )
    other_person = quote_cost(
        session,
        "home_visit",
        2,
        target_npc_ids=("npc_zhou_dashan",),
    )

    assert untargeted.discount == 0
    assert matching.discount == 0
    assert matching.final_cost == 2
    assert other_person.discount == 0


def test_key_character_demands_match_their_story_roles(package):
    resources = {
        item.npc_id: {
            value["resource_id"] for value in item.commit.get("resources", ())
        }
        for item in package.npc_demands
    }
    assert resources["npc_zhou_mancang"] == {"audit_slot"}
    assert resources["npc_ma_changshun"] == {"business_restart_package"}
    assert resources["npc_ning_dehai"] == {"legal_review_slot"}
    assert resources["npc_yang_bo"] == {
        "startup_interest_slot", "broadband_transition_slot",
        "school_transition_seat",
    }
    assert resources["npc_lao_juetou"] == {"housing_d1_100"}
    assert resources["npc_miao_xiwang"] == {
        "lead_recheck_slot", "child_assessment_slot",
    }
    assert resources["npc_deng_shouben"] == {
        "housing_d1_80", "elder_support_slot",
    }


def test_low_stability_does_not_secretly_change_next_day_cap(package):
    class Events:
        @staticmethod
        def trigger_fixed_events(_session, _package):
            return []

    session = new_session(package, social_stability=30)
    StoryClockService(Events()).end_day(session, package)
    assert session.game_state.daily_action_point_cap == 8
    assert not any(
        item.get("type") == "low_stability_action_cap" for item in session.logs
    )


def test_zero_ap_forced_decision_has_no_deadlock_and_preview_hides_internal_fields(package):
    session = new_session(package, action_points=0)
    StoryFlowService()._present_decision_id(session, package, "dp2_08")
    visible = VisibleStateProjector().project(session, package)
    options = visible["pending_decision"]["options"]
    assert options
    assert all("tradeoff_preview" not in item for item in options)
    serialized = json.dumps(options, ensure_ascii=False)
    assert "flag_" not in serialized
    assert "open_flags" not in serialized
    assert "state_assignments" not in serialized


def test_attached_and_collective_decisions_do_not_charge_again(package):
    assert package.decisions["dp1_03"].cost_source == "attached"
    assert package.decisions["ev1_01_reception_bag"].cost_source == "interrupt"
    assert package.decisions["dp2_08"].cost_source == "desk"
    assert package.decisions["dp1_04"].cost_source == "collective"
    assert package.decisions["dp1_04"].action_point_cost == 0


def test_every_decision_option_has_visible_gain_and_cost_preview(package):
    harmful_when_positive = {"media_pressure", "cadre_discontent"}
    for decision in package.decisions.values():
        for option in decision.options:
            deltas = player_facing_metric_deltas(option)
            assert deltas or option.effects.ledger_deltas
            if deltas:
                valences = set()
                for field, (minimum, maximum) in deltas.items():
                    positive = minimum > 0 and maximum > 0
                    beneficial = positive != (field in harmful_when_positive)
                    valences.add("benefit" if beneficial else "cost")
                assert valences == {"benefit", "cost"}
