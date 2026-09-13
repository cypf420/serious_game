"""Read-only saved-contract projection for conversation paths.

The audience and fields follow the existing household-visit context. This
does not grant signature authority or inspect drafts held only in the UI.
"""
from copy import deepcopy

from serious_game_backend.application.contract_workflow import (
    public_review_history,
    selected_housing,
)


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
        result.append({
            "household_id": contract.household_id,
            "status": contract.status,
            "terms": contract.term_sheet,
            "current_version": version.version,
            "contract_text": version.text,
            "selected_housing": selected_housing(package, contract.term_sheet or {}),
            "reviews": public_review_history(contract),
            "scope": "本人的合同" if own else "代表转述的本批次合同；须由各户本人决定签署",
        })
    return deepcopy(result)
