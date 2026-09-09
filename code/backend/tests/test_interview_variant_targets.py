from types import SimpleNamespace
from unittest.mock import patch

import pytest

from serious_game_backend.application.gameplay_governance_service import GameplayGovernanceService
from serious_game_backend.domain.errors import ActionUnavailableError


@pytest.mark.parametrize("target_kind", ["enterprise", "media"])
def test_interview_variant_accepts_its_public_non_cadre_target(target_kind):
    service = object.__new__(GameplayGovernanceService)
    package = SimpleNamespace(governance_config={"cadre_npc_ids": ["cadre"]})
    variant = {"legal_target_ids": [target_kind]}
    with patch.object(service, "_visible_governance_npc_ids", return_value={"cadre", target_kind}):
        service._validate_action_targets(
            package, action_kind="cadre_interview", target_ids=(target_kind,),
            archive_ids=(), topic="核实责任", proposed_document_type=None,
            lead_npc_id=None, session=SimpleNamespace(), variant=variant,
        )


@pytest.mark.parametrize("variant,target,visible", [
    ({"legal_target_ids": ["enterprise"]}, "cadre", {"cadre", "enterprise"}),
    ({"legal_target_ids": ["enterprise"]}, "enterprise", {"cadre"}),
    (None, "enterprise", {"cadre", "enterprise"}),
])
def test_interview_still_rejects_wrong_or_hidden_targets(variant, target, visible):
    service = object.__new__(GameplayGovernanceService)
    package = SimpleNamespace(governance_config={"cadre_npc_ids": ["cadre"]})
    with patch.object(service, "_visible_governance_npc_ids", return_value=visible):
        with pytest.raises(ActionUnavailableError):
            service._validate_action_targets(
                package, action_kind="cadre_interview", target_ids=(target,),
                archive_ids=(), topic="核实责任", proposed_document_type=None,
                lead_npc_id=None, session=SimpleNamespace(), variant=variant,
            )
