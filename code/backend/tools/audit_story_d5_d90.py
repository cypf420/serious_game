"""Build a deterministic D5-D90 story-beat audit.

The audit is deliberately read-only: it compares the authoritative story beat
package with its decision references and records IDs, conditions and order. It
does not invent a day-end block for free-action days and does not mutate the
package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_PACKAGE = (
    Path(__file__).resolve().parents[1]
    / "content"
    / "packages"
    / "pkg_gameplay_v3"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _condition_summary(value: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "required_flags",
        "required_any_flags",
        "forbidden_flags",
        "required_fact_ids",
        "forbidden_fact_ids",
    ):
        values = value.get(key)
        if values:
            parts.append(f"{key}={','.join(str(item) for item in values)}")
    minimums = value.get("minimum_ledger_values")
    if minimums:
        parts.append(
            "minimum_ledger_values="
            + ",".join(f"{key}:{minimums[key]}" for key in sorted(minimums))
        )
    return "; ".join(parts) or "无条件"


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def _final_script_match(text: str, final_script: str | None) -> bool | None:
    if final_script is None:
        return None
    normalized = _normalize_for_match(text)
    if len(normalized) < 12:
        return normalized in final_script
    # A short matching window is evidence of correspondence, not proof that
    # the final prose is byte-for-byte identical. False values remain a manual
    # review candidate because the final script may intentionally paraphrase.
    return any(
        normalized[index:index + 12] in final_script
        for index in range(0, len(normalized) - 11, 6)
    )


def _block_record(
    block: dict[str, Any], *, final_script: str | None = None
) -> dict[str, Any]:
    text = str(block.get("text", ""))
    return {
        "block_id": str(block.get("block_id", "")),
        "kind": str(block.get("kind", "")),
        "scene_id": str(block.get("scene_id", "")),
        "presentation_phase": str(block.get("presentation_phase", "")),
        "text_length": len(text),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "required_flags": sorted(str(item) for item in block.get("required_flags", [])),
        "required_any_flags": sorted(str(item) for item in block.get("required_any_flags", [])),
        "forbidden_flags": sorted(str(item) for item in block.get("forbidden_flags", [])),
        "required_event_ids": sorted(str(item) for item in block.get("required_event_ids", [])),
        "origin_ids": sorted(str(item) for item in block.get("origin_ids", [])),
        "final_script_match": _final_script_match(text, final_script),
    }


def audit(
    package_root: Path,
    start_day: int = 5,
    end_day: int = 90,
    final_script_path: Path | None = None,
) -> dict[str, Any]:
    beats = _load(package_root / "story_beats.json").get("beats", [])
    decisions = _load(package_root / "decisions.json").get("decisions", [])
    final_script = (
        _normalize_for_match(final_script_path.read_text(encoding="utf-8"))
        if final_script_path is not None and final_script_path.exists()
        else None
    )
    decision_by_id = {str(item.get("decision_id")): item for item in decisions}
    selected = sorted(
        (item for item in beats if start_day <= int(item.get("story_day", 0)) <= end_day),
        key=lambda item: int(item["story_day"]),
    )
    expected_days = list(range(start_day, end_day + 1))
    actual_days = [int(item["story_day"]) for item in selected]
    issues: list[dict[str, Any]] = []
    if actual_days != expected_days:
        issues.append({
            "type": "missing_or_duplicate_day",
            "expected_days": expected_days,
            "actual_days": actual_days,
        })

    global_block_ids: dict[str, list[str]] = {}
    day_records: list[dict[str, Any]] = []
    for beat in selected:
        day = int(beat["story_day"])
        opening = [
            _block_record(item, final_script=final_script)
            for item in beat.get("opening_blocks", [])
        ]
        night = [
            _block_record(item, final_script=final_script)
            for item in beat.get("night_blocks", [])
        ]
        all_blocks = opening + night
        for item in all_blocks:
            block_id = item["block_id"]
            global_block_ids.setdefault(block_id, []).append(f"D{day:02d}")

        decision_ids = []
        if beat.get("opening_decision_id"):
            decision_ids.append(str(beat["opening_decision_id"]))
        decision_ids.extend(str(item) for item in beat.get("decision_ids", []))
        decision_records = []
        for decision_id in decision_ids:
            decision = decision_by_id.get(decision_id)
            record = {
                "decision_id": decision_id,
                "exists": decision is not None,
                "decision_story_day": (
                    int(decision["story_day"]) if decision is not None else None
                ),
                "option_ids": (
                    [str(item.get("option_id", "")) for item in decision.get("options", [])]
                    if decision is not None else []
                ),
            }
            decision_records.append(record)
            if decision is None:
                issues.append({
                    "type": "missing_decision_reference",
                    "story_day": day,
                    "decision_id": decision_id,
                })
            elif int(decision.get("story_day", day)) != day:
                issues.append({
                    "type": "decision_day_mismatch",
                    "story_day": day,
                    "decision_id": decision_id,
                    "decision_story_day": int(decision.get("story_day", -1)),
                })

        conditional_records = []
        for index, condition in enumerate(beat.get("night_conditional_effects", [])):
            condition = dict(condition)
            conditional_records.append({
                "index": index,
                "condition": {
                    key: condition[key]
                    for key in (
                        "required_flags",
                        "required_any_flags",
                        "forbidden_flags",
                        "required_fact_ids",
                        "forbidden_fact_ids",
                        "minimum_ledger_values",
                    )
                    if condition.get(key)
                },
                "condition_summary": _condition_summary(condition),
                "effect_keys": sorted(condition.get("effects", {}).keys()),
            })

        local_ids = [item["block_id"] for item in all_blocks]
        duplicates = sorted({item for item in local_ids if local_ids.count(item) > 1})
        if duplicates:
            issues.append({
                "type": "duplicate_block_id_within_day",
                "story_day": day,
                "block_ids": duplicates,
            })
        if beat.get("day_mode") == "free_action" and (opening or night or decision_ids):
            # Free-action days can carry a short optional opening, but should
            # not silently acquire a required decision/night block.
            if decision_ids or night:
                issues.append({
                    "type": "unexpected_free_action_content",
                    "story_day": day,
                    "decision_ids": decision_ids,
                    "night_block_ids": [item["block_id"] for item in night],
                })
        if day == end_day and beat.get("day_mode") != "ending":
            issues.append({"type": "ending_day_mode_mismatch", "story_day": day})

        day_records.append({
            "story_day": day,
            "beat_id": str(beat.get("beat_id", "")),
            "day_mode": str(beat.get("day_mode", "")),
            "allow_actions": bool(beat.get("allow_actions", False)),
            "allow_end_day": bool(beat.get("allow_end_day", False)),
            "opening_block_ids": [item["block_id"] for item in opening],
            "opening_blocks": opening,
            "night_block_ids": [item["block_id"] for item in night],
            "night_blocks": night,
            "decision_ids": decision_ids,
            "decisions": decision_records,
            "night_conditional_effects": conditional_records,
        })

    for block_id, locations in sorted(global_block_ids.items()):
        if len(locations) > 1:
            issues.append({
                "type": "duplicate_block_id_across_days",
                "block_id": block_id,
                "story_days": locations,
            })

    return {
        "audit_version": 1,
        "package_id": "pkg_gameplay_v3",
        "package_root": str(package_root),
        "range": {"start_day": start_day, "end_day": end_day},
        "final_script": str(final_script_path) if final_script_path is not None else None,
        "day_count": len(day_records),
        "expected_day_count": end_day - start_day + 1,
        "issues": issues,
        "days": day_records,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 剧情逐日审计清单（D05—D90）",
        "",
        "本清单由 `audit_story_d5_d90.py` 从 `pkg_gameplay_v3/story_beats.json` 和 `decisions.json` 生成。它记录 opening、night、decision、条件块的 ID、顺序和条件摘要；不为 free-action 日补写通用日末文本。",
        "",
        f"- 覆盖天数：{report['day_count']}/{report['expected_day_count']}",
        f"- 发现的结构性问题：{len(report['issues'])}",
        "- 证据边界：这是源包结构和最终剧本文本窗口审计；未替代首次加载、增量 feed、整页刷新和真实分支运行时对比。",
        "",
        "## 结构性问题",
        "",
    ]
    if report["issues"]:
        for issue in report["issues"]:
            lines.append(f"- `{issue['type']}`：{json.dumps(issue, ensure_ascii=False, sort_keys=True)}")
    else:
        lines.append("- 未发现缺日、决策引用缺失、决策日不一致或重复 block_id。")
    lines.extend([
        "",
        "## 每日清单",
        "",
        "| 日 | beat | 模式 | opening 顺序 | night 顺序 | decision 顺序 | 条件块 |",
        "|---:|---|---|---|---|---|---:|",
    ])
    for day in report["days"]:
        lines.append(
            "| D{day:02d} | `{beat}` | `{mode}` | {opening} | {night} | {decisions} | {conditions} |".format(
                day=day["story_day"],
                beat=day["beat_id"],
                mode=day["day_mode"],
                opening=" → ".join(f"`{item}`" for item in day["opening_block_ids"]) or "—",
                night=" → ".join(f"`{item}`" for item in day["night_block_ids"]) or "—",
                decisions=" → ".join(f"`{item}`" for item in day["decision_ids"]) or "—",
                conditions=len(day["night_conditional_effects"]),
            )
        )
    lines.extend(["", "## 条件块明细", ""])
    any_condition = False
    for day in report["days"]:
        for item in day["night_conditional_effects"]:
            any_condition = True
            lines.append(
                f"- D{day['story_day']:02d} 条件块 #{item['index']}：{item['condition_summary']}；效果字段：{', '.join(item['effect_keys']) or '无'}"
            )
    if not any_condition:
        lines.append("- D05—D90 未配置条件块。")
    if report.get("final_script"):
        blocks = [
            item
            for day in report["days"]
            for item in (*day["opening_blocks"], *day["night_blocks"])
        ]
        matched = sum(item["final_script_match"] is True for item in blocks)
        unmatched = sum(item["final_script_match"] is False for item in blocks)
        lines.extend([
            "",
            "## 最终剧本文本对应性",
            "",
            f"- 参与窗口匹配的剧情块：{len(blocks)}；找到至少一个 12 字归一化窗口：{matched}；未找到窗口：{unmatched}。",
            "- 未找到窗口只表示最终剧本与当前包可能存在改写、拆分或条件版本差异，不能单独判定为缺失；需结合首次加载、增量 feed 和刷新快照人工复核。",
        ])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--final-script", type=Path, default=None)
    args = parser.parse_args()
    report = audit(args.package_root, final_script_path=args.final_script)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "剧情逐日审计D05-D90.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "剧情逐日审计D05-D90.md").write_text(
        markdown(report), encoding="utf-8"
    )
    print(json.dumps({"days": report["day_count"], "issues": len(report["issues"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
