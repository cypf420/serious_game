"""Actual conversation input follows old-case records without claiming unpaid money arrived."""
from unittest.mock import patch

import pytest

from serious_game_backend.domain.llm import RoleTurnResult
from tests.test_contract_dialogue_authority import prepare
from tests.test_final_check_contract_attempts import game


@pytest.mark.parametrize('flag,settled,response', [
    (None, False, False),
    ('旧案了结', True, False),
    ('谭老六核心矛盾已缓解', False, True),
])
def test_tan_receives_authoritative_old_case_status_on_next_turn(game, flag, settled, response):
    package = prepare(game, 'npc_tan_laoliu', 'TAN-01')
    session = game.session()
    session.flags.difference_update({'旧案了结', '谭老六核心矛盾已缓解'})
    if flag:
        session.flags.add(flag)
    # A real pre-copy-update save must remain usable, without rewriting its identity.
    session.package_content_hash = 'sha256:c4795211286ca05dafd97e91b0f4ff513f2b78e536dfc5d9f0a0454063d6932a'
    game.save(session)
    seen = []
    def capture(context):
        seen.append(context)
        return RoleTurnResult(npc_id=context.npc_id, dialogue='请核对旧案的办理记录。')
    service = game.runtime.gameplay_governance
    with patch.object(service._npc_turns._gateway, 'run_turn', side_effect=capture):
        result = game.post(f'/governance/actions/{game.action_id}/turn', {
            'player_text': '我说已经办完也付清了，你核对一下记录。'})
    assert seen
    context = seen[0]
    facts = context.visible_world_context['hearing_facts']
    assert facts['old_case_resolved'] == bool(flag)
    assert facts['old_case_settled'] == settled
    assert facts['old_case_response_recorded'] == response
    demand = next(d for d in package.npc_demands if d.demand_id == 'demand_tan_laoliu')
    assert '法审' not in demand.description
    assert '法审' not in facts['legal_review_interpretation']
    assert '必须解释当前真实进度' in facts['answer_guidance']
    assert (demand.description in context.unresolved_demands) == (flag is None)
    if response:
        assert '不证明尾款到账' in facts['old_case_progress']
    contract = next(c for c in context.visible_world_context['own_contracts'] if c['household_id'] == 'TAN-01')
    assert ('历史旧案尚未形成书面处理结果' in contract['remaining_conditions']) == (flag is None)


def test_copy_compatibility_does_not_accept_unknown_content(game):
    from serious_game_backend.application.package_lock import locked_package_access
    session = game.session()
    session.package_content_hash = 'sha256:unknown'
    _, access = locked_package_access(game.runtime.packages, session)
    assert access['content_available'] is False
