from __future__ import annotations

from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.interaction_opportunity import InteractionOpportunity
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.enums import AvailabilityMode
from serious_game_backend.application.evidence_guidance import source_opportunity
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)


class InteractionOpportunityService:
    def list_available(
        self, session: GameSession, package: ScriptPackage
    ) -> list[InteractionOpportunity]:
        NPCRelationshipService.synchronize(session, package)
        return [
            item
            for item in (source_opportunity(o, session) for o in package.interaction_opportunities)
            if self._is_available(
                item,
                session,
                require_contactable=bool(package.npc_discovery_rules),
            )
        ]

    def require_available(
        self,
        opportunity_id: str,
        session: GameSession,
        package: ScriptPackage,
    ) -> InteractionOpportunity:
        opportunity = next(
            (
                item
                for item in (source_opportunity(o, session) for o in package.interaction_opportunities)
                if item.opportunity_id == opportunity_id
            ),
            None,
        )
        if opportunity is None or not self._is_available(
            opportunity,
            session,
            require_contactable=bool(package.npc_discovery_rules),
        ):
            raise ActionUnavailableError("当前互动机会不可用")
        return opportunity

    @staticmethod
    def _is_available(
        item: InteractionOpportunity,
        session: GameSession,
        *,
        require_contactable: bool = False,
    ) -> bool:
        if item.availability_mode is AvailabilityMode.CLOSED:
            return False
        day = session.game_state.story_day
        if not item.day_min <= day <= item.day_max:
            return False
        if not item.requires_flags.issubset(session.flags):
            return False
        if not item.requires_events.issubset(session.triggered_events):
            return False
        if item.closes_on_flags.intersection(session.flags):
            return False
        if any(
            log.get("type") == "conversation_ended"
            and log.get("opportunity_id") == item.opportunity_id
            and log.get("completion_status") == "completed"
            for log in session.logs
        ):
            return False
        if item.npc_id not in session.npc_states:
            return False
        if require_contactable:
            return item.npc_id in session.contactable_npc_ids
        return True
