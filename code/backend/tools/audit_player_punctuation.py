"""Report punctuation inconsistencies in player-visible package text.

This script only reports candidate text differences. It never rewrites JSON,
IDs, URLs or code-like values, so the resulting list can be reviewed before a
content edit is approved.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PACKAGE = Path(__file__).resolve().parents[1] / "content" / "packages" / "pkg_gameplay_v3"
TEXT_KEYS = {
    "text", "title", "prompt", "description", "label", "name", "subtitle",
    "narrative", "opening_narrative", "conversation_goal", "instructions",
    "reason", "display_title", "scene_title", "public_narrative", "summary",
    "opening", "content", "question", "answer", "hint", "body",
}
CONTENT_FILES = (
    "story_beats.json", "decisions.json", "event_rules.json", "facts.json",
    "npc_profiles.json", "governance_config.json", "action_rules.json",
    "archive_investigations.json", "social_rules.json", "resource_actions.json",
    "ending_rules.json", "public_briefing.json", "interaction_opportunities.json",
    "households.json", "household_signatories.json", "map_locations.json",
)
ASCII_PUNCTUATION = re.compile(r"[,.;:!?](?=[\u3400-\u9fff])|(?<=[\u3400-\u9fff])[,.;:!?]")
ASCII_QUOTES = re.compile(r"(?P<quote>[\"'])")
URL_OR_CODE = re.compile(r"^(?:https?://|[A-Za-z0-9_./:-]+$)")


def _walk(value: Any, path: str = "") -> Iterable[tuple[str, str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if isinstance(child, str) and key in TEXT_KEYS:
                yield child_path, key, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def _issues_for(text: str) -> list[str]:
    if not text.strip() or URL_OR_CODE.fullmatch(text.strip()):
        return []
    issues: list[str] = []
    if ASCII_PUNCTUATION.search(text):
        issues.append("中英文标点相邻或混用")
    if '"' in text:
        issues.append("正文含 ASCII 双引号，需核对是否应为中文外层引号“”")
    if "'" in text:
        issues.append("正文含 ASCII 单引号，需核对是否应为中文内层引号‘’")
    if text.count("“") != text.count("”"):
        issues.append("中文外层引号不成对")
    if text.count("‘") != text.count("’"):
        issues.append("中文内层引号不成对")
    return issues


def audit(package_root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    files_seen: list[str] = []
    for filename in CONTENT_FILES:
        path = package_root / filename
        if not path.exists():
            continue
        files_seen.append(filename)
        data = json.loads(path.read_text(encoding="utf-8"))
        for value_path, key, text in _walk(data):
            for issue in _issues_for(text):
                entries.append({
                    "file": filename,
                    "path": value_path,
                    "field": key,
                    "issue": issue,
                    "text": text,
                })
    return {
        "audit_version": 1,
        "package_id": "pkg_gameplay_v3",
        "files_scanned": files_seen,
        "candidate_count": len(entries),
        "candidates": entries,
        "review_rule": "仅人工确认的玩家可见正文进入后续修改；不改 JSON 语法、ID、URL 或代码结构。",
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 玩家可见文本标点差异清单",
        "",
        "本清单由 `audit_player_punctuation.py` 生成。它只报告候选，不自动改写内容；候选必须人工确认后，才可进入标点修订。",
        "",
        f"- 扫描文件：{len(report['files_scanned'])}",
        f"- 候选数量：{report['candidate_count']}",
        "- 范围：剧情、人物、界面和治理包中的文本字段；排除 ID、URL、代码结构。",
        "",
        "| 文件 | JSON 路径 | 类型 | 文本 |",
        "|---|---|---|---|",
    ]
    for item in report["candidates"]:
        text = item["text"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{item['file']}` | `{item['path']}` | {item['issue']} | {text} |"
        )
    if not report["candidates"]:
        lines.append("| — | — | 未发现候选 | — |")
    lines.extend(["", "## 复核边界", "", report["review_rule"], ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.package_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "玩家可见文本标点差异清单.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "玩家可见文本标点差异清单.md").write_text(
        markdown(report), encoding="utf-8"
    )
    print(json.dumps({"files": len(report["files_scanned"]), "candidates": report["candidate_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
