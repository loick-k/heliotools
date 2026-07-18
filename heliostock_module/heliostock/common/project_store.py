from __future__ import annotations

from dataclasses import dataclass
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .formatting import normalize_email, owner_slug, safe_slug


HELIOTOOLS_PROJECTS_ROOT = Path.home() / ".heliotools" / "projects"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class ProjectFile:
    path: Path
    payload: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.payload.get("name") or self.payload.get("project_name") or self.path.stem)

    @property
    def updated_at(self) -> str:
        return str(self.payload.get("updated_at") or self.payload.get("saved_at") or "")


class JsonProjectStore:
    """JSON project storage shared by HelioTools applications.

    Layout:
    ~/.heliotools/projects/<app_key>/<owner_email_slug>/<project>.json
    ~/.heliotools/projects/<app_key>/<owner_email_slug>/<project>/inputs/...
    ~/.heliotools/projects/<app_key>/<owner_email_slug>/<project>/results/...

    The payload remains application-specific. This keeps the current JSON
    workflow simple while preparing a future database backend.
    """

    def __init__(
        self,
        app_key: str,
        *,
        app_label: str,
        root_dir: Path = HELIOTOOLS_PROJECTS_ROOT,
    ) -> None:
        self.app_key = safe_slug(app_key)
        self.app_label = str(app_label or app_key)
        self.root_dir = root_dir

    def app_dir(self) -> Path:
        return self.root_dir / self.app_key

    def owner_dir(self, owner_email: str) -> Path:
        return self.app_dir() / owner_slug(owner_email)

    def ensure_owner_dir(self, owner_email: str) -> Path:
        directory = self.owner_dir(owner_email)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def project_path(self, *, owner_email: str, project_id: str, project_name: str) -> Path:
        project_slug = safe_slug(project_name)
        return self.owner_dir(owner_email) / f"{project_slug}_{str(project_id)[:8]}.json"

    def project_artifact_dir(self, path: Path) -> Path:
        """Directory used for application-specific files linked to a project."""

        resolved = self.assert_project_path(path)
        return resolved.with_suffix("")

    def project_inputs_dir(self, path: Path) -> Path:
        return self.project_artifact_dir(path) / "inputs"

    def project_results_dir(self, path: Path) -> Path:
        return self.project_artifact_dir(path) / "results"

    def project_input_path(self, path: Path, filename: str) -> Path:
        directory = self.project_inputs_dir(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / safe_slug(filename, fallback="input")

    def project_result_path(self, path: Path, filename: str) -> Path:
        directory = self.project_results_dir(path)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / safe_slug(filename, fallback="result.json")

    def assert_project_path(self, path: Path) -> Path:
        app_root = self.app_dir().resolve()
        resolved = path.resolve()
        if app_root != resolved and app_root not in resolved.parents:
            raise ValueError(f"Le fichier projet doit se trouver dans l'espace {self.app_label}.")
        return resolved

    def list_projects(self, *, owner_email: str) -> list[ProjectFile]:
        directory = self.owner_dir(owner_email)
        if not directory.exists():
            return []
        projects: list[ProjectFile] = []
        for path in directory.glob("*.json"):
            try:
                payload = self.load_project(path=path, owner_email=owner_email)
            except Exception:
                continue
            projects.append(ProjectFile(path=path, payload=payload))
        return sorted(projects, key=lambda project: project.path.stat().st_mtime, reverse=True)

    def load_project(self, *, path: Path, owner_email: str) -> dict[str, Any]:
        resolved = self.assert_project_path(path)
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Format de projet JSON invalide.")
        if str(payload.get("app_key", self.app_key)) != self.app_key:
            raise ValueError("Ce projet appartient à une autre application.")
        payload_owner = normalize_email(str(payload.get("owner_email", "")))
        expected_owner = normalize_email(owner_email)
        if payload_owner and payload_owner != expected_owner:
            raise PermissionError("Ce projet appartient à un autre utilisateur.")
        return payload

    def save_project(
        self,
        *,
        payload: dict[str, Any],
        owner_email: str,
        project_name: str,
        project_id: str | None = None,
    ) -> Path:
        owner_email = normalize_email(owner_email)
        if not owner_email:
            raise ValueError("Un utilisateur connecté est requis pour enregistrer un projet.")
        project_id = str(project_id or payload.get("project_id") or uuid.uuid4())
        self.ensure_owner_dir(owner_email)
        clean_payload = dict(payload)
        clean_payload.update(
            {
                "schema_version": int(clean_payload.get("schema_version", 1) or 1),
                "app_key": self.app_key,
                "app_label": self.app_label,
                "project_id": project_id,
                "name": str(project_name or clean_payload.get("name") or "Nouveau projet"),
                "owner_email": owner_email,
                "updated_at": now_iso(),
            }
        )
        clean_payload.setdefault("created_at", clean_payload["updated_at"])

        for old_file in self.owner_dir(owner_email).glob(f"*_{project_id[:8]}.json"):
            old_file.unlink(missing_ok=True)

        path = self.project_path(owner_email=owner_email, project_id=project_id, project_name=project_name)
        path.write_text(json.dumps(clean_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
