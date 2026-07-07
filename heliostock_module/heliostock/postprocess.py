from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

import pandas as pd


def btes_efficiency_indicator(extracted_kwh: float, injected_kwh: float) -> float | None:
    """Return eta_BTES = useful ground extraction / solar injection.

    This is a storage restitution indicator only. It is not a system efficiency
    and is not comparable to the heat-pump COP.
    """

    injected = max(0.0, float(injected_kwh))
    if injected <= 1e-9:
        return None
    return max(0.0, float(extracted_kwh)) / injected


def sign_change_diagnostics(q_net_w_m: Iterable[float]) -> dict[str, float | int | str | bool]:
    """Diagnose extraction/injection alternance from signed ground loads.

    Sign convention:
    - q_net_W_m > 0 means heat extraction from ground by the heat pump;
    - q_net_W_m < 0 means solar injection into the ground.
    """

    signs: list[int] = []
    for value in q_net_w_m:
        q = float(value)
        if q > 1e-9:
            signs.append(1)
        elif q < -1e-9:
            signs.append(-1)
        else:
            signs.append(0)

    non_zero = [sign for sign in signs if sign != 0]
    sign_changes = 0
    extraction_to_injection = 0
    injection_to_extraction = 0
    previous = 0
    extraction_sequences = 0
    injection_sequences = 0
    for sign in non_zero:
        if previous == 0:
            if sign > 0:
                extraction_sequences += 1
            else:
                injection_sequences += 1
        elif sign != previous:
            sign_changes += 1
            if previous > 0 and sign < 0:
                extraction_to_injection += 1
                injection_sequences += 1
            elif previous < 0 and sign > 0:
                injection_to_extraction += 1
                extraction_sequences += 1
        previous = sign

    variability = sign_changes / max(1, len(non_zero))
    if variability >= 0.10:
        level = "forte"
    elif variability >= 0.02:
        level = "moderee"
    else:
        level = "faible"
    warning = (
        "Le profil thermique présente de fortes alternances injection/extraction. "
        "Les résultats long terme dépendent fortement de la méthode d'agrégation des charges thermiques."
        if level == "forte"
        else ""
    )
    return {
        "hours_total": len(signs),
        "hours_non_zero": len(non_zero),
        "sign_changes": sign_changes,
        "extraction_to_injection_changes": extraction_to_injection,
        "injection_to_extraction_changes": injection_to_extraction,
        "extraction_sequences": extraction_sequences,
        "injection_sequences": injection_sequences,
        "seasonal_load_variability_index": variability,
        "alternance_level": level,
        "strong_alternance": level == "forte",
        "warning": warning,
    }


def classify_geo_field_mode(ratio_injection_extraction: float) -> str:
    ratio = max(0.0, float(ratio_injection_extraction))
    if ratio < 0.10:
        return "GSHP_dominant"
    if ratio <= 0.50:
        return "solar_recharged_borefield"
    return "BTES_like"


def geo_field_mode_comment(mode: str) -> str:
    comments = {
        "GSHP_dominant": "Le champ fonctionne surtout comme une source géothermique de PAC, avec peu de recharge solaire.",
        "solar_recharged_borefield": "Le champ fonctionne plutôt comme un champ géothermique rechargé par solaire.",
        "BTES_like": "Le champ se rapproche d'un fonctionnement BTES intersaisonnier, avec injection et extraction du même ordre de grandeur.",
    }
    return comments.get(str(mode), "")


def surface_insulation_warning(
    *,
    depth_m: float,
    spacing_m: float,
    injected_kwh: float,
    extracted_kwh: float,
    surface_insulation_considered: bool,
) -> str:
    if surface_insulation_considered:
        return ""
    ratio = max(0.0, float(injected_kwh)) / max(1e-9, max(0.0, float(extracted_kwh)))
    dense_field = float(spacing_m) > 0.0 and float(spacing_m) <= 6.0
    if float(depth_m) < 50.0 and dense_field and float(injected_kwh) > 1e-6 and ratio >= 0.10:
        return (
            "Pour un vrai BTES peu profond avec stockage intersaisonnier, les pertes vers la surface et "
            "l'isolation supérieure peuvent influencer fortement la température du stockage. "
            "HelioStock ne les modélise pas explicitement."
        )
    return ""


def btes_load_diagnostics_from_dataframe(
    results_df: pd.DataFrame,
    *,
    simulation_years: int,
    depth_m: float,
    spacing_m: float,
    surface_insulation_considered: bool,
) -> dict[str, float | int | str | bool | None]:
    if results_df.empty:
        return {
            "hours_total": 0,
            "simulation_years": int(simulation_years),
            "extracted_ground_kwh": 0.0,
            "injected_btes_kwh": 0.0,
            "ratio_injection_extraction": 0.0,
            "eta_btes": None,
            "geo_field_mode": "GSHP_dominant",
            "geo_field_mode_comment": geo_field_mode_comment("GSHP_dominant"),
            "surface_insulation_warning": "",
        }
    extracted = float(results_df.get("btes_extracted_by_pac_kwh", pd.Series(dtype=float)).sum())
    injected = float(results_df.get("solar_to_btes_kwh", pd.Series(dtype=float)).sum())
    ratio = injected / max(1e-9, extracted)
    mode = classify_geo_field_mode(ratio)
    q_net = results_df["q_net_W_m"] if "q_net_W_m" in results_df else results_df.get("q_net_w_m", pd.Series(dtype=float))
    diagnostics = dict(sign_change_diagnostics(q_net))
    diagnostics.update(
        {
            "simulation_years": int(simulation_years),
            "extracted_ground_kwh": extracted,
            "injected_btes_kwh": injected,
            "ratio_injection_extraction": ratio,
            "eta_btes": btes_efficiency_indicator(extracted, injected),
            "geo_field_mode": mode,
            "geo_field_mode_comment": geo_field_mode_comment(mode),
            "surface_insulation_warning": surface_insulation_warning(
                depth_m=depth_m,
                spacing_m=spacing_m,
                injected_kwh=injected,
                extracted_kwh=extracted,
                surface_insulation_considered=surface_insulation_considered,
            ),
        }
    )
    return diagnostics


def btes_load_diagnostics_from_results(
    results,
    *,
    simulation_years: int,
    depth_m: float,
    spacing_m: float,
    surface_insulation_considered: bool,
) -> dict[str, float | int | str | bool | None]:
    rows = list(results)
    if not rows:
        return {
            "hours_total": 0,
            "simulation_years": int(simulation_years),
            "extracted_ground_kwh": 0.0,
            "injected_btes_kwh": 0.0,
            "ratio_injection_extraction": 0.0,
            "eta_btes": None,
            "geo_field_mode": "GSHP_dominant",
            "geo_field_mode_comment": geo_field_mode_comment("GSHP_dominant"),
            "surface_insulation_warning": "",
        }
    extracted = sum(float(row.btes_extracted_by_pac_kwh) for row in rows)
    injected = sum(float(row.solar_to_btes_kwh) for row in rows)
    ratio = injected / max(1e-9, extracted)
    mode = classify_geo_field_mode(ratio)
    diagnostics = dict(sign_change_diagnostics(row.q_net_w_m for row in rows))
    diagnostics.update(
        {
            "simulation_years": int(simulation_years),
            "extracted_ground_kwh": extracted,
            "injected_btes_kwh": injected,
            "ratio_injection_extraction": ratio,
            "eta_btes": btes_efficiency_indicator(extracted, injected),
            "geo_field_mode": mode,
            "geo_field_mode_comment": geo_field_mode_comment(mode),
            "surface_insulation_warning": surface_insulation_warning(
                depth_m=depth_m,
                spacing_m=spacing_m,
                injected_kwh=injected,
                extracted_kwh=extracted,
                surface_insulation_considered=surface_insulation_considered,
            ),
        }
    )
    return diagnostics


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
    df["T_paroi_forage_C"] = df["t_borehole_wall_c"]
    df["T_source_PAC_C"] = df["t_source_pac_c"]
    df["T_source_PAC_pour_COP_C"] = df["t_source_pac_for_cop_c"]
    df["T_source_PAC_fin_heure_C"] = df["T_source_PAC_C"]
    df["T_paroi_forage_fin_heure_C"] = df["T_paroi_forage_C"]
    df["T_evaporateur_PAC_C"] = df["t_evaporator_pac_c"]
    df["T_fluide_injection_C"] = df["t_fluide_injection_c"]
    df["T_fluide_entree_echangeur_geo_C"] = df["t_fluide_entree_echangeur_geo_c"]
    df["q_extraction_W_m"] = df["q_extraction_w_m"]
    df["q_injection_W_m"] = df["q_injection_w_m"]
    df["q_injection_signee_W_m"] = df["q_injection_signed_w_m"]
    df["q_net_W_m"] = df["q_net_w_m"]
    df["Limite_temperature_source"] = df["source_temp_limited"]
    df["BT_non_couvert_limite_source_kWh"] = df["source_temp_unmet_bt_kwh"]
    return df


def _multiyear_btes_summary(
    results_df: pd.DataFrame,
    *,
    t_min_c: float,
    gmi_t_min_c: float = -3.0,
    gmi_t_max_c: float = 40.0,
    gmi_check_enabled: bool = True,
) -> pd.DataFrame:
    rows = []
    if results_df.empty:
        return pd.DataFrame(rows)

    for (year, month), group in results_df.groupby(["simulation_year", "month"], sort=True):
        elec_compressor = float(group["electricity_compressor_kwh"].sum())
        elec_total = float(group["electricity_pac_total_kwh"].sum())
        heat_pac = float(group["heat_bt_from_pac_kwh"].sum())
        extracted = float(group["btes_extracted_by_pac_kwh"].sum())
        injected = float(group["solar_to_btes_kwh"].sum())
        sign_diag = sign_change_diagnostics(group["q_net_W_m"])
        rows.append(
            {
                "Annee": int(year),
                "Mois index": (int(year) - 1) * 12 + int(month),
                "Mois": f"A{int(year):02d}-{int(month):02d}",
                "T source PAC fin (C)": float(group["T_source_PAC_C"].iloc[-1]),
                "T source PAC min (C)": float(group["T_source_PAC_C"].min()),
                "T source PAC max (C)": float(group["T_source_PAC_C"].max()),
                "T source PAC moyenne (C)": float(group["T_source_PAC_C"].mean()),
                "T source PAC pour COP min (C)": float(group["T_source_PAC_pour_COP_C"].min()),
                "T source PAC pour COP moyenne (C)": float(group["T_source_PAC_pour_COP_C"].mean()),
                "T fluide entree echangeur geo min (C)": float(group["T_fluide_entree_echangeur_geo_C"].min()),
                "T fluide injection max (C)": float(group["T_fluide_injection_C"].max()),
                "T paroi forage fin (C)": float(group["T_paroi_forage_C"].iloc[-1]),
                "T paroi forage min (C)": float(group["T_paroi_forage_C"].min()),
                "T paroi forage max (C)": float(group["T_paroi_forage_C"].max()),
                "T evaporateur PAC min (C)": float(group["T_evaporateur_PAC_C"].min()),
                "Q net sol (MWh)": (extracted - injected) / 1000.0,
                "Injection BTES (MWh)": injected / 1000.0,
                "Extraction PAC (MWh)": extracted / 1000.0,
                "Ratio injection/extraction": injected / max(1e-9, extracted),
                "eta_BTES": btes_efficiency_indicator(extracted, injected),
                "Transitions injection/extraction": int(sign_diag["sign_changes"]),
                "Indice alternance charge": float(sign_diag["seasonal_load_variability_index"]),
                "Niveau alternance": str(sign_diag["alternance_level"]),
                "q extraction max (W/m)": float(group["q_extraction_W_m"].max()),
                "q injection max (W/m)": float(group["q_injection_W_m"].max()),
                "q net moyen (W/m)": float(group["q_net_W_m"].mean()),
                "COP machine": heat_pac / elec_compressor if elec_compressor > 0 else 0.0,
                "SPF PAC complet": heat_pac / elec_total if elec_total > 0 else 0.0,
                "Heures sous Tmin operationnelle": int((group["T_source_PAC_pour_COP_C"] <= t_min_c + 1e-6).sum()),
                "Heures sous Tmin source": int((group["T_source_PAC_C"] <= t_min_c + 1e-6).sum()),
                "Heures sous Tmin GMI": int((group["T_fluide_entree_echangeur_geo_C"] < gmi_t_min_c - 1e-6).sum()),
                "Heures sur Tmax GMI": int((group["T_fluide_injection_C"] > gmi_t_max_c + 1e-6).sum()),
                "Conformite GMI": bool(
                    (not gmi_check_enabled)
                    or (
                        (group["T_fluide_entree_echangeur_geo_C"] >= gmi_t_min_c - 1e-6).all()
                        and (group["T_fluide_injection_C"] <= gmi_t_max_c + 1e-6).all()
                    )
                ),
                "Heures limite source": int(group["Limite_temperature_source"].sum()),
                "BT non couvert limite source (MWh)": float(group["BT_non_couvert_limite_source_kWh"].sum()) / 1000.0,
                "Heures COP max": int(group["cop_limited_max"].sum()),
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
        ("Bilan net sol extraction - injection", results_df["btes_extracted_by_pac_kwh"].sum() - results_df["solar_to_btes_kwh"].sum()),
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
                "Bilan net sol (MWh)": (group["btes_extracted_by_pac_kwh"].sum() - group["solar_to_btes_kwh"].sum()) / 1000.0,
                "COP machine": group["heat_bt_from_pac_kwh"].sum() / max(1e-9, elec_compressor),
                "SPF PAC complet": group["heat_bt_from_pac_kwh"].sum() / max(1e-9, elec_total),
                "T ballon fin (C)": group["solar_ht_buffer_temp_end_c"].iloc[-1],
                "T source PAC fin (C)": group["T_source_PAC_C"].iloc[-1],
                "T source PAC min (C)": group["T_source_PAC_C"].min(),
                "T source PAC pour COP min (C)": group["T_source_PAC_pour_COP_C"].min(),
                "T paroi forage fin (C)": group["T_paroi_forage_C"].iloc[-1],
                "T evaporateur PAC min (C)": group["T_evaporateur_PAC_C"].min(),
                "q extraction max (W/m)": group["q_extraction_W_m"].max(),
                "q injection max (W/m)": group["q_injection_W_m"].max(),
                "q net moyen (W/m)": group["q_net_W_m"].mean(),
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
    """Build duration curves for stacked coverage charts with vectorized pandas operations."""

    working_df = results_df
    if mode == "HT":
        sort_column = "Puissance besoin HT (kW)"
        components = [
            ("Solaire thermique", "Puissance prechauffage HT solaire (kW)", 1),
            ("Appoint gaz", "Puissance appoint HT (kW)", 2),
        ]
    elif mode == "BT":
        sort_column = "Puissance besoin BT (kW)"
        components = [
            ("Géothermie PAC", "Puissance BT PAC (kW)", 1),
            ("Appoint gaz", "Puissance appoint BT (kW)", 2),
        ]
    elif mode == "GLOBAL":
        sort_column = "Puissance besoin total (kW)"
        working_df = results_df.copy()
        working_df["Puissance appoint total (kW)"] = (
            working_df["Puissance appoint HT (kW)"] + working_df["Puissance appoint BT (kW)"]
        )
        components = [
            ("Solaire thermique", "Puissance prechauffage HT solaire (kW)", 1),
            ("Géothermie PAC", "Puissance BT PAC (kW)", 2),
            ("Appoint gaz", "Puissance appoint total (kW)", 3),
        ]
    else:
        raise ValueError("mode doit valoir HT, BT ou GLOBAL")

    sorted_df = working_df.sort_values(sort_column, ascending=False).reset_index(drop=True).copy()
    sorted_df["Heure triee"] = sorted_df.index + 1

    component_columns = [column for _, column, _ in components]
    label_by_column = {column: label for label, column, _ in components}
    order_by_label = {label: order for label, _, order in components}
    duration_df = sorted_df[
        ["Heure triee", "month", "day", "hour", "tair_c", *component_columns]
    ].melt(
        id_vars=["Heure triee", "month", "day", "hour", "tair_c"],
        value_vars=component_columns,
        var_name="Poste",
        value_name="Puissance (kW)",
    )
    duration_df["Poste"] = duration_df["Poste"].map(label_by_column)
    duration_df["Ordre"] = duration_df["Poste"].map(order_by_label).astype(int)
    return duration_df.rename(
        columns={
            "month": "Mois",
            "day": "Jour",
            "hour": "Heure EPW",
            "tair_c": "Tair (C)",
        }
    )


def _melt_monthly(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df[["Mois", *columns]].melt(
        id_vars=["Mois"],
        value_vars=columns,
        var_name="Poste",
        value_name="Valeur",
    )
    out["Poste"] = out["Poste"].replace(
        {
            "Prechauffage HT solaire (MWh)": "Production solaire ECS (MWh)",
            "Injection BTES (MWh)": "Production solaire injectée dans le BTES (MWh)",
            "BT PAC (MWh)": "Géothermie PAC (MWh)",
        }
    )
    order_by_poste = {
        "Production solaire ECS (MWh)": 1,
        "Production solaire injectée dans le BTES (MWh)": 2,
        "Géothermie PAC (MWh)": 1,
        "Appoint HT (MWh)": 2,
        "Appoint BT (MWh)": 2,
    }
    out["Ordre"] = out["Poste"].map(order_by_poste).fillna(1).astype(int)
    return out


def _mean_cop(results_df: pd.DataFrame) -> float:
    heat = float(results_df["heat_bt_from_pac_kwh"].sum())
    electricity = float(results_df["electricity_compressor_kwh"].sum())
    return heat / electricity if electricity > 0 else 0.0

