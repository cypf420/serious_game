from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
from threading import RLock
from typing import Callable, Iterator
from urllib.parse import urlsplit

from serious_game_backend.application.ports import LLMCallAuditRepository, RoleLLMGateway
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import (
    PlayerLLMConfigurationInvalidError,
    PlayerLLMConfigurationRequiredError,
    RoleLLMConfigurationError,
    RoleLLMCapabilityUnsupportedError,
    RoleLLMResponseError,
    RoleLLMResponseRetryableError,
    RoleLLMUnavailableError,
)
from serious_game_backend.domain.llm import (
    ExpressionResult,
    ExpressionTask,
    GovernanceLLMContext,
    GovernanceLLMResult,
    NightAgentContext,
    NightAgentResult,
    RoleTurnContext,
    RoleTurnResult,
    SelectionOption,
    SelectionResult,
    SelectionTask,
)
from serious_game_backend.infrastructure.llm.openai_compatible import (
    OpenAICompatibleRoleLLMGateway,
    Transport,
)


Resolver = Callable[..., list[tuple]]
_UNBOUND = object()
_request_gateway: ContextVar[RoleLLMGateway | None | object] = ContextVar(
    "serious_game_request_llm_gateway", default=_UNBOUND
)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection whose TCP peer is restricted to prevalidated IPs."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        validated_addresses: tuple[str, ...],
        timeout: float,
    ) -> None:
        super().__init__(
            host,
            port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self._validated_addresses = validated_addresses

    def connect(self) -> None:
        last_error: OSError | None = None
        for address in self._validated_addresses:
            raw_socket = None
            try:
                raw_socket = socket.create_connection(
                    (address, self.port), self.timeout, self.source_address
                )
                self.sock = self._context.wrap_socket(
                    raw_socket,
                    server_hostname=self.host,
                )
                return
            except OSError as exc:
                last_error = exc
                if raw_socket is not None:
                    raw_socket.close()
        raise last_error or OSError("没有可用的已验证 AI 接口地址")


def _pinned_https_json_transport(
    base_url: str,
    api_key: str,
    body: dict,
    timeout: float,
    *,
    validated_addresses: tuple[str, ...],
) -> dict:
    parsed = urlsplit(base_url)
    connection = _PinnedHTTPSConnection(
        parsed.hostname or "",
        parsed.port or 443,
        validated_addresses=validated_addresses,
        timeout=timeout,
    )
    target = f"{parsed.path.rstrip('/')}/chat/completions"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        connection.request(
            "POST",
            target,
            body=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
            },
        )
        response = connection.getresponse()
        response_body = response.read()
        if response.status in {401, 403}:
            raise RoleLLMConfigurationError(
                f"模型鉴权失败（HTTP {response.status}）"
            )
        if response.status in {408, 409, 429, 500, 502, 503, 504}:
            raise RoleLLMUnavailableError(
                f"模型服务暂时不可用（HTTP {response.status}）"
            )
        if response.status < 200 or response.status >= 300:
            raise RoleLLMResponseError(
                f"模型请求被拒绝（HTTP {response.status}）"
            )
        try:
            value = json.loads(response_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RoleLLMResponseError("模型未返回可解析的结构化响应") from exc
        if not isinstance(value, dict):
            raise RoleLLMResponseError("模型结构化响应必须是 JSON 对象")
        return value
    except (
        RoleLLMConfigurationError,
        RoleLLMResponseError,
        RoleLLMUnavailableError,
    ):
        raise
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        raise RoleLLMUnavailableError("连接角色模型失败") from exc
    finally:
        connection.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class PlayerLLMStatus:
    mode: str
    active: bool
    endpoint: str | None
    model: str | None
    server_default_available: bool
    capabilities: dict[str, str]
    compatibility_status: str
    tested_at: str | None
    config_version: str | None = None
    expires_with_login: bool = True

    def public_dict(self) -> dict:
        return {
            "mode": self.mode,
            "active": self.active,
            "endpoint": self.endpoint,
            "model": self.model,
            "server_default_available": self.server_default_available,
            "capabilities": dict(self.capabilities),
            "compatibility_status": self.compatibility_status,
            "tested_at": self.tested_at,
            "config_version": self.config_version,
            "expires_with_login": self.expires_with_login,
        }


@dataclass(frozen=True, slots=True)
class _Selection:
    mode: str
    gateway: RoleLLMGateway
    endpoint: str
    model: str
    expires_at: datetime
    capabilities: dict[str, str]
    tested_at: str
    config_version: str


class _NullAuditRepository:
    def save(self, _audit) -> None:
        return None

    def successful_for_operation(self, **_identity):
        return None

    def list_for_session(self, _session_id: str) -> tuple:
        return ()


class _ForcedModelGateway:
    def __init__(self, gateway: RoleLLMGateway, model: str) -> None:
        self._gateway = gateway
        self._model = model

    def run_turn(self, context: RoleTurnContext) -> RoleTurnResult:
        return self._gateway.run_turn(context)

    def select(self, task: SelectionTask) -> SelectionResult:
        return self._gateway.select(task)

    def express(self, task: ExpressionTask) -> ExpressionResult:
        return self._gateway.express(task)

    def run_night_turn(self, context: NightAgentContext) -> NightAgentResult:
        return self._gateway.run_night_turn(replace(context, model_id=self._model))

    def run_governance_task(
        self, context: GovernanceLLMContext
    ) -> GovernanceLLMResult:
        return self._gateway.run_governance_task(context)


class PlayerLLMConfigurationRegistry:
    """Process-local credentials and request-frozen gateway selection."""

    def __init__(
        self,
        settings: Settings,
        audits: LLMCallAuditRepository,
        server_default: RoleLLMGateway | None,
        *,
        transport: Transport | None = None,
        resolver: Resolver = socket.getaddrinfo,
    ) -> None:
        self._settings = settings
        self._audits = audits
        self._server_default = server_default
        self._transport = transport
        self._resolver = resolver
        self._items: dict[str, _Selection] = {}
        self._lock = RLock()

    @property
    def server_default_available(self) -> bool:
        return self._server_default is not None

    def server_default_summary(self) -> dict | None:
        if self._server_default is None:
            return None
        return {
            "endpoint": self._public_endpoint(self._settings.role_llm_base_url),
            "model": self._settings.role_llm_model,
        }

    def status(self, scope_id: str) -> PlayerLLMStatus:
        selection = self._get(scope_id)
        if selection is None:
            return PlayerLLMStatus(
                mode="unconfigured",
                active=False,
                endpoint=None,
                model=None,
                server_default_available=self.server_default_available,
                capabilities=self._empty_capabilities(),
                compatibility_status="unconfigured",
                tested_at=None,
                config_version=None,
            )
        return PlayerLLMStatus(
            mode=selection.mode,
            active=True,
            endpoint=selection.endpoint,
            model=selection.model,
            server_default_available=self.server_default_available,
            capabilities=selection.capabilities,
            compatibility_status="compatible",
            tested_at=selection.tested_at,
            config_version=selection.config_version,
        )

    def use_server_default(
        self, scope_id: str, *, expires_at: datetime | None = None
    ) -> PlayerLLMStatus:
        if self._server_default is None:
            raise PlayerLLMConfigurationInvalidError("服务器未配置可用的默认 AI 接口")
        capabilities, tested_at = self._probe_capabilities(self._server_default)
        endpoint = self._public_endpoint(self._settings.role_llm_base_url)
        self._set(scope_id, _Selection(
            mode="server_default",
            gateway=self._server_default,
            endpoint=endpoint,
            model=self._settings.role_llm_model,
            expires_at=expires_at or self._default_expiry(),
            capabilities=capabilities,
            tested_at=tested_at,
            config_version=getattr(
                self._server_default, "config_version", f"cfg_{secrets.token_hex(16)}"
            ),
        ))
        return self.status(scope_id)

    def use_personal(
        self, scope_id: str, *, base_url: str, api_key: str, model: str,
        expires_at: datetime | None = None,
    ) -> PlayerLLMStatus:
        normalized_url = self._validate_public_base_url(base_url)
        normalized_key = api_key.strip()
        normalized_model = model.strip()
        if not normalized_key or not normalized_model:
            raise PlayerLLMConfigurationInvalidError("API Key 和模型名不能为空")
        personal_settings = replace(
            self._settings,
            role_llm_provider="openai_compatible",
            role_llm_base_url=normalized_url,
            role_llm_model=normalized_model,
            document_audit_llm_model=normalized_model,
            contract_audit_llm_model=normalized_model,
        )
        def validated_transport(
            request_base_url: str,
            request_api_key: str,
            request_body: dict,
            request_timeout: float,
        ) -> dict:
            validated_url, validated_addresses = self._resolve_public_base_url(
                request_base_url
            )
            if self._transport is not None:
                return self._transport(
                    validated_url,
                    request_api_key,
                    request_body,
                    request_timeout,
                )
            return _pinned_https_json_transport(
                validated_url,
                request_api_key,
                request_body,
                request_timeout,
                validated_addresses=validated_addresses,
            )

        probe_settings = replace(personal_settings, role_llm_max_retries=2)
        probe = OpenAICompatibleRoleLLMGateway(
            probe_settings,
            normalized_key,
            _NullAuditRepository(),
            transport=validated_transport,
            audit_endpoint_host=self._public_endpoint(normalized_url),
        )
        try:
            capabilities, tested_at = self._probe_capabilities(probe)
        except RoleLLMConfigurationError as exc:
            raise PlayerLLMConfigurationInvalidError(
                "API Key 无效，或该账号没有模型权限"
            ) from exc
        except RoleLLMUnavailableError as exc:
            raise PlayerLLMConfigurationInvalidError(
                "AI 接口连接超时或暂时不可用"
            ) from exc
        except (RoleLLMResponseError, RoleLLMResponseRetryableError) as exc:
            raise RoleLLMCapabilityUnsupportedError(
                "该接口未通过游戏所需的选择与表达能力测试"
            ) from exc
        active = OpenAICompatibleRoleLLMGateway(
            personal_settings,
            normalized_key,
            self._audits,
            transport=validated_transport,
            audit_endpoint_host=self._public_endpoint(normalized_url),
        )
        self._set(scope_id, _Selection(
            mode="personal",
            gateway=_ForcedModelGateway(active, normalized_model),
            endpoint=self._public_endpoint(normalized_url),
            model=normalized_model,
            expires_at=expires_at or self._default_expiry(),
            capabilities=capabilities,
            tested_at=tested_at,
            config_version=active.config_version,
        ))
        return self.status(scope_id)

    def clear(self, scope_id: str) -> PlayerLLMStatus:
        with self._lock:
            self._items.pop(scope_id, None)
        return self.status(scope_id)

    @contextmanager
    def bind(self, scope_id: str, *, require_selection: bool) -> Iterator[None]:
        selection = self._get(scope_id)
        gateway = selection.gateway if selection is not None else None
        if gateway is None and not require_selection:
            gateway = self._server_default
        token = _request_gateway.set(gateway)
        try:
            yield
        finally:
            _request_gateway.reset(token)

    def freeze_current(self) -> RoleLLMGateway | None:
        """Capture the immutable gateway selected at request entry."""
        value = _request_gateway.get()
        if value is _UNBOUND:
            return self._server_default
        return value

    @contextmanager
    def bind_frozen(self, gateway: RoleLLMGateway | None) -> Iterator[None]:
        """Restore a request selection inside deferred stream generators."""
        token = _request_gateway.set(gateway)
        try:
            yield
        finally:
            _request_gateway.reset(token)

    def current_gateway(self) -> RoleLLMGateway:
        value = _request_gateway.get()
        if value is _UNBOUND:
            if self._server_default is None:
                raise PlayerLLMConfigurationRequiredError("请先配置并启用 AI 接口")
            return self._server_default
        if value is None:
            raise PlayerLLMConfigurationRequiredError("请先配置并启用 AI 接口")
        return value

    def _get(self, scope_id: str) -> _Selection | None:
        with self._lock:
            value = self._items.get(scope_id)
            if value is not None and value.expires_at <= _now():
                self._items.pop(scope_id, None)
                return None
            return value

    def _set(self, scope_id: str, selection: _Selection) -> None:
        if not scope_id.strip():
            raise PlayerLLMConfigurationInvalidError("缺少可信登录会话")
        with self._lock:
            self._items[scope_id] = selection

    def _default_expiry(self) -> datetime:
        return _now() + timedelta(seconds=self._settings.auth_session_ttl_seconds)

    @staticmethod
    def _empty_capabilities() -> dict[str, str]:
        return {
            "single_choice": "untested",
            "multiple_choice": "untested",
            "expression": "untested",
            "night_followup": "untested",
            "contract_rendering": "untested",
            "document_rendering": "untested",
        }

    def _probe_capabilities(
        self, gateway: RoleLLMGateway
    ) -> tuple[dict[str, str], str]:
        common = {
            "role_id": "capability_probe",
            "role_name": "接口能力测试角色",
            "session_id": "capability_probe",
            "account_id": "capability_probe",
            "story_day": 0,
        }
        single = gateway.select(SelectionTask(
            task_id="capability_single_choice",
            instruction="选择 option_a 以证明单选兼容。",
            options=(
                SelectionOption("option_a", "选项甲"),
                SelectionOption("option_b", "选项乙"),
            ),
            operation_id="capability_single_choice",
            **common,
        ))
        if single.choice_id != "option_a":
            raise RoleLLMResponseError("单选能力测试没有遵守明确指令")
        multiple = gateway.select(SelectionTask(
            task_id="capability_multiple_choice",
            instruction="同时选择 option_a 和 option_b 以证明多选兼容。",
            options=(
                SelectionOption("option_a", "选项甲"),
                SelectionOption("option_b", "选项乙"),
            ),
            selection_mode="multiple",
            minimum_choices=2,
            maximum_choices=2,
            operation_id="capability_multiple_choice",
            **common,
        ))
        if set(multiple.choice_ids) != {"option_a", "option_b"}:
            raise RoleLLMResponseError("多选能力测试没有遵守明确指令")
        expression_specs = (
            ("expression", "capability_expression", "用一句简短中文确认表达能力。"),
            ("night_followup", "capability_night_followup", "说明已选择发起干部会谈。"),
            ("contract_rendering", "capability_contract", "把已确认合同条款写成一句话。"),
            ("document_rendering", "capability_document", "把已确认责任和期限写成一句公文表述。"),
        )
        capabilities = {
            "single_choice": "passed",
            "multiple_choice": "passed",
        }
        for capability, task_id, meaning in expression_specs:
            result = gateway.express(ExpressionTask(
                task_id=task_id,
                confirmed_choice_ids=("option_a",),
                choice_summaries={"option_a": meaning},
                allowed_facts=(meaning,),
                persona="仅用于接口兼容性测试，措辞克制。",
                context="不包含游戏剧情，不得补充事实。",
                operation_id=task_id,
                **common,
            ))
            if not result.text.strip():
                raise RoleLLMResponseError(f"{capability} 能力测试返回空文本")
            capabilities[capability] = "passed"
        return capabilities, _now().isoformat()

    def _validate_public_base_url(self, raw_value: str) -> str:
        value, _addresses = self._resolve_public_base_url(raw_value)
        return value

    def _resolve_public_base_url(
        self, raw_value: str
    ) -> tuple[str, tuple[str, ...]]:
        value = raw_value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise PlayerLLMConfigurationInvalidError(
                "Base URL 必须是公共 HTTPS 地址，且不能包含账号、查询参数或片段"
            )
        try:
            literal_address = ipaddress.ip_address(parsed.hostname.split("%", 1)[0])
        except ValueError:
            literal_address = None
        if literal_address is not None and not literal_address.is_global:
            raise PlayerLLMConfigurationInvalidError(
                "Base URL 不能指向内网、回环、链路本地或保留地址"
            )
        try:
            addresses = self._resolver(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
            resolved = {
                ipaddress.ip_address(item[4][0].split("%", 1)[0])
                for item in addresses
            }
        except (OSError, ValueError) as exc:
            raise PlayerLLMConfigurationInvalidError("Base URL 域名无法安全解析") from exc
        if not resolved or any(not address.is_global for address in resolved):
            raise PlayerLLMConfigurationInvalidError(
                "Base URL 不能指向内网、回环、链路本地或保留地址"
            )
        return value, tuple(sorted(str(address) for address in resolved))

    @staticmethod
    def _public_endpoint(base_url: str) -> str:
        parsed = urlsplit(base_url)
        port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
        return f"{parsed.hostname}{port}"


class ScopedRoleLLMGateway:
    def __init__(self, registry: PlayerLLMConfigurationRegistry) -> None:
        self._registry = registry

    def run_turn(self, context: RoleTurnContext) -> RoleTurnResult:
        return self._registry.current_gateway().run_turn(context)

    def select(self, task: SelectionTask) -> SelectionResult:
        return self._registry.current_gateway().select(task)

    def express(self, task: ExpressionTask) -> ExpressionResult:
        return self._registry.current_gateway().express(task)

    def run_night_turn(self, context: NightAgentContext) -> NightAgentResult:
        return self._registry.current_gateway().run_night_turn(context)

    def run_governance_task(
        self, context: GovernanceLLMContext
    ) -> GovernanceLLMResult:
        return self._registry.current_gateway().run_governance_task(context)
