"""Modèle quasi-dynamique WISC pour HelioCOP ECS1 dynamique V1.

Le modèle reprend la structure quasi-dynamique EN 12975 / ISO 9806 utilisée
pour caractériser les capteurs sensibles au vent et/ou au rayonnement IR.
Les champs XML eta0, a1...a8, Kd, KT et KL sont utilisés tels quels ; ils ne
sont jamais remplacés par des coefficients génériques fabricant.

Limites V1 explicites :
- condensation/évaporation latente non ajoutée séparément ;
- pluie et givre non modélisés ;
- IAM direct biaxial approché par la moyenne géométrique KT/KL évaluée à
  l'angle d'incidence global ;
- coefficients considérés représentatifs du produit complet : aucune
  multiplication artificielle pour une deuxième face.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Mapping

from ..manufacturer.schemas import WISCCollectorProduct
from .weather import DynamicWeatherHour, SIGMA


@dataclass(frozen=True)
class WISCFluxBreakdown:
    q_useful_wm2: float
    q_solar_wm2: float
    q_temperature_wm2: float
    q_wind_temperature_wm2: float
    q_longwave_wm2: float
    q_capacity_wm2: float
    q_wind_solar_wm2: float
    q_wind_longwave_wm2: float
    q_fourth_order_wm2: float
    iam_beam: float
    u_prime_ms: float
    t_mean_c: float


def _interp_iam(values: Mapping[int, float], angle_deg: float) -> float:
    angle = max(0.0, min(90.0, float(angle_deg)))
    if angle <= 0.0:
        return 1.0
    points = sorted((int(k), float(v)) for k, v in values.items())
    if not points:
        return 1.0
    if angle <= points[0][0]:
        a1, v1 = 0.0, 1.0
        a2, v2 = float(points[0][0]), points[0][1]
        if a2 <= 0:
            return max(0.0, v2)
        return max(0.0, v1 + (v2 - v1) * angle / a2)
    for (a1, v1), (a2, v2) in zip(points, points[1:]):
        if a1 <= angle <= a2:
            f = (angle - a1) / max(1e-9, a2 - a1)
            return max(0.0, v1 + f * (v2 - v1))
    return max(0.0, points[-1][1])


class WISCQuasiDynamicModel:
    """Évalue le flux surfacique utile d'un produit WISC certifié/XML."""

    schema_name = "ISO9806_QDT_XML_A1_A8_V1"

    def __init__(self, product: WISCCollectorProduct, *, wind_reference_ms: float = 3.0) -> None:
        self.product = product
        self.wind_reference_ms = float(wind_reference_ms)
        coeffs = product.coefficients
        required = {"eta0", *(f"a{i}" for i in range(1, 9))}
        missing = required - set(coeffs)
        if missing:
            raise ValueError(f"{product.manufacturer} {product.model}: coefficients WISC manquants {sorted(missing)}")
        if product.unit_area_m2 <= 0:
            raise ValueError("Surface unitaire WISC invalide.")

    def evaluate(
        self,
        *,
        weather: DynamicWeatherHour,
        t_mean_c: float,
        previous_t_mean_c: float | None,
        dt_s: float,
    ) -> WISCFluxBreakdown:
        c = self.product.coefficients
        eta0 = float(c["eta0"])
        a1 = float(c["a1"])
        a2 = float(c["a2"])
        a3 = float(c["a3"])
        a4 = float(c["a4"])
        a5 = float(c["a5"])
        a6 = float(c["a6"])
        a7 = float(c["a7"])
        a8 = float(c["a8"])
        d_t = float(t_mean_c) - weather.t_amb_c
        u_prime = weather.wind_ms - self.wind_reference_ms
        kt = _interp_iam(self.product.KT, weather.incidence_angle_deg)
        kl = _interp_iam(self.product.KL, weather.incidence_angle_deg)
        iam_beam = sqrt(max(0.0, kt) * max(0.0, kl))
        diffuse_global = weather.diffuse_poa_wm2 + weather.reflected_poa_wm2
        q_solar = eta0 * (iam_beam * weather.beam_poa_wm2 + self.product.Kd * diffuse_global)
        q_temp = -a1 * d_t - a2 * d_t * d_t
        q_wind_temp = -a3 * u_prime * d_t
        t_amb_k = weather.t_amb_c + 273.15
        longwave_delta = weather.longwave_poa_wm2 - SIGMA * t_amb_k**4
        q_lw = a4 * longwave_delta
        if previous_t_mean_c is None or dt_s <= 0:
            q_capacity = 0.0
        else:
            q_capacity = -a5 * (float(t_mean_c) - float(previous_t_mean_c)) / float(dt_s)
        q_wind_solar = -a6 * u_prime * weather.g_poa_wm2
        q_wind_lw = -a7 * u_prime * longwave_delta
        q_fourth = -a8 * d_t**4
        q_total = q_solar + q_temp + q_wind_temp + q_lw + q_capacity + q_wind_solar + q_wind_lw + q_fourth
        if not isfinite(q_total):
            raise ValueError("Flux WISC non fini.")
        return WISCFluxBreakdown(
            q_useful_wm2=q_total,
            q_solar_wm2=q_solar,
            q_temperature_wm2=q_temp,
            q_wind_temperature_wm2=q_wind_temp,
            q_longwave_wm2=q_lw,
            q_capacity_wm2=q_capacity,
            q_wind_solar_wm2=q_wind_solar,
            q_wind_longwave_wm2=q_wind_lw,
            q_fourth_order_wm2=q_fourth,
            iam_beam=iam_beam,
            u_prime_ms=u_prime,
            t_mean_c=float(t_mean_c),
        )
