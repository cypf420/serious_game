from unittest.mock import patch
import pytest
from tests.test_contract_workflow_v2 import game
from serious_game_backend.domain.errors import RoleLLMUnavailableError
from serious_game_backend.domain.llm import GovernanceLLMResult


def test_ai_failure_does_not_sign_or_spend(game):
    game.draft()
    before = game.session()
    with patch.object(game.runtime.gameplay_governance._gateway, "run_governance_task", side_effect=RoleLLMUnavailableError("接口连接失败")):
        response = game.client.post(game.base + f"/governance/contracts/{game.cid}/review", headers=game.headers,
            json={"state_version": before.state_version})
    assert response.status_code >= 400
    assert game.session() == before


def test_real_response_text_is_stored_and_decision_is_engine_owned(game):
    game.draft(missing_grave=True)
    gateway = game.runtime.gameplay_governance._gateway
    with patch.object(gateway, "run_governance_task", return_value=GovernanceLLMResult(
            task="review_contract", data={"decision": "accept", "reason": "钱我听明白了，家里那件事还得再商量。"}, model_id="configured-model")) as call:
        result = game.review()
        again = game.review()
    assert call.call_count == 1
    context = call.call_args.args[0]
    assert context.payload["confirmed_decision"] == "explain"
    assert context.payload["allowed_decisions"] == ["explain"]
    assert context.actor_context["prior_contract_versions"]
    assert result["contract"]["status"] != "signed"
    assert result["contract"]["review_reason"] == "钱我听明白了，家里那件事还得再商量。"
    assert again["contract"]["review_history"][-1]["model_id"] == "configured-model"


def test_compatible_gateway_calls_expression_transport_once():
    import json
    from tests.test_choice_expression_protocol import ChoiceExpressionProtocolTests
    from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
    from serious_game_backend.domain.llm import GovernanceLLMContext
    fixture = ChoiceExpressionProtocolTests()
    fixture.setUp()
    requests = []
    def transport(url, key, body, timeout):
        requests.append(body)
        return {"choices": [{"message": {"content": json.dumps({"text": "住处有着落，我同意这份方案。"}, ensure_ascii=False)}}], "usage": {}}
    gateway = OpenAICompatibleRoleLLMGateway(fixture.settings, "test-key", fixture.audits, transport=transport)
    result = gateway.run_governance_task(GovernanceLLMContext(session_id="test", account_id="test", operation_id="test-response",
        story_day=2, task="review_contract", actor_id="npc_wu", actor_name="吴先生", actor_profile="关心住处。",
        payload={"allowed_decisions": ["accept"], "confirmed_decision": "accept", "term_sheet": {}, "remaining_concern": []}))
    assert len(requests) == 1
    assert result.data["reason"] == "住处有着落，我同意这份方案。"
    assert result.data["decision"] == "accept"
    assert "不要列出全部要求" in str(requests)
