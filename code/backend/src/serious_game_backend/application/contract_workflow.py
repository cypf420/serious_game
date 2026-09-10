"""Deterministic contract presentation and scoped negotiation evidence.

Internal resource keys remain authoritative; neither player prose nor an LLM
is allowed to change the saved scheme through contract rendering.
"""
from __future__ import annotations

from dataclasses import asdict
import re

TEMPLATE_AUTHOR = "contract_template_v2"


def scheme_values(terms: dict) -> dict:
    """Payment is due at signature, so its cached day is not a scheme change."""
    return {k: v for k, v in terms.items()
            if k not in {"payment_day", "payment_timing", "policy_minimum_cash"}}


def selected_housing(package, terms: dict) -> dict:
    pool = next((p for p in (package.governance_config or {}).get("resource_pools", [])
                 if p["resource_id"] == terms.get("housing_resource_id")), None)
    if pool is None:
        return {}
    return {"name": resource_name(pool), "attributes": dict(pool.get("attributes", {})),
            "available_day": pool["available_day"]}


def resource_name(pool: dict) -> str:
    # Resource IDs never become fallback labels in player-facing text.
    return re.sub(r"^D(\d+)", r"第\1日", str(pool.get("name") or "所选配套服务"))


def render_contract(session, package, contract, terms: dict) -> str:
    policy = session.administrative_documents[terms["policy_document_id"]]
    pools = {p["resource_id"]: p for p in (package.governance_config or {}).get("resource_pools", [])}
    lines = ["柳林村搬迁补偿安置合同", f"签约人：{contract.signatory_name}",
             f"家庭登记号：{contract.household_id}", f"依据补偿方案：{policy.title}", "",
             f"一、现金补偿：{terms['cash_amount']}万元，签署当日付款。",
             f"二、搬离日期：第{terms['move_out_day']}日。"]
    automatic = terms.get("automatic_arrangement")
    if automatic:
        lines.insert(6, f"其中：基础补偿{automatic['base_cash_amount']}万元，自动计入过渡补偿{automatic['transition_cash_amount']}万元。")
    housing = selected_housing(package, terms)
    if housing:
        lines.append(f"三、安置住房：{housing['name']}，共1套；交房日期：第{terms['housing_delivery_day']}日。")
        if housing["attributes"].get("accessible") is True:
            lines.append("所选住房具备无障碍条件；本约定不表示已经完成实地看房或交付。")
    else:
        lines.append("三、住房安排：本方案不采用实物安置，不分配安置住房。")
    lines.append(f"四、过渡安排：过渡期{terms['transition_months']}个月。")
    services = [f"{resource_name(pools[key])}：{amount}{pools[key].get('unit') or '份'}"
                for key, amount in sorted(terms["service_allocations"].items()) if amount > 0]
    lines.append("五、配套服务：" + ("；".join(services) if services else "未安排配套服务") + "。")
    if terms["public_window_reward"]:
        lines.insert(6, "上述现金补偿已包含政策规定的按期签约奖励，不另行支付。")
    approvals = [session.administrative_documents[key].title for key in terms["approval_document_ids"]]
    if approvals:
        lines.append("批准依据：" + "、".join(approvals) + "。")
    lines.extend(["", "本户签约人同意后合同生效，支付上述款项并分配约定住房和服务名额。",
                  "交房、搬离及服务履行按本合同约定安排；资源分配不代表相关服务已经完成。",
                  "本合同仅约定上述方案，变更补偿与安置安排须重新确认方案。"])
    return "\n".join(lines)


def negotiation_records(session, package, contract) -> list[dict]:
    household = next(h for h in package.households if h.household_id == contract.household_id)
    participants = {household.representative_npc, contract.signatory_npc_id} - {None}
    return [{"action_id": a.action_instance_id, "day": a.story_day, "location": a.location_id,
             "topic": a.topic,
             "transcript": [dict(t) for t in a.transcript
                            if not t.get("visible_to") or bool(participants.intersection(t["visible_to"]))],
             "observed_results": list(a.hard_outcomes)}
            for a in session.governance_actions.values()
            if a.action_kind == "household_visit" and participants.intersection(a.target_ids)]


def prior_personal_conversations(session, contract) -> list[dict]:
    return [asdict(c) for c in session.completed_conversations
            if contract.signatory_npc_id and c.npc_id == contract.signatory_npc_id]


def shared_conversations(session, contract) -> list[dict]:
    return [{"story_day": c.get("story_day"), "agenda": c.get("agenda"),
             "transcript": [t for t in c.get("transcript", ())
                            if not t.get("visible_to") or contract.signatory_npc_id in t["visible_to"]],
             "closure_summary": c.get("closure_summary", "")}
            for c in session.completed_group_conversations
            if contract.signatory_npc_id and contract.signatory_npc_id in c.get("participant_ids", ())]


def personal_meetings(session, contract) -> list[dict]:
    return [{"story_day": m.story_day, "topic": m.topic, "resolution": m.resolution,
             "transcript": [t for t in m.transcript
                            if not t.get("visible_to") or contract.signatory_npc_id in t["visible_to"]]}
            for m in session.meetings.values()
            if contract.signatory_npc_id and contract.signatory_npc_id in m.participant_ids]


def public_review_history(contract) -> list[dict]:
    return [{key: value for key, value in item.items() if key != "review_fingerprint"}
            for item in contract.review_history]
