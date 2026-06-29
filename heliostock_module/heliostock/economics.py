from __future__ import annotations

import math

import pandas as pd


def annuity_average_factor(rate: float, years: int) -> float:
    if years <= 0:
        return 1.0
    if abs(rate) <= 1e-12:
        return 1.0
    return ((1.0 + rate) ** years - 1.0) / (years * rate)


def annualized_capex_eur(capex_eur: float, years: int) -> float:
    return max(0.0, float(capex_eur)) / max(1, int(years))


def solar_energy_allocation(
    *,
    solar_ht_mwh: float,
    solar_btes_mwh: float,
    solar_net_capex_eur: float,
    solar_p2_annual_eur: float,
    solar_p4_annual_eur: float,
) -> dict[str, float]:
    ht = max(0.0, float(solar_ht_mwh))
    recharge = max(0.0, float(solar_btes_mwh))
    total = ht + recharge
    if total <= 0.0:
        part_ht = 0.0
        part_recharge = 0.0
    else:
        part_ht = ht / total
        part_recharge = recharge / total

    net_capex = max(0.0, float(solar_net_capex_eur))
    p2_annual = max(0.0, float(solar_p2_annual_eur))
    p4_annual = max(0.0, float(solar_p4_annual_eur))
    return {
        "solar_total_mwh": total,
        "part_ht": part_ht,
        "part_recharge": part_recharge,
        "capex_solar_ht_eur": net_capex * part_ht,
        "capex_solar_recharge_eur": net_capex * part_recharge,
        "p2_solar_ht_eur_an": p2_annual * part_ht,
        "p2_solar_recharge_eur_an": p2_annual * part_recharge,
        "p4_solar_ht_eur_an": p4_annual * part_ht,
        "p4_solar_recharge_eur_an": p4_annual * part_recharge,
    }


def solar_recharge_value(
    *,
    allocation: dict[str, float],
    saved_borefield_length_m: float,
    borefield_unit_cost_eur_m: float,
    saved_borefield_net_capex_eur: float | None = None,
    electricity_savings_mwh: float,
    average_electricity_cost_eur_mwh: float,
    analysis_years: int,
) -> dict[str, float | bool | str]:
    saved_length = max(0.0, float(saved_borefield_length_m))
    saved_capex_gross = saved_length * max(0.0, float(borefield_unit_cost_eur_m))
    saved_capex_net = (
        max(0.0, float(saved_borefield_net_capex_eur))
        if saved_borefield_net_capex_eur is not None
        else saved_capex_gross
    )
    electricity_savings = max(0.0, float(electricity_savings_mwh)) * max(0.0, float(average_electricity_cost_eur_mwh))
    annualized_saved_capex = annualized_capex_eur(saved_capex_net, analysis_years)
    annual_gain = annualized_saved_capex + electricity_savings
    annual_solar_recharge_cost = (
        annualized_capex_eur(float(allocation["capex_solar_recharge_eur"]), analysis_years)
        + float(allocation["p2_solar_recharge_eur_an"])
        + float(allocation["p4_solar_recharge_eur_an"])
    )
    net_balance = annual_gain - annual_solar_recharge_cost
    payback = float(allocation["capex_solar_recharge_eur"]) / max(1e-9, annual_gain)
    applicable = float(allocation["part_recharge"]) > 0.0
    return {
        "applicable": applicable,
        "status": "ok" if applicable else "non applicable",
        "solar_btes_mwh": float(allocation["solar_total_mwh"]) * float(allocation["part_recharge"]),
        "solar_recharge_part": float(allocation["part_recharge"]),
        "capex_solar_recharge_eur": float(allocation["capex_solar_recharge_eur"]),
        "saved_borefield_length_m": saved_length,
        "saved_borefield_capex_eur": saved_capex_gross,
        "saved_borefield_net_capex_eur": saved_capex_net,
        "electricity_savings_eur_an": electricity_savings,
        "annualized_saved_borefield_capex_eur_an": annualized_saved_capex,
        "annual_recharge_gain_eur_an": annual_gain,
        "annual_solar_recharge_cost_eur_an": annual_solar_recharge_cost,
        "net_recharge_balance_eur_an": net_balance,
        "recharge_payback_years": payback,
        "p2_borefield_savings_eur_an": 0.0,
    }


def solar_capex_unit_eur_m2(surface_m2: float) -> float:
    s = max(0.0, float(surface_m2))
    if s <= 0.0:
        return 0.0
    if s <= 100.0:
        unit = 1500.0
    elif s <= 1000.0:
        unit = 1500.0 - 0.5556 * (s - 100.0)
    elif s <= 1500.0:
        unit = 1000.0 - 0.35 * (s - 1000.0)
    else:
        unit = -159.1 * math.log(s) + 1990.2
    return max(0.0, unit)


def solar_capex_eur(surface_m2: float) -> float:
    return max(0.0, float(surface_m2)) * solar_capex_unit_eur_m2(surface_m2)


def ademe_solar_aid_eur(
    *,
    surface_m2: float,
    annual_solar_valued_mwh: float,
    capex_eur: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    ademe_years: int = 20,
) -> float:
    s = max(0.0, float(surface_m2))
    production = max(0.0, float(annual_solar_valued_mwh))
    capex = max(0.0, float(capex_eur))
    if s <= 0.0 or capex <= 0.0 or production <= 0.0:
        return 0.0

    smooth_factor = min(1.0, math.exp((1500.0 - s) / 1500.0))
    unit_large = max(0.0, -159.1 * math.log(s) + 1990.2)
    productivity_mwh_m2_year = production / s
    aid_formula = (
        min(s, 1500.0)
        * productivity_mwh_m2_year
        * max(0.0, float(ademe_eur_mwh_year))
        * max(0, int(ademe_years))
        * smooth_factor
    ) + (
        max(s, 1500.0) - 1500.0 * smooth_factor
    ) * unit_large * 0.5

    aid_cap = max(0.0, 0.65 * capex - max(0.0, float(other_public_aid_eur)))
    return max(0.0, min(aid_formula, aid_cap))


def compute_solar_thermal_economics(
    *,
    surface_m2: float,
    annual_solar_valued_mwh: float,
    reference_energy_cost_eur_mwh: float,
    reference_energy_inflation_rate: float,
    analysis_years: int,
    eta_appoint: float,
    auxiliary_electricity_ratio: float,
    electricity_cost_eur_mwh: float,
    maintenance_cost_eur_m2_year: float,
    ademe_eur_mwh_year: float,
    other_public_aid_eur: float,
    annual_solar_total_mwh: float | None = None,
) -> dict[str, float | pd.DataFrame]:
    s = max(0.0, float(surface_m2))
    production = max(0.0, float(annual_solar_valued_mwh))
    p2_production = max(0.0, float(annual_solar_total_mwh)) if annual_solar_total_mwh is not None else production
    years = max(1, int(analysis_years))
    eta_ref = max(1e-9, float(eta_appoint))

    capex_unit = solar_capex_unit_eur_m2(s)
    capex = solar_capex_eur(s)
    ademe_aid = ademe_solar_aid_eur(
        surface_m2=s,
        annual_solar_valued_mwh=production,
        capex_eur=capex,
        ademe_eur_mwh_year=ademe_eur_mwh_year,
        other_public_aid_eur=other_public_aid_eur,
        ademe_years=20,
    )
    aid_total = ademe_aid + max(0.0, float(other_public_aid_eur))
    net_capex = max(0.0, capex - aid_total)
    average_reference_energy_cost = (
        max(0.0, float(reference_energy_cost_eur_mwh))
        / eta_ref
        * annuity_average_factor(float(reference_energy_inflation_rate), years)
    )
    auxiliary_cost = max(0.0, float(auxiliary_electricity_ratio)) * production * max(0.0, float(electricity_cost_eur_mwh))
    # P2 solaire HelioStock: maintenance annuelle = 1 % du CAPEX solaire brut.
    # Le cout unitaire P2 est ensuite rapporte a la production solaire totale
    # valorisee (HT direct + injection BTES), pas seulement au HT aide ADEME.
    maintenance_cost = 0.01 * capex if p2_production > 0.0 else 0.0
    operating_cost = auxiliary_cost + maintenance_cost
    annual_savings = production * average_reference_energy_cost - operating_cost
    payback = net_capex / annual_savings if annual_savings > 0.0 else math.nan
    savings_over_period = annual_savings * years - net_capex

    p1_eur_mwh = auxiliary_cost / production if production > 0.0 else 0.0
    p2_eur_mwh = maintenance_cost / p2_production if p2_production > 0.0 else 0.0
    p4_annual = annualized_capex_eur(net_capex, years)
    p4_eur_mwh = p4_annual / production if production > 0.0 else 0.0
    solar_heat_cost = p1_eur_mwh + p2_eur_mwh + p4_eur_mwh

    cost_breakdown = pd.DataFrame(
        [
            {"Poste": "P1 auxiliaires", "Valeur": p1_eur_mwh},
            {"Poste": "P2 maintenance", "Valeur": p2_eur_mwh},
            {"Poste": "P4 investissement net", "Valeur": p4_eur_mwh},
        ]
    )
    cashflow = pd.DataFrame(
        [
            {
                "Annee": year,
                "Flux annuel (€)": -net_capex if year == 0 else annual_savings,
                "Flux cumule (€)": -net_capex if year == 0 else -net_capex + annual_savings * year,
            }
            for year in range(years + 1)
        ]
    )
    return {
        "annual_solar_direct_ht_mwh": production,
        "annual_solar_total_mwh": p2_production,
        "capex_unit_eur_m2": capex_unit,
        "capex_eur": capex,
        "ademe_aid_eur": ademe_aid,
        "aid_total_eur": aid_total,
        "net_capex_eur": net_capex,
        "aid_rate": aid_total / capex if capex > 0.0 else 0.0,
        "average_reference_energy_cost_eur_mwh": average_reference_energy_cost,
        "annual_savings_eur": annual_savings,
        "payback_years": payback,
        "savings_over_period_eur": savings_over_period,
        "solar_heat_cost_eur_mwh": solar_heat_cost,
        "p1_eur_mwh": p1_eur_mwh,
        "p2_eur_mwh": p2_eur_mwh,
        "p4_eur_mwh": p4_eur_mwh,
        "p1_annual_eur": auxiliary_cost,
        "p2_annual_eur": maintenance_cost,
        "p4_annual_eur": p4_annual,
        "cost_breakdown": cost_breakdown,
        "cashflow": cashflow,
    }


def linear_piecewise_interpolate(x: float, points: list[tuple[float, float]]) -> float:
    clean_points = sorted((float(px), float(py)) for px, py in points)
    if not clean_points:
        return 0.0
    if x <= clean_points[0][0]:
        return clean_points[0][1]
    for (x0, y0), (x1, y1) in zip(clean_points, clean_points[1:]):
        if x <= x1:
            ratio = (x - x0) / max(1e-9, x1 - x0)
            return y0 + ratio * (y1 - y0)
    return clean_points[-1][1]


def geothermal_p2_eur_kw_year(power_kw: float) -> float:
    """P2/P3 geothermal O&M law from the opportunity tool threshold table."""

    return linear_piecewise_interpolate(
        max(0.0, power_kw),
        [
            (5.0, 50.0),
            (20.0, 30.0),
            (100.0, 20.0),
            (500.0, 10.0),
            (2000.0, 5.0),
        ],
    )


def compute_heat_costs(
    *,
    solar_economics: dict[str, float | pd.DataFrame],
    annual_solar_mwh: float,
    annual_pac_heat_mwh: float,
    annual_pac_electricity_mwh: float,
    pac_power_kw: float,
    borefield_length_m: float,
    full_borefield_length_m: float,
    annual_backup_heat_mwh: float,
    backup_power_kw: float,
    reference_heat_mwh: float,
    reference_power_kw: float,
    analysis_years: int,
    gas_reference_p1_eur_mwh_pci: float,
    gas_reference_efficiency: float,
    gas_reference_inflation_rate: float,
    geothermal_p1_eur_mwh: float = 150.0,
    geothermal_pac_capex_eur_kw: float = 1460.0,
    geothermal_borefield_capex_eur_m: float = 100.0,
    geothermal_ademe_eur_mwh_year: float = 50.0,
    geothermal_ademe_years: int = 20,
    backup_p1_eur_mwh: float = 70.0,
    backup_p2_eur_kw_year: float = 10.0,
    backup_capex_eur_kw: float = 200.0,
) -> dict[str, float | pd.DataFrame]:
    years = max(1, int(analysis_years))
    solar_mwh = max(0.0, annual_solar_mwh)
    pac_heat_mwh = max(0.0, annual_pac_heat_mwh)
    pac_electricity_mwh = max(0.0, annual_pac_electricity_mwh)
    backup_heat_mwh = max(0.0, annual_backup_heat_mwh)
    pac_kw = max(0.0, pac_power_kw)
    backup_kw = max(0.0, backup_power_kw)
    length_m = max(0.0, borefield_length_m)
    full_length_m = max(length_m, float(full_borefield_length_m))
    saved_length_m = max(0.0, full_length_m - length_m)
    saved_borefield_capex = saved_length_m * max(0.0, geothermal_borefield_capex_eur_m)
    reference_mwh = max(0.0, reference_heat_mwh)
    reference_kw = max(0.0, reference_power_kw)
    gas_useful_p1 = (
        max(0.0, gas_reference_p1_eur_mwh_pci)
        / max(1e-9, gas_reference_efficiency)
        * annuity_average_factor(float(gas_reference_inflation_rate), years)
    )

    solar_p1 = float(solar_economics["p1_eur_mwh"]) if solar_mwh > 0.0 else 0.0
    solar_p2 = float(solar_economics["p2_eur_mwh"]) if solar_mwh > 0.0 else 0.0
    solar_p4 = float(solar_economics["p4_eur_mwh"]) if solar_mwh > 0.0 else 0.0

    geo_capex = geothermal_pac_capex_eur_kw * pac_kw + geothermal_borefield_capex_eur_m * length_m
    geo_aid_formula = pac_heat_mwh * max(0.0, geothermal_ademe_eur_mwh_year) * max(0, int(geothermal_ademe_years))
    geo_ademe_aid = min(geo_aid_formula, 0.65 * geo_capex)
    geo_net_capex = max(0.0, geo_capex - geo_ademe_aid)
    geo_p2_unit = geothermal_p2_eur_kw_year(pac_kw)
    geo_p1_annual = pac_electricity_mwh * max(0.0, geothermal_p1_eur_mwh)
    geo_p2_annual = geo_p2_unit * pac_kw
    geo_p4_annual = geo_net_capex / years
    geo_p1 = geo_p1_annual / pac_heat_mwh if pac_heat_mwh > 0.0 else 0.0
    geo_p2 = geo_p2_annual / pac_heat_mwh if pac_heat_mwh > 0.0 else 0.0
    geo_p4 = geo_p4_annual / pac_heat_mwh if pac_heat_mwh > 0.0 else 0.0

    backup_capex = backup_capex_eur_kw * backup_kw
    # The Mix ENR backup boiler is the same gas energy vector as the 100% gas
    # reference. Its P1 must therefore use the same useful heat cost, including
    # boiler efficiency and gas-price inflation over the analysis period.
    # `backup_p1_eur_mwh` is kept for backward API compatibility but is no
    # longer used by the default Streamlit workflow.
    backup_useful_p1 = gas_useful_p1
    backup_p1_annual = backup_heat_mwh * backup_useful_p1
    backup_p2_annual = backup_kw * max(0.0, float(backup_p2_eur_kw_year))
    backup_p4_annual = backup_capex / years
    backup_p1 = backup_p1_annual / backup_heat_mwh if backup_heat_mwh > 0.0 else 0.0
    backup_p2 = backup_p2_annual / backup_heat_mwh if backup_heat_mwh > 0.0 else 0.0
    backup_p4 = backup_p4_annual / backup_heat_mwh if backup_heat_mwh > 0.0 else 0.0

    solar_annual_cost = solar_mwh * (solar_p1 + solar_p2 + solar_p4)
    geo_annual_cost = geo_p1_annual + geo_p2_annual + geo_p4_annual
    backup_annual_cost = backup_p1_annual + backup_p2_annual + backup_p4_annual
    delivered_heat_mwh = max(1e-9, pac_heat_mwh + backup_heat_mwh + solar_mwh)
    mix_p1 = (solar_mwh * solar_p1 + pac_heat_mwh * geo_p1 + backup_heat_mwh * backup_p1) / delivered_heat_mwh
    mix_p2 = (solar_mwh * solar_p2 + pac_heat_mwh * geo_p2 + backup_heat_mwh * backup_p2) / delivered_heat_mwh
    mix_p4 = (solar_mwh * solar_p4 + pac_heat_mwh * geo_p4 + backup_heat_mwh * backup_p4) / delivered_heat_mwh
    combined_cost = mix_p1 + mix_p2 + mix_p4

    reference_capex = backup_capex_eur_kw * reference_kw
    reference_p2_annual = reference_kw * max(0.0, float(backup_p2_eur_kw_year))
    reference_p1 = gas_useful_p1
    reference_p2 = reference_p2_annual / reference_mwh if reference_mwh > 0.0 else 0.0
    reference_p4 = reference_capex / (reference_mwh * years) if reference_mwh > 0.0 else 0.0
    reference_cost = reference_p1 + reference_p2 + reference_p4

    p1_p2_p4_df = pd.DataFrame(
        [
            {"Generateur": "Solaire thermique", "Poste": "P1", "EUR/MWh": solar_p1},
            {"Generateur": "Solaire thermique", "Poste": "P2", "EUR/MWh": solar_p2},
            {"Generateur": "Solaire thermique", "Poste": "P4", "EUR/MWh": solar_p4},
            {"Generateur": "Geothermie PAC", "Poste": "P1", "EUR/MWh": geo_p1},
            {"Generateur": "Geothermie PAC", "Poste": "P2", "EUR/MWh": geo_p2},
            {"Generateur": "Geothermie PAC", "Poste": "P4", "EUR/MWh": geo_p4},
            {"Generateur": "Appoint gaz", "Poste": "P1", "EUR/MWh": backup_p1},
            {"Generateur": "Appoint gaz", "Poste": "P2", "EUR/MWh": backup_p2},
            {"Generateur": "Appoint gaz", "Poste": "P4", "EUR/MWh": backup_p4},
            {"Generateur": "Mix ENR", "Poste": "P1", "EUR/MWh": mix_p1},
            {"Generateur": "Mix ENR", "Poste": "P2", "EUR/MWh": mix_p2},
            {"Generateur": "Mix ENR", "Poste": "P4", "EUR/MWh": mix_p4},
            {"Generateur": "Reference 100% gaz", "Poste": "P1", "EUR/MWh": reference_p1},
            {"Generateur": "Reference 100% gaz", "Poste": "P2", "EUR/MWh": reference_p2},
            {"Generateur": "Reference 100% gaz", "Poste": "P4", "EUR/MWh": reference_p4},
        ]
    )
    heat_cost_summary = pd.DataFrame(
        [
            {
                "Generateur": "Solaire thermique",
                "Energie (MWh/an)": solar_mwh,
                "P1 (EUR/MWh)": solar_p1,
                "P2 (EUR/MWh)": solar_p2,
                "P4 (EUR/MWh)": solar_p4,
                "Cout chaleur (EUR/MWh)": solar_p1 + solar_p2 + solar_p4,
            },
            {
                "Generateur": "Geothermie PAC",
                "Energie (MWh/an)": pac_heat_mwh,
                "P1 (EUR/MWh)": geo_p1,
                "P2 (EUR/MWh)": geo_p2,
                "P4 (EUR/MWh)": geo_p4,
                "Cout chaleur (EUR/MWh)": geo_p1 + geo_p2 + geo_p4,
            },
            {
                "Generateur": "Appoint gaz",
                "Energie (MWh/an)": backup_heat_mwh,
                "P1 (EUR/MWh)": backup_p1,
                "P2 (EUR/MWh)": backup_p2,
                "P4 (EUR/MWh)": backup_p4,
                "Cout chaleur (EUR/MWh)": backup_p1 + backup_p2 + backup_p4,
            },
            {
                "Generateur": "Mix ENR",
                "Energie (MWh/an)": delivered_heat_mwh,
                "P1 (EUR/MWh)": mix_p1,
                "P2 (EUR/MWh)": mix_p2,
                "P4 (EUR/MWh)": mix_p4,
                "Cout chaleur (EUR/MWh)": combined_cost,
            },
            {
                "Generateur": "Reference 100% gaz",
                "Energie (MWh/an)": reference_mwh,
                "P1 (EUR/MWh)": reference_p1,
                "P2 (EUR/MWh)": reference_p2,
                "P4 (EUR/MWh)": reference_p4,
                "Cout chaleur (EUR/MWh)": reference_cost,
            },
        ]
    )
    capex_summary = pd.DataFrame(
        [
            {
                "Generateur": "Solaire thermique",
                "CAPEX brut (EUR)": float(solar_economics["capex_eur"]),
                "Aide ADEME (EUR)": float(solar_economics["ademe_aid_eur"]),
                "Autres aides (EUR)": float(solar_economics.get("aid_total_eur", 0.0)) - float(solar_economics["ademe_aid_eur"]),
                "Gain sondes (EUR)": 0.0,
                "CAPEX net (EUR)": float(solar_economics["net_capex_eur"]),
            },
            {
                "Generateur": "Geothermie PAC",
                "CAPEX brut (EUR)": geo_capex,
                "Aide ADEME (EUR)": geo_ademe_aid,
                "Autres aides (EUR)": 0.0,
                "Gain sondes (EUR)": saved_borefield_capex,
                "CAPEX net (EUR)": geo_net_capex,
            },
            {
                "Generateur": "Appoint gaz",
                "CAPEX brut (EUR)": backup_capex,
                "Aide ADEME (EUR)": 0.0,
                "Autres aides (EUR)": 0.0,
                "Gain sondes (EUR)": 0.0,
                "CAPEX net (EUR)": backup_capex,
            },
            {
                "Generateur": "Reference 100% gaz",
                "CAPEX brut (EUR)": reference_capex,
                "Aide ADEME (EUR)": 0.0,
                "Autres aides (EUR)": 0.0,
                "Gain sondes (EUR)": 0.0,
                "CAPEX net (EUR)": reference_capex,
            },
        ]
    )
    cost_bars = p1_p2_p4_df.rename(columns={"Generateur": "Vecteur", "EUR/MWh": "Valeur"})
    summary = pd.DataFrame(
        [
            ("Puissance PAC retenue", pac_kw, "kW"),
            ("Lineaire de sondes plein", full_length_m, "ml"),
            ("Lineaire de sondes retenu", length_m, "ml"),
            ("Lineaire de sondes economise", saved_length_m, "ml"),
            ("CAPEX sondes economise", saved_borefield_capex, "EUR"),
            ("P2/P3 geothermie", geo_p2_unit, "EUR/kW.an"),
            ("CAPEX PAC geothermie", geothermal_pac_capex_eur_kw * pac_kw, "EUR"),
            ("CAPEX sondes", geothermal_borefield_capex_eur_m * length_m, "EUR"),
            ("Aide ADEME geothermie", geo_ademe_aid, "EUR"),
            ("CAPEX geothermie net", geo_net_capex, "EUR"),
            ("CAPEX appoint", backup_capex, "EUR"),
            ("P2 appoint gaz", backup_p2_annual, "EUR/an"),
            ("P2 reference gaz", reference_p2_annual, "EUR/an"),
        ],
        columns=["Grandeur", "Valeur", "Unite"],
    )
    return {
        "cost_bars": cost_bars,
        "p1_p2_p4": p1_p2_p4_df,
        "heat_cost_summary": heat_cost_summary,
        "capex_summary": capex_summary,
        "summary": summary,
        "combined_heat_cost_eur_mwh": combined_cost,
        "geo_heat_cost_eur_mwh": geo_p1 + geo_p2 + geo_p4,
        "backup_heat_cost_eur_mwh": backup_p1 + backup_p2 + backup_p4,
        "reference_heat_cost_eur_mwh": reference_cost,
        "mix_p1_eur_mwh": mix_p1,
        "mix_p2_eur_mwh": mix_p2,
        "mix_p4_eur_mwh": mix_p4,
        "reference_p1_eur_mwh": reference_p1,
        "reference_p2_eur_mwh": reference_p2,
        "reference_p4_eur_mwh": reference_p4,
        "reference_capex_eur": reference_capex,
        "geo_p2_unit_eur_kw_year": geo_p2_unit,
        "geo_capex_eur": geo_capex,
        "geo_ademe_aid_eur": geo_ademe_aid,
        "geo_net_capex_eur": geo_net_capex,
        "full_borefield_length_m": full_length_m,
        "economic_borefield_length_m": length_m,
        "saved_borefield_length_m": saved_length_m,
        "saved_borefield_capex_eur": saved_borefield_capex,
        "backup_capex_eur": backup_capex,
    }
