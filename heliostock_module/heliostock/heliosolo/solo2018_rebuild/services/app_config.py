from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping

import pandas as pd

from heliostock.heliosolo.solo2018_rebuild.defaults import DEFAULT_T_ENV_STOCK_C
from heliostock.heliosolo.solo2018_rebuild.services.profiles import default_rows, ensure_rows_schema


SessionState = MutableMapping[str, Any]


@dataclass(slots=True)
class AppConfig:
    """Stable snapshot of the Streamlit state used by the SOLO UI."""

    ecs_rows_df: pd.DataFrame
    vecs_monthly_map: dict[str, float]
    tecs_monthly_map: dict[str, float]
    tecs_dis_monthly_map: dict[str, float]
    tef_monthly_map: dict[str, float]
    tenv_monthly_map: dict[str, float]
    pertes_boucle_monthly_map: dict[str, float]
    rdispo_monthly_map: dict[str, float]

    @classmethod
    def from_session(cls, session_state: SessionState) -> "AppConfig":
        return cls(
            ecs_rows_df=ensure_rows_schema(session_state["ecs_rows_df"]),
            vecs_monthly_map=dict(session_state["vecs_monthly_map_state"]),
            tecs_monthly_map=dict(session_state["tecs_monthly_map_state"]),
            tecs_dis_monthly_map=dict(session_state["tecs_dis_monthly_map_state"]),
            tef_monthly_map=dict(session_state["tef_monthly_map_state"]),
            tenv_monthly_map=dict(session_state["tenv_monthly_map_state"]),
            pertes_boucle_monthly_map=dict(session_state["pertes_boucle_monthly_map_state"]),
            rdispo_monthly_map=dict(session_state["rdispo_monthly_map_state"]),
        )


def _rows_as_records(session_state: SessionState) -> list[dict[str, Any]]:
    return session_state["ecs_rows_df"].to_dict(orient="records")


def _month_map(
    rows: list[dict[str, Any]],
    source_key: str,
    fallback: float,
) -> dict[str, float]:
    return {
        str(row["month"]): float(row.get(source_key, fallback))
        for row in rows
    }


def _tenv_month_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        value = row.get("t_env_stock_c")
        if value is not None and not pd.isna(value):
            out[str(row["month"])] = float(value)
        else:
            out[str(row["month"])] = float(DEFAULT_T_ENV_STOCK_C)
    return out


def ensure_app_state(session_state: SessionState) -> AppConfig:
    """Initialise Streamlit session keys once, then return an AppConfig snapshot."""

    if "ecs_rows_df" not in session_state:
        session_state["ecs_rows_df"] = pd.DataFrame(default_rows())
    else:
        session_state["ecs_rows_df"] = ensure_rows_schema(session_state["ecs_rows_df"])

    rows = _rows_as_records(session_state)

    # Monthly maps avoid losing the first edited value during Streamlit reruns.
    session_state.setdefault("vecs_monthly_map_state", _month_map(rows, "vecs_l_j", 1500.0))
    session_state.setdefault("tecs_monthly_map_state", _month_map(rows, "tecs_m", 60.0))
    session_state.setdefault("tecs_dis_monthly_map_state", _month_map(rows, "tecs_dis_m", 55.0))
    session_state.setdefault("tef_monthly_map_state", _month_map(rows, "tef_m", 12.0))
    session_state.setdefault("tenv_monthly_map_state", _tenv_month_map(rows))
    session_state.setdefault(
        "pertes_boucle_monthly_map_state",
        _month_map(rows, "pertes_boucle_input_kwh_j", 0.0),
    )
    session_state.setdefault(
        "rdispo_monthly_map_state",
        {
            str(row["month"]): float(
                row.get("r_disponible_kwh_m2_j", row.get("r_global_plan_kwh_m2_j", 0.0))
            )
            for row in rows
        },
    )

    return AppConfig.from_session(session_state)


