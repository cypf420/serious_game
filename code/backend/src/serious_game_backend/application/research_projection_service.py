from __future__ import annotations

import hashlib
import hmac
import secrets

from serious_game_backend.application.consent_service import ConsentService
from serious_game_backend.domain.action import ActionCommand
from serious_game_backend.domain.consent import (
    SCOPE_RESEARCH_RAW_TEXT,
    SCOPE_RESEARCH_STRUCTURED,
)
from serious_game_backend.domain.research import ResearchEvent
from serious_game_backend.infrastructure.crypto import FieldCipher


class ResearchProjectionService:
    """Builds pseudonymous events; persistence is handled by the transaction outbox."""

    def __init__(
        self,
        consents: ConsentService,
        *,
        public_id_salt: str,
        field_cipher: FieldCipher | None,
    ) -> None:
        self._consents = consents
        self._salt = public_id_salt.encode("utf-8")
        self._cipher = field_cipher

    def build_action_event(self, session, command: ActionCommand, draft: dict) -> ResearchEvent | None:
        if not session.research_subject_id:
            return None
        try:
            consent = self._consents.require_scope(
                session.account_id, SCOPE_RESEARCH_STRUCTURED
            )
        except Exception:
            return None
        raw_ciphertext = None
        if (
            command.player_text
            and consent.grants(SCOPE_RESEARCH_RAW_TEXT)
            and self._cipher is not None
        ):
            raw_ciphertext = self._cipher.encrypt_text(
                command.player_text, purpose="research_player_text"
            )
        privacy = draft.get("privacy") or {}
        structured = {
            "input_mode": command.input_mode.value,
            "action_id": command.action_id,
            "opportunity_id": command.opportunity_id,
            "target_npc_id": command.target_npc_id,
            "decision_id": command.decision_id,
            "option_id": command.option_id,
            "ordered_option_count": len(command.ordered_option_ids),
            "result_kind": draft.get("kind"),
            "pii_types": list(privacy.get("pii_types", ())),
            "pii_replacement_count": int(privacy.get("replacement_count", 0)),
        }
        public_session_id = hmac.new(
            self._salt,
            session.session_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return ResearchEvent(
            research_event_id=f"re_{secrets.token_hex(16)}",
            research_subject_id=session.research_subject_id,
            experiment_id=session.experiment_id,
            experiment_group_id=session.experiment_group_id,
            session_public_id=f"rsp_{public_session_id}",
            event_type="game_action",
            story_day=session.game_state.story_day,
            structured_payload=structured,
            raw_text_ciphertext=raw_ciphertext,
            consent_record_id=consent.consent_record_id,
        )
