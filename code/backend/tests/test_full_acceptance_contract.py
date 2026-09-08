from __future__ import annotations

from pathlib import Path

from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tools.full_acceptance.coverage_contract import (
    CoverageContract,
    CoverageItem,
    build_coverage_contract,
)
from tools.full_acceptance.evidence_store import EvidenceStore, SecretMaterialError
from tools.full_acceptance.report import build_release_report


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "content" / "packages"


def test_published_v3_full_acceptance_inventory_is_complete() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_ROOT / "pkg_gameplay_v3")

    contract = build_coverage_contract(package)

    assert contract.counts == {
        "story_days": 90,
        "main_endings": 24,
        "sub_endings": 95,
        "facts": 19,
        "fact_acquisition_methods": 28,
        "archives": 12,
        "interaction_opportunities": 32,
        "npcs": 29,
        "map_locations": 8,
        "households": 36,
    }
    assert contract.invalid_items == ()
    assert len(contract.required_evidence_ids) == len(
        set(contract.required_evidence_ids)
    )


def test_coverage_contract_contains_every_published_source_id() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_ROOT / "pkg_gameplay_v3")

    contract = build_coverage_contract(package)
    covered = {(item.category, item.source_id) for item in contract.items}

    assert {item.ending_id for item in package.main_endings} <= {
        source_id for category, source_id in covered if category == "main_ending"
    }
    assert {item.sub_ending_id for item in package.sub_endings} <= {
        source_id for category, source_id in covered if category == "sub_ending"
    }
    assert set(package.facts) <= {
        source_id for category, source_id in covered if category == "fact"
    }
    assert {item.archive_id for item in package.archive_investigations} <= {
        source_id for category, source_id in covered if category == "archive"
    }
    assert {item.opportunity_id for item in package.interaction_opportunities} <= {
        source_id
        for category, source_id in covered
        if category == "interaction_opportunity"
    }
    assert {item.npc_id for item in package.npc_profiles} <= {
        source_id for category, source_id in covered if category == "npc"
    }
    assert {item.location_id for item in package.map_locations} <= {
        source_id for category, source_id in covered if category == "map_location"
    }
    assert {item.household_id for item in package.households} <= {
        source_id for category, source_id in covered if category == "household"
    }


def _minimal_contract() -> CoverageContract:
    return CoverageContract(
        counts={"main_endings": 1},
        items=(
            CoverageItem(
                coverage_id="main_ending:ending_01",
                category="main_ending",
                source_id="ending_01",
                required_evidence=("route", "browser"),
            ),
        ),
        invalid_items=(),
    )


def _passing_metadata(**overrides: object) -> dict[str, object]:
    metadata: dict[str, object] = {
        "status": "passed",
        "provider": "openai_compatible",
        "run_id": "run-20260827-full",
        "git_commit": "0123456789abcdef",
        "v3_content_hash": "sha256:v3-test",
        "fake_count": 0,
        "template_fallback_count": 0,
        "silent_fallback_count": 0,
        "partial_commit_count": 0,
        "api_key_leak_count": 0,
        "unattributed_console_errors": 0,
        "failed_calls": 0,
    }
    metadata.update(overrides)
    return metadata


def test_release_report_refuses_missing_fake_or_secret_evidence(tmp_path: Path) -> None:
    artifact = tmp_path / "route.json"
    artifact.write_text('{"ending":"ending_01"}', encoding="utf-8")
    store = EvidenceStore(tmp_path)
    store.record(
        "main_ending:ending_01",
        "route",
        "route.json",
        _passing_metadata(
            provider="fake",
            api_key="sk-forbidden-example-value",
        ),
    )

    report = build_release_report(_minimal_contract(), store)

    assert report.publishable is False
    assert "fake_provider" in report.blockers
    assert "secret_material" in report.blockers
    assert "missing_evidence" in report.blockers
    assert "sk-forbidden-example-value" not in (
        tmp_path / "manifest.jsonl"
    ).read_text(encoding="utf-8")


def test_release_report_refuses_tampered_artifacts_and_mixed_provenance(
    tmp_path: Path,
) -> None:
    route = tmp_path / "route.json"
    browser = tmp_path / "browser.zip"
    route.write_text("route-ok", encoding="utf-8")
    browser.write_bytes(b"browser-ok")
    store = EvidenceStore(tmp_path)
    store.record(
        "main_ending:ending_01",
        "route",
        "route.json",
        _passing_metadata(),
    )
    store.record(
        "main_ending:ending_01",
        "browser",
        "browser.zip",
        _passing_metadata(run_id="different-run"),
    )
    route.write_text("tampered", encoding="utf-8")

    report = build_release_report(_minimal_contract(), store)

    assert report.publishable is False
    assert "artifact_hash_mismatch" in report.blockers
    assert "mixed_run_id" in report.blockers


def test_release_report_accepts_complete_same_run_evidence(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path)
    for evidence_type, content in (("route", b"route"), ("browser", b"browser")):
        artifact = tmp_path / f"{evidence_type}.bin"
        artifact.write_bytes(content)
        store.record(
            "main_ending:ending_01",
            evidence_type,
            artifact.name,
            _passing_metadata(),
        )

    report = build_release_report(_minimal_contract(), store)

    assert report.publishable is True
    assert report.blockers == ()
    assert report.covered_evidence == 2
    assert report.required_evidence == 2


def test_evidence_store_rejects_secret_material_in_artifact_body(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "unsafe.log"
    artifact.write_text("Authorization: Bearer top-secret-token-value", encoding="utf-8")
    store = EvidenceStore(tmp_path)

    try:
        store.record(
            "main_ending:ending_01",
            "route",
            artifact.name,
            _passing_metadata(),
        )
    except SecretMaterialError:
        pass
    else:
        raise AssertionError("secret-bearing artifacts must never enter the manifest")

    assert not (tmp_path / "manifest.jsonl").exists()
