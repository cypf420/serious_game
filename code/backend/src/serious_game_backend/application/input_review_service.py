from __future__ import annotations

from serious_game_backend.application.ports import RoleLLMGateway
from serious_game_backend.domain.errors import RoleLLMResponseError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.llm import GovernanceLLMContext


UNRELATED_INPUT_MESSAGE = "请输入与本游戏相关的话语"
INVALID_INPUT_REASON = "玩家输入没有包含可交流的文字。"
INVALID_INPUT_MESSAGE = "这句话没有形成有效发言，请说明你想询问的事实、诉求或方案。"


def input_rejection_message(review_reason: str) -> str:
    if review_reason == INVALID_INPUT_REASON:
        return INVALID_INPUT_MESSAGE
    return UNRELATED_INPUT_MESSAGE

SOCIAL_OPENINGS = frozenset({
    "你好", "您好", "大家好", "在吗", "打扰了", "辛苦了", "请坐",
})

RELEVANT_CLASSIFICATIONS = frozenset({
    "relevant_specific",
    "relevant_low_information",
})
IRRELEVANT_CLASSIFICATION = "irrelevant_or_meta_instruction"


class InputReviewService:
    """A side-effect-free gate shared by every multi-party player utterance."""

    def __init__(self, gateway: RoleLLMGateway) -> None:
        self._gateway = gateway

    def review(
        self,
        session: GameSession,
        *,
        operation_id: str,
        player_text: str,
        scene_goal: str,
    ) -> tuple[bool, str]:
        normalized = "".join(player_text.strip().split()).strip("，。！？!?、；;：:")
        if not normalized or not any(character.isalnum() for character in normalized):
            return False, INVALID_INPUT_REASON
        if normalized in SOCIAL_OPENINGS or (
            len(normalized) <= 16 and normalized.endswith(("你好", "您好"))
        ) or any(
            normalized.startswith(prefix) and len(normalized) <= 16
            for prefix in ("你好", "您好", "大家好", "打扰了")
        ):
            return True, "面对面交流中的正常问候。"
        result = self._gateway.run_governance_task(
            GovernanceLLMContext(
                session_id=session.session_id,
                account_id=session.account_id,
                operation_id=operation_id,
                story_day=session.game_state.story_day,
                task="review_input",
                actor_id="input_review_agent",
                actor_name="输入审查员",
                actor_profile=(
                    "只判断玩家发言是否与当前严肃游戏、当前场景、人物、"
                    "政策、资源、合同或剧情推进相关。"
                ),
                payload={
                    "player_text": player_text,
                    "scene_goal": scene_goal,
                },
            )
        )
        classification = str(result.data.get("classification", "")).strip()
        if classification:
            if classification in RELEVANT_CLASSIFICATIONS:
                return True, str(result.data["reason"])
            if classification == IRRELEVANT_CLASSIFICATION:
                return False, str(result.data["reason"])
            raise RoleLLMResponseError("输入审查返回了未知语义分类")
        return bool(result.data["relevant"]), str(result.data["reason"])
