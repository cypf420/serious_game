from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import os

from serious_game_backend.application.action_service import ActionService
from serious_game_backend.application.action_quote_service import ActionQuoteService
from serious_game_backend.application.action_handler_registry import ActionHandlerRegistry
from serious_game_backend.application.trust_derivation_service import TrustDerivationService
from serious_game_backend.application.disclosure_gate_service import DisclosureGateService
from serious_game_backend.application.end_day_service import EndDayService
from serious_game_backend.application.ending_service import EndingAxisProjector, EndingService
from serious_game_backend.application.event_service import EventService
from serious_game_backend.application.game_session_service import GameSessionService
from serious_game_backend.application.group_conversation_service import (
    GroupConversationService,
)
from serious_game_backend.application.governance_service import GovernanceService
from serious_game_backend.application.gameplay_governance_service import (
    GameplayGovernanceService,
)
from serious_game_backend.application.input_review_service import InputReviewService
from serious_game_backend.application.interaction_opportunity_service import (
    InteractionOpportunityService,
)
from serious_game_backend.application.map_service import MapService
from serious_game_backend.application.night_simulation_service import NightSimulationService
from serious_game_backend.application.package_validation_service import (
    PackageValidationService,
)
from serious_game_backend.application.review_service import ReviewService
from serious_game_backend.application.save_service import SaveService
from serious_game_backend.application.npc_turn_service import NPCTurnService
from serious_game_backend.application.npc_memory_service import NPCMemoryService
from serious_game_backend.application.ports import (
    GameSessionRepository,
    OperationRepository,
    RoleLLMGateway,
    SessionRequestRepository,
    SnapshotRepository,
)
from serious_game_backend.application.scripted_delta_resolver import ScriptedDeltaResolver
from serious_game_backend.application.scripted_effect_service import ScriptedEffectService
from serious_game_backend.application.state_delta_validator import StateDeltaValidator
from serious_game_backend.application.story_clock_service import StoryClockService
from serious_game_backend.application.story_flow_service import StoryFlowService
from serious_game_backend.application.visible_state import VisibleStateProjector
from serious_game_backend.application.auth_service import AuthService
from serious_game_backend.application.consent_service import ConsentService
from serious_game_backend.application.model_input_policy import ModelInputPolicy
from serious_game_backend.application.experiment_assignment_service import (
    ExperimentAssignmentService,
)
from serious_game_backend.application.research_projection_service import (
    ResearchProjectionService,
)
from serious_game_backend.application.research_outbox_service import ResearchOutboxService
from serious_game_backend.config import Settings
from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway, Transport
from serious_game_backend.infrastructure.llm.player_configuration import (
    PlayerLLMConfigurationRegistry,
    ScopedRoleLLMGateway,
    Resolver,
)
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryGameSessionRepository,
    InMemoryOperationRepository,
    InMemoryRuntimeTransactionRepository,
    InMemoryScriptPackageRepository,
    InMemorySessionRequestRepository,
    InMemoryLLMCallAuditRepository,
    InMemoryNPCMemoryRepository,
    InMemoryAccountRepository,
    InMemoryAuthSessionRepository,
    InMemoryConsentRepository,
    InMemoryExperimentAssignmentRepository,
    InMemoryResearchEventRepository,
    InMemoryResearchIdentityRepository,
    InMemorySnapshotRepository,
)
from serious_game_backend.infrastructure.repositories.sqlite import (
    SqliteGameSessionRepository,
    SqliteOperationRepository,
    SqliteRuntimeTransactionRepository,
    SqliteRuntimeStore,
    SqliteSessionRequestRepository,
    SqliteLLMCallAuditRepository,
    SqliteNPCMemoryRepository,
    SqliteAccountRepository,
    SqliteAuthSessionRepository,
    SqliteConsentRepository,
    SqliteExperimentAssignmentRepository,
    SqliteResearchEventRepository,
    SqliteResearchIdentityRepository,
    SqliteSnapshotRepository,
)
from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader
from serious_game_backend.infrastructure.privacy import PIIRedactor
from serious_game_backend.domain.consent import ConsentDocument
from serious_game_backend.infrastructure.repositories.mysql import (
    MySQLAccountRepository,
    MySQLAuthSessionRepository,
    MySQLConsentRepository,
    MySQLExperimentAssignmentRepository,
    MySQLGameSessionRepository,
    MySQLLLMCallAuditRepository,
    MySQLNPCMemoryRepository,
    MySQLOperationRepository,
    MySQLResearchEventRepository,
    MySQLResearchIdentityRepository,
    MySQLRuntimeStore,
    MySQLRuntimeTransactionRepository,
    MySQLSessionRequestRepository,
    MySQLSnapshotRepository,
)
from serious_game_backend.infrastructure.crypto import FieldCipher
from serious_game_backend.infrastructure.research_mysql_store import MySQLResearchStore
from serious_game_backend.infrastructure.repositories.governance import (
    MySQLGovernanceRepository, SqliteGovernanceRepository,
)
from serious_game_backend.infrastructure.repositories.governance_memory import InMemoryGovernanceRepository
from serious_game_backend.infrastructure.repositories.research_outbox import (
    MySQLResearchOutboxRepository, NullResearchOutboxRepository,
    SqliteResearchOutboxRepository,
)


@dataclass(slots=True)
class Container:
    settings: Settings
    sessions: GameSessionRepository
    operations: OperationRepository
    session_requests: SessionRequestRepository
    snapshots: SnapshotRepository
    packages: InMemoryScriptPackageRepository
    projector: VisibleStateProjector
    game_sessions: GameSessionService
    actions: ActionService
    action_quotes: ActionQuoteService
    end_days: EndDayService
    group_conversations: GroupConversationService
    gameplay_governance: GameplayGovernanceService
    npc_turns: NPCTurnService
    opportunities: InteractionOpportunityService
    story_flow: StoryFlowService
    map_service: MapService
    review_service: ReviewService
    saves: SaveService
    package_validation: PackageValidationService
    endings: EndingService
    llm_audits: object
    npc_memories: NPCMemoryService
    auth: AuthService
    consents: ConsentService
    accounts: object
    auth_sessions: object
    consent_records: object
    research_identities: object
    experiment_assignments: object
    research_events: object
    governance: GovernanceService
    research_outbox: ResearchOutboxService
    player_llm_configs: PlayerLLMConfigurationRegistry
    role_llm: ScopedRoleLLMGateway


def build_container(
    settings: Settings,
    *,
    player_llm_transport: Transport | None = None,
    player_llm_resolver: Resolver | None = None,
    server_role_llm: RoleLLMGateway | None = None,
) -> Container:
    loader = FileScriptPackageLoader()
    package_values = loader.load_all(settings.content_root)
    if settings.default_package_id == "pkg_gameplay_v3":
        package_values = [
            replace(package, status="retired")
            if package.package_id == "pkg_gameplay_v2"
            else package
            for package in package_values
        ]
    field_key = os.getenv(settings.field_encryption_key_env, "")
    field_cipher = (
        FieldCipher(field_key, key_id=settings.field_encryption_key_id)
        if field_key else None
    )
    if settings.repository == "mysql":
        if field_cipher is None:
            raise ValueError(
                f"MySQL repository requires field encryption key env "
                f"{settings.field_encryption_key_env}"
            )
        store = MySQLRuntimeStore(
            settings.mysql_url,
            field_cipher=field_cipher,
        )
        research_store = (
            MySQLResearchStore(settings.research_mysql_url)
            if settings.research_enabled else store
        )
        for package in package_values:
            store.sync_package(
                package, str((settings.content_root / package.package_id).resolve())
            )
        sessions = MySQLGameSessionRepository(store)
        operations = MySQLOperationRepository(store)
        session_requests = MySQLSessionRequestRepository(store)
        snapshots = MySQLSnapshotRepository(store)
        transactions = MySQLRuntimeTransactionRepository(store)
        llm_audits = MySQLLLMCallAuditRepository(store)
        memory_repository = MySQLNPCMemoryRepository(store)
        accounts = MySQLAccountRepository(store)
        auth_sessions = MySQLAuthSessionRepository(store)
        consent_records = MySQLConsentRepository(store)
        research_identities = MySQLResearchIdentityRepository(store)
        experiment_assignments = MySQLExperimentAssignmentRepository(store)
        research_events = MySQLResearchEventRepository(research_store)
        governance_repository = MySQLGovernanceRepository(store, research_store)
        outbox_repository = MySQLResearchOutboxRepository(store, research_store)
    elif settings.repository == "sqlite":
        store = SqliteRuntimeStore(settings.database_path)
        sessions = SqliteGameSessionRepository(store)
        operations = SqliteOperationRepository(store)
        session_requests = SqliteSessionRequestRepository(store)
        snapshots = SqliteSnapshotRepository(store)
        transactions = SqliteRuntimeTransactionRepository(store)
        llm_audits = SqliteLLMCallAuditRepository(store)
        memory_repository = SqliteNPCMemoryRepository(store)
        accounts = SqliteAccountRepository(store)
        auth_sessions = SqliteAuthSessionRepository(store)
        consent_records = SqliteConsentRepository(store)
        research_identities = SqliteResearchIdentityRepository(store)
        experiment_assignments = SqliteExperimentAssignmentRepository(store)
        research_events = SqliteResearchEventRepository(store)
        governance_repository = SqliteGovernanceRepository(store)
        outbox_repository = SqliteResearchOutboxRepository(store)
    else:
        sessions = InMemoryGameSessionRepository()
        operations = InMemoryOperationRepository()
        session_requests = InMemorySessionRequestRepository()
        snapshots = InMemorySnapshotRepository(sessions, operations)
        llm_audits = InMemoryLLMCallAuditRepository()
        memory_repository = InMemoryNPCMemoryRepository()
        accounts = InMemoryAccountRepository()
        auth_sessions = InMemoryAuthSessionRepository()
        consent_records = InMemoryConsentRepository()
        research_identities = InMemoryResearchIdentityRepository()
        experiment_assignments = InMemoryExperimentAssignmentRepository()
        research_events = InMemoryResearchEventRepository()
        governance_repository = InMemoryGovernanceRepository(research_events)
        outbox_repository = NullResearchOutboxRepository()
        transactions = InMemoryRuntimeTransactionRepository(
            sessions, operations, session_requests, research_events, snapshots
        )
    stale_before = (
        datetime.now(timezone.utc)
        - timedelta(seconds=settings.operation_lease_seconds)
    ).isoformat()
    transactions.recover_stale_operations(stale_before)
    packages = InMemoryScriptPackageRepository(package_values)
    projector = VisibleStateProjector()
    event_service = EventService()
    story_clock = StoryClockService(event_service)
    if server_role_llm is None and settings.role_llm_provider == "openai_compatible":
        server_role_llm = OpenAICompatibleRoleLLMGateway(
            settings,
            os.getenv(settings.role_llm_api_key_env, ""),
            llm_audits,
        )
    registry_kwargs = {"transport": player_llm_transport}
    if player_llm_resolver is not None:
        registry_kwargs["resolver"] = player_llm_resolver
    player_llm_configs = PlayerLLMConfigurationRegistry(
        settings, llm_audits, server_role_llm, **registry_kwargs
    )
    role_llm = ScopedRoleLLMGateway(player_llm_configs)
    delta_resolver = ScriptedDeltaResolver()
    validator = StateDeltaValidator(delta_resolver)
    scripted_effects = ScriptedEffectService(delta_resolver)
    trust_derivation = TrustDerivationService()
    disclosure_gate = DisclosureGateService()
    action_quotes = ActionQuoteService()
    action_handlers = ActionHandlerRegistry(scripted_effects)
    npc_memories = NPCMemoryService(memory_repository)
    nights = NightSimulationService(scripted_effects, trust_derivation, role_llm, npc_memories)
    endings = EndingService(EndingAxisProjector())
    npc_turns = NPCTurnService(role_llm, validator)
    input_review = InputReviewService(role_llm)
    story_flow = StoryFlowService()
    gameplay_governance = GameplayGovernanceService(
        sessions,
        packages,
        role_llm,
        npc_turns,
        projector,
        input_review,
        scripted_effects,
        story_flow,
        snapshots,
        disclosure_gate,
        operations,
        transactions,
        npc_memories,
    )
    auth = AuthService(
        accounts, auth_sessions,
        session_ttl_seconds=settings.auth_session_ttl_seconds,
    )
    consents = ConsentService(
        consent_records,
        active_version=settings.consent_version,
        active_document_hash=settings.consent_document_hash,
    )
    consents.publish(ConsentDocument(
        consent_version=settings.consent_version,
        document_hash=settings.consent_document_hash,
        model_provider=settings.consent_model_provider,
        processing_region=settings.consent_processing_region,
        retention_days_raw_text=settings.raw_text_retention_days,
    ))
    model_input_policy = ModelInputPolicy(
        consents,
        PIIRedactor(),
        require_model_consent=settings.require_model_consent,
    )
    experiment_service = ExperimentAssignmentService(
        experiment_assignments,
        enabled=settings.research_enabled,
        experiment_id=settings.experiment_id,
        groups=settings.experiment_groups,
        assignment_salt=settings.experiment_assignment_salt,
    )
    research_projection = (
        ResearchProjectionService(
            consents,
            public_id_salt=settings.experiment_assignment_salt,
            field_cipher=field_cipher,
        ) if settings.research_enabled else None
    )
    opportunities = InteractionOpportunityService()
    return Container(
        settings=settings,
        sessions=sessions,
        operations=operations,
        session_requests=session_requests,
        snapshots=snapshots,
        packages=packages,
        projector=projector,
        game_sessions=GameSessionService(
            sessions,
            session_requests,
            transactions,
            packages,
            story_flow,
            event_service,
            environment=settings.environment,
            consents=consent_records,
            research_identities=research_identities,
            experiment_assignments=experiment_service,
            model_id=settings.role_llm_model,
            prompt_version="role-turn-v2",
        ),
        actions=ActionService(
            sessions,
            operations,
            transactions,
            packages,
            projector,
            opportunities,
            npc_turns,
            scripted_effects,
            story_flow,
            npc_memories,
            action_quotes,
            action_handlers,
            trust_derivation,
            disclosure_gate,
            model_input_policy,
            research_projection,
        ),
        action_quotes=action_quotes,
        end_days=EndDayService(
            sessions,
            operations,
            transactions,
            packages,
            story_clock,
            nights,
            endings,
            projector,
            story_flow,
            gameplay_governance,
        ),
        group_conversations=GroupConversationService(
            sessions,
            packages,
            role_llm,
            projector,
            input_review,
            operations,
            transactions,
            disclosure_gate,
            npc_memories,
        ),
        gameplay_governance=gameplay_governance,
        npc_turns=npc_turns,
        opportunities=opportunities,
        story_flow=story_flow,
        map_service=MapService(opportunities),
        review_service=ReviewService(projector),
        saves=SaveService(sessions, operations, snapshots),
        package_validation=PackageValidationService(),
        endings=endings,
        llm_audits=llm_audits,
        npc_memories=npc_memories,
        auth=auth,
        consents=consents,
        accounts=accounts,
        auth_sessions=auth_sessions,
        consent_records=consent_records,
        research_identities=research_identities,
        experiment_assignments=experiment_assignments,
        research_events=research_events,
        governance=GovernanceService(
            governance_repository, audit_salt=settings.governance_audit_salt
        ),
        research_outbox=ResearchOutboxService(outbox_repository),
        player_llm_configs=player_llm_configs,
        role_llm=role_llm,
    )
