import pytest

from serious_game_backend.application.contract_requirements import contract_requirement_feedback


@pytest.mark.parametrize("condition,topic", [
    ("血铅复查资源未落实", "血铅"),
    ("就业转介资源未落实", "工作生活"),
    ("医疗随访与就业转介附件未落实", "合同附件"),
])
def test_followup_feedback_explains_only_first_current_concern(condition, topic):
    text = contract_requirement_feedback([condition, "签约人尚未查看可交付实房"])
    assert topic in text
    assert "暂时不能签" not in text
    assert "真住进去" not in text
    assert "resource" not in text and "slot" not in text


def test_followup_mapping_preserves_existing_first_concern():
    assert contract_requirement_feedback(["逐项测算账目尚未公开", "血铅复查资源未落实"]) == (
        "那笔账我还没弄明白，现在签字，心里不踏实。"
    )
