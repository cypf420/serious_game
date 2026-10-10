from __future__ import annotations

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.gameplay_governance import ArchiveRecord
from serious_game_backend.domain.script_package import (
    ArchiveInvestigationDefinition,
    ScriptPackage,
)


ORIGINAL_ARCHIVE_ID = "archive_compensation_detail_original"
# Author source: 最终剧本.md 4783-4789. Runtime addition preserves locked packages.
COMPENSATION_ORIGINAL = ArchiveInvestigationDefinition(
    archive_id=ORIGINAL_ARCHIVE_ID, title="柳林村补偿明细原件", category="户籍与签约",
    unlock_day=32,
    content="县档案室调出的柳林村补偿明细原件，须与手中的两版台账逐项核对。"
            "同村补偿出现两种标准，三个手印对应的人员常年在外；原件供当场核验，"
            "调阅记录证明你亲眼核对过原件，不等于取得其他档案或儿童检测名册的所有权。",
    evidence_level="E3", confidentiality="机密", result_fact_ids=("fact_false_signing",),
    strategic_uses=("核对原件后回应台账和政策口径质疑", "向罗健具体追问经手的补偿材料"),
)


def investigation_definitions(package: ScriptPackage):
    definitions = package.archive_investigations
    if package.package_id == "pkg_gameplay_v3" and not any(x.archive_id == ORIGINAL_ARCHIVE_ID for x in definitions):
        definitions = (*definitions, COMPENSATION_ORIGINAL)
    return definitions


def apply_original_archive_read(session: GameSession, archive_id: str) -> None:
    record = session.archive_records.get(archive_id)
    if (session.package_id == "pkg_gameplay_v3" and archive_id == ORIGINAL_ARCHIVE_ID
            and record is not None and record.status == "available" and record.read_at_days):
        session.flags.add("见过原件")


def archive_definition(
    package: ScriptPackage,
    archive_id: str,
) -> ArchiveInvestigationDefinition | None:
    return next(
        (
            item
            for item in investigation_definitions(package)
            if item.archive_id == archive_id
        ),
        None,
    )


def first_read_cost(session: GameSession, package: ScriptPackage) -> int:
    tier = package.action_cost_tier(session.game_state.story_day).value
    return 1 if tier == "normal" else 2


def eligible_definitions(
    session: GameSession,
    package: ScriptPackage,
    *,
    unread_only: bool = False,
) -> tuple[ArchiveInvestigationDefinition, ...]:
    result = []
    for item in investigation_definitions(package):
        if item.unlock_day > session.game_state.story_day:
            continue
        record = session.archive_records.get(item.archive_id)
        if unread_only and record is not None and record.read_at_days:
            continue
        result.append(item)
    return tuple(result)


def public_investigation_choice(
    session: GameSession,
    package: ScriptPackage,
    item: ArchiveInvestigationDefinition,
) -> dict:
    record = session.archive_records.get(item.archive_id)
    is_read = bool(record is not None and record.read_at_days)
    return {
        "target_id": item.archive_id,
        "label": item.title,
        "archive_id": item.archive_id,
        "title": item.title,
        "category": item.category,
        "evidence_level": item.evidence_level,
        "confidentiality": item.confidentiality,
        "first_read_cost_action_points": first_read_cost(session, package),
        "read_status": "read" if is_read else "unread",
        "result_fact_count": len(item.result_fact_ids),
        "strategic_uses": list(item.strategic_uses),
    }


def materialize_for_read(
    session: GameSession,
    item: ArchiveInvestigationDefinition,
) -> ArchiveRecord:
    record = session.archive_records.get(item.archive_id)
    if record is None:
        record = ArchiveRecord(
            archive_id=item.archive_id,
            category=item.category,
            title=item.title,
            content=item.content,
            source_type="archive_investigation",
            source_id=item.archive_id,
            acquired_day=item.unlock_day,
            acquired_via=f"story_day_unlock:D{item.unlock_day}",
            evidence_level=item.evidence_level,
            confidentiality=item.confidentiality,
        )
        session.archive_records[item.archive_id] = record
    else:
        record.category = item.category
        record.title = item.title
        record.evidence_level = item.evidence_level
        record.confidentiality = item.confidentiality
    if item.archive_id == ORIGINAL_ARCHIVE_ID:
        record.related_npc_ids = ("npc_luo_jian", "npc_zhang_li", "npc_zhao_jianguo", "npc_sun_qiang")
    return record
