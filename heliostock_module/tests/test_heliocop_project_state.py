from __future__ import annotations

from datetime import date
import json

import pandas as pd

from heliostock.heliocop.project_state import build_heliocop_state_payload, restore_heliocop_state_payload


def test_heliocop_state_payload_is_json_safe_and_filters_sensitive() -> None:
    session = {
        "heliocop_project_name": "Projet PAC",
        "heliocop_project_date": date(2026, 8, 21),
        "heliocop_v2_table": pd.DataFrame({"A": [1.5], "B": ["x"]}),
        "heliocop_v2_token": "secret",
        "heliocop_v2_password": "secret",
        "other_app_key": "ignored",
    }

    payload = build_heliocop_state_payload(session)
    encoded = json.dumps(payload, ensure_ascii=False)

    assert "secret" not in encoded
    assert "other_app_key" not in payload["state_values"]
    assert "heliocop_project_name" in payload["state_values"]
    assert "heliocop_v2_table" in payload["state_values"]

    restored: dict = {}
    restore_heliocop_state_payload(payload, restored)

    assert restored["heliocop_project_name"] == "Projet PAC"
    assert restored["heliocop_project_date"] == date(2026, 8, 21)
    assert restored["heliocop_v2_table"].to_dict(orient="records") == [{"A": 1.5, "B": "x"}]
