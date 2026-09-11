import json
from pathlib import Path

import pytest

from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import NightAgentContext
from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
from serious_game_backend.infrastructure.repositories.memory import InMemoryLLMCallAuditRepository

SCENES = json.loads((Path(__file__).parents[1] / "content/packages/pkg_gameplay_v3/social_rules.json").read_text(encoding="utf-8"))["night_agent_scenes"]


@pytest.mark.parametrize("scene", SCENES, ids=[s["scene_id"] for s in SCENES])
@pytest.mark.parametrize("phase", ["dialogue", "player_group_dialogue", "resolved_group_followup"])
def test_all_night_speech_uses_persona_and_topic_without_editorial_guidance(scene, phase):
    prompts = []
    def transport(_url, _key, body, _timeout):
        prompt = body["messages"][0]["content"]
        prompts.append(prompt)
        result = {"text": "这件事我记得。"} if '只返回 JSON：{"text"' in prompt else {"choice_id": "settle"}
        return {"choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]}
    gateway = OpenAICompatibleRoleLLMGateway(
        Settings(environment="test", role_llm_provider="openai_compatible"),
        "DEMO-key", InMemoryLLMCallAuditRepository(), transport=transport,
    )
    gateway.run_night_turn(NightAgentContext(
        session_id="DEMO-session", account_id="DEMO-account", operation_id="DEMO-operation",
        story_day=scene["story_day"], scene_id=scene["scene_id"], phase=phase,
        npc_id="npc_zhao_jianguo", npc_name="赵建国", role_setting="常务副县长，在云溪任职多年。",
        big_five={}, counterpart_ids=("npc_sun_qiang",), counterpart_names={"npc_sun_qiang": "孙强"},
        scene_goal=scene["scene_goal"], transcript=({"text": "上轮真实对话"},), player_text="本轮真实发言",
        private_context="废弃指导：连续追问责任期限", public_expression_context="废弃指导：先问责任",
        reference_context="实际引用材料正文", allowed_dialogue_acts=("settle",),
        allowed_followup_plans=tuple(scene.get("followup_plans", [])) + ({
            "participant_guidance": {"npc_zhao_jianguo": {"questioning_style": "废弃指导"}},
            "persuasion_context": "废弃指导",
        },),
    ))
    speech = prompts[-1]
    for prompt in prompts:
        assert "废弃指导" not in prompt
        assert "questioning_style" not in prompt
        assert "convincing_signals" not in prompt
    for text in ("赵建国", "常务副县长", "上轮真实对话", "本轮真实发言", "主题"):
        assert text in speech
    for text in ("风格约束", "已确认选择", "继续追问", "暂时相信", "判断彼此是否仍可信", "只能讨论"):
        assert text not in speech
    if phase != "dialogue":
        assert "实际引用材料正文" in speech
