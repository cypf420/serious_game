from __future__ import annotations

from pathlib import Path
import json
import unittest

from serious_game_backend.application.action_service import ActionService
from serious_game_backend.domain.enums import ActionCostTier, NPCStateTier
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.infrastructure.script_packages.file_loader import FileScriptPackageLoader


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_backend_dev_v1"
GAMEPLAY_PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v2"
GAMEPLAY_V3_PACKAGE_DIR = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"


class ScriptPackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = FileScriptPackageLoader().load(PACKAGE_DIR)

    def test_package_has_frozen_first_release_counts(self) -> None:
        self.assertEqual(31, len(self.package.action_rules))
        self.assertEqual(29, len(self.package.npc_profiles))
        self.assertEqual(
            19,
            sum(item.state_tier is NPCStateTier.DEEP for item in self.package.npc_profiles),
        )
        self.assertEqual(
            9,
            sum(item.state_tier is NPCStateTier.LIMITED for item in self.package.npc_profiles),
        )
        role_profiles = [item for item in self.package.npc_profiles if item.role_setting]
        self.assertEqual(29, len(role_profiles))
        self.assertTrue(all(item.source_line > 0 for item in role_profiles))
        self.assertEqual(18, len(self.package.facts))
        self.assertTrue(all(item.source_line > 0 for item in self.package.facts.values()))
        self.assertEqual(
            {item.npc_id for item in self.package.npc_profiles},
            {item.npc_id for item in self.package.interaction_opportunities},
        )

    def test_gameplay_profiles_have_structured_big_five(self) -> None:
        package = FileScriptPackageLoader().load(GAMEPLAY_PACKAGE_DIR)
        profiles = {item.npc_id: item for item in package.npc_profiles}

        self.assertEqual(
            29,
            sum(item.big_five is not None for item in package.npc_profiles),
        )
        self.assertFalse(any(
            item.big_five is None for item in package.npc_profiles
        ))
        self.assertEqual(
            {
                "openness": 55,
                "conscientiousness": 80,
                "extraversion": 30,
                "agreeableness": 50,
                "neuroticism": 60,
            },
            profiles["npc_shi_wenbin"].big_five.as_dict(),
        )
        self.assertIn(
            "他在网络里站在体制的最末梢",
            profiles["npc_shi_wenbin"].role_setting,
        )
        expected_inferred_profiles = {
            "npc_lao_juetou": (20, 70, 20, 30, 50),
            "npc_miao_xiwang": (45, 65, 35, 55, 75),
            "npc_deng_shouben": (25, 70, 20, 50, 70),
            "npc_jiang_chongyue": (45, 90, 50, 35, 30),
            "npc_luo_jian": (65, 85, 35, 65, 55),
            "npc_cui_guanglin": (30, 90, 25, 60, 25),
        }
        for npc_id, expected in expected_inferred_profiles.items():
            with self.subTest(npc_id=npc_id):
                big_five = profiles[npc_id].big_five
                self.assertEqual(expected, (
                    big_five.openness,
                    big_five.conscientiousness,
                    big_five.extraversion,
                    big_five.agreeableness,
                    big_five.neuroticism,
                ))
                self.assertIn(
                    "这组大五人格分数依据剧本行为反推，只用于角色扮演",
                    profiles[npc_id].role_setting,
                )
                self.assertGreater(len(profiles[npc_id].role_setting), 500)

    def test_big_five_rejects_incomplete_or_invalid_scores(self) -> None:
        valid = {
            "openness": 55,
            "conscientiousness": 80,
            "extraversion": 30,
            "agreeableness": 50,
            "neuroticism": 60,
        }
        incomplete = dict(valid)
        incomplete.pop("neuroticism")
        out_of_range = dict(valid, openness=101)
        non_integer = dict(valid, openness="55")

        for value in (incomplete, out_of_range, non_integer):
            with self.subTest(value=value):
                with self.assertRaises(ContentValidationError):
                    FileScriptPackageLoader._load_big_five(value)

    def test_action_cost_table_matches_final_script(self) -> None:
        script_path = BACKEND_ROOT.parents[1] / "最终剧本.md"
        lines = script_path.read_text(encoding="utf-8").splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("| 工具"))
        expected = {}
        for line in lines[start + 2:]:
            if line.startswith(":::代码"):
                break
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) == 5 and cells[2].isdigit():
                expected[cells[0]] = (
                    cells[1],
                    int(cells[2]),
                    int(cells[3]),
                    int(cells[4]),
                )

        actual = {
            rule.name: (
                rule.category,
                rule.costs[ActionCostTier.NORMAL],
                rule.costs[ActionCostTier.SENSITIVE],
                rule.costs[ActionCostTier.ACCEPTANCE],
            )
            for rule in self.package.action_rules.values()
        }
        self.assertEqual(expected, actual)

    def test_conditional_options_are_registered_from_final_script(self) -> None:
        dp3_02 = self.package.decisions["dp3_02"]
        self.assertEqual(frozenset({"见过原件"}), dp3_02.option("a").required_flags)
        self.assertEqual(
            frozenset({"见过原件", "罗健留底"}),
            dp3_02.option("c").required_any_flags,
        )
        dp4_09 = self.package.decisions["dp4_09"]
        self.assertIn("赵建国书面自证在手", dp4_09.option("b").forbidden_flags)

    def test_dp2_07_keeps_real_and_reported_signing_separate(self) -> None:
        decision = self.package.decisions["dp2_07"]
        option_a = decision.option("a")
        option_b = decision.option("b")

        self.assertNotIn("signed_households", option_a.effects.ledger_deltas)
        self.assertNotIn("reported_signed_households", option_a.effects.ledger_deltas)
        self.assertEqual(1, len(option_a.conditional_effects))
        branch = option_a.conditional_effects[0]
        self.assertEqual(frozenset({"虚假签约"}), branch.required_flags)
        self.assertEqual(
            (-4, -2), branch.effects.ledger_deltas["reported_signed_households"]
        )
        self.assertNotIn("signed_households", branch.effects.ledger_deltas)
        self.assertEqual(frozenset({"虚假签约"}), branch.effects.close_flags)

        self.assertNotIn("signed_households", option_b.effects.ledger_deltas)
        self.assertIn("reported_signed_households", option_b.effects.ledger_deltas)

        without_false_signing = ActionService._effective_effects(option_a, set())
        with_false_signing = ActionService._effective_effects(
            option_a, {"虚假签约"}
        )
        self.assertNotIn(
            "reported_signed_households", without_false_signing.ledger_deltas
        )
        self.assertEqual(
            (-4, -2),
            with_false_signing.ledger_deltas["reported_signed_households"],
        )
        self.assertIn("虚假签约", with_false_signing.close_flags)

    def test_lead_roster_uses_five_value_state_and_runtime_gates(self) -> None:
        roster = self.package.decisions["dp4_roster_disposition"]
        self.assertEqual(46, roster.story_day)
        self.assertEqual(
            {"未获取", "己方封存", "呈交上级", "被销毁"},
            {
                item.effects.state_assignments["lead_roster_disposition"]
                for item in roster.options
            },
        )
        dp6_03 = self.package.decisions["dp6_03"]
        self.assertEqual(
            "己方封存",
            dp6_03.option("c").effects.state_assignments[
                "lead_roster_disposition"
            ],
        )
        dp6_06 = self.package.decisions["dp6_06"]
        self.assertFalse(
            dp6_06.option("a").is_available(
                set(), {"lead_roster_disposition": "未获取"}
            )
        )
        self.assertTrue(
            dp6_06.option("a").is_available(
                set(), {"lead_roster_disposition": "己方封存"}
            )
        )
        self.assertEqual(
            "交给记者",
            dp6_06.option("a").effects.state_assignments[
                "lead_roster_disposition"
            ],
        )

    def test_dp6_03_household_settlement_obeys_both_guards(self) -> None:
        option = self.package.decisions["dp6_03"].option("a")

        normal = ActionService._effective_effects(option, set())
        duplicate = ActionService._effective_effects(option, {"苗喜旺已入账"})
        blocked = ActionService._effective_effects(option, {"差异化口子已开"})
        allowed_with_board = ActionService._effective_effects(
            option, {"差异化口子已开", "进度榜已上墙"}
        )

        self.assertEqual((1, 1), normal.ledger_deltas["signed_households"])
        self.assertIn("苗喜旺已入账", normal.open_flags)
        self.assertNotIn("signed_households", duplicate.ledger_deltas)
        self.assertNotIn("signed_households", blocked.ledger_deltas)
        self.assertEqual(
            (1, 1), allowed_with_board.ledger_deltas["signed_households"]
        )

    def test_chapter_six_household_guards_are_idempotent(self) -> None:
        old_stubborn = self.package.decisions["dp6_02"].option("b")
        self.assertEqual(
            (1, 1),
            ActionService._effective_effects(old_stubborn, set()).ledger_deltas[
                "signed_households"
            ],
        )
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(
                old_stubborn, {"老倔头已入账"}
            ).ledger_deltas,
        )

        ning_fallback = self.package.decisions["ev6_01"].option("a")
        self.assertEqual(
            (2, 2),
            ActionService._effective_effects(ning_fallback, set()).ledger_deltas[
                "signed_households"
            ],
        )
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(
                ning_fallback, {"宁德海线已锁死"}
            ).ledger_deltas,
        )

        livelihood_first = self.package.decisions["dp6_07"].option("a_b_c_d_e")
        self.assertEqual(
            (1, 1),
            ActionService._effective_effects(livelihood_first, set()).ledger_deltas[
                "signed_households"
            ],
        )
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(
                livelihood_first, {"邓守本已入账"}
            ).ledger_deltas,
        )

    def test_chapter_five_deferred_households_use_named_locks(self) -> None:
        self.assertEqual(
            frozenset({"村账在手"}),
            self.package.decisions["dp5_04"].required_flags,
        )

        ning = self.package.decisions["dp5_06"].option("a")
        self.assertNotIn(
            "signed_households", ActionService._effective_effects(ning, set()).ledger_deltas
        )
        self.assertEqual(
            (2, 2),
            ActionService._effective_effects(ning, {"代签已查实"}).ledger_deltas[
                "signed_households"
            ],
        )

        ma = self.package.decisions["dp5_07"]
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(ma.option("d"), set()).ledger_deltas,
        )
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(ma.option("e"), set()).ledger_deltas,
        )
        self.assertEqual(
            (3, 3),
            ActionService._effective_effects(
                ma.option("e"), {"党员样板已立"}
            ).ledger_deltas["signed_households"],
        )

        he = self.package.decisions["dp5_08"].option("b")
        self.assertIn("何铁柱已冷", ActionService._effective_effects(he, set()).open_flags)
        self.assertEqual(
            (4, 4),
            ActionService._effective_effects(
                he, {"何铁柱欠你一个人情"}
            ).ledger_deltas["signed_households"],
        )

        zhou = self.package.decisions["dp5_09"]
        self.assertEqual(
            (6, 6),
            ActionService._effective_effects(zhou.option("a"), set()).ledger_deltas[
                "signed_households"
            ],
        )
        self.assertEqual(
            (4, 4),
            ActionService._effective_effects(
                zhou.option("a"), {"周大山预付已入账"}
            ).ledger_deltas["signed_households"],
        )
        pressured = ActionService._effective_effects(
            zhou.option("b"), {"周大山被压价"}
        )
        self.assertNotIn("signed_households", pressured.ledger_deltas)
        self.assertIn("周大山已寒心", pressured.open_flags)

    def test_d86_cross_chapter_recovery_is_structured(self) -> None:
        day = self.package.story_day(86)
        self.assertEqual(2, len(day.night_blocks))
        self.assertEqual(3, len(day.night_conditional_effects))
        self.assertEqual(
            (4, 4),
            day.night_conditional_effects[0].effects.ledger_deltas[
                "signed_households"
            ],
        )

    def test_ma_changshun_natural_trigger_reads_hidden_ratio_ledger(self) -> None:
        branches = self.package.story_day(75).night_conditional_effects
        normal = branches[0]
        lowered = branches[1]
        flags = {"马长顺待自然触发"}
        self.assertFalse(normal.matches(flags, {}, {"signed_households": 2}))
        self.assertTrue(normal.matches(flags, {}, {"signed_households": 3}))
        self.assertTrue(
            lowered.matches(
                flags | {"进度榜已上墙"}, {}, {"signed_households": 1}
            )
        )

    def test_dp6_07_invalid_environment_first_falls_back_to_second(self) -> None:
        option = self.package.decisions["dp6_07"].option("b_a_c_d_e")
        fallback = ActionService._effective_effects(option, set())
        valid_environment = ActionService._effective_effects(
            option, {"环评揭穿"}
        )

        self.assertIn("民生优先", fallback.open_flags)
        self.assertEqual((1, 1), fallback.ledger_deltas["signed_households"])
        self.assertNotIn("合规优先", fallback.open_flags)
        self.assertIn("合规优先", valid_environment.open_flags)
        self.assertIn("面子优先", valid_environment.close_flags)
        self.assertNotIn("民生优先", valid_environment.open_flags)
        self.assertNotIn("signed_households", valid_environment.ledger_deltas)

    def test_chapter_four_household_layers_use_cross_npc_guards(self) -> None:
        zhou = self.package.decisions["dp4_05"]
        self.assertEqual(frozenset({"周氏松口"}), zhou.required_flags)
        self.assertEqual(
            (4, 4),
            ActionService._effective_effects(zhou.option("a"), set()).ledger_deltas[
                "signed_households"
            ],
        )

        tan = self.package.decisions["dp4_06"].option("a")
        self.assertIn("谭老六被空口应付", ActionService._effective_effects(tan, set()).open_flags)
        self.assertEqual(
            (3, 3),
            ActionService._effective_effects(
                tan, {"旧账缺口已坐实"}
            ).ledger_deltas["signed_households"],
        )

        yuan = self.package.decisions["ev4_01"].option("a")
        self.assertEqual(
            (2, 2),
            ActionService._effective_effects(yuan, set()).ledger_deltas[
                "signed_households"
            ],
        )
        self.assertNotIn(
            "signed_households",
            ActionService._effective_effects(
                yuan, {"赔付换谅解在册"}
            ).ledger_deltas,
        )

        wu = self.package.decisions["dp4_07"].option("a")
        self.assertNotIn(
            "signed_households", ActionService._effective_effects(wu, set()).ledger_deltas
        )
        self.assertEqual(
            (6, 6),
            ActionService._effective_effects(
                wu, {"普查结果公开"}
            ).ledger_deltas["signed_households"],
        )

        he = self.package.decisions["dp4_08"].option("a")
        combined = ActionService._effective_effects(
            he, {"吴秀英已入账", "谭老六已安抚"}
        )
        self.assertEqual((6, 6), combined.ledger_deltas["signed_households"])
        self.assertTrue({"何铁柱已入账", "杨波已入账"}.issubset(combined.open_flags))

    def test_calendar_uses_precomputed_cost_tiers(self) -> None:
        self.assertEqual(ActionCostTier.NORMAL, self.package.action_cost_tier(1))
        self.assertEqual(ActionCostTier.SENSITIVE, self.package.action_cost_tier(31))
        self.assertEqual(ActionCostTier.ACCEPTANCE, self.package.action_cost_tier(59))
        self.assertEqual(ActionCostTier.SENSITIVE, self.package.action_cost_tier(61))
        self.assertEqual(ActionCostTier.ACCEPTANCE, self.package.action_cost_tier(76))

    def test_four_timeline_anchors_are_independent(self) -> None:
        anchors = {item.event_id: item.story_day for item in self.package.fixed_events}
        self.assertEqual(31, anchors["event_d31_municipal_inspection_arrival"])
        self.assertEqual(45, anchors["event_d45_municipal_inspection_departure"])
        self.assertEqual(59, anchors["event_d59_environmental_reception_arrival"])
        self.assertEqual(90, anchors["event_d90_final_acceptance"])

    def test_d1_tutorial_decision_is_structured_and_zero_cost(self) -> None:
        day_one = self.package.story_day(1)
        self.assertIsNotNone(day_one)
        self.assertEqual("beat_d01_arrival_and_reception", day_one.beat_id)
        self.assertFalse(day_one.allow_actions)
        self.assertTrue(day_one.allow_end_day)
        self.assertEqual("ev1_01_reception_bag", day_one.opening_decision_id)

        decision = self.package.decisions["ev1_01_reception_bag"]
        self.assertEqual(0, decision.action_point_cost)
        self.assertFalse(decision.skippable)
        self.assertEqual(4, len(decision.options))
        self.assertEqual(
            {
                "a_reject_on_site",
                "b_file_with_discipline",
                "c_return_next_day",
                "d_keep_in_drawer",
            },
            {item.option_id for item in decision.options},
        )

        day_two = self.package.story_day(2)
        self.assertIsNotNone(day_two)
        self.assertTrue(day_two.allow_actions)
        self.assertTrue(day_two.allow_end_day)
        self.assertEqual(
            "dp1_01_taskforce_faction_map", day_two.opening_decision_id
        )
        self.assertEqual(
            {"flag_wu_first_talk_completed"},
            set(day_two.end_day_requires_flags),
        )

    def test_current_d1_player_text_is_sourced_from_final_script(self) -> None:
        current_package = FileScriptPackageLoader().load(
            BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"
        )
        script_text = (BACKEND_ROOT.parents[1] / "最终剧本.md").read_text(
            encoding="utf-8"
        )
        normalized_script_text = script_text.replace("**", "")
        for label in ("A·", "B·", "C·", "D·", "E·"):
            normalized_script_text = normalized_script_text.replace(label, "")
        compact_script_text = "".join(normalized_script_text.split())
        for story_day in (1,):
            beat = current_package.story_day(story_day)
            for block in (*beat.opening_blocks, *beat.night_blocks):
                if block.kind != "system":
                    if block.text not in script_text:
                        # Approved fact corrections retain exact source provenance
                        # without rewriting the original authoring manuscript.
                        registry = json.loads((BACKEND_ROOT / 'content/editorial/story_integrity_20260908.json').read_text(encoding='utf8'))
                        matches = [op for op in registry['operations']
                                   if op['file']=='story_beats.json'
                                   and op.get('node_id')==beat.beat_id
                                   and op.get('after')==block.text]
                        self.assertEqual(1,len(matches),block.block_id)
                        self.assertTrue(matches[0]['before'] in script_text,block.block_id)

        decision = current_package.decisions["ev1_01_reception_bag"]
        self.assertIn(decision.prompt, script_text)
        for option in decision.options:
            self.assertIn(
                "".join(option.text.split()), compact_script_text, option.option_id
            )
            self.assertIn(option.consequence, script_text, option.option_id)
        for decision in current_package.decisions.values():
            self.assertTrue(decision.prompt.strip(), decision.decision_id)
            for block in decision.followup_blocks:
                self.assertTrue(block.text.strip(), block.block_id)
            for option in decision.options:
                if " > " in option.text:
                    self.assertEqual(
                        option.option_id.split("_"),
                        [item.lower() for item in option.text.split(" > ")],
                    )
                else:
                    self.assertTrue(option.text.strip(), option.option_id)
                self.assertTrue(option.consequence.strip(), option.option_id)
        for opportunity in self.package.interaction_opportunities:
            for block in opportunity.completion_blocks:
                self.assertIn(block.text, script_text, block.block_id)

    def test_content_hash_is_deterministic(self) -> None:
        loader = FileScriptPackageLoader()
        self.assertEqual(
            loader.compute_content_hash(PACKAGE_DIR),
            loader.compute_content_hash(PACKAGE_DIR),
        )

    def test_every_household_signatory_setting_contains_its_authoritative_ledger(self) -> None:
        package = FileScriptPackageLoader().load(GAMEPLAY_V3_PACKAGE_DIR)
        profiles = {item.npc_id: item for item in package.npc_profiles}
        limited = {
            item.household_id: item
            for item in package.limited_household_signatories
        }

        for household in package.households:
            ledger_markers = (
                f"户号 {household.household_id}",
                f"登记人口{household.registered_population}人",
                f"实际居住{household.actual_residents}人",
                f"安置人口{household.resettlement_population}人",
                f"合法住宅{household.legal_residential_area_m2:g}平方米",
                f"认定宅基地{household.homestead_recognized_m2:g}平方米",
                f"承包地{household.contracted_land_mu:g}亩",
            )
            if household.is_shadow_household:
                setting = limited[household.household_id].role_setting
            else:
                setting = profiles[household.representative_npc].role_setting
            for marker in ledger_markers:
                self.assertIn(marker, setting, (household.household_id, marker))

    def test_every_v3_map_location_has_an_enabled_governance_entry(self) -> None:
        package = FileScriptPackageLoader().load(GAMEPLAY_V3_PACKAGE_DIR)
        enabled_variants = [
            item
            for item in package.governance_config.get("action_variants", ())
            if item.get("enabled") is True
        ]
        covered_location_ids = {
            str(location_id)
            for variant in enabled_variants
            for location_id in variant.get("legal_location_ids", ())
        }

        self.assertEqual(
            {item.location_id for item in package.map_locations},
            covered_location_ids,
        )

    def test_every_v3_fact_has_a_reachable_player_acquisition_method(self) -> None:
        package = FileScriptPackageLoader().load(GAMEPLAY_V3_PACKAGE_DIR)
        archives = {
            item.archive_id: item for item in package.archive_investigations
        }
        opportunities = {
            item.opportunity_id: item
            for item in package.interaction_opportunities
        }
        actions = package.resource_actions

        self.assertEqual(19, len(package.facts))
        for fact in package.facts.values():
            self.assertTrue(fact.acquisition_methods, fact.fact_id)
            for method in fact.acquisition_methods:
                self.assertTrue(str(method["label"]).strip(), fact.fact_id)
                self.assertTrue(str(method["instructions"]).strip(), fact.fact_id)
                self.assertGreaterEqual(int(method["unlock_day"]), 1)
                if method["route_type"] == "archive":
                    archive = archives[str(method["source_id"])]
                    self.assertIn(fact.fact_id, archive.result_fact_ids)
                    self.assertEqual(archive.unlock_day, method["unlock_day"])
                elif method["route_type"] == "conversation":
                    opportunity = opportunities[str(method["source_id"])]
                    self.assertIn(
                        fact.fact_id,
                        set(opportunity.allowed_fact_ids)
                        | set(opportunity.completion_fact_ids),
                    )
                    self.assertGreaterEqual(
                        int(method["unlock_day"]), opportunity.day_min
                    )
                    self.assertLessEqual(
                        int(method["unlock_day"]), opportunity.day_max
                    )
                else:
                    self.assertEqual("action", method["route_type"])
                    action = actions[str(method["source_id"])]
                    self.assertTrue(action.enabled)
                    self.assertIn(fact.fact_id, action.result_fact_ids)
                    self.assertEqual(action.unlock_day, method["unlock_day"])

    def test_recording_days_d12_to_d26_have_complete_player_facing_flow(self) -> None:
        package = FileScriptPackageLoader().load(
            BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v2"
        )
        forbidden = ("编号决策", "关键剧情", "代码", "来找玩家")
        previous_opening = None
        for day in range(12, 27):
            beat = package.story_day(day)
            has_decision = bool(beat.opening_decision_id or beat.decision_ids)
            self.assertTrue(
                beat.opening_blocks or has_decision or beat.day_mode == "free_action",
                f"D{day} neither has story nor an explicit free-action card",
            )
            opening = "\n".join(block.text for block in beat.opening_blocks)
            if opening and previous_opening:
                self.assertNotEqual(previous_opening, opening, f"D{day} repeats D{day - 1}")
            if opening:
                previous_opening = opening
            for block in beat.opening_blocks:
                self.assertTrue(block.scene_id, block.block_id)
                self.assertTrue(block.presentation_phase, block.block_id)
                self.assertFalse(any(word in block.text for word in forbidden), block.block_id)
            for decision_id in (beat.opening_decision_id, *beat.decision_ids):
                if not decision_id:
                    continue
                decision = package.decisions[decision_id]
                self.assertEqual(0, decision.action_point_cost, decision_id)
                self.assertTrue(decision.presentation_blocks, decision_id)
                self.assertTrue(decision.followup_blocks, decision_id)

        labels = package.decisions["dp3_07"].input_schema["labels"]
        self.assertEqual(
            ["巡察组书面说明", "柳林村签约", "清江排口取证", "谭老六卷宗"],
            [labels[key] for key in ("a", "b", "c", "d")],
        )


if __name__ == "__main__":
    unittest.main()
