from __future__ import annotations

from dataclasses import replace
import secrets

from serious_game_backend.application.ports import ConsentRepository
from serious_game_backend.domain.consent import (
    KNOWN_CONSENT_SCOPES,
    SCOPE_RESEARCH_RAW_TEXT,
    SCOPE_RESEARCH_STRUCTURED,
    ConsentDocument,
    ConsentRecord,
    consent_now_iso,
)
from serious_game_backend.domain.errors import ConsentRequiredError, ConsentVersionError


class ConsentService:
    def __init__(
        self,
        repository: ConsentRepository,
        *,
        active_version: str,
        active_document_hash: str,
    ) -> None:
        self._repository = repository
        self.active_version = active_version
        self.active_document_hash = active_document_hash

    def publish(self, document: ConsentDocument) -> None:
        self._repository.publish_document(document)

    def sign(self, *, account_id: str, consent_version: str, scopes: frozenset[str]) -> ConsentRecord:
        if consent_version != self.active_version:
            raise ConsentVersionError("必须签署当前有效的知情同意版本")
        document = self._repository.get_document(consent_version)
        if document is None or document.document_hash != self.active_document_hash:
            raise ConsentVersionError("知情同意文档不存在或内容哈希不匹配")
        unknown = scopes - KNOWN_CONSENT_SCOPES
        if unknown:
            raise ConsentVersionError(
                "知情同意包含未知授权范围", details={"unknown_scopes": sorted(unknown)}
            )
        if SCOPE_RESEARCH_RAW_TEXT in scopes and SCOPE_RESEARCH_STRUCTURED not in scopes:
            raise ConsentVersionError("原文研究授权必须同时包含结构化研究授权")
        record = ConsentRecord(
            consent_record_id=f"consent_{secrets.token_hex(16)}",
            account_id=account_id,
            consent_version=document.consent_version,
            document_hash=document.document_hash,
            scopes=scopes,
        )
        self._repository.create_record(record)
        return record

    def withdraw(self, *, account_id: str, reason: str | None = None) -> ConsentRecord:
        record = self._repository.latest_for_account(account_id)
        if record is None:
            raise ConsentRequiredError("当前账号没有可撤回的知情同意记录")
        if record.withdrawn_at is not None:
            return record
        updated = replace(
            record,
            withdrawn_at=consent_now_iso(),
            withdrawal_reason=(reason or "").strip() or None,
        )
        self._repository.save_record(updated)
        return updated

    def latest(self, account_id: str) -> ConsentRecord | None:
        return self._repository.latest_for_account(account_id)

    def require_scope(self, account_id: str, scope: str) -> ConsentRecord:
        record = self._repository.latest_for_account(account_id)
        if (
            record is None
            or record.consent_version != self.active_version
            or record.document_hash != self.active_document_hash
            or not record.grants(scope)
        ):
            raise ConsentRequiredError(
                "当前操作需要有效的知情同意",
                details={"required_scope": scope, "consent_version": self.active_version},
            )
        return record
