from types import SimpleNamespace

from serious_game_backend.application.night_simulation_service import NightSimulationService


def test_empty_mornings_do_not_generate_transition_filler():
    for day in range(1, 90):
        for propagated in ([], [{"fact_id": "test-message"}]):
            assert NightSimulationService._morning_card(
                day, [], propagated, [], package_id="pkg_gameplay_v3",
            ) == []


def test_specific_news_and_observed_events_are_preserved():
    news = "吴秀英约好今天带两户村民来核对补偿。"
    assert NightSimulationService._morning_card(
        2, [], [], [{"public_summary": news}], package_id="pkg_gameplay_v3",
    ) == ["夜间动向：" + news]
    observed = "县城茶楼昨晚有人订了包间，订到子夜。"
    assert NightSimulationService._morning_card(
        29, [SimpleNamespace(text=observed, presentation_phase="morning")], [], [],
        package_id="pkg_gameplay_v3",
    ) == [observed]
