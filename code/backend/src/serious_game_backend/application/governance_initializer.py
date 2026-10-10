from __future__ import annotations

import hashlib
import json

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.gameplay_governance import (
    AdministrativeDocument,
    ArchiveRecord,
)
from serious_game_backend.domain.script_package import ScriptPackage


def initialize_governance_state(
    session: GameSession, package: ScriptPackage
) -> None:
    config = package.governance_config or {}
    day = session.game_state.story_day
    background = (
        (
            "archive_project_brief",
            "项目背景",
            "清江搬迁项目简报",
            json.dumps(
                package.public_briefing.get("mission", {}),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "public_briefing",
        ),
        (
            "archive_household_registry",
            "逐户底账",
            "柳林村36户基础底账",
            json.dumps(
                [
                    {
                        "household_id": item.household_id,
                        "registered_population": item.registered_population,
                        "resettlement_population": item.resettlement_population,
                        "legal_residential_area_m2": item.legal_residential_area_m2,
                        "homestead_recognized_m2": item.homestead_recognized_m2,
                        "contracted_land_mu": item.contracted_land_mu,
                        "ownership_status": item.ownership_status,
                    }
                    for item in package.households
                ],
                ensure_ascii=False,
                sort_keys=True,
            ),
            "households",
        ),
        (
            "archive_resource_ledger",
            "项目资源",
            "项目预算与资源底账",
            json.dumps(
                {
                    "budget_envelopes": config.get("budget_envelopes", {}),
                    "resource_pools": config.get("resource_pools", []),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            "governance_config",
        ),
    )
    for archive_id, category, title, content, source_id in background:
        session.archive_records[archive_id] = ArchiveRecord(
            archive_id=archive_id,
            category=category,
            title=title,
            content=content,
            source_type="background",
            source_id=source_id,
            acquired_day=day,
            acquired_via="new_game",
            evidence_level="E1",
            confidentiality="internal",
        )

    for item in config.get("initial_documents", []):
        content = str(item["content"])
        content_hash = _sha256(content)
        archive_id = f"archive:{item['document_id']}"
        document = AdministrativeDocument(
            document_id=str(item["document_id"]),
            document_type=str(item["document_type"]),
            title=str(item["title"]),
            status=str(item["status"]),
            version=1,
            content=content,
            story_day=day,
            policy_version=str(item["policy_version"]),
            required_countersign_ids=tuple(
                item.get("required_countersign_ids", ())
            ),
            countersigned_by=tuple(
                item.get("required_countersign_ids", ())
            ),
            public_scope=tuple(item.get("public_scope", ())),
            content_hash=content_hash,
            issued_day=day,
            archive_id=archive_id,
        )
        session.administrative_documents[document.document_id] = document
        session.archive_records[archive_id] = ArchiveRecord(
            archive_id=archive_id,
            category="政策与红头文件",
            title=document.title,
            content=document.content,
            source_type="administrative_document",
            source_id=document.document_id,
            acquired_day=day,
            acquired_via="new_game",
            evidence_level="E3",
            confidentiality="public",
        )


def sync_known_facts_to_archives(
    session: GameSession, package: ScriptPackage
) -> None:
    investigation_fact_ids = {
        fact_id
        for item in package.archive_investigations
        for fact_id in item.result_fact_ids
    }
    for fact_id in sorted(session.known_fact_ids):
        if fact_id in investigation_fact_ids:
            continue
        fact = package.facts.get(fact_id)
        if fact is None:
            continue
        archive_id = f"archive:fact:{fact_id}"
        if archive_id in session.archive_records:
            continue
        session.archive_records[archive_id] = ArchiveRecord(
            archive_id=archive_id,
            category="线索档案" if fact.category != "evidence" else "证据档案",
            title=fact.title,
            content=fact.text,
            source_type="story_fact",
            source_id=fact_id,
            acquired_day=session.game_state.story_day,
            acquired_via=f"story_unlock:{fact_id}",
            evidence_level="E2" if fact.category == "evidence" else "E1",
            confidentiality="internal",
            related_npc_ids=tuple(fact.related_npc_ids),
        )


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
