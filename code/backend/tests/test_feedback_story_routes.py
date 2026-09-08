"""Per-block visibility and per-event trigger/skip checks; not a full AI playthrough."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from serious_game_backend.application.event_service import EventService
from serious_game_backend.application.story_flow_service import StoryFlowService
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings


@pytest.fixture(scope="module")
def world():
    r = build_container(Settings(environment="test", repository="memory", role_llm_provider="none",
        content_root=Path(__file__).resolve().parents[1] / "content/packages",
        default_package_id="pkg_gameplay_v3"))
    p = r.packages.get("pkg_gameplay_v3")
    s = r.game_sessions.start_session(account_id="editorial-route-test", package_id=p.package_id,
        client_request_id="editorial-route-test-session", origin_id="technical")
    return r, p, s


def test_each_story_block_emits_only_on_its_declared_routes(world):
    _, p, prototype = world
    for day in range(1, 91):
        beat = p.story_day(day)
        blocks = [*beat.opening_blocks, *beat.night_blocks]
        blocks += [b for d in p.decisions.values() if d.story_day == day
                   for b in (*d.presentation_blocks, *d.followup_blocks)]
        for block in blocks:
            origin = sorted(block.origin_ids)[0] if block.origin_ids else "technical"
            positive = set(block.required_flags)
            if block.required_any_flags:
                positive.add(sorted(block.required_any_flags)[0])
            cases = [(origin, positive, True)]
            cases += [(origin, positive - {flag}, False) for flag in block.required_flags]
            cases += [(origin, positive | {flag}, False) for flag in block.forbidden_flags]
            if block.required_any_flags:
                cases.append((origin, positive - block.required_any_flags, False))
            if block.origin_ids:
                cases.append(("unrelated_origin", positive, False))
            for selected_origin, flags, visible in cases:
                s = deepcopy(prototype)
                s.origin_id, s.flags = selected_origin, flags
                s.game_state = replace(s.game_state, story_day=day)
                s.narrative_feed.clear()
                s.rendered_content_ids.clear()
                StoryFlowService().append_blocks(s, [block])
                assert bool(s.narrative_feed) is visible, (day, block.block_id, flags)
                if visible:
                    assert s.narrative_feed[0].text.strip(), block.block_id
                    assert s.narrative_feed[0].scene_id == block.scene_id
                    assert "决定已经写入当天案卷" not in s.narrative_feed[0].text


def test_every_conditional_event_trigger_skip_and_retry(world):
    _, p, prototype = world
    for rule in p.fixed_events:
        flags = set(rule.required_flags)
        if rule.required_any_flags:
            flags.add(sorted(rule.required_any_flags)[0])
        cases = [(flags, set(), True)]
        cases += [(flags - {f}, set(), False) for f in rule.required_flags]
        if rule.required_any_flags:
            cases.append((flags - rule.required_any_flags, set(), False))
        cases += [(flags | {f}, set(), False) for f in rule.forbidden_flags]
        cases += [(flags, {e}, False) for e in rule.forbidden_event_ids]
        for candidate, prior, should_trigger in cases:
            s = deepcopy(prototype)
            s.game_state = replace(s.game_state, story_day=rule.story_day)
            s.flags, s.triggered_events = candidate, prior.copy()
            s.pending_decision_queue.clear()
            result = EventService().trigger_fixed_events(s, p)
            assert (rule.event_id in result) is should_trigger, (rule.event_id, candidate, prior)
            assert rule.event_id not in EventService().trigger_fixed_events(s, p)


def test_d8_blockade_and_d10_rescue_are_separate_routes(world):
    _, p, prototype = world
    for flags, blockade in ((set(), False), ({"强势立威"}, True), ({"开口子许诺"}, True)):
        s = deepcopy(prototype)
        s.triggered_events.clear()
        s.flags = flags
        s.pending_decision_queue.clear()
        s.game_state = replace(s.game_state, story_day=8)
        assert ("EV1-02" in EventService().trigger_fixed_events(s, p)) is blockade
        s.game_state = replace(s.game_state, story_day=10)
        assert ("EV1-03" in EventService().trigger_fixed_events(s, p)) is (not blockade)
        s.narrative_feed.clear()
        s.rendered_content_ids.clear()
        StoryFlowService().append_night(s, p)
        # An untriggered rescue must never leak through the unconditional night feed.
        assert all("高烧抽搐" not in entry.text for entry in s.narrative_feed)
    assert "高烧抽搐" in p.decisions["ev1_03"].presentation_blocks[0].text


def test_d9_restores_invitation_payoff_and_d44_keeps_later_scene_after_first_choice(world):
    _, p, _ = world
    d9 = p.story_day(9).opening_blocks
    assert [b.scene_id for b in d9[:2]] == ["C06_S07", "C06_S07"]
    assert all(b.scene_id == "C01_S08" for b in d9[2:])
    assert "冶炼厂" in d9[-1].text
    assert all("下午，巡察组" not in b.text for b in p.story_day(44).opening_blocks)
    assert p.decisions["dp3_09"].presentation_blocks[0].scene_id == "C03_S06"
    assert p.decisions["dp5_09"].presentation_blocks[0].scene_id == "C05_S02"


@pytest.fixture
def feedback_upgrade_baseline(tmp_path):
    """Rebuild the real 3.5.13 package and same-ref authority from tracked Git blobs."""
    from unittest.mock import patch
    from tools.upgrade_feedback_session import NEW_VERSION
    from tests.test_content_hash_portability import (
        PACKAGE_BASELINE_REF, _materialize_package_from_git_blobs,
        _materialize_authority_from_git_blobs,
    )

    root = tmp_path / "feedback-baseline"
    _materialize_package_from_git_blobs(root / "content/packages", "pkg_gameplay_v3",
                                        autocrlf=False, ref=PACKAGE_BASELINE_REF)
    authority = _materialize_authority_from_git_blobs(root / "baseline-authority.json",
                                                     ref=PACKAGE_BASELINE_REF)
    with patch("serious_game_backend.infrastructure.script_packages.file_loader.STORY_AUTHORITY_CONTRACT",
               authority):
        runtime = build_container(Settings(environment="test", repository="memory", role_llm_provider="none",
            content_root=root / "content/packages", default_package_id="pkg_gameplay_v3"))
        package = runtime.packages.get("pkg_gameplay_v3")
        assert package.package_version == NEW_VERSION
        session = runtime.game_sessions.start_session(account_id="feedback-upgrade-test",
            package_id=package.package_id, client_request_id="feedback-upgrade-session", origin_id="technical")
    return root, authority, package, session


def test_feedback_upgrade_baseline_builds_without_output_and_without_head(tmp_path, monkeypatch):
    import sys
    from tests import test_content_hash_portability as blobs

    # A checkout without generated output must still supply the historical fixture.
    checkout = tmp_path / "fresh-checkout"
    test_file = checkout / "code/backend/tests/test_feedback_story_routes.py"
    assert not (checkout / "output").exists()
    git = blobs._git

    def pinned_git(*args):
        assert all("HEAD" not in arg for arg in args), "Fixture must not drift with HEAD"
        return git(*args)

    monkeypatch.setattr(sys.modules[__name__], "__file__", str(test_file))
    monkeypatch.setattr(blobs, "_git", pinned_git)
    root, authority, package, _ = feedback_upgrade_baseline.__wrapped__(tmp_path)
    assert package.package_version == "3.5.13-feedback-reading-actions"
    assert package.content_hash == "sha256:d32346777561cd929b7222ce3a6ceb14e0735798e860dff7dabe9e19487d072c"
    assert authority.read_bytes() == git(
        "show", "057ff492282d22326dde04a81379142ddb2fa361:code/backend/content/authority/story_authority_d13_d30.json")
    for path in (root / "content/packages/pkg_gameplay_v3").rglob("*"):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            assert path.read_bytes() == git("show", f"057ff492282d22326dde04a81379142ddb2fa361:code/backend/{relative}")
    assert not (checkout / "output").exists()


def _run_feedback_upgrade(database, session_id, root, authority):
    """Run the actual CLI, changing only its test input root and authority path."""
    import subprocess
    import sys

    tool = Path(__file__).resolve().parents[1] / "tools/upgrade_feedback_session.py"
    launcher = """
import runpy
import sys
from pathlib import Path
from unittest.mock import patch
tool, root, authority = sys.argv[1:4]
sys.argv = [tool, *sys.argv[4:]]
namespace = runpy.run_path(tool)
main = namespace['main']
main.__globals__['ROOT'] = Path(root)
with patch('serious_game_backend.infrastructure.script_packages.file_loader.STORY_AUTHORITY_CONTRACT', Path(authority)):
    main()
"""
    return subprocess.run([sys.executable, "-X", "utf8", "-c", launcher, str(tool), str(root), str(authority),
        "--database", str(database), "--session-id", session_id, "--apply"],
        capture_output=True, text=True, encoding="utf-8")


def _recorded_legacy_progress(prototype):
    """Construct the old-lock save fixture using its actual historical manifest."""
    import json
    from tests.test_content_hash_portability import _git
    from tools.upgrade_feedback_session import OLD_VERSION, OLD_HASH

    legacy = json.loads(_git(
        "show", "057ff492282d22326dde04a81379142ddb2fa361^:code/backend/content/packages/pkg_gameplay_v3/package_manifest.json"
    ))
    assert (legacy["package_version"], legacy["content_hash"]) == (OLD_VERSION, OLD_HASH)
    session = deepcopy(prototype)
    session.package_version = legacy["package_version"]
    session.package_content_hash = legacy["content_hash"]
    return session


def test_reviewed_sqlite_upgrade_backs_up_progress_and_keeps_existing_history(feedback_upgrade_baseline, tmp_path):
    import json
    import sqlite3
    from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore, SqliteGameSessionRepository
    from serious_game_backend.infrastructure.repositories.codec import encode_session
    root, authority, p, original = feedback_upgrade_baseline
    s = _recorded_legacy_progress(original)
    db = tmp_path / "progress.db"
    store = SqliteRuntimeStore(db)
    sessions = SqliteGameSessionRepository(store)
    sessions.create(s)
    before = encode_session(s)
    result = _run_feedback_upgrade(db, s.session_id, root, authority)
    assert result.returncode == 0, result.stderr
    after = encode_session(sessions.get_owned(s.session_id, s.account_id))
    for key in before:
        if key not in {"package_version", "package_content_hash", "state_version", "logs", "updated_at", "pending_decision"}:
            assert after[key] == before[key], key
    assert after["package_content_hash"] == p.content_hash
    assert after["state_version"] == before["state_version"] + 1
    backup = next(tmp_path.glob("progress.db.before-feedback-*.bak"))
    with sqlite3.connect(backup) as c:
        old = json.loads(c.execute("select payload_json from runtime_game_sessions").fetchone()[0])
        assert old == json.loads(json.dumps(before))
    with sqlite3.connect(db) as c:
        versions = [r[0] for r in c.execute("select state_version from runtime_game_snapshots order by state_version")]
        assert versions == [before["state_version"], after["state_version"]]


@pytest.mark.parametrize("current_revision", ["target", "progress"])
def test_old_feedback_migrator_rejects_current_revision_without_database_changes(
    world, feedback_upgrade_baseline, tmp_path, current_revision
):
    from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore, SqliteGameSessionRepository
    from serious_game_backend.infrastructure.repositories.codec import encode_session
    from tools.upgrade_feedback_session import NEW_VERSION

    root, authority, _, prototype = feedback_upgrade_baseline
    _, current_package, current_progress = world
    assert current_package.package_version != NEW_VERSION
    if current_revision == "target":
        session = _recorded_legacy_progress(prototype)
        root = Path(__file__).resolve().parents[1]
        authority = root / "content/authority/story_authority_d13_d30.json"
        expected_error = "Unexpected target content revision"
    else:
        session = deepcopy(current_progress)
        expected_error = "This progress does not match the reviewed source revision"
    database = tmp_path / "rejected.db"
    sessions = SqliteGameSessionRepository(SqliteRuntimeStore(database))
    sessions.create(session)
    before = database.read_bytes()
    saved = encode_session(sessions.get_owned(session.session_id, session.account_id))
    result = _run_feedback_upgrade(database, session.session_id, root, authority)
    assert result.returncode != 0
    assert expected_error in result.stderr
    assert database.read_bytes() == before
    assert encode_session(sessions.get_owned(session.session_id, session.account_id)) == saved
    assert not list(tmp_path.glob("rejected.db.before-feedback-*.bak"))
