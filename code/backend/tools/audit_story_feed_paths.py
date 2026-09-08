"""Validate first-load, incremental and refresh feed consistency for D5-D90.

This is a deterministic service-level check. It does not call an LLM and does
not claim to replace a browser replay: it checks that the authoritative story
flow emits the same content instances through all three feed views.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.config import Settings


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "content" / "packages"
sys.path.insert(0, str(ROOT / "tests"))
from test_doubles import build_test_container  # noqa: E402


def run() -> dict:
    settings = Settings(
        environment="test",
        content_root=PACKAGE_ROOT,
        default_package_id="pkg_gameplay_v3",
        repository="memory",
        role_llm_provider="none",
    )
    runtime = build_test_container(settings)
    package = runtime.packages.get("pkg_gameplay_v3")
    prototype = runtime.game_sessions.start_session(
        account_id="story-feed-audit",
        package_id=package.package_id,
        client_request_id="story-feed-audit-session",
        origin_id="technical",
    )
    flow = StoryFlowService()
    days: list[dict] = []
    errors: list[dict] = []
    for day in range(5, 91):
        session = deepcopy(prototype)
        session.game_state = replace(session.game_state, story_day=day)
        session.story_beat_id = None
        session.pending_decision = None
        session.pending_decision_queue.clear()
        session.narrative_feed.clear()
        session.rendered_content_ids.clear()
        session.next_feed_cursor = 1

        flow.enter_current_day(session, package)
        first = flow.feed_since(session, 0)
        first_ids = [item["content_instance_id"] for item in first["items"]]
        first_cursors = [item["cursor"] for item in first["items"]]
        first_cursor = first["cursor"]

        flow.append_night(session, package)
        incremental = flow.feed_since(session, first_cursor)
        refreshed = flow.feed_since(session, 0)
        refreshed_ids = [item["content_instance_id"] for item in refreshed["items"]]
        incremental_ids = [item["content_instance_id"] for item in incremental["items"]]

        if len(first_ids) != len(set(first_ids)):
            errors.append({"day": day, "type": "duplicate_first_load_content_instance"})
        if len(refreshed_ids) != len(set(refreshed_ids)):
            errors.append({"day": day, "type": "duplicate_refresh_content_instance"})
        if first_ids and refreshed_ids[: len(first_ids)] != first_ids:
            errors.append({"day": day, "type": "refresh_order_changed", "first": first_ids, "refresh": refreshed_ids})
        if not set(first_ids).issubset(refreshed_ids):
            errors.append({"day": day, "type": "refresh_missing_first_load_items"})
        if not set(incremental_ids).issubset(refreshed_ids):
            errors.append({"day": day, "type": "incremental_missing_from_refresh"})
        if any(cursor <= first_cursor for cursor in [item["cursor"] for item in incremental["items"]]):
            errors.append({"day": day, "type": "incremental_cursor_leak"})

        beat = package.story_day(day)
        # append_night intentionally omits blocks marked ``morning``; those
        # are projected by the next-day morning card rather than this feed.
        expected_blocks = (
            *beat.opening_blocks,
            *(block for block in beat.night_blocks if block.presentation_phase != "morning"),
        )
        visible_source_ids = {
            block.block_id
            for block in expected_blocks
            if block.is_visible(origin_id=session.origin_id, flags=session.flags)
        }
        emitted_source_ids = {
            item["block_id"]
            for item in refreshed["items"]
            if item.get("block_id")
        }
        missing_source_ids = sorted(visible_source_ids - emitted_source_ids)
        if missing_source_ids:
            errors.append({"day": day, "type": "visible_story_block_missing", "block_ids": missing_source_ids})

        days.append({
            "story_day": day,
            "first_load_count": len(first["items"]),
            "incremental_count": len(incremental["items"]),
            "refresh_count": len(refreshed["items"]),
            "first_load_cursor": first_cursor,
            "first_load_cursors": first_cursors,
            "incremental_content_ids": incremental_ids,
            "refresh_content_ids": refreshed_ids,
            "visible_source_block_count": len(visible_source_ids),
            "emitted_source_block_count": len(emitted_source_ids & visible_source_ids),
        })
    return {
        "audit_version": 1,
        "package_id": package.package_id,
        "range": {"start_day": 5, "end_day": 90},
        "days": days,
        "errors": errors,
        "passed": not errors,
        "evidence_boundary": "service-level feed comparison; no browser rendering or real model call",
    }


def markdown(report: dict) -> str:
    lines = [
        "# 剧情 feed 首次/增量/刷新审计（D05—D90）",
        "",
        f"- 结果：{'通过' if report['passed'] else '失败'}",
        f"- 覆盖天数：{len(report['days'])}",
        f"- 错误数：{len(report['errors'])}",
        f"- 证据边界：{report['evidence_boundary']}",
        "",
        "| 日 | 首次加载 | 增量 feed | 刷新 feed | 可见源块 | 已发出源块 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["days"]:
        lines.append(
            f"| D{item['story_day']:02d} | {item['first_load_count']} | "
            f"{item['incremental_count']} | {item['refresh_count']} | "
            f"{item['visible_source_block_count']} | {item['emitted_source_block_count']} |"
        )
    if report["errors"]:
        lines.extend(["", "## 错误", ""])
        lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in report["errors"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "days": len(report["days"]), "errors": len(report["errors"])}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
