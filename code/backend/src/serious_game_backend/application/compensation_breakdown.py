"""Read-only explanation of the existing compensation rates, never settlement."""


def compensation_breakdown(package, household, contract, *, reward, base_total):
    rates = package.governance_config["compensation_rates"]
    specs = [
        ("合法住宅", household.legal_residential_area_m2, "平方米", float(rates["residential_structure"][household.residential_structure])),
        ("认定宅基地", household.homestead_recognized_m2, "平方米", float(rates["homestead_recognized_m2"])),
        ("承包地", household.contracted_land_mu, "亩", float(rates["contracted_land_mu"])),
        ("搬家补助", 1, "户", float(rates["moving_per_household"])),
        ("按期签约奖励", 1 if reward else 0, "户", float(rates["public_window_reward"])),
    ]
    rows = [dict(label=label, quantity=quantity, unit=unit, rate=rate, amount=quantity * rate)
            for label, quantity, unit, rate in specs]
    terms = contract.term_sheet or {}
    automatic = terms.get("automatic_arrangement") or {}
    return dict(rows=rows, unit="万元", suggested_base_total=base_total,
                rounding_adjustment=base_total - sum(row["amount"] for row in rows),
                saved_base_amount=automatic.get("base_cash_amount"),
                saved_transition_amount=automatic.get("transition_cash_amount"),
                saved_total=terms.get("cash_amount"),
                transition_population=household.resettlement_population,
                transition_months=terms.get("transition_months"),
                transition_rate=float(rates["transition_per_person_month"]),
                reward_available=reward,
                source="本内容包补偿费率与本户登记底账；政策建议基础额按当前日期计算，已保存金额单列。")
