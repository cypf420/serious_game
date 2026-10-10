from __future__ import annotations

import hashlib


class ScriptedDeltaResolver:
    """用 session 固定种子把剧本区间稳定解析为整数，保证回放一致。"""

    def resolve(self, minimum: int, maximum: int, *, random_seed: str, source_id: str) -> int:
        if minimum > maximum:
            raise ValueError("minimum must not exceed maximum")
        if minimum == maximum:
            return minimum
        digest = hashlib.sha256(f"{random_seed}:{source_id}".encode("utf-8")).digest()
        offset = int.from_bytes(digest[:8], "big") % (maximum - minimum + 1)
        return minimum + offset
