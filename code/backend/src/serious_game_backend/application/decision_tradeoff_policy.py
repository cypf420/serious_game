from __future__ import annotations


VISIBLE_DECISION_METRICS = {
    "public_trust", "social_stability", "political_credit",
    "media_pressure", "cadre_discontent",
}


def normalize_direction(delta: tuple[int, int]) -> tuple[int, int]:
    minimum, maximum = delta
    if minimum == 0 < maximum:
        return 1, maximum
    if minimum < 0 == maximum:
        return minimum, -1
    return minimum, maximum


def player_facing_metric_deltas(option) -> dict[str, tuple[int, int]]:
    """为非纯叙事选项提供最小、确定方向的即时权衡。"""

    existing = {
        field: normalize_direction(delta)
        for field, delta in option.effects.metric_deltas.items()
        if field in VISIBLE_DECISION_METRICS and delta != (0, 0)
    }
    result = dict(existing)
    text = f"{option.text} {option.consequence}"
    if not result:
        if any(word in text for word in ("强制", "清场", "施压", "隔离", "硬压")):
            result = {"social_stability": (2, 2), "public_trust": (-3, -3)}
        elif any(word in text for word in ("暂缓", "拖", "搁置", "按下", "不处理")):
            result = {"social_stability": (1, 1), "political_credit": (-2, -2)}
        elif any(word in text for word in ("医疗", "救助", "民生", "入户", "安置", "就业")):
            result = {"public_trust": (2, 2), "political_credit": (-1, -1)}
        elif any(word in text for word in ("公开", "记者", "报道", "据实", "真相")):
            result = {"public_trust": (2, 2), "media_pressure": (2, 2)}
        elif any(word in text for word in ("审计", "程序", "法", "移交", "封存", "核查")):
            result = {"political_credit": (2, 2), "cadre_discontent": (1, 1)}
        elif any(word in text for word in ("补偿", "钱", "提高", "追加")):
            result = {"public_trust": (2, 2), "political_credit": (-1, -1)}
        else:
            result = {"political_credit": (1, 1), "cadre_discontent": (1, 1)}

    valences = {_valence(field, delta) for field, delta in result.items()}
    if "benefit" not in valences:
        added = False
        for field in ("political_credit", "social_stability", "public_trust"):
            if field not in result:
                result[field] = (1, 1)
                added = True
                break
        if not added:
            for field in ("media_pressure", "cadre_discontent"):
                if field not in result:
                    result[field] = (-1, -1)
                    added = True
                    break
        if not added:
            result["social_stability"] = (1, 1)
    if "cost" not in valences:
        added = False
        for field in ("cadre_discontent", "media_pressure"):
            if field not in result:
                result[field] = (1, 1)
                added = True
                break
        if not added:
            if "political_credit" not in result:
                result["political_credit"] = (-1, -1)
                added = True
        if not added:
            result["cadre_discontent"] = (1, 1)
    return result


def _valence(field: str, delta: tuple[int, int]) -> str:
    minimum, maximum = delta
    positive = minimum > 0 and maximum > 0
    negative_metric = field in {"media_pressure", "cadre_discontent"}
    return "benefit" if positive != negative_metric else "cost"
