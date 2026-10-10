from __future__ import annotations

from dataclasses import replace
import hashlib

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


class TrustDerivationService:
    """按已发生旗标一次性派生人物信任；不会向玩家投影数值。"""

    def apply(self, session: GameSession, package: ScriptPackage) -> None:
        rules = package.trust_rules or {}
        base = int(rules.get("base", 40))
        villagers = set(rules.get("common_villager_ids", ()))
        common = dict(rules.get("common_flag_effects", {}))
        specific = dict(rules.get("npc_flag_effects", {}))
        aliases = dict(rules.get("aliases", {}))
        active_flags = set(session.flags)
        active_flags.update(
            canonical for source, canonical in aliases.items()
            if source in session.flags
        )
        crowd = tuple(rules.get("crowd_effects", ()))

        for npc_id, state in tuple(session.npc_states.items()):
            if state.trust_score is None or state.trust_locked:
                continue
            applied = set(state.trust_effects_applied)
            score = state.trust_score
            locked = False
            candidates: list[tuple[str, int | str]] = []
            if npc_id in villagers:
                candidates.extend(common.items())
            candidates.extend(dict(specific.get(npc_id, {})).items())
            for flag, effect in candidates:
                canonical = str(aliases.get(flag, flag))
                effect_key = f"flag:{canonical}"
                if flag not in active_flags or effect_key in applied:
                    continue
                applied.add(effect_key)
                if effect == "lock":
                    score, locked = 0, True
                    break
                score = max(0, min(100, score + int(effect)))
            if not locked:
                for item in crowd:
                    if npc_id not in set(item.get("npc_ids", ())):
                        continue
                    threshold = float(item["threshold_percent"])
                    signed_percent = session.game_state.signed_households / 36 * 100
                    effect_key = f"crowd_percent:{threshold:g}"
                    if signed_percent <= threshold or effect_key in applied:
                        continue
                    applied.add(effect_key)
                    score = max(0, min(100, score + int(item.get("delta", 15))))
            if not locked:
                freeze_after = int(
                    rules.get("explicit_freeze_after_day", {}).get(npc_id, 90)
                )
                explicit_flags = dict(
                    rules.get("explicit_flag_effects", {}).get(npc_id, {})
                )
                if session.game_state.story_day <= freeze_after:
                    for flag, bounds in explicit_flags.items():
                        effect_key = f"explicit_flag:{flag}"
                        if flag not in active_flags or effect_key in applied:
                            continue
                        score = self._apply_bounds(
                            score,
                            bounds,
                            random_seed=session.random_seed,
                            npc_id=npc_id,
                            effect_key=effect_key,
                        )
                        applied.add(effect_key)
                explicit = dict(
                    rules.get("explicit_decision_effects", {}).get(npc_id, {})
                )
                for log in session.logs:
                    if log.get("type") != "decision" or int(log.get("story_day", 0)) > freeze_after:
                        continue
                    key = f"{log.get('decision_id')}:{log.get('option_id')}"
                    effect_key = f"decision:{key}"
                    if key not in explicit or effect_key in applied:
                        continue
                    bounds = explicit[key]
                    if isinstance(bounds, dict):
                        required_flag = str(bounds.get("required_flag", ""))
                        bounds = (
                            bounds.get("when_present")
                            if required_flag in active_flags
                            else bounds.get("otherwise")
                        )
                    if bounds is None:
                        continue
                    score = self._apply_bounds(
                        score,
                        bounds,
                        random_seed=session.random_seed,
                        npc_id=npc_id,
                        effect_key=effect_key,
                    )
                    applied.add(effect_key)
            # 老存档中若没有可信派生记录，仍从统一初值开始。
            if not applied and state.trust_score is None:
                score = base
            session.npc_states[npc_id] = replace(
                state,
                trust_score=0 if locked else score,
                trust_locked=locked,
                trust_effects_applied=frozenset(applied),
            )

    @staticmethod
    def _apply_bounds(
        score: int,
        bounds,
        *,
        random_seed: str,
        npc_id: str,
        effect_key: str,
    ) -> int:
        minimum, maximum = int(bounds[0]), int(bounds[1])
        if minimum > maximum:
            raise ValueError(f"人物信任区间上下界倒置：{npc_id}:{effect_key}")
        digest = hashlib.sha256(
            f"{random_seed}:{npc_id}:{effect_key}".encode("utf-8")
        ).digest()
        delta = minimum + int.from_bytes(digest[:4], "big") % (
            maximum - minimum + 1
        )
        return max(0, min(100, score + delta))
