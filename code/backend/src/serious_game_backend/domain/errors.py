from __future__ import annotations


class DomainError(RuntimeError):
    code = "DOMAIN_ERROR"
    http_status = 400
    retryable = False

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    http_status = 404


class StateVersionConflictError(DomainError):
    code = "STATE_VERSION_CONFLICT"
    http_status = 409


class SessionBusyError(DomainError):
    code = "SESSION_BUSY"
    http_status = 409


class DecisionRequiredError(DomainError):
    code = "DECISION_REQUIRED"
    http_status = 409


class IdempotencyKeyReusedError(DomainError):
    code = "IDEMPOTENCY_KEY_REUSED"
    http_status = 409


class InsufficientActionPointsError(DomainError):
    code = "INSUFFICIENT_ACTION_POINTS"
    http_status = 409


class ActionUnavailableError(DomainError):
    code = "ACTION_UNAVAILABLE"
    http_status = 409


class ContentValidationError(DomainError):
    code = "CONTENT_VALIDATION_FAILED"
    http_status = 422


class SessionEndedError(DomainError):
    code = "SESSION_ENDED"
    http_status = 409


class SessionContentUnavailableError(DomainError):
    code = "SESSION_CONTENT_UNAVAILABLE"
    http_status = 503


class PackageRetiredError(DomainError):
    code = "PACKAGE_RETIRED"
    http_status = 409


class OperationRetryRequiredError(DomainError):
    code = "OPERATION_RETRY_REQUIRED"
    http_status = 409


class StoredOperationError(DomainError):
    """重放操作记录中已经固定的终态错误。"""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        http_status: int,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.code = code
        self.http_status = http_status


class RoleLLMUnavailableError(DomainError):
    code = "ROLE_LLM_UNAVAILABLE"
    http_status = 503
    retryable = True


class RoleLLMResponseError(DomainError):
    code = "ROLE_LLM_INVALID_RESPONSE"
    http_status = 502
    retryable = True


class RoleLLMCapabilityUnsupportedError(DomainError):
    code = "ROLE_LLM_CAPABILITY_UNSUPPORTED"
    http_status = 422
    retryable = False


class RoleLLMResponseRetryableError(DomainError):
    code = "ROLE_LLM_RESPONSE_RETRYABLE"
    http_status = 503
    retryable = True


class RoleLLMExpressionUnsafeError(RoleLLMResponseError):
    code = "ROLE_LLM_EXPRESSION_UNSAFE"
    http_status = 502
    retryable = True


class SnapshotStateMismatchError(DomainError):
    code = "SNAPSHOT_STATE_MISMATCH"
    http_status = 409
    retryable = False


class RoleLLMBudgetExceededError(DomainError):
    code = "ROLE_LLM_BUDGET_EXCEEDED"
    http_status = 429
    retryable = False


class RoleLLMConfigurationError(DomainError):
    code = "ROLE_LLM_CONFIGURATION_ERROR"
    http_status = 503
    retryable = False


class PlayerLLMConfigurationRequiredError(DomainError):
    code = "ROLE_LLM_CONFIGURATION_REQUIRED"
    http_status = 409
    retryable = False


class PlayerLLMConfigurationInvalidError(DomainError):
    code = "ROLE_LLM_CONFIGURATION_INVALID"
    http_status = 422
    retryable = False


class AuthenticationRequiredError(DomainError):
    code = "AUTHENTICATION_REQUIRED"
    http_status = 401


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"
    http_status = 401


class AccountConflictError(DomainError):
    code = "ACCOUNT_CONFLICT"
    http_status = 409


class RegistrationDisabledError(DomainError):
    code = "REGISTRATION_DISABLED"
    http_status = 403


class PermissionDeniedError(DomainError):
    code = "PERMISSION_DENIED"
    http_status = 403


class CSRFValidationError(DomainError):
    code = "CSRF_VALIDATION_FAILED"
    http_status = 403


class ConsentRequiredError(DomainError):
    code = "CONSENT_REQUIRED"
    http_status = 451


class ConsentVersionError(DomainError):
    code = "CONSENT_VERSION_INVALID"
    http_status = 409
