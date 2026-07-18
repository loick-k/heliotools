import pandas as pd

from heliostock.dashboard_data_cleaning import group_small_categories, join_values, to_float, to_year


def test_dashboard_data_cleaning_helpers_are_testable():
    assert to_float("5 000,5 L") == 5000.5
    assert to_year("mise en service 2024") == 2024
    assert join_values(["A", "B"]) == "A, B"
    grouped = group_small_categories(
        pd.DataFrame({"Categorie": ["A", "B", "C"], "Valeur": [95, 3, 2]}),
        "Categorie",
        "Valeur",
        seuil_pct=4.0,
    )
    assert "Autres" in set(grouped["Categorie"])
