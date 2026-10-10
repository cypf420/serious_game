from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    detected_types: tuple[str, ...]
    replacement_count: int


class PIIRedactor:
    """发送第三方模型前的确定性最小化；不替代人工风险评估。"""

    _patterns = (
        ("email", re.compile(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")),
        ("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
        ("national_id", re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\w)")),
        ("bank_card", re.compile(r"(?<!\d)(?:\d[ -]?){16,19}(?!\d)")),
        ("ipv4", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
        (
            "address",
            re.compile(
                r"[\u4e00-\u9fff]{2,}(?:省|自治区|市|县|区)[\u4e00-\u9fff0-9]{2,}"
                r"(?:路|街|巷|村|镇|乡|号|栋|单元|室)"
            ),
        ),
    )

    def redact(self, text: str) -> RedactionResult:
        value = text
        detected: list[str] = []
        count = 0
        for kind, pattern in self._patterns:
            value, replacements = pattern.subn(f"[已脱敏:{kind}]", value)
            if replacements:
                detected.append(kind)
                count += replacements
        return RedactionResult(value, tuple(detected), count)
