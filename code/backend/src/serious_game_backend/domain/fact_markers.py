from __future__ import annotations

import unicodedata

from serious_game_backend.domain.story import FactDefinition


FACT_DISCLOSURE_MARKERS: dict[str, tuple[str, ...]] = {
    "fact_clan_power_map": (
        "三大家族",
        "周家、何家、杨家",
        "周氏宗族",
        "散姓",
    ),
    "fact_wu_independent_voice": ("按姓分肥", "不怕周大山"),
    "fact_connected_invoices": ("连号发票", "八十七万"),
    "fact_original_vouchers": ("四十一张原始凭证", "41张原始凭证"),
    "fact_identical_reports": ("三份一模一样的报告",),
    "fact_liu_old_ledger": ("老账底稿", "前年那本账"),
    "fact_shi_usb": ("优盘", "u盘"),
    "fact_eia_original": ("环评原始数据",),
    "fact_water_sample": ("封存水样",),
    "fact_lead_census": ("血铅普查总表", "受检107", "受检 107"),
    "fact_lead_287": ("血铅二八七", "血铅287", "血铅 287"),
    "fact_false_signing": ("真假签约台账", "账面签约", "真实签约"),
    "fact_grave_protocol": ("择地、择日、起灵、祭祀",),
    "fact_zhou_ledger_order": ("三环顺序", "先摊台账", "最后才谈钱"),
    "fact_two_million_fee": ("两百万前期协调费", "200万前期协调费"),
    "fact_shell_house": ("样板房与毛坯房", "样板房和毛坯房"),
    "fact_inspection_anchors": ("三组检查时点",),
    "fact_total_households": ("三十六户总盘",),
}


def disclosure_markers_for(fact_ids: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    return {
        fact_id: FACT_DISCLOSURE_MARKERS.get(fact_id, ())
        for fact_id in fact_ids
    }


def normalize_fact_signature(value: str) -> str:
    """Normalize formatting variants without turning short generic words into bans."""
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def fact_safety_signature(fact: FactDefinition) -> tuple[str, ...]:
    """Build a deterministic, specific signature from authoritative fact fields."""
    derived_candidates: list[tuple[str, int]] = [
        (fact.fact_id, 8),
        (fact.title, 4),
        (fact.text, 8),
        (fact.source_label, 8),
        (fact.use_hint, 12),
    ]
    if fact.text.startswith(fact.title):
        remainder = fact.text[len(fact.title):].lstrip("的：:，,；;。 ")
        derived_candidates.append((remainder, 8))
    values: list[str] = []
    for raw in FACT_DISCLOSURE_MARKERS.get(fact.fact_id, ()):
        normalized = normalize_fact_signature(raw)
        if normalized and normalized not in values:
            values.append(normalized)
    for raw, minimum_length in derived_candidates:
        normalized = normalize_fact_signature(raw)
        if len(normalized) < minimum_length or normalized in values:
            continue
        values.append(normalized)
    return tuple(values)


def forbidden_fact_signatures(
    facts: dict[str, FactDefinition],
    permitted_fact_ids: set[str],
) -> dict[str, tuple[str, ...]]:
    values: dict[str, tuple[str, ...]] = {}
    for fact_id, fact in facts.items():
        if fact_id in permitted_fact_ids:
            continue
        signature = fact_safety_signature(fact)
        if signature:
            values[fact_id] = signature
    return values
