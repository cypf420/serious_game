from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = REPO_ROOT / "code" / "backend" / "content" / "packages"
EXPECTED_IDENTITIES = {
    "pkg_backend_dev_v1": "sha256:4ae93f107ad2e3136fc73fc54cb356d707fac7fccfbe3de4655585f367939c17",
    "pkg_gameplay_v2": "sha256:1c45123f269f6ebd4ed2a0a8c13cba3b6d15b175100705ecaede1c67fc64a421",
    "pkg_gameplay_v3": "sha256:259837279fb72772739b54638f35d014ac08bb5556bbc2e5feb0fbde0ca700b7",
}


def _git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True
    ).stdout


def _materialize_package_from_git_blobs(
    destination: Path, package_id: str, *, autocrlf: bool
) -> Path:
    relative_root = Path("code/backend/content/packages") / package_id
    tracked = _git("ls-tree", "-r", "--name-only", "HEAD", relative_root.as_posix())
    for raw_name in tracked.decode("utf-8").splitlines():
        relative = Path(raw_name).relative_to(relative_root)
        data = _git("show", f"HEAD:{raw_name}")
        if autocrlf and relative.suffix.lower() in {".json", ".md"}:
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        target = destination / package_id / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return destination / package_id


@pytest.mark.parametrize("autocrlf", [False, True])
@pytest.mark.parametrize("package_id", sorted(EXPECTED_IDENTITIES))
def test_git_blob_materialization_loads_with_stable_legacy_identity(
    tmp_path: Path, package_id: str, autocrlf: bool
) -> None:
    package_dir = _materialize_package_from_git_blobs(
        tmp_path, package_id, autocrlf=autocrlf
    )

    package = FileScriptPackageLoader().load(package_dir)

    assert package.content_hash == EXPECTED_IDENTITIES[package_id]
    expected_source_hash = json.loads(
        (PACKAGE_ROOT / package_id / "package_manifest.json").read_text(encoding="utf-8")
    )["source_sha256"]
    assert package.source_sha256 == expected_source_hash


def test_v2_legacy_content_hash_baseline_is_unchanged() -> None:
    assert (
        FileScriptPackageLoader.compute_content_hash(PACKAGE_ROOT / "pkg_gameplay_v2")
        == EXPECTED_IDENTITIES["pkg_gameplay_v2"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("package_id", "pkg_unknown"),
        ("content_hash", "sha256:" + "0" * 64),
    ],
)
def test_portable_validation_rejects_packages_outside_the_legacy_whitelist(
    tmp_path: Path, field: str, value: str
) -> None:
    package_dir = _materialize_package_from_git_blobs(
        tmp_path, "pkg_gameplay_v3", autocrlf=True
    )
    manifest_path = package_dir / "package_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ContentValidationError):
        FileScriptPackageLoader().load(package_dir)


@pytest.mark.parametrize("change", ["text", "binary"])
def test_portable_validation_rejects_content_changes(tmp_path: Path, change: str) -> None:
    package_dir = _materialize_package_from_git_blobs(
        tmp_path, "pkg_gameplay_v3", autocrlf=True
    )
    if change == "text":
        path = package_dir / "story_calendar.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["_tampered"] = True
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    else:
        (package_dir / "tampered.bin").write_bytes(b"\x00\r\n\xff")

    with pytest.raises(ContentValidationError):
        FileScriptPackageLoader().load(package_dir)
