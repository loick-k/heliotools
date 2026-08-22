from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from heliostock.common.auth_store import NeonAuthStore  # noqa: E402


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        users = data.get("users")
        if isinstance(users, list):
            return [item for item in users if isinstance(item, dict)]
        projects = data.get("projects")
        if isinstance(projects, list):
            return [item for item in projects if isinstance(item, dict)]
    return []


def _database_url() -> str:
    return (
        os.environ.get("NEON_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migre les sauvegardes locales ignorées par Git vers Neon. "
            "Le script n'affiche ni email, ni hash, ni URL de connexion."
        )
    )
    parser.add_argument(
        "--users",
        default=str(ROOT / "seed_data" / "users.json"),
        help="Chemin du users.json local restauré depuis l'historique Git.",
    )
    parser.add_argument(
        "--projects",
        default=str(ROOT.parent / "seed_data" / "heliostock_projects.json"),
        help="Chemin optionnel du backup projets JSON.",
    )
    parser.add_argument(
        "--skip-projects",
        action="store_true",
        help="Migre uniquement les comptes utilisateurs.",
    )
    args = parser.parse_args()

    database_url = _database_url()
    if not database_url:
        print("ERREUR: NEON_DATABASE_URL ou DATABASE_URL absent de l'environnement.")
        return 2

    store = NeonAuthStore(database_url)
    status_before = store.status()
    if not status_before.get("reachable"):
        print(f"ERREUR: Neon non joignable ({status_before.get('error') or 'erreur inconnue'}).")
        return 3

    users = _read_json_list(Path(args.users))
    if not users:
        print("ERREUR: aucun compte utilisateur lisible dans le fichier source.")
        return 4
    store.save_users(users)

    migrated_projects = 0
    if not args.skip_projects:
        projects = _read_json_list(Path(args.projects))
        if projects:
            store.save_project_backups(projects)
            migrated_projects = len(projects)

    status_after = store.status()
    print("Migration terminée.")
    print(f"Comptes migrés depuis le fichier local: {len(users)}")
    print(f"Comptes présents dans Neon: {status_after.get('users_count', 0)}")
    print(f"Projets migrés depuis le fichier local: {migrated_projects}")
    print(f"Projets présents dans Neon: {status_after.get('projects_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
