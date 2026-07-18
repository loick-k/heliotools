from heliostock.common.project_store import JsonProjectStore


def test_json_project_store_isolates_projects_by_app_and_user(tmp_path):
    helionop_store = JsonProjectStore("helionop", app_label="HelioNOP", root_dir=tmp_path)
    heliostock_store = JsonProjectStore("heliostock", app_label="HelioStock", root_dir=tmp_path)

    helionop_store.save_project(
        payload={"site": {"project_name": "Projet commun"}},
        owner_email="alice@example.com",
        project_name="Projet commun",
        project_id="aaaaaaaa-0000-0000-0000-000000000000",
    )
    helionop_store.save_project(
        payload={"site": {"project_name": "Projet commun"}},
        owner_email="bob@example.com",
        project_name="Projet commun",
        project_id="bbbbbbbb-0000-0000-0000-000000000000",
    )
    heliostock_store.save_project(
        payload={"name": "Projet commun"},
        owner_email="alice@example.com",
        project_name="Projet commun",
        project_id="cccccccc-0000-0000-0000-000000000000",
    )

    alice_helionop = helionop_store.list_projects(owner_email="alice@example.com")
    bob_helionop = helionop_store.list_projects(owner_email="bob@example.com")
    alice_heliostock = heliostock_store.list_projects(owner_email="alice@example.com")

    assert len(alice_helionop) == 1
    assert len(bob_helionop) == 1
    assert len(alice_heliostock) == 1
    assert alice_helionop[0].payload["app_key"] == "helionop"
    assert alice_heliostock[0].payload["app_key"] == "heliostock"
    assert alice_helionop[0].payload["owner_email"] == "alice@example.com"
    assert bob_helionop[0].payload["owner_email"] == "bob@example.com"


def test_json_project_store_rejects_other_owner(tmp_path):
    store = JsonProjectStore("helionop", app_label="HelioNOP", root_dir=tmp_path)
    path = store.save_project(
        payload={"site": {"project_name": "Privé"}},
        owner_email="alice@example.com",
        project_name="Privé",
        project_id="aaaaaaaa-0000-0000-0000-000000000000",
    )

    try:
        store.load_project(path=path, owner_email="bob@example.com")
    except PermissionError as exc:
        assert "autre utilisateur" in str(exc)
    else:
        raise AssertionError("Le projet d'un autre utilisateur ne doit pas être lisible.")
