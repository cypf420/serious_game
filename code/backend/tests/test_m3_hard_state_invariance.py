from __future__ import annotations

import unittest

from serious_game_backend.domain.llm import RoleTurnResult
from tests.test_doubles import DeterministicRoleLLMGateway


class OppositeBoundedGateway:
    """合法但与默认测试替身相反的软状态输出。"""

    def run_turn(self, context):
        return RoleTurnResult(
            npc_id=context.npc_id,
            dialogue="我听见了，但这件事还要看你接下来怎么做。",
            portrait_state="guarded",
            attitude_direction="decrease",
            attitude_band="heavy",
            anxiety_direction="increase",
            anxiety_band="heavy",
            disclosure_id=(context.allowed_fact_ids[0] if context.allowed_fact_ids else None),
            memory_candidate="新县长的第一次谈话仍需观察。",
        )


def complete_default_replay(gateway) -> tuple[dict, dict]:
    from tests.test_m2_runtime import M2RuntimeTests

    runner = M2RuntimeTests()
    runner.setUp()
    runner.container.npc_turns._gateway = gateway
    session = runner.container.sessions.get_owned(runner.session_id, "acct_m2")
    session.random_seed = "m3-invariance-fixed-seed"
    runner.container.sessions.save(session, expected_version=session.state_version)
    result = runner.reach_d3()
    for index in range(100):
        if result["visible_state"]["status"] == "ended":
            break
        result = runner.drain_decisions(result, f"m3-stop-{index:02d}")
        result = runner.end_day(result["state_version"], f"m3-end-{index:02d}")
    review_response = runner.client.get(
        f"/api/game/session/{runner.session_id}/review", headers=runner.headers
    )
    runner.assertEqual(200, review_response.status_code)
    return result, review_response.json()


class M3HardStateInvarianceTests(unittest.TestCase):
    def test_llm_soft_output_cannot_change_hard_settlement_or_ending(self) -> None:
        baseline, baseline_review = complete_default_replay(DeterministicRoleLLMGateway())
        opposite, opposite_review = complete_default_replay(OppositeBoundedGateway())

        self.assertEqual("ended", baseline["visible_state"]["status"])
        self.assertEqual("ended", opposite["visible_state"]["status"])
        self.assertEqual(baseline["ending"], opposite["ending"])
        self.assertEqual(
            baseline["visible_state"]["ledger"],
            opposite["visible_state"]["ledger"],
        )
        baseline_choices = [
            (item["decision_id"], item["option_id"])
            for item in baseline_review["decision_timeline"]
        ]
        opposite_choices = [
            (item["decision_id"], item["option_id"])
            for item in opposite_review["decision_timeline"]
        ]
        self.assertEqual(76, len(baseline_choices))
        self.assertEqual(baseline_choices, opposite_choices)


if __name__ == "__main__":
    unittest.main()
