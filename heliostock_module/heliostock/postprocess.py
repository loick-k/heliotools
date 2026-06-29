from __future__ import annotations

from dataclasses import asdict

import pandas as pd

def _hourly_results_to_dataframe(results) -> pd.DataFrame:
    df = pd.DataFrame([asdict(r) for r in results])
    if df.empty:
        return df

    if "simulation_year" not in df.columns:
        df["simulation_year"] = 1
    df["Heure simulation"] = range(len(df))
    df["Jour simulation"] = df["Heure simulation"] / 24.0
    df["Heure annee"] = df.groupby("simulation_year").cumcount()
    df["Jour annee"] = df["Heure annee"] / 24.0
    df["Puissance besoin HT (kW)"] = df["demand_ht_kwh"]
    df["Puissance besoin BT (kW)"] = df["demand_bt_kwh"]
    df["Puissance besoin total (kW)"] = df["demand_ht_kwh"] + df["demand_bt_kwh"]
    df["Puissance prechauffage HT solaire (kW)"] = df["solar_ht_direct_kwh"]
    df["Puissance appoint HT (kW)"] = df["unmet_ht_kwh"]
    df["Puissance BT PAC (kW)"] = df["heat_bt_from_pac_kwh"]
    df["Puissance appoint BT (kW)"] = df["unmet_bt_kwh"]
    df["Puissance chaleur utile totale (kW)"] = df["solar_ht_direct_kwh"] + df["heat_bt_from_pac_kwh"]
    return df


def _multiyear_btes_summary(results_df: pd.DataFrame, *, t_min_c: float) -> pd.DataFrame:
    rows = []
    if results_df.empty:
        return pd.DataFrame(rows)

    for (year, month), group in results_df.groupby(["simulation_year", "month"], sort=True):
        elec_compressor = float(group["electricity_compressor_kwh"].sum())
        elec_total = float(group["electricity_pac_total_kwh"].sum())
        heat_pac = float(group["heat_bt_from_pac_kwh"].sum())
        rows.append(
            {
                "Annee": int(year),
                "Mois index": (int(year) - 1) * 12 + int(month),
                "Mois": f"A{int(year):02d}-{int(month):02d}",
                "T champ fin (C)": float(group["btes_temp_end_c"].iloc[-1]),
                "T champ min (C)": float(group["btes_temp_end_c"].min()),
                "T champ max (C)": float(group["btes_temp_end_c"].max()),
                "E champ fin (MWh)": float(group["btes_energy_end_kwh"].iloc[-1]) / 1000.0,
                "Injection BTES (MWh)": float(group["solar_to_btes_kwh"].sum()) / 1000.0,
                "Extraction PAC (MWh)": float(group["btes_extracted_by_pac_kwh"].sum()) / 1000.0,
                "Pertes champ (MWh)": float(group["btes_loss_to_ground_kwh"].sum()) / 1000.0,
                "Recharge naturelle (MWh)": float(group["btes_natural_recharge_kwh"].sum()) / 1000.0,
                "COP machine": heat_pac / elec_compressor if elec_compressor > 0 else 0.0,
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0 else 0.0,
                "Heures a Tmin": int((group["btes_temp_end_c"] <= t_min_c + 1e-6).sum()),
            }
        )
    return pd.DataFrame(rows)


def _annual_hourly_summary(results_df: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("Besoin HT air -> 60 C", results_df["demand_ht_kwh"].sum()),
        ("Charge ballon solaire", results_df["solar_ht_to_buffer_kwh"].sum()),
        ("Prechauffage HT solaire via ballon", results_df["solar_ht_from_buffer_kwh"].sum()),
        ("Pertes ballon solaire", results_df["solar_ht_buffer_loss_kwh"].sum()),
        ("Appoint HT complement 60 C", results_df["unmet_ht_kwh"].sum()),
        ("Injection solaire BTES", results_df["solar_to_btes_kwh"].sum()),
        ("Solaire non valorise", results_df["solar_not_used_kwh"].sum()),
        ("Besoin BT air -> 25 C", results_df["demand_bt_kwh"].sum()),
        ("Chaleur BT livree par PAC", results_df["heat_bt_from_pac_kwh"].sum()),
        ("Chaleur extraite du champ par PAC", results_df["btes_extracted_by_pac_kwh"].sum()),
        ("Electricite compresseur PAC", results_df["electricity_compressor_kwh"].sum()),
        ("Forfait pompes + auxiliaires PAC", results_df["electricity_pac_auxiliaries_kwh"].sum()),
        ("Veille/regulation PAC", results_df["electricity_standby_kwh"].sum()),
        ("Electricite totale PAC", results_df["electricity_pac_total_kwh"].sum()),
        ("Electricite totale systeme", results_df["electricity_system_total_kwh"].sum()),
        ("Appoint BT", results_df["unmet_bt_kwh"].sum()),
        ("Pertes champ vers sol", results_df["btes_loss_to_ground_kwh"].sum()),
        ("Recharge naturelle depuis sol", results_df["btes_natural_recharge_kwh"].sum()),
    ]
    out = pd.DataFrame(rows, columns=["Poste", "kWh/an"])
    out["MWh/an"] = out["kWh/an"] / 1000.0
    return out


def _hourly_by_month_summary(results_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for month, group in results_df.groupby("month", sort=True):
        elec_compressor = group["electricity_compressor_kwh"].sum()
        elec_total = group["electricity_pac_total_kwh"].sum()
        demand_ht = group["demand_ht_kwh"].sum()
        rows.append(
            {
                "Mois": f"{int(month):02d} {pd.Timestamp(2024, int(month), 1).strftime('%b')}",
                "Besoin HT (MWh)": demand_ht / 1000.0,
                "Charge ballon solaire (MWh)": group["solar_ht_to_buffer_kwh"].sum() / 1000.0,
                "Prechauffage HT solaire (MWh)": group["solar_ht_from_buffer_kwh"].sum() / 1000.0,
                "Appoint HT (MWh)": group["unmet_ht_kwh"].sum() / 1000.0,
                "Taux couverture solaire HT (%)": group["solar_ht_from_buffer_kwh"].sum() / max(1e-9, demand_ht) * 100.0,
                "Injection BTES (MWh)": group["solar_to_btes_kwh"].sum() / 1000.0,
                "Solaire non valorise (MWh)": group["solar_not_used_kwh"].sum() / 1000.0,
                "Besoin BT (MWh)": group["demand_bt_kwh"].sum() / 1000.0,
                "BT PAC (MWh)": group["heat_bt_from_pac_kwh"].sum() / 1000.0,
                "Extraction champ PAC (MWh)": group["btes_extracted_by_pac_kwh"].sum() / 1000.0,
                "Elec compresseur PAC (MWh)": elec_compressor / 1000.0,
                "Elec totale PAC (MWh)": elec_total / 1000.0,
                "Appoint BT (MWh)": group["unmet_bt_kwh"].sum() / 1000.0,
                "Pertes champ vers sol (MWh)": group["btes_loss_to_ground_kwh"].sum() / 1000.0,
                "Recharge naturelle sol (MWh)": group["btes_natural_recharge_kwh"].sum() / 1000.0,
                "COP machine": group["heat_bt_from_pac_kwh"].sum() / max(1e-9, elec_compressor),
                "SPF PAC complet": group["heat_bt_from_pac_kwh"].sum() / max(1e-9, elec_total),
                "T ballon fin (C)": group["solar_ht_buffer_temp_end_c"].iloc[-1],
                "T champ fin (C)": group["btes_temp_end_c"].iloc[-1],
                "Rendement capteur ballon moyen": group["collector_eff_ht"].mean(),
            }
        )
    return pd.DataFrame(rows)


def _load_duration_dataframe(results_df: pd.DataFrame, sort_by: str = "Besoin total") -> pd.DataFrame:
    sort_columns = {
        "Besoin HT": "Puissance besoin HT (kW)",
        "Besoin BT": "Puissance besoin BT (kW)",
        "Besoin total": "Puissance besoin total (kW)",
        "Prechauffage HT solaire": "Puissance prechauffage HT solaire (kW)",
        "BT PAC": "Puissance BT PAC (kW)",
    }
    sort_column = sort_columns.get(sort_by, "Puissance besoin total (kW)")
    sorted_df = results_df.sort_values(sort_column, ascending=False).reset_index(drop=True).copy()
    sorted_df["Heure triee"] = sorted_df.index + 1

    rows = []
    series = {
        "Besoin HT": "Puissance besoin HT (kW)",
        "Prechauffage HT solaire": "Puissance prechauffage HT solaire (kW)",
        "Appoint HT": "Puissance appoint HT (kW)",
        "Besoin BT": "Puissance besoin BT (kW)",
        "BT PAC geothermie": "Puissance BT PAC (kW)",
        "Appoint BT": "Puissance appoint BT (kW)",
        "Besoin total": "Puissance besoin total (kW)",
        "Chaleur utile solaire+PAC": "Puissance chaleur utile totale (kW)",
    }
    for label, column in series.items():
        for _, row in sorted_df.iterrows():
            rows.append(
                {
                    "Heure triee": int(row["Heure triee"]),
                    "Courbe": label,
                    "Puissance (kW)": float(row[column]),
                    "Heure annee": int(row["Heure annee"]),
                    "Mois": int(row["month"]),
                    "Jour": int(row["day"]),
                    "Heure EPW": int(row["hour"]),
                    "Tair (C)": float(row["tair_c"]),
                    "Tri": sort_by,
                }
            )
    return pd.DataFrame(rows)


def _stacked_coverage_duration_dataframe(results_df: pd.DataFrame, *, mode: str) -> pd.DataFrame:
    if mode == "HT":
        sort_column = "Puissance besoin HT (kW)"
        components = [
            ("Solaire thermique", "Puissance prechauffage HT solaire (kW)", 1),
            ("Appoint HT", "Puissance appoint HT (kW)", 2),
        ]
    elif mode == "BT":
        sort_column = "Puissance besoin BT (kW)"
        components = [
            ("Géothermie PAC", "Puissance BT PAC (kW)", 1),
            ("Appoint BT", "Puissance appoint BT (kW)", 2),
        ]
    else:
        raise ValueError("mode doit valoir HT ou BT")

    sorted_df = results_df.sort_values(sort_column, ascending=False).reset_index(drop=True).copy()
    sorted_df["Heure triee"] = sorted_df.index + 1
    rows = []
    for _, row in sorted_df.iterrows():
        for label, column, order in components:
            rows.append(
                {
                    "Heure triee": int(row["Heure triee"]),
                    "Poste": label,
                    "Ordre": order,
                    "Puissance (kW)": float(row[column]),
                    "Mois": int(row["month"]),
                    "Jour": int(row["day"]),
                    "Heure EPW": int(row["hour"]),
                    "Tair (C)": float(row["tair_c"]),
                }
            )
    return pd.DataFrame(rows)


def _melt_monthly(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return df[["Mois", *columns]].melt(
        id_vars=["Mois"],
        value_vars=columns,
        var_name="Poste",
        value_name="Valeur",
    )


def _mean_cop(results_df: pd.DataFrame) -> float:
    heat = float(results_df["heat_bt_from_pac_kwh"].sum())
    electricity = float(results_df["electricity_compressor_kwh"].sum())
    return heat / electricity if electricity > 0 else 0.0

