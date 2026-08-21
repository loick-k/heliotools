"""Couplage itératif champ WISC / évaporateur PAC.

V1.0.6 : voie rapide pour cartes rectangulaires et warm-start temporel.
La physique et les bornes fabricant restent inchangées ; seule la stratégie
numérique est optimisée pour une simulation annuelle interactive.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

import numpy as np
from scipy.optimize import brentq

from ..manufacturer.hp_map import HeatPumpEvaluation
from ..manufacturer.schemas import HeatPumpProduct
from .weather import DynamicWeatherHour
from .wisc_qdt import WISCFluxBreakdown, WISCQuasiDynamicModel


CP_BRINE_JKGK = 3900.0
RHO_BRINE_KGM3 = 1030.0


@dataclass(frozen=True)
class SourceCouplingResult:
    valid: bool
    reason: str
    t_source_in_c: float = 0.0
    t_source_out_c: float = 0.0
    t_collector_mean_c: float = 0.0
    p_collector_kw: float = 0.0
    p_evap_kw: float = 0.0
    p_heat_kw: float = 0.0
    p_el_kw: float = 0.0
    cop: float = 0.0
    sink_in_c: float = 0.0
    sink_map_lookup_c: float = 0.0
    sink_map_status: str = "IN_MAP"
    sink_out_c: float = 0.0
    q_solar_kw: float = 0.0
    q_atmospheric_and_ir_kw: float = 0.0
    wisc_breakdown: WISCFluxBreakdown | None = None


def solve_wisc_heat_pump_equilibrium(
    *,
    weather: DynamicWeatherHour,
    collector_model: WISCQuasiDynamicModel,
    collector_area_m2: float,
    heat_pump: HeatPumpProduct,
    hp_count: int,
    sink_in_c: float,
    source_flow_m3h_per_hp: float,
    sink_flow_m3h_per_hp: float,
    previous_collector_mean_c: float | None,
    dt_s: float,
    sink_map_lookup_c: float | None = None,
    sink_map_status: str = "IN_MAP",
    clamp_sink_below_map: bool = False,
    clamp_sink_above_map: bool = False,
    previous_source_in_c: float | None = None,
    cp_brine_jkgk: float = CP_BRINE_JKGK,
    rho_brine_kgm3: float = RHO_BRINE_KGM3,
    cp_sink_jkgk: float = 4180.0,
    rho_sink_kgm3: float = 1000.0,
) -> SourceCouplingResult:
    """Cherche T entrée PAC source telle que Qcapteur = Qévap.

    Optimisations V1.0.6 :
    - pour une carte ``sink_out`` rectangulaire, l'équation hydraulique côté
      chaud est résolue exactement sur chaque segment bilinéaire, sans Brent
      imbriqué ;
    - la température source de l'itération précédente sert de warm-start ;
    - le balayage 17 points n'est utilisé qu'en repli (9 points en V1.0.6).

    Aucune extrapolation continue de carte PAC n'est introduite.
    """
    if heat_pump.performance_map is None:
        return SourceCouplingResult(False, "MISSING_HP_MAP")
    count = max(1, int(hp_count))
    area = max(0.0, float(collector_area_m2))
    if area <= 0.0:
        return SourceCouplingResult(False, "INVALID_COLLECTOR_AREA")
    source_flow_m3h = float(source_flow_m3h_per_hp) * count
    sink_flow_m3h = float(sink_flow_m3h_per_hp) * count
    if source_flow_m3h <= 0.0:
        return SourceCouplingResult(False, "MISSING_SOURCE_FLOW")
    if sink_flow_m3h <= 0.0:
        return SourceCouplingResult(False, "MISSING_SINK_FLOW")
    m_source = source_flow_m3h / 3600.0 * rho_brine_kgm3
    m_sink = sink_flow_m3h / 3600.0 * rho_sink_kgm3
    hp_map = heat_pump.performance_map
    source_lo, source_hi = hp_map.source_bounds_C
    sink_lo, sink_hi = hp_map.sink_bounds_C
    failure_reasons: list[str] = []

    def _hp_eval_from_values(p_heat: float, p_el: float) -> HeatPumpEvaluation:
        if not (isfinite(p_heat) and isfinite(p_el) and p_heat > 0.0 and p_el > 0.0):
            return HeatPumpEvaluation(False, 0.0, 0.0, 0.0, 0.0, reason="OUTSIDE_HP_MAP", provenance=hp_map.provenance)
        return HeatPumpEvaluation(
            True,
            P_heat_kW=float(p_heat),
            P_el_kW=float(p_el),
            COP=float(p_heat) / float(p_el),
            P_evap_kW=float(p_heat) - float(p_el),
            provenance=hp_map.provenance,
            uncertainty_pct=hp_map.uncertainty_pct,
        )

    def _sink_state_regular_outlet(t_source_in: float):
        sliced = hp_map.regular_sink_slice(T_source_in_C=float(t_source_in))
        if sliced is None:
            return None
        sinks, pheat_nodes, pel_nodes = sliced
        # Pheat_nodes est la puissance d'une PAC ; m_sink est déjà le débit de
        # la batterie complète. La température réelle de sortie est donc :
        actual_nodes = float(sink_in_c) + pheat_nodes * count * 1000.0 / max(1e-9, m_sink * cp_sink_jkgk)
        g = sinks - actual_nodes

        def node_state(idx: int, status: str):
            hp = _hp_eval_from_values(float(pheat_nodes[idx]), float(pel_nodes[idx]))
            return hp, float(sinks[idx]), status, float(actual_nodes[idx]), "OK"

        if g[0] > 0.0:
            if not clamp_sink_below_map:
                return None, float(sinks[0]), "SINK_OUTSIDE_HP_MAP", float(actual_nodes[0]), "SINK_OUTSIDE_HP_MAP"
            return node_state(0, "SINK_CLAMPED_LOW")
        if g[-1] < 0.0:
            if not clamp_sink_above_map:
                return None, float(sinks[-1]), "SINK_OUTSIDE_HP_MAP", float(actual_nodes[-1]), "SINK_OUTSIDE_HP_MAP"
            return node_state(len(sinks) - 1, "SINK_CLAMPED_HIGH")

        # Sur une cellule bilinéaire et à Tsource fixé, Pheat(Tsink) est
        # linéaire : g(Tsink)=Tsink-Tretour-k.Pheat(Tsink) l'est aussi. Le
        # zéro est donc obtenu par interpolation linéaire exacte sur le segment.
        for j in range(len(sinks) - 1):
            gj, gj1 = float(g[j]), float(g[j + 1])
            if abs(gj) <= 1e-10:
                return node_state(j, "IN_MAP")
            if gj * gj1 <= 0.0:
                denom = gj1 - gj
                f = 0.0 if abs(denom) <= 1e-14 else -gj / denom
                f = max(0.0, min(1.0, f))
                lookup = float(sinks[j] + f * (sinks[j + 1] - sinks[j]))
                p_heat = float(pheat_nodes[j] + f * (pheat_nodes[j + 1] - pheat_nodes[j]))
                p_el = float(pel_nodes[j] + f * (pel_nodes[j + 1] - pel_nodes[j]))
                hp = _hp_eval_from_values(p_heat, p_el)
                actual = float(sink_in_c) + p_heat * count * 1000.0 / max(1e-9, m_sink * cp_sink_jkgk)
                return hp, lookup, "IN_MAP", actual, "OK"
        if abs(float(g[-1])) <= 1e-10:
            return node_state(len(sinks) - 1, "IN_MAP")
        return None, float(sink_in_c), "IN_MAP", float(sink_in_c), "OUTSIDE_HP_MAP"

    def _sink_state_for_source(t_source_in: float):
        """Retourne (hp_eval, lookup, status, Tout_reel, reason)."""
        if hp_map.sink_temperature_convention == "sink_in":
            lookup = float(sink_in_c if sink_map_lookup_c is None else sink_map_lookup_c)
            hp = hp_map.evaluate(T_source_in_C=t_source_in, T_sink_C=lookup)
            if not hp.valid:
                return None, lookup, sink_map_status, float(sink_in_c), "OUTSIDE_HP_MAP"
            p_heat = hp.P_heat_kW * count
            t_sink_out = sink_in_c + p_heat * 1000.0 / max(1e-9, m_sink * cp_sink_jkgk)
            return hp, lookup, str(sink_map_status), t_sink_out, "OK"

        # Voie rapide exacte pour les cartes P-25/P-50 rectangulaires.
        if hp_map.is_regular_grid:
            return _sink_state_regular_outlet(float(t_source_in))

        # Repli générique pour une éventuelle carte irrégulière sink_out.
        def _state_at_lookup(lookup: float):
            hp = hp_map.evaluate(T_source_in_C=t_source_in, T_sink_C=float(lookup))
            if not hp.valid:
                return None
            p_heat = hp.P_heat_kW * count
            t_actual = sink_in_c + p_heat * 1000.0 / max(1e-9, m_sink * cp_sink_jkgk)
            return hp, t_actual

        low_state = _state_at_lookup(sink_lo)
        high_state = _state_at_lookup(sink_hi)
        if low_state is None or high_state is None:
            return None, float(sink_in_c), "IN_MAP", float(sink_in_c), "OUTSIDE_HP_MAP"
        hp_low, actual_low = low_state
        hp_high, actual_high = high_state
        g_low = sink_lo - actual_low
        g_high = sink_hi - actual_high
        if g_low > 0.0:
            if not clamp_sink_below_map:
                return None, sink_lo, "SINK_OUTSIDE_HP_MAP", actual_low, "SINK_OUTSIDE_HP_MAP"
            return hp_low, sink_lo, "SINK_CLAMPED_LOW", actual_low, "OK"
        if g_high < 0.0:
            if not clamp_sink_above_map:
                return None, sink_hi, "SINK_OUTSIDE_HP_MAP", actual_high, "SINK_OUTSIDE_HP_MAP"
            return hp_high, sink_hi, "SINK_CLAMPED_HIGH", actual_high, "OK"

        def sink_residual(lookup: float) -> float:
            state = _state_at_lookup(float(lookup))
            if state is None:
                raise ValueError("Point côté chaud intermédiaire hors carte PAC.")
            _, actual = state
            return float(lookup) - actual

        if abs(g_low) <= 1e-8:
            lookup = sink_lo
        elif abs(g_high) <= 1e-8:
            lookup = sink_hi
        else:
            lookup = float(brentq(sink_residual, sink_lo, sink_hi, xtol=1e-4, rtol=1e-6, maxiter=40))
        state = _state_at_lookup(lookup)
        if state is None:
            return None, lookup, "IN_MAP", float(sink_in_c), "OUTSIDE_HP_MAP"
        hp, actual = state
        return hp, lookup, "IN_MAP", actual, "OK"

    eval_cache: dict[float, tuple | None] = {}

    def evaluate_at(t_source_in: float):
        # Brent revisite parfois exactement les mêmes points ; ce petit cache
        # local évite de refaire l'interpolation PAC et le bilan WISC.
        key = round(float(t_source_in), 10)
        if key in eval_cache:
            return eval_cache[key]
        hp, sink_lookup, sink_status, t_sink_out, sink_reason = _sink_state_for_source(float(t_source_in))
        if hp is None:
            failure_reasons.append(sink_reason)
            eval_cache[key] = None
            return None
        p_heat = hp.P_heat_kW * count
        p_el = hp.P_el_kW * count
        p_evap = hp.P_evap_kW * count
        t_source_out = t_source_in - p_evap * 1000.0 / max(1e-9, m_source * cp_brine_jkgk)
        t_mean = 0.5 * (t_source_in + t_source_out)
        flux = collector_model.evaluate(
            weather=weather,
            t_mean_c=t_mean,
            previous_t_mean_c=previous_collector_mean_c,
            dt_s=dt_s,
        )
        p_collector = flux.q_useful_wm2 * area / 1000.0
        residual = p_collector - p_evap
        if heat_pump.sink_outlet_temperature_max_C is not None and t_sink_out > heat_pump.sink_outlet_temperature_max_C + 1e-9:
            failure_reasons.append("SINK_OUTSIDE_HP_MAP")
            eval_cache[key] = None
            return None
        value = (
            residual, hp, p_heat, p_el, p_evap, t_source_out, t_mean,
            p_collector, t_sink_out, flux, sink_lookup, sink_status,
        )
        eval_cache[key] = value
        return value

    def _valid_sample(t: float):
        v = evaluate_at(float(t))
        return None if v is None or not isfinite(v[0]) else (float(t), v)

    def _is_root(v) -> bool:
        return v is not None and abs(float(v[1][0])) <= 1e-7

    def _sign_bracket(a, b):
        if a is None or b is None:
            return None
        ra, rb = float(a[1][0]), float(b[1][0])
        if abs(ra) <= 1e-7:
            return (a[0], a[0])
        if abs(rb) <= 1e-7:
            return (b[0], b[0])
        if ra * rb < 0.0:
            return (a[0], b[0])
        return None

    # 1) Warm-start temporel autour de la solution précédente.
    bracket: tuple[float, float] | None = None
    if previous_source_in_c is not None and source_lo <= previous_source_in_c <= source_hi:
        guess = _valid_sample(float(previous_source_in_c))
        if _is_root(guess):
            bracket = (guess[0], guess[0])
        else:
            base_span = max(1.5, 0.06 * (source_hi - source_lo))
            for factor in (1.0, 2.5, 6.0):
                a_t = max(source_lo, float(previous_source_in_c) - base_span * factor)
                b_t = min(source_hi, float(previous_source_in_c) + base_span * factor)
                a = _valid_sample(a_t)
                b = _valid_sample(b_t)
                bracket = _sign_bracket(a, b)
                if bracket is not None:
                    break
                if a_t <= source_lo + 1e-12 and b_t >= source_hi - 1e-12:
                    break

    # 2) Cas courant : les bornes globales encadrent déjà la racine.
    bound_samples: list[tuple[float, tuple]] = []
    if bracket is None:
        lo_s = _valid_sample(source_lo)
        hi_s = _valid_sample(source_hi)
        if lo_s is not None:
            bound_samples.append(lo_s)
        if hi_s is not None and (not bound_samples or hi_s[0] != bound_samples[-1][0]):
            bound_samples.append(hi_s)
        bracket = _sign_bracket(lo_s, hi_s)

    # 3) Repli robuste seulement si nécessaire. On conserve le balayage
    # historique à 17 points pour ne pas rater une fenêtre valide étroite
    # (par exemple lorsque la limite chaude invalide les bords de carte).
    samples: list[tuple[float, tuple]] = list(bound_samples)
    if bracket is None:
        samples_by_t = {t: v for t, v in samples}
        for t in np.linspace(source_lo, source_hi, 17):
            sample = _valid_sample(float(t))
            if sample is not None:
                samples_by_t[sample[0]] = sample[1]
        samples = sorted(samples_by_t.items(), key=lambda item: item[0])
        for a, b in zip(samples, samples[1:]):
            bracket = _sign_bracket(a, b)
            if bracket is not None:
                break

    if bracket is None:
        # Si tous les points sont invalides, privilégier le diagnostic côté chaud.
        if not samples:
            if "SINK_OUTSIDE_HP_MAP" in failure_reasons:
                return SourceCouplingResult(False, "SINK_OUTSIDE_HP_MAP", sink_in_c=float(sink_in_c))
            return SourceCouplingResult(False, "OUTSIDE_HP_MAP", sink_in_c=float(sink_in_c))
        residuals = [float(v[0]) for _, v in samples]
        if max(residuals) < 0.0:
            return SourceCouplingResult(False, "SOURCE_INSUFFICIENT", sink_in_c=float(sink_in_c))
        if min(residuals) > 0.0:
            return SourceCouplingResult(False, "SOURCE_EQUILIBRIUM_ABOVE_HP_MAP", sink_in_c=float(sink_in_c))
        return SourceCouplingResult(False, "NO_SOURCE_EQUILIBRIUM", sink_in_c=float(sink_in_c))

    if bracket[0] == bracket[1]:
        root = bracket[0]
    else:
        def residual_fn(t: float) -> float:
            val = evaluate_at(t)
            if val is None:
                raise ValueError("Point intermédiaire hors carte PAC.")
            return float(val[0])
        root = float(brentq(residual_fn, bracket[0], bracket[1], xtol=1e-4, rtol=1e-6, maxiter=50))

    val = evaluate_at(root)
    if val is None:
        reason = "SINK_OUTSIDE_HP_MAP" if "SINK_OUTSIDE_HP_MAP" in failure_reasons else "OUTSIDE_HP_MAP"
        return SourceCouplingResult(False, reason, sink_in_c=float(sink_in_c))
    (
        _, hp, p_heat, p_el, p_evap, t_source_out, t_mean, p_collector,
        t_sink_out, flux, sink_lookup, sink_status,
    ) = val
    q_solar_kw = flux.q_solar_wm2 * area / 1000.0
    q_other_kw = p_collector - q_solar_kw
    return SourceCouplingResult(
        True,
        "OK",
        t_source_in_c=root,
        t_source_out_c=t_source_out,
        t_collector_mean_c=t_mean,
        p_collector_kw=p_collector,
        p_evap_kw=p_evap,
        p_heat_kw=p_heat,
        p_el_kw=p_el,
        cop=p_heat / max(1e-9, p_el),
        sink_in_c=float(sink_in_c),
        sink_map_lookup_c=float(sink_lookup),
        sink_map_status=str(sink_status),
        sink_out_c=t_sink_out,
        q_solar_kw=q_solar_kw,
        q_atmospheric_and_ir_kw=q_other_kw,
        wisc_breakdown=flux,
    )
