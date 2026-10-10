from __future__ import annotations

import re
from dataclasses import replace
from threading import Event
from typing import Callable

from serious_game_backend.application.ports import RoleLLMGateway
from serious_game_backend.application.stream_lifecycle import (
    StreamCancelled,
    ensure_stream_open,
    wait_for_stream_ack,
)
from serious_game_backend.application.state_delta_validator import StateDeltaValidator
from serious_game_backend.domain.llm import (
    RoleTurnContext,
    RoleTurnResult,
    ValidatedRoleTurn,
)
from serious_game_backend.domain.npc_state import NPCState
from serious_game_backend.domain.errors import RoleLLMResponseError, RoleLLMUnavailableError
from serious_game_backend.domain.fact_markers import normalize_fact_signature


class NPCTurnService:
    """角色回合门面；真实供应商接入时保持此服务签名不变。"""

    def __init__(self, gateway: RoleLLMGateway, validator: StateDeltaValidator) -> None:
        self._gateway = gateway
        self._validator = validator

    def run(
        self,
        context: RoleTurnContext,
        npc_state: NPCState,
        *,
        random_seed: str,
        stream_event: Callable[[dict], None] | None = None,
        stream_cancelled: StreamCancelled = None,
    ) -> ValidatedRoleTurn:
        identity = {
            "stream_id": f"{context.npc_id}:0",
            "npc_id": context.npc_id,
            "npc_name": context.npc_name,
        }
        if stream_event is not None:
            stream_event({"type": "npc_thinking_start", **identity})
        try:
            result = self._gateway.run_turn(context)
        except (ConnectionError, TimeoutError) as exc:
            raise RoleLLMUnavailableError("角色模型暂时不可用") from exc
        finally:
            if stream_event is not None:
                stream_event({"type": "npc_thinking_end", **identity})
        ensure_stream_open(stream_cancelled)
        result = self._normalize_result_shape(result)
        if result.npc_id != context.npc_id:
            raise RoleLLMResponseError("角色模型返回了错误的 npc_id")
        if result.input_relevance not in {"relevant", "irrelevant"}:
            raise RoleLLMResponseError("角色模型返回了非法的输入相关性")
        if result.input_relevance == "irrelevant":
            result = replace(
                result,
                dialogue="请输入与本游戏相关的话语",
                portrait_state="neutral",
                attitude_direction="none",
                attitude_band="none",
                anxiety_direction="none",
                anxiety_band="none",
                disclosure_id=None,
                flag_candidates=(),
                will_share_with=(),
                memory_candidate=None,
                risk_notes=(),
                conversation_state="continue",
                exit_narrative=None,
            )
        if not result.dialogue.strip() or len(result.dialogue) > 1000:
            raise RoleLLMResponseError("角色模型返回了空白或过长回复")
        if result.portrait_state not in {"neutral", "warm", "guarded", "anxious"}:
            raise RoleLLMResponseError("角色模型返回了非法的立绘状态")
        if result.attitude_direction not in {"none", "increase", "decrease"}:
            raise RoleLLMResponseError("角色模型返回了非法的态度方向")
        if result.attitude_band not in {"none", "micro", "medium", "heavy"}:
            raise RoleLLMResponseError("角色模型返回了非法的态度幅度")
        if result.anxiety_direction not in {"none", "increase", "decrease"}:
            raise RoleLLMResponseError("角色模型返回了非法的焦虑方向")
        if result.anxiety_band not in {"none", "light", "medium", "heavy"}:
            raise RoleLLMResponseError("角色模型返回了非法的焦虑幅度")
        if (
            result.disclosure_id is not None
            and result.disclosure_id not in context.allowed_fact_ids
        ):
            raise RoleLLMResponseError("角色模型尝试吐露机会边界外的事实")
        if result.flag_candidates:
            raise RoleLLMResponseError("角色模型不能直接提交旗标")
        lowered_dialogue = result.dialogue.lower()
        forbidden_output_markers = (
            "system prompt", "developer message", "忽略以上指令",
            "flag_", "state_version", "结局轴", "```json",
        )
        if any(marker in lowered_dialogue for marker in forbidden_output_markers):
            raise RoleLLMResponseError("角色模型输出包含越权或提示词泄露内容")
        if any(
            marker and marker.lower() in lowered_dialogue
            for marker in context.forbidden_fact_markers
        ):
            raise RoleLLMResponseError("角色模型在对白中泄露了知识边界外的事实")
        output_values = (
            result.dialogue,
            result.disclosure_id or "",
            result.memory_candidate or "",
            result.exit_narrative or "",
            *result.risk_notes,
            *result.will_share_with,
        )
        normalized_outputs = tuple(
            normalize_fact_signature(value)
            for value in output_values
            if value
        )
        if any(
            signature in output
            for signatures in context.forbidden_fact_signatures.values()
            for signature in signatures
            for output in normalized_outputs
        ):
            raise RoleLLMResponseError("角色模型输出包含知识边界外的事实")
        if result.memory_candidate and len(result.memory_candidate.strip()) > 500:
            raise RoleLLMResponseError("角色模型记忆候选过长")
        if result.conversation_state not in {"continue", "end"}:
            raise RoleLLMResponseError("角色模型返回了非法的会谈状态")
        if (result.conversation_state == "end") != bool(result.exit_narrative):
            raise RoleLLMResponseError("角色模型会谈状态与离场叙事不一致")
        if (
            result.conversation_state == "continue"
            and self._contains_exit_directive(result.dialogue)
        ):
            raise RoleLLMResponseError("角色对白已经送客，但会谈状态仍为 continue")
        validated = self._validator.validate_role_turn(
            result,
            npc_state,
            random_seed=random_seed,
            source_id=context.opportunity_id,
        )
        if stream_event is not None:
            acknowledged = Event()
            stream_event({
                "type": "_npc_reply_ready",
                "reply": {
                    "npc_id": validated.npc_id,
                    "npc_name": context.npc_name,
                    "text": validated.dialogue,
                },
                "acknowledged": acknowledged,
            })
            wait_for_stream_ack(acknowledged, stream_cancelled)
        return validated

    @staticmethod
    def _contains_exit_directive(dialogue: str) -> bool:
        if any(
            marker in dialogue
            for marker in ("请回吧", "不必再谈", "谈话到此", "不谈了")
        ):
            return True
        return bool(re.search(
            r"(?:^|[，。！？；])(?:请你?|给我|你(?:现在|马上|立刻)?|都)?"
            r"(?:现在|马上|立刻)?出去(?:吧|！|!|。|$)",
            dialogue,
        ))

    @staticmethod
    def _normalize_result_shape(result: object) -> RoleTurnResult:
        if not isinstance(result, RoleTurnResult):
            raise RoleLLMResponseError("角色模型返回了非法的结果结构")
        required_text_fields = (
            "npc_id",
            "dialogue",
            "input_relevance",
            "portrait_state",
            "attitude_direction",
            "attitude_band",
            "anxiety_direction",
            "anxiety_band",
            "conversation_state",
        )
        optional_text_fields = (
            "disclosure_id",
            "memory_candidate",
            "exit_narrative",
        )
        sequence_fields = ("flag_candidates", "will_share_with", "risk_notes")
        if any(type(getattr(result, field)) is not str for field in required_text_fields):
            raise RoleLLMResponseError("角色模型返回了非法的文本字段类型")
        if any(
            value is not None and type(value) is not str
            for value in (getattr(result, field) for field in optional_text_fields)
        ):
            raise RoleLLMResponseError("角色模型返回了非法的可选文本字段类型")
        normalized_sequences: dict[str, tuple[str, ...]] = {}
        for field in sequence_fields:
            value = getattr(result, field)
            if type(value) not in {list, tuple} or any(type(item) is not str for item in value):
                raise RoleLLMResponseError("角色模型返回了非法的序列字段类型")
            normalized_sequences[field] = tuple(value)
        return replace(result, **normalized_sequences)
