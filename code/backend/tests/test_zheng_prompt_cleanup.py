from dataclasses import replace

from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import RoleTurnContext, SelectionResult, ExpressionResult
from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
from serious_game_backend.infrastructure.repositories.memory import InMemoryLLMCallAuditRepository


def test_zheng_needs_remain_motives_not_facts_and_other_roles_unchanged(monkeypatch):
    selections, expressions = [], []
    def select(self, task):
        selections.append(task)
        return SelectionResult(choice_id="communication_guarded")
    def express(self, task):
        expressions.append(task)
        return ExpressionResult(text="测试响应，不代表真实模型验收。")
    monkeypatch.setattr(OpenAICompatibleRoleLLMGateway, "select", select)
    monkeypatch.setattr(OpenAICompatibleRoleLLMGateway, "express", express)
    gateway = OpenAICompatibleRoleLLMGateway(
        Settings(environment="test", role_llm_provider="openai_compatible"),
        "DEMO-key", InMemoryLLMCallAuditRepository(),
    )
    need = "需要法审工时把口头指令转成责任、期限和材料位置。"
    context = RoleTurnContext(
        session_id="DEMO-test", npc_id="npc_zheng_xiangdong", npc_name="郑向东",
        player_text="还剩多少户？", story_day=1, opportunity_id="DEMO-talk",
        unresolved_demands=(need,), unresolved_commitments=("尚未完成的承诺",),
        memory_items=("历史记录：该诉求尚未解决",),
        conversation_goal="核对签约进度", conversation_opening="办公室开场",
        visible_world_context={"signed_households": 0, "total_households": 36},
        conversation_history=({"text": "之前的回答可能错误"},),
    )
    gateway.run_turn(context)
    task = expressions[-1]
    assert need not in task.allowed_facts
    assert context.conversation_goal not in task.allowed_facts
    assert "尚未完成的承诺" not in task.allowed_facts
    assert context.memory_items[0] not in task.allowed_facts
    assert context.memory_items[0] in task.context
    for prompt in (task.context, selections[-1].context):
        assert prompt.count(need) == 1
        assert context.player_text in prompt
        assert "之前的回答可能错误" in prompt
        assert '"signed_households": 0' in prompt
        assert '"total_households": 36' in prompt
        assert "不是已存在的文件" in prompt
    assert any("确定的减法" in s for s in task.style_constraints)
    gateway.run_turn(replace(context, npc_id="npc_wu_xiuying", npc_name="吴秀英"))
    other = expressions[-1]
    assert need in other.allowed_facts
    assert context.conversation_goal in other.allowed_facts
    assert "不要推断未提供的职责、事实、数字或承诺" in other.style_constraints
