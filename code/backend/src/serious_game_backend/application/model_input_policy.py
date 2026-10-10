from __future__ import annotations

from dataclasses import dataclass

from serious_game_backend.application.consent_service import ConsentService
from serious_game_backend.domain.consent import SCOPE_THIRD_PARTY_MODEL
from serious_game_backend.infrastructure.privacy import PIIRedactor


@dataclass(frozen=True, slots=True)
class PreparedModelInput:
    text: str
    consent_record_id: str | None
    pii_types: tuple[str, ...]
    replacement_count: int


class ModelInputPolicy:
    def __init__(
        self,
        consents: ConsentService,
        redactor: PIIRedactor,
        *,
        require_model_consent: bool,
    ) -> None:
        self._consents = consents
        self._redactor = redactor
        self._required = require_model_consent

    def prepare(self, account_id: str, player_text: str) -> PreparedModelInput:
        record = (
            self._consents.require_scope(account_id, SCOPE_THIRD_PARTY_MODEL)
            if self._required else None
        )
        redacted = self._redactor.redact(player_text)
        return PreparedModelInput(
            text=redacted.text,
            consent_record_id=(record.consent_record_id if record else None),
            pii_types=redacted.detected_types,
            replacement_count=redacted.replacement_count,
        )
