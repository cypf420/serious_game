from __future__ import annotations

from serious_game_backend.domain.enums import AvailabilityMode
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.application.evidence_guidance import source_opportunity


TRUST_BANDS = (
    (19, "closed"),
    (39, "guarded"),
    (69, "working"),
    (100, "trusted"),
)
ATTITUDE_BANDS = (
    (19, "hostile"),
    (39, "resistant"),
    (59, "neutral"),
    (79, "cooperative"),
    (100, "supportive"),
)
ANXIETY_BANDS = (
    (19, "calm"),
    (39, "uneasy"),
    (59, "worried"),
    (79, "strained"),
    (100, "critical"),
)

RELATIONSHIP_BAND_REASONS = {
    "trust": {
        "closed": "对方尚未建立可依赖的信任基础",
        "guarded": "对方仍会谨慎核对你的说法和兑现",
        "working": "对方愿意在已有接触基础上继续沟通",
        "trusted": "多次可见互动已形成较稳定的信任",
        "not_assessed": "目前还没有足够公开互动可作判断",
    },
    "attitude": {
        "hostile": "对方公开表现出明显对立",
        "resistant": "对方仍在抵触当前推进方式",
        "neutral": "对方尚未公开站到支持或反对一边",
        "cooperative": "对方愿意配合当前沟通和核验",
        "supportive": "对方已公开表现出积极支持",
        "not_assessed": "目前还没有足够公开互动可作判断",
    },
    "anxiety": {
        "calm": "公开表现中暂未出现明显担忧",
        "uneasy": "对方对后续安排仍有轻微不安",
        "worried": "对方对自身处境和后续安排有明确担忧",
        "strained": "可见压力已明显影响对方的判断",
        "critical": "公开表现显示对方正承受很强的风险压力",
        "not_assessed": "目前还没有足够公开互动可作判断",
    },
}


def qualitative_band(
    score: int | None,
    bands: tuple[tuple[int, str], ...],
    *,
    untracked: str,
) -> str:
    if score is None:
        return untracked
    return next(label for maximum, label in bands if score <= maximum)


class NPCRelationshipService:
    """Derive and persist player discovery without exposing private scores."""

    @staticmethod
    def synchronize(session: GameSession, package: ScriptPackage) -> None:
        if package.gameplay_schema_version < 4:
            return
        rules = package.npc_discovery_rules or {}
        profiles = {item.npc_id: item for item in package.npc_profiles}
        profile_ids_by_name = {item.name: item.npc_id for item in package.npc_profiles}
        known = set(session.known_npc_ids)
        encountered = set(session.encountered_npc_ids)
        initial_known = rules.get("initial_known_npc_ids")
        if initial_known is None:
            initial_known = (package.governance_config or {}).get(
                "initial_visible_npc_ids", ()
            )
        known.update(
            npc_id
            for npc_id in initial_known
            if npc_id in profiles
        )

        visible_text = "\n".join(
            filter(None, (
                *(item.text for item in session.narrative_feed),
                *(item.speaker for item in session.narrative_feed),
            ))
        )
        for npc_id, profile in profiles.items():
            if profile.name and profile.name in visible_text:
                known.add(npc_id)
        encountered.update(
            profile_ids_by_name[item.speaker]
            for item in session.narrative_feed
            if item.speaker in profile_ids_by_name
        )
        for fact_id in session.known_fact_ids:
            fact = package.facts.get(fact_id)
            if fact is not None:
                known.update(fact.related_npc_ids)
        for log in session.logs:
            if not log.get("visible_to_player", False):
                continue
            for key in ("npc_id", "source_id", "target_npc_id"):
                npc_id = str(log.get(key, ""))
                if npc_id in profiles:
                    known.add(npc_id)
        for npc_id, rule in dict(rules.get("by_npc", {})).items():
            if npc_id not in profiles:
                continue
            if session.game_state.story_day < int(rule.get("known_from_day", 1)):
                continue
            required_flags = set(rule.get("known_required_flags", ()))
            required_facts = set(rule.get("known_required_fact_ids", ()))
            if required_flags.issubset(session.flags) and required_facts.issubset(
                session.known_fact_ids
            ):
                known.add(npc_id)

        session.known_npc_ids = known.intersection(profiles)
        encountered.update(
            item.npc_id for item in session.completed_conversations
        )
        if session.active_conversation is not None:
            encountered.add(session.active_conversation.npc_id)
        encountered.update(
            npc_id
            for action in session.governance_actions.values()
            if action.action_kind != "inspect_archives"
            for npc_id in action.target_ids
            if npc_id in profiles
        )
        if session.active_group_conversation is not None:
            encountered.update(session.active_group_conversation.participant_ids)
        encountered.update(
            str(npc_id)
            for group in session.completed_group_conversations
            for npc_id in group.get("participant_ids", ())
            if str(npc_id) in profiles
        )
        contactable = {
            npc_id
            for npc_id in rules.get("initial_contactable_npc_ids", ())
            if npc_id in session.known_npc_ids
        }
        for opportunity in package.interaction_opportunities:
            if (
                opportunity.npc_id in session.known_npc_ids
                and NPCRelationshipService._base_opportunity_available(
                    opportunity, session
                )
            ):
                contactable.add(opportunity.npc_id)
        if session.active_conversation is not None:
            contactable.add(session.active_conversation.npc_id)
        if session.game_state.story_day >= 90:
            contactable.clear()
        session.contactable_npc_ids = contactable
        encountered.update(contactable)
        session.encountered_npc_ids = encountered.intersection(
            session.known_npc_ids
        )
        NPCRelationshipService._synchronize_edges(session, package)

    @staticmethod
    def actionable_npc_ids(
        session: GameSession,
        package: ScriptPackage,
    ) -> set[str]:
        NPCRelationshipService.synchronize(session, package)
        return set(session.encountered_npc_ids).union(
            session.contactable_npc_ids
        )

    @staticmethod
    def _base_opportunity_available(opportunity, session: GameSession) -> bool:
        opportunity = source_opportunity(opportunity, session)
        if opportunity.availability_mode is AvailabilityMode.CLOSED:
            return False
        day = session.game_state.story_day
        if not opportunity.day_min <= day <= opportunity.day_max:
            return False
        if not opportunity.requires_flags.issubset(session.flags):
            return False
        if not opportunity.requires_events.issubset(session.triggered_events):
            return False
        if opportunity.closes_on_flags.intersection(session.flags):
            return False
        return not any(
            log.get("type") == "conversation_ended"
            and log.get("opportunity_id") == opportunity.opportunity_id
            and log.get("completion_status") == "completed"
            for log in session.logs
        )

    @staticmethod
    def _synchronize_edges(
        session: GameSession, package: ScriptPackage
    ) -> None:
        existing = {
            str(item.get("edge_id")): dict(item)
            for item in session.relationship_edges
            if item.get("edge_id")
        }
        values: list[dict] = []
        for index, configured in enumerate(package.npc_relationships):
            edge_id = str(configured.get("edge_id") or f"relationship_{index}")
            current = existing.get(edge_id, {})
            visibility = str(current.get(
                "visibility", configured.get("initial_visibility", "hidden")
            ))
            reveal = dict(configured.get("visibility_requirements", {}))
            confirmed = (
                bool(set(reveal.get("confirmed_flags", ())) & session.flags)
                or bool(
                    set(reveal.get("confirmed_fact_ids", ()))
                    & session.known_fact_ids
                )
            )
            suspected = (
                bool(set(reveal.get("suspected_flags", ())) & session.flags)
                or bool(
                    set(reveal.get("suspected_fact_ids", ()))
                    & session.known_fact_ids
                )
                or (
                    bool(reveal.get("when_both_known", False))
                    and configured.get("source_npc_id") in session.known_npc_ids
                    and configured.get("target_npc_id") in session.known_npc_ids
                )
            )
            target_visibility = (
                "confirmed" if confirmed else "suspected" if suspected else visibility
            )
            if target_visibility not in {"hidden", "suspected", "confirmed"}:
                target_visibility = "hidden"
            discovered = target_visibility != "hidden"
            values.append({
                "edge_id": edge_id,
                "source_npc_id": str(configured["source_npc_id"]),
                "target_npc_id": str(configured["target_npc_id"]),
                "channel": str(configured.get("channel", "association")),
                "subnetwork": str(configured.get("subnetwork", "")),
                "visibility": target_visibility,
                "discovery_reason": (
                    str(current.get("discovery_reason", ""))
                    or (
                        str(configured.get(
                            f"{target_visibility}_reason",
                            "玩家取得了可说明这段关系的事实。",
                        ))
                        if discovered else ""
                    )
                ),
                "discovery_day": (
                    current.get("discovery_day")
                    if current.get("discovery_day") is not None
                    else session.game_state.story_day if discovered else None
                ),
            })
        session.relationship_edges = values

    @staticmethod
    def relationship_context(session: GameSession, npc_id: str) -> dict[str, str]:
        state = session.npc_states.get(npc_id)
        return {
            "trust_band": qualitative_band(
                state.trust_score if state is not None else None,
                TRUST_BANDS,
                untracked="not_assessed",
            ),
            "attitude_band": qualitative_band(
                state.attitude_score if state is not None else None,
                ATTITUDE_BANDS,
                untracked="not_assessed",
            ),
            "anxiety_band": qualitative_band(
                state.anxiety_score if state is not None else None,
                ANXIETY_BANDS,
                untracked="not_assessed",
            ),
        }

    @staticmethod
    def recent_visible_change_reasons(
        session: GameSession, npc_id: str
    ) -> tuple[str, ...]:
        events = {}
        for item in session.logs:
            if (item.get("type") != "relationship_change" or item.get("npc_id") != npc_id
                    or not item.get("visible_to_player", False) or not str(item.get("reason", "")).strip()):
                continue
            identity = item.get("event_id") or item.get("action_instance_id") or item.get("conversation_id")
            # Legacy logs cannot recover absent event IDs; deduplicate only same-day,
            # same-reason copies, and never merge identical text across different days.
            key = (item.get("story_day"), identity or ("legacy", item["reason"]))
            event = events.setdefault(key, [])
            if item["reason"] not in event:
                event.append(item["reason"])
        numbered = []
        rounds = {}
        for (day, _identity), reasons in events.items():
            rounds[day] = rounds.get(day, 0) + 1
            numbered.append(f"第{day}日·第{rounds[day]}次记录：" + "；".join(reasons))
        return tuple(reversed(numbered[-3:]))

    @staticmethod
    def public_relationship_reasons(
        session: GameSession,
        package: ScriptPackage,
        npc_id: str,
    ) -> dict[str, str]:
        if npc_id not in session.encountered_npc_ids:
            source = NPCRelationshipService.known_source_reason(
                session, package, npc_id
            ).rstrip("。")
            return {
                dimension: f"{source}；尚未与此人直接接触，暂不能判断{label}。"
                for dimension, label in (
                    ("trust", "信任"),
                    ("attitude", "态度"),
                    ("anxiety", "焦虑"),
                )
            }
        context = NPCRelationshipService.relationship_context(session, npc_id)
        latest_by_dimension: dict[str, str] = {}
        for item in reversed(session.logs):
            if (
                item.get("type") != "relationship_change"
                or item.get("npc_id") != npc_id
                or not item.get("visible_to_player", False)
            ):
                continue
            dimension = str(item.get("dimension", ""))
            reason = str(item.get("reason", "")).strip()
            if dimension in {"trust", "attitude", "anxiety"} and reason:
                latest_by_dimension.setdefault(dimension, reason)
        source = NPCRelationshipService.known_source_reason(
            session, package, npc_id
        ).rstrip("。")
        labels = {"trust": "信任", "attitude": "态度", "anxiety": "焦虑"}
        return {
            dimension: latest_by_dimension.get(
                dimension,
                (
                    f"{source}；尚无直接互动改变{labels[dimension]}，"
                    f"{RELATIONSHIP_BAND_REASONS[dimension][context[f'{dimension}_band']]}。"
                ),
            )
            for dimension in ("trust", "attitude", "anxiety")
        }

    @staticmethod
    def known_source_reason(
        session: GameSession,
        package: ScriptPackage,
        npc_id: str,
    ) -> str:
        rules = package.npc_discovery_rules or {}
        initial_known = rules.get("initial_known_npc_ids")
        if initial_known is None:
            initial_known = (package.governance_config or {}).get(
                "initial_visible_npc_ids", ()
            )
        if npc_id in initial_known:
            return "此人已列入开局工作联系名册。"
        if any(
            npc_id in fact.related_npc_ids
            for fact_id, fact in package.facts.items()
            if fact_id in session.known_fact_ids
        ):
            return "已取得的公开材料提到了此人。"
        profile = next(
            (item for item in package.npc_profiles if item.npc_id == npc_id),
            None,
        )
        if profile is not None and any(
            item.speaker == profile.name for item in session.narrative_feed
        ):
            return "当前公开剧情中已经与此人见面。"
        if profile is not None and any(
            profile.name in (item.text or "") for item in session.narrative_feed
        ):
            return "公开卷宗或剧情材料提到了此人。"
        if npc_id in dict(rules.get("by_npc", {})):
            return "随着搬迁工作推进，此人已进入公开工作联系范围。"
        return "已有公开办事记录将此人纳入当前工作联系。"

    @staticmethod
    def public_people(session: GameSession, package: ScriptPackage) -> list[dict]:
        NPCRelationshipService.synchronize(session, package)
        profiles = {item.npc_id: item for item in package.npc_profiles}
        values = []
        for npc_id in sorted(
            session.known_npc_ids,
            key=lambda item: (profiles[item].name, item),
        ):
            if npc_id not in profiles:
                continue
            reasons = NPCRelationshipService.public_relationship_reasons(
                session, package, npc_id
            )
            discovery_state = (
                "contactable"
                if npc_id in session.contactable_npc_ids
                else "encountered"
                if npc_id in session.encountered_npc_ids
                else "mentioned"
            )
            context = (
                NPCRelationshipService.relationship_context(session, npc_id)
                if discovery_state != "mentioned"
                else {
                    "trust_band": "not_assessed",
                    "attitude_band": "not_assessed",
                    "anxiety_band": "not_assessed",
                }
            )
            values.append({
                "npc_id": npc_id,
                "name": profiles[npc_id].name,
                "discovery_state": discovery_state,
                "contact_state": (
                    "contactable"
                    if npc_id in session.contactable_npc_ids else "known"
                ),
                **context,
                "relationship_reasons": reasons,
                "recent_change_reasons": list(NPCRelationshipService.recent_visible_change_reasons(session, npc_id))
                    or list(dict.fromkeys(reasons.values()))[:3],
            })
        return values

    @staticmethod
    def public_edges(session: GameSession, package: ScriptPackage) -> list[dict]:
        NPCRelationshipService.synchronize(session, package)
        encountered = set(session.encountered_npc_ids)
        return [
            dict(item)
            for item in session.relationship_edges
            if item.get("visibility") in {"suspected", "confirmed"}
            and item.get("source_npc_id") in encountered
            and item.get("target_npc_id") in encountered
        ]
