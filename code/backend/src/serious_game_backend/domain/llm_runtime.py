from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def runtime_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class LLMCallAudit:
    audit_id: str
    session_id: str
    account_id: str
    operation_id: str
    story_day: int
    npc_id: str
    provider: str
    model_id: str
    prompt_version: str
    request_hash: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    retry_count: int = 0
    response_hash: str | None = None
    validated_result: dict | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=runtime_now_iso)
    endpoint_host: str | None = None
    config_version: str | None = None
    source_audit_id: str | None = None


@dataclass(frozen=True, slots=True)
class NPCMemory:
    memory_id: str
    session_id: str
    account_id: str
    npc_id: str
    source_operation_id: str
    content: str
    memory_type: str
    keywords: tuple[str, ...]
    valid_from_day: int
    expires_after_day: int | None = None
    actor_id: str = ""
    commitment_content: str | None = None
    due_day: int | None = None
    resolution_state: str = "observed"
    invalidated_at: str | None = None
    created_at: str = field(default_factory=runtime_now_iso)

    def is_active(self, story_day: int) -> bool:
        return (
            self.invalidated_at is None
            and self.valid_from_day <= story_day
            and (
                self.expires_after_day is None
                or story_day <= self.expires_after_day
            )
        )
