from __future__ import annotations

import re

from serious_game_backend.domain.errors import ContentValidationError


_HIDDEN_METRIC_DELTA = re.compile(
    r"(?:政治资本|政治信用|群众信任|社会稳定|舆论压力|班子不满|"
    r"信任(?:值|分)?|焦虑(?:值|分)?|态度(?:值|分)?)"
    r"\s*(?:[：:]\s*)?(?:[+\-±]\s*\d|"
    r"\d+\s*(?:到|至|[-~—])\s*[+\-]?\d+)"
)
_ADJACENT_PUNCTUATION = re.compile(r"[，。；：！？]{2,}")
_ASCII_COMMA_IN_CHINESE = re.compile(r"(?<=[\u3400-\u9fff]),|,(?=[\u3400-\u9fff])")
_TERMINAL = ("。", "！", "？", "…")
_SOFT_TERMINAL = ("，", "；", "：", ",", ";", ":")


def validate_player_visible_text(text: str) -> None:
    if _HIDDEN_METRIC_DELTA.search(text):
        raise ContentValidationError("玩家可见文本不得暴露隐藏指标的精确数值变化")
    if _ADJACENT_PUNCTUATION.search(text):
        raise ContentValidationError("玩家可见文本包含紧邻的重复标点")
    if _ASCII_COMMA_IN_CHINESE.search(text):
        raise ContentValidationError("中文玩家可见文本不得使用半角逗号")


def player_visible_sentence(text: str) -> str:
    value = str(text).strip()
    validate_player_visible_text(value)
    if not value:
        return value
    if value.endswith(_SOFT_TERMINAL):
        value = value[:-1].rstrip() + "。"
    # A complete utterance keeps its terminal mark inside the closing quotes.
    # Ignore closing quotes only for this check: quoted phrases without their
    # own terminal mark still need an outer full stop (这叫“先核实”。).
    elif not value.rstrip('”’」』').endswith(_TERMINAL):
        value += "。"
    validate_player_visible_text(value)
    return value
