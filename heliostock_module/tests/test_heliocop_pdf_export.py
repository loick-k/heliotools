from heliostock.heliocop.pdf_export import build_heliocop_overview_pdf


def test_heliocop_pdf_export_builds_valid_pdf():
    payload = {
        "app": "HelioCOP",
        "mode": "profil_horaire",
        "project": {
            "name": "Projet test PAC solaire",
            "client": "Maitre d'ouvrage test",
            "city": "Nantes",
            "typology": "Station de lavage poids lourds",
        },
        "cold_water_mode": "Methode ESM2",
        "profile": {
            "source_name": "profil_test.xlsx",
            "annual_energy_mwh": 120.0,
            "peak_hourly_kw": 48.0,
        },
        "target_storage_l_eq60": 5000.0,
        "selected_tank": {"label": "2 x 2500 L", "total_volume_l": 5000.0},
        "selected_pac": {
            "brand": "Marque test",
            "model": "PAC-80",
            "unit_count": 1,
            "installed_power_kw": 80.0,
        },
        "source_type": "Capteurs solaires PVT",
        "source_surface_m2": 240.0,
        "profile_simulation": {
            "coverage_fraction": 0.98,
            "min_soc_fraction": 0.22,
            "equivalent_full_load_hours": 1500.0,
        },
        "economics": {
            "annual_ecs_need_mwh": 120.0,
            "system_cop_including_aux": 3.2,
            "pac_electricity_mwh": 38.0,
            "gas_backup_heat_mwh": 5.0,
            "heat_cost_eur_mwh": 142.0,
            "average_reference_heat_cost_eur_mwh": 175.0,
            "p1_eur_mwh": 64.0,
            "p2_eur_mwh": 16.0,
            "p4_eur_mwh": 62.0,
            "capex_mid_eur": 180000.0,
            "estimated_aid_eur": 52000.0,
            "net_investment_eur": 128000.0,
            "annual_savings_eur": 9000.0,
            "analysis_years": 20,
            "monthly_rows": [
                {
                    "month": month,
                    "heat_mwh": 10.0,
                    "gas_backup_heat_mwh": 0.4,
                    "cop_system": 3.0,
                }
                for month in (
                    "Janvier",
                    "Fevrier",
                    "Mars",
                    "Avril",
                    "Mai",
                    "Juin",
                    "Juillet",
                    "Aout",
                    "Septembre",
                    "Octobre",
                    "Novembre",
                    "Decembre",
                )
            ],
        },
    }

    pdf_bytes = build_heliocop_overview_pdf(payload)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 1000
