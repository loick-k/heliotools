"""Shared column names for critical HelioStock DataFrames.

Keep this module small and focused on columns used across calculation,
post-processing, parametric studies and borefield-savings checks. Display-only
labels can stay local to the UI modules.
"""

SIMULATION_YEAR = "simulation_year"

DEMAND_HT_KWH = "demand_ht_kwh"
DEMAND_BT_KWH = "demand_bt_kwh"

SOLAR_HT_TO_BUFFER_KWH = "solar_ht_to_buffer_kwh"
SOLAR_HT_FROM_BUFFER_KWH = "solar_ht_from_buffer_kwh"
SOLAR_TO_BTES_KWH = "solar_to_btes_kwh"
SOLAR_HT_BUFFER_LOSS_KWH = "solar_ht_buffer_loss_kwh"

HEAT_BT_FROM_PAC_KWH = "heat_bt_from_pac_kwh"
ELECTRICITY_COMPRESSOR_KWH = "electricity_compressor_kwh"
ELECTRICITY_PAC_TOTAL_KWH = "electricity_pac_total_kwh"
GAS_HT_KWH = "unmet_ht_kwh"
GAS_BT_KWH = "unmet_bt_kwh"

BTES_EXTRACTED_BY_PAC_KWH = "btes_extracted_by_pac_kwh"
SOURCE_TEMP_LIMITED = "source_temp_limited"
SOURCE_TEMP_UNMET_BT_KWH = "source_temp_unmet_bt_kwh"

T_BOREHOLE_WALL_C = "T_paroi_forage_C"
T_SOURCE_PAC_C = "T_source_PAC_C"
T_SOURCE_PAC_FOR_COP_C = "T_source_PAC_pour_COP_C"
T_SOURCE_PAC_END_HOUR_C = "T_source_PAC_fin_heure_C"
T_EVAPORATOR_PAC_C = "T_evaporateur_PAC_C"
T_FLUID_INJECTION_C = "T_fluide_injection_C"
T_FLUID_ENTERING_GEO_EXCHANGER_C = "T_fluide_entree_echangeur_geo_C"

Q_EXTRACTION_W_M = "q_extraction_W_m"
Q_INJECTION_W_M = "q_injection_W_m"
Q_NET_W_M = "q_net_W_m"

SOURCE_TEMP_LIMITED_DISPLAY = "Limite_temperature_source"
SOURCE_TEMP_UNMET_BT_DISPLAY_KWH = "BT_non_couvert_limite_source_kWh"
