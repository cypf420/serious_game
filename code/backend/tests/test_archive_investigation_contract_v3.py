from __future__ import annotations

from pathlib import Path

from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"


def test_v3_archive_investigations_have_authoritative_unlock_contract() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_DIR)

    expected = {
        "archive_household_registry": (1, ("fact_total_households",)),
        "archive_coordination_fee_index": (1, ("fact_two_million_fee",)),
        "archive_village_social_excerpt": (2, ("fact_clan_power_map",)),
        "archive_invoice_number_index": (16, ("fact_connected_invoices",)),
        "archive_original_vouchers": (18, ("fact_original_vouchers",)),
        "archive_environmental_report_versions": (21, ("fact_identical_reports",)),
        "archive_signing_ledger_comparison": (30, ("fact_false_signing",)),
        "archive_tan_land_arrears": (38, ("fact_tan_land_arrears",)),
        "archive_lead_census_master": (45, ("fact_lead_census",)),
        "archive_eia_raw_data": (45, ("fact_eia_original",)),
        "archive_inspection_schedule": (58, ("fact_inspection_anchors",)),
        "archive_resettlement_acceptance_sample": (60, ("fact_shell_house",)),
    }

    actual = {
        item.archive_id: (item.unlock_day, item.result_fact_ids)
        for item in package.archive_investigations
    }
    assert actual == expected
    assert all(item.content.strip() for item in package.archive_investigations)
    assert all(item.strategic_uses for item in package.archive_investigations)
    assert all(item.evidence_level in {"E1", "E2", "E3"} for item in package.archive_investigations)


def test_v3_evidence_decisions_reference_fact_ids_and_keep_a_fallback() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_DIR)
    expected = {
        ("dp2_01", "a"): {"fact_connected_invoices"},
        ("dp2_04", "a"): {"fact_identical_reports"},
        ("dp2_04", "b"): {"fact_identical_reports"},
        ("dp3_02", "a"): {"fact_false_signing"},
        ("dp4_01", "a"): {"fact_lead_census"},
        ("dp4_01", "d"): {"fact_lead_census"},
        ("dp4_08", "a"): {"fact_lead_census"},
        ("dp4_10", "a"): {
            "fact_lead_census",
            "fact_two_million_fee",
            "fact_eia_original",
        },
        ("dp5_06", "a"): {"fact_false_signing"},
        ("dp6_09", "a"): {"fact_inspection_anchors", "fact_eia_original"},
        ("dp6_09", "b"): {"fact_lead_census"},
        ("dp6_10", "b"): {
            "fact_original_vouchers",
            "fact_lead_census",
            "fact_false_signing",
            "fact_shell_house",
        },
    }

    for (decision_id, option_id), fact_ids in expected.items():
        option = package.decisions[decision_id].option(option_id)
        assert option is not None
        assert option.required_fact_ids == frozenset(fact_ids)
        assert option.unlock_requirements

    for decision_id in {item[0] for item in expected}:
        decision = package.decisions[decision_id]
        assert any(
            not option.required_fact_ids and not option.required_any_fact_ids
            for option in decision.options
        ), decision_id


def test_person_only_facts_are_not_unlocked_by_archives() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_DIR)
    archive_facts = {
        fact_id
        for item in package.archive_investigations
        for fact_id in item.result_fact_ids
    }

    assert archive_facts.isdisjoint(
        {
            "fact_wu_independent_voice",
            "fact_liu_old_ledger",
            "fact_shi_usb",
            "fact_water_sample",
            "fact_lead_287",
            "fact_grave_protocol",
            "fact_zhou_ledger_order",
        }
    )
