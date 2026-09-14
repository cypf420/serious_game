from copy import deepcopy

import pytest

from serious_game_backend.domain.gameplay_governance import ResourceReservation
from tests.test_final_check_contract_attempts import game


@pytest.mark.parametrize('prior_hash', [
    'sha256:c4795211286ca05dafd97e91b0f4ff513f2b78e536dfc5d9f0a0454063d6932a',
    'sha256:17614221c51fcca8a8b5b4716533367cae6f6812d41ea57d845095896edb3a43',
])
def test_old_save_uses_new_capacity_without_resetting_occupied_housing(game, prior_hash):
    session = game.session()
    session.package_content_hash = prior_hash
    ids = ['housing_d1_100_accessible', 'housing_d1_120_accessible']
    for rid in ids:
        session.resource_reservations.append(ResourceReservation(
            rid, 'contract', 'existing-contract', rid, 1, 'allocated', 1))
    game.save(session)
    before = deepcopy(game.session())
    for _ in range(2):
        response = game.client.get(game.base + '/governance', headers=game.headers)
        assert response.status_code == 200, response.text
        pools = {p['resource_id']: p for p in response.json()['resources']['resource_pools']}
        for rid in ids:
            assert pools[rid]['capacity'] == 3
            assert pools[rid]['available'] == 2
            assert pools[rid]['allocated'] == 1
    assert game.session() == before
