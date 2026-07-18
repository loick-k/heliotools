import heliostock.columns as columns
from heliostock.postprocess import _hourly_results_to_dataframe

from helpers import fake_hourly_result


def test_critical_column_constants_match_hourly_dataframe():
    result = fake_hourly_result(simulation_year=1)
    df = _hourly_results_to_dataframe([result])

    expected = {
        columns.SIMULATION_YEAR,
        columns.T_SOURCE_PAC_C,
        columns.T_SOURCE_PAC_FOR_COP_C,
        columns.T_SOURCE_PAC_END_HOUR_C,
        columns.T_BOREHOLE_WALL_C,
        columns.Q_EXTRACTION_W_M,
        columns.Q_INJECTION_W_M,
        columns.Q_NET_W_M,
        columns.HEAT_BT_FROM_PAC_KWH,
        columns.ELECTRICITY_COMPRESSOR_KWH,
        columns.GAS_HT_KWH,
        columns.GAS_BT_KWH,
        columns.SOLAR_HT_FROM_BUFFER_KWH,
        columns.SOLAR_TO_BTES_KWH,
    }
    assert expected.issubset(df.columns)
