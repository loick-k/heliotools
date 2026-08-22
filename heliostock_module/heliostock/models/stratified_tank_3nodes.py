"""Three-node stratified daily solar storage tank.

The model is inspired by the multinode approach discussed by Kleinbach,
Beckman and Klein (Solar Energy, 1993): the tank is split into perfectly
mixed horizontal volumes, one energy balance is solved per node, and
temperature inversions are corrected by conservative mixing.

This is a compact 1D approximation for hourly pre-design calculations. It is
not a full TRNSYS reproduction and does not model detailed hydraulics inside
the tank.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

J_PER_KWH = 3.6e6

TankNode = Literal["bottom", "middle", "top"]


@dataclass(frozen=True)
class StratifiedTankState:
    t_bottom_c: float
    t_middle_c: float
    t_top_c: float
    t_mean_c: float
    stored_energy_kwh: float
    useful_energy_available_kwh: float


class StratifiedTank3Nodes:
    """Simple robust stratified tank with bottom, middle and top nodes."""

    def __init__(
        self,
        *,
        volume_m3: float,
        t_init_c: float,
        ua_total_w_per_k: float,
        t_amb_c: float,
        fractions_volume: tuple[float, float, float] = (0.35, 0.30, 0.35),
        rho: float = 1000.0,
        cp: float = 4180.0,
        g_interlayer_w_per_k: float = 2.0,
        t_max_c: float = 80.0,
        t_min_useful_c: float = 25.0,
        mode_charge_solaire: str = "bottom",
        dt_internal_s: float = 300.0,
    ) -> None:
        self.volume_m3 = max(0.0, float(volume_m3))
        self.rho = max(1e-9, float(rho))
        self.cp = max(1e-9, float(cp))
        self.ua_total_w_per_k = max(0.0, float(ua_total_w_per_k))
        self.t_amb_c = float(t_amb_c)
        self.g_interlayer_w_per_k = max(0.0, float(g_interlayer_w_per_k))
        self.t_max_c = float(t_max_c)
        self.t_min_useful_c = float(t_min_useful_c)
        self.mode_charge_solaire = (
            "variable_inlet" if mode_charge_solaire == "variable_inlet" else "bottom"
        )
        self.dt_internal_s = max(1.0, float(dt_internal_s))

        fractions = [max(0.0, float(value)) for value in fractions_volume]
        total_fraction = sum(fractions)
        if total_fraction <= 0.0:
            fractions = [0.35, 0.30, 0.35]
            total_fraction = 1.0
        self.fractions_volume = tuple(value / total_fraction for value in fractions)
        self.masses_kg = [self.volume_m3 * self.rho * fraction for fraction in self.fractions_volume]
        init = min(self.t_max_c, float(t_init_c))
        self.temperatures_c = [init, init, init]  # bottom, middle, top

    def state(self) -> StratifiedTankState:
        mass_total = sum(self.masses_kg)
        if mass_total <= 0.0:
            t_mean = self.t_amb_c
        else:
            t_mean = sum(m * t for m, t in zip(self.masses_kg, self.temperatures_c)) / mass_total
        return StratifiedTankState(
            t_bottom_c=self.temperatures_c[0],
            t_middle_c=self.temperatures_c[1],
            t_top_c=self.temperatures_c[2],
            t_mean_c=t_mean,
            stored_energy_kwh=self.stored_energy_j(self.t_amb_c) / J_PER_KWH,
            useful_energy_available_kwh=self.useful_energy_available_j() / J_PER_KWH,
        )

    def stored_energy_j(self, reference_temp_c: float) -> float:
        return sum(
            mass_kg * self.cp * (temp_c - reference_temp_c)
            for mass_kg, temp_c in zip(self.masses_kg, self.temperatures_c)
        )

    def useful_energy_available_j(self) -> float:
        return sum(
            mass_kg * self.cp * max(0.0, temp_c - self.t_min_useful_c)
            for mass_kg, temp_c in zip(self.masses_kg, self.temperatures_c)
        )

    def apply_losses(self, dt_s: float, t_amb_c: float | None = None) -> float:
        """Apply tank envelope heat transfer.

        Positive returned energy means heat lost by the tank. A negative value
        can occur if a node is colder than ambient and is warmed by the room.
        """

        ambient_c = self.t_amb_c if t_amb_c is None else float(t_amb_c)
        ua_distribution = (0.30, 0.40, 0.30)
        q_loss_total_j = 0.0
        for index, ua_fraction in enumerate(ua_distribution):
            mass_cp = self._mass_cp(index)
            if mass_cp <= 0.0:
                continue
            delta_t_k = self.temperatures_c[index] - ambient_c
            q_raw_j = self.ua_total_w_per_k * ua_fraction * delta_t_k * dt_s
            # The explicit loss step is capped at the energy that would bring
            # the node exactly to ambient. This avoids numerical overshoot for
            # small/high-UA tanks or large internal timesteps.
            q_to_ambient_j = mass_cp * delta_t_k
            if q_raw_j >= 0.0:
                q_loss_j = min(q_raw_j, q_to_ambient_j)
            else:
                q_loss_j = max(q_raw_j, q_to_ambient_j)
            self.temperatures_c[index] -= q_loss_j / mass_cp
            q_loss_total_j += q_loss_j
        return q_loss_total_j

    def apply_interlayer_exchange(self, dt_s: float) -> float:
        """Exchange heat between adjacent layers while conserving energy."""

        exchanged_abs_j = 0.0
        exchanged_abs_j += abs(self._exchange_between(0, 1, self.g_interlayer_w_per_k, dt_s))
        exchanged_abs_j += abs(self._exchange_between(1, 2, self.g_interlayer_w_per_k, dt_s))
        return exchanged_abs_j

    def enforce_stratification(self) -> None:
        """Mix inverted adjacent layers without changing total tank energy.

        This is a weighted isotonic projection from bottom to top. It is the
        three-node equivalent of merging adjacent inverted control volumes
        until the tank is ordered as T_top >= T_middle >= T_bottom.
        """

        blocks = [
            {"indices": [index], "mass": self.masses_kg[index], "temp": self.temperatures_c[index]}
            for index in range(3)
        ]
        index = 0
        while index < len(blocks) - 1:
            current = blocks[index]
            next_block = blocks[index + 1]
            if current["temp"] <= next_block["temp"] + 1e-12:
                index += 1
                continue
            total_mass = current["mass"] + next_block["mass"]
            if total_mass <= 0.0:
                mixed_temp_c = min(current["temp"], next_block["temp"])
            else:
                mixed_temp_c = (
                    current["mass"] * current["temp"] + next_block["mass"] * next_block["temp"]
                ) / total_mass
            blocks[index : index + 2] = [
                {
                    "indices": current["indices"] + next_block["indices"],
                    "mass": total_mass,
                    "temp": mixed_temp_c,
                }
            ]
            index = max(0, index - 1)

        for block in blocks:
            for node_index in block["indices"]:
                self.temperatures_c[node_index] = block["temp"]

    def add_energy_to_node(self, node: TankNode, q_j: float) -> float:
        node_index = {"bottom": 0, "middle": 1, "top": 2}[node]
        return self._add_energy_to_index(node_index, q_j)

    def charge_from_solar(self, q_solar_j: float, t_inlet_c: float | None = None) -> tuple[float, float]:
        if q_solar_j <= 0.0 or self.volume_m3 <= 0.0:
            return 0.0, max(0.0, q_solar_j)
        if self.mode_charge_solaire == "variable_inlet" and t_inlet_c is not None:
            if t_inlet_c >= self.temperatures_c[2]:
                node = "top"
            elif t_inlet_c >= self.temperatures_c[1]:
                node = "middle"
            else:
                node = "bottom"
        else:
            node = "bottom"
        accepted_j = self.add_energy_to_node(node, q_solar_j)
        self.enforce_stratification()
        return accepted_j, max(0.0, q_solar_j - accepted_j)

    def discharge_to_load(
        self,
        q_load_j: float,
        t_cold_c: float,
        t_supply_target_c: float,
        dt_s: float,
    ) -> tuple[float, float]:
        """Deliver useful heat with a simplified draw-off flow.

        Hot water is drawn from the top node while the same mass of cold water
        enters the bottom node. The three perfectly mixed nodes are updated as
        stirred tanks in series. This keeps the model compact while making the
        draw-off more physical than a purely energetic top-to-bottom subtraction.
        """

        if q_load_j <= 0.0 or self.volume_m3 <= 0.0:
            return 0.0, max(0.0, q_load_j)
        cold_c = float(t_cold_c)
        target_delta_k = max(1e-6, float(t_supply_target_c) - cold_c)
        nominal_draw_mass_kg = q_load_j / (self.cp * target_delta_k)
        max_draw_mass_kg = max(0.0, nominal_draw_mass_kg)
        min_node_mass_kg = min((m for m in self.masses_kg if m > 0.0), default=0.0)
        if min_node_mass_kg <= 0.0 or max_draw_mass_kg <= 0.0:
            return 0.0, max(0.0, q_load_j)
        max_chunk_mass_kg = 0.25 * min_node_mass_kg
        chunk_count = max(1, int(max_draw_mass_kg / max(1e-9, max_chunk_mass_kg)) + 1)
        base_chunk_mass_kg = max_draw_mass_kg / chunk_count
        remaining_j = q_load_j
        delivered_j = 0.0
        del dt_s  # The requested hourly/sub-hourly energy already defines the draw mass.

        for _ in range(chunk_count):
            top_temp_c = self.temperatures_c[2]
            useful_delta_k = top_temp_c - cold_c
            if useful_delta_k <= 0.0 or top_temp_c < self.t_min_useful_c:
                break
            chunk_mass_kg = min(base_chunk_mass_kg, remaining_j / (self.cp * useful_delta_k))
            if chunk_mass_kg <= 1e-9:
                break
            delivered_chunk_j = self._apply_draw_mass(chunk_mass_kg, cold_c)
            delivered_j += delivered_chunk_j
            remaining_j = max(0.0, remaining_j - delivered_chunk_j)
            if remaining_j <= 1e-6:
                break

        self.enforce_stratification()
        return delivered_j, max(0.0, q_load_j - delivered_j)

    def step(
        self,
        *,
        q_solar_j: float,
        q_load_j: float,
        dt_s: float,
        t_cold_c: float,
        t_supply_target_c: float,
        t_amb_c: float | None = None,
        t_solar_inlet_c: float | None = None,
        reference_temp_c: float | None = None,
    ) -> dict[str, float]:
        """Advance the tank over one external timestep with internal substeps."""

        reference_c = self.t_amb_c if reference_temp_c is None else float(reference_temp_c)
        e_initial_j = self.stored_energy_j(reference_c)
        n_substeps = max(1, int(round(max(1.0, dt_s) / self.dt_internal_s)))
        sub_dt_s = float(dt_s) / n_substeps
        solar_in_j = max(0.0, q_solar_j) / n_substeps
        load_j = max(0.0, q_load_j) / n_substeps
        accepted_solar_j = 0.0
        rejected_solar_j = 0.0
        delivered_load_j = 0.0
        unmet_load_j = 0.0
        losses_j = 0.0
        interlayer_abs_j = 0.0

        for _ in range(n_substeps):
            accepted, rejected = self.charge_from_solar(solar_in_j, t_inlet_c=t_solar_inlet_c)
            accepted_solar_j += accepted
            rejected_solar_j += rejected
            delivered, unmet = self.discharge_to_load(load_j, t_cold_c, t_supply_target_c, sub_dt_s)
            delivered_load_j += delivered
            unmet_load_j += unmet
            interlayer_abs_j += self.apply_interlayer_exchange(sub_dt_s)
            losses_j += self.apply_losses(sub_dt_s, t_amb_c=t_amb_c)
            self.enforce_stratification()

        e_final_j = self.stored_energy_j(reference_c)
        residual_j = e_initial_j + accepted_solar_j - delivered_load_j - losses_j - e_final_j
        exchanged_j = accepted_solar_j + delivered_load_j + abs(losses_j)
        residual_ratio = abs(residual_j) / exchanged_j if exchanged_j > 1e-9 else 0.0
        return {
            "solar_to_tank_j": accepted_solar_j,
            "solar_rejected_j": rejected_solar_j,
            "load_from_tank_j": delivered_load_j,
            "unmet_load_j": unmet_load_j,
            "losses_j": losses_j,
            "interlayer_exchange_j": interlayer_abs_j,
            "energy_balance_residual_j": residual_j,
            "energy_balance_residual_ratio": residual_ratio,
            "solar_fraction": delivered_load_j / max(1e-9, q_load_j),
        }

    def _mass_cp(self, index: int) -> float:
        return self.masses_kg[index] * self.cp

    def _apply_draw_mass(self, draw_mass_kg: float, t_cold_c: float) -> float:
        draw_mass_kg = max(0.0, float(draw_mass_kg))
        if draw_mass_kg <= 0.0:
            return 0.0
        bottom_mass, middle_mass, top_mass = self.masses_kg
        if min(bottom_mass, middle_mass, top_mass) <= 0.0:
            return 0.0
        draw_mass_kg = min(draw_mass_kg, bottom_mass, middle_mass, top_mass)
        t_bottom, t_middle, t_top = self.temperatures_c
        delivered_j = draw_mass_kg * self.cp * max(0.0, t_top - t_cold_c)
        self.temperatures_c[0] = (
            (bottom_mass - draw_mass_kg) * t_bottom + draw_mass_kg * t_cold_c
        ) / bottom_mass
        self.temperatures_c[1] = (
            (middle_mass - draw_mass_kg) * t_middle + draw_mass_kg * t_bottom
        ) / middle_mass
        self.temperatures_c[2] = (
            (top_mass - draw_mass_kg) * t_top + draw_mass_kg * t_middle
        ) / top_mass
        return delivered_j

    def _add_energy_to_index(self, index: int, q_j: float) -> float:
        mass_cp = self._mass_cp(index)
        if mass_cp <= 0.0 or q_j == 0.0:
            return 0.0
        if q_j > 0.0:
            q_j = min(q_j, mass_cp * max(0.0, self.t_max_c - self.temperatures_c[index]))
        self.temperatures_c[index] += q_j / mass_cp
        return q_j

    def _exchange_between(self, cold_index: int, hot_index: int, g_w_per_k: float, dt_s: float) -> float:
        if g_w_per_k <= 0.0:
            return 0.0
        cold_mass_cp = self._mass_cp(cold_index)
        hot_mass_cp = self._mass_cp(hot_index)
        if cold_mass_cp <= 0.0 or hot_mass_cp <= 0.0:
            return 0.0
        delta_t_k = self.temperatures_c[hot_index] - self.temperatures_c[cold_index]
        if abs(delta_t_k) <= 1e-12:
            return 0.0
        q_raw_j = g_w_per_k * delta_t_k * dt_s
        # The explicit exchange is capped at the energy that would exactly
        # equalize both layers. This prevents numerical overshoot when G or
        # the internal timestep is large compared with the node heat capacity.
        q_equalize_j = delta_t_k / (1.0 / cold_mass_cp + 1.0 / hot_mass_cp)
        if q_raw_j >= 0.0:
            q_to_cold_j = min(q_raw_j, q_equalize_j)
        else:
            q_to_cold_j = max(q_raw_j, q_equalize_j)
        self.temperatures_c[cold_index] += q_to_cold_j / cold_mass_cp
        self.temperatures_c[hot_index] -= q_to_cold_j / hot_mass_cp
        return q_to_cold_j

    def _mix_nodes(self, index_a: int, index_b: int) -> None:
        mass_a = self.masses_kg[index_a]
        mass_b = self.masses_kg[index_b]
        total_mass = mass_a + mass_b
        if total_mass <= 0.0:
            return
        mixed_temp_c = (
            mass_a * self.temperatures_c[index_a] + mass_b * self.temperatures_c[index_b]
        ) / total_mass
        self.temperatures_c[index_a] = mixed_temp_c
        self.temperatures_c[index_b] = mixed_temp_c
