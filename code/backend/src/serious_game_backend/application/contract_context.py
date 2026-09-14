"""Read-only saved-contract projection for conversation paths.

The audience and fields follow the existing household-visit context. This
does not grant signature authority or inspect drafts held only in the UI.
"""
from copy import deepcopy

from serious_game_backend.application import contract_requirements
from serious_game_backend.application.contract_workflow import (
    public_review_history,
    selected_housing,
)


CONTRACT_DIALOGUE_CONSTRAINTS = [
    "requirements_assessed=true 时，remaining_conditions 是当前保存版本经后端核验的本户签约条件缺项；为空即本户条件已满足，可以正式提交，最终签署仍由后端校验版本、费用和资源并结算。不得新增签约前置条件。",
    "角色的生活或程序关注可以保留，但须与签约缺项区分：不在 remaining_conditions 中的听证、账目核验等只能表达关注或建议，不能说成必须先办、办完才签。缺项未核验时不得声称条件已满足。",
    "不得虚构未记录的过往发言。只有本NPC实际对话记录能证明的内容才可说成‘我之前提过’；玩家当前转述、疑问或假设不证明NPC曾经说过，也不证明资料、图号或领取手续存在。",
    "housing_delivery_day 是剧情绝对日：值60应说‘剧情第60日交房’，不能说‘60天后交房’或‘六十天交房’；约定交房日不代表已交房。房源面积与属性以当前 selected_housing 为准，未提供的图号、边界、电梯、楼层等不得编造。",
]


def own_saved_contracts(session, package, npc_id: str) -> list[dict]:
    result = []
    for contract in session.household_contracts.values():
        batch = session.contract_batches.get(contract.batch_id)
        own = contract.signatory_npc_id == npc_id
        if not own and (batch is None or batch.representative_npc_id != npc_id):
            continue
        version = next((item for item in contract.versions
                        if item.version == contract.current_version), None)
        if version is None:
            continue
        requirements_assessed = (
            contract.term_sheet is not None
            and "service_allocations" in contract.term_sheet
            and any(h.household_id == contract.household_id for h in getattr(package, "households", ()))
        )
        remaining_conditions = (
            contract_requirements.missing_contract_conditions(session, package, contract)
            if requirements_assessed else None
        )
        result.append({
            "contract_id": contract.contract_id,
            "household_id": contract.household_id,
            "signatory_name": contract.signatory_name,
            "conversation_npc_id": npc_id,
            "status": contract.status,
            "terms": contract.term_sheet,
            "current_version": version.version,
            "contract_text": version.text,
            "selected_housing": selected_housing(package, contract.term_sheet or {}),
            "requirements_assessed": requirements_assessed,
            "remaining_conditions": remaining_conditions,
            "dialogue_constraints": CONTRACT_DIALOGUE_CONSTRAINTS,
            "reviews": public_review_history(contract),
            "current_review": next((review for review in reversed(public_review_history(contract))
                                    if review.get("version") == version.version), None),
            "history_note": "历史答复仅适用于其记录版本；以当前方案及已核实材料为准。",
            "scope": "本人的合同" if own else "代表转述的本批次合同；须由各户本人决定签署",
        })
    return deepcopy(result)
