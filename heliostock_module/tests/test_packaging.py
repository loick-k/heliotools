from pathlib import Path


def _module_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_no_nested_project_folder():
    assert not (_module_root() / "heliostock_module").exists()


def test_gitignore_keeps_caches_and_local_secrets_out_of_repo():
    gitignore = (_module_root().parent / ".gitignore").read_text(encoding="utf-8")

    required_patterns = [
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".streamlit/secrets.toml",
        ".env",
        ".env.*",
    ]

    for pattern in required_patterns:
        assert pattern in gitignore


def test_no_mojibake_strings():
    root = _module_root()
    patterns = (
        chr(0x00C3),
        chr(0x00C2),
        "\u00e2\u20ac\u2122",
        "\u00e2\u20ac\u201c",
        "\u00e2\u20ac\u201d",
        "\u00e2\u20ac\u0153",
        "\u00e2\u20ac",
    )
    offenders: list[str] = []
    for path in root.rglob("*"):
        if path.suffix.lower() not in {".py", ".md", ".txt"}:
            continue
        if any(part in {"__pycache__", ".pytest_cache", ".git"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if any(pattern in text for pattern in patterns):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_no_advanced_btes_indicators_in_public_outputs():
    root = _module_root()
    scanned_paths = [
        root / "heliostock" / "ui_results.py",
        root / "heliostock" / "postprocess.py",
        root / "heliostock" / "scenario_metrics.py",
        root / "heliostock" / "scenarios.py",
        root / "README.md",
        root / "NOTICE_MODELE_HELIOSTOCK.md",
    ]
    forbidden_terms = [
        "ratio_injection_extraction",
        "ratio injection/extraction",
        "eta_btes",
        "eta_BTES",
        "geo_field_mode",
        "GSHP",
        "BTES-like",
        "BTES_like",
        "classification BTES",
        "type fonctionnement champ",
    ]

    offenders: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for term in forbidden_terms:
            if term.lower() in lowered:
                offenders.append(f"{path.relative_to(root)}: {term}")

    assert offenders == []
