from __future__ import annotations

from pathlib import Path

import pytest

from serious_game_backend.application.action_service import ActionService
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tools.full_acceptance.ending_witnesses import (
    load_witnesses,
    validate_witnesses,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"
ROUTE_PROFILE_PATH = PACKAGE_ROOT / "acceptance_route_profiles.json"


def load_v3():
    return FileScriptPackageLoader().load(PACKAGE_ROOT)


def test_ending_witness_catalog_covers_every_published_ending() -> None:
    package = load_v3()
    witnesses = load_witnesses(ROUTE_PROFILE_PATH)
    coverage = validate_witnesses(witnesses, package)

    assert coverage.main_ending_ids == {
        item.ending_id for item in package.main_endings
    }
    assert coverage.sub_ending_ids == {
        item.sub_ending_id for item in package.sub_endings
    }
    assert coverage.invalid_state_patches == ()
    assert coverage.invalid_targets == ()
    assert coverage.duplicate_route_ids == ()
    assert len(witnesses) == 95
    assert all(len(item.target_main_ending_ids) == 1 for item in witnesses)
    assert all(len(item.target_sub_ending_ids) == 1 for item in witnesses)


def test_full_medical_settlement_reaches_the_published_remediated_axis() -> None:
    package = load_v3()
    medical = package.decisions["dp6_03"].option("a")
    effects = ActionService._effective_effects(
        medical,
        {"环评揭穿", "掌握血铅"},
        {},
        {"budget_remaining": 8000},
        {},
        decision_id="dp6_03",
    )

    assert "血铅补实" in effects.open_flags
    assert "环评已处理" in effects.open_flags

    unknown_environment = ActionService._effective_effects(
        medical,
        set(),
        {},
        {"budget_remaining": 8000},
        {},
        decision_id="dp6_03",
    )
    assert "血铅补实" in unknown_environment.open_flags
    assert "环评已处理" not in unknown_environment.open_flags


def test_tan_contract_path_requires_written_evidence_and_unlocks_after_resolution() -> None:
    package = load_v3()
    option = package.decisions["dp4_06"].option("a")

    # A reply is always selectable, but empty assurances and unrelated
    # engineering vouchers must not unlock the land-arrears contract route.
    for flags, facts, resolved in (
        (set(), set(), False),
        (set(), {"fact_original_vouchers"}, False),
        (set(), {"fact_tan_land_arrears"}, True),
        ({"旧账缺口已坐实"}, set(), True),
        ({"旧案了结"}, set(), True),
    ):
        effects = ActionService._effective_effects(
            option, flags, known_fact_ids=facts, decision_id="dp4_06",
        )
        assert ("谭老六核心矛盾已缓解" in effects.open_flags) == resolved
        assert ("谭老六合同批次可发起" in effects.open_flags) == resolved


def test_respectful_grave_route_requires_the_conversation_fact() -> None:
    package = load_v3()
    option = package.decisions["dp5_03"].option("a")

    assert option.required_fact_ids == frozenset({"fact_grave_protocol"})
    assert not option.required_flags


def test_zhou_clan_land_decision_is_reachable_from_its_story_scene() -> None:
    package = load_v3()

    assert not package.decisions["dp4_05"].required_flags


def test_suppressed_reporter_witnesses_declare_people_axis_not_proof_of_reachability() -> None:
    witnesses = load_witnesses(ROUTE_PROFILE_PATH)
    reporter_routes = [
        item for item in witnesses
        if item.target_main_ending_ids == ("ending_18",)
    ]

    assert len(reporter_routes) == 4
    assert {
        item.conversation_strategies["people_axis"] for item in reporter_routes
    } == {"认可"}


def test_veto_and_inspection_witnesses_include_their_legal_trigger_choices() -> None:
    witnesses = {item.route_id: item for item in load_witnesses(ROUTE_PROFILE_PATH)}

    for suffix in "abcde":
        assert witnesses[f"route-ending-02{suffix}"].decision_policy["dp6_05"] == "a"
    assert witnesses["route-ending-15b"].decision_policy["dp6_07"] == "d_a_b_c_e"


@pytest.mark.parametrize(
    "forbidden_key",
    ("state_patch", "flags_override", "metric_override", "database_operations"),
)
def test_witness_loader_rejects_direct_state_manipulation(
    tmp_path: Path,
    forbidden_key: str,
) -> None:
    path = tmp_path / "routes.json"
    path.write_text(
        """
        {
          "schema_version": 1,
          "profiles": [{
            "route_id": "illegal-route",
            "target_main_ending_ids": ["ending_01"],
            "target_sub_ending_ids": ["ending_01a"],
            "origin_id": "integrity",
            "decision_policy": {},
            "daily_action_policy": [],
            "conversation_strategies": {},
            "expected_end_day": 90,
            "%s": {}
          }]
        }
        """ % forbidden_key,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=forbidden_key):
        load_witnesses(path)
