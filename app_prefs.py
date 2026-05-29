"""app_prefs.py — Preferencias de la app (JSON simple en el config dir).

Separado de themes/registry.py (que gestiona el theme activo). Aquí viven:
  - flag de onboarding completado (para mostrar el wizard solo la 1ª vez)
  - defaults del formulario Nuevo proyecto (stack/provider/type)

Archivo: <app_config_dir>/preferences.json
"""
from __future__ import annotations

import json

import platform_compat as pc

PREFS_PATH = pc.app_config_dir() / "preferences.json"


def _load() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def get(key: str, default=None):
    return _load().get(key, default)


def set(key: str, value) -> None:  # noqa: A003 (shadow builtin OK here)
    d = _load()
    d[key] = value
    _save(d)


# ── UI mode: 'web' (Neo-Tokyo WebEngine) | 'classic' (QWidgets nativo) ────
def ui_mode(fallback: str = "web") -> str:
    return get("ui_mode", fallback) or fallback


def set_ui_mode(mode: str) -> None:
    set("ui_mode", "classic" if mode == "classic" else "web")


# ── Onboarding ──────────────────────────────────────────────────────────
def onboarding_done() -> bool:
    return bool(get("onboarding_done", False))


def mark_onboarding_done() -> None:
    set("onboarding_done", True)


# ── Defaults del formulario Nuevo proyecto ──────────────────────────────
def default_stack(fallback: str = "nextjs-tailwind") -> str:
    return get("default_stack", fallback) or fallback


def default_provider(fallback: str = "claude") -> str:
    return get("default_provider", fallback) or fallback


def default_type(fallback: str = "") -> str:
    return get("default_type", fallback) or fallback


def set_defaults(stack: str | None = None, provider: str | None = None,
                 type_: str | None = None) -> None:
    d = _load()
    if stack:
        d["default_stack"] = stack
    if provider:
        d["default_provider"] = provider
    if type_:
        d["default_type"] = type_
    _save(d)
