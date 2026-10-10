from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_request_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(normalized).hexdigest()}"
