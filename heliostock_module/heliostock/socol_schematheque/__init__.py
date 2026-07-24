def render_socol_schematheque_app() -> None:
    from .streamlit_socol_app import render_socol_schematheque_app as _render

    _render()


def current_socol_payload() -> dict[str, object]:
    from .streamlit_socol_app import current_socol_payload as _current

    return _current()


def restore_socol_state(payload: dict[str, object] | None) -> None:
    from .streamlit_socol_app import restore_socol_state as _restore

    _restore(payload)


__all__ = ["current_socol_payload", "render_socol_schematheque_app", "restore_socol_state"]
