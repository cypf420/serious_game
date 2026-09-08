"""Pure, fail-closed helpers for the T1 story revision sidecar.

The visible-field table is a schema allowlist, not a string-key heuristic. It
enumerates *registered* public text, including conditional variants, without
claiming that each record is reachable or editorially reviewed. Runtime Python
templates are outside enumerate_visible_records(package_dir)'s package scope.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re


def _fields(scope: str, names: str) -> tuple[str, ...]:
    return tuple(f"{scope}/{name}" for name in names.split())


# '*' is used only by this internal schema table; operation pointers are exact.
VISIBLE_FIELDS = {
    "decisions.json": (
        *_fields("/decisions/*", "title prompt input_schema/unit input_schema/labels/*"),
        *_fields("/decisions/*/options/*", "text consequence unavailable_reason "
                 "unlock_requirements/*/archive_name unlock_requirements/*/reason"),
        *_fields("/decisions/*/presentation_blocks/*", "text speaker"),
        *_fields("/decisions/*/followup_blocks/*", "text speaker"),
        *_fields("/decisions/*/text_variants/*", "title prompt option_texts/* option_consequences/*"),
    ),
    "story_beats.json": (
        "/beats/*/title", *_fields("/beats/*/opening_blocks/*", "text speaker"),
        *_fields("/beats/*/night_blocks/*", "text speaker"),
    ),
    "ending_rules.json": (
        *_fields("/main_endings/*", "name text"),
        *_fields("/sub_endings/*", "title text"), "/appendices/*/title",
    ),
    "event_rules.json": _fields("/fixed_events/*", "title visible_summary"),
    "facts.json": _fields("/facts/*", "title text source_label use_hint "
                          "acquisition_methods/*/label acquisition_methods/*/instructions"),
    "interaction_opportunities.json": (
        "/conversation_contexts/*/opening_narrative",
        "/opportunities/*/opening_narrative",
        *_fields("/opportunities/*/completion_blocks/*", "text speaker"),
    ),
    "public_briefing.json": (
        *_fields("/mission", "title summary hard_constraints/*/label "
                 "hard_constraints/*/value hard_constraints/*/detail"),
        *_fields("/authorities/*", "name description limitation"),
        *_fields("/dossiers/*", "title summary known_points/*"),
        *_fields("/tool_categories/*", "name description"),
        *_fields("/tool_guidance/*", "description availability_note"),
        *_fields("/compensation_policy", "title status numeric_guardrail principles/* "
                 "covered_items/* authority_boundaries/* funding/*/label funding/*/value"),
    ),
    "archive_investigations.json": _fields("/archives/*", "title content strategic_uses/*"),
    "origins.json": _fields("/origins/*", "title description"),
    "map_locations.json": _fields("/locations/*", "name description"),
    "action_rules.json": ("/actions/*/name",),
    "resource_actions.json": _fields("/actions/*", "narrative unavailable_reason"),
    "npc_demands.json": _fields("/demands/*", "title description legal_disposition"),
    # role_setting contains private motives after its public identity fragment.
    # Do not expose that entire field as public copy.
    "npc_profiles.json": ("/npcs/*/name",),
    "household_signatories.json": ("/signatories/*/name",),
    "households.json": _fields("/households/*", "residential_structure other_land_note "
                               "attachments_profile grave_or_shrine_profile "
                               "resettlement_preference ownership_status"),
    "numbers.json": ("/visible_metric_bands/*/*/label",),
    "package_manifest.json": ("/title",),
    "governance_config.json": (
        *_fields("/base_actions/*", "name description"),
        *_fields("/action_variants/*", "name description unavailable_reason visible_result location_labels/*"),
        *_fields("/initial_documents/*", "title content"),
        *_fields("/resource_pools/*", "name attributes/unit"),
    ),
    "social_rules.json": (
        *_fields("/npc_relationships/*", "suspected_reason confirmed_reason"),
        "/relationship_subnetworks/*/name",
        *_fields("/night_agent_actions/*", "name description public_direction_summary"),
        "/night_agent_scenes/*/public_direction_summary",
        *_fields("/night_agent_scenes/*/followup_plans/*", "label agenda demands/*"),
    ),
    # These are validation/lookup data, not public prose. Listing them explicitly
    # records that their strings were considered rather than silently forgotten.
    "flags.json": (), "content_catalog.json": (), "story_calendar.json": (),
    "acceptance_route_profiles.json": (), "story_acceptance_matrix.json": (),
}

_IDENTITY_KEYS = (
    "decision_id", "beat_id", "node_id", "sub_ending_id", "ending_id", "event_id", "fact_id",
    "opportunity_id", "archive_id", "origin_id", "location_id", "variant_id",
    "action_id", "demand_id", "household_id", "npc_id", "document_id", "resource_id",
    "dossier_id", "appendix_id", "plan_id", "scene_id", "edge_id", "subnetwork_id",
)
_MISSING = object()


def validate_relative_file(name: str) -> str:
    """Require one canonical relative POSIX file path, also safe on Windows."""
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError(f"Unsafe JSON file path: {name!r}")
    parts = name.split("/")
    if (PurePosixPath(name).is_absolute()
            or any(p in {"", ".", ".."} or p.endswith((" ", "."))
                   or re.search(r'[<>:"|?*\x00-\x1f]', p)
                   or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
                   for p in parts)):
        raise ValueError(f"Unsafe JSON file path: {name!r}")
    return name


def validate_file_name(name: str) -> str:
    validate_relative_file(name)
    if not name.endswith(".json"):
        raise ValueError(f"Operations require a JSON file: {name!r}")
    return name


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _tokens(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError(f"Expected a non-root JSON Pointer: {pointer!r}")
    if re.search(r"~(?![01])", pointer):
        raise ValueError(f"Invalid JSON Pointer escape: {pointer!r}")
    tokens = tuple(t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/"))
    if any("*" in t for t in tokens):
        raise ValueError("Wildcard operation paths are not supported")
    return tokens


def _index(token: str, size: int, *, add: bool = False) -> int:
    if not re.fullmatch(r"0|[1-9][0-9]*", token):
        raise ValueError(f"Array index must be explicit and canonical: {token!r}")
    index = int(token)
    if index >= size + int(add):
        raise ValueError(f"Array index out of bounds: {index}")
    return index


def _child(value, token):
    if isinstance(value, dict):
        if token not in value:
            raise ValueError(f"JSON Pointer does not exist: {token!r}")
        return value[token]
    if isinstance(value, list):
        return value[_index(token, len(value))]
    raise ValueError("JSON Pointer traverses a scalar")


def _equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def _leaves(value, pointer):
    if isinstance(value, (dict, list)) and value:
        rows = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in rows:
            yield from _leaves(child, f"{pointer}/{_escape(str(key))}")
    else:
        yield pointer, value


def diff_paths(before, after, pointer="") -> set[str]:
    """Return changed leaves; missing empty containers are leaves too."""
    if _equal(before, after):
        return set()
    if isinstance(before, dict) and isinstance(after, dict):
        result = set()
        for key in before.keys() | after.keys():
            result |= diff_paths(before.get(key, _MISSING), after.get(key, _MISSING),
                                 f"{pointer}/{_escape(key)}")
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = set()
        for i in range(max(len(before), len(after))):
            result |= diff_paths(before[i] if i < len(before) else _MISSING,
                                 after[i] if i < len(after) else _MISSING, f"{pointer}/{i}")
        return result
    # A type replacement must account for both the old and new subtrees.
    result = {p for value in (before, after) if value is not _MISSING
              for p, _ in _leaves(value, pointer)}
    if before is not _MISSING and after is not _MISSING and type(before) is not type(after):
        result.add(pointer)
    return result


def assert_allowed_diff(before: dict, after: dict, allowed_paths: set[str]) -> None:
    """Authorize exact changed leaves, never the descendants of a prefix."""
    for path in allowed_paths:
        _tokens(path)
    denied = diff_paths(before, after) - allowed_paths
    if denied:
        raise ValueError(f"Unregistered difference paths: {sorted(denied)}")


def _public_path(file, pointer):
    actual = _tokens(pointer)
    for pattern in VISIBLE_FIELDS.get(file, ()):
        expected = pattern[1:].split("/")
        if len(expected) == len(actual) and all(e == "*" or e == a
                                                for e, a in zip(expected, actual)):
            return True
    return False


def _context(ancestors):
    day = node_id = option_id = None
    for value in ancestors:
        if isinstance(value, dict):
            if type(value.get("story_day")) is int:
                day = value["story_day"]
            if "option_id" in value:
                option_id = value["option_id"]
            # A block inherits its owning decision/beat, not an unrelated speaker.
            if node_id is None:
                for key in _IDENTITY_KEYS:
                    if key in value:
                        node_id = value[key]
                        break
    return day, node_id, option_id


def validate_operation_identities(documents: dict[str, dict], operations: list[dict]) -> None:
    """CLI guard: require explicit stable IDs wherever the source provides them.

    Call after apply_operations has validated the operation structure. Full
    baseline hashes pin array ordering; these guards independently bind the
    author's intended entity rather than trusting a numeric position alone.
    """
    for op in operations:
        tokens = _tokens(op["pointer"])
        value = documents[op["file"]]
        ancestors = [value]
        for token in tokens[:-1]:
            value = _child(value, token)
            ancestors.append(value)
        _, node_id, option_id = _context(ancestors)
        if len(tokens) >= 2 and tokens[-2] in {"option_texts", "option_consequences"}:
            option_id = tokens[-1]
        if tokens[0] == "conversation_contexts" and len(tokens) > 1:
            node_id = tokens[1]
        for key, expected in (("node_id", node_id), ("option_id", option_id)):
            if expected is not None and op.get(key) != expected:
                raise ValueError(f"Explicit {key} guard required at {op['file']}:{op['pointer']}")


def _approval_index(authorizations):
    if authorizations is None:
        return {}
    if isinstance(authorizations, dict):
        authorizations = list(authorizations.values())
    if not isinstance(authorizations, list):
        raise ValueError("consistency_authorizations must be a list or approval-ID map")
    result = {}
    for entry in authorizations:
        if not isinstance(entry, dict):
            raise ValueError("Consistency approval must be an object")
        file = validate_file_name(entry.get("file"))
        pointer = entry.get("pointer")
        _tokens(pointer)
        if entry.get("op") not in ("replace", "add", "remove"):
            raise ValueError("Invalid approval operation")
        if ((entry["op"] != "add" and "before" not in entry)
                or (entry["op"] != "remove" and "after" not in entry)):
            raise ValueError("Approval is missing before/after")
        if (file, pointer) in result:
            raise ValueError("Duplicate consistency approval path")
        result[file, pointer] = entry
    return result


def _get(document, tokens, default=_MISSING):
    try:
        for token in tokens:
            document = _child(document, token)
        return document
    except ValueError:
        return default


_MATRIX_DISPLAY = {
    "opening_block_ids", "required_story_entry_ids", "decision_ids", "prerequisite_narrative_ids",
    "decision_display_node_ids", "decision_presentation_order", "outcome_transition_ids",
    "scene_ids", "visible_speakers",
}

# Additional source-backed player blocks authorized in the 2026-09-08 repair.
# A stable node + exact block-ID allowlist, never an arbitrary path prefix.
_SOURCE_BLOCK_SCOPES = {
    ('decisions.json', 'dp1_01_taskforce_faction_map', 'followup_blocks'):
        {'source_restore_l2554', 'source_restore_l2558', 'source_restore_l2560'},
    ('decisions.json', 'dp3_04', 'presentation_blocks'):
        {f'source_restore_l{n}' for n in range(5004, 5025, 2)},
    ('decisions.json', 'dp4_10', 'presentation_blocks'): set(),
    ('story_beats.json', 17, 'opening_blocks'): {'source_restore_l3541'},
    ('story_beats.json', 59, 'opening_blocks'):
        {'source_restore_l7651', 'source_restore_l7653', 'source_restore_l7655'},
    ('story_beats.json', 61, 'opening_blocks'): {'d61_roster_recheck', 'd61_named_worklist'},
}
_SOURCE_BLOCK_PRESENTATION = {
    **{f'source_restore_l{n}': ('C01_S06', 'followup', 'dialogue', '吴秀英') for n in (2554, 2558)},
    'source_restore_l2560': ('C01_S06', 'followup', 'narration', None),
    'source_restore_l3541': ('C02_S01', 'scene', 'narration', None),
    **{f'source_restore_l{n}': ('C01_S02', 'scene', 'dialogue', '罗健') for n in (5008, 5012, 5016, 5020, 5024)},
    **{f'source_restore_l{n}': ('C01_S02', 'scene', 'narration', None) for n in (5004, 5006, 5010, 5014, 5018, 5022)},
    **{f'source_restore_l{n}': ('C04_S07', 'scene', 'narration', None) for n in (7651, 7653, 7655)},
    'd61_roster_recheck': ('C05_S01', 'scene', 'narration', None),
    'd61_named_worklist': ('C05_S01', 'npc', 'dialogue', '郑向东'),
}


def _consistency_scope(documents, op):
    """Return a bounded validation subtree, never an arbitrary approved prefix."""
    file, tokens = op["file"], _tokens(op["pointer"])
    if file == "package_manifest.json" and tokens in (("package_version",), ("notes",), ("content_hash",)):
        return file, tokens, "metadata"
    if file == 'package_manifest.json' and tokens in (('source_version',),('source_sha256',)):
        return file, tokens, 'authored_source_metadata'
    if file == 'content_catalog.json' and tokens == ('source_sha256',):
        return file, tokens, 'authored_source_metadata'
    if file == 'acceptance_route_profiles.json' and tokens == ('decision_policy_templates', 'unknown', 'dp6_06'):
        return file, tokens, 'return_witness'
    if (file, tokens) in {('archive_investigations.json', ('archives',)), ('facts.json', ('facts',))}:
        return file, tokens, 'author_revision'
    if len(tokens) < 3:
        raise ValueError("Consistency operation is outside the fixed story scope")
    row = _get(documents[file], tokens[:2])
    if not isinstance(row, dict):
        raise ValueError("Consistency operation must target an existing stable record")
    source_identity = row.get('decision_id') if file == 'decisions.json' else row.get('story_day')
    if (file == 'decisions.json' and source_identity == 'dp4_10' and len(tokens)>=5
            and tokens[2]=='options' and _get(documents[file],tokens[:4]).get('option_id')=='d'
            and tokens[4] in {'effects','conditional_effects'}):
        return file, tokens[:5], 'author_revision'
    if file == 'decisions.json' and source_identity in {'dp3_06','dp4_06'}:
        if tokens[2] in {'presentation_blocks','text_variants'}:
            return file, tokens[:3], 'author_revision'
        if (source_identity == 'dp4_06' and len(tokens) >= 5 and tokens[2] == 'options'
                and _get(documents[file], tokens[:4]).get('option_id') == 'a'
                and tokens[4] in {'effects','conditional_effects','required_fact_ids','unlock_requirements'}):
            return file, tokens[:5], 'author_revision'
    if file == 'story_beats.json' and source_identity in {38,53} and tokens[2] == 'opening_blocks':
        return file, tokens[:3], 'author_revision'
    if (file, source_identity, tokens[2]) in _SOURCE_BLOCK_SCOPES:
        return file, tokens[:3], 'source_blocks'
    if file == "decisions.json" and tokens[0] == "decisions":
        if row.get("decision_id") == "dp3_08" and tokens[2:] == ("story_day",):
            return file, tokens, "day"
        if (row.get("decision_id") == "dp6_03" and len(tokens) == 7
                and tokens[2] == "options"
                and tokens[4:] == ("effects", "state_assignments", "lead_roster_disposition")
                and op["op"] == "remove"):
            option = _get(documents[file], tokens[:4])
            if isinstance(option, dict) and option.get("option_id") == "c":
                return file, tokens[:6], "no_resurrection"
        if row.get("decision_id") == "dp4_07":
            if tokens[2] == "text_variants":
                return file, tokens[:3], "refusal"
            if len(tokens) >= 5 and tokens[2] == "options":
                option = _get(documents[file], tokens[:4])
                if isinstance(option, dict) and option.get("option_id") == "a":
                    if tokens[4] == "required_state_values":
                        return file, tokens[:5], "possession"
                    if tokens[4:6] == ("effects", "state_assignments"):
                        return file, tokens[:6], "handoff"
    if file == "story_beats.json" and tokens[0] == "beats":
        day = row.get("story_day")
        if day in (43, 44) and tokens[2] == "decision_ids":
            return file, tokens[:3], "queue"
        if day in (12, 56, 58, 69) and tokens[2] == "opening_blocks":
            return file, tokens[:3], "opening"
    if file == "story_acceptance_matrix.json" and tokens[0] == "days":
        if row.get('story_day') == 38 and tokens[2] == 'archive_unlock_ids':
            return file, tokens[:3], 'author_revision'
        if (tokens[2] in {"introduced_npc_ids", "npc_discovery_transitions"}
                or row.get("story_day") in (2, 12, 17, 34, 38, 43, 44, 53, 56, 58, 59, 61, 69) and tokens[2] in _MATRIX_DISPLAY):
            return file, tokens[:3], "matrix"
    raise ValueError(f"Consistency operation is outside the fixed story scope: {file}:{op['pointer']}")


def _strings(value):
    return isinstance(value, list) and all(isinstance(x, str) and x for x in value)


def _validate_source_blocks(before_docs, after_docs, file, tokens, old, new):
    row = _get(before_docs[file], tokens[:2])
    identity = row.get('decision_id') if file == 'decisions.json' else row.get('story_day')
    allowed = _SOURCE_BLOCK_SCOPES[file, identity, tokens[2]]
    if not isinstance(old, list) or not isinstance(new, list):
        raise ValueError('Source blocks must remain lists')
    previous = {b['block_id']: b for b in old}
    retained = list(previous)
    # One explicit cross-node move: main arrival from D59 to DP4-10.
    day59 = next((b for b in before_docs.get('story_beats.json', {}).get('beats', [])
                  if b.get('story_day') == 59), None)
    moved = day59.get('opening_blocks', []) if day59 else []
    if file == 'story_beats.json' and identity == 59:
        destination = next(d for d in after_docs['decisions.json']['decisions'] if d['decision_id'] == 'dp4_10')
        target_ids = [b['block_id'] for b in destination['presentation_blocks']]
        if any(target_ids.count(bid) != 1 for bid in retained):
            raise ValueError('D59 arrival must be moved to DP4-10, not deleted')
        previous, retained = {}, []
    elif file == 'decisions.json' and identity == 'dp4_10':
        previous.update({b['block_id']: b for b in moved})
        retained = [b['block_id'] for b in moved] + retained
    ids = []
    public = {'text', 'speaker'}
    fields = public | {'block_id', 'kind', 'scene_id', 'presentation_phase'}
    all_ids = [v for p, v in _leaves(after_docs, '') if p.endswith('/block_id')]
    for block in new:
        if not isinstance(block, dict) or not isinstance(block.get('block_id'), str):
            raise ValueError('Invalid source block')
        bid = block['block_id']
        ids.append(bid)
        if bid in previous:
            if not _equal({k:v for k,v in previous[bid].items() if k not in public},
                          {k:v for k,v in block.items() if k not in public}):
                raise ValueError('Source restoration cannot change existing block mechanisms')
        elif (bid not in allowed or set(block) - fields
              or block.get('kind') not in ('narration', 'dialogue')
              or any(not isinstance(v, str) for v in block.values())):
            raise ValueError('Unregistered source block or unsupported mechanism')
        if bid in allowed and tuple(block.get(k) for k in
                ('scene_id', 'presentation_phase', 'kind', 'speaker')) != _SOURCE_BLOCK_PRESENTATION[bid]:
            raise ValueError('Source block scene, phase and speaker must match the reviewed presentation')
        if not isinstance(block.get('text'), str) or not block['text'] or all_ids.count(bid) != 1:
            raise ValueError('Source blocks require unique IDs and nonempty text')
    if [bid for bid in ids if bid in previous] != retained:
        raise ValueError('Existing source blocks cannot be removed or reordered')


def _validate_openings(before, after):
    guards = {"required_flags", "required_any_flags", "forbidden_flags"}
    mutable = guards | {"text", "speaker"}
    new_fields = mutable | {"block_id", "kind", "scene_id", "presentation_phase"}
    if not isinstance(before, list) or not isinstance(after, list) or len(after) < len(before):
        raise ValueError("Opening revisions must preserve existing blocks and append new blocks")
    identities = []
    for i, block in enumerate(after):
        if (not isinstance(block, dict) or not isinstance(block.get("block_id"), str)
                or not block["block_id"] or not isinstance(block.get("text"), str)
                or block.get("speaker") is not None and not isinstance(block["speaker"], str)):
            raise ValueError("Invalid opening block")
        identities.append(block["block_id"])
        if i < len(before):
            old = before[i]
            if not isinstance(old, dict) or not _equal(
                    {k: v for k, v in old.items() if k not in mutable},
                    {k: v for k, v in block.items() if k not in mutable}):
                raise ValueError("Existing block IDs, order, and internal fields are immutable")
        elif (set(block) - new_fields or block.get("kind") not in ("narration", "dialogue")
              or any(not isinstance(v, str) for k, v in block.items() if k not in guards)):
            raise ValueError("New opening block contains unsupported fields or mechanisms")
        if any(not _strings(block[k]) for k in guards if k in block):
            raise ValueError("Opening conditions must be explicit flag lists")
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate opening block ID")


def _matrix_projection(before_docs, after_docs, tokens):
    old = _get(before_docs["story_acceptance_matrix.json"], tokens[:2])
    row = _get(after_docs["story_acceptance_matrix.json"], tokens[:2])
    day, field = row["story_day"], tokens[2]
    beat = next((b for b in after_docs.get("story_beats.json", {}).get("beats", [])
                 if b.get("story_day") == day), None)
    if beat is None:
        raise ValueError("Matrix bookkeeping requires the corresponding story beat")
    openings = beat.get("opening_blocks", [])
    if field in {"introduced_npc_ids", "npc_discovery_transitions"}:
        text = "\n".join((b.get("speaker") or "") + "\n" + b["text"] for b in openings)
        actual = [n["npc_id"] for n in after_docs.get("npc_profiles.json", {}).get("npcs", [])
                  if n.get("name") and n["name"] in text]
        introduced = list(dict.fromkeys([n for n in old.get("introduced_npc_ids", []) if n in actual] + actual))
        if field == "introduced_npc_ids":
            return introduced
        if day == 61:
            profiles = {n['name']:n['npc_id'] for n in after_docs.get('npc_profiles.json', {}).get('npcs', [])}
            speakers = list(dict.fromkeys(b['speaker'] for b in openings if b.get('speaker')))
            return ([{'npc_id':n,'state':'mentioned'} for n in introduced]
                    + [{'npc_id':profiles[name],'state':'encountered'} for name in speakers]
                    + [t for t in old.get('npc_discovery_transitions', []) if t.get('state')=='contactable'])
        return ([{"npc_id": n, "state": "mentioned"} for n in introduced]
                + [t for t in old.get("npc_discovery_transitions", []) if t.get("state") != "mentioned"])
    if field in {"opening_block_ids", "required_story_entry_ids"}:
        return [b["block_id"] for b in openings]
    if field == "visible_speakers":
        return list(dict.fromkeys(b["speaker"] for b in openings if b.get("speaker")))
    ids = row.get("decision_ids", [])
    if field == "decision_ids":
        old_ids = old.get("decision_ids", [])
        return ([d for d in old_ids if d != "dp3_08"] if day == 43
                else ["dp3_08", *[d for d in old_ids if d != "dp3_08"]] if day == 44 else old_ids)
    catalog = {d["decision_id"]: d for d in after_docs.get("decisions.json", {}).get("decisions", [])}
    if any(d not in catalog for d in ids):
        raise ValueError("Matrix refers to an unknown decision")
    decisions = [catalog[d] for d in ids]
    presentation = [b for d in decisions for b in d.get("presentation_blocks", [])]
    if field in {"prerequisite_narrative_ids", "decision_display_node_ids"}:
        return [b["block_id"] for b in presentation]
    if field == "decision_presentation_order":
        return [{"decision_id": d["decision_id"], "presentation_entry_ids": [
            b["block_id"] for b in d.get("presentation_blocks", [])]} for d in decisions]
    if field == "outcome_transition_ids":
        return [b["block_id"] for d in decisions for b in d.get("followup_blocks", [])]
    blocks = [*openings, *(b for d in decisions for b in [
        *d.get("presentation_blocks", []), *d.get("followup_blocks", [])])]
    return list(dict.fromkeys(b["scene_id"] for b in blocks if b.get("scene_id")))


def _validate_consistency_section(before_docs, after_docs, scope):
    file, tokens, kind = scope
    old, new = _get(before_docs[file], tokens), _get(after_docs[file], tokens)
    if kind == "metadata":
        if not isinstance(new, str) or not new or (tokens[0] == "content_hash"
                and not re.fullmatch(r"sha256:[0-9a-f]{64}", new)):
            raise ValueError("Invalid manifest metadata")
    elif kind == 'authored_source_metadata':
        import hashlib
        from content.editorial.story_author_revision import source_path, read_source_edition
        raw = source_path().read_bytes()
        read_source_edition(raw)
        expected = ('最终剧本_20260908_连贯性统修' if tokens[0]=='source_version'
                    else 'sha256:' + hashlib.sha256(raw).hexdigest())
        if new != expected:
            raise ValueError('Source metadata must identify the approved edited script')
    elif kind == "day":
        if type(old) is not int or type(new) is not int or (old, new) != (43, 44):
            raise ValueError("Only dp3_08 day 43 to 44 is approved")
    elif kind == "queue":
        row = _get(before_docs[file], tokens[:2])
        if not _strings(old) or not isinstance(new, list):
            raise ValueError("Decision queue must be a list")
        expected = ([d for d in old if d != "dp3_08"] if row["story_day"] == 43
                    else ["dp3_08", *[d for d in old if d != "dp3_08"]])
        if not _equal(new, expected):
            raise ValueError("Queue approval may only move dp3_08 from day 43 to 44")
    elif kind == "opening":
        _validate_openings(old, new)
        # A newly introduced block must not alias any existing or other new block.
        all_ids = [v for p, v in _leaves(after_docs, "") if p.endswith("/block_id")]
        for block in new[len(old):]:
            if all_ids.count(block["block_id"]) != 1:
                raise ValueError("New opening block ID collides with another registered block")
    elif kind == 'source_blocks':
        _validate_source_blocks(before_docs, after_docs, file, tokens, old, new)
    elif kind == 'author_revision':
        from content.editorial.story_author_revision import apply_author_revision
        expected_docs = deepcopy(before_docs)
        apply_author_revision(expected_docs)
        expected = _get(expected_docs[file], tokens)
        def structure(value):
            if isinstance(value, dict):
                return {k:structure(v) for k,v in value.items() if k != 'text'}
            if isinstance(value, list):
                return [structure(v) for v in value]
            return value
        # Public prose has its own leaf approval. Every ID, condition, phase,
        # prerequisite and economic effect must match this specific author edition.
        if not _equal(structure(new), structure(expected)):
            raise ValueError('Outside the exact user-approved author revision')
    elif kind == 'return_witness':
        template = _get(before_docs[file], tokens[:2])
        if old != 'a' or new != 'b' or not isinstance(template, dict) or template.get('dp4_01') != 'e':
            raise ValueError('Only the returned-original witness may switch DP6-06.a to existing DP6-06.b')
    elif kind == "no_resurrection":
        if (not isinstance(old, dict) or old.get("lead_roster_disposition") != "己方封存"
                or not _equal(new, {k: v for k, v in old.items() if k != "lead_roster_disposition"})):
            raise ValueError("Only removal of dp6_03.c's own-sealed assignment is approved")
    elif kind in {"possession", "handoff"}:
        old = {} if old is _MISSING else old
        expected = "己方封存" if kind == "possession" else "交给记者"
        if (not isinstance(old, dict) or not isinstance(new, dict)
                or old.get("lead_roster_disposition") not in (None, "己方封存", expected)
                or not _equal(new, {**old, "lead_roster_disposition": expected})):
            raise ValueError("Only the owned-original possession guard/reporter handoff is approved")
    elif kind == "refusal":
        old = [] if old is _MISSING else old
        if (not isinstance(old, list) or not isinstance(new, list) or len(new) != len(old) + 1
                or not _equal(new[:-1], old)):
            raise ValueError("Only appending the request-refusal variant is approved")
        variant = new[-1]
        if (not isinstance(variant, dict)
                or set(variant) - {"variant_id", "required_flags", "option_consequences"}
                or variant.get("required_flags") != ["门诊楼前被清场"]
                or variant.get("variant_id", "press_request_after_clearance") != "press_request_after_clearance"
                or not isinstance(variant.get("option_consequences"), dict)
                or set(variant["option_consequences"]) != {"e"}
                or not isinstance(variant["option_consequences"]["e"], str)):
            raise ValueError("Refusal variant must only override option e under the clearance flag")
        if any(v.get("variant_id") == variant.get("variant_id", "press_request_after_clearance")
               for v in old if isinstance(v, dict)):
            raise ValueError("Duplicate request-refusal variant ID")
    elif kind == "matrix":
        if not _equal(new, _matrix_projection(before_docs, after_docs, tokens)):
            raise ValueError(f"Matrix bookkeeping does not match final story: {'/'.join(tokens)}")


def apply_operations(documents: dict[str, dict], operations: list[dict], *,
                     consistency_authorizations: list[dict] | dict[str, dict] | None = None
                     ) -> dict[str, dict]:
    """Apply exact copy or independently approved story-consistency operations.

    category='story_consistency' requires consistency_authorizations: a list of
    approval objects or {approval_id: approval_object}. Each approval independently
    repeats file/pointer/op and exactly the same present before/after fields.
    Optional reason/test_ids metadata is not used as authority. Approval never
    bypasses the fixed semantic scope, identity guards, or economic/schema bans.
    Structural copy edits must contain only public string leaves; mechanisms and IDs cannot
    hitchhike in a replaced object. Array add requires a vacant explicit index
    (the current length); use registered leaf replacements for reordering.
    Optional node_id/option_id guards are checked against the source ancestry.
    """
    if not isinstance(documents, dict) or not isinstance(operations, list):
        raise ValueError("Expected document mapping and operation list")
    seen_files = set()
    for file, document in documents.items():
        validate_file_name(file)
        if file.casefold() in seen_files or not isinstance(document, dict):
            raise ValueError("Duplicate file alias or non-object document")
        seen_files.add(file.casefold())
    result = deepcopy(documents)
    approvals = _approval_index(consistency_authorizations)
    consistency_scopes = set()
    seen = {}
    allowed = {file: set() for file in documents}
    for op in operations:
        if not isinstance(op, dict):
            raise ValueError("Operation must be an object")
        file = validate_file_name(op.get("file"))
        path = op.get("pointer")
        tokens = _tokens(path)
        if file not in result:
            raise ValueError(f"Unregistered JSON file: {file}")
        action = op.get("op")
        category = op.get("category")
        if action not in ("replace", "remove", "add") or category not in ("copy", "story_consistency"):
            raise ValueError("Expected replace/remove/add with copy or story_consistency category")
        if action != "add" and "before" not in op or action != "remove" and "after" not in op:
            raise ValueError("Operation is missing before/after value")
        prior = seen.setdefault(file, [])
        if any(tokens[:len(p)] == p or p[:len(tokens)] == tokens for p in prior):
            raise ValueError(f"Duplicate or overlapping operation: {file}:{path}")
        prior.append(tokens)
        parent = result[file]
        ancestors = [parent]
        for token in tokens[:-1]:
            parent = _child(parent, token)
            ancestors.append(parent)
        day, node_id, option_id = _context(ancestors)
        if len(tokens) >= 2 and tokens[-2] in {"option_texts", "option_consequences"}:
            option_id = tokens[-1]
        if tokens[0] == "conversation_contexts" and len(tokens) > 1:
            node_id = tokens[1]
        for key, actual in (("node_id", node_id), ("option_id", option_id)):
            if key in op and op[key] != actual:
                raise ValueError(f"{key} mismatch at {file}:{path}")
        token = tokens[-1]
        if isinstance(parent, dict):
            key = token
            exists = key in parent
        elif isinstance(parent, list):
            key = _index(token, len(parent), add=action == "add")
            exists = key < len(parent)
        else:
            raise ValueError("Operation parent is not a container")
        old = parent[key] if exists else _MISSING
        if action == "add":
            if exists or "before" in op and op["before"] is not None:
                raise ValueError(f"Add must target an absent value: {path}")
        elif not exists or not _equal(old, op["before"]):
            raise ValueError(f"Old value mismatch at {file}:{path}")
        new = op.get("after", _MISSING) if action != "remove" else _MISSING
        leaves = [(p, v) for value in (old, new) if value is not _MISSING
                  for p, v in _leaves(value, path)]
        if category == "copy":
            if any(not isinstance(v, str) or not _public_path(file, p) for p, v in leaves):
                raise ValueError(f"Copy operation includes non-public or non-text fields: {file}:{path}")
            allowed[file].update(p for p, _ in leaves)
        else:
            auth = approvals.get((file, path))
            if auth is None or any((k in auth) != (k in op) or not _equal(auth.get(k), op.get(k))
                                   for k in ("file", "pointer", "op", "before", "after")):
                raise ValueError(f"Exact separate consistency approval required: {file}:{path}")
            validate_operation_identities(documents, [op])
            consistency_scopes.add(_consistency_scope(documents, op))
            allowed[file].update(diff_paths(old, new, path))
        if action == "remove":
            del parent[key]
        elif isinstance(parent, list) and action == "add":
            parent.append(deepcopy(new))
        else:
            parent[key] = deepcopy(new)
    for file in documents:
        assert_allowed_diff(documents[file], result[file], allowed[file])
    for scope in consistency_scopes:
        _validate_consistency_section(documents, result, scope)
    return result


def read_json_bytes(raw: bytes) -> dict:
    """Reject duplicate object keys and non-JSON numeric constants."""
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError(f"Duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def bad_constant(value):
        raise ValueError(f"Invalid JSON constant: {value}")

    result = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                        parse_constant=bad_constant)
    if not isinstance(result, dict):
        raise ValueError("JSON document must be an object")
    return result


def reject_link(path: Path) -> None:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError(f"Symbolic links/junctions are not supported: {path}")
    if path.exists() and getattr(path.stat(), "st_file_attributes", 0) & 0x400:
        raise ValueError(f"Reparse point is not supported: {path}")


def read_package(package_dir: Path) -> tuple[dict, dict]:
    """Read all files once; no links, unaccounted files or case aliases."""
    package_dir = Path(package_dir)
    reject_link(package_dir)
    if not package_dir.is_dir():
        raise ValueError(f"Source package directory does not exist: {package_dir}")
    documents, raw_files, aliases = {}, {}, set()
    for path in sorted(package_dir.rglob("*")):
        reject_link(path)
        if path.is_dir():
            continue
        name = validate_relative_file(path.relative_to(package_dir).as_posix())
        if name.casefold() in aliases or not path.is_file():
            raise ValueError(f"Duplicate or unsupported package file: {name}")
        aliases.add(name.casefold())
        raw_files[name] = path.read_bytes()
        if name.endswith(".json"):
            documents[name] = read_json_bytes(raw_files[name])
    if not documents:
        raise ValueError("Source package is empty")
    return documents, raw_files


def enumerate_visible_records(package_dir: Path) -> list[dict]:
    """Enumerate explicit public string fields; never assign a disposition."""
    documents, _ = read_package(package_dir)
    records = []

    def walk(file, value, pointer, semantic, ancestors):
        if isinstance(value, dict):
            for key, child in value.items():
                yield from walk(file, child, f"{pointer}/{_escape(key)}",
                                f"{semantic}/{_escape(key)}", [*ancestors, value])
        elif isinstance(value, list):
            for i, child in enumerate(value):
                identity = str(i)
                if isinstance(child, dict):
                    for key in ("option_id", "block_id", *_IDENTITY_KEYS):
                        if key in child:
                            identity = f"{key}={child[key]}"
                            break
                yield from walk(file, child, f"{pointer}/{i}",
                                f"{semantic}/{_escape(identity)}", ancestors)
        elif isinstance(value, str) and _public_path(file, pointer):
            day, node_id, option_id = _context(ancestors)
            tokens = _tokens(pointer)
            if file == "interaction_opportunities.json" and tokens[0] == "conversation_contexts":
                node_id = tokens[1]
            if len(tokens) >= 2 and tokens[-2] in {"option_texts", "option_consequences"}:
                option_id = tokens[-1]
            kind = tokens[-2] if tokens[-2:-1] in [("option_texts",), ("option_consequences",)] else tokens[-1]
            yield dict(review_id=f"{file}:{semantic}", file=file, pointer=pointer,
                       kind=kind, day=day, node_id=node_id, option_id=option_id, text=value)

    for file, document in documents.items():
        records.extend(walk(file, document, "", "", []))
    if len({r["review_id"] for r in records}) != len(records):
        raise ValueError("Duplicate stable record identity in public inventory")
    return sorted(records, key=lambda r: (r["file"], r["pointer"]))
