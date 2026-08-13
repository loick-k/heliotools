from heliostock.collector_library import COLLECTOR_LIBRARY, DEFAULT_COLLECTOR_NAME, get_collector_reference
from heliostock.common.collector_library import as_heliosolo_capteur_library, make_collector_reference
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


def test_shared_library_exports_heliosolo_legacy_format():
    capteur_library = as_heliosolo_capteur_library()

    assert "SunOptimo" in capteur_library
    assert "245V" in capteur_library["SunOptimo"]
    assert capteur_library["SunOptimo"]["245V"]["surface_utile_m2"] == get_collector_reference("SunOptimo 245V").area_m2
    assert "245V - référence HelioSOLO" in capteur_library["SunOptimo"]


def test_custom_collector_can_be_added_to_shared_library():
    custom = make_collector_reference(
        manufacturer="TestFab",
        model="Capteur 1",
        area_m2=2.8,
        eta0=0.79,
        a1_w_m2_k=3.1,
        a2_w_m2_k2=0.012,
    )
    capteur_library = as_heliosolo_capteur_library(extra_collectors={"TestFab Capteur 1": custom})

    assert get_collector_reference("TestFab Capteur 1", extra_collectors={"TestFab Capteur 1": custom}).area_m2 == 2.8
    assert capteur_library["TestFab"]["Capteur 1"]["n0"] == 0.79
