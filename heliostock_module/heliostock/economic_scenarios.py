from __future__ import annotations

import pandas as pd

from .economics import compute_heat_costs, compute_solar_thermal_economics
from .scenario_outputs import ScenarioEconomicsConfig


def _reference_gas_trajectory_from(trajectory_df: pd.DataFrame) -> pd.DataFrame:
    reference_df = trajectory_df.copy()
    reference_df["Solaire HT (MWh)"] = 0.0
    reference_df["Injection solaire BTES (MWh)"] = 0.0
    reference_df["Chaleur PAC BT (MWh)"] = 0.0
    reference_df["Appoint gaz HT (MWh)"] = reference_df["E utile HT (MWh)"]
    reference_df["Appoint gaz BT (MWh)"] = reference_df["E utile BT (MWh)"]
    reference_df["Appoint gaz total (MWh)"] = reference_df["E utile totale (MWh)"]
    reference_df["Electricite PAC (MWh)"] = 0.0
    reference_df["COP moyen"] = 0.0
    reference_df["SPF PAC complet"] = 0.0
    reference_df["Couverture PAC BT (%)"] = 0.0
    reference_df["Heures equivalentes PAC BT"] = 0.0
    reference_df["T_source_PAC_min (C)"] = 0.0
    reference_df["T_source_PAC_moy (C)"] = 0.0
    reference_df["T_source_PAC_pour_COP_min (C)"] = 0.0
    reference_df["T_fluide_injection_max (C)"] = 0.0
    reference_df["q_extraction_W_m_max"] = 0.0
    reference_df["q_injection_W_m_max"] = 0.0
    reference_df["Heures sous Tmin GMI"] = 0
    reference_df["Heures sur Tmax GMI"] = 0
    reference_df["Conformite GMI"] = True
    reference_df["Heures limite source"] = 0
    reference_df["BT non couvert limite source (MWh)"] = 0.0
    reference_df["Taux EnR (%)"] = 0.0
    return reference_df


def _unit_cost(heat_costs: dict[str, float | pd.DataFrame], generator: str, poste: str) -> float:
    df = heat_costs["p1_p2_p4"]
    assert isinstance(df, pd.DataFrame)
    if df.empty or not {"Generateur", "Poste", "EUR/MWh"}.issubset(df.columns):
        return 0.0
    match = df[(df["Generateur"] == generator) & (df["Poste"] == poste)]
    return float(match["EUR/MWh"].iloc[0]) if not match.empty else 0.0


def _multiyear_heat_cost(
    *,
    trajectory_df: pd.DataFrame,
    heat_costs: dict[str, float | pd.DataFrame],
    economics: ScenarioEconomicsConfig,
    capex_net_eur: float,
    reference: bool = False,
) -> dict[str, float]:
    """Compute the multiannual heat cost from annual technical trajectories."""

    gas_inflation = max(0.0, float(economics.reference_energy_inflation_pct)) / 100.0
    gas_useful_year_1 = max(0.0, economics.reference_energy_cost_eur_mwh) / max(1e-9, economics.eta_appoint_eco)
    geo_p1_eur_mwh = max(0.0, float(economics.electricity_cost_eur_mwh))
    solar_p1_eur_mwh = _unit_cost(heat_costs, "Solaire thermique", "P1")
    p2_annual = 0.0
    capex_df = heat_costs.get("capex_summary", pd.DataFrame())
    p_table = heat_costs.get("p1_p2_p4", pd.DataFrame())
    if isinstance(p_table, pd.DataFrame) and not p_table.empty:
        if reference:
            delivered_ref = float(trajectory_df["E utile totale (MWh)"].mean())
            p2_annual = float(heat_costs["reference_p2_eur_mwh"]) * delivered_ref
        else:
            solar_p2_total = float(heat_costs.get("solar_p2_total_annual_eur", 0.0))
            if solar_p2_total > 0.0:
                p2_annual = (
                    solar_p2_total
                    + float(heat_costs.get("geo_p2_base_annual_eur", 0.0))
                    + _unit_cost(heat_costs, "Appoint gaz", "P2") * float(trajectory_df["Appoint gaz total (MWh)"].mean())
                )
            else:
                p2_annual = 0.0
                for generator in ["Solaire thermique", "Geothermie PAC", "Appoint gaz"]:
                    match = p_table[(p_table["Generateur"] == generator) & (p_table["Poste"] == "P2")]
                    if not match.empty:
                        if generator == "Solaire thermique":
                            energy = trajectory_df["Solaire HT (MWh)"].mean()
                        elif generator == "Geothermie PAC":
                            energy = trajectory_df["Chaleur PAC BT (MWh)"].mean()
                        else:
                            energy = trajectory_df["Appoint gaz total (MWh)"].mean()
                        p2_annual += float(match["EUR/MWh"].iloc[0]) * float(energy)
    if isinstance(capex_df, pd.DataFrame) and not capex_df.empty:
        pass

    total_cost = max(0.0, capex_net_eur)
    total_useful = 0.0
    p1_total_nominal = 0.0
    p2_total_nominal = 0.0
    p4_total_nominal = 0.0
    for _, row in trajectory_df.iterrows():
        year = int(row["Annee"])
        gas_price = gas_useful_year_1 * ((1.0 + gas_inflation) ** max(0, year - 1))
        if reference:
            p1 = float(row["E utile totale (MWh)"]) * gas_price
        else:
            p1 = (
                float(row["Appoint gaz total (MWh)"]) * gas_price
                + float(row["Electricite PAC (MWh)"]) * geo_p1_eur_mwh
                + float(row["Solaire HT (MWh)"]) * solar_p1_eur_mwh
            )
        p2 = p2_annual
        p4 = max(0.0, capex_net_eur) / max(1, int(economics.analysis_years))
        total_cost += p1 + p2
        total_useful += float(row["E utile totale (MWh)"])
        p1_total_nominal += p1
        p2_total_nominal += p2
        p4_total_nominal += p4
    return {
        "multiyear_heat_cost_eur_mwh": total_cost / max(1e-9, total_useful),
        "p1_annual_eur": p1_total_nominal / max(1, len(trajectory_df)),
        "p2_annual_eur": p2_total_nominal / max(1, len(trajectory_df)),
        "p4_annual_eur": p4_total_nominal / max(1, len(trajectory_df)),
        "p1_cumulative_eur": p1_total_nominal,
        "p2_cumulative_eur": p2_total_nominal,
        "p4_cumulative_eur": p4_total_nominal,
        "backup_gas_cumulative_mwh": float(trajectory_df["Appoint gaz total (MWh)"].sum()),
        "pac_electricity_cumulative_mwh": float(trajectory_df["Electricite PAC (MWh)"].sum()),
    }


def _zero_solar_economics(economics: ScenarioEconomicsConfig) -> dict[str, float | pd.DataFrame]:
    return compute_solar_thermal_economics(
        surface_m2=0.0,
        annual_solar_valued_mwh=0.0,
        reference_energy_cost_eur_mwh=economics.reference_energy_cost_eur_mwh,
        reference_energy_inflation_rate=economics.reference_energy_inflation_pct / 100.0,
        analysis_years=int(economics.analysis_years),
        eta_appoint=economics.eta_appoint_eco,
        auxiliary_electricity_ratio=economics.auxiliary_electricity_ratio_pct / 100.0,
        electricity_cost_eur_mwh=economics.electricity_cost_eur_mwh,
        maintenance_cost_eur_m2_year=economics.maintenance_cost_eur_m2_year,
        ademe_eur_mwh_year=economics.ademe_eur_mwh_year,
        other_public_aid_eur=0.0,
    )


def _scenario_heat_costs(
    *,
    metrics: dict[str, float],
    economics: ScenarioEconomicsConfig,
    solar_economics: dict[str, float | pd.DataFrame],
    solar_mwh: float,
    pac_power_kw: float,
    borefield_length_m: float,
    full_borefield_length_m: float,
    reference_heat_mwh: float,
    reference_power_kw: float,
) -> dict[str, float | pd.DataFrame]:
    return compute_heat_costs(
        solar_economics=solar_economics,
        annual_solar_mwh=solar_mwh,
        annual_pac_heat_mwh=metrics["pac_heat_mwh"],
        annual_pac_electricity_mwh=metrics["pac_electricity_mwh"],
        pac_power_kw=pac_power_kw,
        borefield_length_m=borefield_length_m,
        full_borefield_length_m=full_borefield_length_m,
        annual_backup_heat_mwh=metrics["backup_total_mwh"],
        backup_power_kw=metrics["backup_power_kw"],
        reference_heat_mwh=reference_heat_mwh,
        reference_power_kw=reference_power_kw,
        analysis_years=int(economics.analysis_years),
        gas_reference_p1_eur_mwh_pci=economics.reference_energy_cost_eur_mwh,
        gas_reference_efficiency=economics.eta_appoint_eco,
        gas_reference_inflation_rate=economics.reference_energy_inflation_pct / 100.0,
        geothermal_p1_eur_mwh=economics.electricity_cost_eur_mwh,
        backup_p2_eur_kw_year=economics.backup_p2_eur_kw_year,
    )


def _capex_net_total(heat_costs: dict[str, float | pd.DataFrame], generators: list[str]) -> float:
    df = heat_costs["capex_summary"]
    assert isinstance(df, pd.DataFrame)
    return float(df[df["Generateur"].isin(generators)]["CAPEX net (EUR)"].sum())


def _comparison_row(
    *,
    name: str,
    heat_costs: dict[str, float | pd.DataFrame],
    metrics: dict[str, float],
    delivered_mwh: float,
    borefield_length_m: float,
    saved_borefield_length_m: float,
    capex_net_eur: float,
    reference: bool = False,
    solar_area_m2: float,
) -> dict[str, float | str]:
    delivered = max(1e-9, delivered_mwh)
    if reference:
        p1 = float(heat_costs["reference_p1_eur_mwh"])
        p2 = float(heat_costs["reference_p2_eur_mwh"])
        p4 = float(heat_costs["reference_p4_eur_mwh"])
        cost = float(heat_costs["reference_heat_cost_eur_mwh"])
        backup_mwh = delivered_mwh
        elec_mwh = 0.0
        cop = 0.0
        ren = 0.0
        solar_cov = 0.0
        pac_cov = 0.0
        line = 0.0
        saved = 0.0
        p1_solar = 0.0
        p1_geo = 0.0
        p1_backup = p1 * delivered
        p2_solar = 0.0
        p2_geo = 0.0
        p2_backup = p2 * delivered
        p4_solar = 0.0
        p4_geo = 0.0
        p4_backup = p4 * delivered
    else:
        p1 = float(heat_costs["mix_p1_eur_mwh"])
        p2 = float(heat_costs["mix_p2_eur_mwh"])
        p4 = float(heat_costs["mix_p4_eur_mwh"])
        cost = float(heat_costs["combined_heat_cost_eur_mwh"])
        backup_mwh = metrics["backup_total_mwh"]
        elec_mwh = metrics["pac_electricity_mwh"]
        cop = metrics["mean_cop"]
        ren = metrics["global_ren_rate"]
        solar_cov = metrics["solar_ht_coverage"]
        pac_cov = metrics["pac_bt_coverage"]
        line = borefield_length_m
        saved = saved_borefield_length_m
        p1_solar = _unit_cost(heat_costs, "Solaire thermique", "P1") * metrics["solar_ht_mwh"]
        p1_geo = _unit_cost(heat_costs, "Geothermie PAC", "P1") * metrics["pac_heat_mwh"]
        p1_backup = _unit_cost(heat_costs, "Appoint gaz", "P1") * metrics["backup_total_mwh"]
        p2_solar = float(
            heat_costs.get(
                "solar_p2_ht_annual_eur",
                _unit_cost(heat_costs, "Solaire thermique", "P2") * metrics["solar_ht_mwh"],
            )
        )
        p2_geo = float(
            heat_costs.get(
                "geo_p2_base_annual_eur",
                _unit_cost(heat_costs, "Geothermie PAC", "P2") * metrics["pac_heat_mwh"],
            )
        ) + float(heat_costs.get("solar_p2_recharge_annual_eur", 0.0))
        p2_backup = _unit_cost(heat_costs, "Appoint gaz", "P2") * metrics["backup_total_mwh"]
        p4_solar = _unit_cost(heat_costs, "Solaire thermique", "P4") * metrics["solar_ht_mwh"]
        p4_geo = _unit_cost(heat_costs, "Geothermie PAC", "P4") * metrics["pac_heat_mwh"]
        p4_backup = _unit_cost(heat_costs, "Appoint gaz", "P4") * metrics["backup_total_mwh"]
    return {
        "Scenario": name,
        "Cout chaleur global (EUR/MWh)": cost,
        "CAPEX net (EUR)": capex_net_eur,
        "P1 annuel (EUR/an)": p1 * delivered,
        "P1 solaire (EUR/an)": p1_solar,
        "P1 geothermie (EUR/an)": p1_geo,
        "P1 appoint gaz (EUR/an)": p1_backup,
        "P2 annuel (EUR/an)": p2 * delivered,
        "P2 solaire (EUR/an)": p2_solar,
        "P2 geothermie (EUR/an)": p2_geo,
        "P2 appoint gaz (EUR/an)": p2_backup,
        "P4 annuel (EUR/an)": p4 * delivered,
        "P4 solaire (EUR/an)": p4_solar,
        "P4 geothermie (EUR/an)": p4_geo,
        "P4 appoint gaz (EUR/an)": p4_backup,
        "Appoint gaz (MWh/an)": backup_mwh,
        "Electricite PAC (MWh/an)": elec_mwh,
        "COP PAC moyen": cop,
        "Taux EnR global (%)": ren * 100.0,
        "Couverture solaire HT (%)": solar_cov * 100.0,
        "Couverture PAC BT (%)": pac_cov * 100.0,
        "Lineaire sondes (ml)": line,
        "Lineaire sondes economise (ml)": saved,
        "Surface solaire (m2)": solar_area_m2,
    }
