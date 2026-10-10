from __future__ import annotations

from dataclasses import dataclass

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.interaction_opportunity import InteractionOpportunity
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.fact_markers import (
    disclosure_markers_for,
    forbidden_fact_signatures,
)


@dataclass(frozen=True, slots=True)
class DisclosureGate:
    trust_tier: int
    trust_label: str
    allowed_fact_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleTurnFactBoundary:
    gate: DisclosureGate
    allowed_fact_texts: dict[str, str]
    allowed_fact_markers: dict[str, tuple[str, ...]]
    required_disclosure_ids: tuple[str, ...]
    forbidden_fact_markers: tuple[str, ...]
    forbidden_fact_signatures: dict[str, tuple[str, ...]]


class DisclosureGateService:
    LABELS = {
        1: "敌对封口",
        2: "戒备提防",
        3: "认可交谈",
        4: "交底托付",
    }

    def build(
        self,
        session: GameSession,
        package: ScriptPackage,
        opportunity: InteractionOpportunity,
        *,
        repeat_count: int = 0,
    ) -> DisclosureGate:
        state = session.npc_states[opportunity.npc_id]
        if state.trust_score is None:
            # 有限角色按剧情白名单说话，不套用数值信任。
            return DisclosureGate(4, "剧情许可", tuple(opportunity.allowed_fact_ids))
        repeat_penalty = 15 if repeat_count >= 2 else 5 if repeat_count == 1 else 0
        effective = max(0, state.trust_score - repeat_penalty)
        tier = 1 if effective <= 25 else 2 if effective <= 50 else 3 if effective <= 75 else 4
        values: list[str] = []
        for fact_id in opportunity.allowed_fact_ids:
            fact = package.facts.get(fact_id)
            if fact is None:
                continue
            if fact.owner_npc_ids and opportunity.npc_id not in fact.owner_npc_ids:
                continue
            if fact.disclosure_tier > tier:
                continue
            if fact.disclosure_tier == 4 and state.chapter_disclosure_used:
                continue
            values.append(fact_id)
        return DisclosureGate(tier, self.LABELS[tier], tuple(values))

    def role_turn_boundary(
        self,
        session: GameSession,
        package: ScriptPackage,
        opportunity: InteractionOpportunity,
        *,
        repeat_count: int = 0,
        player_text: str = "",
    ) -> RoleTurnFactBoundary:
        gate = (
            self.build(session, package, opportunity, repeat_count=repeat_count)
            if package.gameplay_schema_version >= 2
            else DisclosureGate(
                4, "旧包机会白名单", tuple(opportunity.allowed_fact_ids)
            )
        )
        archive_unlock_days = {
            fact_id: min(
                item.unlock_day
                for item in package.archive_investigations
                if fact_id in item.result_fact_ids
            )
            for fact_id in {
                value
                for item in package.archive_investigations
                for value in item.result_fact_ids
            }
        }

        def available_through_this_conversation(fact_id: str) -> bool:
            fact = package.facts.get(fact_id)
            if fact is None:
                return False
            matching_days = [
                int(method["unlock_day"])
                for method in fact.acquisition_methods
                if method.get("route_type") == "conversation"
                and method.get("source_id") == opportunity.opportunity_id
            ]
            if matching_days:
                return min(matching_days) <= session.game_state.story_day
            if fact.acquisition_methods:
                return False
            return archive_unlock_days.get(fact_id, 1) <= session.game_state.story_day

        protocol_fact_ids: set[str] = set()
        normalized_player_text = player_text.casefold()
        for protocol in opportunity.disclosure_protocols:
            groups = tuple(protocol.get("required_term_groups", ()))
            if groups and all(
                any(str(term).casefold() in normalized_player_text for term in group)
                for group in groups
            ):
                protocol_fact_ids.update(
                    str(item) for item in protocol.get("fact_ids", ())
                )
        gate = DisclosureGate(
            gate.trust_tier,
            gate.trust_label,
            tuple(
                fact_id
                for fact_id in gate.allowed_fact_ids
                if fact_id in session.known_fact_ids
                or available_through_this_conversation(fact_id)
            ),
        )
        scoped_protocol_ids = tuple(
            fact_id for fact_id in opportunity.allowed_fact_ids
            if fact_id in protocol_fact_ids
            and available_through_this_conversation(fact_id)
        )
        gate = DisclosureGate(
            gate.trust_tier,
            gate.trust_label,
            tuple(dict.fromkeys((*gate.allowed_fact_ids, *scoped_protocol_ids))),
        )
        permitted = set(gate.allowed_fact_ids) | session.known_fact_ids
        return RoleTurnFactBoundary(
            gate=gate,
            allowed_fact_texts={
                fact_id: package.facts[fact_id].text
                for fact_id in gate.allowed_fact_ids
                if fact_id in package.facts
            },
            allowed_fact_markers=disclosure_markers_for(gate.allowed_fact_ids),
            required_disclosure_ids=tuple(sorted(
                opportunity.required_disclosure_ids.intersection(gate.allowed_fact_ids)
                | set(scoped_protocol_ids)
            )),
            forbidden_fact_markers=tuple(
                fact.title
                for fact_id, fact in package.facts.items()
                if fact_id not in permitted and len(fact.title.strip()) >= 4
            ),
            forbidden_fact_signatures=forbidden_fact_signatures(
                package.facts, permitted
            ),
        )

    def session_boundary(
        self,
        session: GameSession,
        package: ScriptPackage,
        *,
        additional_allowed_fact_ids: tuple[str, ...] = (),
    ) -> RoleTurnFactBoundary:
        """Build the global known-fact boundary for turns without an opportunity."""
        permitted = set(session.known_fact_ids) | set(additional_allowed_fact_ids)
        allowed_ids = tuple(sorted(
            fact_id for fact_id in permitted if fact_id in package.facts
        ))
        return RoleTurnFactBoundary(
            gate=DisclosureGate(4, "已知事实", allowed_ids),
            allowed_fact_texts={
                fact_id: package.facts[fact_id].text for fact_id in allowed_ids
            },
            allowed_fact_markers=disclosure_markers_for(allowed_ids),
            required_disclosure_ids=(),
            forbidden_fact_markers=tuple(
                fact.title
                for fact_id, fact in package.facts.items()
                if fact_id not in permitted and len(fact.title.strip()) >= 4
            ),
            forbidden_fact_signatures=forbidden_fact_signatures(
                package.facts, permitted
            ),
        )
