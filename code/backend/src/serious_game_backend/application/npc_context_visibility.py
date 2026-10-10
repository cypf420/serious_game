"""Read-only stage projection for Luo's source-backed early compensation route.

The immutable package still contains his complete later evidence history. That
history is not a licence to announce future documents during the D32 encounter.
Already authorized facts/references remain supplied by the existing fact boundary.
"""
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import NPCProfileStub, ScriptPackage


EARLY_LUO_PERSONA = (
    "三十一岁，县医院防疫系统技术员，也做过柳林村补偿资料的录入核对。"
    "发现过同村同年两种补偿标准和常年外出人员名下的可疑手印，曾询问而未获答复。"
    "不是领导，没有可以调动的资源。说话精确、简短，只答问到的经手材料和亲眼核对的内容，"
    "不猜测他人的动机，也不主动扩展到未经本次材料核实的事情。"
)
KNOWN_MEDICAL_FACTS = frozenset({'fact_lead_census', 'fact_lead_287'})


def stage_role_setting(session: GameSession, profile: NPCProfileStub) -> str:
    if (session.package_id == 'pkg_gameplay_v3' and profile.npc_id == 'npc_luo_jian'
            and session.game_state.story_day < 42):
        return EARLY_LUO_PERSONA
    return profile.role_setting


def stage_unresolved_demands(session: GameSession, package: ScriptPackage, npc_id: str) -> tuple[str, ...]:
    if (session.package_id == 'pkg_gameplay_v3' and npc_id == 'npc_luo_jian'
            and session.game_state.story_day < 42
            and not KNOWN_MEDICAL_FACTS.intersection(session.known_fact_ids)):
        return ()
    return tuple(demand.description for demand in package.npc_demands
                 if demand.npc_id == npc_id
                 and not (demand.demand_id == 'demand_tan_laoliu'
                          and session.flags.intersection({'旧案了结', '谭老六核心矛盾已缓解'}))
                 and session.npc_demand_states.get(demand.demand_id, {}).get('status') != 'satisfied')
