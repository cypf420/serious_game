# Source-backed Story Restoration Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans; use test-driven-development for runtime behavior and verification-before-completion for handoff.

**Goal:** Restore missing player scenes from the user-selected final script, repair source-supported transitions, and explicitly report unresolved authorial contradictions.

**Architecture:** Extend the existing controlled editorial builder with one source-pinned restoration module. Rebuild a new candidate and install only after baseline drift checks. Keep the extra legacy D46 return choice compatible by skipping the redundant physical-custody question after it.

**Tech Stack:** Python, FastAPI in-memory TestClient, JSON story packages, pytest.

**Spec:** User-selected `E:/严肃游戏/.codex-worktrees/backend-0c15d36/最终剧本.md`; previous 13-item review in this task.

## Global Constraints

- Original source SHA-256: `648041c97cab18edaf945cfa775351212b7b05dea4d789bbe5c3527d71481614`.
- Do not modify the original script, old candidate packages, saves, deployment, or unrelated working changes.
- Do not invent D53 dialogue, new compensation agreements, character recovery, upper-level identities, or ending histories.
- Preserve 81 decisions, 688 options and existing ending selection rules; the legacy D46 entry remains supported.
- No commit, push, or deployment is required.

### Task 1: Recover source scenes and playback order

Files: create `code/backend/content/editorial/story_source_restoration.py`; modify `code/backend/tools/build_story_integrity_candidate.py`; create `code/backend/tests/test_story_source_restoration.py`.

- [x] Write consumer tests: D2 quote precedes its anaphora and survives refresh; D17 car precedes decision; D34 evidence description precedes decision and is not replayed after selection; D59 advance visit resolves before main arrival; D61 named worklist does not claim a fixed unresolved count.
- [x] Run `python -m pytest tests/test_story_source_restoration.py -q` and confirm expected missing-scene failures.
- [x] Restore D2 source lines 2554, 2558, 2560; D17 line 3541; D34 lines 5004–5024. Extract only player paragraphs with source hash checking. Keep existing outcomes.
- [x] Move D59 main arrival into `dp4_10` presentation; use source 7651–7655 for the day opening. Retain current city-level inspector identity rather than reintroducing the source's conflicting provincial title.
- [x] Restore the seven D61 names from source 8023 as a worklist to check, not a declaration that all 13 remain unsigned. Replace fixed-count option/outcome wording with references to the actual outstanding list.
- [x] Register changed block IDs, scenes and speaker prerequisites in the acceptance matrix; bump candidate to `3.5.15-source-restoration` and preserve authority regeneration.

### Task 2: Prevent repeat disposal after legacy return

Files: modify `code/backend/src/serious_game_backend/application/story_flow_service.py`; tests in the same new test module.

- [x] Through real API choose `dp4_01:e`; assert no second custody decision, custody `未获取`, zero extra ledger/metric effects, and no acceptance of a subsequent `dp4_roster_disposition:a` request.
- [x] Also assert choices a–d still expose the custody question and return/retain/transfer choices still work.
- [x] Implement an idempotent skip based on the recorded `dp4_01:e` action, recording custody and a private skip event; use it in both queued and direct presentation.
- [x] Run the tests, including refresh and repeated presentation, without altering prior decision effects. Execution adjustment: the existing `unknown` acceptance-driver template's `dp6_06` changed only a→b, since full replay demonstrated its former handoff required resurrecting the returned original. All route IDs, targets, contracts and other template fields remain fixed, checked by the independent whitelist.

### Task 3: Build, verify and hand off

- [x] Build candidates using the existing builder; validate authority and install with previous-candidate drift guards. Final: `candidate-15-source-restoration`. Candidates12–13 were rejected before install, candidate14 was superseded by the acceptance-driver compatibility fix.
- [x] Run source restoration tests, story integrity tests, export completeness, package/authority tests, and relevant existing story review regressions: 284 passed, 2 skipped; feed audit86 days/0 errors.
- [x] Export a new full Markdown and coverage JSON using `tools/export_player_story.py`; preserve prior exports. Verify final exported bytes and coverage equal the current package projection.
- [x] Create a source mapping and unresolved-issues report under outer `outputs/`. Seven unresolved items: D53 missing answer, D26/53 old-case reset, D11 husband's contradiction, D59 Feng's role, ending18 chronology, ending20 meeting history, rope antecedent. Give original line references and required editorial decisions.
- [x] Report actual test results in the handoff document and explicitly state that source recovery is not certification of every 90-day route.
