"""后端运行配置。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def load_local_env(path: Path | None = None) -> None:
    """加载后端本地 .env；已有进程环境变量始终优先。"""
    env_path = path or (BACKEND_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'\"")


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "sandbox"
    host: str = "0.0.0.0"
    port: int = 8100
    default_package_id: str = "pkg_gameplay_v3"
    content_root: Path = BACKEND_ROOT / "content" / "packages"
    repository: str = "sqlite"
    database_path: Path = BACKEND_ROOT / "data" / "serious_game.db"
    mysql_url: str = ""
    research_mysql_url: str = ""
    auth_cookie_name: str = "serious_game_session"
    auth_cookie_secure: bool = True
    auth_session_ttl_seconds: int = 8 * 60 * 60
    auth_required: bool = False
    allow_self_registration: bool = False
    consent_version: str = "draft-consent-v1"
    consent_document_hash: str = "sha256:draft"
    consent_model_provider: str = "未配置"
    consent_processing_region: str = "未配置"
    raw_text_retention_days: int = 180
    require_model_consent: bool = False
    field_encryption_key_env: str = "SERIOUS_GAME_FIELD_KEY"
    field_encryption_key_id: str = "local-dev"
    research_enabled: bool = False
    experiment_id: str = ""
    experiment_groups: tuple[str, ...] = ()
    experiment_assignment_salt: str = ""
    governance_audit_salt: str = "local-dev-governance-audit"
    retention_policy_version: str = "draft-retention-v1"
    # The product runtime is fail-closed until a real OpenAI-compatible
    # provider is configured. Deterministic doubles live under tests only.
    role_llm_provider: str = "none"
    role_llm_base_url: str = "https://api.qianzhang-ai.cn/v1"
    role_llm_model: str = "qwen3.6-plus"
    document_audit_llm_model: str = "qwen3.6-plus"
    contract_audit_llm_model: str = "qwen3.6-plus"
    role_llm_api_key_env: str = "DASHSCOPE_API_KEY"
    role_llm_timeout_seconds: float = 30.0
    role_llm_max_retries: int = 2
    role_llm_max_output_tokens: int = 700
    role_llm_max_calls_per_session: int = 1_500
    role_llm_max_tokens_per_session: int = 3_000_000
    operation_lease_seconds: int = 300

    @classmethod
    def from_env(cls) -> "Settings":
        load_local_env()
        content_value = os.getenv("GAME_CONTENT_ROOT", "content/packages").strip()
        content_root = Path(content_value)
        if not content_root.is_absolute():
            content_root = BACKEND_ROOT / content_root
        database_value = os.getenv(
            "GAME_DATABASE_PATH", "data/serious_game.db"
        ).strip()
        database_path = Path(database_value)
        if not database_path.is_absolute():
            database_path = BACKEND_ROOT / database_path
        settings = cls(
            environment=os.getenv("GAME_ENVIRONMENT", "sandbox").strip().lower(),
            host=os.getenv("GAME_HOST", "0.0.0.0").strip(),
            port=int(os.getenv("GAME_PORT", "8100")),
            default_package_id=os.getenv(
                "GAME_DEFAULT_PACKAGE_ID", "pkg_gameplay_v3"
            ).strip(),
            content_root=content_root.resolve(),
            repository=os.getenv("GAME_REPOSITORY", "sqlite").strip().lower(),
            database_path=database_path.resolve(),
            mysql_url=os.getenv("GAME_MYSQL_URL", "").strip(),
            research_mysql_url=os.getenv("RESEARCH_MYSQL_URL", "").strip(),
            auth_cookie_name=os.getenv(
                "AUTH_COOKIE_NAME", "serious_game_session"
            ).strip(),
            auth_cookie_secure=os.getenv(
                "AUTH_COOKIE_SECURE", "true"
            ).strip().lower() in {"1", "true", "yes", "on"},
            auth_session_ttl_seconds=int(os.getenv(
                "AUTH_SESSION_TTL_SECONDS", str(8 * 60 * 60)
            )),
            auth_required=os.getenv(
                "AUTH_REQUIRED", "false"
            ).strip().lower() in {"1", "true", "yes", "on"},
            allow_self_registration=os.getenv(
                "ALLOW_SELF_REGISTRATION", "false"
            ).strip().lower() in {"1", "true", "yes", "on"},
            consent_version=os.getenv(
                "CONSENT_VERSION", "draft-consent-v1"
            ).strip(),
            consent_document_hash=os.getenv(
                "CONSENT_DOCUMENT_HASH", "sha256:draft"
            ).strip(),
            consent_model_provider=os.getenv(
                "CONSENT_MODEL_PROVIDER", "未配置"
            ).strip(),
            consent_processing_region=os.getenv(
                "CONSENT_PROCESSING_REGION", "未配置"
            ).strip(),
            raw_text_retention_days=int(os.getenv(
                "RAW_TEXT_RETENTION_DAYS", "180"
            )),
            require_model_consent=os.getenv(
                "REQUIRE_MODEL_CONSENT",
                "true" if os.getenv("GAME_ENVIRONMENT", "sandbox").strip().lower() == "production" else "false",
            ).strip().lower() in {"1", "true", "yes", "on"},
            field_encryption_key_env=os.getenv(
                "FIELD_ENCRYPTION_KEY_ENV", "SERIOUS_GAME_FIELD_KEY"
            ).strip(),
            field_encryption_key_id=os.getenv(
                "FIELD_ENCRYPTION_KEY_ID", "local-dev"
            ).strip(),
            research_enabled=os.getenv(
                "RESEARCH_ENABLED", "false"
            ).strip().lower() in {"1", "true", "yes", "on"},
            experiment_id=os.getenv("EXPERIMENT_ID", "").strip(),
            experiment_groups=tuple(
                item.strip() for item in os.getenv("EXPERIMENT_GROUPS", "").split(",")
                if item.strip()
            ),
            experiment_assignment_salt=os.getenv(
                "EXPERIMENT_ASSIGNMENT_SALT", ""
            ).strip(),
            governance_audit_salt=os.getenv(
                "GOVERNANCE_AUDIT_SALT", "local-dev-governance-audit"
            ).strip(),
            retention_policy_version=os.getenv(
                "RETENTION_POLICY_VERSION", "draft-retention-v1"
            ).strip(),
            role_llm_provider=os.getenv("ROLE_LLM_PROVIDER", "none").strip().lower(),
            role_llm_base_url=os.getenv(
                "ROLE_LLM_BASE_URL",
                "https://api.qianzhang-ai.cn/v1",
            ).strip().rstrip("/"),
            role_llm_model=os.getenv("ROLE_LLM_MODEL", "qwen3.6-plus").strip(),
            document_audit_llm_model=os.getenv(
                "DOCUMENT_AUDIT_LLM_MODEL",
                os.getenv("ROLE_LLM_MODEL", "qwen3.6-plus"),
            ).strip(),
            contract_audit_llm_model=os.getenv(
                "CONTRACT_AUDIT_LLM_MODEL",
                os.getenv("ROLE_LLM_MODEL", "qwen3.6-plus"),
            ).strip(),
            role_llm_api_key_env=os.getenv(
                "ROLE_LLM_API_KEY_ENV", "DASHSCOPE_API_KEY"
            ).strip(),
            role_llm_timeout_seconds=float(
                os.getenv("ROLE_LLM_TIMEOUT_SECONDS", "30")
            ),
            role_llm_max_retries=int(os.getenv("ROLE_LLM_MAX_RETRIES", "2")),
            role_llm_max_output_tokens=int(
                os.getenv("ROLE_LLM_MAX_OUTPUT_TOKENS", "700")
            ),
            role_llm_max_calls_per_session=int(
                os.getenv("ROLE_LLM_MAX_CALLS_PER_SESSION", "1500")
            ),
            role_llm_max_tokens_per_session=int(
                os.getenv("ROLE_LLM_MAX_TOKENS_PER_SESSION", "3000000")
            ),
            operation_lease_seconds=int(
                os.getenv("OPERATION_LEASE_SECONDS", "300")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.environment not in {"sandbox", "test", "production"}:
            raise ValueError("GAME_ENVIRONMENT must be sandbox, test, or production")
        if self.repository not in {"memory", "sqlite", "mysql"}:
            raise ValueError("GAME_REPOSITORY must be memory, sqlite, or mysql")
        if self.environment == "production" and self.repository != "mysql":
            raise ValueError("production must use the MySQL repository")
        if self.repository == "mysql" and not self.mysql_url:
            raise ValueError("MySQL repository requires GAME_MYSQL_URL")
        if self.repository == "mysql" and self.research_enabled and (
            not self.research_mysql_url or self.research_mysql_url == self.mysql_url
        ):
            raise ValueError("research mode requires a physically separate RESEARCH_MYSQL_URL")
        if self.environment == "production" and not self.auth_cookie_secure:
            raise ValueError("production auth cookie must be Secure")
        if self.environment == "production" and not self.auth_required:
            raise ValueError("production must require authenticated accounts")
        if self.environment == "production" and self.allow_self_registration:
            raise ValueError("production must not enable unrestricted self-registration")
        if self.environment == "production" and (
            self.consent_version.startswith("draft-")
            or self.consent_document_hash in {"", "sha256:draft"}
            or self.consent_model_provider == "未配置"
            or self.consent_processing_region == "未配置"
        ):
            raise ValueError("production requires a frozen consent document and provider disclosure")
        if self.environment == "production" and not self.require_model_consent:
            raise ValueError("production must require third-party model consent")
        if self.environment == "production" and (
            self.governance_audit_salt == "local-dev-governance-audit"
            or self.retention_policy_version.startswith("draft-")
        ):
            raise ValueError("production requires frozen retention policy and secret audit salt")
        if self.repository == "mysql" and not os.getenv(self.field_encryption_key_env, ""):
            raise ValueError(
                f"MySQL repository requires field encryption key env {self.field_encryption_key_env}"
            )
        if self.research_enabled and (
            not self.experiment_id
            or len(self.experiment_groups) < 1
            or not self.experiment_assignment_salt
        ):
            raise ValueError("research mode requires experiment id, groups, and assignment salt")
        if self.role_llm_provider not in {"none", "openai_compatible"}:
            raise ValueError("ROLE_LLM_PROVIDER must be none or openai_compatible")
        if self.role_llm_provider == "openai_compatible":
            if not self.role_llm_base_url.startswith("https://"):
                raise ValueError("ROLE_LLM_BASE_URL must use https")
            if (
                not self.role_llm_model
                or not self.document_audit_llm_model
                or not self.contract_audit_llm_model
                or not self.role_llm_api_key_env
            ):
                raise ValueError("real role LLM requires model and API key env name")
        if not 1 <= self.role_llm_max_output_tokens <= 4000:
            raise ValueError("ROLE_LLM_MAX_OUTPUT_TOKENS must be between 1 and 4000")
        if self.role_llm_timeout_seconds <= 0 or self.role_llm_max_retries not in range(0, 4):
            raise ValueError("invalid role LLM timeout or retry count")
        if min(
            self.role_llm_max_calls_per_session,
            self.role_llm_max_tokens_per_session,
        ) <= 0:
            raise ValueError("role LLM budgets must be positive")
        if self.auth_session_ttl_seconds <= 0 or self.raw_text_retention_days <= 0:
            raise ValueError("invalid auth session TTL or raw text retention")
        if self.operation_lease_seconds <= 0:
            raise ValueError("OPERATION_LEASE_SECONDS must be positive")
