import json
from pathlib import Path
from types import SimpleNamespace

from serious_game_backend.application.character_facts import (
    CHARACTER_FACTS, factual_persona, household_knowledge,
)
from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import RoleTurnContext
from serious_game_backend.infrastructure.llm.openai_compatible import OpenAICompatibleRoleLLMGateway
from tests.test_doubles import build_test_container


ROOT = Path(__file__).resolve().parents[1] / "content/packages"


def test_all_shipped_profiles_exclude_walkthroughs_in_model_context():
    profiles = json.loads((ROOT / "pkg_gameplay_v3/npc_profiles.json").read_text(encoding="utf-8"))["npcs"]
    assert {p["name"] for p in profiles} == set(CHARACTER_FACTS)
    for profile in profiles:
        clean = factual_persona(profile["name"], profile["role_setting"])
        assert clean == CHARACTER_FACTS[profile["name"]]
        assert not any(s in clean for s in ("玩家", "旗标", "唯一", "必须", "路径", "结局"))
        context = RoleTurnContext(
            session_id="test", npc_id=profile["npc_id"], npc_name=profile["name"],
            player_text="谈一下本户方案", story_day=2, opportunity_id="test",
            role_setting=profile["role_setting"], big_five=profile["big_five"],
            prompt_template="旧回应指导标记",
        )
        prompt = OpenAICompatibleRoleLLMGateway._character_context(context)
        assert clean in prompt
        for removed in ("旧回应指导标记", "information_play_rules", "contract_discussion_rules", "current_gameplay_authority"):
            assert removed not in prompt
        assert profile["role_setting"] not in prompt


def test_representatives_know_each_own_household_without_other_groups_or_flags():
    runtime = build_test_container(Settings(
        environment="test", repository="memory", role_llm_provider="none",
        default_package_id="pkg_gameplay_v3", content_root=ROOT,
    ))
    package = runtime.packages.get("pkg_gameplay_v3")
    total = 0
    for npc in package.npc_profiles:
        facts = household_knowledge(package, npc.npc_id)
        expected = [h for h in package.households if h.representative_npc == npc.npc_id]
        assert [f["household_id"] for f in facts] == [h.household_id for h in expected]
        total += len(facts)
        for fact, household in zip(facts, expected):
            assert fact["legal_residential_area_m2"] == household.legal_residential_area_m2
            assert fact["resettlement_population"] == household.resettlement_population
            assert "signing_lock_flag" not in fact
            signatory = package.limited_signatory_for(household.household_id)
            if signatory:
                assert fact["needs"] == signatory.core_concern
    assert total == 36
    wu = household_knowledge(package, "npc_wu_xiuying")
    assert len(wu) == 6
    assert all(f["household_id"].startswith("WU-") for f in wu)
    assert household_knowledge(package, "npc_unknown") == []
    for signatory in package.limited_household_signatories:
        _, _, persona = runtime.gameplay_governance._contract_actor(package, SimpleNamespace(
            signatory_npc_id=None, household_id=signatory.household_id,
        ))
        assert signatory.core_concern in persona
        assert "拒绝触发" not in persona
        assert "接受条件" not in persona
