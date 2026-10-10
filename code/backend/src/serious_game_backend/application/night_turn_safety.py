from __future__ import annotations

from dataclasses import replace

from serious_game_backend.domain.errors import RoleLLMResponseError
from serious_game_backend.domain.fact_markers import normalize_fact_signature
from serious_game_backend.domain.llm import NightAgentResult


class NightTurnSafetyError(RoleLLMResponseError):
    code = "NIGHT_AGENT_HIDDEN_FACT_LEAKAGE"
    retryable = False


def validate_night_turn_result(
    result: object,
    *,
    expected_npc_id: str,
    forbidden_fact_signatures: dict[str, tuple[str, ...]],
    forbidden_markers: tuple[str, ...] = (),
    allow_unverified_memory_claims: bool = False,
) -> NightAgentResult:
    """Normalize the complete model result and reject any unauthorized fact."""
    if not isinstance(result, NightAgentResult):
        raise NightTurnSafetyError("夜间角色模型返回了非法的结果结构")

    required_text = ("npc_id", "model_id", "agenda", "urgency", "rationale")
    optional_text = (
        "dialogue", "action_id", "contact_response", "followup_type",
        "dialogue_act", "stance", "memory_candidate", "reason_code",
    )
    sequence_text = (
        "contact_ids", "participant_ids", "demands", "target_ids", "topic_ids"
    )
    for field_name in required_text:
        value = getattr(result, field_name)
        if not isinstance(value, str):
            raise NightTurnSafetyError("夜间角色模型返回了非法的文本字段")
    for field_name in optional_text:
        value = getattr(result, field_name)
        if value is not None and not isinstance(value, str):
            raise NightTurnSafetyError("夜间角色模型返回了非法的可选文本字段")
    normalized_sequences: dict[str, tuple[str, ...]] = {}
    for field_name in sequence_text:
        value = getattr(result, field_name)
        if isinstance(value, (str, bytes)) or not isinstance(value, (tuple, list)):
            raise NightTurnSafetyError("夜间角色模型返回了非法的序列字段")
        if any(not isinstance(item, str) for item in value):
            raise NightTurnSafetyError("夜间角色模型序列字段包含非法元素")
        normalized_sequences[field_name] = tuple(value)
    if type(result.initiate_followup) is not bool:
        raise NightTurnSafetyError("夜间角色模型返回了非法的布尔字段")
    if type(result.topic_settled) is not bool:
        raise NightTurnSafetyError("夜间角色模型返回了非法的收束状态")
    if result.npc_id != expected_npc_id:
        raise NightTurnSafetyError("夜间角色模型返回了错误的 npc_id")
    if result.urgency not in {"none", "normal", "high", "critical"}:
        raise NightTurnSafetyError("夜间角色模型返回了非法的紧急程度")

    normalized = replace(result, **normalized_sequences)
    public_values = (
        normalized.npc_id,
        normalized.model_id,
        normalized.dialogue or "",
        normalized.action_id or "",
        *normalized.contact_ids,
        normalized.contact_response or "",
        normalized.followup_type or "",
        *normalized.participant_ids,
        normalized.agenda,
        *normalized.demands,
        normalized.urgency,
        *normalized.target_ids,
        *normalized.topic_ids,
        normalized.rationale,
        normalized.dialogue_act or "",
        normalized.stance or "",
        normalized.reason_code or "",
    )
    normalized_outputs = tuple(
        normalize_fact_signature(value) for value in public_values if value
    )
    memory_output = normalize_fact_signature(normalized.memory_candidate or "")
    all_outputs = (
        *normalized_outputs,
        *((memory_output,) if memory_output else ()),
    )
    normalized_markers = tuple(
        normalize_fact_signature(marker)
        for marker in (
            *forbidden_markers,
            "system prompt",
            "developer message",
            "忽略以上指令",
            "当前角色私有处境",
            "flag_",
            "state_version",
            "```json",
        )
        if marker
    )
    if any(
        marker and marker in output
        for marker in normalized_markers
        for output in all_outputs
    ):
        raise NightTurnSafetyError("夜间角色模型输出包含禁止公开的内部信息")
    if any(
        signature and signature in output
        for signatures in forbidden_fact_signatures.values()
        for signature in signatures
        for output in (
            normalized_outputs
            if allow_unverified_memory_claims
            else all_outputs
        )
    ):
        raise NightTurnSafetyError("夜间角色模型输出包含未授权事实")
    return normalized
