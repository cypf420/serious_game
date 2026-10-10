"""Source-backed guidance; facts, original custody, and reads stay distinct."""
from dataclasses import replace

from serious_game_backend.application.archive_investigation_service import (
    ORIGINAL_ARCHIVE_ID, eligible_definitions,
)


def source_opportunity(opportunity, session):
    # Author source 4783-4789 places Luo's concrete questioning before D32's choice.
    if session.package_id == "pkg_gameplay_v3" and opportunity.opportunity_id == "opp_31_luo_jian_contact":
        if session.game_state.story_day < 42:
            return replace(opportunity, day_min=32,
                opening_narrative="你找到经手柳林村补偿明细的罗健，继续核对台账。两种补偿标准和三个手印有待逐项查清；他只回答自己经手、亲眼见过的部分，等你提出具体问题。",
                conversation_goal="核对柳林村补偿明细中的两个标准、异常手印和经手材料的保管来源。",
                allowed_fact_ids=("fact_false_signing",), disclosure_protocols=(),
                complete_on_player_exit=False, complete_on_npc_exit=False)
        return opportunity
    return opportunity


def original_requirement(option, session):
    return ("见过原件" in option.required_flags and "见过原件" not in session.flags) or (
        {"见过原件", "罗健留底"}.intersection(option.required_any_flags)
        and not option.required_any_flags.intersection(session.flags))


def option_next_steps(option, session, package):
    steps = []
    if original_requirement(option, session):
        steps.append({"label": "调阅柳林村补偿明细原件", "action_id": "inspect_archives",
                      "variant_id": "consult_county_archives", "archive_id": ORIGINAL_ARCHIVE_ID,
                      **({"unavailable_reason": "第32日台账核查开始后开放。"} if session.game_state.story_day < 32 else {})})
    missing = option.required_fact_ids - session.known_fact_ids
    if option.required_any_fact_ids and not option.required_any_fact_ids.intersection(session.known_fact_ids):
        missing = missing | option.required_any_fact_ids
    for definition in eligible_definitions(session, package):
        if missing.intersection(definition.result_fact_ids) and definition.archive_id != ORIGINAL_ARCHIVE_ID:
            steps.append({"label": f"查阅《{definition.title}》", "action_id": "inspect_archives",
                          "variant_id": "consult_county_archives", "archive_id": definition.archive_id})
    return tuple(steps)


def custody_reason(option, session):
    if original_requirement(option, session):
        return ("已查阅比对材料或掌握口头事实，仍不等于核对过原件。请进入行动—查阅档案，"
                "调阅《柳林村补偿明细原件》；核对原件后，也可向罗健具体追问其经手材料与留底。")
    if option.required_state_values.get("lead_roster_disposition") == "己方封存":
        disposition = session.state_values.get("lead_roster_disposition")
        if disposition == "己方封存":
            return None
        reason = {
            "呈交上级": "原件此前已通过机要渠道移交上级，当前不能重复交付；可选择提供脱敏检测汇总或说明去向。",
            "交给记者": "原件此前已经交给记者，不能再交同一份原件；可提供脱敏汇总或说明已有交接。",
            "被销毁": "原件此前已被销毁，当前没有恢复原件的办理入口；仍可提供可核验的脱敏汇总。",
            "未获取": "原件此前未留取或退回疾控，当前未建立重新领取原件的办理入口；可说明去向或提供脱敏汇总。",
        }.get(disposition)
        return reason or "原件保管记录尚未确认。查阅普查汇总不能取得名册原件；请先完成前序名册保管决策，当前也可提供脱敏汇总。"
    return None
