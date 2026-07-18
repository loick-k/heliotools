import importlib.util


def test_import_package_minimal():
    import heliostock

    assert heliostock.__all__ == []
    if importlib.util.find_spec("streamlit") is None:
        return
    from heliostock.streamlit_module import render_heliostock_hourly

    assert callable(render_heliostock_hourly)
