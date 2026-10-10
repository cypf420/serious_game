from __future__ import annotations

from math import ceil

from serious_game_backend.domain.game_session import GameSession


def progress_broadcast(session: GameSession) -> dict | None:
    """Return the deterministic ten-day督办播报 for the current state."""

    state = session.game_state
    day = state.story_day
    if day < 10 or day % 10 != 0:
        return None

    expected_signed = min(
        state.total_households,
        ceil(state.total_households * day / 90),
    )
    lag = max(0, expected_signed - state.signed_households)
    pressure = 0
    if lag:
        pressure += 1
    if lag >= max(4, ceil(expected_signed * 0.4)):
        pressure += 2
    if state.public_trust <= 40:
        pressure += 1
    if state.social_stability <= 40:
        pressure += 2
    if state.media_pressure >= 61:
        pressure += 1
    if state.budget_remaining <= state.budget_base_authorized * 0.25:
        pressure += 1

    on_schedule = state.signed_households >= expected_signed
    if on_schedule and pressure == 0:
        tone = "encouraging"
        headline = "这十天没有被日历追上"
        message = (
            f"第{day}日点名：已签约{state.signed_households}户，阶段参考"
            f"{expected_signed}户。不错，至少这一次，进度表不是专门拿来"
            "解释进度的。别急着庆功，九十天只认落笔，不认掌声。"
        )
    elif pressure >= 4:
        tone = "stern"
        headline = "日历已经替你推进了，群众还没有"
        message = (
            f"第{day}日督办：已签约{state.signed_households}户，阶段参考"
            f"{expected_signed}户，还差{lag}户。会议纪要写得再厚，也不能"
            "替任何一家搬完行李。请把解释、资源和责任人真正送到户。"
        )
    else:
        tone = "wry"
        headline = "“稳步推进”里的“稳”，不能只指不动"
        message = (
            f"第{day}日提醒：已签约{state.signed_households}户，阶段参考"
            f"{expected_signed}户，还差{lag}户。材料上当然可以写“正在"
            "推进”，只是群众家的行李不会被这四个字自己搬走。"
        )

    signals: list[str] = []
    if lag:
        signals.append(
            f"签约进度落后阶段参考{lag}户：需要把核权、协商和落笔真正推进到户。"
        )
    if state.public_trust <= 40:
        signals.append("群众信任承压：催得越急，越要把账和依据讲清楚。")
    if state.social_stability <= 40:
        signals.append("社会稳定偏低：先拆风险，不要把每一次沉默都当成同意。")
    if state.media_pressure >= 61:
        signals.append("舆论压力较高：口径之外，还需要可核验的事实和进展。")
    if state.budget_remaining <= state.budget_base_authorized * 0.25:
        signals.append("财政余量偏紧：别拿明天的资源安抚今天的情绪。")
    if not signals:
        signals.append("签约进度达到阶段参考；程序、兑现和后续风险仍要逐项复核。")

    return {
        "broadcast_id": f"progress_d{day}",
        "story_day": day,
        "tone": tone,
        "title": "云溪县十日督办播报",
        "headline": headline,
        "message": message,
        "signals": signals,
        "progress": {
            "signed": state.signed_households,
            "expected": expected_signed,
            "total": state.total_households,
            "days_left": state.days_left,
        },
        "audio_cue": "three_note_bulletin",
    }
