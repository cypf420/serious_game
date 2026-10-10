from __future__ import annotations

from typing import Protocol

from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.llm import (
    ExpressionResult,
    ExpressionTask,
    GovernanceLLMContext,
    GovernanceLLMResult,
    NightAgentContext,
    NightAgentResult,
    RoleTurnContext,
    RoleTurnResult,
    SelectionResult,
    SelectionTask,
)
from serious_game_backend.domain.llm_runtime import LLMCallAudit, NPCMemory
from serious_game_backend.domain.operation import OperationRecord
from serious_game_backend.domain.snapshots import GameSnapshot, ManualSaveSlot
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.consent import ConsentDocument, ConsentRecord
from serious_game_backend.domain.identity import Account, AuthSession
from serious_game_backend.domain.research import (
    ExperimentAssignment,
    ResearchEvent,
    ResearchSubject,
)
from serious_game_backend.domain.governance import (
    DataSubjectRequest,
    ExportJob,
    PrivilegedAccessAudit,
    RetentionResult,
)


class GameSessionRepository(Protocol):
    def create(self, session: GameSession) -> None: ...

    def get_owned(self, session_id: str, account_id: str) -> GameSession | None: ...

    def latest_active(self, account_id: str) -> GameSession | None: ...

    def list_for_account(self, account_id: str) -> tuple[GameSession, ...]: ...

    def save(self, session: GameSession, *, expected_version: int) -> None: ...


class OperationRepository(Protocol):
    def get(
        self,
        account_id: str,
        session_id: str,
        client_action_id: str,
    ) -> OperationRecord | None: ...

    def create(self, operation: OperationRecord) -> None: ...

    def save(self, operation: OperationRecord) -> None: ...


class SessionRequestRepository(Protocol):
    def get(self, account_id: str, client_request_id: str) -> OperationRecord | None: ...

    def create(self, request: OperationRecord) -> None: ...

    def save(self, request: OperationRecord) -> None: ...


class RuntimeTransactionRepository(Protocol):
    def recover_stale_operations(self, stale_before: str) -> int: ...

    def reserve_operation(
        self,
        session: GameSession,
        *,
        expected_version: int,
        operation: OperationRecord,
        create_operation: bool,
    ) -> None: ...

    def finish_operation(
        self,
        session: GameSession,
        *,
        expected_version: int,
        operation: OperationRecord,
        research_event: ResearchEvent | None = None,
    ) -> None: ...

    def complete_session_request(
        self,
        session: GameSession,
        request: OperationRecord,
    ) -> None: ...


class SnapshotRepository(Protocol):
    def commit_session_snapshot(
        self,
        session: GameSession,
        *,
        expected_version: int,
        snapshot_type: str,
        reason: str,
    ) -> GameSnapshot: ...

    def get_owned(
        self, account_id: str, session_id: str, snapshot_id: str
    ) -> GameSnapshot | None: ...

    def current_for_session(
        self, session: GameSession
    ) -> GameSnapshot | None: ...

    def list_manual_slots(
        self, account_id: str, session_id: str
    ) -> tuple[tuple[ManualSaveSlot, GameSnapshot], ...]: ...

    def list_history(
        self, account_id: str, session_id: str, *, limit: int = 20
    ) -> tuple[GameSnapshot, ...]: ...

    def create_manual_save(
        self,
        session: GameSession,
        *,
        snapshot: GameSnapshot,
        slot_number: int,
        display_name: str,
        overwrite: bool,
        operation: OperationRecord,
    ) -> tuple[ManualSaveSlot, GameSnapshot]: ...

    def commit_load(
        self,
        current: GameSession,
        restored: GameSession,
        *,
        expected_version: int,
        source_snapshot: GameSnapshot,
        result_snapshot: GameSnapshot,
        operation: OperationRecord,
    ) -> None: ...


class ScriptPackageRepository(Protocol):
    def get(self, package_id: str) -> ScriptPackage | None: ...


class RoleLLMGateway(Protocol):
    def select(self, task: SelectionTask) -> SelectionResult: ...

    def express(self, task: ExpressionTask) -> ExpressionResult: ...

    def run_turn(self, context: RoleTurnContext) -> RoleTurnResult: ...

    def run_night_turn(self, context: NightAgentContext) -> NightAgentResult: ...

    def run_governance_task(
        self, context: GovernanceLLMContext
    ) -> GovernanceLLMResult: ...


class LLMCallAuditRepository(Protocol):
    def save(self, audit: LLMCallAudit) -> None: ...

    def successful_for_operation(
        self, *, account_id: str, session_id: str, operation_id: str,
        request_hash: str, config_version: str, endpoint_host: str,
    ) -> LLMCallAudit | None: ...

    def list_for_owned_session(
        self, account_id: str, session_id: str, *, after: str, limit: int
    ) -> tuple[LLMCallAudit, ...]: ...

    def list_for_session(self, session_id: str) -> tuple[LLMCallAudit, ...]: ...


class NPCMemoryRepository(Protocol):
    def save(self, memory: NPCMemory) -> None: ...

    def active_for_npc(
        self, session_id: str, npc_id: str, story_day: int
    ) -> tuple[NPCMemory, ...]: ...

    def invalidate(self, memory_ids: tuple[str, ...], invalidated_at: str) -> None: ...


class AccountRepository(Protocol):
    def create(self, account: Account) -> None: ...

    def get_by_id(self, account_id: str) -> Account | None: ...

    def get_by_username(self, username: str) -> Account | None: ...


class AuthSessionRepository(Protocol):
    def create(self, session: AuthSession) -> None: ...

    def get(self, token_hash: str) -> AuthSession | None: ...

    def save(self, session: AuthSession) -> None: ...


class ConsentRepository(Protocol):
    def publish_document(self, document: ConsentDocument) -> None: ...

    def get_document(self, consent_version: str) -> ConsentDocument | None: ...

    def create_record(self, record: ConsentRecord) -> None: ...

    def get_record(self, consent_record_id: str) -> ConsentRecord | None: ...

    def latest_for_account(self, account_id: str) -> ConsentRecord | None: ...

    def save_record(self, record: ConsentRecord) -> None: ...


class ResearchIdentityRepository(Protocol):
    def get_or_create(self, account_id: str) -> ResearchSubject: ...

    def get_for_account(self, account_id: str) -> ResearchSubject | None: ...


class ExperimentAssignmentRepository(Protocol):
    def create(self, assignment: ExperimentAssignment) -> None: ...

    def get_for_subject(
        self, research_subject_id: str, experiment_id: str
    ) -> ExperimentAssignment | None: ...


class ResearchEventRepository(Protocol):
    def append(self, event: ResearchEvent) -> None: ...

    def list_for_subject(
        self, research_subject_id: str
    ) -> tuple[ResearchEvent, ...]: ...


class GovernanceRepository(Protocol):
    def create_export(self, job: ExportJob) -> None: ...

    def get_export(self, export_job_id: str) -> ExportJob | None: ...

    def save_export(self, job: ExportJob) -> None: ...

    def research_export_rows(self, conditions: dict) -> tuple[dict, ...]: ...

    def create_subject_request(self, request: DataSubjectRequest) -> None: ...

    def get_subject_request(self, request_id: str) -> DataSubjectRequest | None: ...

    def save_subject_request(self, request: DataSubjectRequest) -> None: ...

    def subject_data(self, account_id: str) -> dict: ...

    def erase_subject(self, account_id: str) -> dict: ...

    def append_privileged_audit(self, audit: PrivilegedAccessAudit) -> None: ...

    def apply_retention(self, *, cutoff_at: str, policy_version: str) -> RetentionResult: ...


class ResearchOutboxRepository(Protocol):
    def drain(self, limit: int = 100) -> int: ...
