from __future__ import annotations

import asyncio
import base64
import binascii
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import re
import secrets

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from serious_game_backend.api.schemas import (
    ActionRequest,
    ActionQuoteRequest,
    ConsentSignRequest,
    ConsentWithdrawRequest,
    EndDayRequest,
    LoginRequest,
    LoadSnapshotRequest,
    ManualSaveRequest,
    RegisterRequest,
    PlayerLLMConfigurationRequest,
    ExportRequestBody,
    GovernancePurposeBody,
    GroupConversationFinishRequest,
    GroupConversationTurnRequest,
    GovernanceActionStartRequest,
    GovernanceFinishRequest,
    GovernanceTurnRequest,
    NPCDemandDispositionRequest,
    MeetingResolutionRequest,
    MeetingTurnRequest,
    DocumentEditRequest,
    DocumentCountersignRequest,
    DocumentPublishRequest,
    ContractBatchConfirmRequest,
    ContractTermsRequest,
    ContractEditRequest,
    ContractStateRequest,
    ContractSignRequest,
    RetentionRunBody,
    SubjectRequestBody,
    StartSessionRequest,
)
from serious_game_backend.application.package_lock import (
    locked_package_access,
    require_locked_package,
)
from serious_game_backend.application.action_cost_policy import quote_cost
from serious_game_backend.application.action_variants import (
    canonical_opportunity_descriptor,
    configured_variants,
    default_npc_location,
    governance_action_permission,
    public_variant,
    variant_availability,
)
from serious_game_backend.application.stream_lifecycle import StreamCancellation
from serious_game_backend.application.npc_relationship_service import (
    NPCRelationshipService,
)
from serious_game_backend.bootstrap import Container, build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import (
    DomainError,
    NotFoundError,
    PackageRetiredError,
)
from serious_game_backend.domain.errors import (
    AuthenticationRequiredError,
    PlayerLLMConfigurationRequiredError,
    RegistrationDisabledError,
)
from serious_game_backend.domain.identity import PERMISSION_PLAY, PLAYER, Principal
from serious_game_backend.domain.identity import PERMISSION_OPERATE


_principal_context: ContextVar[Principal | None] = ContextVar(
    "serious_game_principal", default=None
)

_PUBLIC_NPC_TITLES = {
    "老倔头": "柳林村独户",
    "苗喜旺": "柳林村村民、水暖工",
    "邓守本": "柳林村独居老人",
    "蒋崇岳": "云溪县委书记",
    "罗健": "县卫生院防疫科工作人员",
    "崔广林": "县信访办卷宗室工作人员",
}


def _public_npc_description(name: str, role_setting: str) -> tuple[str, str]:
    """Extract only the public heading and opening sentence from a role profile.

    The rest of role_setting contains hidden motives and model-only knowledge and
    must never be projected to a player-facing DTO.
    """
    lines = [line.strip() for line in role_setting.splitlines() if line.strip()]
    title = ""
    if lines and lines[0].startswith("#"):
        heading = lines[0].lstrip("#").strip()
        for separator in ("：", ":"):
            prefix = f"{name}{separator}"
            if heading.startswith(prefix):
                title = heading[len(prefix):].strip()
                break
    content_lines = lines[1:] if lines and lines[0].startswith("#") else lines
    opening = next((line for line in content_lines if not line.startswith("#")), "")
    if "。" in opening:
        opening = opening.split("。", 1)[0].strip() + "。"
    # Keep the public introduction concise and stop before later clauses that
    # may contain story-only knowledge or hidden motivations.
    clauses = opening.rstrip("。").split("，")
    if len(clauses) > 2:
        opening = "，".join(clauses[:2]).strip() + "。"
    if len(opening) > 120:
        opening = opening[:119].rstrip("，、；： ") + "……"
    title = title or _PUBLIC_NPC_TITLES.get(name, "剧情人物")
    return title, opening or f"{name}，{title}。"


def _opportunity_context(entry_type: str, action_name: str) -> str:
    entry_labels = {
        "story_followup": "剧情后续交谈",
        "stage_handoff": "阶段衔接会面",
        "story_window": "当前阶段可主动联系",
        "conditional_recovery": "条件触发的再次接触",
    }
    prefix = entry_labels.get(entry_type, "当前可接触")
    return f"{prefix}，接触方式：{action_name}"


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    effective_settings = settings or Settings.from_env()
    runtime = container or build_container(effective_settings)
    app = FastAPI(
        title="浊流之上后端",
        version="0.1.0",
        description="游戏权威运行时；前端通过玩家 API 与其交互。",
    )
    app.state.container = runtime
    authentication_enabled = (
        effective_settings.environment == "production"
        or effective_settings.auth_required
    )

    def error_response(exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return error_response(exc)

    def retired_session_error(path: str, account_id: str) -> DomainError | None:
        match = re.match(r"^/api/game/session/([^/]+)(?:/|$)", path)
        if match is None:
            return None
        try:
            session = runtime.game_sessions.get_owned(match.group(1), account_id)
        except DomainError as exc:
            # Middleware runs outside FastAPI's route exception handler.
            return exc
        package = runtime.packages.get(session.package_id) if session else None
        if package is not None and package.status == "retired":
            return PackageRetiredError("退役剧本包仅供复盘，不能继续写入")
        return None

    def ai_configuration_error_for_gameplay(
        request: Request, scope_id: str
    ) -> DomainError | None:
        if effective_settings.environment == "test":
            return None
        if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return None
        if not request.url.path.startswith("/api/game/session"):
            return None
        if runtime.player_llm_configs.status(scope_id).active:
            return None
        return PlayerLLMConfigurationRequiredError(
            "请先配置并启用 AI 接口，再开始或继续活动存档"
        )

    @app.middleware("http")
    async def production_authentication(request: Request, call_next):
        if not authentication_enabled:
            account_id = request.headers.get("X-Account-ID", "").strip()
            if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                retired_error = retired_session_error(request.url.path, account_id)
                if retired_error is not None:
                    return error_response(retired_error)
            if not account_id or not request.url.path.startswith("/api/"):
                return await call_next(request)
            with runtime.player_llm_configs.bind(
                account_id, require_selection=effective_settings.environment != "test"
            ):
                configuration_error = ai_configuration_error_for_gameplay(
                    request, account_id
                )
                if configuration_error is not None:
                    return error_response(configuration_error)
                return await call_next(request)
        public_paths = {
            "/health/live", "/health/ready", "/api/auth/login", "/api/auth/register",
            # Logout must remain idempotent when the authentication cookie has
            # already expired or been revoked. The route only revokes the
            # presented cookie and clears it from the response.
            "/api/auth/logout",
            "/docs", "/openapi.json", "/redoc",
        }
        if request.url.path in public_paths:
            return await call_next(request)
        try:
            principal = runtime.auth.authenticate(
                request.cookies.get(effective_settings.auth_cookie_name)
            )
            if request.url.path.startswith("/api/game"):
                runtime.auth.require(principal, PERMISSION_PLAY)
            if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                runtime.auth.verify_csrf(
                    principal, request.headers.get("X-CSRF-Token")
                )
                retired_error = retired_session_error(
                    request.url.path, principal.account_id
                )
                if retired_error is not None:
                    raise retired_error
        except DomainError as exc:
            return error_response(exc)
        context_token = _principal_context.set(principal)
        try:
            with runtime.player_llm_configs.bind(
                principal.auth_session_hash,
                require_selection=effective_settings.environment != "test",
            ):
                configuration_error = ai_configuration_error_for_gameplay(
                    request, principal.auth_session_hash
                )
                if configuration_error is not None:
                    return error_response(configuration_error)
                return await call_next(request)
        finally:
            _principal_context.reset(context_token)

    def current_account_id(x_account_id: str | None = Header(default=None)) -> str:
        if authentication_enabled:
            principal = _principal_context.get()
            if principal is None:
                raise AuthenticationRequiredError("缺少可信登录身份")
            return principal.account_id
        value = (x_account_id or "").strip()
        if not value:
            raise DomainError("沙盒请求必须提供 X-Account-ID")
        return value

    def current_llm_scope_id(x_account_id: str | None = Header(default=None)) -> str:
        if authentication_enabled:
            principal = _principal_context.get()
            if principal is None:
                raise AuthenticationRequiredError("缺少可信登录身份")
            return principal.auth_session_hash
        return current_account_id(x_account_id)

    def current_llm_expiry() -> datetime | None:
        if not authentication_enabled:
            return None
        principal = _principal_context.get()
        if principal is None:
            raise AuthenticationRequiredError("缺少可信登录身份")
        auth_session = runtime.auth_sessions.get(principal.auth_session_hash)
        if auth_session is None:
            raise AuthenticationRequiredError("登录会话无效或已过期")
        return datetime.fromisoformat(auth_session.expires_at)

    def npc_reply_items(result: dict) -> list[dict]:
        reply = result.get("npc_reply")
        if isinstance(reply, dict) and reply.get("text"):
            return [reply]
        for key in ("replies", "turn_dialogues"):
            values = result.get(key)
            if isinstance(values, list):
                return [
                    item for item in values
                    if isinstance(item, dict) and item.get("text")
                ]
        return []

    async def npc_stream(
        result: dict,
        *,
        include_start: bool = True,
        include_thinking: bool = True,
        include_replies: bool = True,
    ):
        if include_start:
            yield json.dumps(
                {"type": "stream_start"}, ensure_ascii=False
            ) + "\n"
        for index, reply in enumerate(npc_reply_items(result) if include_replies else ()):
            stream_id = f"{reply.get('npc_id', 'npc')}:{index}"
            identity = {
                "stream_id": stream_id,
                "npc_id": reply.get("npc_id", ""),
                "npc_name": reply.get("npc_name", ""),
                "dialogue_mode": reply.get("dialogue_mode", "persuasion"),
            }
            if include_thinking:
                yield json.dumps({
                    "type": "npc_thinking_start", **identity,
                }, ensure_ascii=False) + "\n"
                yield json.dumps({
                    "type": "npc_thinking_end", **identity,
                }, ensure_ascii=False) + "\n"
            yield json.dumps({
                "type": "npc_start",
                **identity,
            }, ensure_ascii=False) + "\n"
            text = str(reply["text"])
            for offset in range(0, len(text), 4):
                yield json.dumps({
                    "type": "npc_delta",
                    "stream_id": stream_id,
                    "delta": text[offset:offset + 4],
                }, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.028)
            yield json.dumps({
                "type": "npc_end", **identity,
            }, ensure_ascii=False) + "\n"
        yield json.dumps(
            {"type": "complete", "result": result}, ensure_ascii=False
        ) + "\n"

    def npc_stream_response(result: dict) -> StreamingResponse:
        return StreamingResponse(
            npc_stream(result),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    def live_npc_stream_response(
        call,
        *,
        bind_operation_abort: bool = False,
        **kwargs,
    ) -> StreamingResponse:
        frozen_gateway = runtime.player_llm_configs.freeze_current()

        async def generate():
            with runtime.player_llm_configs.bind_frozen(frozen_gateway):
                async for chunk in generate_bound():
                    yield chunk

        async def generate_bound():
            queue: asyncio.Queue[dict] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            cancelled = StreamCancellation()

            def emit(event: dict) -> None:
                loop.call_soon_threadsafe(queue.put_nowait, event)

            call_kwargs = {
                "stream_event": emit,
                "stream_cancelled": cancelled.is_set,
                **kwargs,
            }
            if bind_operation_abort:
                call_kwargs["stream_cancel_register"] = cancelled.add_callback
            task = asyncio.create_task(run_in_threadpool(call, **call_kwargs))
            try:
                yield json.dumps({"type": "stream_start"}, ensure_ascii=False) + "\n"
                while not task.done() or not queue.empty():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.05)
                    except asyncio.TimeoutError:
                        continue
                    if event.get("type") == "_npc_reply_ready":
                        acknowledged = event.get("acknowledged")
                        try:
                            async for chunk in npc_stream(
                                {"npc_reply": event["reply"]},
                                include_start=False,
                                include_thinking=False,
                            ):
                                document = json.loads(chunk)
                                if document.get("type") != "complete":
                                    yield chunk
                        finally:
                            if acknowledged is not None:
                                acknowledged.set()
                        continue
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                try:
                    result = await task
                except DomainError as exc:
                    if exc.code == "ROLE_LLM_CONFIGURATION_REQUIRED":
                        yield json.dumps({
                            "type": "error",
                            "code": exc.code,
                            "message": "请先配置并启用 AI 接口。",
                        }, ensure_ascii=False) + "\n"
                        return
                    yield json.dumps({
                        "type": "error",
                        "code": "NPC_RESPONSE_UNAVAILABLE",
                        "message": "对方暂时无法回应，请稍后重试。",
                    }, ensure_ascii=False) + "\n"
                    return
                except Exception:
                    yield json.dumps({
                        "type": "error",
                        "code": "NPC_RESPONSE_UNAVAILABLE",
                        "message": "对方暂时无法回应，请稍后重试。",
                    }, ensure_ascii=False) + "\n"
                    return
                async for chunk in npc_stream(
                    result,
                    include_start=False,
                    include_thinking=False,
                    include_replies=False,
                ):
                    yield chunk
            finally:
                try:
                    cancelled.cancel()
                except Exception:
                    # Stream closure is best-effort; repository CAS is the
                    # final ownership boundary for operation transitions.
                    pass
                if not task.done():
                    task.cancel()

        return StreamingResponse(
            generate(),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    def privileged_principal() -> Principal:
        principal = _principal_context.get()
        if principal is None:
            raise AuthenticationRequiredError("治理接口仅接受正式 Cookie 登录身份")
        return principal

    def required_opportunity(session, package) -> dict | None:
        """Return the current story-required conversation, when one exists.

        The source of truth is the beat's end-day flag requirement and the
        interaction opportunity's completion flags. This keeps the UI guided
        by authoritative state instead of hard-coding a calendar day or NPC.
        """
        beat = package.story_day(session.game_state.story_day)
        if beat is None or not beat.end_day_requires_flags:
            return None
        missing = set(beat.end_day_requires_flags) - set(session.flags)
        if not missing:
            return None
        available = runtime.opportunities.list_available(session, package)
        candidate = next(
            (
                item for item in available
                if missing.intersection(item.completion_flags)
            ),
            None,
        )
        if candidate is None:
            return None
        profile = next(
            (item for item in package.npc_profiles if item.npc_id == candidate.npc_id),
            None,
        )
        name = profile.name if profile is not None else candidate.npc_id
        description = (
            f"请先与{name}交谈，了解村庄关系与真实顾虑。"
            if candidate.npc_id == "npc_wu_xiuying"
            else f"请先完成与{name}的会谈，以满足当前剧情前置条件。"
        )
        return {
            "opportunity_id": candidate.opportunity_id,
            "npc_id": candidate.npc_id,
            "npc_name": name,
            "action_id": candidate.action_id,
            "entry_type": candidate.entry_type,
            "entry_description": "寻找会谈",
            "reason": description,
            "missing_flags": sorted(missing),
        }

    def command_gate(session, package) -> dict:
        pending = session.pending_decision is not None
        conversing = session.active_conversation is not None
        group_conversing = session.active_group_conversation is not None
        governance_active = any(
            item.status == "active"
            for item in session.governance_actions.values()
        )
        busy = session.processing_action_id is not None
        beat = package.story_day(session.game_state.story_day)
        active = session.status.value == "active"
        allow_actions = (
            beat is None
            or beat.allow_actions
            or (
                package.gameplay_schema_version >= 2
                and session.game_state.story_day < 90
            )
        )
        allow_end_day = (
            beat is None
            or (
                beat.allow_end_day
                and beat.end_day_requires_flags.issubset(session.flags)
            )
        )
        action_blocked_reason = None
        if package.status == "retired":
            action_blocked_reason = "该剧本包已退役，本局仅供复盘"
        elif not active:
            action_blocked_reason = "本局已经结束"
        elif busy:
            action_blocked_reason = "上一操作仍在处理中，请等待原操作完成"
        elif pending:
            action_blocked_reason = "必须先处理当前决策"
        elif group_conversing:
            action_blocked_reason = "必须先完成NPC发起的群组会谈"
        elif governance_active:
            action_blocked_reason = "基础行动场景正在进行，请先继续或结束"
        elif conversing:
            action_blocked_reason = "会谈正在进行，请先继续或结束当前会谈"
        elif not allow_actions:
            action_blocked_reason = "当前剧情节点不开放自主行动"
        can_inspect_archives, inspect_blocked_reason = governance_action_permission(
            session, package, "inspect_archives"
        )
        required = required_opportunity(session, package)
        return {
            "can_choose": (
                package.status != "retired" and active and not busy and pending
                and not conversing and not group_conversing
            ),
            "can_act": (
                package.status != "retired"
                and active and not busy and not pending and not conversing
                and not group_conversing and not governance_active and allow_actions
            ),
            "can_talk": (
                package.status != "retired"
                and active and not busy and not pending and not group_conversing
                and not governance_active and (conversing or allow_actions)
            ),
            "can_end_day": (
                package.status != "retired"
                and active and not busy and not pending and not conversing
                and not group_conversing and not governance_active and allow_end_day
            ),
            # A pending decision blocks ordinary actions but still permits the
            # player to inspect already-acquired archives.  This is a separate
            # capability so callers cannot accidentally treat it as permission
            # to start other actions while the decision remains pending.
            "can_inspect_archives": can_inspect_archives,
            "action_blocked_reason": action_blocked_reason,
            "inspect_blocked_reason": inspect_blocked_reason,
            "required_opportunity": required,
        }

    def executable_variant(session, package, variant, gate) -> dict:
        descriptor = public_variant(session, package, variant)
        permission_key = (
            "can_inspect_archives"
            if variant.get("action_id") == "inspect_archives"
            else "can_act"
        )
        reason = (
            gate["inspect_blocked_reason"]
            if permission_key == "can_inspect_archives"
            else gate["action_blocked_reason"]
        )
        if not gate[permission_key] and reason is None:
            reason = "当前不能执行该行动"
        if reason is None and session.game_state.action_points < descriptor["cost_action_points"]:
            reason = "今日精力不足"
        if reason:
            descriptor.update(available=False, unavailable_reason=reason)
        return descriptor

    def action_entries(session, package) -> tuple[str, list[dict]]:
        NPCRelationshipService.synchronize(session, package)
        state = session.game_state
        tier = package.action_cost_tier(state.story_day)
        gate = command_gate(session, package)
        if package.gameplay_schema_version >= 2 and package.governance_config:
            active = any(
                item.status == "active"
                for item in session.governance_actions.values()
            )
            values = []
            for item in package.governance_config.get("base_actions", []):
                base = int(item.get("costs", {}).get(tier.value, item["cost"]))
                cost_result = quote_cost(
                    session, str(item["action_id"]), base
                )
                cost = cost_result.final_cost
                permission_key = (
                    "can_inspect_archives"
                    if item["action_id"] == "inspect_archives"
                    else "can_act"
                )
                available = (
                    gate[permission_key]
                    and not active
                    and state.action_points >= cost
                )
                values.append({
                    "action_id": item["action_id"],
                    "name": item["name"],
                    "category": "基础行动",
                    "cost": cost,
                    "cost_breakdown": {
                        "base": cost_result.base_cost,
                        "friction": cost_result.friction,
                        "discount": cost_result.discount,
                        "reasons": list(cost_result.reasons),
                    },
                    "available": available,
                    "unavailable_reason": (
                        (
                            gate["inspect_blocked_reason"]
                            if permission_key == "can_inspect_archives"
                            else gate["action_blocked_reason"]
                        )
                        if not available else None
                    ),
                    "execution_mode": "governance",
                    "description": item["description"],
                    "permissions": item["permissions"],
                    "target_kind": item["target_kind"],
                    "variants": [
                        executable_variant(session, package, variant, gate)
                        for variant in configured_variants(package)
                        if variant.get("action_id") == item["action_id"]
                        and variant_availability(session, variant)[0]
                    ] if package.gameplay_schema_version >= 4 else [],
                })
            return tier.value, values
        available_opportunities = (
            runtime.opportunities.list_available(session, package)
            if gate["can_act"] else ()
        )
        npc_names = {item.npc_id: item.name for item in package.npc_profiles}
        result = []
        for rule in package.action_rules.values():
            cost_result = quote_cost(session, rule.action_id, rule.cost_for(tier))
            cost = cost_result.final_cost
            opportunity_ids = [
                item.opportunity_id for item in available_opportunities
                if item.action_id == rule.action_id
            ]
            definition = package.resource_actions.get(rule.action_id)
            conversation_only = bool(
                definition and definition.executor_kind == "conversation"
            )
            resource_available = bool(
                definition
                and definition.enabled
                and state.story_day >= definition.unlock_day
                and not conversation_only
                and definition.required_flags.issubset(session.flags)
                and (
                    not definition.required_any_flags
                    or bool(definition.required_any_flags & session.flags)
                )
                and not bool(definition.forbidden_flags & session.flags)
            )
            target_choices = (
                resource_target_choices(session, package, rule.action_id)
                if resource_available else []
            )
            if definition and resource_available and (
                len(target_choices) < int(definition.target_schema.get("min_items", 0))
            ):
                resource_available = False
            available = gate["can_act"] and (
                bool(opportunity_ids) or resource_available
            ) and state.action_points >= cost
            reason = gate["action_blocked_reason"]
            if reason is None and definition and not definition.enabled:
                reason = definition.unavailable_reason or "当前版本尚未开放"
            elif reason is None and not opportunity_ids and not resource_available:
                reason = "当前剧情尚未出现可用入口或程序条件未满足"
            elif (
                reason is None
                and rule.daily_cap is not None
                and state.daily_action_counts.get(rule.action_id, 0) >= rule.daily_cap
            ):
                available, reason = False, "今日次数已用尽"
            elif reason is None and rule.half_day and state.half_day_action_used:
                available, reason = False, "今日半日行程已占用"
            elif reason is None and rule.precondition_flags_any and not any(
                flag in session.flags for flag in rule.precondition_flags_any
            ):
                available, reason = False, "前置条件尚未满足"
            elif reason is None and state.action_points < cost:
                reason = "行动点不足"
            result.append({
                "action_id": rule.action_id,
                "name": rule.name,
                "category": rule.category,
                "cost_action_points": cost,
                "cost_breakdown": {
                    "base": cost_result.base_cost,
                    "friction": cost_result.friction,
                    "discount": cost_result.discount,
                    "reasons": list(cost_result.reasons),
                },
                "available": available,
                "unavailable_reason": reason,
                "opportunity_ids": opportunity_ids,
                "opportunity_labels": {
                    item.opportunity_id: npc_names.get(item.npc_id, item.npc_id)
                    for item in available_opportunities
                    if item.opportunity_id in opportunity_ids
                },
                "execution_mode": (
                    "conversation" if conversation_only or opportunity_ids
                    else "resource_action"
                ),
                "requires_quote": bool(resource_available),
                "target_schema": definition.target_schema if resource_available else None,
                "target_choices": (
                    target_choices if resource_available else []
                ),
                "parameter_schema": definition.parameter_schema if resource_available else None,
                "direct_budget_cost": (
                    definition.budget_cost if resource_available else None
                ),
            })
        return tier.value, result

    def resource_target_choices(session, package, action_id: str) -> list[dict]:
        definition = package.resource_actions[action_id]
        target_kind = str(definition.target_schema.get("target_kind", "npc"))
        if target_kind == "household":
            return [
                {
                    "target_id": item.household_id,
                    "label": (
                        f"{item.household_id}｜{item.registered_population}人｜"
                        f"住宅 {item.legal_residential_area_m2:g}㎡"
                    ),
                }
                for item in package.households
            ]
        if target_kind == "fact":
            return [
                {"target_id": fact_id, "label": package.facts[fact_id].title}
                for fact_id in sorted(session.known_fact_ids)
                if fact_id in package.facts
            ]
        if target_kind == "location":
            return [
                {"target_id": item.location_id, "label": item.name}
                for item in package.map_locations
                if session.game_state.story_day >= item.unlock_day
                and item.required_flags.issubset(session.flags)
            ]
        if action_id in {"cross_validate_clues", "zheng_clue_summary"}:
            return [
                {"target_id": fact_id, "label": package.facts[fact_id].title}
                for fact_id in sorted(session.known_fact_ids)
                if fact_id in package.facts
            ]
        if action_id == "field_visit":
            return [
                {"target_id": item.location_id, "label": item.name}
                for item in package.map_locations
                if session.game_state.story_day >= item.unlock_day
                and item.required_flags.issubset(session.flags)
            ]
        visible_npc_ids = (
            NPCRelationshipService.actionable_npc_ids(session, package)
            if package.gameplay_schema_version >= 4
            else set(session.npc_states)
        )
        return [
            {"target_id": item.npc_id, "label": item.name}
            for item in package.npc_profiles
            if item.npc_id in session.npc_states
            and item.npc_id in visible_npc_ids
        ]

    def public_acquisition_method(
        method: dict[str, object], *, fact_id: str | None = None,
        include_binding: bool = False,
    ) -> dict:
        return {
            **({"fact_id": fact_id} if include_binding and fact_id is not None else {}),
            "route_type": str(method["route_type"]),
            **({"source_id": str(method["source_id"])} if include_binding else {}),
            "unlock_day": int(method["unlock_day"]),
            "label": str(method["label"]),
            "instructions": str(method["instructions"]),
        }

    def public_fact(item) -> dict:
        return {
            "fact_id": item.fact_id,
            "title": item.title,
            "text": item.text,
            "category": item.category,
            "source_label": item.source_label,
            "related_npc_ids": list(item.related_npc_ids),
            "use_hint": item.use_hint,
            "acquisition_methods": [
                public_acquisition_method(method, fact_id=item.fact_id)
                for method in item.acquisition_methods
            ],
        }

    def related_materials(session, package, npc_id: str) -> list[dict]:
        values = [
            public_fact(package.facts[fact_id])
            for fact_id in sorted(session.known_fact_ids)
            if fact_id in package.facts
            and npc_id in package.facts[fact_id].related_npc_ids
        ]
        policy = package.public_briefing["compensation_policy"]
        values.append({
            "material_id": "public_compensation_policy",
            "title": policy["title"],
            "text": "统一按依法登记的房屋、土地、人口和政策项目核算；具体计价参数尚待正式细则补全。",
            "category": "policy",
            "source_label": "县长案头公开政策底册",
            "use_hint": "可向任何相关方说明已确定原则；未配置的单价和额度不得口头承诺。",
        })
        return values

    @app.get("/health/live")
    async def live() -> dict:
        return {
            "status": "ok",
            "service": "serious-game-backend",
            "terminal_protocol_version": "text-gameplay-v3",
        }

    @app.get("/health/ready")
    async def ready() -> dict:
        package = runtime.packages.get(effective_settings.default_package_id)
        return {
            "status": "ready" if package else "not_ready",
            "default_package_id": effective_settings.default_package_id,
            "llm_provider": effective_settings.role_llm_provider,
            "llm_model": effective_settings.role_llm_model,
            "repository": effective_settings.repository,
            "authentication_required": authentication_enabled,
            "self_registration": effective_settings.allow_self_registration,
            "model_consent_required": effective_settings.require_model_consent,
            "csrf_cookie_name": f"{effective_settings.auth_cookie_name}_csrf",
            "player_ai_configuration": True,
            "server_default_ai_available": runtime.player_llm_configs.server_default_available,
        }

    @app.post("/api/auth/login")
    async def login(body: LoginRequest, response: Response) -> dict:
        raw_token, csrf_token, principal, expires_at = runtime.auth.login(
            body.username, body.password
        )
        return set_login_cookie(
            response, raw_token, csrf_token, principal, expires_at
        )

    def set_login_cookie(
        response: Response, raw_token: str, csrf_token: str,
        principal: Principal, expires_at: str,
    ) -> dict:
        account = runtime.accounts.get_by_id(principal.account_id)
        response.set_cookie(
            key=effective_settings.auth_cookie_name,
            value=raw_token,
            httponly=True,
            secure=effective_settings.auth_cookie_secure,
            samesite="lax",
            max_age=effective_settings.auth_session_ttl_seconds,
            path="/",
        )
        return {
            "account_id": principal.account_id,
            "username": account.username if account is not None else "",
            "roles": sorted(principal.roles),
            "csrf_token": csrf_token,
            "expires_at": expires_at,
        }

    @app.post("/api/auth/register", status_code=201)
    async def register(body: RegisterRequest, response: Response) -> dict:
        if not effective_settings.allow_self_registration:
            raise RegistrationDisabledError("当前环境未开放自助注册")
        account = runtime.auth.create_account(
            account_id=f"acct_{secrets.token_hex(16)}",
            username=body.username,
            password=body.password,
            roles=frozenset({PLAYER}),
        )
        raw_token, csrf_token, principal, expires_at = runtime.auth.login(
            account.username, body.password
        )
        return set_login_cookie(
            response, raw_token, csrf_token, principal, expires_at
        )

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request, response: Response) -> Response:
        raw_token = request.cookies.get(effective_settings.auth_cookie_name)
        if raw_token:
            runtime.player_llm_configs.clear(
                hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            )
        runtime.auth.logout(raw_token)
        response.delete_cookie(
            effective_settings.auth_cookie_name,
            path="/",
            secure=effective_settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        response.status_code = 204
        return response

    @app.get("/api/auth/me")
    async def auth_me(x_account_id: str | None = Header(default=None)) -> dict:
        account_id = current_account_id(x_account_id)
        principal = _principal_context.get()
        account = runtime.accounts.get_by_id(account_id)
        return {
            "account_id": account_id,
            "username": account.username if account is not None else "",
            "roles": sorted(principal.roles) if principal else ["sandbox"],
        }

    @app.get("/api/consent/current")
    async def current_consent(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        record = runtime.consents.latest(account_id)
        return {
            "required_version": effective_settings.consent_version,
            "document_hash": effective_settings.consent_document_hash,
            "model_provider": effective_settings.consent_model_provider,
            "processing_region": effective_settings.consent_processing_region,
            "retention_days_raw_text": effective_settings.raw_text_retention_days,
            "model_consent_required": effective_settings.require_model_consent,
            "record": ({
                "consent_record_id": record.consent_record_id,
                "consent_version": record.consent_version,
                "scopes": sorted(record.scopes),
                "signed_at": record.signed_at,
                "withdrawn_at": record.withdrawn_at,
            } if record else None),
        }

    @app.post("/api/consent")
    async def sign_consent(
        body: ConsentSignRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        record = runtime.consents.sign(
            account_id=account_id,
            consent_version=body.consent_version,
            scopes=frozenset(body.scopes),
        )
        return {
            "consent_record_id": record.consent_record_id,
            "consent_version": record.consent_version,
            "scopes": sorted(record.scopes),
            "signed_at": record.signed_at,
        }

    @app.post("/api/consent/withdraw")
    async def withdraw_consent(
        body: ConsentWithdrawRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        record = runtime.consents.withdraw(account_id=account_id, reason=body.reason)
        return {
            "consent_record_id": record.consent_record_id,
            "withdrawn_at": record.withdrawn_at,
        }

    @app.post("/api/privacy/requests", status_code=202)
    async def create_subject_request(
        body: SubjectRequestBody,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        request = runtime.governance.request_subject_action(
            current_account_id(x_account_id), body.request_type, body.reason
        )
        return {"request_id": request.request_id, "status": request.status,
                "request_type": request.request_type, "created_at": request.created_at}

    @app.post("/api/admin/privacy/requests/{request_id}/process")
    async def process_subject_request(request_id: str, body: GovernancePurposeBody) -> dict:
        result = runtime.governance.process_subject_action(
            privileged_principal(), request_id, purpose=body.purpose
        )
        return {"request_id": result.request_id, "status": result.status,
                "completed_at": result.completed_at, "result": result.result}

    @app.post("/api/admin/research/exports", status_code=202)
    async def request_research_export(body: ExportRequestBody) -> dict:
        job = runtime.governance.request_export(
            privileged_principal(), purpose=body.purpose,
            fields=tuple(body.fields), conditions=body.conditions,
            minimum_cell_size=body.minimum_cell_size,
        )
        return {"export_job_id": job.export_job_id, "status": job.status}

    @app.post("/api/admin/research/exports/{export_job_id}/approve")
    async def approve_research_export(export_job_id: str, body: GovernancePurposeBody) -> dict:
        job = runtime.governance.approve_export(
            privileged_principal(), export_job_id, purpose=body.purpose
        )
        return {"export_job_id": job.export_job_id, "status": job.status,
                "approved_by": job.approved_by}

    @app.post("/api/admin/research/exports/{export_job_id}/materialize")
    async def materialize_research_export(export_job_id: str, body: GovernancePurposeBody) -> dict:
        return runtime.governance.materialize_export(
            privileged_principal(), export_job_id, purpose=body.purpose
        )

    @app.post("/api/admin/retention/run")
    async def run_retention(body: RetentionRunBody) -> dict:
        result = runtime.governance.apply_retention(
            privileged_principal(), cutoff_at=body.cutoff_at,
            policy_version=body.policy_version, purpose=body.purpose,
        )
        return result.__dict__ if hasattr(result, "__dict__") else {
            "policy_version": result.policy_version, "cutoff_at": result.cutoff_at,
            "raw_research_text_removed": result.raw_research_text_removed,
            "auth_sessions_removed": result.auth_sessions_removed,
        }

    @app.post("/api/admin/research/outbox/drain")
    async def drain_research_outbox(limit: int = Query(default=100, ge=1, le=1000)) -> dict:
        principal = privileged_principal()
        runtime.auth.require(principal, PERMISSION_OPERATE)
        return {"dispatched": runtime.research_outbox.drain(limit)}

    @app.post("/api/game/session", status_code=201)
    async def start_session(
        body: StartSessionRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        package_id = body.package_id or effective_settings.default_package_id
        session = runtime.game_sessions.start_session(
            account_id=account_id,
            package_id=package_id,
            client_request_id=body.client_request_id,
            origin_id="mayor",
        )
        package = require_locked_package(runtime.packages, session)
        return runtime.projector.project(session, package)

    @app.get("/api/game/origins")
    async def list_origins(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        current_account_id(x_account_id)
        package = runtime.packages.get(effective_settings.default_package_id)
        if package is None:
            raise NotFoundError("默认剧本包不存在")
        return {
            "package_id": package.package_id,
            "selection_required": False,
            "origins": [],
        }

    @app.get("/api/game/package/validation")
    async def get_package_validation(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        current_account_id(x_account_id)
        package = runtime.packages.get(effective_settings.default_package_id)
        if package is None:
            raise NotFoundError("默认剧本包不存在")
        return runtime.package_validation.build_report(package)

    @app.get("/api/game/session/latest-active")
    async def get_latest_active(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.latest_active(account_id)
        package = require_locked_package(runtime.packages, session)
        return runtime.projector.project(session, package)

    @app.get("/api/game/sessions")
    async def list_game_sessions(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        def summary(session) -> dict:
            _, access = locked_package_access(runtime.packages, session)
            return {
                "session_id": session.session_id,
                "story_day": session.game_state.story_day,
                "status": session.status.value,
                "state_version": session.state_version,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                **access,
            }
        return {
            "sessions": [summary(session) for session in runtime.sessions.list_for_account(account_id)]
        }

    def player_llm_status(scope_id: str) -> dict:
        value = runtime.player_llm_configs.status(scope_id).public_dict()
        value["server_default"] = runtime.player_llm_configs.server_default_summary()
        return value

    @app.get("/api/ai/config")
    async def get_player_llm_configuration(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return player_llm_status(current_llm_scope_id(x_account_id))

    @app.put("/api/ai/config")
    async def put_player_llm_configuration(
        body: PlayerLLMConfigurationRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        scope_id = current_llm_scope_id(x_account_id)
        if body.mode == "server_default":
            runtime.player_llm_configs.use_server_default(
                scope_id, expires_at=current_llm_expiry()
            )
        else:
            runtime.player_llm_configs.use_personal(
                scope_id,
                base_url=body.base_url or "",
                api_key=body.api_key or "",
                model=body.model or "",
                expires_at=current_llm_expiry(),
            )
        return player_llm_status(scope_id)

    @app.delete("/api/ai/config")
    async def delete_player_llm_configuration(
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        scope_id = current_llm_scope_id(x_account_id)
        runtime.player_llm_configs.clear(scope_id)
        return player_llm_status(scope_id)

    @app.get("/api/game/session/{session_id}")
    async def get_session(session_id: str, x_account_id: str | None = Header(default=None)) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        return runtime.projector.project(session, package)

    @app.get("/api/game/session/{session_id}/ai/audits")
    async def get_session_llm_audits(
        session_id: str,
        after: str = Query(default="", max_length=160),
        limit: int = Query(default=50, ge=1, le=50),
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        """Return a strict, secret-free audit projection for the owned run."""

        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        if session is None:
            raise NotFoundError("活动存档不存在")
        audits = runtime.llm_audits.list_for_owned_session(
            account_id, session_id, after=after, limit=limit
        )
        next_cursor = (
            f"{audits[-1].created_at}|{audits[-1].audit_id}" if audits else after
        )
        return {
            "run_nonce": session_id,
            "session_id": session_id,
            "next_cursor": next_cursor,
            "audits": [
                {
                    "audit_id": audit.audit_id,
                    "operation_id": audit.operation_id,
                    "provider": audit.provider,
                    "model": audit.model_id,
                    "endpoint_host": audit.endpoint_host,
                    "config_version": audit.config_version,
                    "status": audit.status,
                    "error_code": audit.error_code,
                    "timestamp": audit.created_at,
                    "run_id": session_id,
                    "session_id": session_id,
                }
                for audit in audits
            ],
        }

    @app.get("/api/game/session/{session_id}/view")
    async def get_terminal_view(
        session_id: str,
        after: int = Query(default=0, ge=0),
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        gate = command_gate(session, package)
        commands = {
            "can_choose": gate["can_choose"],
            "can_act": gate["can_act"],
            "can_end_day": gate["can_end_day"],
            "can_talk": gate["can_talk"] and (
                session.active_conversation is not None
                or bool(runtime.opportunities.list_available(session, package))
            ),
        }
        # Keep the retired-session read-only contract stable while exposing
        # the additional live interaction capabilities during an active game.
        if session.status.value == "active" and package.status != "retired":
            commands.update(
                can_inspect_archives=gate["can_inspect_archives"],
                required_opportunity=gate["required_opportunity"],
            )
        return {
            "state": runtime.projector.project(session, package),
            "feed": runtime.story_flow.feed_since(session, after),
            "commands": commands,
        }

    @app.get("/api/game/session/{session_id}/feed")
    async def get_narrative_feed(
        session_id: str,
        after: int = Query(default=0, ge=0),
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        require_locked_package(runtime.packages, session)
        return {
            "state_version": session.state_version,
            **runtime.story_flow.feed_since(session, after),
        }

    @app.get("/api/game/session/{session_id}/knowledge")
    async def get_known_knowledge(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        facts = [
            package.facts[fact_id]
            for fact_id in sorted(session.known_fact_ids)
            if fact_id in package.facts
        ]
        grouped = {"facts": [], "clues": [], "evidence": []}
        category_keys = {"fact": "facts", "clue": "clues", "evidence": "evidence"}
        for item in facts:
            grouped[category_keys.get(item.category, "facts")].append(public_fact(item))
        available_opportunity_ids = {
            item.opportunity_id
            for item in runtime.opportunities.list_available(session, package)
        }
        archive_unlock_days = {
            item.archive_id: item.unlock_day
            for item in package.archive_investigations
        }
        investigation_leads = []
        for fact_id, fact in sorted(package.facts.items()):
            if fact_id in session.known_fact_ids:
                continue
            methods = []
            for method in fact.acquisition_methods:
                route_type = str(method["route_type"])
                source_id = str(method["source_id"])
                unlock_day = int(method["unlock_day"])
                if unlock_day > session.game_state.story_day:
                    continue
                if route_type == "archive":
                    if archive_unlock_days.get(source_id) != unlock_day:
                        continue
                elif route_type == "action":
                    action = package.resource_actions.get(source_id)
                    if action is None or not action.enabled or action.unlock_day > session.game_state.story_day:
                        continue
                elif source_id not in available_opportunity_ids:
                    continue
                methods.append(public_acquisition_method(
                    method, fact_id=fact.fact_id, include_binding=True
                ))
            if methods:
                investigation_leads.append({
                    "fact_id": fact.fact_id,
                    "title": fact.title,
                    "category": fact.category,
                    "methods": methods,
                })
        return {
            "state_version": session.state_version,
            "known_fact_ids": sorted(session.known_fact_ids),
            "investigation_leads": investigation_leads,
            **grouped,
        }

    @app.get("/api/game/session/{session_id}/desk")
    async def get_mayor_desk(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        briefing = package.public_briefing
        tier, actions = action_entries(session, package)
        gate = command_gate(session, package)
        guidance = briefing["tool_guidance"]
        tools = [
            {
                **item,
                "description": guidance.get(item["action_id"], {}).get(
                    "description", item.get("description", "")
                ),
                "availability_note": guidance.get(item["action_id"], {}).get(
                    "availability_note", "四项基础行动在当天剧情允许行动时可用。"
                ),
            }
            for item in actions
        ]
        state = session.game_state
        npc_names = {item.npc_id: item.name for item in package.npc_profiles}
        limited_signatory_names = {
            item.household_id: item.name
            for item in package.limited_household_signatories
        }
        known = [
            package.facts[item]
            for item in sorted(session.known_fact_ids)
            if item in package.facts
        ]
        return {
            "state_version": session.state_version,
            "mission": briefing["mission"],
            "dossiers": briefing["dossiers"],
            "compensation_policy": {
                **briefing["compensation_policy"],
                "current_budget": {
                    "base_authorized": state.budget_base_authorized,
                    "remaining": state.budget_remaining,
                    "approved_adjustments": state.budget_approved_adjustments,
                    "committed": state.budget_committed,
                    "paid": state.budget_paid,
                    "precoord_suspense": state.budget_precoord_suspense,
                    "unit": state.budget_unit,
                },
            },
            "authorities": briefing["authorities"],
            "tool_categories": briefing["tool_categories"],
            "cost_tier": tier,
            "tools": tools,
            "required_opportunity": gate["required_opportunity"],
            "household_registry": [
                {
                    "household_id": item.household_id,
                    "signatory_name": limited_signatory_names.get(
                        item.household_id,
                        npc_names[item.representative_npc],
                    ),
                    "registered_population": item.registered_population,
                    "actual_residents": item.actual_residents,
                    "resettlement_population": item.resettlement_population,
                    "residential_structure": item.residential_structure,
                    "legal_residential_area_m2": item.legal_residential_area_m2,
                    "homestead_recognized_m2": item.homestead_recognized_m2,
                    "homestead_over_m2": item.homestead_over_m2,
                    "contracted_land_mu": item.contracted_land_mu,
                    "other_land_mu": item.other_land_mu,
                    "other_land_note": item.other_land_note,
                    "business_area_m2": item.business_area_m2,
                    "attachments_profile": item.attachments_profile,
                    "resettlement_preference": item.resettlement_preference,
                    "ownership_status": item.ownership_status,
                    "detail_status": "附属物数量、地类等未登记明细待核验",
                }
                for item in package.households
            ],
            "knowledge_summary": {
                "total": len(known),
                "facts": sum(item.category == "fact" for item in known),
                "clues": sum(item.category == "clue" for item in known),
                "evidence": sum(item.category == "evidence" for item in known),
            },
        }

    @app.get("/api/game/session/{session_id}/map")
    async def get_map(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        return runtime.map_service.build(session, package)

    @app.get("/api/game/session/{session_id}/review")
    async def get_review(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        return runtime.review_service.build(session, package)

    @app.get("/api/game/session/{session_id}/night-dialogues")
    async def get_night_dialogues(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        require_locked_package(runtime.packages, session)
        return {
            "session_id": session.session_id,
            "nights": [
                {
                    "story_day": item.get("story_day"),
                    "morning_brief": list(item.get("morning_card", ()))[:3],
                }
                for item in session.night_logs
            ],
        }

    @app.get("/api/game/session/{session_id}/manual-saves")
    async def list_manual_saves(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        return runtime.saves.list_manual_saves(
            account_id=account_id,
            session_id=session_id,
        )

    @app.post("/api/game/session/{session_id}/manual-saves")
    async def create_manual_save(
        session_id: str,
        body: ManualSaveRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        return runtime.saves.create_manual_save(
            account_id=account_id,
            session_id=session_id,
            client_action_id=body.client_action_id,
            state_version=body.state_version,
            slot_number=body.slot_number,
            display_name=body.display_name,
            overwrite=body.overwrite,
        )

    @app.post("/api/game/session/{session_id}/load-snapshot")
    async def load_snapshot(
        session_id: str,
        body: LoadSnapshotRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        return runtime.saves.load_snapshot(
            account_id=account_id,
            session_id=session_id,
            client_action_id=body.client_action_id,
            state_version=body.state_version,
            snapshot_id=body.snapshot_id,
            confirmed=body.confirmed,
        )

    @app.get("/api/game/session/{session_id}/actions")
    async def list_actions(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        tier, result = action_entries(session, package)
        gate = command_gate(session, package)
        return {
            "state_version": session.state_version,
            "cost_tier": tier,
            "actions": result,
            "required_opportunity": gate["required_opportunity"],
        }

    @app.get("/api/game/session/{session_id}/governance")
    async def governance_overview(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        result = runtime.gameplay_governance.overview(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
        )
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        result["required_opportunity"] = required_opportunity(session, package)
        can_inspect_archives, inspect_blocked_reason = governance_action_permission(
            session, package, "inspect_archives"
        )
        result["can_inspect_archives"] = can_inspect_archives
        result["inspect_blocked_reason"] = inspect_blocked_reason
        return result

    @app.post(
        "/api/game/session/{session_id}/governance/npc-demands/{demand_id}/dispose"
    )
    def dispose_npc_demand(
        session_id: str,
        demand_id: str,
        body: NPCDemandDispositionRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.dispose_npc_demand(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            demand_id=demand_id,
            transition=body.transition,
        )

    @app.get(
        "/api/game/session/{session_id}/governance/archives/{archive_id}"
    )
    async def governance_archive_detail(
        session_id: str,
        archive_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.archive_detail(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            archive_id=archive_id,
        )

    @app.post("/api/game/session/{session_id}/governance/actions", status_code=201)
    def start_governance_action(
        session_id: str,
        body: GovernanceActionStartRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.start_action(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            action_kind=body.action_kind,
            variant_id=body.variant_id,
            location_id=body.location_id,
            opportunity_id=body.opportunity_id,
            map_entry_id=body.map_entry_id,
            target_ids=tuple(body.target_ids),
            topic=body.topic,
            archive_ids=tuple(body.archive_ids),
            proposed_document_type=body.proposed_document_type,
            lead_npc_id=body.lead_npc_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/actions/{action_instance_id}/turn"
    )
    def turn_governance_action(
        session_id: str,
        action_instance_id: str,
        body: GovernanceTurnRequest,
        x_account_id: str | None = Header(default=None),
    ):
        result = runtime.gameplay_governance.action_turn(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            action_instance_id=action_instance_id,
            player_text=body.player_text,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.post(
        "/api/game/session/{session_id}/governance/actions/"
        "{action_instance_id}/turn/stream"
    )
    async def stream_governance_action_turn(
        session_id: str,
        action_instance_id: str,
        body: GovernanceTurnRequest,
        x_account_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        account_id = current_account_id(x_account_id)
        return live_npc_stream_response(
            runtime.gameplay_governance.action_turn,
            bind_operation_abort=True,
            account_id=account_id,
            session_id=session_id,
            state_version=body.state_version,
            action_instance_id=action_instance_id,
            player_text=body.player_text,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/actions/{action_instance_id}/finish"
    )
    async def finish_governance_action(
        session_id: str,
        action_instance_id: str,
        body: GovernanceFinishRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.finish_action(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            action_instance_id=action_instance_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/actions/{action_instance_id}/cancel"
    )
    async def cancel_governance_action(
        session_id: str,
        action_instance_id: str,
        body: GovernanceFinishRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.cancel_action(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            action_instance_id=action_instance_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/meetings/{meeting_id}/turn"
    )
    def turn_governance_meeting(
        session_id: str,
        meeting_id: str,
        body: MeetingTurnRequest,
        x_account_id: str | None = Header(default=None),
    ):
        result = runtime.gameplay_governance.meeting_turn(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            meeting_id=meeting_id,
            player_text=body.player_text,
            addressed_npc_id=body.addressed_npc_id,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.post(
        "/api/game/session/{session_id}/governance/meetings/"
        "{meeting_id}/turn/stream"
    )
    async def stream_governance_meeting_turn(
        session_id: str,
        meeting_id: str,
        body: MeetingTurnRequest,
        x_account_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        account_id = current_account_id(x_account_id)
        return live_npc_stream_response(
            runtime.gameplay_governance.meeting_turn,
            bind_operation_abort=True,
            account_id=account_id,
            session_id=session_id,
            state_version=body.state_version,
            meeting_id=meeting_id,
            player_text=body.player_text,
            addressed_npc_id=body.addressed_npc_id,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/meetings/{meeting_id}/resolve"
    )
    def resolve_governance_meeting(
        session_id: str,
        meeting_id: str,
        body: MeetingResolutionRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.resolve_meeting(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            meeting_id=meeting_id,
            adopt=body.adopt,
            resolution=body.resolution,
        )

    @app.put(
        "/api/game/session/{session_id}/governance/documents/{document_id}"
    )
    async def edit_governance_document(
        session_id: str,
        document_id: str,
        body: DocumentEditRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.edit_document(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            document_id=document_id,
            content=body.content,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/documents/{document_id}/countersign"
    )
    def countersign_governance_document(
        session_id: str,
        document_id: str,
        body: DocumentCountersignRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.countersign_document(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            document_id=document_id,
            npc_id=body.npc_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/documents/{document_id}/issue"
    )
    async def issue_governance_document(
        session_id: str,
        document_id: str,
        body: ContractStateRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.issue_document(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            document_id=document_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/documents/{document_id}/publish"
    )
    async def publish_governance_document(
        session_id: str,
        document_id: str,
        body: DocumentPublishRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.publish_document(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            document_id=document_id,
            scope=tuple(body.scope),
        )

    @app.post("/api/game/session/{session_id}/governance/actions/{action_instance_id}/prepare-contracts")
    async def prepare_contracts(
        session_id: str,
        action_instance_id: str,
        body: GovernanceFinishRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.prepare_contracts(
            account_id=current_account_id(x_account_id), session_id=session_id,
            state_version=body.state_version, action_instance_id=action_instance_id,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/contract-batches/{batch_id}/confirm"
    )
    async def confirm_contract_batch(
        session_id: str,
        batch_id: str,
        body: ContractBatchConfirmRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.confirm_contract_batch(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            batch_id=batch_id,
            confirmed=body.confirmed,
        )

    @app.get(
        "/api/game/session/{session_id}/governance/contracts/{contract_id}"
    )
    async def get_governance_contract(
        session_id: str,
        contract_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.contract_detail(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            contract_id=contract_id,
        )

    @app.put(
        "/api/game/session/{session_id}/governance/contracts/{contract_id}/terms"
    )
    def set_contract_terms(
        session_id: str,
        contract_id: str,
        body: ContractTermsRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.set_contract_terms(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            contract_id=contract_id,
            term_sheet=body.term_sheet(),
            acknowledge_legacy_text=body.acknowledge_legacy_text,
        )

    @app.put(
        "/api/game/session/{session_id}/governance/contracts/{contract_id}/text"
    )
    async def edit_contract_text(
        session_id: str,
        contract_id: str,
        body: ContractEditRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.edit_contract(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            contract_id=contract_id,
            text=body.text,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/contracts/{contract_id}/review"
    )
    def review_contract(
        session_id: str,
        contract_id: str,
        body: ContractStateRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.submit_contract_review(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            contract_id=contract_id,
            expected_contract_version=body.expected_contract_version,
        )

    @app.post(
        "/api/game/session/{session_id}/governance/contracts/{contract_id}/sign"
    )
    async def sign_contract(
        session_id: str,
        contract_id: str,
        body: ContractSignRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        return runtime.gameplay_governance.sign_contract(
            account_id=current_account_id(x_account_id),
            session_id=session_id,
            state_version=body.state_version,
            contract_id=contract_id,
            confirmed=body.confirmed,
        )

    @app.get("/api/game/session/{session_id}/opportunities")
    async def list_opportunities(
        session_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        NPCRelationshipService.synchronize(session, package)
        gate = command_gate(session, package)
        if session.processing_action_id is not None:
            values = ()
        elif session.active_conversation is not None:
            values = tuple(
                item for item in package.interaction_opportunities
                if item.opportunity_id == session.active_conversation.opportunity_id
            )
        else:
            values = (
                runtime.opportunities.list_available(session, package)
                if gate["can_act"] else ()
            )
        tier = package.action_cost_tier(session.game_state.story_day)
        npc_profiles = {item.npc_id: item for item in package.npc_profiles}

        def public_opportunity(item) -> dict:
            descriptor = canonical_opportunity_descriptor(session, package, item)
            return {
                "opportunity_id": item.opportunity_id,
                "npc_id": item.npc_id,
                "npc_name": (
                    npc_profiles[item.npc_id].name
                    if item.npc_id in npc_profiles else item.npc_id
                ),
                "npc_title": (
                    _public_npc_description(
                        npc_profiles[item.npc_id].name,
                        npc_profiles[item.npc_id].role_setting,
                    )[0]
                    if item.npc_id in npc_profiles else "剧情人物"
                ),
                "npc_introduction": (
                    _public_npc_description(
                        npc_profiles[item.npc_id].name,
                        npc_profiles[item.npc_id].role_setting,
                    )[1]
                    if item.npc_id in npc_profiles
                    else "当前剧情中的可接触人物。"
                ),
                "entry_type": item.entry_type,
                "action_id": item.action_id,
                "action_name": package.action_rules[item.action_id].name,
                "conversation_context": _opportunity_context(
                    item.entry_type,
                    package.action_rules[item.action_id].name,
                ),
                "opening_narrative": item.opening_narrative,
                "conversation_goal": item.conversation_goal,
                "related_materials": related_materials(
                    session, package, item.npc_id
                ),
                "conversation_active": (
                    session.active_conversation is not None
                    and session.active_conversation.opportunity_id == item.opportunity_id
                ),
                "conversation_id": (
                    session.active_conversation.conversation_id
                    if session.active_conversation is not None
                    and session.active_conversation.opportunity_id == item.opportunity_id
                    else None
                ),
                "cost_action_points": package.action_rules[item.action_id].cost_for(tier),
                "canonical_action_descriptor": descriptor,
                "cta_available": descriptor is not None,
                "no_cta_reason": (
                    None if descriptor is not None
                    else "该人物当前仅可查看公开档案，尚无可安全执行的统一会谈入口。"
                ),
            }

        # Both screens consume the same action catalog, even after a one-off
        # story topic has closed. No new NPC visibility or execution permission.
        _, families = action_entries(session, package)
        person_actions = []
        for family in families:
            if family["action_id"] not in {"household_visit", "cadre_interview"}:
                continue
            for descriptor in family.get("variants", []):
                for target in descriptor["target_choices"]:
                    person_actions.append({
                        **descriptor,
                        "npc_id": target["target_id"],
                        "npc_name": target["label"],
                        "preselected_npc_ids": [target["target_id"]],
                        "contract_preparation": runtime.gameplay_governance.contract_preparation(
                            session, package, target["target_id"]
                        ) if family["action_id"] == "household_visit" else None,
                    })
        return {
            "state_version": session.state_version,
            "blocked_reason": gate["action_blocked_reason"],
            "person_actions": person_actions,
            "people": NPCRelationshipService.public_people(session, package),
            "relationship_edges": NPCRelationshipService.public_edges(
                session, package
            ),
            "opportunities": [public_opportunity(item) for item in values],
        }

    @app.get("/api/game/session/{session_id}/conversations")
    async def list_conversations(
        session_id: str,
        npc_id: str | None = Query(default=None, min_length=1, max_length=128),
        story_day: int | None = Query(default=None, ge=1, le=90),
        cursor: str | None = Query(default=None, min_length=1, max_length=512),
        limit: int = Query(default=20, ge=1, le=100),
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        if npc_id is not None and npc_id not in {
            item.npc_id for item in package.npc_profiles
        }:
            raise HTTPException(
                status_code=422, detail="invalid conversation npc filter"
            )
        offset = 0
        if cursor is not None:
            try:
                raw = base64.b64decode(
                    cursor.encode("ascii"), altchars=b"-_", validate=True
                )
                document = json.loads(raw.decode("utf-8"))
                if (
                    not isinstance(document, dict)
                    or set(document) != {"offset", "npc_id", "story_day"}
                    or document["npc_id"] != npc_id
                    or document["story_day"] != story_day
                    or isinstance(document["offset"], bool)
                    or int(document["offset"]) < 0
                ):
                    raise ValueError("cursor does not match filters")
                offset = int(document["offset"])
            except (
                UnicodeError, ValueError, TypeError, json.JSONDecodeError,
                binascii.Error,
            ) as exc:
                raise HTTPException(
                    status_code=422, detail="invalid conversation cursor"
                ) from exc
        values = sorted(
            (
                item
                for item in session.completed_conversations
                if (npc_id is None or item.npc_id == npc_id)
                and (story_day is None or item.story_day == story_day)
            ),
            key=lambda item: (
                item.story_day, item.started_at, item.conversation_id
            ),
        )
        if offset > len(values):
            raise HTTPException(
                status_code=422, detail="invalid conversation cursor"
            )
        page = values[offset: offset + limit]
        next_offset = offset + len(page)
        next_cursor = None
        if next_offset < len(values):
            payload = json.dumps(
                {
                    "offset": next_offset,
                    "npc_id": npc_id,
                    "story_day": story_day,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            next_cursor = base64.urlsafe_b64encode(payload).decode("ascii")
        return {
            "items": [
                {
                    "conversation_id": item.conversation_id,
                    "opportunity_id": item.opportunity_id,
                    "npc_id": item.npc_id,
                    "story_day": item.story_day,
                    "start_reason": item.start_reason,
                    "end_reason": item.end_reason,
                    "completion_status": item.completion_status,
                    "transcript": [
                        {
                            "speaker_type": str(
                                turn.get("speaker_type")
                                or turn.get("speaker")
                                or "npc"
                            ),
                            "text": str(turn.get("text", "")),
                            **(
                                {"npc_id": str(turn["npc_id"])}
                                if turn.get("npc_id") else {}
                            ),
                            **(
                                {"npc_name": str(turn["npc_name"])}
                                if turn.get("npc_name") else {}
                            ),
                        }
                        for turn in item.transcript
                    ],
                    "started_at": item.started_at,
                    "ended_at": item.ended_at,
                }
                for item in page
            ],
            "next_cursor": next_cursor,
        }

    @app.post("/api/game/session/{session_id}/action/stream")
    async def stream_action(
        session_id: str,
        body: ActionRequest,
        x_account_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        account_id = current_account_id(x_account_id)
        return live_npc_stream_response(
            runtime.actions.execute,
            bind_operation_abort=True,
            account_id=account_id,
            session_id=session_id,
            command=body.to_command(),
        )

    @app.post("/api/game/session/{session_id}/action")
    def execute_action(
        session_id: str,
        body: ActionRequest,
        x_account_id: str | None = Header(default=None),
    ):
        # This path can wait on a remote role LLM.  Keeping it synchronous lets
        # Starlette run it in a worker thread, so health checks and idempotency
        # polling remain responsive while one NPC turn is being generated.
        account_id = current_account_id(x_account_id)
        result = runtime.actions.execute(
            account_id=account_id,
            session_id=session_id,
            command=body.to_command(),
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.post("/api/game/session/{session_id}/actions/quote")
    async def quote_action(
        session_id: str,
        body: ActionQuoteRequest,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        session = runtime.game_sessions.get_owned(session_id, account_id)
        package = require_locked_package(runtime.packages, session)
        gate = command_gate(session, package)
        permitted, permission_reason = governance_action_permission(
            session, package, body.action_id
        )
        if not permitted:
            raise DomainError(permission_reason or "当前不能执行行动")
        if session.state_version != body.state_version:
            from serious_game_backend.domain.errors import StateVersionConflictError
            raise StateVersionConflictError(
                "状态版本已变化，请刷新后重试",
                details={"current_state_version": session.state_version},
            )
        quote = runtime.action_quotes.quote(
            session,
            package,
            action_id=body.action_id,
            target_ids=tuple(body.target_ids),
            parameters=body.parameters,
        )
        definition = package.resource_actions[body.action_id]
        return runtime.action_quotes.public(quote, definition)

    @app.post("/api/game/session/{session_id}/end-day")
    async def end_day(
        session_id: str,
        body: EndDayRequest,
        x_account_id: str | None = Header(default=None),
    ):
        account_id = current_account_id(x_account_id)
        result = runtime.end_days.end_day(
            account_id=account_id,
            session_id=session_id,
            client_action_id=body.client_action_id,
            state_version=body.state_version,
            retry=body.retry,
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.post("/api/game/session/{session_id}/group-conversation/turn")
    async def reply_group_conversation(
        session_id: str,
        body: GroupConversationTurnRequest,
        x_account_id: str | None = Header(default=None),
    ):
        account_id = current_account_id(x_account_id)
        result = runtime.group_conversations.reply(
            account_id=account_id,
            session_id=session_id,
            state_version=body.state_version,
            player_text=body.player_text,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.post("/api/game/session/{session_id}/group-conversation/turn/stream")
    async def stream_group_conversation_turn(
        session_id: str,
        body: GroupConversationTurnRequest,
        x_account_id: str | None = Header(default=None),
    ) -> StreamingResponse:
        account_id = current_account_id(x_account_id)
        return live_npc_stream_response(
            runtime.group_conversations.reply,
            bind_operation_abort=True,
            account_id=account_id,
            session_id=session_id,
            state_version=body.state_version,
            player_text=body.player_text,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )

    @app.post("/api/game/session/{session_id}/group-conversation/finish")
    async def finish_group_conversation(
        session_id: str,
        body: GroupConversationFinishRequest,
        x_account_id: str | None = Header(default=None),
    ):
        account_id = current_account_id(x_account_id)
        result = runtime.group_conversations.finish(
            account_id=account_id,
            session_id=session_id,
            state_version=body.state_version,
            client_action_id=body.client_action_id,
            retry=body.retry,
        )
        if result.get("status") == "processing":
            return JSONResponse(status_code=202, content=result)
        return result

    @app.get("/api/game/session/{session_id}/operations/{client_action_id}")
    async def get_operation(
        session_id: str,
        client_action_id: str,
        x_account_id: str | None = Header(default=None),
    ) -> dict:
        account_id = current_account_id(x_account_id)
        runtime.game_sessions.get_owned(session_id, account_id)
        operation = runtime.operations.get(account_id, session_id, client_action_id)
        if operation is None:
            raise NotFoundError("操作不存在")
        return {
            "operation_id": operation.operation_id,
            "status": operation.status.value,
            "attempt_count": operation.attempt_count,
            "response": operation.response,
            "error": operation.error,
        }

    return app
