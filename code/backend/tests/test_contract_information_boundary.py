"""Private negotiation context stays complete without making the player omniscient."""
from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch
import json

from tests import test_contract_accounting as fixtures
from serious_game_backend.domain.gameplay_governance import GovernanceActionRecord


def test_review_keeps_full_household_history_but_not_other_private_visits():
    fixture = fixtures.ContractAccountingTests(); fixture.setUp(); fixture.draft(missing_grave=True)
    s = fixture.session()
    c = s.household_contracts[fixture.cid]
    c.review_history = [{"version": 1, "decision": "explain", "reason": f"此前谈判{i}"} for i in range(12)]
    action = s.governance_actions[fixture.action_id]
    action.transcript = [{"speaker_type": "player", "text": f"第{i}轮已提出的方案"} for i in range(30)]
    s.governance_actions['other-private-visit'] = GovernanceActionRecord(
        'other-private-visit', 'household_visit', 10, ('npc_tan_laoliu',), (),
        transcript=[{"speaker_type": "player", "text": "不属于周家的私下谈话"}])
    s.completed_group_conversations.append({'participant_ids':['npc_zhou_dashan','npc_tan_laoliu'],
        'participant_guidance': {'npc_tan_laoliu':'OTHER_SECRET'},
        'transcript':[{'speaker_type':'npc','text':'大家听到的公开发言'},
                      {'speaker_type':'npc','text':'OTHER_SECRET','visible_to':['npc_tan_laoliu']}]})
    fixture.save(s)
    seen = []
    def review(context):
        seen.append(context)
        return SimpleNamespace(model_id="test-ai", data={"decision": "explain", "reason": "我想再聊聊。", "counteroffer": {}})
    with patch.object(fixture.runtime.gameplay_governance._gateway, 'run_governance_task', side_effect=review):
        result = fixture.review()
    ctx = seen[0]
    assert len(ctx.actor_context['prior_contract_reviews']) == 12
    assert len(ctx.actor_context['household_negotiation_records'][0]['transcript']) == 30
    assert ctx.actor_context['household']['household_id'] == 'ZDS-01'
    assert '不属于周家的私下谈话' not in json.dumps(asdict(ctx), ensure_ascii=False)
    assert 'OTHER_SECRET' not in json.dumps(asdict(ctx), ensure_ascii=False)
    assert '大家听到的公开发言' in json.dumps(asdict(ctx), ensure_ascii=False)
    assert 'authorization_confirmed' not in ctx.payload['term_sheet']
    assert 'authorization_confirmed' in ctx.actor_context['verified_household_facts']
    assert 'remaining_concern' in ctx.payload  # current authoritative concern
    assert 'missing_hard_conditions' not in json.dumps(result, ensure_ascii=False)
    assert len(fixture.session().household_contracts[fixture.cid].review_history) == 13


def test_nonrepresentative_signatory_has_own_household_not_generic_npc_context():
    fixture = fixtures.ContractAccountingTests(); fixture.setUp(); fixture.draft()
    s = fixture.session(); c = s.household_contracts[fixture.cid]
    assert c.signatory_npc_id is None
    svc = fixture.runtime.gameplay_governance
    package = fixture.runtime.packages.get(s.package_id)
    actor, name, profile = svc._contract_actor(package, c)
    ctx = svc._governance_context(s, package, session_id=s.session_id, account_id=s.account_id,
        operation_id='context-test', story_day=10, task='review_contract', actor_id=actor,
        actor_name=name, actor_profile=profile, payload={'contract_id':c.contract_id})
    assert ctx.actor_context['household']['household_id'] == 'ZDS-03'
    assert ctx.actor_context['signatory_identity']['name'] == name
    assert ctx.actor_profile and ctx.actor_context['household_negotiation_records']
    assert ctx.actor_context['private_needs'] == []  # no inherited representative's secret desires


def test_rejecting_household_does_not_create_fresh_contract_to_erase_negotiation():
    fixture = fixtures.ContractAccountingTests(); fixture.setUp(); fixture.draft()
    s = fixture.session(); c = s.household_contracts[fixture.cid]
    c.status = 'rejected'; c.review_history.append({'reason': '不同意当前方案', 'decision': 'reject'})
    fixture.save(s); before = deepcopy(fixture.session())
    fixture.post(f'/governance/actions/{fixture.action_id}/prepare-contracts', status=409)
    assert fixture.session() == before
