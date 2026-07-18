from heliostock.collector_library import COLLECTOR_LIBRARY, DEFAULT_COLLECTOR_NAME, get_collector_reference
from heliostock.opportunity_notes.opportunity_model import SizingInputs


def test_common_collector_library_exposes_sunoptimo_default():
    collector = get_collector_reference(DEFAULT_COLLECTOR_NAME)

    assert DEFAULT_COLLECTOR_NAME == "SunOptimo 245V"
    assert DEFAULT_COLLECTOR_NAME in COLLECTOR_LIBRARY
    assert collector.manufacturer == "SunOptimo"
    assert collector.model == "245V"
    assert collector.area_m2 > 0.0
    assert collector.eta0 > 0.0


def test_opportunity_sizing_defaults_use_common_collector_library():
    sizing = SizingInputs()
    collector = get_collector_reference(sizing.collector_name)

    assert sizing.collector_name == DEFAULT_COLLECTOR_NAME
    assert sizing.collector_unit_area_m2 == collector.area_m2

