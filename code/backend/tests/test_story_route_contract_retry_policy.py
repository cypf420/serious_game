"""The witness driver must spend turns on progress, not calendar-only retries."""
from copy import deepcopy

import pytest

from tests import test_story_routes_v3 as routes


def reviewed_contract():
    return {
        "household_id": "HE-02",
        "term_sheet": {"payment_day": 63},
        "current_version": 1,
        "review_history": [{"version": 1, "remaining_conditions": ["missing evidence"]}],
        "remaining_conditions": ["missing evidence"],
        "can_review": False,
    }


def test_unchanged_blocker_preserves_saved_version_even_if_inventory_changed():
    contract = reviewed_contract()
    # Backend may permit a new attempt after another household consumes stock.
    # That does not solve this household's unchanged evidence requirement.
    contract["can_review"] = True
    before = deepcopy(contract)
    assert not routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)
    assert contract == before


@pytest.mark.parametrize("missing", [[], ["different evidence"]])
def test_new_verified_condition_is_reconsidered(missing):
    contract = reviewed_contract()
    contract.update(remaining_conditions=missing, can_review=True)
    assert routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)


def test_explicit_new_saved_version_is_submitted():
    contract = reviewed_contract()
    contract["current_version"] = 2
    assert routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)


def test_first_submission_is_not_suppressed_by_known_missing_material():
    contract = reviewed_contract()
    contract["review_history"] = []
    assert routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)


def test_actual_viewing_still_runs_for_lao():
    contract = reviewed_contract()
    contract["household_id"] = "LAO-01"
    assert routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)


def test_unchanged_model_response_waits_for_backend_to_allow_retry():
    contract = reviewed_contract()
    contract["remaining_conditions"] = []
    contract["review_history"][0]["remaining_conditions"] = []
    assert not routes.StoryRoutesV3Tests.route_contract_needs_attempt(contract)
