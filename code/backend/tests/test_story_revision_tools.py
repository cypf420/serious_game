"""Bounded revision tools: real pure operations and CLI runs on temporary packages."""

from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def revision_tools():
    assert importlib.util.find_spec("tools.story_revision") is not None, "revision tools missing"
    return importlib.import_module("tools.story_revision")


def operation(pointer="/decisions/0/prompt", **overrides):
    result = dict(file="decisions.json", pointer=pointer, op="replace",
                  before="old", after="new", category="copy", issue_ids=["I01"])
    result.update(overrides)
    return result


def documents():
    return {"decisions.json": {"decisions": [{"decision_id": "d1", "story_day": 5,
            "prompt": "old", "cost": 2, "options": [{"option_id": "b", "text": "choose",
            "consequence": "old", "effects": {"ledger_deltas": {"budget": [2, 2]}}}]}]}}


def test_exact_patch_is_copy_on_write_and_preserves_effects():
    api = revision_tools()
    docs = documents()
    saved = deepcopy(docs)
    result = api.apply_operations(docs, [operation()])
    assert result["decisions.json"]["decisions"][0]["prompt"] == "new"
    assert docs == saved
    api.assert_allowed_diff(docs["decisions.json"], result["decisions.json"],
                            {"/decisions/0/prompt"})
    result["decisions.json"]["decisions"][0]["options"][0]["effects"].clear()
    assert docs == saved


@pytest.mark.parametrize("changes", [
    {"before": "wrong"}, {"file": "../decisions.json"}, {"file": "/decisions.json"},
    {"file": "C:/decisions.json"}, {"file": "a\\decisions.json"},
    {"file": "./decisions.json"}, {"file": "a//decisions.json"},
    {"file": "decisions.json:stream"}, {"file": "decisions.JSON"},
    {"file": "unknown.json"}, {"op": "move"}, {"pointer": "decisions/0/prompt"},
    {"pointer": "/decisions/-1/prompt"}, {"pointer": "/decisions/01/prompt"},
    {"pointer": "/decisions/2/prompt"}, {"pointer": "/decisions/-/prompt"},
    {"pointer": "/decisions/*/prompt"}, {"pointer": "/decisions/0/bad~2key"},
    {"pointer": ""}, {"pointer": "/decisions/0/cost", "before": 2, "after": 0},
    {"node_id": "wrong"}, {"category": "unreviewed"},
])
def test_rejects_unsafe_or_invalid_operation_without_mutating_input(changes):
    docs = documents()
    saved = deepcopy(docs)
    with pytest.raises(ValueError):
        revision_tools().apply_operations(docs, [operation(**changes)])
    assert docs == saved


def test_duplicate_and_overlapping_operations_rejected():
    api = revision_tools()
    with pytest.raises(ValueError):
        api.apply_operations(documents(), [operation(), operation(before="new")])
    with pytest.raises(ValueError):
        api.apply_operations(documents(), [operation(), operation("/decisions/0",
            before=documents()["decisions.json"]["decisions"][0], after={})])


def test_add_remove_escaped_keys_and_list_append_are_exact():
    api = revision_tools()
    docs = documents()
    docs["decisions.json"]["decisions"][0]["input_schema"] = {
        "labels": {"a/b~c": "old", "": "blank"}}
    ops = [operation("/decisions/0/input_schema/labels/a~1b~0c"),
           operation("/decisions/0/input_schema/labels/", op="remove", before="blank")]
    added = operation("/decisions/0/input_schema/labels/z", op="add", after="last")
    added.pop("before")
    ops.append(added)
    result = api.apply_operations(docs, ops)
    assert result["decisions.json"]["decisions"][0]["input_schema"]["labels"] == {
        "a/b~c": "new", "z": "last"}
    briefing = {"public_briefing.json": {"mission": {"hard_constraints": []}}}
    add = dict(file="public_briefing.json", pointer="/mission/hard_constraints/0",
               op="add", after={"label": "Limit", "detail": "Detail", "value": "90 days"},
               category="copy")
    assert api.apply_operations(briefing, [add])["public_briefing.json"]["mission"][
        "hard_constraints"] == [{"label": "Limit", "detail": "Detail", "value": "90 days"}]


@pytest.mark.parametrize("before,after,allowed", [
    ({"cost": 2}, {"cost": 0}, {"/prompt"}),
    ({"a": {"x": 1}}, {"a": {"x": 2}}, {"/a"}),
    ({"a": []}, {"a": [{"x": 1, "cost": 2}]}, {"/a/0/x"}),
    ({"a": ["x", "y"]}, {"a": ["y"]}, {"/a/0"}),
    ({"a": True}, {"a": 1}, set()),
    ({"a": {}}, {}, set()),
])
def test_diff_rejects_every_unregistered_leaf(before, after, allowed):
    with pytest.raises(ValueError):
        revision_tools().assert_allowed_diff(before, after, allowed)


def test_diff_allows_exact_escaped_leaves_and_empty_container_changes():
    revision_tools().assert_allowed_diff({"a/b": {"~": "old"}, "x": []},
        {"a/b": {"~": "new"}}, {"/a~1b/~0", "/x"})


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_inventory_explicit_nested_public_fields_and_variants(tmp_path):
    docs = documents()
    decision = docs["decisions.json"]["decisions"][0]
    decision.update(title="Title", notes="private", required_flags=["secret"],
        presentation_blocks=[{"block_id": "blk", "text": "Scene", "speaker": "NPC"}],
        text_variants=[{"prompt": "Variant", "option_texts": {"b": "Alt choice"},
                        "option_consequences": {"b": "Alt result"}, "required_flags": ["x"]}])
    docs["public_briefing.json"] = {"mission": {"summary": "Mission", "hard_constraints": [
        {"key": "hidden_key", "label": "Limit", "value": "90 days", "detail": "Detail"}]},
        "dossiers": [{"dossier_id": "dos", "known_points": ["Known"]}],
        "tool_guidance": {"act": {"description": "Tool", "availability_note": "When"}},
        "notes": {"text": "Do not expose"}}
    docs["interaction_opportunities.json"] = {
        "conversation_contexts": {"opp": {"opening_narrative": "Hello", "conversation_goal": "Hidden"}},
        "opportunities": [{"opportunity_id": "opp", "day_min": 2, "day_max": 4,
                           "completion_blocks": [{"text": "Done"}]}]}
    docs["flags.json"] = {"flags": [{"title": "secret title", "text": "secret text"}]}
    for name, doc in docs.items():
        write_json(tmp_path / name, doc)
    records = revision_tools().enumerate_visible_records(tmp_path)
    assert {r["text"] for r in records} == {"Title", "old", "choose", "Scene", "NPC", "Variant",
        "Alt choice", "Alt result", "Mission", "Limit", "90 days", "Detail", "Known", "Tool",
        "When", "Hello", "Done"}
    assert all(set(r) == {"review_id", "file", "pointer", "kind", "day", "node_id", "option_id",
                          "text"} for r in records)
    assert len({r["review_id"] for r in records}) == len(records)
    alt = next(r for r in records if r["text"] == "Alt result")
    assert (alt["day"], alt["node_id"], alt["option_id"]) == (5, "d1", "b")
    hello = next(r for r in records if r["text"] == "Hello")
    assert (hello["day"], hello["node_id"], hello["option_id"]) == (None, "opp", None)
    assert revision_tools().enumerate_visible_records(tmp_path) == records


def cli_fixture(tmp_path):
    source = tmp_path / "source"
    docs = documents()
    docs["package_manifest.json"] = {"package_id": "pkg_test", "package_version": "1"}
    for name, doc in docs.items():
        write_json(source / name, doc)
    revision = {"schema_version": 1, "base_package_id": "pkg_test", "base_package_version": "1",
        "base_file_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in source.iterdir()},
        "operations": [operation(node_id="d1")], "reviews": []}
    registry = tmp_path / "revision.json"
    write_json(registry, revision)
    return source, registry, tmp_path / "candidate", revision


def run_cli(source, registry, output, *extra):
    script = Path(__file__).resolve().parents[1] / "tools" / "apply_story_revision.py"
    assert script.exists(), "revision CLI missing"
    return subprocess.run([sys.executable, str(script), "--source-root", str(source),
        "--revision", str(registry), "--output-root", str(output), *extra],
        capture_output=True, text=True, encoding="utf-8")


def test_cli_dryrun_never_writes_and_candidate_preserves_baseline(tmp_path):
    source, registry, output, revision = cli_fixture(tmp_path)
    baseline = {p.name: p.read_bytes() for p in source.iterdir()}
    preview = run_cli(source, registry, output)
    assert preview.returncode == 0, preview.stderr
    report = json.loads(preview.stdout)
    assert report["mode"] == "dry-run"
    assert report["baseline_hashes"] == revision["base_file_hashes"]
    assert report["changes"][0]["pointer"] == "/decisions/0/prompt"
    assert not output.exists()
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "decisions.json").read_text())["decisions"][0]["prompt"] == "new"
    assert (output / "package_manifest.json").read_bytes() == baseline["package_manifest.json"]
    assert {p.name: p.read_bytes() for p in source.iterdir()} == baseline
    assert run_cli(source, registry, output, "--write-candidate").returncode != 0


@pytest.mark.parametrize("problem", ["drift", "missing_hash", "extra_hash", "wrong_version",
    "same", "child", "parent", "nonempty", "duplicate_json_key", "extra_file"])
def test_cli_rejects_unsafe_candidate_or_incomplete_baseline(tmp_path, problem):
    source, registry, output, revision = cli_fixture(tmp_path)
    if problem == "drift":
        write_json(source / "decisions.json", {"decisions": []})
    elif problem == "missing_hash":
        revision["base_file_hashes"].pop("package_manifest.json")
    elif problem == "extra_hash":
        revision["base_file_hashes"]["absent.json"] = "0" * 64
    elif problem == "wrong_version":
        revision["base_package_version"] = "0"
    elif problem == "same":
        output = source
    elif problem == "child":
        output = source / "candidate"
    elif problem == "parent":
        output = tmp_path
    elif problem == "nonempty":
        write_json(output / "precious.json", {"keep": True})
    elif problem == "extra_file":
        (source / "unexpected.txt").write_text("unhashed", encoding="utf-8")
    write_json(registry, revision)
    if problem == "duplicate_json_key":
        registry.write_text('{"operations": [], "operations": []}', encoding="utf-8")
    saved = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode != 0
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == saved


def test_candidate_hashes_and_copies_nested_non_json_assets(tmp_path):
    source, registry, output, revision = cli_fixture(tmp_path)
    asset = source / "prompt_templates" / "role_turn_system.md"
    asset.parent.mkdir()
    asset.write_bytes(b"# Private system instructions\r\n")
    revision["base_file_hashes"]["prompt_templates/role_turn_system.md"] = (
        "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest())
    write_json(registry, revision)
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode == 0, result.stderr
    assert (output / "prompt_templates" / asset.name).read_bytes() == asset.read_bytes()
    assert all("Private" not in r["text"] for r in revision_tools().enumerate_visible_records(source))


def test_block_and_variant_scene_ids_do_not_replace_owning_node_identity(tmp_path):
    docs = documents()
    decision = docs["decisions.json"]["decisions"][0]
    decision["presentation_blocks"] = [{"block_id": "block", "scene_id": "scene", "text": "old"}]
    decision["text_variants"] = [{"scene_id": "other", "option_consequences": {"b": "old"}}]
    write_json(tmp_path / "decisions.json", docs["decisions.json"])
    records = revision_tools().enumerate_visible_records(tmp_path)
    assert all(r["node_id"] == "d1" for r in records)
    updated = revision_tools().apply_operations(docs, [operation(
        "/decisions/0/text_variants/0/option_consequences/b", node_id="d1", option_id="b")])
    assert updated["decisions.json"]["decisions"][0]["text_variants"][0][
        "option_consequences"]["b"] == "new"


@pytest.mark.parametrize("change", [{"op": []}, {"category": []}, {"pointer": None},
    {"file": None}, {"op": "add"}, {"op": "remove", "before": "wrong"}])
def test_malformed_operation_always_raises_value_error(change):
    with pytest.raises(ValueError):
        revision_tools().apply_operations(documents(), [operation(**change)])


def test_copy_rejects_mechanisms_embedded_in_parent_replacement():
    docs = documents()
    before = docs["decisions.json"]["decisions"][0]["options"][0]
    after = deepcopy(before)
    after["consequence"] = "new"
    after["effects"]["ledger_deltas"]["budget"] = [0, 0]
    with pytest.raises(ValueError):
        revision_tools().apply_operations(docs, [operation(
            "/decisions/0/options/0", before=before, after=after)])


def test_failed_later_operation_leaves_original_and_operation_values_untouched():
    docs = documents()
    ops = [operation(), operation("/decisions/0/options/0/consequence", before="mismatch")]
    snapshot = deepcopy((docs, ops))
    with pytest.raises(ValueError):
        revision_tools().apply_operations(docs, ops)
    assert (docs, ops) == snapshot


def test_public_inventory_excludes_internal_fields_even_with_public_sounding_keys(tmp_path):
    write_json(tmp_path / "governance_config.json", {"action_variants": [{"variant_id": "v",
        "action_id": "a", "name": "Action", "visible_result": "Result",
        "location_labels": {"loc": "Town"}, "hard_outcomes": [{"description": "Internal"}]}],
        "resource_pools": [{"resource_id": "r", "name": "Fund", "allocatable_scope": "npc_demand"}]})
    write_json(tmp_path / "npc_profiles.json", {"npcs": [{"npc_id": "npc", "name": "Person",
        "role_setting": "Public identity\nSecret motive"}]})
    records = revision_tools().enumerate_visible_records(tmp_path)
    assert {r["text"] for r in records} == {"Action", "Result", "Town", "Fund", "Person"}


@pytest.mark.parametrize("side", ["source", "output"])
def test_cli_rejects_directory_symlinks_without_following_them(tmp_path, side):
    source, registry, output, _ = cli_fixture(tmp_path)
    link = tmp_path / "linked"
    target = source if side == "source" else output
    target.mkdir(exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Host cannot create symlinks: {exc}")
    result = run_cli(link if side == "source" else source, registry,
                     link if side == "output" else output, "--write-candidate")
    assert result.returncode != 0
    assert not list(output.iterdir()) if output.exists() else True


def test_cli_accepts_an_existing_empty_candidate_and_requires_arguments(tmp_path):
    source, registry, output, _ = cli_fixture(tmp_path)
    output.mkdir()
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode == 0, result.stderr
    script = Path(__file__).resolve().parents[1] / "tools" / "apply_story_revision.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True)
    assert result.returncode == 2


@pytest.mark.parametrize("guard", ["node_id", "option_id"])
def test_cli_requires_stable_identity_guards_for_indexed_records(tmp_path, guard):
    source, registry, output, revision = cli_fixture(tmp_path)
    revision["operations"] = [operation("/decisions/0/options/0/consequence",
                                       node_id="d1", option_id="b")]
    revision["operations"][0].pop(guard)
    write_json(registry, revision)
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode != 0
    assert guard in result.stderr
    assert not output.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
@pytest.mark.parametrize("side", ["source", "output", "nested_source"])
def test_cli_rejects_windows_junctions(tmp_path, side):
    source, registry, output, _ = cli_fixture(tmp_path)
    target = tmp_path / "junction_target"
    target.mkdir()
    link = source / "linked" if side == "nested_source" else tmp_path / "linked"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True)
    assert result.returncode == 0, result.stderr
    result = run_cli(link if side == "source" else source, registry,
                     link if side == "output" else output, "--write-candidate")
    assert result.returncode != 0
    assert not list(target.iterdir())


def test_nested_visible_fields_cover_facts_endings_and_social_followups(tmp_path):
    docs = {
        "facts.json": {"facts": [{"fact_id": "f", "text": "Fact", "source_label": "Source",
            "use_hint": "Hint", "acquisition_methods": [{"label": "Find", "instructions": "Read",
                                                          "source_id": "private"}]}]},
        "ending_rules.json": {"main_endings": [{"ending_id": "e", "name": "End", "text": "Main"}],
            "sub_endings": [{"sub_ending_id": "s", "main_ending_id": "e", "title": "Sub", "text": "Body"}]},
        "social_rules.json": {"night_agent_scenes": [{"scene_id": "scene", "scene_goal": "Internal",
            "followup_plans": [{"plan_id": "plan", "label": "Meet", "agenda": "Discuss",
                "demands": ["Explain"], "participant_guidance": {"npc": {"text": "Hidden"}}}]}]},
    }
    for name, doc in docs.items():
        write_json(tmp_path / name, doc)
    records = revision_tools().enumerate_visible_records(tmp_path)
    assert {r["text"] for r in records} == {"Fact", "Source", "Hint", "Find", "Read", "End", "Main",
                                           "Sub", "Body", "Meet", "Discuss", "Explain"}
    assert next(r for r in records if r["text"] == "Body")["node_id"] == "s"


def test_inventory_record_id_is_stable_when_decisions_reorder(tmp_path):
    docs = documents()["decisions.json"]
    other = deepcopy(docs["decisions"][0])
    other["decision_id"] = "d2"
    docs["decisions"].append(other)
    path = tmp_path / "decisions.json"
    write_json(path, docs)
    before = revision_tools().enumerate_visible_records(tmp_path)
    docs["decisions"].reverse()
    write_json(path, docs)
    after = revision_tools().enumerate_visible_records(tmp_path)
    assert {r["review_id"] for r in before} == {r["review_id"] for r in after}
    assert before[0]["pointer"] == after[0]["pointer"]
    assert before[0]["node_id"] != after[0]["node_id"]


def consistency_docs():
    return {
        "decisions.json": {"decisions": [
            {"decision_id": "dp3_08", "story_day": 43, "options": []},
            {"decision_id": "dp4_07", "story_day": 56, "options": [
                {"option_id": "a", "effects": {"state_assignments": {},
                 "metric_deltas": {"trust": [1, 1]}, "ledger_deltas": {"budget": [2, 2]}}}]}]},
        "story_beats.json": {"beats": [
            {"beat_id": f"beat{d}", "story_day": d, "decision_ids": ["dp3_08"] if d == 43 else [],
             "opening_blocks": [{"block_id": f"b{d}", "kind": "narration", "text": "old"}]}
            for d in (12, 43, 44, 56, 58, 69)]},
        "story_acceptance_matrix.json": {"days": [
            {"node_id": "beat12", "story_day": 12, "opening_block_ids": ["b12"],
             "introduced_npc_ids": [], "npc_discovery_transitions": []}]},
        "package_manifest.json": {"package_id": "pkg_test", "package_version": "1",
                                  "notes": "old", "gameplay_schema_version": 4},
    }


def consistency_op(file, pointer, before, after, **kwargs):
    return dict(file=file, pointer=pointer, op="replace", before=before, after=after,
                category="story_consistency", **kwargs)


def approval(op):
    return {k: deepcopy(op[k]) for k in ("file", "pointer", "op", "before", "after") if k in op}


def apply_approved(docs, ops, approvals=None):
    return revision_tools().apply_operations(docs, ops, consistency_authorizations=(
        [approval(op) for op in ops] if approvals is None else approvals))


def test_copy_cannot_swap_dict_and_list_with_identical_leaf_paths():
    docs = documents()
    docs["decisions.json"]["decisions"][0]["input_schema"] = {"labels": {"0": "old"}}
    op = operation("/decisions/0/input_schema/labels", before={"0": "old"}, after=["new"])
    with pytest.raises(ValueError):
        revision_tools().apply_operations(docs, [op])


def test_diff_reports_container_type_change_at_parent_even_when_leaves_identical():
    api = revision_tools()
    with pytest.raises(ValueError):
        api.assert_allowed_diff({"labels": {"0": "x"}}, {"labels": ["x"]}, {"/labels/0"})
    api.assert_allowed_diff({"labels": {"0": "x"}}, {"labels": ["x"]},
                            {"/labels", "/labels/0"})


@pytest.mark.parametrize("mapping", [False, True])
def test_reviewed_chronology_operations_accept_exact_separate_approvals(mapping):
    docs = consistency_docs()
    ops = [consistency_op("decisions.json", "/decisions/0/story_day", 43, 44, node_id="dp3_08"),
           consistency_op("story_beats.json", "/beats/1/decision_ids", ["dp3_08"], [], node_id="beat43"),
           consistency_op("story_beats.json", "/beats/2/decision_ids", [], ["dp3_08"], node_id="beat44")]
    approvals = [approval(op) for op in ops]
    if mapping:
        approvals = {f"review-{i}": row for i, row in enumerate(approvals)}
    saved = deepcopy(docs)
    result = apply_approved(docs, ops, approvals)
    assert result["decisions.json"]["decisions"][0]["story_day"] == 44
    assert result["story_beats.json"]["beats"][2]["decision_ids"] == ["dp3_08"]
    assert docs == saved


@pytest.mark.parametrize("mismatch", ["absent", "file", "pointer", "op", "before", "after", "duplicate"])
def test_consistency_approval_is_exact_and_separate(mismatch):
    docs = consistency_docs()
    op = consistency_op("decisions.json", "/decisions/0/story_day", 43, 44, node_id="dp3_08")
    auth = approval(op)
    approvals = [auth]
    if mismatch == "absent":
        approvals = []
    elif mismatch == "duplicate":
        approvals.append(deepcopy(auth))
    else:
        auth[mismatch] = {"file": "other.json", "pointer": "/decisions/1/story_day",
            "op": "add", "before": 42, "after": 45}[mismatch]
    with pytest.raises(ValueError):
        apply_approved(docs, [op], approvals)


def test_reviewed_opening_additions_guards_handoff_and_refusal_variant():
    docs = consistency_docs()
    block = {"block_id": "new12", "kind": "narration", "text": "deferred",
             "required_flags": ["审慎缓签"], "scene_id": "C06_S02"}
    blocks = deepcopy(docs["story_beats.json"]["beats"][0]["opening_blocks"])
    blocks[0]["forbidden_flags"] = ["审慎缓签"]
    blocks.append(block)
    variant = {"variant_id": "press_request_after_clearance", "required_flags": ["门诊楼前被清场"],
               "option_consequences": {"e": "He refused the request."}}
    ops = [consistency_op("story_beats.json", "/beats/0/opening_blocks",
        docs["story_beats.json"]["beats"][0]["opening_blocks"], blocks, node_id="beat12"),
        dict(file="decisions.json", pointer="/decisions/1/options/0/required_state_values", op="add",
            after={"lead_roster_disposition": "己方封存"}, category="story_consistency", node_id="dp4_07", option_id="a"),
        dict(file="decisions.json", pointer="/decisions/1/options/0/effects/state_assignments/lead_roster_disposition",
            op="add", after="交给记者", category="story_consistency", node_id="dp4_07", option_id="a"),
        dict(file="decisions.json", pointer="/decisions/1/text_variants", op="add", after=[variant],
            category="story_consistency", node_id="dp4_07"),
        consistency_op("story_acceptance_matrix.json", "/days/0/opening_block_ids", ["b12"],
                       ["b12", "new12"], node_id="beat12")]
    result = apply_approved(docs, ops)
    assert result["story_beats.json"]["beats"][0]["opening_blocks"] == blocks
    option = result["decisions.json"]["decisions"][1]["options"][0]
    assert option["effects"]["state_assignments"] == {"lead_roster_disposition": "交给记者"}
    assert option["effects"]["ledger_deltas"] == {"budget": [2, 2]}
    assert result["decisions.json"]["decisions"][1]["text_variants"] == [variant]


@pytest.mark.parametrize("target,before,after", [
    ("/decisions/1/options/0/effects/ledger_deltas/budget", [2, 2], [0, 0]),
    ("/decisions/1/options/0/effects/metric_deltas/trust", [1, 1], [50, 50]),
    ("/decisions/0/decision_id", "dp3_08", "new_id"),
    ("/decisions/0/story_day", 43, 45),
    ("/decisions/1/story_day", 56, 44),
])
def test_authorization_never_overrides_hard_scope(target, before, after):
    docs = consistency_docs()
    op = consistency_op("decisions.json", target, before, after,
                        node_id="dp3_08" if target.startswith("/decisions/0") else "dp4_07")
    with pytest.raises(ValueError):
        apply_approved(docs, [op])


@pytest.mark.parametrize("field,before,after", [
    ("condition", {"axis": "A"}, {"axis": "B"}), ("order", 1, 0),
    ("free_axis", "T", "A"), ("ending_id", "e", "new"),
])
def test_ending_mechanisms_and_ids_cannot_be_authorized(field, before, after):
    docs = {"ending_rules.json": {"main_endings": [{"ending_id": "e", field: before}]}}
    op = consistency_op("ending_rules.json", f"/main_endings/0/{field}", before, after, node_id="e")
    with pytest.raises(ValueError):
        apply_approved(docs, [op])


def test_metadata_approvals_preserve_package_id_and_schema():
    docs = consistency_docs()
    for field, value in (("package_version", "3.5.14-story-integrity"), ("notes", "Reviewed")):
        op = consistency_op("package_manifest.json", f"/{field}", docs["package_manifest.json"][field], value)
        assert apply_approved(docs, [op])["package_manifest.json"][field] == value
    for field, after in (("package_id", "other"), ("gameplay_schema_version", 3)):
        op = consistency_op("package_manifest.json", f"/{field}", docs["package_manifest.json"][field], after)
        with pytest.raises(ValueError):
            apply_approved(docs, [op])


def test_cli_consumes_consistency_authorizations_and_still_rejects_drift(tmp_path):
    source, registry, output, revision = cli_fixture(tmp_path)
    manifest = json.loads((source / "package_manifest.json").read_text())
    op = consistency_op("package_manifest.json", "/package_version", manifest["package_version"], "2")
    revision["operations"] = [op]
    revision["consistency_authorizations"] = {"version-review": approval(op)}
    write_json(registry, revision)
    result = run_cli(source, registry, output, "--write-candidate")
    assert result.returncode == 0, result.stderr
    assert json.loads((output / "package_manifest.json").read_text())["package_version"] == "2"
    (source / "package_manifest.json").write_text('{"package_id":"pkg_test","package_version":"1"}')
    other = tmp_path / "drift-candidate"
    result = run_cli(source, registry, other, "--write-candidate")
    assert result.returncode != 0
    assert not other.exists()


@pytest.mark.parametrize("payload", [
    {"block_id": "b56", "kind": "narration", "text": "Duplicate elsewhere"},
    {"block_id": "new", "kind": "narration", "text": "Mechanism",
     "effects": {"ledger_deltas": {"budget": [999, 999]}}},
])
def test_opening_approval_cannot_duplicate_global_ids_or_add_effects(payload):
    docs = consistency_docs()
    old = docs["story_beats.json"]["beats"][0]["opening_blocks"]
    op = consistency_op("story_beats.json", "/beats/0/opening_blocks", old,
                        [*deepcopy(old), payload], node_id="beat12")
    with pytest.raises(ValueError):
        apply_approved(docs, [op])


def test_opening_approval_cannot_replace_existing_speaker_with_a_container():
    docs = consistency_docs()
    old = docs["story_beats.json"]["beats"][0]["opening_blocks"]
    old[0]["speaker"] = "Person"
    new = deepcopy(old)
    new[0]["speaker"] = {"internal_id": "invalid"}
    op = consistency_op("story_beats.json", "/beats/0/opening_blocks", old, new, node_id="beat12")
    with pytest.raises(ValueError):
        apply_approved(docs, [op])


def test_refusal_variant_cannot_duplicate_an_existing_variant_id():
    docs = consistency_docs()
    variant = {"variant_id": "press_request_after_clearance", "required_flags": ["门诊楼前被清场"],
               "option_consequences": {"e": "No"}}
    docs["decisions.json"]["decisions"][1]["text_variants"] = [variant]
    op = consistency_op("decisions.json", "/decisions/1/text_variants", [variant],
                        [variant, variant], node_id="dp4_07")
    with pytest.raises(ValueError):
        apply_approved(docs, [op])


@pytest.mark.parametrize("day_index", [0, 3, 4, 5])
def test_explicit_guard_additions_are_scoped_to_the_four_reviewed_beats(day_index):
    docs = consistency_docs()
    op = dict(file="story_beats.json", pointer=f"/beats/{day_index}/opening_blocks/0/required_flags",
              op="add", after=["reviewed_flag"], category="story_consistency",
              node_id=docs["story_beats.json"]["beats"][day_index]["beat_id"])
    result = apply_approved(docs, [op])
    assert result["story_beats.json"]["beats"][day_index]["opening_blocks"][0]["required_flags"] == ["reviewed_flag"]


@pytest.mark.parametrize("mutation", ["id", "schema", "budget"])
def test_parent_replacement_cannot_smuggle_hard_banned_fields(mutation):
    docs = consistency_docs()
    if mutation == "budget":
        file, pointer = "decisions.json", "/decisions/1/options/0/effects"
        old = docs[file]["decisions"][1]["options"][0]["effects"]
        new = deepcopy(old)
        new["state_assignments"]["lead_roster_disposition"] = "交给记者"
        new["ledger_deltas"]["budget"] = [0, 0]
        guards = {"node_id": "dp4_07", "option_id": "a"}
    else:
        file, pointer = "package_manifest.json", "/metadata"
        old = docs[file].copy()
        docs[file]["metadata"] = old
        new = {**old, "package_version": "2"}
        new["package_id" if mutation == "id" else "gameplay_schema_version"] = "changed" if mutation == "id" else 3
        guards = {}
    with pytest.raises(ValueError):
        apply_approved(docs, [consistency_op(file, pointer, old, new, **guards)])


def test_matrix_introductions_must_match_visible_text_and_preserve_nonmentioned_transitions():
    docs = consistency_docs()
    docs["npc_profiles.json"] = {"npcs": [{"npc_id": "npc_p", "name": "Person"}]}
    docs["story_beats.json"]["beats"][0]["opening_blocks"][0]["text"] = "Person arrives."
    row = docs["story_acceptance_matrix.json"]["days"][0]
    row["npc_discovery_transitions"] = [{"npc_id": "npc_existing", "state": "known"}]
    ops = [consistency_op("story_acceptance_matrix.json", "/days/0/introduced_npc_ids", [],
                          ["npc_p"], node_id="beat12"),
           consistency_op("story_acceptance_matrix.json", "/days/0/npc_discovery_transitions",
                          row["npc_discovery_transitions"], [
                              {"npc_id": "npc_p", "state": "mentioned"},
                              {"npc_id": "npc_existing", "state": "known"}], node_id="beat12")]
    result = apply_approved(docs, ops)
    assert result["story_acceptance_matrix.json"]["days"][0]["introduced_npc_ids"] == ["npc_p"]
    ops[1]["after"][0]["state"] = "known"
    with pytest.raises(ValueError):
        apply_approved(docs, ops)


def test_reviewed_dp6_03_c_removes_only_original_resurrection_assignment():
    docs = {"decisions.json": {"decisions": [{"decision_id": "dp6_03", "story_day": 78,
        "options": [{"option_id": "c", "effects": {"metric_deltas": {"trust": [1, 2]},
            "ledger_deltas": {"budget": [-2, -2]}, "open_flags": ["kept"],
            "state_assignments": {"lead_roster_disposition": "己方封存", "other": "kept"}}}]}]}}
    op = dict(file="decisions.json", pointer="/decisions/0/options/0/effects/state_assignments/lead_roster_disposition",
              op="remove", before="己方封存", category="story_consistency", node_id="dp6_03", option_id="c")
    result = apply_approved(docs, [op])
    expected = deepcopy(docs)
    del expected["decisions.json"]["decisions"][0]["options"][0]["effects"]["state_assignments"]["lead_roster_disposition"]
    assert result == expected
    for change in ({"op": "replace", "after": "交给记者"}, {"option_id": "b"}, {"before": "交给记者"}):
        with pytest.raises(ValueError):
            apply_approved(docs, [{**op, **change}])
