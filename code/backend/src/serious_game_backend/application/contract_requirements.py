"""Express an actual unresolved concern without exposing a solution checklist."""

from serious_game_backend.application.contract_facts import resolve_contract_facts
from serious_game_backend.domain.errors import NotFoundError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.gameplay_governance import HouseholdContract
from serious_game_backend.domain.script_package import ScriptPackage

REQUIREMENT_HELP = {
    "本户对整体签约安排仍有顾虑": "之前那件事还压在心里，我现在还不能安心签字。",
    "本户尚未接受不安排实物房源的方案": "补偿是一回事，离开老屋以后住在哪里，我还放不下。",
    "本户对房源上下楼条件仍有顾虑": "家里人的身体情况你也知道，我担心搬过去以后出入不方便。",
    "迁坟事务资源未落实": "屋子的事可以谈，可先人的事，我心里还没着落。",
    "医疗复检或评估资源未落实": "家里人的身体一直让我牵挂，搬家的事还不能只算房子和钱。",
    "血铅复查资源未落实": "孩子的血铅还得继续复查，只做一次评估，我心里不踏实。",
    "就业转介资源未落实": "搬过去以后家里人靠什么工作生活，这份安排里还没有着落。",
    "医疗随访与就业转介附件未落实": "复查和就业转介不能只口头答应，具体怎么办还得在合同附件里写清楚。",
    "就学衔接资源未落实": "大人搬过去还好说，孩子的学业，我怕这么一搬就耽搁了。",
    "外出户本人授权尚未核验": "这是我们自家的事，签字这一步还得由本人来。",
    "逐项测算账目尚未公开": "那笔账我还没弄明白，现在签字，心里不踏实。",
    "历史旧案尚未形成书面处理结果": "以前那件事还没有个结果，我没法当它没发生过。",
    "既往额外付款尚未核验": "以前那笔补偿和这次怎么衔接，我心里还有疑问。",
    "签约人尚未查看可交付实房": "纸上的房子我看明白了，可真住进去是什么样，我还没底。",
    "本户核心矛盾尚未解决": "我在意的那件事还悬着，现在还不能答应。",
}


REQUIREMENT_STEPS = {
    "本户尚未接受不安排实物房源的方案": "在当前合同的安置住房中选择满足本户人口面积档位的房源，保存后再提交。",
    "本户对房源上下楼条件仍有顾虑": "在当前合同选择标有无障碍条件且面积达标的房源；更大面积不能代替无障碍条件。",
    "迁坟事务资源未落实": "在当前合同的配套服务中配置迁坟服务，保存后再提交。",
    "医疗复检或评估资源未落实": "在当前合同的配套服务中配置医疗复检、儿童评估或紧急转诊名额，保存后再提交。",
    "血铅复查资源未落实": "在当前合同配套服务中配置血铅复查名额，保存后再提交。",
    "就业转介资源未落实": "在当前合同配套服务中配置稳定岗位或技能培训名额，保存后再提交。",
    "医疗随访与就业转介附件未落实": "在当前合同补齐复查机构、周期、费用承担方式和就业接收单位；配置名额不代表服务已完成。",
    "就学衔接资源未落实": "在当前合同配套服务中配置就学衔接名额，保存后再提交。",
    "外出户本人授权尚未核验": "正式提交会由系统联系本户签约人核验本人意愿；代表会谈不能代替本人签署。",
    "逐项测算账目尚未公开": "返回周满仓相关剧情办理逐项账目公开，完成后再核对本户合同。",
    "历史旧案尚未形成书面处理结果": "返回谭老六旧案剧情形成书面处理结果；普通听证记录或法审名额不代替旧案了结。",
    "既往额外付款尚未核验": "返回苗喜旺相关剧情核清既往补偿口径，完成后再核对本户合同。",
    "本户对整体签约安排仍有顾虑": "返回该代表当前相关剧情处理整体签约安排；修改合同条款不能替代尚未完成的剧情办理。",
    "本户核心矛盾尚未解决": "返回该户当前相关剧情处理已提出的核心问题，完成后再提交当前方案。",
}


def contract_next_steps(missing, representative_npc_id):
    """Explain the same authoritative conditions used by contract review."""
    result = []
    for condition in missing:
        if condition == "签约人尚未查看可交付实房":
            result.append({"label": "结束签约协商后，进入现场走访，邀请本人现在一起查看合同所选实房；现场走访单独计费。",
                           "action_id": "household_visit", "variant_id": "field_visit",
                           "target_ids": [representative_npc_id]})
        else:
            result.append({"label": REQUIREMENT_STEPS.get(condition, condition)})
    return result


def contract_requirement_feedback(missing: list[str]) -> str:
    if not missing:
        return "当前方案已满足本户签约条件，合同已签署。补偿、房源及服务以这份合同为准。"
    # Reveal one current concern, not all requirements or the required clicks.
    return REQUIREMENT_HELP.get(missing[0], "这份安排还有让我顾虑的地方，我暂时不能签。")


def missing_contract_conditions(
    session: GameSession, package: ScriptPackage, contract: HouseholdContract,
) -> list[str]:
    """Read the same household conditions for review and saved-plan dialogue."""
    assert contract.term_sheet is not None
    household = next((h for h in package.households if h.household_id == contract.household_id), None)
    if household is None:
        raise NotFoundError("家庭底账不存在")
    terms = contract.term_sheet
    facts = resolve_contract_facts(session, package, contract)
    allocations = set(terms["service_allocations"])
    missing = []
    gate = (package.governance_config or {}).get("contract_batch_gate_flags", {}).get(household.representative_npc)
    if gate and gate not in session.flags:
        missing.append("本户对整体签约安排仍有顾虑")
    housing_id = terms.get("housing_resource_id")
    if not housing_id and (household.resettlement_preference.startswith("resettlement_house")
                           or "low_floor" in household.resettlement_preference):
        missing.append("本户尚未接受不安排实物房源的方案")
    pool = next((p for p in (package.governance_config or {}).get("resource_pools", [])
                 if p["resource_id"] == housing_id), None)
    if (pool and "low_floor" in household.resettlement_preference
            and not pool.get("attributes", {}).get("accessible")):
        missing.append("本户对房源上下楼条件仍有顾虑")
    if (
        household.grave_or_shrine_profile
        not in {"none", "clan_follower", "clan_accounting"}
        and "grave_relocation_service" not in allocations
    ):
        missing.append("迁坟事务资源未落实")
    if household.medical_tags and not allocations.intersection({
        "lead_recheck_slot",
        "child_assessment_slot",
        "emergency_referral_slot",
    }):
        missing.append("医疗复检或评估资源未落实")
    if household.household_id == "HE-02":
        if "lead_recheck_slot" not in allocations:
            missing.append("血铅复查资源未落实")
        if not allocations.intersection({"stable_job_slot", "training_slot"}):
            missing.append("就业转介资源未落实")
        if not all((terms.get("followup_plan") or {}).get(key) for key in (
            "medical_provider", "recheck_interval_days", "employment_receiver", "medical_fee_arrangement"
        )):
            missing.append("医疗随访与就业转介附件未落实")
    if (
        "school_continuity" in household.employment_startup_tags
        and "school_transition_seat" not in allocations
    ):
        missing.append("就学衔接资源未落实")
    if (
        household.ownership_status == "migrant_authorization_needed"
        and not facts["authorization_confirmed"]
    ):
        missing.append("外出户本人授权尚未核验")
    if (
        household.ownership_status == "ledger_sensitive"
        and not facts["ledger_disclosed"]
    ):
        missing.append("逐项测算账目尚未公开")
    if (
        household.ownership_status in {
            "old_road_case_pending", "old_materials_sensitive",
        }
        and not facts["old_case_resolved"]
    ):
        missing.append("历史旧案尚未形成书面处理结果")
    if (
        household.ownership_status == "prior_extra_payment_risk"
        and not facts["prior_payment_verified"]
    ):
        missing.append("既往额外付款尚未核验")
    if (
        household.resettlement_preference
        == "resettlement_house_must_see_real_unit"
        and not facts["real_unit_viewed"]
    ):
        missing.append("签约人尚未查看可交付实房")
    if (
        household.signing_lock_flag
        and household.signing_lock_flag not in session.flags
    ):
        missing.append(
            "本户核心矛盾尚未解决"
        )
    return missing
