def test_heliocop_import_is_lazy():
    import heliostock.heliocop as heliocop

    assert hasattr(heliocop, "render_heliocop_app")
