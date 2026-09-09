"""Read-only punctuation inventory across script sources, packages and renderers."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import re

CHINESE = re.compile(r"[\u3400-\u9fff]")
PATTERNS = {
    "redundant_period_after_quote": re.compile(r"[。！？…][”’」』]+[ \t\u3000]*。+"),
    "repeated_punctuation": re.compile(r"。{2,}|，{2,}|[，；：][。！？]|[。！？][，；：]"),
    "replacement_character": re.compile("\ufffd"),
    "corner_quotes": re.compile("[「」『』]"),
    "ascii_punctuation": re.compile(r"(?<=[\u3400-\u9fff])[,;:!?]|[,;:!?](?=[\u3400-\u9fff])"),
    "short_ellipsis": re.compile(r"(?<!…)…(?!…)|(?<!\.)\.{3}(?!\.)"),
}


def quote_issues(text):
    stack = []
    errors = set()
    pairs = {"“": "”", "‘": "’", "「": "」", "『": "』"}
    for i, char in enumerate(text):
        if char == "’" and i and i + 1 < len(text) and text[i - 1].isascii() and text[i - 1].isalpha() and text[i + 1].isascii() and text[i + 1].isalpha():
            continue
        if char in pairs:
            if stack and char in ("“", "「") and stack[-1] in ("”", "」"):
                errors.add("nested_double_quotes")
            stack.append(pairs[char])
        elif char in pairs.values():
            if not stack or stack.pop() != char:
                errors.add("unbalanced_quotes")
    if stack:
        errors.add("unbalanced_quotes")
    return errors


def json_strings(value, pointer=""):
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from json_strings(child, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from json_strings(child, f"{pointer}/{index}")


def audit(root):
    roots = [root / "code/backend/content", root / "code/backend/src", root / "code/backend/tools",
             root / "code/frontend/web/app", root / "code/frontend/terminal", root / "docs/game_design"]
    paths = {root / "最终剧本.md"}
    for folder in roots:
        paths.update(p for p in folder.rglob("*") if p.suffix in {".json", ".py", ".ts", ".tsx", ".md", ".txt", ".html"}
                     and not any(part in {"__pycache__", "node_modules", ".venv"} for part in p.parts))
    findings, inventory = [], []
    for path in sorted(paths):
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8-sig")
        full_text = path.suffix in {".json", ".py"}
        if path.suffix == ".json":
            records = list(json_strings(json.loads(source)))
        elif path.suffix == ".py":
            records = [(f"line:{n.lineno}", n.value) for n in ast.walk(ast.parse(source))
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        else:
            records = [(f"line:{i}", line) for i, line in enumerate(source.splitlines(), 1)]
        chinese_records = [(pointer, text) for pointer, text in records if CHINESE.search(text)]
        inventory.append({"file": path.relative_to(root).as_posix(), "chinese_records": len(chinese_records)})
        for pointer, text in chinese_records:
            issues = {name for name, pattern in PATTERNS.items() if pattern.search(text)}
            if full_text:
                issues.update(quote_issues(text))
                if '"' in text:
                    issues.add("ascii_double_quotes")
            for issue in sorted(issues):
                findings.append({"file": path.relative_to(root).as_posix(), "pointer": pointer,
                                 "issue": issue, "text": text})
    return {"files": inventory, "findings": findings,
            "counts": dict(Counter(item["issue"] for item in findings)),
            "note": "Candidates require context review; source conventions, code examples, fragments and historical packages are not automatically rewritten."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(result["files"]), "chinese_records": sum(f["chinese_records"] for f in result["files"]),
                      "counts": result["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
