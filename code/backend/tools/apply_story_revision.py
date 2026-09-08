"""Preview a registered copy revision or write a separate candidate package.

--source-root and --output-root name package directories, not loader roots.
Revision schema: schema_version=1, base_package_id, base_package_version,
base_file_hashes={relative_file_path: raw_byte_sha256}, operations=[...]. All
files including the manifest must be hashed; either bare hex or sha256:hex is
accepted. Review conclusions and authority/manifest regeneration are owned by
the controller. A candidate is not a published or loader-validated package.
Operations use category='copy' or independently approved 'story_consistency'.
The revision's optional consistency_authorizations is a list of approval objects
or {approval_id: approval_object}; repeat exact file/pointer/op/before/after
(including field presence). Approval does not override fixed field restrictions.
The CLI requires
node_id/option_id guards whenever the targeted source record provides them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.story_revision import (
    apply_operations, diff_paths, read_json_bytes, read_package, reject_link, validate_relative_file,
    validate_operation_identities,
)


def _checked_root(path: Path) -> Path:
    if ".." in path.parts:
        raise ValueError(f"Parent traversal is not supported: {path}")
    for part in (path, *path.parents):
        reject_link(part)
    return path.resolve()


def _check_output(source: Path, output: Path) -> None:
    _checked_root(output)
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Source and candidate directories must be disjoint")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Candidate directory must be new or empty")


def _hashes(raw_files):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in raw_files.items()}


def build_candidate(source_root: Path, revision_path: Path, output_root: Path,
                    *, write_candidate: bool = False) -> dict:
    """Validate everything before filesystem writes and preserve original bytes."""
    source = _checked_root(Path(source_root))
    output = _checked_root(Path(output_root))
    _check_output(source, output)
    revision = read_json_bytes(Path(revision_path).read_bytes())
    if type(revision.get("schema_version")) is not int or revision["schema_version"] != 1:
        raise ValueError("Unsupported revision schema_version")
    documents, raw_files = read_package(source)
    manifest = documents.get("package_manifest.json", {})
    if (not revision.get("base_package_id") or not revision.get("base_package_version")
            or manifest.get("package_id") != revision["base_package_id"]
            or manifest.get("package_version") != revision["base_package_version"]):
        raise ValueError("Baseline package ID/version mismatch")
    expected = revision.get("base_file_hashes")
    if not isinstance(expected, dict) or set(expected) != set(raw_files):
        raise ValueError("base_file_hashes must cover exactly every source file, including manifest")
    actual = _hashes(raw_files)
    for name, digest in expected.items():
        validate_relative_file(name)
        if not isinstance(digest, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
            raise ValueError(f"Invalid baseline SHA-256 for {name}")
        if digest.removeprefix("sha256:") != actual[name]:
            raise ValueError(f"Baseline hash drift: {name}")
    operations = revision.get("operations")
    candidate = apply_operations(documents, operations,
        consistency_authorizations=revision.get("consistency_authorizations"))
    validate_operation_identities(documents, operations)
    changes = [{"file": name, "pointer": pointer}
               for name in sorted(documents)
               for pointer in sorted(diff_paths(documents[name], candidate[name]))]
    candidate_bytes = {
        name: (json.dumps(candidate[name], ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if name in documents and diff_paths(documents[name], candidate[name]) else raw
        for name, raw in raw_files.items()
    }
    report = dict(mode="candidate" if write_candidate else "dry-run",
                  source_root=str(source), output_root=str(output),
                  baseline_hashes=actual, candidate_hashes=_hashes(candidate_bytes),
                  changes=changes, operations=operations,
                  validation="copy/approved consistency scope and baseline only; runtime/authority validation pending")
    if write_candidate:
        # Re-read the entire source just before writing, catching ordinary drift
        # during preview generation. This does not claim adversarial race safety.
        _, fresh = read_package(source)
        if _hashes(fresh) != actual:
            raise ValueError("Baseline changed during candidate preparation")
        _check_output(source, output)
        output.mkdir(parents=True, exist_ok=True)
        for name, raw in candidate_bytes.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            for parent in (target, *target.parents):
                reject_link(parent)
            # Exclusive creation avoids overwriting a concurrent writer's file.
            with target.open("xb") as stream:
                stream.write(raw)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--write-candidate", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_candidate(args.source_root, args.revision, args.output_root,
                                 write_candidate=args.write_candidate)
    except (ValueError, OSError) as exc:
        print(f"story revision rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
