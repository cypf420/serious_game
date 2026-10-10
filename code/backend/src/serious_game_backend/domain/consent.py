from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def consent_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


SCOPE_SERVICE_STORAGE = "service_storage"
SCOPE_THIRD_PARTY_MODEL = "third_party_model"
SCOPE_RESEARCH_STRUCTURED = "research_structured"
SCOPE_RESEARCH_RAW_TEXT = "research_raw_text"

KNOWN_CONSENT_SCOPES = frozenset({
    SCOPE_SERVICE_STORAGE,
    SCOPE_THIRD_PARTY_MODEL,
    SCOPE_RESEARCH_STRUCTURED,
    SCOPE_RESEARCH_RAW_TEXT,
})


@dataclass(frozen=True, slots=True)
class ConsentDocument:
    consent_version: str
    document_hash: str
    model_provider: str
    processing_region: str
    retention_days_raw_text: int
    published_at: str = field(default_factory=consent_now_iso)
    retired_at: str | None = None


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    consent_record_id: str
    account_id: str
    consent_version: str
    document_hash: str
    scopes: frozenset[str]
    signed_at: str = field(default_factory=consent_now_iso)
    withdrawn_at: str | None = None
    withdrawal_reason: str | None = None

    def grants(self, scope: str) -> bool:
        return self.withdrawn_at is None and scope in self.scopes
