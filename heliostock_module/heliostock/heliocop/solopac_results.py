"""Lecture ciblée des exports mensuels SOLOPAC utiles à HelioCOP.

HelioCOP ne cherche pas à reproduire l'intégralité du classeur SOLOPAC. Seuls
les flux nécessaires à l'analyse technique et économique sont conservés :
besoin utile, chaleur PAC, énergie renouvelable à l'évaporateur, électricité
compresseur, auxiliaires, appoint chaudière et COP.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .model import MONTH_NAMES


_REQUIRED_COLUMNS = {
    "Mois",
    "BECS",
    "QPAC_Evap",
    "QPAC_Cond",
    "PAbs_PAC",
    "QChaudiere",
    "COP",
}


@dataclass(frozen=True)
class SoloPacMonthlyResult:
    month: str
    useful_need_mwh: float
    renewable_evaporator_mwh: float
    pac_condenser_mwh: float
    compressor_electricity_mwh: float
    auxiliary_electricity_mwh: float
    gas_backup_heat_mwh: float
    cop_system: float
    renewable_rate: float
    pac_coverage_rate: float
    gas_share_rate: float


@dataclass(frozen=True)
class SoloPacResults:
    monthly_rows: tuple[SoloPacMonthlyResult, ...]
    source_sheet: str
    annual_useful_need_mwh: float
    annual_renewable_evaporator_mwh: float
    annual_pac_condenser_mwh: float
    annual_compressor_electricity_mwh: float
    annual_auxiliary_electricity_mwh: float
    annual_total_electricity_mwh: float
    annual_gas_backup_heat_mwh: float
    annual_cop_machine: float
    annual_cop_system: float
    annual_renewable_rate: float
    annual_pac_coverage_rate: float
    annual_gas_share_rate: float


def _safe_divide(a: float, b: float) -> float:
    return float(a) / float(b) if float(b) > 0 else 0.0


def _read_excel(source: str | Path | bytes | bytearray | BinaryIO) -> tuple[pd.DataFrame, str]:
    if isinstance(source, (bytes, bytearray)):
        source = BytesIO(source)
    excel = pd.ExcelFile(source)
    if not excel.sheet_names:
        raise ValueError("Le fichier SOLOPAC ne contient aucune feuille.")
    sheet = excel.sheet_names[0]
    frame = pd.read_excel(excel, sheet_name=sheet)
    return frame, sheet


def load_solopac_results(source: str | Path | bytes | bytearray | BinaryIO) -> SoloPacResults:
    """Lit un export mensuel SOLOPAC et retourne uniquement les flux utiles.

    Les valeurs SOLOPAC sont exprimées en kWh dans le classeur d'export. Elles
    sont converties ici en MWh. La ligne TOTAL n'est pas utilisée : les totaux
    sont recalculés à partir des douze mois pour éviter toute dépendance aux
    formules ou formats du classeur.
    """

    df, sheet = _read_excel(source)
    df.columns = [str(c).strip() for c in df.columns]
    missing = sorted(_REQUIRED_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(
            "Export SOLOPAC non reconnu : colonnes manquantes : " + ", ".join(missing)
        )

    aux_col = "Waux" if "Waux" in df.columns else None
    monthly: list[SoloPacMonthlyResult] = []
    for _, raw in df.iterrows():
        try:
            month_number = int(float(raw["Mois"]))
        except (TypeError, ValueError):
            continue
        if not 1 <= month_number <= 12:
            continue

        def mwh(column: str) -> float:
            value = pd.to_numeric(raw.get(column, 0.0), errors="coerce")
            if pd.isna(value):
                return 0.0
            return max(0.0, float(value)) / 1000.0

        useful = mwh("BECS")
        q_evap = mwh("QPAC_Evap")
        q_cond = mwh("QPAC_Cond")
        e_comp = mwh("PAbs_PAC")
        e_aux = mwh(aux_col) if aux_col else 0.0
        q_gas = mwh("QChaudiere")
        production = q_cond + q_gas
        cop_raw = pd.to_numeric(raw.get("COP", 0.0), errors="coerce")
        cop = float(cop_raw) if not pd.isna(cop_raw) and float(cop_raw) > 0 else _safe_divide(q_cond, e_comp + e_aux)

        monthly.append(
            SoloPacMonthlyResult(
                month=MONTH_NAMES[month_number - 1],
                useful_need_mwh=useful,
                renewable_evaporator_mwh=q_evap,
                pac_condenser_mwh=q_cond,
                compressor_electricity_mwh=e_comp,
                auxiliary_electricity_mwh=e_aux,
                gas_backup_heat_mwh=q_gas,
                cop_system=cop,
                renewable_rate=_safe_divide(q_evap, production),
                pac_coverage_rate=_safe_divide(q_cond, production),
                gas_share_rate=_safe_divide(q_gas, production),
            )
        )

    if len(monthly) != 12:
        raise ValueError(f"Export SOLOPAC incomplet : {len(monthly)} mois trouvés au lieu de 12.")

    # SOLOPAC arrondit les valeurs mensuelles dans l'export ; la ligne TOTAL
    # contient des totaux annuels plus précis. On l'utilise lorsqu'elle est
    # disponible, tout en conservant les 12 lignes mensuelles pour les graphes.
    total_rows = df[df["Mois"].astype(str).str.strip().str.upper() == "TOTAL"]
    total = total_rows.iloc[0] if not total_rows.empty else None

    def annual_mwh(column: str, fallback: float) -> float:
        if total is None or column not in df.columns:
            return fallback
        value = pd.to_numeric(total.get(column, None), errors="coerce")
        if pd.isna(value):
            return fallback
        return max(0.0, float(value)) / 1000.0

    useful = annual_mwh("BECS", sum(r.useful_need_mwh for r in monthly))
    q_evap = annual_mwh("QPAC_Evap", sum(r.renewable_evaporator_mwh for r in monthly))
    q_cond = annual_mwh("QPAC_Cond", sum(r.pac_condenser_mwh for r in monthly))
    e_comp = annual_mwh("PAbs_PAC", sum(r.compressor_electricity_mwh for r in monthly))
    e_aux = annual_mwh(aux_col, sum(r.auxiliary_electricity_mwh for r in monthly)) if aux_col else 0.0
    q_gas = annual_mwh("QChaudiere", sum(r.gas_backup_heat_mwh for r in monthly))
    production = q_cond + q_gas

    return SoloPacResults(
        monthly_rows=tuple(monthly),
        source_sheet=sheet,
        annual_useful_need_mwh=useful,
        annual_renewable_evaporator_mwh=q_evap,
        annual_pac_condenser_mwh=q_cond,
        annual_compressor_electricity_mwh=e_comp,
        annual_auxiliary_electricity_mwh=e_aux,
        annual_total_electricity_mwh=e_comp + e_aux,
        annual_gas_backup_heat_mwh=q_gas,
        annual_cop_machine=_safe_divide(q_cond, e_comp),
        annual_cop_system=_safe_divide(q_cond, e_comp + e_aux),
        annual_renewable_rate=_safe_divide(q_evap, production),
        annual_pac_coverage_rate=_safe_divide(q_cond, production),
        annual_gas_share_rate=_safe_divide(q_gas, production),
    )
