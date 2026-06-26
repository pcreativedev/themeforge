#!/usr/bin/env python3
"""
ThemeForge — builder de plantillas para ThemeForest.

GUI PyQt6 con tres modos:

  1) Desde cero            : scaffolding del stack + agente AI.
  2) Recrear referencia    : el usuario aporta una referencia (carpeta local,
                             .zip o URL); el builder la prepara en `reference/`
                             e indica al agente que la estudie y reimplemente
                             en el stack elegido.
  3) Trabajar sobre repo   : clona un repo existente de GitHub y abre el
                             agente sobre él para actualizar/añadir funciones.

Además permite crear un repo nuevo privado en GitHub al terminar el setup.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Render por software ANTES de importar Qt ─────────────────────────────
# QtWebEngine deja la ventana COMPLETAMENTE en negro en entornos sin GPU
# (VMs, RDP, servidores). La env var QT_OPENGL tiene que estar puesta ANTES
# del primer import de Qt — por eso esto va aquí arriba y NO en main().
# Se activa con THEMEFORGE_SOFTWARE_GL=1 (override) o auto-detectando un
# adaptador de vídeo virtual en el registro de Windows.
def _detect_software_gl() -> bool:
    val = os.environ.get("THEMEFORGE_SOFTWARE_GL")
    if val is not None:
        return val.strip() == "1"
    if sys.platform.startswith("win"):
        try:
            import winreg
            base = (r"SYSTEM\CurrentControlSet\Control\Class"
                    r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
                idx = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, idx)
                    except OSError:
                        break
                    idx += 1
                    if not sub.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(k, sub) as sk:
                            desc = str(winreg.QueryValueEx(sk, "DriverDesc")[0]).lower()
                    except OSError:
                        continue
                    markers = ("virtualbox", "vmware", "qemu", "virtio",
                               "parallels", "basic display", "standard vga",
                               "red hat", "hyper-v")
                    if any(m in desc for m in markers):
                        return True
        except Exception:
            pass
    return False


USE_SOFTWARE_GL = _detect_software_gl()
if USE_SOFTWARE_GL:
    os.environ["QT_OPENGL"] = "software"
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --disable-gpu-compositing --in-process-gpu",
    )


def _add_bundled_tools_to_path() -> None:
    """Si el instalador trae Node y git portables (carpeta `vendor/`), los
    añade al PATH del proceso para que estén disponibles sin descargar.

    El build de Windows (build-windows.yml) descarga Node portable + MinGit
    en `vendor/node` y `vendor/git` y los empaqueta con `--add-data`. En
    PyInstaller onedir/onefile esos datos cuelgan de `sys._MEIPASS`.
    Corriendo desde source no hay `vendor/` → no-op (se descargan al vuelo).
    """
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    vendor = base / "vendor"
    if not vendor.is_dir():
        return
    candidates = [
        vendor / "node",                  # node.exe + npm.cmd
        vendor / "git" / "bin",           # bash.exe + sh.exe + git.exe (PortableGit)
        vendor / "git" / "cmd",           # git.exe
        vendor / "git" / "usr" / "bin",   # utils unix: ls, cat, grep, etc.
        vendor / "git" / "mingw64" / "bin",
    ]
    extra = [str(d) for d in candidates if d.is_dir()]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")


def _add_user_bin_dirs_to_path() -> None:
    """Añade al PATH las rutas donde los instaladores de CLIs colocan los
    binarios pero que NO suelen estar en el PATH del sistema. Así ThemeForge
    detecta los CLIs recién instalados sin que el usuario reinicie el shell:

      - ~/.local/bin      → Claude Code (instalador nativo), Codex, pipx
      - %APPDATA%/npm      → paquetes npm globales en Windows (gemini, opencode)
      - ~/.npm-global/bin  → npm global con prefix custom (Linux/Mac)
      - ~/.bun/bin         → instalaciones vía bun
    """
    home = Path.home()
    dirs = [home / ".local" / "bin"]
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            dirs.append(Path(appdata) / "npm")
    else:
        dirs += [home / ".npm-global" / "bin", home / ".bun" / "bin"]
    extra = [str(d) for d in dirs if d.is_dir()]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")


def _add_macos_brew_to_path() -> None:
    """En macOS las apps lanzadas desde Finder/Dock NO heredan el PATH del
    shell de login, así que `/opt/homebrew/bin` (Apple Silicon) o
    `/usr/local/bin` (Intel) NO están en el PATH y la app no encuentra `brew`
    ni nada instalado con él (todo sale como "no instalado"). Añadimos las
    rutas estándar de Homebrew + los `bin` de las fórmulas keg-only que sí
    instalamos (python@3.12, openjdk, ruby), que brew NO enlaza a <prefix>/bin.
    Corriendo en Linux/Windows → no-op."""
    if sys.platform != "darwin":
        return
    candidates = [
        "/opt/homebrew/bin", "/opt/homebrew/sbin",   # Apple Silicon
        "/usr/local/bin", "/usr/local/sbin",         # Intel
    ]
    for prefix in ("/opt/homebrew", "/usr/local"):
        candidates += [
            f"{prefix}/opt/python@3.12/libexec/bin",  # python keg-only
            f"{prefix}/opt/openjdk/bin",              # java keg-only
            f"{prefix}/opt/ruby/bin",                 # ruby keg-only
        ]
    extra = [d for d in candidates if os.path.isdir(d)]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + os.environ.get("PATH", "")


_add_bundled_tools_to_path()
_add_macos_brew_to_path()
_add_user_bin_dirs_to_path()

# IMPORTANTE: QtWebEngineWidgets debe importarse ANTES de crear QApplication,
# si no, falla con "QtWebEngineWidgets must be imported... before a
# QCoreApplication instance is created". Lo hacemos aquí aunque solo lo use
# project_window.py más adelante.
try:
    from PyQt6 import QtWebEngineWidgets  # noqa: F401
except Exception:
    QtWebEngineWidgets = None

from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from stacks import AGENTS, STACKS, TEMPLATE_TYPES, TEMPLATE_NICHES
from stack_picker import StackPickerDialog
import ai_providers as aip
import platform_compat as pc
from provider_picker import ProviderPicker

# Mantenemos referencias vivas a las ProjectWindow abiertas para que Qt no las
# recolecte mientras el user las usa.
_OPEN_PROJECT_WINDOWS: list = []
_MAIN_APP = None  # ref a la ThemeForgeApp principal (para enfocarla desde otras ventanas)


# Skills que ThemeForge instala (autoskills → `.agents/skills/` + symlinks en
# `.claude/skills/`; uipro-cli → carpeta `ui-ux-pro-max`). Una skill genérica de
# un fork (Medusa: reviewing-prs, writing-docs…) NO cuenta.
_UIPRO_HINTS = ("ui-ux-pro", "uiux-pro", "uipro")
# Señales de que hay un stack escaffoldeado (mismo set que el script de setup).
_STACK_MARKERS = (
    "package.json", "composer.json", "pubspec.yaml", "Cargo.toml", "go.mod",
    "pyproject.toml", "Gemfile", "theme.json", "style.css", "build.gradle",
)


def _has_real_skills(root: Path) -> bool:
    """¿Hay skills de autoskills/uipro (no genéricas de un fork)? Raíz + apps/* + packages/*."""
    roots = [root]
    for sub in ("apps", "packages"):
        d = root / sub
        if d.is_dir():
            try:
                roots += [p for p in d.iterdir() if p.is_dir()]
            except OSError:
                pass
    for r in roots:
        ag = r / ".agents" / "skills"
        try:
            if ag.is_dir() and any(ag.iterdir()):
                return True
        except OSError:
            pass
        try:
            for e in (r / ".claude" / "skills").iterdir():
                if e.is_symlink() or any(h in e.name.lower() for h in _UIPRO_HINTS):
                    return True
        except OSError:
            continue
    return False


def _maybe_bootstrap_skills(root: Path) -> bool:
    """Si el proyecto tiene stack pero NO las skills de ThemeForge (autoskills/uipro),
    lánzalas en segundo plano (detached) — así un proyecto adoptado en la galería sin
    pasar por el setup deja de quejarse. Idempotente vía marcador (no re-lanza aunque
    la instalación tarde). NO bloquea la apertura de la ventana."""
    import subprocess
    try:
        if _has_real_skills(root):
            return False
        marker = root / ".themeforge" / ".skills-bootstrap"
        if marker.exists():  # ya lanzado antes (puede seguir corriendo)
            return False
        # ¿hay stack escaffoldeado hasta 3 niveles?
        has_stack = False
        for m in _STACK_MARKERS:
            try:
                if next(root.glob(m), None) or next(root.glob(f"*/{m}"), None) \
                        or next(root.glob(f"*/*/{m}"), None):
                    has_stack = True
                    break
            except OSError:
                continue
        if not has_stack or not shutil.which("npx"):
            return False
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("autoskills+uipro lanzados al abrir desde galería\n")
        log = root / ".themeforge" / "skills-install.log"
        cmd = ('echo "=== autoskills ==="; npx --yes autoskills -a claude 2>&1; '
               'echo "=== uipro-cli ==="; npx --yes uipro-cli init --ai claude 2>&1; '
               'echo "=== DONE ==="')
        with open(log, "w") as fh:
            subprocess.Popen(["bash", "-lc", cmd], cwd=str(root),
                             stdout=fh, stderr=subprocess.STDOUT,
                             start_new_session=True)
        return True
    except Exception as e:
        print(f"[wiring] bootstrap skills falló: {e}", file=sys.stderr)
        return False


def _ensure_project_wiring(project_path: Path) -> list[str]:
    """Auto-cablea el wiring que ThemeForge espera (context/, .mcp.json, skills)
    en proyectos que NO pasaron por el setup — symlinks, adopciones externas,
    repos clonados a mano. El init-prompt del agente asume que existen; sin esto
    se queja de que `context/` no existe y las skills/MCP no saltan.
    NO-fatal, idempotente (solo crea lo que falta), resuelve symlinks."""
    done: list[str] = []
    try:
        root = Path(project_path).resolve()  # sigue symlinks → opera sobre el real
        if not root.is_dir():
            return done
        # Solo proyectos "reales" (señal de que el agente los abrirá con init-prompt)
        if not any((root / m).exists() for m in ("CLAUDE.md", "AGENTS.md", "package.json")):
            return done
        # 1. context/ — poblar con los MDs de contexto (privados preferidos)
        ctx = root / "context"
        if not ctx.exists():
            ctx.mkdir(parents=True, exist_ok=True)
            n = 0
            for src_dir in (CONTEXT_PRIVATE_DIR, CONTEXT_DIR):
                if src_dir and src_dir.is_dir():
                    for md in sorted(src_dir.glob("*.md")):
                        dst = ctx / md.name.replace(".template.md", ".md")
                        if not dst.exists():
                            try:
                                shutil.copy(md, dst); n += 1
                            except Exception:
                                pass
            if n:
                done.append(f"context/ ({n} MDs)")
        # 2. .mcp.json — MCPs (magic/21st.dev, etc.) si falta
        if not (root / ".mcp.json").exists():
            try:
                import web_enhancements as we
                we.ensure_mcps(root)
                if (root / ".mcp.json").exists():
                    done.append(".mcp.json")
            except Exception:
                pass
        # 3. skills — descubribles en .claude/skills si falta
        if not (root / ".claude" / "skills").exists():
            try:
                import skills_wireup as sw
                sw.ensure_skills_discoverable(root)
                if (root / ".claude" / "skills").exists():
                    done.append("skills")
            except Exception:
                pass
        # 4. autoskills/uipro — si hay stack pero faltan, instalarlas en background
        #    (proyectos adoptados en la galería sin pasar por el setup).
        if _maybe_bootstrap_skills(root):
            done.append("skills-bootstrap (autoskills+uipro en background)")
    except Exception as e:
        print(f"[wiring] auto-cableado: {e}", file=sys.stderr)
    return done


def open_project_window(project_path: Path, initial_cmd: str | None = None,
                        provider_key: str | None = None,
                        auto_agent: bool = False) -> None:
    """Abre una ProjectWindow para el proyecto dado. Importa lazy para
    no cargar QtWebEngine si nadie la usa. Si se pasa `initial_cmd`,
    se ejecuta en la primera pestaña de la terminal embebida. Si se
    pasa `provider_key`, solo se abre la tab del CLI de ese provider."""
    # Auto-cablea el wiring faltante (context/skills/MCP) antes de lanzar el
    # agente — así un proyecto que entró a la galería sin pasar por el setup
    # (symlink/adopción) se abre listo sin quejarse de `context/`.
    _wired = _ensure_project_wiring(project_path)
    if _wired:
        print(f"[wiring] cableado al abrir {Path(project_path).name}: {', '.join(_wired)}", file=sys.stderr)
    try:
        from project_window import ProjectWindow
    except Exception as e:
        QMessageBox.critical(None, "ThemeForge", f"No se pudo cargar ProjectWindow:\n{e}")
        return
    w = ProjectWindow(project_path, initial_cmd=initial_cmd,
                      provider_key=provider_key, auto_agent=auto_agent)
    _OPEN_PROJECT_WINDOWS.append(w)
    w.destroyed.connect(lambda *_: _OPEN_PROJECT_WINDOWS.remove(w) if w in _OPEN_PROJECT_WINDOWS else None)
    w.show()
    w.raise_()
    w.activateWindow()


def focus_new_project() -> bool:
    """Trae al frente la ventana principal y abre la pestaña New project, para
    poder crear otro proyecto sin cerrar los que ya están funcionando."""
    if _MAIN_APP is None:
        return False
    _MAIN_APP.show()
    _MAIN_APP.raise_()
    _MAIN_APP.activateWindow()
    try:
        _MAIN_APP.tabs.setCurrentIndex(0)  # pestaña New project
    except Exception:
        pass
    return True


HOME = Path.home()
BUILDER_DIR = HOME / "Proyectos" / "themeforge"
PROJECTS_DIR = HOME / "Proyectos" / "themes"
CONTEXT_DIR = BUILDER_DIR / "context"
CONFIG_DIR = pc.app_config_dir()
THUMBNAILS_DIR = pc.app_cache_dir() / "thumbnails"
# Carpeta opcional con versiones privadas de los MDs de context/.
# Si un MD existe aquí, ThemeForge lo prefiere sobre el del repo. Útil
# para que el usuario tenga su versión REAL (con secrets, estrategia,
# análisis de mercado real) fuera del repo público.
CONTEXT_PRIVATE_DIR = CONFIG_DIR / "context-private"
FAVORITES_FILE = CONFIG_DIR / "favorites.json"

# Plugin opcional con integraciones privadas de agencia (pestañas Leads/Catálogo/
# Locales + filtro de la Galería). Ausente en el repo OSS → esas piezas no
# aparecen. Todo el naming privado vive en ese módulo (gitignored).
try:
    import themeforge_private as _np
except Exception:
    _np = None


# Patrones de API keys conocidas — para redactar de stderr antes de
# mostrarlos en el UI (defensa en profundidad, no debería pasar pero).
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{20,}"),     # Anthropic
    re.compile(r"sk-proj-[a-zA-Z0-9_\-]{20,}"),    # OpenAI proj
    re.compile(r"sk-[a-zA-Z0-9_\-]{40,}"),         # OpenAI clásica + genéricas
    re.compile(r"sk-or-v\d+-[a-zA-Z0-9_\-]{40,}"), # OpenRouter
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),         # Google API keys
    re.compile(r"gho_[A-Za-z0-9]{36}"),            # GitHub OAuth
    re.compile(r"ghp_[A-Za-z0-9]{36}"),            # GitHub PAT
    re.compile(r"glpat-[A-Za-z0-9_\-]{20,}"),      # GitLab PAT
]


def _redact_secrets(text: str) -> str:
    """Reemplaza cualquier API key conocida con un placeholder.
    Usado al pintar stderr/logs del subproceso de IA en la UI."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("<REDACTED-API-KEY>", text)
    return text


def collect_context_mds() -> list[Path]:
    """Devuelve los .md a copiar al proyecto generado.

    Discovery dinámico (no hay nombres hardcoded en el código público):

    1. Recoge todos los `*.md` de `~/.config/themeforge/context-private/`
       (versiones REALES del usuario con secrets / estrategia / etc.).
    2. Completa con los `*.md` y `*.template.md` del repo `context/`
       que NO tengan ya equivalente privado.

    Comparación por stem (sin extensión y sin `.template`). Eso permite
    que `MARKET-RESEARCH.md` privado oculte `MARKET-RESEARCH.template.md`
    público.
    """
    def _canon_stem(name: str) -> str:
        if name.endswith(".template.md"):
            return name[:-len(".template.md")]
        if name.endswith(".md"):
            return name[:-3]
        return name

    seen_stems: set[str] = set()
    out: list[Path] = []

    if CONTEXT_PRIVATE_DIR.is_dir():
        for f in sorted(CONTEXT_PRIVATE_DIR.glob("*.md")):
            seen_stems.add(_canon_stem(f.name))
            out.append(f)

    if CONTEXT_DIR.is_dir():
        for f in sorted(CONTEXT_DIR.glob("*.md")):
            stem = _canon_stem(f.name)
            if stem in seen_stems:
                continue
            seen_stems.add(stem)
            out.append(f)
    return out


def load_favorites() -> set[str]:
    try:
        return set(json.loads(FAVORITES_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_favorites(favs: set[str]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        FAVORITES_FILE.write_text(json.dumps(sorted(favs), indent=2))
    except Exception:
        pass


# ── Metadata por proyecto (tags, archived, etc.) ─────────────────────
# Persistido en ~/.config/themeforge/projects-meta.json. Estructura:
#   { "<slug>": { "tags": ["foo","bar"], "archived": bool, ... } }
PROJECTS_META_FILE = CONFIG_DIR / "projects-meta.json"


def load_projects_meta() -> dict[str, dict]:
    try:
        data = json.loads(PROJECTS_META_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_projects_meta(meta: dict[str, dict]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PROJECTS_META_FILE.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def get_project_tags(slug: str) -> list[str]:
    return list((load_projects_meta().get(slug) or {}).get("tags") or [])


def set_project_tags(slug: str, tags: list[str]) -> None:
    meta = load_projects_meta()
    entry = meta.get(slug) or {}
    # Normalizar: lowercase, sin espacios extra, sin duplicados, ordenado.
    norm = sorted({t.strip().lower().lstrip("#") for t in tags if t.strip()})
    if norm:
        entry["tags"] = norm
    else:
        entry.pop("tags", None)
    if entry:
        meta[slug] = entry
    else:
        meta.pop(slug, None)
    save_projects_meta(meta)


# ── Thumbnails de proyectos (cards de la galería) ────────────────────
# Tamaño objetivo: 200×120 (ratio ~5:3 que combina bien con cards
# 220×180). Si hay screenshot real cacheado lo usamos; si no,
# generamos un placeholder dibujado con QPainter (gradient + iniciales
# del proyecto + abbreviation del stack). El propio ProjectWindow
# hookea el botón 📸 para guardar copia como thumbnail del proyecto.

THUMB_WIDTH = 200
THUMB_HEIGHT = 120

# Paleta determinista por stack — colores marca-friendly que no chocan
# con el dark theme de KDE. Si el stack no está aquí, se calcula un
# color por hash del nombre.
_STACK_COLORS: dict[str, tuple[int, int, int]] = {
    "nextjs-tailwind":     (0, 0, 0),
    "nextjs-shadcn":       (24, 24, 27),
    "nextjs-mantine":      (51, 154, 240),
    "nextjs-heroui":       (236, 72, 153),
    "astro-tailwind":      (255, 90, 30),
    "astro-shadcn":        (255, 117, 64),
    "wordpress-block":     (33, 117, 155),
    "wordpress-plugin":    (33, 117, 155),
    "shopify-liquid":      (149, 191, 71),
    "html-tailwind":       (56, 189, 248),
    "html-bootstrap":      (124, 58, 237),
    "react-vite-tailwind": (97, 218, 251),
    "vue3-vite-tailwind":  (65, 184, 131),
    "angular-tailwind":    (221, 0, 49),
    "laravel-inertia":     (255, 45, 32),
    "sveltekit-tailwind":  (255, 62, 0),
    "nuxt-tailwind":       (0, 220, 130),
    "remix-tailwind":      (227, 90, 64),
    "qwik-tailwind":       (172, 113, 234),
    "solidstart-tailwind": (43, 138, 218),
    "flutter":             (66, 165, 245),
    "tauri-react":         (255, 192, 30),
    "electron-react":      (51, 153, 255),
    "expo-rn-nativewind":  (0, 0, 0),
    "expo-rn-router":      (28, 28, 28),
    "ionic-capacitor":     (54, 138, 247),
    "kotlin-compose":      (123, 31, 162),
    "phoenix-liveview":    (252, 89, 70),
    "rails-tailwind":      (204, 33, 30),
    "go-fiber":            (0, 173, 216),
    "rust-axum":           (255, 137, 36),
    "spring-boot":         (109, 179, 63),
    "ktor-server":         (74, 60, 144),
    "fastapi":             (5, 153, 138),
    "django-tailwind":     (9, 88, 67),
    "hono-bun":            (251, 240, 218),
    "hono-cloudflare":     (244, 145, 28),
    "nestjs-prisma":       (224, 35, 77),
    "bun-elysia":          (251, 240, 218),
    "deno-fresh":          (255, 255, 255),
    "t3-stack":            (104, 51, 162),
    "docusaurus":          (62, 90, 184),
    "vitepress":           (89, 211, 154),
    "starlight":           (190, 117, 226),
    "hugo":                (255, 64, 129),
    "eleventy":            (255, 209, 60),
    "payload-cms":         (0, 0, 0),
    "strapi":              (74, 33, 255),
    "medusa":              (50, 50, 50),
    "storybook-react":     (255, 80, 130),
    "react-email":         (37, 99, 235),
    "phaser-vite-ts":      (252, 132, 23),
    "pixijs-vite-ts":      (232, 31, 99),
    "r3f-vite-ts":         (255, 161, 0),
    "sanity-studio":       (242, 49, 73),
    "directus":            (100, 70, 255),
    "plasmo":              (245, 102, 116),
    "wxt":                 (123, 207, 88),
}


def _color_for_stack(stack_key: str) -> tuple[int, int, int]:
    if stack_key in _STACK_COLORS:
        return _STACK_COLORS[stack_key]
    # Fallback determinista por hash: HSL → RGB sencillo (saturación
    # media, lightness oscuro para que el texto blanco se vea bien).
    h = abs(hash(stack_key)) % 360
    s, l = 0.55, 0.35
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def get_or_make_thumbnail(slug: str, stack_key: str, project_name: str):
    """Devuelve un QPixmap THUMB_WIDTH×THUMB_HEIGHT.

    1. Si existe `~/.cache/themeforge/thumbnails/<slug>.png` → lo carga.
    2. Si no → genera un placeholder dibujado: gradient con el color
       del stack + iniciales del proyecto centradas + label del stack
       abajo.
    """
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QLinearGradient, QFont, QPen
    from PyQt6.QtCore import Qt as _Qt, QRect

    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    cached = THUMBNAILS_DIR / f"{slug}.png"
    if cached.is_file():
        pm = QPixmap(str(cached))
        if not pm.isNull():
            return pm.scaled(
                THUMB_WIDTH, THUMB_HEIGHT,
                _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                _Qt.TransformationMode.SmoothTransformation,
            )

    # Placeholder dibujado
    pm = QPixmap(THUMB_WIDTH, THUMB_HEIGHT)
    r, g, b = _color_for_stack(stack_key)
    color_top = QColor(r, g, b)
    color_bottom = QColor(max(0, r - 40), max(0, g - 40), max(0, b - 40))
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        grad = QLinearGradient(0, 0, 0, THUMB_HEIGHT)
        grad.setColorAt(0, color_top)
        grad.setColorAt(1, color_bottom)
        p.fillRect(0, 0, THUMB_WIDTH, THUMB_HEIGHT, grad)

        # Iniciales del proyecto (1-2 letras grandes en el centro)
        words = re.split(r"[-_\s]+", project_name or slug)
        initials = "".join(w[:1].upper() for w in words[:2] if w) or "?"
        if len(initials) == 1:
            initials = (project_name or slug)[:2].upper()
        font = QFont()
        font.setPointSize(48)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255, 220)))
        p.drawText(QRect(0, 0, THUMB_WIDTH, THUMB_HEIGHT - 18),
                   _Qt.AlignmentFlag.AlignCenter, initials)

        # Label del stack abajo
        stack_label = stack_key.replace("-", " ") if stack_key and stack_key != "none" else "no stack"
        font.setPointSize(9)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255, 160)))
        p.drawText(QRect(0, THUMB_HEIGHT - 20, THUMB_WIDTH, 18),
                   _Qt.AlignmentFlag.AlignCenter, stack_label[:30])
    finally:
        p.end()
    return pm


def save_project_thumbnail(slug: str, source_pixmap) -> None:
    """Guarda `source_pixmap` (cualquier tamaño) como thumbnail del
    proyecto. Lo redimensiona a THUMB_WIDTH×THUMB_HEIGHT manteniendo
    aspect ratio (crop). Útil para hookear desde el botón 📸 del
    ProjectWindow."""
    from PyQt6.QtCore import Qt as _Qt
    if source_pixmap is None or source_pixmap.isNull():
        return
    THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
    out = source_pixmap.scaled(
        THUMB_WIDTH, THUMB_HEIGHT,
        _Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        _Qt.TransformationMode.SmoothTransformation,
    )
    # Crop centrado si quedó más grande que el target
    if out.width() > THUMB_WIDTH or out.height() > THUMB_HEIGHT:
        x = max(0, (out.width() - THUMB_WIDTH) // 2)
        y = max(0, (out.height() - THUMB_HEIGHT) // 2)
        out = out.copy(x, y, THUMB_WIDTH, THUMB_HEIGHT)
    out.save(str(THUMBNAILS_DIR / f"{slug}.png"), "PNG", 92)


def last_ai_activity(project_path: Path) -> float | None:
    """Devuelve el unix timestamp (segundos) de la última sesión de
    IA en este proyecto, o None si no hay sesiones detectables.

    Hoy busca en:
      ~/.claude/projects/<encoded-path>/*.jsonl
    donde `encoded-path` es el path absoluto del proyecto con `/`
    reemplazados por `-`. Es el formato que usa Claude Code.

    En el futuro se puede ampliar a Codex / Gemini / OpenCode cuando
    se conozcan sus rutas equivalentes.
    """
    encoded = str(project_path.resolve()).replace("/", "-")
    claude_dir = Path.home() / ".claude" / "projects" / encoded
    if not claude_dir.is_dir():
        return None
    best = 0.0
    try:
        for f in claude_dir.iterdir():
            if f.is_file() and f.name.endswith(".jsonl"):
                m = f.stat().st_mtime
                if m > best:
                    best = m
    except Exception:
        return None
    return best or None


def format_relative_time(ts: float | None) -> str:
    """Formato 'hace X min/h/d' a partir de un unix timestamp."""
    if ts is None:
        return "—"
    import time
    diff = time.time() - ts
    if diff < 0:
        return "en el futuro?"
    if diff < 60:
        return "hace un momento"
    if diff < 3600:
        return f"hace {int(diff // 60)} min"
    if diff < 86400:
        return f"hace {int(diff // 3600)} h"
    if diff < 86400 * 30:
        return f"hace {int(diff // 86400)} d"
    if diff < 86400 * 365:
        return f"hace {int(diff // (86400 * 30))} meses"
    return f"hace {int(diff // (86400 * 365))} años"


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _stop_containers_using_path(target_path) -> list[str]:
    """Detecta containers Docker con bind-mounts dentro de target_path
    y los elimina con docker rm -f. Devuelve la lista de IDs eliminados.

    Útil para borrar proyectos que tienen docker-compose con servicios
    que escribieron archivos como root (meilisearch, mysql, postgres
    no-themeforge, etc.) — necesario antes de rmtree.
    """
    if not shutil.which("docker"):
        return []
    target = str(target_path).rstrip("/")
    try:
        r = subprocess.run(
            ["docker", "ps", "-aq"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return []
        ids = r.stdout.split()
        killed = []
        for cid in ids:
            ins = subprocess.run(
                ["docker", "inspect", "--format", "{{range .Mounts}}{{.Source}}\n{{end}}", cid],
                capture_output=True, text=True, timeout=10,
            )
            if ins.returncode != 0:
                continue
            mounts = [m.strip() for m in ins.stdout.splitlines() if m.strip()]
            if any(m == target or m.startswith(target + "/") for m in mounts):
                subprocess.run(
                    ["docker", "rm", "-f", cid],
                    capture_output=True, text=True, timeout=30,
                )
                killed.append(cid)
        return killed
    except Exception:
        return []


def gh_username() -> str | None:
    """Devuelve el usuario activo de GitHub CLI, o None."""
    try:
        out = subprocess.check_output(
            ["gh", "api", "user", "--jq", ".login"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        return out or None
    except Exception:
        return None


def detect_stack(path: Path) -> str:
    """Heurística rápida para identificar el stack de un proyecto."""
    # PRIORIDAD: Laravel (artisan + composer.json) — antes que cualquier
    # check de package.json, porque muchos Laravel modernos traen Vite.
    if (path / "artisan").is_file() and (path / "composer.json").is_file():
        try:
            data = json.loads((path / "composer.json").read_text(errors="ignore", encoding="utf-8"))
            req = {**(data.get("require") or {}), **(data.get("require-dev") or {})}
            if "laravel/framework" in req or "laravel/laravel" in req:
                return "Laravel"
        except Exception:
            pass

    pkg = path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="ignore", encoding="utf-8"))
            deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
            # Móviles primero (más específicos)
            if "expo" in deps: return "Expo (React Native)"
            if any(k in deps for k in ("@ionic/react", "@ionic/angular", "@ionic/vue")):
                return "Ionic + Capacitor"
            if "react-native" in deps: return "React Native"
            # Web
            if "next" in deps: return "Next.js"
            if "astro" in deps: return "Astro"
            if "nuxt" in deps: return "Nuxt"
            if "@angular/core" in deps: return "Angular"
            if "vue" in deps: return "Vue 3"
            if "react" in deps: return "React"
            if "vite" in deps: return "Vite (genérico)"
        except Exception:
            pass
    # Flutter
    if (path / "pubspec.yaml").is_file():
        return "Flutter"
    # Android nativo
    if (path / "build.gradle").is_file() or (path / "build.gradle.kts").is_file():
        return "Android (Kotlin)"
    # iOS (Xcode project) — solo identificar, no podemos buildear en Linux
    if (path / "Package.swift").is_file() or list(path.glob("*.xcodeproj")):
        return "iOS (Swift)"
    if (path / "composer.json").exists():
        try:
            data = json.loads((path / "composer.json").read_text(errors="ignore", encoding="utf-8"))
            req = {**(data.get("require") or {}), **(data.get("require-dev") or {})}
            if "laravel/framework" in req or "laravel/laravel" in req:
                return "Laravel"
            if "symfony/framework-bundle" in req:
                return "Symfony"
            return "PHP"
        except Exception:
            return "PHP"
    if (path / "theme.json").exists() and (path / "style.css").exists():
        return "WordPress (Block Theme)"
    if (path / "config" / "settings_schema.json").exists():
        return "Shopify Liquid"
    if (path / "angular.json").exists():
        return "Angular"
    if (path / "index.html").exists():
        return "HTML estático"
    return "?"


def detected_stack_to_key(label: str) -> str:
    """Convierte el string de detect_stack() al key usado en STACKS."""
    m = {
        # Web
        "Next.js":              "nextjs-tailwind",
        "Astro":                "astro-tailwind",
        "Nuxt":                 "none",
        "Angular":              "angular-tailwind",
        "Vue 3":                "vue3-vite-tailwind",
        "React":                "react-vite-tailwind",
        "Vite (genérico)":      "html-tailwind",
        "Laravel":              "laravel-inertia",
        "Symfony":              "none",
        "PHP":                  "none",
        "WordPress (Block Theme)": "wordpress-block",
        "Shopify Liquid":       "shopify-liquid",
        "HTML estático":        "html-bootstrap",
        # Móvil
        "Expo (React Native)":  "expo-rn-nativewind",
        "React Native":         "expo-rn-nativewind",
        "Ionic + Capacitor":    "ionic-capacitor",
        "Flutter":              "flutter",
        "Android (Kotlin)":     "kotlin-compose",
        "iOS (Swift)":          "none",
    }
    return m.get(label, "none")


ARCHIVE_DIR = HOME / "Proyectos" / "themes-archive"
BUILDS_DIR = HOME / "Proyectos" / "themes-builds"


# ── Build de ZIP para marketplaces ───────────────────────────────────
# Dirs y archivos que NUNCA deben entrar al ZIP final.
_ZIP_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", ".next", ".nuxt", "out", "dist", "build",
    ".cache", "__pycache__", ".venv", "venv", "env", "ENV",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "coverage",
    ".turbo", ".vercel", ".netlify",
    ".vscode", ".idea", ".cursor", ".windsurf", ".claude", ".aider",
    ".agents",  # skills de agente (autoskills, CC BY-NC) — tooling de dev, NO va al producto
    "target", "vendor", ".gradle", ".dart_tool",
    "screenshots-private", "tmp", ".tmp",
})
# Directorios que ThemeForge inyecta SOLO en la RAÍZ del proyecto y que no
# forman parte del template vendible: contexto/investigación (puede tener datos
# privados) y la referencia estudiada (copyright ajeno). Se excluyen solo a
# nivel raíz para no chocar con código legítimo (p.ej. `src/context/` de React).
_ZIP_EXCLUDE_ROOT_DIRS: frozenset[str] = frozenset({"context", "reference"})
_ZIP_EXCLUDE_FILES: frozenset[str] = frozenset({
    ".env", ".env.local", ".env.development", ".env.production",
    ".env.test",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", "MEMORY.md",
    ".themeforge-init-prompt",  # prompt inicial que ThemeForge deja en el proyecto
    ".eslintcache",
})
_ZIP_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".log", ".pyc", ".pyo", ".swp", ".swo", ".bak", ".tmp",
)


def build_marketplace_zip(
    project_dir: Path,
    *,
    include_screenshots: bool = True,
    include_documentation: bool = True,
    include_source: bool = True,
    output_path: Path | None = None,
) -> tuple[bool, str, Path | None]:
    """Empaqueta el proyecto en un ZIP listo para subir a un marketplace.

    Args:
        project_dir: raíz del proyecto.
        include_screenshots: incluir `screenshots/` si existe.
        include_documentation: incluir `documentation/` si existe.
        include_source: incluir `source/` (PSDs, Figma exports) si existe.
        output_path: si None, usa BUILDS_DIR/<slug>-<timestamp>.zip.

    Returns:
        (ok, message, output_path_real)
    """
    import zipfile

    if not project_dir.is_dir():
        return False, f"No existe: {project_dir}", None

    slug = project_dir.name
    if output_path is None:
        BUILDS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = BUILDS_DIR / f"{slug}-{ts}.zip"
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    files_added = 0
    bytes_raw = 0

    def should_include_dir(name: str) -> bool:
        if name in _ZIP_EXCLUDE_DIRS:
            return False
        # Carpetas opcionales según flags
        if name == "screenshots" and not include_screenshots:
            return False
        if name == "documentation" and not include_documentation:
            return False
        if name == "source" and not include_source:
            return False
        return True

    def should_include_file(name: str) -> bool:
        if name in _ZIP_EXCLUDE_FILES:
            return False
        if name.startswith(".env."):  # cualquier .env.<algo>
            return False
        if any(name.endswith(s) for s in _ZIP_EXCLUDE_SUFFIXES):
            return False
        return True

    try:
        with zipfile.ZipFile(
            str(output_path), "w",
            compression=zipfile.ZIP_DEFLATED, compresslevel=6,
        ) as zf:
            for root, dirs, files in os.walk(project_dir):
                # Pruning in-place de dirs excluidos. En la RAÍZ del proyecto
                # se excluyen además context/ y reference/ (solo ahí, para no
                # tocar p.ej. src/context/).
                at_root = Path(root) == project_dir
                dirs[:] = [
                    d for d in dirs
                    if should_include_dir(d)
                    and not (at_root and d in _ZIP_EXCLUDE_ROOT_DIRS)
                ]
                for f in files:
                    if not should_include_file(f):
                        continue
                    src = Path(root) / f
                    try:
                        rel = src.relative_to(project_dir)
                    except ValueError:
                        continue
                    # arcname incluye el slug como dir raíz para que al
                    # descomprimir quede `<slug>/...` (estándar marketplace)
                    arcname = str(Path(slug) / rel)
                    try:
                        zf.write(str(src), arcname)
                        st = src.stat()
                        bytes_raw += st.st_size
                        files_added += 1
                    except (OSError, PermissionError):
                        continue
    except Exception as e:
        return False, f"Error empaquetando: {e}", output_path

    size_zip = output_path.stat().st_size
    msg = (
        f"ZIP creado: {output_path}\n"
        f"{files_added} archivos · {bytes_raw // 1024} KB sin comprimir → "
        f"{size_zip // 1024} KB comprimido "
        f"({100 - int(size_zip * 100 / max(bytes_raw, 1))}% reducción)"
    )
    return True, msg, output_path


def list_projects(archived: bool = False) -> list[dict]:
    """Metadatos de cada subcarpeta de PROJECTS_DIR (o ARCHIVE_DIR si
    archived=True), ordenados por mtime desc."""
    root = ARCHIVE_DIR if archived else PROJECTS_DIR
    if not root.exists():
        return []
    items = []
    for d in root.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            mtime = d.stat().st_mtime
            for sub in ("src", "src_v2", "app", "templates", "package.json", "CLAUDE.md"):
                p = d / sub
                if p.exists():
                    mtime = max(mtime, p.stat().st_mtime)
        except Exception:
            mtime = 0
        items.append({
            "path": d,
            "name": d.name,
            "stack": detect_stack(d),
            "mtime": mtime,
            "has_git": (d / ".git").is_dir(),
            "has_claude": (d / "CLAUDE.md").exists(),
            "has_agents": (d / "AGENTS.md").exists(),
            "archived": archived,
        })
    return sorted(items, key=lambda x: x["mtime"], reverse=True)


def archive_project(slug: str) -> tuple[bool, str]:
    """Mueve PROJECTS_DIR/<slug> → ARCHIVE_DIR/<slug>. No borra nada."""
    src = PROJECTS_DIR / slug
    if not src.is_dir():
        return False, f"No existe {src}"
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVE_DIR / slug
    if dst.exists():
        return False, f"Ya existe en archivo: {dst} — renómbralo o bórralo antes."
    try:
        shutil.move(str(src), str(dst))
        return True, f"Archivado en {dst}"
    except Exception as e:
        return False, f"Error al archivar: {e}"


def unarchive_project(slug: str) -> tuple[bool, str]:
    """Mueve ARCHIVE_DIR/<slug> → PROJECTS_DIR/<slug>."""
    src = ARCHIVE_DIR / slug
    if not src.is_dir():
        return False, f"No existe en archivo: {src}"
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = PROJECTS_DIR / slug
    if dst.exists():
        return False, f"Ya hay un proyecto activo con ese nombre: {dst}"
    try:
        shutil.move(str(src), str(dst))
        return True, f"Restaurado en {dst}"
    except Exception as e:
        return False, f"Error al restaurar: {e}"


def gh_list_repos(limit: int = 200) -> list[dict]:
    """Lista repos del usuario autenticado (vacío si gh falla)."""
    try:
        out = subprocess.check_output(
            ["gh", "repo", "list", "--limit", str(limit),
             "--json", "nameWithOwner,visibility,description,updatedAt,isArchived"],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        data = json.loads(out.decode())
        return [r for r in data if not r.get("isArchived")]
    except Exception:
        return []


def _read_context(name: str) -> str:
    """Lee un MD de context/ del builder. Prioridad (misma convención que el
    discovery de context-private): versión PRIVADA del usuario
    (`context-private/`) > nombre exacto en `context/` > stub `.template.md`
    del repo (p. ej. LICENSING-SYSTEM.md → LICENSING-SYSTEM.template.md)."""
    candidates: list[Path] = []
    priv = globals().get("CONTEXT_PRIVATE_DIR")
    tmpl = (name[:-3] + ".template.md") if name.endswith(".md") else None
    if priv:
        candidates.append(priv / name)
        if tmpl:
            candidates.append(priv / tmpl)
    candidates.append(CONTEXT_DIR / name)
    if tmpl:
        candidates.append(CONTEXT_DIR / tmpl)
    for p in candidates:
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return f"_(no se pudo leer {name})_"


# Formato de producto Envato derivado del stack. Decide qué checklist (§B)
# aplica al generar el CLAUDE.md: Site Template estático (ThemeForest) vs
# Script/App full-stack (CodeCanyon) vs tema WordPress vs app móvil. Sin esto,
# un PHP Script/SaaS caía en el checklist de Site Template estático y el agente
# se bloqueaba ante la contradicción.
_FORMAT_MOBILE = {"expo-rn-nativewind", "expo-rn-router", "flutter", "ionic-capacitor", "kotlin-compose"}
_FORMAT_WORDPRESS = {
    "wordpress-block", "wordpress-bricks", "wordpress-elementor",
    "wordpress-divi", "wordpress-breakdance", "wordpress-plugin",
}
# Variantes de THEME WP (todas las anteriores excepto el stack de plugin).
# Cualquiera de estas tiene un child theme distinto y un ux_pack distinto:
# si el usuario eligió una a mano, NO la pisamos al detectar "wordpress-theme".
_WORDPRESS_THEME_STACKS = _FORMAT_WORDPRESS - {"wordpress-plugin"}
_FORMAT_SHOPIFY = {
    "shopify-liquid", "shopify-liquid-blank",
    "shopify-hydrogen",
    "shopify-polaris-app", "shopify-functions", "shopify-checkout-extension",
    "shopify-storefront-webcomponents",
}
_FORMAT_SCRIPT_APP = {
    "laravel-inertia", "nestjs-prisma", "fastapi", "django-tailwind", "t3-stack",
    "hono-bun", "hono-cloudflare", "phoenix-liveview", "rails-tailwind", "go-fiber",
    "rust-axum", "bun-elysia", "deno-fresh", "spring-boot", "ktor-server",
    "payload-cms", "strapi", "medusa", "directus", "sanity-studio",
    "nextjs-tailwind", "nextjs-shadcn", "nextjs-mantine", "nextjs-heroui",
    "nuxt-tailwind", "sveltekit-tailwind", "remix-tailwind", "solidstart-tailwind",
    "qwik-tailwind", "tauri-react", "electron-react",
    "restaurant-saas", "pcreative-commerce", "pcreative-commerce-growshop",
}


_WP_BUILDER_CONTEXT = {
    "wordpress-block": """### Builder activo: **FSE (block theme nativo)** — sin builder externo

Diseña con bloques nativos de Gutenberg. La estructura del theme:

- `theme.json` — design tokens (palette/typography/spacing). El equivalente al
  `:root` CSS del diseño. Cualquier color o tipografía global vive aquí.
- `templates/*.html` — templates (index, single, archive, page, 404…) en
  Block Markup (`<!-- wp:... -->`).
- `parts/*.html` — template parts reutilizables (header, footer, sidebar).
- `patterns/*.php` — patrones reutilizables registrados con `register_block_pattern`.

Plugins instalados (free): **GenerateBlocks** (containers/grid/headlines de
performance) · **Spectra** (25+ bloques avanzados) · **ACF (free)** · **Pods**
(CPT + fields) · **Royal MCP**.""",
    "wordpress-bricks": """### Builder activo: **Bricks Builder** (parent theme)

El proyecto es un **child theme** que declara `Template: bricks` en `style.css`.
Bricks (parent) viene de `wp_packs.json` si tienes licencia; si no, súbelo a
mano a Apariencia → Temas → Subir y activa este child theme.

- Diseña en `/wp-admin/admin.php?page=bricks` (Bricks → Templates).
- Cada template (header / footer / single / archive / page / popup) se **exporta
  a JSON** vía *Bricks → Templates → Export* y se commitea en `bricks-templates/`.
- **Global Classes** y **Theme Styles** (paleta, tipografía, spacing) se exportan
  igual y entran como un único *Theme Style export*.
- CSS / JS / hooks PHP del child theme van en `assets/` y `functions.php`.

Plugins instalados (free): **GreenShift** (animations + dynamic data) · **ACF** ·
**Pods** · **Royal MCP**. Premium (si en `wp_packs.json`): **Bricksforge**
(interactivos avanzados), **JetEngine** (Listings + Query Builder), **Motion.page**
(GSAP visual), **Novamira Pro** (MCP que controla Bricks nativamente).""",
    "wordpress-elementor": """### Builder activo: **Elementor** (sobre Hello Elementor)

El proyecto es un **child theme** que declara `Template: hello-elementor`. El parent
y Elementor free los instala ThemeForge solos.

- Diseña en `/wp-admin/admin.php?page=elementor_app/templates` y en la edición de
  páginas (botón "Editar con Elementor").
- Cada template (header / footer / single / archive / page / popup) se **exporta a
  JSON** vía *Plantillas → Mis plantillas → Exportar* y se commitea en
  `elementor-templates/`. Los **Kits** (paleta, tipografía, layout globals) van en
  `elementor-templates/kits/` (exportar desde *Site Settings → Export Site Kit*).
- CSS/JS/hooks del child en `assets/` + `functions.php`.

Plugins instalados (free): **Elementor** · **Essential Addons Lite** · **ACF (free)** ·
**Pods** · **Royal MCP**. Premium (si en `wp_packs.json`): **Elementor Pro** (theme
builder + custom CSS por widget + popups), **JetEngine**, **Motion.page**,
**Novamira Pro** (MCP con conocimiento de widgets atómicos v3→v4).""",
    "wordpress-divi": """### Builder activo: **Divi** (Elegant Themes)

El proyecto es un **child theme** que declara `Template: Divi`. Divi parent
viene de `wp_packs.json` (es paid: requiere zip propio).

- Diseña con *Divi Builder* en cualquier página. Exporta layouts vía
  *Divi → Library → Export* a JSON. Commitea en `divi-layouts/`.
- Theme options globales (paleta, tipografía): *Divi → Theme Options* + export.
- CSS/JS/hooks del child en `assets/` + `functions.php`.

Plugins instalados (free): **ACF (free)** · **Pods** · **Royal MCP**. Premium
(si en `wp_packs.json`): **Divi parent theme** (obligatorio para activar el
child), **Novamira Pro** (MCP con soporte Divi 4/5).""",
    "wordpress-breakdance": """### Builder activo: **Breakdance** (plugin de render)

A diferencia de los anteriores, Breakdance es un **plugin** que reemplaza el
render del front. El theme base es **Kadence** (free, lo instala ThemeForge),
sirve solo de fallback / wp-admin. El proyecto es un child theme de Kadence.

- Diseña en `/wp-admin/admin.php?page=breakdance_settings` y *Breakdance →
  Templates*. Exporta global settings, headers, footers, popups, singles y
  archives a JSON vía *Breakdance → Templates → Export* y commitea en
  `breakdance-templates/`.
- Theme base sirve solo para wp-admin y fallback de páginas no editadas con BD.
- CSS/JS/hooks del child en `assets/` + `functions.php`.

Plugins instalados (free): **Breakdance** · **ACF (free)** · **Pods** ·
**Royal MCP**. Premium (si en `wp_packs.json`): **Breakdance Pro** (más
elementos), **JetEngine**, **Novamira Pro**.""",
    "wordpress-plugin": """### Stack: **plugin de WordPress (PHP 8.2 + PSR-4 + Vite)**

Stack para CodeCanyon (Script/App): plugin PHP que añade funcionalidad.
Ver scaffold completo en `composer.json` + `src/` (Admin/Frontend/Core/Database).
No hay builder externo; trabajas con PHP, JS/Vue y bloques propios si necesitas UI editorial.""",
}


def _wp_builder_context(stack_key: str) -> str:
    """Bloque de contexto específico del builder para el CLAUDE.md del proyecto."""
    return _WP_BUILDER_CONTEXT.get(stack_key, "")


def product_format_for(stack_key: str) -> str:
    """stack_key → 'site-template' | 'script-app' | 'mobile' | 'wordpress' | 'shopify' | 'unknown'."""
    if stack_key == "none":
        return "unknown"
    if stack_key in _FORMAT_MOBILE:
        return "mobile"
    if stack_key in _FORMAT_WORDPRESS:
        return "wordpress"
    if stack_key in _FORMAT_SHOPIFY:
        return "shopify"
    if stack_key in _FORMAT_SCRIPT_APP:
        return "script-app"
    return "site-template"


_SHOPIFY_BUILDER_CONTEXT = {
    "shopify-liquid": """### Stack: **Shopify Liquid — Online Store 2.0** (Dawn como base)

El proyecto se ha clonado de **Dawn** (theme oficial Shopify, MIT).

#### ⚠️ Crítico — decide MARKET antes de empezar

- **ThemeForest (Envato)** → Dawn como base ESTÁ PERMITIDO. Tu trabajo es
  personalizar profundamente (diseño + secciones premium + nichos).
- **Shopify Theme Store** → **INELEGIBLE** si se deriva de Dawn o Horizon.
  Si vendes ahí, **borra todo el código de Dawn** y construye desde cero
  con la estructura OS 2.0 mínima (`config/`, `layout/theme.liquid`,
  `templates/*.json`, `sections/`, `blocks/`, `snippets/`, `assets/`,
  `locales/`). La identidad visual y las capacidades deben ser
  **no reproducibles fácilmente** (no basta cambiar paleta o spacing).
- **Shopify Partner / custom build** → cualquier base sirve.

Confirma el market con el user ANTES de tocar código.

#### Arquitectura OS 2.0 (la que importa)

- `config/settings_schema.json` — settings del theme customizer (paleta,
  tipografía, layout). Aquí viven los **DESIGN TOKENS globales**.
  Decláralos en sentido **opinionado** (no inundes con 300 settings — los
  themes top venden con settings curados).
- `config/settings_data.json` — valores por defecto (presets).
- `layout/theme.liquid` — el layout maestro. Contiene `{% sections 'header-group' %}`
  y `{% sections 'footer-group' %}`.
- `sections/*.liquid` con `{% schema %}` al final. Atributos clave:
  `name`, `tag`, `class`, `limit`, `settings`, `blocks` (con `{"type":"@theme"}`
  y **`{"type":"@app"}` obligatorio** para que apps de terceros funcionen),
  `max_blocks` (hasta 50), `presets`, `enabled_on`/`disabled_on`.
  Hasta 25 sections por template/section group.
- `sections/*.json` — **Section Groups** (`header.json`, `footer.json`,
  `aside.json`). El merchant añade/quita/reordena sections desde el
  editor sin tocar código. Estructura: `{type, name, sections{}, order[]}`.
- `blocks/*.liquid` — **Theme blocks** reutilizables entre sections
  (separado de `sections/blocks` inline). Permite anidamiento + presets.
- `templates/*.json` — templates basados en sections.
  **OBLIGATORIOS para Theme Store**: 404, article, blog, cart, collection,
  customers/*, gift_card, index, page, password, product, search.
- `snippets/*.liquid` — fragmentos reutilizables (chip-precio, card-product,
  rating, etc.).
- `locales/*.json` — i18n (`es.default.json`, `en.json`…). **Obligatorio**.
- `assets/*` — CSS, JS, imágenes. **NO Sass/SCSS** (rechazado por Theme
  Store), CSS plano. JS modular **sin jQuery, sin React/Vue/Angular**.

#### Performance — el bar OFICIAL del Theme Store

- **Lighthouse mobile**: **60+ mínimo** (home/collection/product, average).
  Themes top venden con 90+ → es tu diferenciador.
- **Accessibility**: **90+ obligatorio**.
- **JS bundle**: **16 KB minified MAX**. Shopify minifica automáticamente.
  Sin frameworks (React/Vue/Angular/jQuery prohibidos). IIFE para evitar
  colisiones de scope global.
- **CSS**: critical inline + el resto subseteado por Shopify automáticamente.
- **Imágenes**: filtro `image_tag` con `loading: 'lazy'` (off-fold) y
  `srcset` inteligente. `fetchpriority="high"` SOLO en LCP.
- **Fonts**: usa `font_url` + `system-ui` como fallback. System fonts
  preferidos para evitar download.
- **Preload hints**: máximo **2** resource hints por template.
- **Scripts**: `defer` o `async` siempre — nada parser-blocking.
- **Liquid**: nunca itera `all_products` sin paginar; ops costosas FUERA
  de loops; usa Theme Inspector Chrome para profilear.

#### Features OBLIGATORIAS para Theme Store (auto-rechaza si faltan)

Sections Everywhere, discounts display, accelerated checkout buttons,
**faceted search** filtering, gift cards, **image focal points**,
country/language selection, **multi-level menus**, newsletter forms,
**pickup availability**, product recommendations, **rich media** (3D,
video), **predictive search**, **selling plans** (subscriptions),
**Shop Pay Installments**, **unit pricing**, **variant images**,
**Follow on Shop** button.

Para ThemeForest el bar es similar pero más laxo — implementa todas
igualmente como diferenciador competitivo.

#### Conversion patterns que vende cada theme top

- **Cart drawer** (modal lateral) en vez de página /cart. Hot reload sin recarga.
- **Quick add** desde collection (no abre PDP — añade y muestra mini-confirm).
- **Predictive search** custom (no la default) con thumbnails + categorías.
- **Sticky add-to-cart bar** en PDP cuando se scrollea por debajo del fold.
- **Recently viewed** (cookie/localStorage).
- **Trust badges** sobre el botón comprar.
- **Reviews** (placeholder para Loox/Judge.me — no hardcodees uno).
- **Upsells & cross-sells** en cart drawer.
- **Color/variant swatches** con metafields, no con name strings.

#### MCPs activos (los tres en `.mcp.json`)

- `shopify-dev` — schemas GraphQL Admin/Storefront/Checkout, tipos Liquid,
  esquemas de section/block, y **Polaris** (para apps embebidas).
- `shopify-storefront` — cart/policies/FAQ del store por URL. Sustituye
  `YOUR-SHOP` en `.mcp.json` por tu subdominio.
- `shopify-storefront-catalog` — UCP catalog con búsqueda natural.

#### Developer Tools oficiales (úsalas todas)

- **Shopify CLI** — `shopify theme dev / check / push / pull / package /
  publish / list / info / share / open / rename / delete / console`.
  Hot reload de CSS y sections; multi-tienda vía environments.
- **Theme Check** — linter Liquid+JSON. Detecta sintaxis, templates
  perdidos, vars no usadas, tags deprecated, performance issues
  (parser-blocking JS, asset-size-css). Corre via CLI o VS Code extension.
  Config en `.theme-check.yml`. **Resuelve todo antes de subir** —
  warnings críticos son auto-reject.
- **Shopify Liquid VS Code Extension** — autocomplete, hover docs,
  navigation, integra Theme Check. Imprescindible.
- **Liquid Prettier Plugin** (`@shopify/prettier-plugin-liquid`) —
  formatter automático. Añádelo a `package.json` + `.prettierrc.json`.
- **Shopify Theme Inspector** (Chrome extension) — profila tiempos de
  render de cada section/snippet Liquid. Identifica el bottleneck real.
- **Lighthouse CI GitHub Action** (de Shopify) — corre Lighthouse en cada
  PR/push y bloquea merges que rompan el budget. Añade workflow YAML.
- **Shopify GitHub Integration** — sync bidireccional GitHub ↔ Shopify
  admin (branches mapean a themes). Hace deploy automático en cada push.
- **Theme Access App** — para CI/CD que necesita push sin login Partner.
  Genera password de theme access en la tienda y úsala en GitHub Actions.
- **Development Stores** (Partners) — gratis, para testing. NO uses
  tienda real para dev.
- **LiquidDoc** — anotaciones de tipo para snippets (`{% doc %}` tag).
  Mejora autocomplete y Theme Check.
- **Admin Theme Editor** — preview en vivo con merchant interactions.
  Test del WYSIWYG después de cada push.

#### Comandos clave

```bash
shopify theme dev                        # http://127.0.0.1:9292, hot reload
shopify theme check                      # linter — sin errores antes de subir
shopify theme push --unpublished --json  # subir como borrador
shopify theme package                    # genera .zip para ThemeForest / Theme Store
shopify theme publish <id>               # publicar tema
shopify theme console                    # REPL de Liquid en vivo
shopify theme share                      # crear preview URL pública
npx prettier --write '**/*.liquid'       # formatear todo el código Liquid
```

#### Para venta en ThemeForest

Categoría WooCommerce/Shopify Themes. El `.zip` de `shopify theme
package` se sube tal cual. Cumple Theme Store Guidelines aunque vendas
en ThemeForest — es tu diferenciador competitivo.

#### `layout/theme.liquid` — canónico OS 2.0

```liquid
<!DOCTYPE html>
<html lang="{{ request.locale.iso_code }}">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="canonical" href="{{ canonical_url }}">
    {%- if settings.favicon != blank -%}
      <link rel="icon" type="image/png" href="{{ settings.favicon | image_url: width: 32 }}">
    {%- endif -%}
    {{ content_for_header }}  {%- comment -%} OBLIGATORIO — Shopify inyecta scripts aquí {%- endcomment -%}
  </head>
  <body class="template-{{ template.name }}">
    <a class="skip-link" href="#MainContent">{{ 'accessibility.skip_to_content' | t }}</a>
    {% sections 'header-group' %}
    <main id="MainContent" role="main">{{ content_for_layout }}</main>
    {% sections 'footer-group' %}
  </body>
</html>
```

⚠️ `checkout.liquid` **deprecado desde 2025-08** — checkout/thank-you/order-status van por Shopify Extensions (`@shopify/ui-extensions-checkout`), no por theme.

#### Locales — `locales/*.json` (i18n obligatorio)

DOS tipos de archivo por idioma:

- `<idioma[-región]>.json` — strings del **storefront** (visible por el cliente, editable por merchant).
- `<idioma[-región]>.schema.json` — strings del **theme editor** (settings labels).

**Naming IETF**: `es-ES.json`, `en-GB.json` o `es.json`. UN archivo por idioma debe llevar `.default` (`es.default.json` + `es.default.schema.json`) — es el fallback.

**Límites**: 3.400 traducciones/archivo, 1.000 chars/valor.

**Estructura**: 3 niveles `category > group > description`:

```json
{
  "general":  { "404": { "title": "Página no encontrada", "subtext": "La página…" } },
  "cart":     { "general": { "title": "Carrito", "empty_html": "Tu carrito está vacío" } },
  "products": { "product": { "add_to_cart": "Añadir al carrito", "sold_out": "Agotado" } }
}
```

**Uso en Liquid**: filtro `t` (translate):

```liquid
{{ 'general.404.title' | t }}
{{ 'products.product.add_to_cart' | t }}
{{ 'cart.general.empty_html' | t }}
```

**ZERO texto hardcoded** en sections, snippets, templates. Theme Store auto-rechaza si encuentra strings sin traducir.

#### Markets — multi-currency + multi-language

Selector país+idioma obligatorio para Theme Store:

```liquid
{%- form 'localization' -%}
  <select name="country_code" aria-label="{{ 'general.country' | t }}">
    {%- for country in localization.available_countries -%}
      <option value="{{ country.iso_code }}" {% if country.iso_code == localization.country.iso_code %}selected{% endif %}>
        {{ country.name }} ({{ country.currency.iso_code }})
      </option>
    {%- endfor -%}
  </select>
  <select name="locale_code" aria-label="{{ 'general.language' | t }}">
    {%- for language in localization.available_languages -%}
      <option value="{{ language.iso_code }}" {% if language.iso_code == localization.language.iso_code %}selected{% endif %}>
        {{ language.endonym_name }}
      </option>
    {%- endfor -%}
  </select>
  <button type="submit">{{ 'general.update' | t }}</button>
{%- endform -%}
```

**hreflang** en `<head>` (loop sobre `localization.available_languages`):

```liquid
{%- for lang in localization.available_languages -%}
  <link rel="alternate" hreflang="{{ lang.iso_code }}" href="{{ canonical_url | replace: request.locale.iso_code, lang.iso_code }}">
{%- endfor -%}
```

**Money con currency**: `{{ product.price | money_with_currency }}` o el objeto `localization.country.currency`. Cantidad por unidad de mercado: filtro `currency_selector`.

Geolocation pre-select solo para Shopify Plus.

#### LiquidDoc — anotaciones de tipos en snippets

Todo snippet con parámetros DEBE llevar `{% doc %}` para autocomplete + Theme Check + Liquid VS Code:

```liquid
{% doc %}
Product card snippet.

@param {object} product - Producto Shopify.
@param {boolean} [show_vendor] - Mostrar vendor sobre el título.
@param {number}  [max_description_length] - Truncar a N caracteres.

@example
  {% render 'product-card', product: product, show_vendor: true %}
{% enddoc %}

<article class="product-card" itemscope itemtype="https://schema.org/Product">
  …
</article>
```

Render con parámetros nombrados (NO `include`, que es legacy):

```liquid
{% render 'product-card', product: product, show_vendor: true %}
```

Scoping aislado: el snippet NO ve variables del caller, solo los `@param` + objetos globales (`product`, `collection`, `cart`, `customer`, `settings`, `localization`, `request`, `template`).

#### Schema settings — tipos completos (referencia rápida)

| Tipo | Para qué |
|---|---|
| `text` · `textarea` · `richtext` · `inline_richtext` · `html` · `liquid` | strings con escalado de complejidad. `liquid` permite renderizar Liquid dentro del setting. |
| `number` · `range` | numéricos. `range` da slider con min/max/step/unit. |
| `select` · `radio` · `checkbox` | choice fields. |
| `color` · `color_background` · `color_scheme` · `color_scheme_group` | **`color_scheme_group`** es el rey en OS 2.0 — define grupos de colores (bg/text/accent) que el merchant asigna a cada section. |
| `font_picker` | tipografía Shopify fonts (incluye Google Fonts). Usar con filtro `font_face`. |
| `image_picker` · `video` · `video_url` | media. `video_url` acepta YouTube/Vimeo. |
| `url` · `link_list` | URLs y menús. `link_list` apunta a menús de navegación. |
| `collection` · `collection_list` · `product` · `product_list` · `article` · `blog` · `page` | resource pickers. Limit configurable. |
| `metaobject` · `metaobject_list` | **clave para contenido dinámico custom** — testimonios, FAQs, store locations, miembros del equipo, etc. Sin necesidad de bloques. |
| `header` · `paragraph` | UI-only (separadores y textos en el editor, no se renderizan). |

Ejemplo de `color_scheme_group`:

```json
{ "type": "color_scheme_group", "id": "color_schemes", "label": "Color schemes",
  "definition": [
    { "type": "color", "id": "background", "label": "Background", "default": "#FFFFFF" },
    { "type": "color", "id": "text", "label": "Text", "default": "#1A1A1A" },
    { "type": "color", "id": "accent", "label": "Accent", "default": "#C56A4D" }
  ],
  "role": { "text": "text", "background": { "solid": "background" } }
}
```

En section o block: `"type": "color_scheme", "id": "color_scheme", "label": "Color scheme"` — el merchant elige UNO de los grupos definidos arriba.

#### Customer Accounts (New, no Classic)

Shopify ha sustituido el sistema **Classic** por **New customer accounts** (passwordless, OAuth con código de acceso por email). El theme NO maneja login/signup directamente: redirige al endpoint de Shopify.

- Templates: `templates/customers/account.json`, `addresses.json`, `order.json`, `register.json`, `reset_password.json` siguen existiendo PERO para Classic.
- Para New: el theme apunta a `/account` y Shopify lo redirige al portal hosted.
- Para que el theme sea compatible con AMBOS, usa `customer` object con `customer.has_account` checks.

#### SEO — JSON-LD canónico

PDP (`templates/product.json` + section principal):

```liquid
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": {{ product.title | json }},
  "image": [
    {% for media in product.media limit: 5 -%}
      {{ media | image_url: width: 1200 | prepend: 'https:' | json }}{% unless forloop.last %},{% endunless %}
    {%- endfor %}
  ],
  "description": {{ product.description | strip_html | json }},
  "sku": {{ product.selected_or_first_available_variant.sku | json }},
  "brand": { "@type": "Brand", "name": {{ product.vendor | json }} },
  "offers": {
    "@type": "Offer",
    "url": {{ canonical_url | json }},
    "priceCurrency": {{ cart.currency.iso_code | json }},
    "price": {{ product.selected_or_first_available_variant.price | divided_by: 100.0 | json }},
    "availability": "{% if product.available %}https://schema.org/InStock{% else %}https://schema.org/OutOfStock{% endif %}"
  }
}
</script>
```

Article (`templates/article.json`): mismo patrón con `@type: "Article"` (`headline`, `image`, `author`, `datePublished`, `articleBody`).

#### Predictive search — endpoint y patrón

Shopify expone `/search/suggest.json?q=…&resources[type]=product,collection,page,article,query&resources[limit]=10`:

```html
<predictive-search class="predictive-search">
  <input type="search" name="q" aria-label="Search" autocomplete="off">
  <div id="predictive-results" role="status" aria-live="polite"></div>
</predictive-search>
```

JS (custom element, sin frameworks):

```js
class PredictiveSearch extends HTMLElement {
  constructor() {
    super();
    this.input = this.querySelector('input[name="q"]');
    this.results = this.querySelector('#predictive-results');
    this.input?.addEventListener('input', this._debounce(this._search.bind(this), 250));
  }
  async _search() {
    const q = this.input.value.trim();
    if (q.length < 2) return this.results.innerHTML = '';
    const r = await fetch(`/search/suggest.json?q=${encodeURIComponent(q)}&resources[type]=product,collection,page,query&resources[limit]=8`);
    const json = await r.json();
    this.results.innerHTML = this._render(json.resources.results);
  }
  _render(d) { /* ... markup ... */ }
  _debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
}
customElements.define('predictive-search', PredictiveSearch);
```

#### Section Rendering API — el patrón OS 2.0 para actualizar sin recargar

La API mágica que permite actualizar **cualquier section o snippet por
ID** sin recargar la página entera. Es lo que usan **todos** los themes
modernos para cart drawer, variant selector, predictive search, filter
collection, sort, paginación AJAX, etc.

```js
// Pedir HTML de UNA section por ID, con parámetros que afectan al render.
const url = `${window.Shopify.routes.root}products/${handle}?section_id=cart-drawer&variant=${variantId}`;
const html = await fetch(url, { headers: { Accept: 'text/html' } }).then(r => r.text());

// Parseamos y reemplazamos el nodo viejo por el nuevo.
const doc = new DOMParser().parseFromString(html, 'text/html');
const oldEl = document.querySelector('cart-drawer');
const newEl = doc.querySelector('cart-drawer');
oldEl.replaceWith(newEl);
```

Variantes útiles del query string:
- `?section_id=<id>` — renderiza solo esa section (no el theme entero).
- `?sections=<id1>,<id2>,<id3>` — devuelve un JSON `{id: html, ...}` (POST a `/cart/change.js` también lo acepta vía `sections=`).

Patterns donde es obligatorio para no romper UX:
- **Cart drawer / mini cart** — al añadir → solo refresca `cart-drawer`.
- **Variant picker** — al cambiar variant → solo refresca `product-form` y `product-media-gallery`.
- **Predictive search** — al teclear → solo `predictive-search-results`.
- **Faceted search** (filter / sort en collection) → solo `main-collection-product-grid`.
- **Quick add** (collection card) → respuesta de `/cart/add.js?sections=cart-drawer` → reemplaza drawer.

#### Ajax API — endpoints completos del Storefront

```js
// Carrito
POST  /cart/add.js              { items: [{ id, quantity, properties }] }
POST  /cart/change.js           { id, quantity, sections: 'cart-drawer,header' }
POST  /cart/update.js           { updates: { variant_id: qty }, sections: '...' }
POST  /cart/clear.js
GET   /cart.js                  // estado actual del cart
POST  /cart.js                  // cart + sections en JSON
GET   /cart/shipping_rates.json

// Productos
GET   /products/{handle}.js     // JSON del producto
GET   /collections/{handle}/products.json  // JSON de productos de una collection

// Búsqueda predictive
GET   /search/suggest.json?q=&resources[type]=product,collection,page,article,query&resources[limit]=10

// Customer (solo si logged)
GET   /account.json             // (en New customer accounts redirige a OAuth)

// Locale switching
POST  /localization             // cambia country_code y/o locale_code (con session)
```

Todos los endpoints aceptan `?sections=id1,id2` para devolver además el
HTML renderizado de esas sections — eso evita un segundo round-trip.

Toda mutación carga `Accept: 'application/json'` excepto cuando pides
HTML con `Accept: 'text/html'` + `?section_id=`. Errores siempre con
HTTP 422 + body JSON `{description, message, status}`.

#### Metaobjects & Metafields — contenido dinámico custom

**Metafields**: campos custom en recursos existentes (product, variant,
collection, customer, order, shop, page, blog, article, market). Definidos
en Admin → Settings → Custom data o vía API.

```liquid
{# Acceso directo en Liquid #}
{{ product.metafields.specs.materials }}
{{ product.metafields.reviews.rating.value | json }}

{# Por tipo: single_line_text, multi_line_text, rich_text_field,
   number_integer, number_decimal, boolean, money, weight, dimension,
   volume, rating, color, date, date_time, url, file_reference,
   page_reference, product_reference, variant_reference, collection_reference,
   customer_reference, company_reference, metaobject_reference, json #}
```

**Metaobjects**: definiciones de tipos custom para contenido reutilizable
**sin necesidad de un theme block**. Casos perfectos: testimonios, FAQs,
team members, store locations, recipes, awards, certifications.

```liquid
{# Loop sobre todos los metaobjects de tipo 'testimonial' #}
{%- for testimonial in shop.metaobjects.testimonial.values -%}
  <article class="testimonial">
    {%- if testimonial.author_image -%}
      {{ testimonial.author_image | image_url: width: 200 | image_tag: loading: 'lazy', alt: testimonial.author_name }}
    {%- endif -%}
    <blockquote>{{ testimonial.quote }}</blockquote>
    <cite>{{ testimonial.author_name }}, {{ testimonial.author_role }}</cite>
  </article>
{%- endfor -%}
```

Como **setting** en section/block schema (el merchant elige cuál usar):

```json
{ "type": "metaobject", "id": "featured_testimonial",
  "metaobject_type": "testimonial", "label": "Featured testimonial" }
```

```json
{ "type": "metaobject_list", "id": "testimonials",
  "metaobject_type": "testimonial", "label": "Testimonials", "limit": 8 }
```

Patrón pro: **definir metaobjects en `theme.json`** (settings_schema.json
sub-config) para que se creen automáticamente al instalar el theme.

#### Web components nativos de Shopify (úsalos directamente)

- `<shopify-payment-terms>` — banner de Shop Pay Installments. Mandatory para Theme Store. Va en PDP cerca del botón comprar.
- `<pickup-availability-preview>` + `<pickup-availability-drawer>` — pickup availability widget. Mandatory.
- `<product-form>`, `<variant-radios>`, `<variant-selects>` — formularios de producto.
- `<cart-drawer>`, `<cart-notification>` — UI de carrito.

Cada uno se hidrata automáticamente — solo añadir el tag HTML.

#### Theme Inspector for Chrome — setup

1. Instala la extensión desde [Chrome Web Store](https://chrome.google.com/webstore) buscando "Shopify Theme Inspector".
2. Abre tu storefront en preview (`shopify theme dev`).
3. Chrome DevTools → tab "Shopify".
4. Click "Profile" → la extensión muestra tiempo de render por section/snippet/filter Liquid.
5. Iterar en lo más lento (típicamente: loops sobre `all_products`, llamadas a metafields sin cache).

#### Theme Store — checklist de submission (auto-iterable)

Antes de subir a Theme Store o pasar QA, ir marcando uno a uno:

- [ ] `shopify theme check` 0 errors, 0 critical warnings.
- [ ] Lighthouse mobile **60+** en home / collection / product (media de 3 runs).
- [ ] Lighthouse **accessibility 90+** en TODAS las páginas.
- [ ] JS bundle final **< 16 KB minified**. Sin React/Vue/Angular/jQuery.
- [ ] Templates JSON completos: 404, article, blog, cart, collection, customers/* (account, addresses, login, order, register, reset_password), gift_card.liquid, index, list-collections, page, password, product, search.
- [ ] **18 features mandatorias** implementadas: Sections Everywhere · discounts display · accelerated checkout (Shop Pay/Apple/Google) · faceted search · gift cards · image focal points · country/language selector · multi-level menus · newsletter forms · pickup availability · product recommendations · rich media (3D/video) · predictive search · selling plans · Shop Pay Installments · unit pricing · variant images · Follow on Shop.
- [ ] App blocks: TODAS las sections principales con `{"type": "@app"}` en `blocks`.
- [ ] WCAG 2.1 AA: contraste 4.5:1 (texto) / 3:1 (large+UI), focus visible, skip link, alt en todas las imágenes, `aria-live` para cart/search updates, touch targets ≥ 44×44 px.
- [ ] i18n: `locales/*.default.json` + `locales/*.default.schema.json` completos. ZERO hardcoded strings (grep).
- [ ] Demo data realista (productos plausibles, fotos auténticas, NO Lorem Ipsum, NO onboarding text).
- [ ] Documentation publicada (HTML estático con install + customization + FAQ).
- [ ] Contact form público + FAQ + commitment to respond ≤ 2 business days.
- [ ] Theme Store exclusivity verificada (no vendido en otros marketplaces si es esta route).
- [ ] Sin créditos de designer ni affiliate links embebidos en archivos del theme.
- [ ] Sin Sass/SCSS — solo CSS plano.
- [ ] Scripts Shopify-hosted o de librerías aprobadas.
- [ ] Browsers testados: Safari (2 últimas), Chrome (3), Firefox (3), Edge (2) en desktop + Mobile Safari + Chrome Mobile + Samsung Internet + webviews IG/FB/Pinterest.

#### Ejemplos canónicos (copy-paste base)

**`templates/index.json`** — template basado en sections:

```json
{
  "layout": "theme",
  "wrapper": "main#main",
  "sections": {
    "hero":      { "type": "hero-banner", "settings": { "heading": "Bienvenida", "image_focal_point": "center center" } },
    "featured":  { "type": "featured-collection", "settings": { "title": "Más vendidos", "limit": 8 },
                   "blocks": { "b1": { "type": "title" }, "b2": { "type": "products" }, "b3": { "type": "view_all" } },
                   "block_order": ["b1", "b2", "b3"] },
    "image_with_text": { "type": "image-with-text", "settings": { "title": "Nuestra historia" } },
    "newsletter": { "type": "newsletter", "settings": { "heading": "Suscríbete" } }
  },
  "order": ["hero", "featured", "image_with_text", "newsletter"]
}
```

**`sections/hero-banner.liquid`** — schema mínimo serio:

```liquid
<section class="hero" data-section-id="{{ section.id }}">
  <h1>{{ section.settings.heading }}</h1>
  {% if section.settings.image %}
    {{ section.settings.image | image_url: width: 2200 | image_tag:
       loading: 'eager', fetchpriority: 'high',
       widths: '375, 768, 1280, 1920, 2200',
       sizes: '100vw',
       class: 'hero__img' }}
  {% endif %}
</section>

{% schema %}
{
  "name": "Hero banner",
  "tag": "section",
  "class": "section section--hero",
  "settings": [
    { "type": "text", "id": "heading", "label": "Heading", "default": "Bienvenida" },
    { "type": "image_picker", "id": "image", "label": "Imagen de fondo" },
    { "type": "select", "id": "alignment", "label": "Alineación",
      "options": [
        { "value": "left", "label": "Izquierda" },
        { "value": "center", "label": "Centro" }
      ], "default": "center" }
  ],
  "blocks": [
    { "type": "@app" },
    { "type": "button", "name": "Botón",
      "settings": [
        { "type": "text", "id": "label", "label": "Etiqueta" },
        { "type": "url",  "id": "link",  "label": "Enlace" }
      ]
    }
  ],
  "max_blocks": 3,
  "presets": [ { "name": "Hero banner", "category": "Home page" } ],
  "enabled_on": { "templates": ["index", "page"] }
}
{% endschema %}
```

**`config/settings_schema.json`** — design tokens curados (extracto):

```json
[
  { "name": "theme_info", "theme_name": "__PROJECT__", "theme_version": "0.1.0", "theme_author": "you", "theme_documentation_url": "https://your-docs" },
  { "name": "Colors", "settings": [
    { "type": "color_scheme_group", "id": "color_schemes", "label": "Esquemas de color",
      "definition": [
        { "type": "color", "id": "background", "label": "Background", "default": "#FFFFFF" },
        { "type": "color", "id": "text", "label": "Text", "default": "#1A1A1A" },
        { "type": "color", "id": "accent", "label": "Accent", "default": "#C56A4D" }
      ] }
  ]},
  { "name": "Typography", "settings": [
    { "type": "font_picker", "id": "type_heading_font", "label": "Heading", "default": "fraunces_n4" },
    { "type": "font_picker", "id": "type_body_font", "label": "Body", "default": "inter_n4" },
    { "type": "range", "id": "type_heading_scale", "label": "Heading scale", "min": 100, "max": 150, "step": 5, "unit": "%", "default": 130 }
  ]}
]
```""",
    "shopify-hydrogen": """### Stack: **Shopify Hydrogen — Remix v3 + React 19 + Oxygen**

Storefront headless de Shopify. Estructura del proyecto vía
`@shopify/create-hydrogen` (template skeleton).

#### Arquitectura Hydrogen (importante)

- **Remix v3 / React Router v7** — convención de rutas en `app/routes/`.
  Cada ruta exporta `loader` (server) y/o `action` (mutaciones) + el
  componente React. **Server-driven UI**: el state real vive en el server.
- **Cache hints en loaders** — `context.storefront.CacheLong()` para
  catálogos, `CacheShort()` para carts, `CacheNone()` para usuario.
- **GraphQL fragments** en `app/lib/fragments.ts` — definir UNA vez,
  reutilizar en queries. Patrón crítico para mantener tipos.
- **Optimistic UI** con `useOptimisticCart` + `<CartForm>` — el cart
  responde instantáneo, server se sincroniza después.
- **Hydrogen primitives** que ahorran trabajo: `<Money>` (formato +
  multilocale), `<Image>` (auto srcset Shopify CDN), `<CartProvider>`,
  `<ShopifyAnalytics>`, `<PaymentTokens>` (Shop Pay native).

#### Customer Account API (la nueva, no Classic)

- OAuth-based, no cookie. `app/routes/account.tsx` con loader que llama
  `context.customerAccount.query`.
- Tracking de pedidos, returns, addresses, wishlist (con metafields).
- Reemplaza al Customer Accounts legacy y a las `/account/*` de Liquid.

#### Deployment: Oxygen (gratis, edge global de Shopify)

```
npx shopify hydrogen link            # vincula a la tienda
npx shopify hydrogen deploy          # deploy a Oxygen workers (edge)
```

Alternativas: Cloudflare Workers, Vercel, Netlify, fly.io.

#### Performance — bar más alto que Liquid

- **Lighthouse objetivo**: **95+** en mobile (Hydrogen te lo permite,
  Liquid es más difícil).
- **Hydrating mínimo**: el server hace la mayoría del trabajo. RSC patterns.
- **Edge caching**: `Cache-Control` por loader; TTL dinámico vía
  `context.storefront.CacheCustom()`.
- **Streaming SSR** con `defer` + `<Suspense>` para datos no-críticos.

#### Tailwind v4 (recomendado)

- `app/styles/app.css` con `@import 'tailwindcss';`.
- Design tokens en CSS custom properties → `theme.json` equivalente.
- Mismo patrón que en los stacks WP/FSE para portabilidad de tokens.

#### MCPs activos

Mismos tres que Liquid (`shopify-dev`, `shopify-storefront`, `-catalog`).
Útiles aquí para resolver schemas GraphQL en tiempo real mientras
construyes loaders y queries.

#### Cuándo Hydrogen vs Liquid

- Catálogo > 500 SKU con filtros pesados → Hydrogen gana.
- Multi-mercado/multi-currency/multi-locale fuerte → Hydrogen.
- Build con presupuesto ajustado y < 200 SKU → Liquid es más rentable.

#### Para venta

- **ThemeForest** acepta Hydrogen como categoría separada (menos
  competencia, ticket más alto: $99-249).
- **Shopify Theme Store** todavía es solo Liquid; Hydrogen va por el
  partner channel (custom builds para merchants enterprise).

#### Customer Account API — new (no Classic)

Pattern canon de loader auth + rutas account:

```ts
// app/routes/account.$.tsx
import {Outlet} from '@remix-run/react';
import {LoaderFunctionArgs, redirect} from '@shopify/remix-oxygen';

export async function loader({context}: LoaderFunctionArgs) {
  const {data} = await context.customerAccount.query(CUSTOMER_QUERY);
  if (!data.customer) throw redirect(await context.customerAccount.loginUrl());
  return {customer: data.customer};
}

export default function AccountLayout() {
  return <Outlet />;
}
```

```graphql
# app/lib/fragments.ts → CUSTOMER_QUERY
query Customer {
  customer {
    id
    firstName
    lastName
    emailAddress { emailAddress }
    defaultAddress { ...AddressFragment }
    orders(first: 10) { nodes { id orderNumber processedAt totalPrice { amount currencyCode } } }
  }
}
```

Mutations clave: `customerUpdate`, `customerAddressCreate`,
`customerAddressUpdate`, `customerAddressDelete`. Logout:
`context.customerAccount.logout()` redirige al login.

Cuenta passwordless: el customer entra con email + código (Shopify
envía). El theme NO maneja contraseñas — toda la auth la gestiona el
endpoint `.customer-account.com` del store.

#### Markets API — multi-currency, multi-language, multi-domain

Cada Market tiene su own currency/locale/dominio. Query patterns:

```graphql
# Storefront query con @inContext para forzar Market activo
query ProductWithContext($handle: String!, $country: CountryCode!, $language: LanguageCode!)
@inContext(country: $country, language: $language) {
  product(handle: $handle) {
    title  # automáticamente en el idioma del Market
    priceRange { minVariantPrice { amount currencyCode } }  # en currency del Market
  }
}
```

```tsx
// app/routes/($locale).products.$handle.tsx
import { getSelectedProductOptions } from '@shopify/hydrogen';

export async function loader({ params, context }: LoaderFunctionArgs) {
  const { locale } = params;
  const { country, language } = parseLocale(locale ?? 'en-us');
  const { product } = await context.storefront.query(PRODUCT_QUERY, {
    variables: { handle: params.handle, country, language }
  });
  return { product };
}
```

Selector de país/idioma:

```tsx
// app/components/CountrySelector.tsx
const { isoCode: currentCountry } = await context.storefront.i18n;
const availableCountries = await context.storefront.query(COUNTRIES_QUERY);

<form action="/api/localization" method="post">
  <select name="country">
    {availableCountries.map(c => (
      <option key={c.isoCode} value={c.isoCode} selected={c.isoCode === currentCountry}>
        {c.name} ({c.currency.isoCode})
      </option>
    ))}
  </select>
  <button type="submit">Update</button>
</form>
```

**hreflang** en `root.tsx`:

```tsx
export function meta({ data }) {
  const { locale, availableLocales } = data;
  return availableLocales.map(l => ({
    tagName: 'link',
    rel: 'alternate',
    hreflang: l.isoCode,
    href: `https://yourshop.com/${l.pathPrefix}${currentPath}`
  }));
}
```

**`<Money>` y `<Image>`** ya respetan el Market activo automáticamente
cuando vienen de Hydrogen primitives. No hace falta lógica custom.""",
    "shopify-polaris-app": """### Stack: **Shopify App (Polaris + App Bridge + Remix)**

NO es un theme — es una **app embebida** en el Admin de Shopify. Para
clientes que quieren extender funcionalidad del Admin o de checkout/POS,
o para distribuir en el **Shopify App Store**.

#### Stack confirmado

- **Remix v3** — routing + loaders (server) + actions (mutaciones).
- **`@shopify/polaris`** (design system MIT) — Cards, IndexTable,
  ResourcePicker, Form, Modal, Toast, Banner, etc. Componentes que el
  merchant ya conoce.
- **`@shopify/polaris-icons`** — iconografía consistente.
- **`@shopify/app-bridge-react`** v4 — puente nativo app↔Admin: navegación,
  contextual save bar, resource picker, scopes API, billing UI.
- **Shopify CLI 3** — `shopify app dev` arranca con **tunnel automático**
  (cloudflared) — el Admin de Shopify puede acceder a tu localhost.
- **Prisma + SQLite** (dev) / PostgreSQL (prod) — sesiones OAuth + tu data.
- **OAuth + sesiones** — `@shopify/shopify-app-remix` configura todo.

#### Tipos de extensiones a generar (`shopify app generate extension`)

- **Theme app extension** — bloques que aparecen en el theme editor del
  merchant. Sin tocar el código del theme. Reviews/sticky-bar/etc.
- **Checkout UI extension** — UI custom en checkout (solo Shopify Plus).
- **Customer account UI extension** — UI en la nueva customer account.
- **Admin block / Admin action** — extiende paneles del Admin con bloques
  reutilizables o acciones contextuales.
- **Shopify Functions** — lógica server-side embebida (discount, payment,
  delivery, validation). Rust o JavaScript-Wasm. Pre-compilado.
- **Flow action / trigger** — integraciones para Shopify Flow.
- **POS UI extension** — UI custom en Shopify POS.

#### MCP activo

- `shopify-dev` (STDIO, oficial) — incluye TODO: schemas GraphQL Admin
  API, Storefront API, Checkout API, tipos Liquid y **propiedades de
  cada componente Polaris**. El agente puede preguntar "qué props tiene
  IndexTable v13" en vivo.

#### Distribución

- **Shopify App Store** (público, requiere revisión de Shopify, ~$99-499
  margen mensual promedio según categoría).
- **Custom app** (privada, instalada solo en una tienda concreta).
- **Partner Manage Tier** (apps para clientes managed por agencia).

#### App Bridge 4 — patterns canon

```tsx
// 1. NavigationMenu (sidebar del Admin con links a tus páginas)
import { NavMenu } from '@shopify/app-bridge-react';

<NavMenu>
  <a href="/app" rel="home">Home</a>
  <a href="/app/products">Products</a>
  <a href="/app/settings">Settings</a>
</NavMenu>

// 2. SaveBar — auto-aparece al detectar cambios sin guardar
import { useAppBridge, SaveBar } from '@shopify/app-bridge-react';

const shopify = useAppBridge();
const [hasChanges, setHasChanges] = useState(false);

<SaveBar id="my-save-bar" open={hasChanges}>
  <button onClick={save} variant="primary">Save</button>
  <button onClick={discard}>Discard</button>
</SaveBar>

// 3. Resource Picker (productos, collections, variants, customers)
const picked = await shopify.resourcePicker({
  type: 'product',
  multiple: true,
  filter: { archived: false, variants: false }
});

// 4. Toast (notificaciones efímeras, success/info)
shopify.toast.show('Saved successfully', { duration: 3000 });

// 5. Modal (full-page dialog)
import { Modal } from '@shopify/app-bridge-react';
<Modal id="confirm-delete" variant="base">
  <p>Are you sure?</p>
  <button onClick={confirm}>Delete</button>
</Modal>
shopify.modal.show('confirm-delete');

// 6. Contextual Actions (acciones en cualquier resource page del Admin)
// Vienen de Admin block / action extensions (no de App Bridge directo).
```

Banner (errores) vs Toast (info): Toast es efímero y dismiss
automático; Banner es persistente y queda en la página hasta que el user
lo cierra o se resuelva el problema. Usa Banner para errores
recuperables y validaciones; Toast para confirmaciones de éxito.

#### GDPR Webhooks — OBLIGATORIOS para App Store

Sin estos 3 webhooks la app **NO PASA** la review. Implementa todos
aunque tu app no almacene PII (Shopify igualmente los exige).

```ts
// app/routes/webhooks/customers.data_request.tsx
import { authenticate } from '~/shopify.server';

export async function action({ request }: ActionFunctionArgs) {
  const { shop, payload } = await authenticate.webhook(request);
  // payload.customer.email, payload.customer.id, payload.orders_requested
  // Si almacenas datos del customer: emite un reporte al merchant (vía email/dashboard)
  // con TODO lo que tienes de ese customer. NO devuelvas datos al cliente.
  await logDataRequest(shop, payload);
  return new Response(null, { status: 200 });
}

// app/routes/webhooks/customers.redact.tsx
export async function action({ request }: ActionFunctionArgs) {
  const { shop, payload } = await authenticate.webhook(request);
  await deleteCustomerData(shop, payload.customer.id);
  return new Response(null, { status: 200 });
}

// app/routes/webhooks/shop.redact.tsx
export async function action({ request }: ActionFunctionArgs) {
  const { shop } = await authenticate.webhook(request);
  // Llega 48h después de uninstall. BORRA todos los datos del shop.
  await deleteShopData(shop);
  return new Response(null, { status: 200 });
}
```

Registralos en `shopify.app.toml`:

```toml
[webhooks]
api_version = "2026-01"

  [[webhooks.subscriptions]]
  topics = ["customers/data_request"]
  uri = "/webhooks/customers/data_request"

  [[webhooks.subscriptions]]
  topics = ["customers/redact"]
  uri = "/webhooks/customers/redact"

  [[webhooks.subscriptions]]
  topics = ["shop/redact"]
  uri = "/webhooks/shop/redact"
```

#### "Built for Shopify" — la certificación premium

Es el equivalente al "verified" badge en redes. Da visibilidad ALTA en
el App Store + aparece en listados curados. Gates:

- **Performance**: TTI < 1.0s en `/admin/apps/<app>` (Lighthouse mobile).
  Ojo: el iframe del Admin pesa. Optimiza loaders, lazy-load rutas,
  bundle splitting.
- **Polaris ONLY**: ni Material UI, ni Tailwind, ni Chakra. Polaris.
- **Mobile-first**: el Shopify mobile app embebe tu app en webview.
- **Accessibility**: WCAG 2.1 AA — usa Polaris correctamente, añade
  ARIA en lo custom.
- **Storefront performance** (si tu app inyecta scripts en el theme):
  no penalizar CWV del merchant.
- **App stability**: error tracking, retry logic, graceful degradation.
- **Documentation**: knowledge base público, support ≤ 24h.
- **Reviews**: 4.0+ stars con ≥ 50 reviews.

Aplica después de tener tu app aprobada. Beneficios: badge "Built for
Shopify", aparición en curated lists, prioridad en revenue share, mejor
ranking de búsqueda en el App Store.

#### App Store launch — checklist completo

1. **Quality Standards** — checklist requirements (este context block).
2. **Monetization** — billing API: recurring / one-time / usage.
   `appSubscriptionCreate` GraphQL mutation. Test mode con tiendas dev.
3. **Hosting** — Oxygen para Hydrogen, Vercel/Fly/Render para Remix
   apps, AWS/GCP para apps pesadas. **Webhook delivery garantizado** =
   tu servidor SIEMPRE responde 200 (o reintenta).
4. **App Store Review** — submit con listing optimizado (5 screenshots
   mobile + 5 desktop + video 60s + descripción 1500 chars + pricing
   transparente + categoría correcta + tags). Tiempo: 2-6 semanas
   típico. Top rejection: GDPR webhooks faltando, scope minimization
   violations, Polaris violations.
5. **Customer Care** — knowledge base + email support + intercom/
   crisp/zendesk. Response SLA: 24h business days. Estado público.

**Revenue share 2026**: **0% en los primeros $1.000.000 USD** de
revenue anual del App Store. Después: 15%. (Comparativa: Apple/Google =
30% siempre.)

#### Extension types — qué generar y para qué

```bash
shopify app generate extension --type <type>
```

| Type slug | UI? | Cuándo usarlo | Stack |
|---|---|---|---|
| `theme_app_extension` | Liquid blocks | Reviews/sticky-bar/widgets que el merchant añade al theme sin tocar Liquid | Liquid + JS + CSS |
| `checkout_ui_extension` | React | Banners/Surveys/Custom fields en checkout (Shopify Plus) | React + checkout-ui-extensions-react |
| `customer_account_ui_extension` | React | UI custom en /account (orders, loyalty, returns) | React + customer-account-ui-extensions |
| `ui_extension` (admin block) | React | Bloques contextuales en product/order/customer pages del Admin | React + admin-ui-extensions |
| `admin_action` (admin action) | React | Acciones contextuales (bulk export, custom modal) | React + admin-ui-extensions |
| `pos_ui_extension` | React Native-ish | UI custom en Shopify POS iOS/Android | React Native + POS UI |
| `flow_action` / `flow_trigger` | JSON config | Integraciones para Shopify Flow workflow builder | JSON + tu API |
| `web_pixel_extension` | Sandboxed JS | Tracking de eventos (browser/server) GDPR-compliant | JavaScript sandbox |
| `product_discounts` / `order_discounts` / `shipping_discounts` | Shopify Function | Lógica de descuento server-side | Rust o JS-Wasm |
| `payment_customization` / `delivery_customization` / `cart_validations` | Shopify Function | Reordenar/ocultar opciones, validar cart | Rust o JS-Wasm |

#### Theme App Extensions (TAE) — el camino premium

Permite que el merchant añada **bloques de tu app** dentro de su theme
desde el theme editor, sin tocar Liquid. Generar:

```bash
shopify app generate extension --type theme_app_extension --name reviews
```

Estructura típica:

```
extensions/reviews/
├── shopify.extension.toml
├── blocks/
│   ├── reviews-list.liquid     # el block que ve el merchant
│   └── star-rating.liquid
├── snippets/
│   └── _review-card.liquid
├── assets/
│   ├── reviews.css             # se carga solo en páginas con el block
│   └── reviews.js
└── locales/
    └── en.default.json
```

Ejemplo `blocks/reviews-list.liquid`:

```liquid
{% schema %}
{
  "name": "Product reviews",
  "target": "section",   <!-- "section" | "head" -->
  "stylesheet": "reviews.css",
  "javascript": "reviews.js",
  "settings": [
    { "type": "text",    "id": "title", "label": "Heading", "default": "Reviews" },
    { "type": "range",   "id": "limit", "label": "Max reviews", "min": 3, "max": 50, "step": 1, "default": 10 },
    { "type": "color_scheme", "id": "color_scheme", "label": "Color scheme" }
  ]
}
{% endschema %}

<div class="reviews" {% if block.shopify_attributes %}{{ block.shopify_attributes }}{% endif %}>
  <h2>{{ block.settings.title }}</h2>
  <!-- fetch a tu endpoint /apps/<your-app-handle>/reviews?product_id={{ product.id }} -->
</div>
```

Targets:
- `section` — el merchant lo añade dentro de cualquier section del theme.
- `head` — para inyectar scripts/styles globales (analytics, fonts).

El merchant lo añade desde *Theme editor → Add block → Apps → tu-app →
Reviews*. Tu app NO necesita modificar el theme del merchant.

Deploy: `npm run deploy` empuja la extension junto con el resto de la
app.""",
    "shopify-liquid-blank": """### Stack: **Shopify Liquid — Theme Store route** (desde cero, sin Dawn)

A diferencia de `shopify-liquid` (que clona Dawn), este stack scaffoldea
la **estructura mínima válida OS 2.0 vacía**. **Elegible** para el
Shopify Theme Store. Más esfuerzo upfront pero mayor margen comercial.

#### Lo que ya tienes scaffoldeado

- `config/{settings_schema,settings_data}.json` con un esqueleto curado
  (color_scheme_group + font_picker + layout + social + favicon).
- `layout/theme.liquid` canónico (skip-link, content_for_header, section
  groups header/footer, title/description SEO).
- `sections/{header,footer}-group.json` + sus `.liquid` mínimos válidos
  con `@app` blocks soportados.
- `blocks/` vacío — listo para que añadas theme blocks reutilizables.
- `templates/*.json` — 14 templates obligatorios + customers/* todos
  vacíos (`{ "sections": {}, "order": [] }`). Cumple el requisito de
  presencia pero TÚ rellenas cada uno con sections/blocks.
- `locales/en.default.{json,schema.json}` + `es.{json,schema.json}` con
  las claves base (accessibility, general, cart, products).
- `assets/base.css` con CSS variables de paleta y skip-link.
- `package.json` + `.prettierrc.json` + `.theme-check.yml` estricto
  (16 KB JS cap, ValidJSON, ValidSchema, RequiredLayoutThemeObject,
  UnreachableCode, ImgWidthAndHeight, MatchingTranslations).
- `.github/workflows/lighthouse-ci.yml`.
- `.mcp.json` con los 3 MCPs Shopify (igual que el stack Dawn).

#### Lo que TÚ tienes que construir

Sigue el mismo manual técnico que `shopify-liquid` (arquitectura,
performance budget, features mandatorias, ejemplos canónicos, dev tools,
Theme Store submission checklist al final — todo lo de arriba aplica).
Pero específicamente para Theme Store:

1. **Identidad visual ÚNICA** — diseño no reproducible cosméticamente
   con cambios de paleta o spacing. Reviewers rechazan themes que son
   "Dawn con paleta diferente".
2. **Settings curados** — no inundes con 300 opciones. Themes top
   tienen entre 30 y 80 settings TOTAL.
3. **Section presets diferenciados** — cada section principal con 3-5
   presets que demuestren versatilidad real.
4. **Demo store profesional** — productos plausibles, fotografía
   editorial, sin Lorem Ipsum, sin onboarding text.
5. **Las 18 features mandatorias** del Theme Store (faceted search,
   predictive search custom, gift cards, selling plans, Shop Pay
   Installments con `<shopify-payment-terms>`, pickup availability con
   `<pickup-availability-preview>`, variant images, Follow on Shop, etc.).
6. **i18n completo** en `locales/*.default.json` + `.schema.json`.
   ZERO hardcoded strings (auto-reject).
7. **Documentation HTML estática** para entregar al merchant —
   instalación + customization + lista de sections + FAQ.

#### MCPs activos (mismos 3)

`shopify-dev` (STDIO) · `shopify-storefront` (HTTP YOUR-SHOP) ·
`shopify-storefront-catalog` (HTTP UCP YOUR-SHOP).

#### Ejemplo de section premium para empezar

```liquid
{% comment %} sections/hero-banner.liquid {% endcomment %}
<section class="hero" style="--bg: {{ section.settings.bg_color.background }}">
  {%- if section.settings.image -%}
    {{ section.settings.image | image_url: width: 2200 | image_tag:
       loading: 'eager', fetchpriority: 'high',
       widths: '375, 768, 1280, 1920, 2200', sizes: '100vw',
       class: 'hero__img' }}
  {%- endif -%}
  <div class="hero__content">
    {%- for block in section.blocks -%}
      {%- case block.type -%}
        {%- when 'heading' -%}<h1>{{ block.settings.text }}</h1>
        {%- when 'paragraph' -%}<p>{{ block.settings.text }}</p>
        {%- when 'button' -%}<a class="btn" href="{{ block.settings.link }}">{{ block.settings.label }}</a>
        {%- when '@app' -%}{% render block %}
      {%- endcase -%}
    {%- endfor -%}
  </div>
</section>

{% schema %}
{
  "name": "Hero banner",
  "tag": "section",
  "class": "section section--hero",
  "settings": [
    { "type": "image_picker", "id": "image", "label": "Background image" },
    { "type": "color_scheme", "id": "bg_color", "label": "Color scheme" }
  ],
  "blocks": [
    { "type": "@app" },
    { "type": "heading",   "name": "Heading",   "settings": [{ "type": "text", "id": "text", "label": "Heading" }] },
    { "type": "paragraph", "name": "Paragraph", "settings": [{ "type": "richtext", "id": "text", "label": "Text" }] },
    { "type": "button",    "name": "Button",
      "settings": [
        { "type": "text", "id": "label", "label": "Label" },
        { "type": "url",  "id": "link",  "label": "Link" }
      ]
    }
  ],
  "max_blocks": 6,
  "presets": [
    { "name": "Hero banner", "category": "Hero",
      "blocks": [ { "type": "heading" }, { "type": "paragraph" }, { "type": "button" } ] }
  ],
  "enabled_on": { "templates": ["index", "page"] }
}
{% endschema %}
```

#### Theme Store submission checklist

Ver la sección homónima en el contexto del stack `shopify-liquid` arriba
— aplica igual. Diferencia clave: este stack **ya pasa** el filtro
"Dawn-derived" porque no se ha derivado de Dawn.""",
    "shopify-functions": """### Stack: **Shopify Functions** (Rust + Wasm)

Lógica **server-side custom** que Shopify ejecuta dentro de su infra
como módulos Wasm. NO necesita servidor propio. Reemplaza apps
tradicionales para casos de descuento/payment/delivery.

#### Targets disponibles

| Target | Para qué |
|---|---|
| `cart.lines.discounts.generate.run` | Product discount / order discount custom |
| `cart.delivery_options.transform.run` | Reordenar / renombrar / ocultar shipping options |
| `cart.payment_methods.transform.run` | Reordenar / ocultar payment methods |
| `cart.validations.generate.run` | Bloquear checkout con custom rules |
| `fulfillment_constraints.run` | Constraints sobre fulfillment (warehouse routing) |
| `purchase.product_run.run` | Custom pricing / product transforms |

#### Por qué Rust y no JS

Functions tienen un budget **estricto de <5 ms** que Shopify enforcea.
Pasar de ese límite = function rechazada en runtime. Rust → Wasm32 es la
única manera realista de cumplirlo + binarios pequeños (<256 KB).
JS-Wasm también está disponible pero ~10x más lento y ~5x más grande.

#### Estructura mínima

```
extensions/discount-function/
├── shopify.extension.toml      # target + input_query + export
├── Cargo.toml                  # crate-type cdylib + shopify_function dep
└── src/
    ├── run.graphql             # qué input recibe la function
    └── run.rs                  # la lógica
```

#### shopify.extension.toml canon

```toml
api_version = "2026-01"

[[extensions]]
type = "function"
name = "discount-function"
handle = "discount-function"

[extensions.build]
command = "cargo wasi build --release"
path = "target/wasm32-wasi/release/discount_function.wasm"

[extensions.targeting]
target = "cart.lines.discounts.generate.run"
input_query = "src/run.graphql"
export = "run"
```

#### Workflow

```bash
rustup target add wasm32-wasi             # primera vez
cargo install cargo-wasi                  # primera vez
npm install
npm run dev                               # arranca tunnel + dev mode
shopify app function build                # build Wasm
shopify app function run                  # test local con input.json
npm run deploy                            # publish (incluye Wasm + app metadata)
```

#### Combina con app embebida

Una Function NO funciona sola — vive dentro de una **app Shopify** que
la registra. El scaffold incluye la app Remix mínima. La UI (si tu
function necesita configuración del merchant) la pones en la app con
Polaris.

#### Distribución

App Store o custom app. Functions son una capability premium —
merchants pagan más por apps que las usan (típicamente $19-99/mes
recurrente).""",
    "shopify-storefront-webcomponents": """### Stack: **Shopify Storefront Web Components** (vanilla HTML + JS)

Embedded commerce en sites **NO-Shopify** (blogs, landing pages,
WordPress, Webflow, Framer, Notion sites, etc.). Componentes oficiales
de Shopify cargados via CDN — cero build complejo.

#### Setup (1 vez)

1. Activa la **Storefront API** en tu Shopify Admin: Apps → Develop apps →
   Create an app → Configure Storefront API access. Scopes mínimos:
   `unauthenticated_read_product_listings`,
   `unauthenticated_write_checkouts`.
2. Copia el **Storefront access token**.
3. Pégalo en `index.html` dentro de `<shopify-context store=YOUR-SHOP
   token=YOUR_TOKEN>`.

#### Componentes principales

- `<shopify-context>` — root, configura store + token (uno por página).
- `<shopify-product handle="...">` — wrapper de producto.
- `<shopify-product-media>` / `<shopify-product-title>` /
  `<shopify-product-price>` / `<shopify-product-description>` —
  campos individuales con slots.
- `<shopify-product-variant-selector>` — UI de variantes (size/color).
- `<shopify-product-quantity>` — input cantidad.
- `<shopify-product-buy-button>` — botón add-to-cart con loading state.
- `<shopify-cart>` — cart drawer/widget completo.
- `<shopify-collection handle="...">` — wrapper de colección.

#### Estilizado con `::part()`

Cada componente expone `parts` CSS para customizar SIN romper el
shadow DOM:

```css
shopify-product-buy-button::part(button) {
  background: var(--brand-color);
  color: white;
  padding: 1rem 2rem;
}
shopify-product-title::part(text) {
  font-size: 2rem;
  font-family: 'Fraunces', serif;
}
shopify-cart::part(drawer) {
  background: #fafaf5;
}
```

#### Checkout

Al añadir al carrito, el `<shopify-product-buy-button>` redirige al
checkout hosted (`tu-tienda.myshopify.com/checkout`). El carrito + pago
+ fulfillment los gestiona Shopify entero. Tu site solo es la vitrina.

#### MCPs activos

Mismos 3 que el resto de Shopify. `shopify-dev` (schemas Storefront API
para entender las queries), `shopify-storefront` (cart/policies),
`shopify-storefront-catalog` (búsqueda de catálogo).

#### Casos de uso reales

- Blog de marca con productos featured embebidos (Substack, Ghost).
- Landing page de campaña paid ads (separada del store).
- WordPress / Webflow / Framer site que embebe productos.
- Microsite de colaboración (artist drop, brand collab).
- Newsletter HTML con productos comprables.
- App nativa mobile con WebView que carga estos componentes.

#### Performance

Bundle inicial del CDN: ~80 KB gzip. Cero render-blocking si lo añades
con `type="module"`. CWV pasa fácil 95+.

#### Vender en Envato

Categoría ThemeForest "HTML Templates" o "Shopify Themes". Puedes
empaquetar tu site con un theme HTML estático + integración Shopify
Web Components como sección — ticket: $19-49, volumen alto.""",
    "shopify-checkout-extension": """### Stack: **Shopify Checkout UI Extension** (Shopify Plus only)

UI custom dentro del **checkout hosted de Shopify**: banners, surveys,
custom fields, upsells, loyalty widgets, country-specific compliance,
etc. Distribuido como una **app Shopify** con extensions.

#### ⚠️ Solo Shopify Plus

Las Checkout UI Extensions REQUIEREN que la tienda destino tenga el
plan **Shopify Plus** ($2.300+/mes). En tiendas non-Plus la extension
NO se carga. Mercado: agencias Plus, brands premium, B2B, enterprise.

#### Targets (9 disponibles)

| Target | Dónde aparece |
|---|---|
| `purchase.checkout.block.render` | Bloque libre que el merchant coloca con drag-and-drop |
| `purchase.checkout.delivery-address.render-before` | Antes del bloque shipping address |
| `purchase.checkout.payment-method-list.render-after` | Tras la lista de payment methods |
| `purchase.checkout.shipping-option-list.render-after` | Tras shipping options |
| `purchase.checkout.cart-line-item.render-after` | Tras cada line item del carrito |
| `purchase.checkout.header.render-after` | Header del checkout |
| `purchase.checkout.footer.render-after` | Footer del checkout |
| `purchase.thank-you.block.render` | Thank you page |
| `purchase.order-status.block.render` | Order status page |

Generar más extensions:

```bash
shopify app generate extension --type checkout_ui_extension --name <name>
```

#### Capabilities (`shopify.extension.toml`)

```toml
[extensions.capabilities]
network_access = false              # true para fetch a tu backend
block_progress = false              # true para bloquear el avance del checkout
api_access = true                   # queries Storefront API desde la extension
collect_buyer_consent.sms_marketing = false
```

#### Sandbox

Las extensions corren en un **Worker sandbox**: NO tienen acceso a:
- DOM directo (no `document.querySelector`).
- LocalStorage / cookies / sessionStorage.
- Network calls sin `network_access = true`.
- Librerías de tracking (Google Analytics, Meta Pixel) — usa Web Pixels
  extension para eso.

#### API canon (`useApi`)

```tsx
import {useApi, useCartLines, useApplyCartLinesChange} from '@shopify/ui-extensions-react/checkout';

const {buyerJourney, cost, shippingAddress, paymentOption, extension} = useApi();
const lines = useCartLines();
const applyChange = useApplyCartLinesChange();

await applyChange({
  type: 'addCartLine',
  merchandiseId: 'gid://shopify/ProductVariant/123',
  quantity: 1,
});
```

#### Componentes UI (cherry-pick)

- `<BlockStack>` / `<InlineStack>` — layout.
- `<Banner status="info|warning|critical|success">` — feedback.
- `<Heading level={2}>` / `<Text>` / `<TextField>` / `<Button>`.
- `<Checkbox>` / `<Select>` / `<RangeSlider>` / `<DatePicker>`.
- `<Image>` / `<Icon>` / `<Divider>`.
- `<Tooltip>` / `<Modal>` / `<Form>`.

#### Workflow

```bash
npm install
npm run dev                              # arranca app + extension con tunnel
shopify app generate extension           # añadir más
npm run deploy                           # publish a Shopify Partners
```

Cada deploy crea una **draft version** que el merchant activa en
*Settings → Checkout → Customize → Add app block*.

#### NO permitido (auto-reject)

- Tracking de PII fuera de los webhooks GDPR (usa Web Pixels).
- DOM manipulation custom (sandbox).
- Network sin declarar `network_access`.
- Hard-coded URLs sin variables de entorno.
- Bloquear progress sin razón válida.

#### Pricing

App Store o custom. Por contrato: $50-500/mes recurrente típico para
Plus merchants. Margen alto.""",
}


def _shopify_builder_context(stack_key: str) -> str:
    """Bloque de contexto específico del stack Shopify para CLAUDE.md."""
    return _SHOPIFY_BUILDER_CONTEXT.get(stack_key, "")


def _render_analysis_block(ai_analysis: str | None, kind: str) -> str:
    """Sección de análisis previo para CLAUDE.md, adaptada a la procedencia:

      reference → análisis IA de una referencia (modo recreate/adopt).
      market    → análisis de mercado (pestaña Market) — el agente decide stack/nicho.
      vibe      → dev_prompt del Vibe scaffolder (scratch).
    """
    if not ai_analysis:
        return ""
    text = ai_analysis.strip()
    if kind == "market":
        return (
            "## Análisis de mercado previo (pestaña Market)\n\n"
            "> Generado por ThemeForge con IA antes de crear este proyecto. **Léelo "
            "antes de proponer nada** — contiene el mapa del mercado de productos "
            "digitales 2026 (nichos top, stacks ganadores, gap analysis y "
            "recomendaciones concretas).\n>\n"
            "> El usuario te ha pasado este análisis **sin fijar stack ni nicho a "
            "propósito**: tu trabajo es leerlo, elegir el ángulo más vendible "
            "(nicho + stack + tipo de producto + USP) y **proponérselo antes de "
            "tocar código**. Confirma con él antes de scaffoldear.\n\n"
            + text + "\n"
        )
    if kind == "vibe":
        return (
            "## Briefing inicial (Vibe scaffolder)\n\n"
            "> Generado por ThemeForge con IA a partir de la descripción "
            "natural del usuario. Es el norte del producto — no la copia.\n\n"
            + text + "\n"
        )
    if kind == "brief":
        return (
            "## 🚨🚨 WEB A MEDIDA PARA UN CLIENTE DIRECTO — NO es un template de marketplace\n\n"
            "> **IGNORA por completo cualquier instrucción de ESTE documento sobre "
            "vender en marketplaces (ThemeForest, Envato, CodeCanyon, Theme Store), "
            "sobre escribir DOCUMENTACIÓN de producto, sobre 'demo data' genérica, "
            "onboarding, o requisitos de Envato. NADA de eso aplica aquí.** Esto es "
            "una web REAL para UN negocio concreto, que se le entrega a ESE cliente.\n>\n"
            "> **Materia prima REAL del cliente** (extraída de su web y Google por "
            "ThemeForge + revisada por el usuario): datos, carta/servicios/productos, "
            "horarios, fotos, branding y **EL CONTENIDO COMPLETO de su web actual** "
            "(todas sus páginas: inicio, nosotros/historia, servicios, blog/noticias, "
            "galería, contacto…). Está más abajo en «Contenido REAL de su web».\n>\n"
            "> **REGLAS OBLIGATORIAS (no negociables):**\n"
            "> 1. 📸 **USA SUS FOTOS REALES** — las URLs de imágenes del brief. "
            "Descárgalas a `public/`/`assets/` y úsalas en la web. "
            "**PROHIBIDO Unsplash, Pexels, fotos de stock, placeholders o imágenes "
            "inventadas.** Si falta alguna foto concreta, deja un hueco limpio o usa "
            "otra suya — NUNCA stock.\n"
            "> 2. 📝 **REPRODUCE TODO SU CONTENIDO** (sección «Contenido REAL»): cada "
            "página, cada texto, su historia, su blog/noticias, sus servicios. "
            "Reescríbelo MEJOR (copy más vendedor + SEO) pero **sin perder "
            "información ni secciones**. La web nueva debe tener TODO lo que tiene su "
            "web actual y más, nunca menos.\n"
            "> 3. Usa nombre, dirección, teléfono, horarios y carta/precios **tal "
            "cual** (no inventes nada).\n"
            "> 4. ❌ **Cero documentación, cero Lorem Ipsum, cero demo genérica, cero "
            "texto de onboarding.** La 'demo' ES su web real llevada x100 (mejor "
            "diseño, UX, velocidad y SEO).\n"
            "> 5. Si el stack trae boilerplate (restaurant-saas, etc.), rellénalo con "
            "estos datos y personalízalo a su branding — no rehagas la fontanería.\n\n"
            + text + "\n"
        )
    # default: reference
    return (
        "## Análisis IA previo de la referencia\n\n"
        "> Generado automáticamente por ThemeForge antes de crear el proyecto. "
        "**Léelo antes de tocar nada** — contiene la lectura técnica del template "
        "original, análisis de mercado y recomendación de stack para tu "
        "reimplementación.\n>\n"
        "> ⚠️ **Recordatorio crítico**: este análisis se hace para INSPIRARTE en "
        "funcionalidades. NO copies código, assets ni branding del template "
        "original (`reference/`). Reimplementa todo desde cero con código propio. "
        "Mira las \"🚨 Reglas Anti-copia\" más abajo.\n\n"
        + text + "\n"
    )


def render_context(
    stack_key: str,
    template_type: str,
    project_name: str,
    mode: str,
    reference_kind: str | None,
    reference_value: str | None,
    existing_repo: str | None,
    ai_analysis: str | None = None,
    niche: str | None = None,
    ai_analysis_kind: str = "reference",
) -> str:
    stack = STACKS[stack_key]
    type_unspecified = template_type.startswith("(Sin tipo")
    stack_unspecified = stack_key == "none"
    niche_clean = (niche or "").strip()
    niche_unspecified = (not niche_clean) or niche_clean.startswith("(Sin nicho")
    # Sistema de licencias: PRIORIZA el doc REAL del usuario en context-private
    # (p. ej. SISTEMA-PCREATIVE.md, el sistema pcreative con endpoint + contrato
    # + pubkey). Solo si no existe, cae a LICENSING-SYSTEM.md / al stub
    # `.template.md`. Antes solo leía "LICENSING-SYSTEM.md" exacto y fallaba con
    # "no se pudo leer" → el agente improvisaba endpoint/contrato (de ahí las
    # decisiones a medias del DECISIONS-PENDING.md).
    sistema_licencias = ""
    for _name in ("SISTEMA-PCREATIVE.md", "PCREATIVE-LICENSING.md",
                  "LICENSING.md", "LICENSING-SYSTEM.md"):
        _try = _read_context(_name)
        if "no se pudo leer" not in _try:
            sistema_licencias = _try
            break
    if not sistema_licencias:
        sistema_licencias = "_(no se pudo leer LICENSING-SYSTEM.md)_"

    # Modo "web a medida para cliente directo" (Generador de webs desde un lead):
    # NO es un producto de marketplace → banner que anula §A/§B y exige datos reales.
    is_brief = (ai_analysis_kind == "brief")
    brief_banner = ("" if not is_brief else (
        "\n> 🚨🚨🚨 **MODO WEB-A-MEDIDA (CLIENTE DIRECTO) — LEE ESTO PRIMERO**\n>\n"
        "> Este proyecto es una **web real para UN comercio concreto** que se le "
        "entrega a ese cliente. **NO es un template para vender en marketplace.**\n>\n"
        "> Por tanto: **IGNORA §A (Licensing) y §B (Requisitos Envato)** y cualquier "
        "mención a ThemeForest/CodeCanyon/Theme Store/documentación de producto/demo "
        "data genérica. **NO aplican.**\n>\n"
        "> Tu trabajo: recrear su web actual llevándola **x100** usando **SUS datos, "
        "SUS fotos y TODO su contenido reales** (ver «Brief del comercio» abajo). "
        "**PROHIBIDO Unsplash / fotos de stock / Lorem Ipsum / placeholders.**\n>\n"
        "---\n"))

    # ── Formato de producto Envato derivado del stack ────────────────────
    product_format = product_format_for(stack_key)
    if product_format in ("script-app", "mobile"):
        envato_doc_name = "REQUISITOS-CODECANYON-SCRIPT.md"
        requisitos_envato = _read_context(envato_doc_name)
    elif product_format == "unknown":
        envato_doc_name = None
        requisitos_envato = (
            "El stack aún NO está fijado, así que el formato Envato tampoco. "
            "**Primero** propón el stack en `ANALYSIS.md`; el formato — y por tanto "
            "el checklist que debes cumplir — se deriva de él:\n\n"
            "- Stack **estático** (HTML/Astro/Hugo/SPA build) → **Site Template** "
            "(ThemeForest): HTML/CSS válido, Lighthouse ≥ 90 y docs HTML estáticas.\n"
            "- Stack **backend/full-stack** (Laravel, Django, Next+BD, Rails, Nest, "
            "FastAPI…) → **Script/App** (CodeCanyon): instalador, esquema de BD + "
            "seeders, panel admin, configuración por `.env` y documentación de "
            "instalación. **NO** apliques el checklist de Site Template estático.\n"
            "- **WordPress** → tema/plugin (estándares WP + Theme Check).\n"
            "- **Móvil** → app (CodeCanyon mobile).\n\n"
            "Una vez fijes el stack, adopta el checklist Envato del formato "
            "correspondiente y avísame de cuál es."
        )
    else:  # site-template, wordpress
        envato_doc_name = "REQUISITOS-THEMEFOREST.md"
        requisitos_envato = _read_context(envato_doc_name)

    _PRODUCT_KIND = {
        "site-template": "plantilla web (Site Template)",
        "script-app": "script / aplicación full-stack",
        "mobile": "app móvil",
        "wordpress": "tema / plugin de WordPress",
        "unknown": "producto digital (formato a determinar según el stack)",
    }
    _MARKETPLACES = {
        "site-template": "ThemeForest, TemplateMonster, Creative Market, Gumroad",
        "script-app": "CodeCanyon (Envato), Gumroad y tu propia web",
        "mobile": "CodeCanyon (Envato), Apptopia, marketplaces de Flutter, GitHub",
        "wordpress": "ThemeForest / CodeCanyon (Envato), Gumroad",
        "unknown": "ThemeForest o CodeCanyon (Envato) según el formato que elijas",
    }
    product_kind = _PRODUCT_KIND[product_format]
    marketplaces = _MARKETPLACES[product_format]

    # Contexto para el agente: si es WordPress, ThemeForge ya levantó WP en
    # Docker (ver bloque WP del setup) y el preview apunta ahí.
    if product_format == "wordpress":
        wp_kind = "plugin" if stack_key == "wordpress-plugin" else "theme"
        wp_dir = "themes" if wp_kind == "theme" else "plugins"
        builder_block = _wp_builder_context(stack_key)
        wp_dev_block = f"""
## Entorno WordPress (Docker) — YA INSTALADO Y FUNCIONAL

ThemeForge ha levantado **WordPress + MariaDB en Docker** y ha **instalado WordPress**
(admin / admin) **antes** de este setup. **El preview de ThemeForge ya apunta a ese
WordPress en vivo** — NO tienes que instalar, configurar ni levantar nada.

- URL, puerto y credenciales exactas: en **`WORDPRESS-DEV.md`** (raíz del proyecto). Léelo.
- Tu {wp_kind} está montado en `wp-content/{wp_dir}/<slug>`: lo que escribas se ve en vivo.
- Hay un helper **`./wp`** (wp-cli dentro del contenedor). Activa tu {wp_kind} cuando tenga
  su cabecera: `./wp {wp_kind} activate <slug>`.
- **Autologueado como admin** en `localhost` (mu-plugin de ThemeForge): abre el preview y vas
  directo al wp-admin sin formulario.

### MCPs disponibles para operar WordPress

- **`wordpress`** (bridge oficial de Automattic vía `.mcp.json`) — control nativo del core:
  posts, páginas, media, opciones, customizer, usuarios. Úsalo para todo lo que sea CRUD WP.
- **Royal MCP** (instalado en el WP, free) — 67 operaciones con auth + audit log; soporta
  meta de ACF/MetaBox/JetEngine/Pods/CPT UI y term meta de Yoast/Rank Math/AIOSEO.
  Para wirearlo, ver `WORDPRESS-DEV.md` (genera API key en wp-admin → Royal MCP).
- **Novamira Pro** (premium, si declarado en `wp_packs.json`) — el único que entiende
  estructura interna de los builders: widgets atómicos de Elementor, templates de Bricks,
  layouts de Divi, plus ACF/JetEngine/Meta Box/Pods. Configuración exacta desde
  wp-admin → Novamira → AI Agent Setup.

Combina con las **skills de WordPress** (`.claude/skills/`: wp-block-themes, wp-rest-api…)
que te dan el know-how de desarrollo.

{builder_block}

⚠️ **NO** ejecutes `wp core install`, ni levantes otro WordPress, ni edites `wp-config.php`:
ya está corriendo y servido en el preview. Trabaja directamente sobre tu {wp_kind}.
"""
        # Spec del plugin instalador de demos — OBLIGATORIO en themes WP.
        wp_installer_block = ("\n---\n\n" + _read_context("WP-DEMO-INSTALLER.md")) if wp_kind == "theme" else ""
    elif product_format == "shopify":
        builder_block = _shopify_builder_context(stack_key)
        wp_dev_block = f"""
## Entorno Shopify — provisión y herramientas

ThemeForge ha scaffoldeado este proyecto invocando los tooling oficiales
de Shopify (no se bundlea nada en el repo). Tienes:

- **Shopify CLI** (`@shopify/cli`, MIT) — comandos `shopify theme dev`,
  `shopify theme check`, `shopify theme push`, `shopify theme package`.
- **3 MCPs activos** en `.mcp.json` (ver `README-MCP.md` o
  `README-HYDROGEN.md`):
  - `shopify-dev` (oficial, STDIO) — admin/storefront/checkout API docs,
    GraphQL schema introspection, tipos Liquid, esquemas section/block,
    componentes Polaris.
  - `shopify-storefront` (oficial, HTTP zero-auth) — cart, policies, FAQ.
    Sustituye `YOUR-SHOP` por tu dominio.
  - `shopify-storefront-catalog` (oficial, HTTP, UCP) — catálogo con
    búsqueda en lenguaje natural.

Para probar de verdad necesitas: cuenta Shopify Partners (gratis) y una
tienda de desarrollo (Partners → Stores → Add development store).

{builder_block}
"""
        wp_installer_block = ""
    else:
        wp_dev_block = ""
        wp_installer_block = ""

    if product_format in ("script-app", "mobile"):
        objetivos_block = """## Objetivos finales

1. Cumplir el checklist Envato del §B (CodeCanyon Script/App) al 100%.
2. **Instalación reproducible**: `.env.example` completo, migraciones + seeders de
   demo, y un comando documentado que deja la app corriendo en una máquina limpia.
3. **Funcional de verdad**: auth, BD, panel admin y flujos principales operativos
   con demo data realista (no maqueta estática).
4. **Documentación de instalación y uso** (no "docs HTML estáticas" de site template).
5. Seguridad básica: validación en servidor, hashing de credenciales, sin secretos
   hardcodeados (todo por `.env`).

## Restricciones

- Código limpio y mantenible; configuración 100% por `.env`.
- Protección contra SQLi/XSS/CSRF; manejo de errores sin filtrar trazas en prod.
- UI del panel responsive y accesible (WCAG AA), con estados hover/focus/error.
- Assets libres de derechos (ver sección §C abajo)."""
    elif product_format == "unknown":
        objetivos_block = """## Objetivos finales

> El formato (y su checklist) depende del stack que elijas — ver §B. Cuando lo
> fijes, adopta los objetivos del formato correspondiente:
> - **Site Template** (estático): Lighthouse ≥ 90, HTML/CSS válido, docs HTML.
> - **Script/App** (backend): instalador, BD + seeders, admin, docs de instalación.

1. Cumplir el checklist Envato del §B al 100% (el del formato real de tu stack).
2. Producto que arranca y funciona con demo data realista desde el primer momento.
3. Responsive (360→1920) + accesible (WCAG AA) en la UI.
4. Variantes/demos competitivos en el nicho.

## Restricciones

- Sin secretos hardcodeados; configuración por `.env` si el stack tiene backend.
- WCAG AA y `prefers-reduced-motion` respetado en la UI.
- Assets libres de derechos (ver sección §C abajo)."""
    elif product_format == "shopify":
        objetivos_block = """## Objetivos finales — Shopify theme

1. Cumplir las **Shopify Theme Store Quality Guidelines** OFICIALES — bar
   más alto de la industria. Aunque vendas en ThemeForest, esto te
   posiciona en la cima:
   - Lighthouse mobile **60+ mínimo** (home/collection/product, avg).
     Top themes pasan **90+**.
   - **Accessibility 90+ OBLIGATORIO**.
   - `shopify theme check` SIN errores ni warnings críticos.
   - WCAG 2.1 AA: contraste 4.5:1 texto regular, 3:1 large/UI, focus
     visible, navegación teclado, skip link, alt en todas las imágenes,
     `aria-live` para cambios dinámicos (cart, search), touch targets
     ≥ 44×44 px.
   - Multilocale (i18n en `locales/*.json`, ZERO texto hardcoded).
   - Soporte browsers: Safari 2 últimas, Chrome 3 últimas, Firefox 3
     últimas, Edge 2 últimas (desktop) + Mobile Safari, Chrome Mobile,
     Samsung Internet + webviews Instagram/Facebook/Pinterest.
2. **18 features mandatorias** Theme Store (faceted search, gift cards,
   predictive search, selling plans, Shop Pay Installments, unit
   pricing, variant images, Follow on Shop, etc.) — ver detalle arriba.
3. Templates JSON completos: 404, article, blog, cart, collection,
   customers/*, gift_card, index, page, password, product, search.
4. Patrones de conversión: cart drawer, quick add, predictive search
   custom, sticky ATC, variant swatches, recently viewed, upsells.
5. Demo data realista (NO Lorem Ipsum, NO onboarding text). Productos
   plausibles con multimedia auténtica.
6. Documentación pública + FAQ + contact form + respuesta ≤ 2 días.

## Restricciones (auto-rechazo si fallan)

- **JS bundle < 16 KB minified**. NO React/Vue/Angular/jQuery.
- **NO Sass/SCSS** — CSS plano.
- **NO** dependencia de apps para features core.
- **NO** Lorem Ipsum ni texto onboarding en demo.
- **NO** crédito de designer ni affiliate links embebidos.
- **NO** distribución en otros marketplaces si vas a Theme Store
  (exclusividad obligatoria — Theme Store route).
- Scripts hospedados en Shopify (excepto librerías de terceros aprobadas).
- Sin secretos hardcodeados; settings en `config/settings_schema.json`.
- Compatibilidad con apps top (Klaviyo, Loox/Judge.me, Bold) — placeholders.
- Assets libres de derechos (ver §C)."""
    else:  # site-template / wordpress
        objetivos_block = """## Objetivos finales

1. Cumplir el checklist Envato del §B (ThemeForest Site Template) al 100%.
2. Lighthouse ≥ 90 Performance / SEO / Accessibility / Best Practices.
3. Documentación HTML estática en `documentation/`.
4. Variantes/demos competitivos en el nicho.

## Restricciones

- HTML/CSS válido (W3C).
- Responsive 360/768/1024/1280/1440/1920.
- WCAG AA: contraste, ARIA, navegación teclado.
- `prefers-reduced-motion` respetado.
- Assets libres de derechos (ver sección §C abajo)."""

    # --- Entregable MULTIPÁGINA (obligatorio en CUALQUIER stack web) ---------
    # Aplica a nativo y WebUI por igual (ambos usan este mismo contexto).
    if product_format == "mobile":
        pages_block = ""  # app móvil: navegación por pantallas, no "páginas web"
    elif product_format == "script-app":
        pages_block = """## 📄 Entregable MULTI-VISTA / multipágina (OBLIGATORIO)

Aunque sea una app/script con backend, **no entregues una sola pantalla**.
Implementa **varias vistas/páginas reales y navegables** (no un único dashboard
vacío): landing pública + auth (login/registro) + varias secciones del panel
(dashboard, listado, detalle, ajustes/perfil) + páginas de error (404/500).
Cada vista con demo data realista y distinta, responsive 360→1920 y WCAG AA."""
    else:
        # site-template / wordpress / shopify / unknown → tema/sitio multipágina
        pages_block = """## 📄 Entregable MULTIPÁGINA (OBLIGATORIO en stacks web)

Este template **NO es una landing de una sola página**. Salvo que el usuario lo
pida explícitamente, entrega un sitio **multipágina**: varias páginas/rutas
**reales y navegables**, no secciones ancladas (`#anchor`) en un único scroll.

**Mínimo de páginas reales** (adáptalas al tipo/nicho del §D — renombra/añade
según el sector, p. ej. *Menú* en restaurante, *Portfolio* en agencia,
*Habitaciones* en hotel, *Tienda/Producto* en e-commerce):

- **Home / Inicio**
- **About / Nosotros**
- **Services / Features** (o el catálogo equivalente del nicho)
- **Pricing / Planes** (si encaja con el modelo de negocio)
- **Blog** (índice) + **Blog post / artículo** (detalle)
- **Contact / Contacto** (formulario validado, aunque sea maqueta)
- **404** personalizada

Reglas:
- Cada página es una **ruta real** del stack, no un ancla. Next/Astro/Remix →
  archivos en el router; Vite/SPA → rutas del router (React Router, Vue Router…);
  WordPress → *page templates* + `single`/`archive`/`404`; Shopify → templates
  `page.*`/`blog`/`article` + secciones. El **header/footer enlaza a todas**.
- **Demo data realista y distinta por página** (no clones la misma sección).
  Cada página se ve 100% terminada al primer `npm run dev`.
- Todas las páginas: responsive 360→1920, WCAG AA, SEO por página
  (title/meta/OG propios) y `prefers-reduced-motion`.
- Si el tipo elegido es intrínsecamente *one-page* (porque se pidió así o es un
  widget), respétalo — pero entonces entrega **demos/variantes** adicionales en
  su lugar para que el paquete no sea una única pantalla."""

    if mode == "scratch":
        mode_block = (
            "## Modo: desde cero\n\n"
            "No hay template de referencia. Diseña la plantilla desde cero apuntando a\n"
            "lo que mejor vende según los MDs de mercado en `context/`.\n"
        )
    elif mode == "recreate" and reference_kind == "figma":
        # Importar diseño de Figma (del PROPIO usuario): implementar con
        # fidelidad vía el MCP figma-context. NO aplican reglas anti-copia
        # (no es un template ajeno — es su diseño).
        mode_block = f"""## Modo: implementar diseño de Figma

Diseño de origen (Figma, del usuario): {reference_value}

### Tu tarea
1. **Lee el diseño con el MCP de Figma** (figma-context / `figma-developer-mcp`):
   extrae layout, espaciado, tipografía, colores/tokens, componentes y assets del
   frame/archivo de la URL. El MCP usa el `node-id` de la URL (el usuario copia el
   link con clic derecho → *Copy link to selection* en Figma).
2. **Implementa el diseño con fidelidad** en el stack del proyecto: estructura,
   responsive, estados, interacciones. Reprodúcelo con precisión — es del usuario.
3. **Demo data completa + imágenes reales** (Unsplash/Pixabay) donde el diseño
   tenga placeholders. Nada de lorem ipsum ni imágenes rotas.
4. **Envato-ready**: responsive, accesible (WCAG AA), SEO, código limpio, docs.

> Requiere `FIGMA_API_KEY` configurado (Settings → 🔑 AI credentials → Figma) y el
> MCP `figma-context` activo. Si el MCP no responde, pídele al usuario su token."""
    elif mode == "recreate":
        if reference_kind == "url":
            ref_descr = f"Web demo descargada con wget desde: {reference_value}"
        elif reference_kind == "zip":
            ref_descr = f"Template extraído de un .zip local: {reference_value}"
        else:
            ref_descr = f"Carpeta local con el template referencia: {reference_value}"
        mode_block = f"""## Modo: recrear referencia (reverse-engineer)

En `reference/` tienes el material de referencia.

- Origen: {ref_descr}

### Tu tarea

1. **Estudia** la referencia: estructura de páginas, layout, paleta, tipografía,
   componentes, animaciones, copy, sectores objetivo.
2. **Documenta** un análisis breve en `ANALYSIS.md`: qué está bien, qué hay
   que mejorar, qué incumple los REQUISITOS ENVATO (§B).
3. **Reimplementa desde cero** usando el stack del proyecto, sin copiar
   código. Renombra clases, reorganiza componentes, mejora a11y/SEO/perf.
4. **Mejora** sobre la referencia: variantes de color, modo oscuro, mejor
   Lighthouse, micro-interacciones, demos adicionales.

### 🚨 REGLA INNEGOCIABLE — Anti-copia

**`reference/` es SOLO para estudio.** Está en `.gitignore` y NO va al
paquete final. De ahí **NO se copia NADA**:

- ❌ **NADA de código** (HTML, CSS, JS, TS, PHP, Dart, Vue, Blade…).
   Si necesitas un patrón visual, mira la referencia, **cierra el archivo
   y reescribe desde cero** con tus convenciones (naming, indentación,
   estructura de carpetas).
- ❌ **NADA de assets propietarios** (imágenes, iconos, fuentes con
   licencia restrictiva, vídeos). Usa Unsplash/Pexels/Heroicons/Lucide.
- ❌ **NADA de copy textual** ni branding (logos, nombres, eslóganes).
- ❌ **NADA de configuración propietaria** (claves API ajenas, IDs de
   Stripe del autor original, webhooks externos, tokens).

✅ **Solo se copian IDEAS Y FUNCIONALIDADES**: qué features tiene la
referencia, cómo estructura los flujos de usuario, qué integraciones
plantea, qué problemas resuelve. Todo eso se **reimplementa desde cero
con tu propio código y tus propios assets**.

Si dudas si algo "se puede copiar", la respuesta por defecto es **NO**.
En `licensing.txt` del paquete final cita patrones genéricos de
inspiración, jamás marcas ni nombres del template original.

### Autoskills (lanza tú cuando proceda)

ThemeForge no ha podido ejecutar `npx autoskills` durante el setup porque
la raíz aún estaba vacía. **En cuanto hayas hecho el scaffold del stack
elegido** (típicamente `create-next-app`, `composer create-project laravel/laravel`,
`flutter create`, etc.) y tengas `package.json`/`composer.json`/`pubspec.yaml`
en la raíz, ejecuta:

```bash
npx --yes autoskills -a claude
```

Esto auto-instala las skills relevantes según las dependencias detectadas.

**Mono-repo (apps/web, apps/admin, etc.)**: si trabajas con un mono-repo,
ejecuta `autoskills` **dentro de cada sub-app** para que detecte el stack
de cada una. Las skills se instalan en `apps/<app>/.agents/skills/` y
autoskills crea automáticamente los symlinks `apps/<app>/.claude/skills/`
que Claude Code escanea.

**Importante para auto-trigger**: Claude Code solo ve las skills del
`.claude/skills/` del directorio donde **lo lances**. Por eso:

- **Para skills cross-cutting** (accessibility, seo, frontend-design,
  tailwind-css-patterns): ThemeForge las agrega automáticamente a la
  raíz `<repo>/.claude/skills/`. Disponibles desde cualquier cwd.
- **Para skills stack-specific** (laravel, next, flutter, react…):
  `cd apps/<app> && claude` para verlas en auto-trigger sin que las de
  otras apps contaminen el contexto.
"""
    elif mode == "adopt":
        mode_block = """## Modo: adoptar template local (mono-repo posible)

El contenido completo del template original se copió tal cual a la raíz del
proyecto. **NO está en `reference/`** — trabajamos directamente con estos
archivos.

### Tu tarea

1. **Explora la estructura**: si hay varios subdirectorios con stack propio
   (Laravel, Next.js, Flutter, etc.), trátalo como mono-repo y documenta
   en `ANALYSIS.md` cuántas piezas hay y qué hace cada una.
2. **Identifica dependencias compartidas**: BD, API, autenticación. Si hay
   un backend Laravel/Node y clientes que lo consumen, deja documentado el
   contrato (rutas, payloads, auth).
3. **Define el plan de modernización**: actualización de versiones, refactor
   de capas obsoletas, mejoras según los REQUISITOS ENVATO (§B).
4. **Mantén coherencia entre piezas**: cualquier cambio en el modelo de
   datos o las rutas se propaga a todos los clientes (web + mobile +
   admin).
5. **Postgres compartido**: si el proyecto tiene BD provisionada
   automáticamente por ThemeForge, comparte la misma instancia entre los
   sub-proyectos que la necesiten (admin Laravel + web Next + apps).
"""
    else:  # existing
        mode_block = f"""## Modo: trabajar sobre repo existente

Este proyecto es un clone de `{existing_repo}` con su historial git intacto.

### Tu tarea

1. **Explora** el repo: árbol de archivos, dependencias, stack real, scripts.
2. **Documenta** estado actual en `ANALYSIS.md`: qué hace, su arquitectura,
   bugs aparentes, deuda técnica, oportunidades de mejora.
3. **Pregunta al usuario** sus objetivos concretos para este sprint:
   actualización de versiones, añadir feature X, refactor Y, mejor doc, etc.
4. Trabaja **manteniendo coherencia** con el código y convenciones existentes.
   No reescribas a tu gusto componentes que ya funcionan.
5. Verifica que el resultado sigue cumpliendo los REQUISITOS ENVATO (§B).

Los commits que hagas se añaden encima del historial existente.
"""

    # Bloque de calidad de UI. framer-motion + 21st.dev (magic/shadcn) SOLO
    # existen en frontends React/JS. En PHP/Smarty (PrestaShop, Magento…), Ruby,
    # etc. se inyecta una versión de "calidad de diseño" con las herramientas
    # nativas del stack, sin mandar usar libs que ahí no aplican.
    _ui_lang = (stack.get("language", "") or "").lower()
    _ui_is_react = any(k in _ui_lang for k in ("react", "next", "typescript", "javascript", "remix")) and not any(
        k in _ui_lang for k in ("php", "smarty", "ruby", "java", "kotlin", "go", "golang",
                                "rust", "elixir", "phoenix", "swift", "dart", "flutter", "c#", ".net", "blazor", "python"))
    if _ui_is_react:
        uipro_block = """## 🎨 UI PRO + ANIMACIONES — OBLIGATORIO (21st.dev + framer-motion)

> 🎯 Esta web debe quedar a nivel de **ESTUDIO DE DISEÑO**: profesional,
> animada y pulida — NUNCA una plantilla básica. Es un requisito, no un extra.

Si es una web React (Next/Vite/Remix/…), ThemeForge ya ha instalado
**framer-motion**, escrito **`UI-MOTION.md`** en la raíz y cableado (si hay key
21st.dev) el MCP **`magic`** en `.mcp.json`.

**LEE `UI-MOTION.md` AHORA y SÍGUELA AL PIE DE LA LETRA** (es la guía completa).
En resumen, sin que te lo pida el usuario y como parte de la primera versión:
1. Comprueba `/mcp` → el server **`magic`** debe estar *connected*. Para CADA
   sección visual usa **`21st_magic_component_inspiration`** (trae componentes
   pro del registro 21st.dev al chat, SIN abrir navegador), **elige TÚ la mejor**
   para el nicho y rellénala con el **contenido REAL**. ❌ NO uses
   `21st_magic_component_builder` (`/ui`) desatendido: abre el navegador y se
   cuelga esperando que el usuario elija. Si `magic` falla, constrúyela tú al
   mismo nivel.
2. **Anima con framer-motion**: reveal al scroll (`whileInView` once), stagger en
   grids, micro-interacciones hover/tap, hero cinematográfico, parallax
   (`useScroll`), tilt 3D, count-up, marquee, `AnimatePresence`. Respeta SIEMPRE
   `useReducedMotion` y anima solo `transform`/`opacity`.
3. Calidad de estudio: tipografía con jerarquía, espaciado generoso, paleta
   coherente + acento, estados hover/focus, `next/image`, responsive 360→1920,
   WCAG AA. Aplica también las skills de `.claude/skills/` (UI/UX Pro)."""
    else:
        uipro_block = """## 🎨 CALIDAD DE DISEÑO — OBLIGATORIO

> 🎯 Esta web/theme debe quedar a nivel de **ESTUDIO DE DISEÑO**: profesional y
> pulida — NUNCA una plantilla básica. Es un requisito, no un extra.

Sin que te lo pida el usuario, como parte de la primera versión:
1. Tipografía con jerarquía clara, espaciado generoso, paleta coherente + acento.
2. Estados hover/focus y micro-interacciones con las herramientas NATIVAS de este
   stack (CSS/transitions/animations, motor de plantillas correspondiente). NO uses
   framer-motion ni el MCP 21st.dev: no aplican a este stack.
3. Responsive 360→1920, imágenes optimizadas, accesibilidad WCAG AA.
4. Aplica las skills de `.claude/skills/` (UI/UX Pro) adaptadas a este stack."""

    _md = f"""# Contexto del proyecto: {project_name}
{brief_banner}
> **LECTURA OBLIGATORIA**
>
> Antes de cualquier otra acción en este proyecto, asimila TODO el contenido
> de las secciones **§A "LICENSING SYSTEM"** y **§B "REQUISITOS ENVATO"**
> que vienen al final de este archivo. Son requisitos no negociables:
>
> - §A define cómo este theme conecta al sistema de licencias (si lo hay).
>   Si vas a publicar el theme bajo el sistema configurado en
>   `~/.config/themeforge/licensing.json`, sigue el patrón al pie de la letra.
> - §B es el checklist de Envato. No empieces a entregar nada sin haberlo
>   validado contra esa lista.
>
> Los demás archivos en `context/` (research de mercado, ideas de templates,
> análisis de competencia, etc.) están como referencia y los puedes leer
> con la tool Read cuando los necesites. Listado completo con `ls context/`.

{product_kind.capitalize()} destinada a {marketplaces}.
{wp_dev_block}
## Stack

{('- **Stack**: no fijado a priori. Antes de empezar, analiza la referencia '
  '(si la hay) y propón el stack más adecuado en `ANALYSIS.md`.') if stack_unspecified else (
    f"- **Stack**: {stack['name']}\n"
    f"- **Categoría**: {stack['category']}\n"
    f"- **Lenguaje principal**: {stack['language']}\n"
    f"- **Versión mínima requerida**: {stack['min_version']}\n"
    f"- **Notas técnicas**: {stack['notes']}"
)}

## Tipo de template

{('- **Tipo**: ' + template_type) if not type_unspecified else (
    '- **Tipo**: no fijado a priori. Detéctalo de la referencia/repo y '
    'propónlo en `ANALYSIS.md`.'
)}
{('- **Nicho / industria objetivo**: ' + niche_clean + ' (ver §D abajo para tono, paleta y demo data específica)') if not niche_unspecified else (
    '- **Nicho / industria**: genérico — adapta el demo data al tipo elegido arriba'
)}

{pages_block}

{mode_block}

{_render_analysis_block(ai_analysis, ai_analysis_kind)}
{uipro_block}

## 🛠️ Estás trabajando DENTRO de ThemeForge

Este proyecto fue creado por **ThemeForge** (un builder GUI Python/PyQt6
que vive en `~/Proyectos/themeforge/`). Antes de tomar decisiones técnicas
que afecten al setup del proyecto, ten en cuenta:

### Lo que ThemeForge gestiona POR TI

- **Preview embebido**: hay una `QWebEngineView` que carga la URL del
  dev server. Cuando el usuario te diga "lanza el preview" o "arranca
  el dev server", **NO inicies `npm run dev` tú mismo en una terminal
  paralela** — eso crea procesos duplicados. Avísale al usuario que
  pulse el botón **▶ Start preview** del ProjectWindow (o equivalente
  para su sub-app en mono-repos).
- **Terminal embebida**: hay un xterm.js vivo en el ProjectWindow donde
  ya estás corriendo. Cuando ejecutes comandos `Bash`, salen ahí.
- **Puerto único asignado** persistido en `~/.config/themeforge/ports.json`.
  Para este proyecto se le asignó un puerto específico — si lanzas el
  dev server manualmente con otro puerto, el preview embebido no lo
  detectará.
- **Postgres del proyecto**: si está provisionado, el container vive en
  `themeforge-pg-<slug>` con su volumen propio. La URL está en `.env`
  como `DATABASE_URL`.
- **Re-detectar perfil**: si el stack cambia (instalas un framework,
  haces scaffold, etc.) el usuario tiene un botón **🔄 Re-detectar**
  arriba de su ProjectWindow para que ThemeForge actualice el perfil.

### Mono-repos (apps/* y packages/*)

Si trabajas en un mono-repo, ThemeForge detecta sub-apps automáticamente
y muestra un dropdown "Sub-proyecto" arriba del preview. Lanzar el dev
server de la sub-app correcta es responsabilidad del usuario (al elegir
en el dropdown). Tú no tienes que tocar nada.

### Cosas que es seguro que hagas

- Editar/crear código en el filesystem.
- Ejecutar comandos puntuales (`tsc --noEmit`, tests, lint, migraciones).
- Instalar dependencias (`npm install`, `composer install`).
- Hacer `git add/commit`.

### Cosas que ThemeForge prefiere que NO hagas

- Lanzar `npm run dev` / `vite` / `php artisan serve` en background si
  el usuario ya tiene el botón Start del preview. Duplica procesos y
  ocupa el puerto asignado.
- Modificar `.claude/settings.json` ni `.claude/skills/` arbitrariamente
  — ThemeForge ya cableó las skills correctamente al crear el proyecto.
- Cambiar el `DATABASE_URL` del `.env` si la BD viene de ThemeForge —
  el container Postgres asociado deja de mapear correctamente.

### Cómo reportar problemas del setup al usuario

Si detectas que el detector de preview no encajó (lanza puerto incorrecto,
el stack real es otro, etc.), dile al usuario:
> "El detector de ThemeForge no pillaron este caso. Si quieres lo arreglo
> editando `~/Proyectos/themeforge/preview.py` o `themeforge.py` y se lo
> reportas para futuros proyectos."

ThemeForge es código del propio usuario, no es propietario — todo es
editable y los bug fixes se aplican a futuros proyectos creados.

## Archivos de contexto

Discovery dinámico: ThemeForge copia al proyecto cualquier `*.md` que
encuentre en `~/.config/themeforge/context-private/` (versiones reales
del usuario) y los `*.template.md` del repo `context/` que no tengan
equivalente privado.

Archivos típicamente presentes en `context/`:

- El **checklist Envato (§B)**, al final de este archivo, es el criterio de aceptación obligatorio.
- `LICENSING-SYSTEM.md` — arquitectura del sistema de licencias
  configurado en `~/.config/themeforge/licensing.json` (verify endpoint,
  panel admin, integración en el theme). Léelo si vas a publicar este
  theme bajo licencia.
- `MARKET-RESEARCH.md`, `IDEAS.md`, `COMPETITORS.md` — research del
  autor sobre el mercado y la competencia (opcional, contenido libre).

{objetivos_block}

## §C — Assets visuales y demo data (OBLIGATORIO desde el primer commit)

**No entregues nunca un template con placeholders grises, "lorem ipsum"
genérico o "John Doe / Test User".** Cada sección debe verse 100% terminada
al primer `npm run dev` — con imágenes reales y copy realista del nicho.

Esto es **no negociable**: ningún comprador de ThemeForest/CodeCanyon paga
por un template que parece a medio hacer. La primera impresión la dan los
assets y la coherencia del contenido.

### C.1 — Imágenes: usa SIEMPRE estos providers libres de derechos

| Provider | Hot-link directo en `src=""` | Cuándo |
|---|---|---|
| **Unsplash** | `https://images.unsplash.com/photo-<ID>?w=1600&q=80&auto=format&fit=crop` | Fotos premium (hero, gallery, blog) |
| **Pexels** | `https://images.pexels.com/photos/<ID>/pexels-photo-<ID>.jpeg?auto=compress&w=1600` | Alternativa a Unsplash |
| **Pixabay** | `https://cdn.pixabay.com/photo/<path>.jpg` | Stock genérico |
| **Picsum** | `https://picsum.photos/seed/<slug>/1200/800` | Placeholders deterministas para dev |
| **DiceBear** | `https://api.dicebear.com/7.x/avataaars/svg?seed=<name>` | Avatares de usuarios |
| **UI Avatars** | `https://ui-avatars.com/api/?name=Sarah+Chen&background=random` | Avatares con iniciales |
| **Logoipsum** | `https://img.logoipsum.com/<n>.svg` | Logos placeholder para "trusted by" |

**Ejemplo concreto** (hero de una landing):

```html
<img
  src="https://images.unsplash.com/photo-1531297484001-80022131f5a1?w=1600&q=80&auto=format&fit=crop"
  alt="Modern team collaborating on a laptop"
  loading="eager"
  width="1600" height="900"
  class="rounded-2xl shadow-2xl"
/>
```

**Reglas de imágenes (todas obligatorias):**

- ✅ URLs reales de Unsplash/Pexels con parámetros de optimización (`?w=`, `?q=80`, `?auto=format`).
- ✅ `alt` descriptivo en CADA imagen (a11y + SEO + Lighthouse).
- ✅ `loading="lazy"` below the fold; `loading="eager"` arriba del fold.
- ✅ `width` y `height` explícitos para evitar CLS.
- ✅ Mínimo **8-12 imágenes únicas** distribuidas en el template (no la misma 4 veces).
- ✅ Atribución en `licensing.txt` (Unsplash/Pexels no la exigen, pero ThemeForest valora documentarlo).
- ❌ NO uses `placeholder.com`, `via.placeholder.com`, `dummyimage.com` — quedan amateur.
- ❌ NO incluyas imágenes binarias >200 KB en el repo (hot-link a CDN).
- ❌ NO copies imágenes de `reference/` (assets propietarios del template original).

### C.2 — Iconos

- **Lucide** (`lucide-react`, `lucide-vue-next`, `@lucide/svelte`, `lucide`) — primera opción para JS/TS.
- **Heroicons** (`@heroicons/react`) — alternativa oficial de Tailwind.
- **Phosphor** (`@phosphor-icons/react`) — si necesitas más variedad de estilos.
- ❌ NO uses Font Awesome (licencia mixta, complicada en Envato).
- ❌ NO uses emojis Unicode como iconos en producción (render inconsistente entre OS).

### C.3 — Demo data realista por tipo de template

Elige el bloque que se aplique a tu template. Si no encaja exactamente,
adapta el patrón al nicho.

#### Landing SaaS / startup

- **Hero**: headline real ("Ship production-ready SaaS in days, not months"), subhead 1 frase, CTA primario "Start free trial" + secundario "Watch demo (2 min)".
- **Logos "Trusted by"**: 5-6 logos placeholder con nombres ficticios coherentes — "Acme", "Pixel.io", "Lumen", "Nexus", "Vortex", "Aurora", "Stripe-like styling".
- **Features Bento (5-6 cards)**: cada una con icono Lucide, título corto, descripción 1 línea, ejemplos:
  - "AI-powered search · Find anything in 0.2s with vector embeddings"
  - "Realtime collaboration · Multi-cursor editing with sub-100ms sync"
- **Pricing**: 3 tarjetas (Hobby $0, Pro $19/mo, Business $79/mo), middle destacada con badge "Most popular".
- **Testimonials (4-6)**: nombre + avatar DiceBear + rol + empresa coherente:
  - "ThemeForge cut our launch time by 80%." — Sarah Chen, Head of Product · Lumen Labs
  - "Best DX I've had in 5 years of building SaaS." — Marcus Reyes, CTO · Nexus AI
- **FAQ**: 6-8 preguntas realistas del nicho.
- **CTA final** + footer con 4 columnas (Product, Company, Resources, Legal).

#### Portfolio / agencia creativa

- **Hero**: nombre del estudio ficticio coherente ("Aurora Studio", "Nordic Forge", "Pixel & Pine"), tagline 1 frase, foto bg Unsplash editorial.
- **Trabajos seleccionados (6 cases)** con título + cliente + categoría + año + imagen Unsplash temática:
  - "Nordic Bank — Brand Identity Refresh · Branding · 2025"
  - "Vortex Aerospace — Marketing Website · Web Design · 2024"
  - "Helix Coffee — Packaging System · Packaging · 2025"
- **Servicios (4)**: Branding, Editorial, Web, Packaging — con iconografía linear (Lucide).
- **Sobre el equipo (3-4 perfiles)**: nombre + headshot Unsplash (`?w=400&face=true` no funciona, pero filtra `people` en la búsqueda) + bio 2 líneas.
- **Contacto**: form (Name, Email, Project Type, Message) + redes sociales.

#### Blog / magazine / publicación

- **6-12 artículos demo** con: título realista del nicho, autor (nombre + avatar DiceBear), fecha, categoría, excerpt 2 líneas, imagen featured Unsplash, tiempo de lectura ("8 min read").
- **Categorías reales**: si es blog tech → "Engineering", "Product", "Design", "AI". NO "Category 1, Category 2".
- **Autor pages**: bio + foto + 3-4 últimos posts.
- **Trending posts** sidebar + newsletter signup en footer.

#### E-commerce / tienda

- **Catálogo: 12-24 productos** con: nombre real, precio, 2-4 imágenes Unsplash/Pexels, descripción 3-4 líneas, stock, categoría, rating (3.5-5★ con count), badges ("New", "Sale", "Best seller").
- **Categorías reales**: si es ropa → "Women", "Men", "Accessories", "Sale". NO "Category A".
- **Cart drawer** con 2-3 items demo precargados.
- **Checkout** con campos realistas + opciones de envío plausibles.
- **Reviews** en producto: 3-5 reviews con avatar + rating + texto.

#### Dashboard / admin / SaaS app

- **KPI cards** (4-6) con métricas plausibles + trend ("Revenue $24,580 ↑12.4%").
- **Charts** (Chart.js, Recharts, ApexCharts) con datos demo realistas en 7/30/90 días.
- **Tablas** (50-200 filas) generadas con `@faker-js/faker` o similar: usuarios (nombre, email, rol, status, last login), transacciones (id, customer, amount, status, date), productos (sku, name, stock, price).
- **Sidebar** con navegación completa de la app real (Dashboard, Users, Orders, Products, Analytics, Settings, etc.).
- Script `npm run seed:demo` que pobla la BD/JSON con todo en 1 comando.

#### App móvil (Expo/Flutter/Capacitor)

- **Onboarding** 3-4 slides con headlines + ilustraciones (puedes usar `https://undraw.co/` SVGs).
- **Tabs principales** ya con contenido demo cada una.
- **Listas** con 10-20 items por pantalla (perfiles, productos, posts, etc.).
- **Profile mock** con avatar + datos plausibles + settings interactivos.
- **Notificaciones** demo (3-5 en el centro de notificaciones).

### C.4 — Reglas universales de demo data

- ✅ **Variedad demográfica**: nombres internacionales, géneros, etnias diversas en avatares (DiceBear `?seed=` o filtros Unsplash). Refleja la audiencia global del comprador.
- ✅ **Coherencia de nicho**: si el template es para clínicas dentales, NO uses fotos de yoga ni copy de tech. Todo debe encajar.
- ✅ **Multi-idioma**: si el template soporta i18n (i18next, vue-i18n, etc.), demo data **en cada idioma soportado** (mínimo EN + ES + FR).
- ✅ **Modo oscuro**: si hay dark mode, todas las imágenes y demo data deben verse bien en ambos modos (cuidado con backgrounds blancos en hero).
- ✅ **Seed script**: para apps con BD, `npm run seed:demo` ejecuta todo en 1 comando.
- ✅ **Fechas plausibles**: usa fechas recientes (últimos 30-90 días), no `2020-01-01` ni futuras lejanas.
- ❌ NO uses "John Doe", "Test User", "Example Item", "Sample Product". Son red flags de template no terminado.
- ❌ NO dejes "lorem ipsum dolor sit amet" visible. Si te falta inspiración para copy, **inventa algo coherente con el nicho** — la IA puede generar copy en 2 segundos.
- ❌ NO uses números redondos en todo ("$100", "10 users") — alterna ($24, $79, $149, 1.2k users, 14,580 events).

### C.5 — Atribución y licencias

Aunque Unsplash y Pexels NO exigen atribución, en el `licensing.txt` o
`CREDITS.md` del paquete final documenta:

```
## Image credits (demo content)

All demo images are sourced from royalty-free providers and can be replaced
by the buyer with their own assets:

- Unsplash (https://unsplash.com/license) — hero, gallery, blog featured
- Pexels (https://www.pexels.com/license/) — backgrounds, secondary
- DiceBear (https://www.dicebear.com/licenses/) — user avatars (CC0)
- Lucide Icons (https://lucide.dev/license) — UI icons (ISC)

Replace with your own assets before going to production. Unsplash and
Pexels both allow commercial use without attribution.
```

ThemeForest sí pide listar fuentes de assets externos en la doc del
template. Este bloque cubre el requisito.

## §D — Nicho / industria objetivo

{('**Nicho elegido**: ' + niche_clean + '''

**Implicaciones del nicho** (aplícalas a TODO el template — paleta, tono,
imágenes, copy, demo data, iconografía, micro-interacciones):

1. **Paleta**: investiga 2-3 referencias visuales reales del sector y
   propón una paleta coherente. Ejemplos rápidos:
   - Médico/Clínica → blanco + azul confianza + acento verde salud
   - Restaurante → tonos cálidos crema/terracota + foto comida saturada
   - Fitness → negro + acentos neón energéticos
   - Legal → navy + gold + serif clásico
   - Startup SaaS → blanco + acento vibrante + gradient sutil
   - Boda → off-white + dusty rose + tipografía serif elegante
   - Crypto/Web3 → negro/dark + neon/holographic + grids futuristas

2. **Tono de voz del copy**:
   - Profesionales (legal/médico/financiero) → formal, "Usted", autoridad.
   - Lifestyle (boda/yoga/spa) → emocional, narrativo, evocador.
   - SaaS/tech → directo, beneficios, social proof, ROI.
   - Creativo (agencia/artista) → desenfadado, irreverente, "tú".
   - Restaurante/food → sensorial, descripción de ingredientes, fotos hablan.

3. **Imágenes Unsplash/Pexels**: busca con queries del nicho:
   - "dental clinic", "modern office", "yoga studio", "tattoo parlor",
     "coffee shop interior", "real estate luxury", "fitness gym dark", etc.
   - **No uses fotos genéricas** ("business meeting" para todo).

4. **Demo data específica del nicho**:
   - Si es clínica → nombres de doctores realistas + especialidades + horarios.
   - Si es restaurante → menú con platos plausibles + precios + maridajes.
   - Si es agencia → cases studies con clientes ficticios del sector típico.
   - Si es e-commerce → catálogo con productos reales del nicho.

5. **Secciones obligatorias del nicho**:
   - Médico → "Especialidades", "Equipo médico", "Reservar cita", "Seguros aceptados"
   - Restaurante → "Menú", "Reservar mesa", "Carta de vinos", "Galería"
   - Inmobiliaria → "Propiedades destacadas", "Filtros avanzados", "Agentes", "Hipoteca calculadora"
   - Boda → "Nuestra historia", "Lugar y fecha", "RSVP", "Lista de regalos"
   - Fitness → "Clases", "Entrenadores", "Membresías", "Tour virtual"
   - Educación → "Cursos", "Profesores", "Calendario académico", "Matriculación"
   - Adapta según el nicho real elegido.

6. **CTAs del nicho** (NO uses "Sign up" genérico):
   - Restaurante → "Reservar mesa"
   - Médico → "Pedir cita"
   - Inmobiliaria → "Agendar visita"
   - Agencia → "Solicitar propuesta"
   - SaaS → "Empezar gratis 14 días"
   - E-commerce → "Añadir al carrito"

7. **Iconografía**: usa iconos coherentes con el nicho — médico (stetoscopio,
   heart pulse, calendar), restaurante (cutlery, wine glass, chef hat),
   crypto (wallet, chain, coin), etc. Lucide tiene casi todo.

**Si encuentras conflicto entre el "tipo" y el "nicho"** (ej: tipo=SaaS pero
nicho=Restaurante), pregunta al usuario qué prima — generalmente el nicho
debería ganar y el tipo se interpreta dentro del nicho (sería entonces "SaaS
para restaurantes" → reservas online).
''') if not niche_unspecified else '''**Nicho**: no especificado por el usuario.

Si el usuario te describe en mensajes posteriores el nicho concreto al que
va el template, recuerda aplicar todas las implicaciones que estarían listadas
si lo hubiera elegido al crear el proyecto (paleta del sector, tono del copy,
imágenes temáticas, demo data específica, secciones obligatorias y CTAs).

Mientras no haya nicho concreto, trabaja en modo "showcase genérico" del
tipo de template elegido: contenido neutro pero realista, paleta versátil
fácil de re-tintar, secciones modulares que el comprador pueda activar/
desactivar según su nicho real.'''}

## §E — Política de interacción con el usuario (OBLIGATORIA)

**Pregunta SIEMPRE antes de tomar decisiones de diseño o producto.**

Este es un template comercial que se va a vender — el usuario quiere
control sobre las decisiones que afectan al valor final del producto.
Nunca asumas "lo más simple" ni "lo que tú harías". Pregunta.

### Cuándo PREGUNTAR (no asumir):

- Elección entre 2+ alternativas plausibles de UX, layout o componente.
- Cuál sub-sección incluir/omitir cuando hay margen.
- Qué copy concreto poner (headlines, CTAs, tagline) — propón 3 opciones.
- Paleta exacta (propón 2-3 paletas coherentes con el nicho).
- Tipografías (propón 2-3 combos típicos del sector).
- Animaciones / micro-interacciones — pregunta "discreta vs. expresiva".
- Demo data: nombres ficticios, marcas placeholder, sectores secundarios.
- Cualquier feature opcional (modo oscuro, multi-idioma, blog, etc.).
- Integraciones externas (Stripe, Mailchimp, analytics).

### Cómo formular las preguntas:

Numéralas (1, 2, 3) y describe cada opción en 1 línea con su trade-off.
Ejemplo:

> Para el hero de esta landing, ¿cuál prefieres?
>
> 1) **Imagen full-bleed con texto overlay** — más impacto visual,
>    requiere foto Unsplash buena, riesgo de contraste pobre en mobile.
> 2) **Split layout (texto izquierda, imagen derecha)** — más legible,
>    diseño "honesto" tipo Linear/Vercel, encaja bien con SaaS.
> 3) **Solo texto centrado con gradient mesh background** — minimalista,
>    estilo Stripe/Anthropic, foco total en el value prop.
>
> Por defecto iría con (2). ¿Qué prefieres?

Da siempre **una recomendación por defecto** (la opción que tú elegirías)
para que el usuario pueda decir "vale, tira" sin tener que decidir él.

### Cuándo NO preguntar (avanza solo):

- Tareas mecánicas: `npm install`, `git add/commit`, formatear código.
- Generar variantes de un componente ya aprobado (otra card igual).
- Correcciones obvias de bugs / errores de tipos / lint.
- Implementar lo que el usuario ya pidió explícitamente.
- Ajustes pequeños de spacing, colores muy cercanos, copy sinónimo.

### Antes de empezar a crear archivos:

Lanza una primera ronda de preguntas para alinear visión. Mínimo 3-5
preguntas críticas para evitar rehacer:

1. Paleta exacta (oferta 2-3 opciones).
2. Tipografía (oferta 2-3 combos).
3. Tono del copy (formal/casual/técnico).
4. Secciones a incluir / omitir del template-base del nicho.
5. ¿Algún competidor o referencia visual específica que admire?

Espera la respuesta. **Luego sí trabajas autónomo dentro de los límites
acordados.** Si te encuentras una decisión grande NO acordada, vuelves a
preguntar.

### Excepción: si el usuario dice "decide tú" o "tú mismo"

Entonces SÍ decides por defecto, pero **documenta brevemente la decisión**
en `ANALYSIS.md` o en el commit message para que el usuario pueda
revertirla luego sin tener que averiguar por qué elegiste eso.

Este flujo es lo que diferencia un template **vendible** ($30-50 en
ThemeForest) de uno **hecho a voleo** que se queda en draft sin
aprobación de Envato. La opinión del usuario es contexto crítico — no
es una molestia, es lo que evita el trabajo perdido.

---

{wp_installer_block}

# §A. LICENSING SYSTEM (lectura obligatoria si el theme se publica con licencia)

{sistema_licencias}

---

# §B. REQUISITOS ENVATO (lectura obligatoria)

{requisitos_envato}
"""
    # Web de CLIENTE (brief): reemplaza §C (que recomienda Unsplash) por una
    # directiva tajante de usar SOLO las imágenes/contenido reales del comercio.
    if is_brief:
        _brief_assets = (
            "## §C — IMÁGENES Y CONTENIDO (web de CLIENTE — OBLIGATORIO)\n\n"
            "Esta web es para un comercio REAL: usa EXCLUSIVAMENTE sus imágenes y "
            "contenido reales (ver «Fotos del negocio», «Vídeos» y «Contenido REAL» "
            "del brief de arriba).\n\n"
            "- ❌ **PROHIBIDO Unsplash, Pexels, Pixabay, Picsum, DiceBear, "
            "Logoipsum, stock o placeholders. NI UNA SOLA imagen que no sea del "
            "propio negocio.**\n"
            "- ✅ Usa SOLO las URLs de fotos reales del brief (son del comercio). "
            "Para fondos/hero usa también esas fotos reales.\n"
            "- Si falta una foto para una sección concreta, **reutiliza otra foto "
            "real del negocio** o deja un hueco con `{/* FOTO REAL DEL CLIENTE */}` "
            "y un aviso al final — NUNCA rellenes con stock.\n"
            "- Iconos: Lucide OK (no son fotos). Respeta nombres, textos, precios y "
            "datos REALES del brief, sin inventar.\n"
        )
        _md = re.sub(r"## §C — Assets.*?(?=\n## §D —)", _brief_assets, _md,
                     flags=re.S)
    return _md


def write_setup_script(
    project_dir: Path,
    stack_key: str,
    template_type: str,
    project_name: str,
    agent_key: str,
    run_autoskills: bool,
    mode: str,
    reference_kind: str | None,
    reference_value: str | None,
    existing_repo: str | None,
    create_github_repo: bool,
    github_user: str | None,
    embedded: bool = True,
    db_provision: dict | None = None,
    force_postgres: bool = False,
    adopt_src: str | None = None,
    ai_analysis: str | None = None,
    is_licensed_product: bool = False,
    licensing_create_gh_repo: bool = False,
    licensing_force_all_modes: bool = False,
    run_uipro: bool = False,
    niche: str | None = None,
    launch_agent: bool = True,
    ai_analysis_kind: str = "reference",
) -> Path:
    """Si embedded=True, el script se ejecuta dentro de la terminal
    embebida del ProjectWindow (no necesita `read` final ni dejar la
    ventana abierta — eso lo gestiona el wrapper del ProjectWindow)."""
    stack = STACKS[stack_key]
    agent = AGENTS[agent_key]
    ctx_md = render_context(
        stack_key, template_type, project_name, mode,
        reference_kind, reference_value, existing_repo,
        ai_analysis=ai_analysis,
        niche=niche,
        ai_analysis_kind=ai_analysis_kind,
    )

    # Si se van a instalar skills de agente (autoskills / UI-UX Pro), el
    # agente DEBE saber que existen y usarlas. Sin esto arranca sin ellas en
    # contexto: las skills quedan instaladas en `.claude/skills/` pero el
    # agente no las invoca al empezar.
    if run_autoskills or run_uipro:
        _sk = []
        if run_autoskills:
            _sk.append("- **autoskills** → skills específicas del stack en "
                       "`.agents/skills/` (con symlinks en `.claude/skills/`).")
        if run_uipro:
            _sk.append("- **UI/UX Pro Max** → design system + estilos en "
                       "`.claude/skills/` (si tu provider lo soporta).")
        ctx_md += (
            "\n\n## Skills instaladas — ÚSALAS desde el principio\n\n"
            "Durante el setup, ThemeForge ha instalado skills de agente en este "
            "proyecto:\n\n"
            + "\n".join(_sk)
            + "\n\n**OBLIGATORIO antes de escribir código:** lista `.claude/skills/` "
            "(y en mono-repos también `apps/*/.claude/skills/`). Para cada `SKILL.md` "
            "que encuentres, léelo y aplícalo durante el build — son la guía de cómo "
            "construir en este stack y cómo aplicar el design system. Si la carpeta "
            "está vacía (p. ej. stack=none aún sin scaffold), ejecuta "
            "`npx --yes autoskills -a <tu-agente>` tras el primer scaffold y entonces "
            "úsalas. No las ignores.\n"
        )

    parts = []
    parts.append("#!/usr/bin/env bash")
    parts.append("set -e")
    # Windows (git-bash): el binario de Python se llama `python`, no `python3`.
    # Sin esto, los bloques `python3 - <<EOF` y `python3 -m …` del setup
    # fallan y, con `set -e`, abortan el script ANTES de lanzar el agente
    # (por eso Claude no se autoejecutaba con el contexto en Windows).
    parts.append('if ! command -v python3 >/dev/null 2>&1 && command -v python >/dev/null 2>&1; then python3() { python "$@"; }; fi')
    if embedded:
        parts.append('trap \'EC=$?; echo ""; echo "❌ ERROR en línea $LINENO (exit $EC). La shell sigue activa para que puedas inspeccionar."\' ERR')
    else:
        parts.append('trap \'EC=$?; echo ""; echo "❌ ERROR en línea $LINENO (exit $EC)."; echo "(la ventana queda abierta — pulsa Enter para cerrar)"; read\' ERR')
    parts.append(f'echo "════ ThemeForge: {project_name} ════"')

    if mode == "existing":
        # Clonamos en una carpeta nueva. project_dir aún no debe existir
        # porque gh repo clone lo crea.
        parts.append(f"mkdir -p {shell_quote(project_dir.parent.as_posix())}")
        parts.append(f"cd {shell_quote(project_dir.parent.as_posix())}")
        parts.append(f'echo "→ Clonando {existing_repo} en {project_dir.name}/…"')
        # Si la carpeta existe vacía la borramos para que gh clone trabaje limpio
        parts.append(f"[ -d {shell_quote(project_dir.name)} ] && rmdir {shell_quote(project_dir.name)} 2>/dev/null || true")
        parts.append(f"gh repo clone {shell_quote(existing_repo)} {shell_quote(project_dir.name)}")
        parts.append(f"cd {shell_quote(project_dir.as_posix())}")
    elif mode == "adopt":
        # Adoptamos un template local: copia tal cual a project_dir.
        # No hay scaffold porque el código ya existe.
        parts.append(f"mkdir -p {shell_quote(project_dir.as_posix())}")
        parts.append(f"cd {shell_quote(project_dir.as_posix())}")
        parts.append('echo ""')
        parts.append(f'echo "→ Adoptando template desde: {adopt_src}"')
        # cp -a preserva permisos/timestamps. El /. al final fuerza copiar
        # el contenido, no la carpeta misma.
        parts.append(f"cp -a {shell_quote(adopt_src + '/.')} .")
        parts.append('echo "  Template copiado."')
    else:
        parts.append(f"mkdir -p {shell_quote(project_dir.as_posix())}")
        parts.append(f"cd {shell_quote(project_dir.as_posix())}")
        if stack["scaffold"]:
            parts.append('echo ""')
            parts.append(f'echo "→ Scaffolding {stack["name"]}…"')
            # PascalCase del slug: "my-cool-plugin" → "MyCoolPlugin"
            pascal = "".join(p.capitalize() for p in re.split(r"[-_\s]+", project_dir.name) if p)
            # ORG_ID se lee de licensing.json (campo `org_id`) — sirve
            # para Java/Kotlin/Flutter/Tauri/Spring/Ktor (estilo
            # com.empresa.app). Default "com.example" si no hay config.
            try:
                from licensing_config import load as _load_lic
                org_id = _load_lic().get("org_id", "com.example")
            except Exception:
                org_id = "com.example"
            # Directorio de instalación de ThemeForge (para que un stack pueda
            # copiar plantillas de `templates/<stack>/` con `cp -a __TFDIR__/…`).
            tfdir = str(Path(__file__).resolve().parent)
            # ThemeForge pre-escribe .mcp.json en la carpeta ANTES del setup, pero
            # algunos scaffolders (create-next-app, create-vite…) abortan si el
            # directorio no está vacío ("contains files that could conflict").
            # Apartamos esos ficheros, scaffoldeamos en una carpeta limpia y los
            # restauramos después (sin pisar lo que cree el scaffold).
            parts.append('__TF_STASH="$(mktemp -d)"')
            parts.append(
                'for __f in .mcp.json README-MCP.md; do '
                '[ -e "$__f" ] && mv "$__f" "$__TF_STASH/" 2>/dev/null || true; done')
            for cmd in stack["scaffold"]:
                substituted = (
                    cmd.replace("__PROJECT__", project_name)
                       .replace("__SLUG__", project_dir.name)
                       .replace("__PASCAL__", pascal)
                       .replace("__ORG_ID__", org_id)
                       .replace("__TFDIR__", tfdir)
                )
                parts.append(substituted)
            # Restaura los ficheros apartados (sin sobrescribir los del scaffold).
            parts.append(
                'for __f in .mcp.json README-MCP.md; do '
                '[ -e "$__TF_STASH/$__f" ] && [ ! -e "./$__f" ] && '
                'mv "$__TF_STASH/$__f" "./" 2>/dev/null || true; done')
            parts.append('rmdir "$__TF_STASH" 2>/dev/null || true')
        else:
            parts.append('echo "→ Sin scaffolding (stack: Sin stack)."')

    # ── UI pro: framer-motion + guía 21st.dev ───────────────────────────
    # Para CUALQUIER proyecto React (modo scratch/adopt/existing). Escribe la
    # guía UI-MOTION.md (instrucciones al agente), asegura el MCP `magic` en
    # .mcp.json e instala framer-motion. Todo NO-FATAL.
    _tf_home_ui = Path(__file__).resolve().parent
    parts.append('echo ""')
    parts.append('echo "──── UI pro: framer-motion + 21st.dev ────"')
    parts.append(f"cd {shell_quote(project_dir.as_posix())} 2>/dev/null || true")
    parts.append(
        f"python3 {shell_quote((_tf_home_ui / 'web_enhancements.py').as_posix())} "
        f"{shell_quote(project_dir.as_posix())} >/dev/null 2>&1 "
        '&& echo "  guía UI-MOTION.md + MCP 21st.dev ✓" || true')
    # OJO: `npm install framer-motion` va al FINAL del setup (con timeout), no
    # aquí: con wifi flojo puede tardar/colgarse y dejaría el proyecto SIN
    # CLAUDE.md/context si abortara antes de escribirlos.

    # ── WordPress dev env (Docker) — SOLO stacks WordPress, ANTES de todo lo
    #    demás. Levanta WP + MariaDB, instala WP (admin/admin) y monta el
    #    proyecto en wp-content. No-fatal: si docker falla, el setup sigue.
    if stack_key in _FORMAT_WORDPRESS:
        wp_kind = "plugin" if stack_key == "wordpress-plugin" else "theme"
        # ux_pack viene del stack (fse | bricks). Si no, "-" para que la CLI
        # del provisioner lo interprete como None.
        _ux_pack = stack.get("ux_pack") or "-"
        _wp_builder = Path(__file__).resolve().parent
        _wp_slug = project_dir.name
        parts.append('echo ""')
        parts.append('echo "──── WordPress dev env (Docker) ────"')
        parts.append('if command -v docker >/dev/null 2>&1; then')
        parts.append('  echo "→ Provisionando WordPress + MariaDB en Docker (el primer pull puede tardar)…"')
        parts.append(
            f'  if WP_OUT=$(PYTHONPATH={shell_quote(str(_wp_builder))} python3 -m wp_provisioner '
            f'provision {shell_quote(_wp_slug)} "$(pwd)" {wp_kind} {shell_quote(_ux_pack)} 2>&1); then'
        )
        parts.append('    WP_URL=$(echo "$WP_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)[\\"url\\"])" 2>/dev/null)')
        parts.append('    echo "✓ WordPress listo en ${WP_URL:-localhost} (admin/admin) — ver WORDPRESS-DEV.md"')
        parts.append('  else')
        parts.append('    echo "(No se pudo provisionar WordPress — el setup continúa.)"')
        parts.append('    echo "$WP_OUT" | tail -5')
        parts.append('  fi')
        parts.append('else')
        parts.append('  echo "(docker no disponible — WordPress no se autoinstala; instálalo a mano)"')
        parts.append('fi')

    if mode == "recreate" and reference_kind == "figma":
        # Figma no se descarga — el agente lee el diseño vía el MCP figma-context.
        parts.append('echo ""')
        parts.append('echo "→ Diseño de Figma: el agente lo leerá con el MCP '
                     'figma-context (necesita FIGMA_API_KEY). No se descarga nada."')
    elif mode == "recreate":
        parts.append('echo ""')
        parts.append('echo "→ Preparando reference/…"')
        parts.append("mkdir -p reference")
        if reference_kind == "zip":
            parts.append(f"unzip -q -o {shell_quote(reference_value)} -d reference/")
        elif reference_kind == "folder":
            parts.append(f"cp -r {shell_quote(reference_value)}/. reference/")
        elif reference_kind == "url":
            parts.append(
                "wget --mirror --convert-links --adjust-extension --page-requisites "
                "--no-parent --no-host-directories --cut-dirs=0 "
                f"-P reference {shell_quote(reference_value)} || "
                'echo "(wget falló parcialmente — revisa reference/)"'
            )

    parts.append('echo ""')
    parts.append('echo "→ Copiando contexto al proyecto…"')
    parts.append("mkdir -p context")
    # Discovery dinámico: prioriza ~/.config/themeforge/context-private/
    # (versiones reales del usuario) sobre context/ del repo (stubs).
    # NO hay nombres de archivos hardcoded en el código público.
    for src in collect_context_mds():
        # Normaliza el destino quitando ".template" si lo trae el
        # stub público — así el agente IA del proyecto siempre encuentra
        # `MARKET-RESEARCH.md` independientemente de si es la versión
        # privada o el stub.
        dst_name = src.name
        if dst_name.endswith(".template.md"):
            dst_name = dst_name[:-len(".template.md")] + ".md"
        parts.append(
            f"cp {shell_quote(str(src))} context/{shell_quote(dst_name)}"
        )

    # ── licensing scaffold (Phase 1) ─────────────────────────────────
    # Por defecto solo en scratch/recreate (en existing/adopt el proyecto
    # ya tiene estructura propia y el drop podría chocar). Si el usuario
    # marca "Forzar también en adopt/existing" se aplica en todos los
    # modos — el risk es del usuario.
    allowed_modes = ("scratch", "recreate", "existing", "adopt") if licensing_force_all_modes \
        else ("scratch", "recreate")
    if is_licensed_product and mode in allowed_modes:
        try:
            from licensing_scaffold import scaffold as _pcre_scaffold
            parts.extend(_pcre_scaffold(
                stack_key=stack_key,
                slug=project_dir.name,
                project_name=project_name,
                create_gh_repo_under_org=licensing_create_gh_repo,
            ))
        except Exception as e:
            parts.append(f'echo "[licensing_scaffold error: {e}]"')

    parts.append('echo ""')
    parts.append(f'echo "→ Generando {agent["context_file"]}…"')
    parts.append(f"cat > {agent['context_file']} <<'THEMEFORGE_EOF'\n{ctx_md}\nTHEMEFORGE_EOF")

    if mode == "recreate":
        parts.append('grep -q "^reference/" .gitignore 2>/dev/null || echo "reference/" >> .gitignore')

    # Skills predeclaradas — autoskills v0.3.6+ soporta claude/codex/gemini/
    # opencode (+ cursor/windsurf/copilot). El `elif` queda como red de
    # seguridad por si en el futuro un provider nuevo arranca con
    # autoskills_flag=None mientras se valida soporte upstream.
    skills_flag = agent.get("autoskills_flag")
    if stack["skills"] and skills_flag:
        parts.append('echo ""')
        parts.append('echo "→ Instalando skills predeclaradas del stack…"')
        for skill in stack["skills"]:
            parts.append(
                f"npx --yes skills add {shell_quote(skill)} -a {skills_flag} "
                f'|| echo "(skill {skill} no se pudo añadir, continuamos)"'
            )
    elif stack["skills"]:
        parts.append('echo ""')
        parts.append(f'echo "→ Saltando skills predeclaradas (provider {agent["name"]} no soportado por autoskills)."')

    # autoskills:
    #   - Si el provider no soporta autoskills → skip silencioso.
    #   - Si el stack es "none" Y el modo es scratch/recreate → el
    #     scaffold real lo hará el agente; no hay nada que detectar.
    #     Skip con mensaje y dejar la instrucción en CLAUDE.md.
    #   - En el resto de casos: guard de detección recursivo (hasta
    #     depth 3) que cubra Node/PHP/Flutter/Rust/Go/Python/Ruby/Java/
    #     Hugo/WordPress block (theme.json) / Astro / Vite. Mono-repos
    #     con stack en apps/*/, packages/*/, Files/*/ se detectan
    #     correctamente.
    autoskills_will_skip_no_stack = (
        run_autoskills and skills_flag
        and stack_key == "none"
        and mode in ("scratch", "recreate")
    )
    if autoskills_will_skip_no_stack:
        parts.append('echo ""')
        parts.append(
            'echo "→ Saltando autoskills: stack=none. Tras el primer '
            "scaffold real, el agente puede ejecutar 'npx --yes autoskills "
            f"-a {skills_flag}' manualmente (ver CLAUDE.md).\""
        )
    elif run_autoskills and skills_flag:
        parts.append('echo ""')
        parts.append(
            'if find . -maxdepth 3 -type f \\( '
            '-name "package.json" -o -name "composer.json" '
            '-o -name "pubspec.yaml" -o -name "Cargo.toml" '
            '-o -name "go.mod" -o -name "pyproject.toml" '
            '-o -name "Gemfile" -o -name "theme.json" '
            '-o -name "style.css" -o -name "config.toml" '
            '-o -name "config.yaml" -o -name "config.yml" '
            '-o -name "build.gradle" -o -name "build.gradle.kts" '
            '\\) -not -path "*/node_modules/*" -not -path "*/vendor/*" '
            '-not -path "*/.git/*" -not -path "*/reference/*" '
            '2>/dev/null | head -1 | grep -q .; then'
        )
        parts.append('  echo "→ Ejecutando autoskills…"')
        parts.append(f'  npx --yes autoskills -a {skills_flag} || echo "(autoskills falló — sigue sin él)"')
        parts.append('else')
        parts.append(
            '  echo "→ Saltando autoskills (sin stack detectable hasta 3 '
            'niveles). Lánzalo a mano cuando el scaffold esté completo: '
            f'npx --yes autoskills -a {skills_flag}"'
        )
        parts.append('fi')

    # ── uipro UI/UX Pro Max (opcional, paralelo a autoskills) ─────────
    # Skill de diseño (161 reasoning rules, 67 estilos, 161 paletas).
    # Solo se ejecuta si el provider mapea a uno soportado por uipro-cli.
    if run_uipro:
        # ThemeForge agent key → uipro --ai value
        UIPRO_AGENT_MAP = {
            "claude": "claude", "claude-api": "claude",
            "codex": "codex", "codex-api": "codex",
            "gemini": "gemini",
            "opencode": "opencode", "openrouter": "opencode",
        }
        uipro_flag = UIPRO_AGENT_MAP.get(agent_key)
        if uipro_flag:
            parts.append("")
            parts.append('echo "──── UI/UX Pro Max ────"')
            parts.append('echo "→ Ejecutando uipro-cli init (design system + 67 styles)…"')
            parts.append(
                f'npx --yes uipro-cli init --ai {uipro_flag} '
                f'|| echo "(uipro-cli falló — sigue sin él)"'
            )
        else:
            parts.append(
                f'echo "→ Saltando uipro: provider \'{agent_key}\' no soportado por uipro-cli."'
            )

    # ── Skills cross-cutting → raíz (solo necesario en mono-repos) ──
    # autoskills YA crea symlinks en `.claude/skills/` del cwd donde se
    # ejecutó (apps/<app>/.claude/skills/ → apps/<app>/.agents/skills/).
    # En mono-repos eso significa que el Claude lanzado desde RAÍZ no
    # ve ninguna skill, porque solo escanea `<repo>/.claude/skills/`.
    # Aquí agregamos solo las skills "cross-cutting" (agnósticas de
    # stack) a la raíz para que estén disponibles desde cualquier cwd.
    # Las stack-specific (laravel/next/flutter/react/php/dart) quedan
    # solo per-app para evitar contaminación.
    # ── Cablear skills de autoskills (.agents/skills/) → .claude/skills/ ──
    # autoskills instala en `.agents/skills/` pero no siempre crea el symlink
    # en `.claude/skills/` (lo único que escanea Claude Code), así que el
    # agente no las veía. `skills_wireup` lo arregla (single-app y mono-repo).
    _sw_dir = Path(__file__).resolve().parent
    parts.append('echo ""')
    parts.append('echo "→ Cableando skills de autoskills a .claude/skills/ (para que el agente las use)…"')
    parts.append(
        f'PYTHONPATH={shell_quote(str(_sw_dir))} python3 -m skills_wireup "$(pwd)" || true'
    )
    # ── Exponer esas mismas skills a Hermes (auto-carga AGENTS.md, no .claude/skills) ──
    # Sin esto Hermes no veía las skills de autoskills/uipro: el puente las lista
    # en un bloque gestionado de AGENTS.md y le ordena leerlas+seguirlas.
    parts.append('echo "→ Exponiendo skills a Hermes (AGENTS.md)…"')
    parts.append(
        f'PYTHONPATH={shell_quote(str(_sw_dir))} python3 -m hermes_skills_bridge "$(pwd)" || true'
    )

    # ── BD: aprovisionamiento automático post-clone/scaffold ──
    # El propio script detecta si el proyecto necesita Postgres (drizzle/
    # prisma) y, en su caso, levanta el container, inyecta DATABASE_URL en
    # .env y ejecuta db:push + db:seed.
    builder_dir = Path(__file__).resolve().parent
    secret = secrets.token_urlsafe(32)
    slug = project_dir.name
    parts.append('echo ""')
    parts.append('echo "→ Detectando BD requerida por el proyecto…"')
    parts.append(f'export PYTHONPATH={shell_quote(str(builder_dir))}')
    parts.append('DB_KIND=$(python3 -m db_provisioner detect "$(pwd)" 2>/dev/null || true)')
    # WordPress trae su propia MariaDB (en el contenedor de wp_provisioner),
    # así que NO forzamos Postgres aunque el checkbox esté marcado.
    if force_postgres and stack_key not in _FORMAT_WORDPRESS:
        parts.append('# Override: el usuario marcó "Provisionar Postgres" en la UI')
        parts.append('if [ -z "$DB_KIND" ]; then')
        parts.append('  echo "  (No detectada en archivos, pero forzada por checkbox UI)"')
        parts.append('  DB_KIND=postgres')
        parts.append('fi')
    parts.append('if [ "$DB_KIND" = "postgres" ]; then')
    parts.append(f'  echo "→ Postgres requerido — provisionando container (slug: {slug})…"')
    parts.append(f'  PROV_JSON=$(python3 -m db_provisioner provision {shell_quote(slug)})')
    parts.append('  if [ -n "$PROV_JSON" ]; then')
    parts.append('    DATABASE_URL=$(echo "$PROV_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)[\\"url\\"])")')
    parts.append('    PG_PORT=$(echo "$PROV_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)[\\"port\\"])")')
    parts.append('    echo "  Container listo en puerto $PG_PORT"')
    parts.append('    # Generar/actualizar .env conservando entradas previas que no sean DATABASE_URL/AUTH_SECRET')
    parts.append('    touch .env')
    parts.append('    grep -v -E "^(DATABASE_URL|AUTH_SECRET)=" .env > .env.tmp 2>/dev/null || true')
    parts.append('    mv .env.tmp .env 2>/dev/null || true')
    parts.append('    echo "DATABASE_URL=$DATABASE_URL" >> .env')
    parts.append(f'    echo "AUTH_SECRET={secret}" >> .env')
    parts.append('    grep -q "NUXT_PUBLIC_DEMO_MODE" .env || echo "NUXT_PUBLIC_DEMO_MODE=true" >> .env')
    parts.append('    echo "  .env actualizado"')
    parts.append('    if [ -f package.json ]; then')
    parts.append('''      # Detectar el gestor de paquetes correcto. `workspace:*` es protocolo
      # de pnpm/yarn (NO de npm → `npm install` peta con EUNSUPPORTEDPROTOCOL).
      if [ -f pnpm-lock.yaml ] || grep -q "workspace:" package.json 2>/dev/null; then
        PM=pnpm
        command -v pnpm >/dev/null 2>&1 || { command -v corepack >/dev/null 2>&1 && corepack enable >/dev/null 2>&1; } || true
      elif [ -f yarn.lock ]; then PM=yarn
      elif [ -f bun.lockb ] || [ -f bun.lock ]; then PM=bun
      else PM=npm; fi
      echo "→ Instalando dependencias ($PM)…"
      # NO fatal: si falla, seguimos igual (el agente puede arreglar las deps).
      if [ "$PM" = npm ]; then
        npm install --legacy-peer-deps || echo "(npm install falló — el agente puede arreglarlo)"
      else
        "$PM" install || echo "($PM install falló — el agente puede arreglarlo)"
      fi
      for _s in db:push db:seed; do
        if grep -q "\\"$_s\\"" package.json 2>/dev/null; then
          echo "→ Ejecutando $_s ($PM)…"
          "$PM" run "$_s" || echo "($_s falló — revisa drizzle/prisma)"
        fi
      done''')
    parts.append('    fi')
    parts.append('  else')
    parts.append('    echo "(provision_postgres_for falló — revisa que docker funciona sin sudo: \\"docker info\\")"')
    parts.append('  fi')
    parts.append('else')
    parts.append('  echo "  Sin BD detectada — saltando aprovisionamiento."')
    parts.append('fi')

    # framer-motion al FINAL: el CLAUDE.md/context/skills ya están escritos, así
    # que aunque la instalación tarde o se omita (wifi flojo), el proyecto queda
    # completo. `timeout` evita que se cuelgue indefinidamente.
    parts.append('echo ""')
    parts.append('echo "──── framer-motion (animaciones) ────"')
    parts.append("if [ -f package.json ] && grep -qE '\"(react|next)\"' package.json; then")
    parts.append('  echo "→ Instalando framer-motion…"')
    parts.append('  timeout 240 npm install framer-motion >/dev/null 2>&1 '
                 '&& echo "  framer-motion ✓" '
                 "|| echo \"  [framer-motion omitido — instálalo luego con 'npm i framer-motion']\"")
    parts.append("fi")

    if mode != "existing":
        parts.append('echo ""')
        parts.append('echo "→ Inicializando git + commit inicial…"')
        parts.append("[ -d .git ] || git init -q")
        parts.append("git add -A && git commit -m 'init: scaffold por ThemeForge' -q || true")
    else:
        parts.append('echo ""')
        parts.append('echo "→ Añadiendo MDs y CLAUDE.md/AGENTS.md como commit nuevo…"')
        parts.append("git add -A && git commit -m 'chore: contexto ThemeForge' -q || true")

    # El repo de GitHub se crea bajo demanda desde el botón "📦 GitHub"
    # de la ProjectWindow para evitar publicar accidentalmente código
    # sensible durante el scaffold automático.

    parts.append('echo ""')
    parts.append(f'echo "════ Listo. Lanzando {agent["name"]}… ════"')
    parts.append('echo ""')

    # ── Prompt inicial automático ─────────────────────────────────
    # Cuando arranca el agente, le pasamos como primer mensaje una
    # instrucción para que LEA el CLAUDE.md/AGENTS.md generado, asuma
    # el análisis IA previo (si lo hay) y CONFIRME al usuario qué
    # entiende que tiene que hacer antes de empezar a tocar código.
    has_analysis = ai_analysis is not None
    # Si hay skills instaladas (autoskills / UI-UX Pro), recordárselo
    # explícitamente al arrancar para que las lea y las incluya en el plan.
    skills_hint = ""
    if run_autoskills or run_uipro:
        skills_hint = (
            f"\n\nIMPORTANTE: ThemeForge ha instalado skills de agente en "
            f"`.claude/skills/` (mira la sección '## Skills instaladas' de "
            f"{agent['context_file']}). LÍSTALAS y léelas ANTES de planificar, "
            f"e indícame cuáles vas a usar en tu plan."
        )
    if has_analysis:
        initial_prompt = (
            f"Acabas de arrancar en un proyecto recién scaffoldeado por ThemeForge. "
            f"Lee COMPLETAMENTE {agent['context_file']} (especialmente la sección "
            f"'## Análisis IA previo de la referencia' que ya contiene un análisis "
            f"hecho por otra IA sobre el template original). Luego lee context/ si necesitas."
            f"{skills_hint}"
            f"\n\nAntes de tocar NADA del código:\n"
            f"1. Resume en 4-6 líneas qué entiendes que tienes que hacer en este sprint.\n"
            f"2. Confirma si estás de acuerdo con el stack recomendado o si propones otro.\n"
            f"3. Lista los primeros 3-5 pasos concretos que vas a dar.\n"
            f"4. Espera mi OK antes de ejecutar nada."
        )
    else:
        initial_prompt = (
            f"Acabas de arrancar en un proyecto recién scaffoldeado por ThemeForge. "
            f"Lee COMPLETAMENTE {agent['context_file']} y todo lo que haya en context/."
            f"{skills_hint}"
            f"\n\nAntes de tocar NADA del código:\n"
            f"1. Resume en 4-6 líneas qué entiendes que tienes que hacer.\n"
            f"2. Lista los primeros 3-5 pasos concretos que vas a dar.\n"
            f"3. Espera mi OK antes de ejecutar nada."
        )

    # Escribir el prompt a un fichero temporal del proyecto (.themeforge-init-prompt)
    # y pasarlo al agente como argumento posicional. Así evitamos problemas
    # de escape de comillas y mantenemos el agente interactivo después.
    parts.append(
        f"cat > .themeforge-init-prompt <<'THEMEFORGE_PROMPT_EOF'\n"
        f"{initial_prompt}\n"
        f"THEMEFORGE_PROMPT_EOF"
    )
    # No queremos versionar ese archivo
    parts.append('grep -q "^\\.themeforge-init-prompt$" .gitignore 2>/dev/null || echo ".themeforge-init-prompt" >> .gitignore')

    # Comando interactivo del provider + prompt inicial. Las API keys
    # se cargan en os.environ al startup de ThemeForge (apply_all_known_keys),
    # así que la terminal embebida ya las hereda.
    cmd, extra_args = aip.interactive_cmd_args(agent_key)
    extra = (" " + " ".join(shell_quote(a) for a in extra_args)) if extra_args else ""
    if launch_agent:
        parts.append(f'{cmd}{extra} "$(cat .themeforge-init-prompt)"')
    else:
        # Modo headless (MCP create_project): NO lanzar el agente interactivo
        # (fallaría sin TTY). El build autónomo lo hace run_agent_build.
        parts.append('echo "✓ Proyecto preparado (build headless: usa run_agent_build)."')

    parts.append('echo ""')
    if embedded:
        # En modo embebido el wrapper hará `exec bash -i` para dejar
        # shell viva — no necesitamos `read` que pida Enter dos veces.
        parts.append('echo "════ Sesión del agente cerrada. Shell embebida lista. ════"')
    else:
        parts.append('echo "════ Sesión del agente cerrada. Pulsa Enter para cerrar. ════"')
        parts.append("read")

    cache_dir = pc.app_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    setup = cache_dir / f"setup-{project_dir.name}.sh"
    setup.write_text("\n".join(parts), encoding="utf-8")
    try:
        setup.chmod(0o755)
    except OSError:
        pass  # Windows: NTFS no aplica bits POSIX
    return setup


class _ReferenceAnalysisDialog(QDialog):
    """Diálogo modal que ejecuta el agente CLI con un prompt sobre la
    referencia y muestra el resultado en streaming token-a-token.

    Cada CLI emite output estructurado (Claude/Codex/Gemini/OpenCode →
    stream-json o JSONL). El parser correspondiente vive en
    `stream_parsers.py` y normaliza eventos al mismo shape canónico
    (text_delta + ttft_ms + tokens + model + cost + status + done) que
    consume `_handle_event`.

    Si el parser_kind no se reconoce (caso edge), el diálogo cae a
    modo texto plano sin métricas.
    """

    def __init__(self, parent, agent_label: str, facts: dict, parser_kind: str):
        super().__init__(parent)
        self.setWindowTitle(f"🔍 Análisis de referencia con {agent_label}")
        self.resize(960, 820)
        self.proc: QProcess | None = None
        # Parser dispatcher: 'claude' / 'codex' / 'gemini' / 'opencode' / 'text'
        import stream_parsers as _sp
        self._parser = _sp.parser_for(parser_kind)
        self._use_stream_json = self._parser is not None  # back-compat flag
        self._stdout_buffer = ""
        # Métricas en vivo
        self._t0 = None
        self._ttft_ms = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_creation_tokens = 0
        self._cache_read_tokens = 0
        self._cost_usd = 0.0
        self._model_name = ""
        # Conversación multi-turno
        self._original_argv: list[str] = []
        self._original_env: dict = {}
        self._original_prompt: str = ""
        # Historial: [{"role": "user"|"assistant", "content": "..."}]
        self._messages: list[dict] = []
        # Buffer del texto que va llegando del turno actual del assistant
        self._current_assistant_buf: list[str] = []
        self._final_banner_inserted = False

        header = QLabel(
            f"<b>Pidiendo a {agent_label}</b> que analice la referencia "
            f"y recomiende un stack moderno para tu reimplementación."
        )
        header.setWordWrap(True)

        # Mini-resumen de facts (lo que se manda)
        kind = facts.get("kind", "?")
        if kind == "mono-repo":
            summary = f"Detectado mono-repo con {len(facts.get('subprojects', []))} sub-proyectos:\n"
            for s in facts.get("subprojects", []):
                fw = s.get("framework") or s.get("preview_profile") or "?"
                summary += f"  • {s.get('name')} — {fw}\n"
        elif kind == "single":
            summary = f"Detectado proyecto único — {facts.get('framework') or facts.get('preview_profile') or '?'}"
        elif kind == "zip":
            summary = (
                f"Detectado .zip ({facts.get('size_mb','?')} MB, "
                f"{facts.get('entries','?')} entradas).\nMarcadores: "
                f"{list((facts.get('markers') or {}).keys())}"
            )
        else:
            summary = f"Detectado: {kind}"

        facts_lbl = QLabel(f"<pre style='color:#888'>{summary}</pre>")
        facts_lbl.setTextFormat(Qt.TextFormat.RichText)
        facts_lbl.setWordWrap(True)

        # Etiqueta del comando que se ejecuta (para depurar)
        self.cmd_lbl = QLabel("")
        self.cmd_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.cmd_lbl.setStyleSheet("color:#62b4ff;font-family:monospace;font-size:9pt;")
        self.cmd_lbl.setWordWrap(True)

        # Panel de stderr / diagnóstico (siempre visible)
        self.err_box = QTextEdit()
        self.err_box.setReadOnly(True)
        self.err_box.setMaximumHeight(120)
        self.err_box.setStyleSheet(
            "background:#2a1a1a;color:#ff8a8a;font-family:'DejaVu Sans Mono',monospace;font-size:10pt;"
        )
        self.err_box.setPlaceholderText("stderr del agente (vacío si no hay errores)")

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setStyleSheet(
            "background:#1e1e1e;color:#e6e6e6;font-family:'DejaVu Sans Mono',monospace;"
        )
        self.out.setPlaceholderText("Esperando respuesta del agente…")

        # Barra de status con cronómetro + tokens
        self.elapsed_lbl = QLabel("⏱️  00:00")
        self.elapsed_lbl.setStyleSheet("color:#62b4ff;font-family:monospace;")
        self.tokens_lbl = QLabel("")
        self.tokens_lbl.setStyleSheet("color:#888;font-family:monospace;")
        self.status_lbl = QLabel("⏳ Lanzando agente…")
        self.status_lbl.setStyleSheet("color:#cfcfcf;")

        status_row = QHBoxLayout()
        status_row.addWidget(self.elapsed_lbl)
        status_row.addWidget(self.tokens_lbl)
        status_row.addStretch()
        status_row.addWidget(self.status_lbl)

        # Input de respuesta multi-turno (oculto hasta que el primer
        # turno del agente termine)
        self.reply_input = QTextEdit()
        self.reply_input.setPlaceholderText(
            "Responde al agente para iterar la conversación, o cierra "
            "para guardar el análisis actual…"
        )
        self.reply_input.setMaximumHeight(110)
        self.reply_input.setStyleSheet(
            "background:#1a1a1a;color:#e6e6e6;"
            "font-family:'DejaVu Sans Mono',monospace;"
            "border:1px solid #444;"
        )
        self.reply_input.setEnabled(False)
        self.send_btn = QPushButton("➡ Enviar respuesta")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send_reply)
        self.send_btn.setStyleSheet("font-weight:bold;")

        reply_row = QHBoxLayout()
        reply_row.addWidget(self.reply_input, 1)
        reply_row.addWidget(self.send_btn)

        # Botonera
        self.cancel_btn = QPushButton("✖ Cancelar")
        self.cancel_btn.clicked.connect(self._cancel)
        self.copy_btn = QPushButton("📋 Copiar todo")
        self.copy_btn.clicked.connect(self._copy_output)
        self.close_btn = QPushButton("💾 Guardar y cerrar")
        self.close_btn.clicked.connect(self.accept)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.close_btn)

        lay = QVBoxLayout()
        lay.addWidget(header)
        lay.addWidget(facts_lbl)
        lay.addWidget(self.cmd_lbl)
        lay.addWidget(self.out, 1)
        lay.addLayout(reply_row)
        lay.addWidget(QLabel("<i>stderr del proceso:</i>"))
        lay.addWidget(self.err_box)
        lay.addLayout(status_row)
        lay.addLayout(btn_row)
        self.setLayout(lay)

        # Cronómetro
        from PyQt6.QtCore import QTimer, QTime
        self._QTime = QTime
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick_elapsed)

    def run(self, prompt: str, argv: list[str], extra_env: dict | None = None):
        # Persistimos para poder relanzar en turnos sucesivos.
        self._original_argv = list(argv)
        self._original_env = dict(extra_env or {})
        self._original_prompt = prompt
        self._messages = [{"role": "user", "content": prompt}]
        self._launch_turn(prompt)

    def _launch_turn(self, full_prompt: str):
        """Lanza un turno del agente con el prompt dado. Reutiliza argv y
        env del primer turno (`run`). Reinicia métricas del turno actual
        pero conserva el cronómetro acumulado."""
        from PyQt6.QtCore import QTime, QProcessEnvironment
        if self._t0 is None:
            self._t0 = QTime.currentTime()
        self._timer.start()
        self._current_assistant_buf = []
        self._stdout_buffer = ""
        self._ttft_ms = None
        argv = self._original_argv
        cmd_txt = " ".join(argv) + "  &lt;  &lt;prompt&gt;"
        self.cmd_lbl.setText(f"<b>cmd:</b> <code>{cmd_txt}</code>")
        self._pending_prompt = full_prompt
        self.proc = QProcess(self)
        self.proc.setProgram(argv[0])
        self.proc.setArguments(argv[1:])
        if self._original_env:
            penv = QProcessEnvironment.systemEnvironment()
            for k, v in self._original_env.items():
                penv.insert(k, v)
            self.proc.setProcessEnvironment(penv)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._on_output)
        self.proc.readyReadStandardError.connect(self._on_stderr)
        self.proc.finished.connect(self._on_finished)
        self.proc.started.connect(self._on_started)
        self.proc.errorOccurred.connect(self._on_error)
        self.status_lbl.setText("⏳ Arrancando agente…")
        self.cancel_btn.setEnabled(True)
        self.proc.start()

    def _tick_elapsed(self):
        if self._t0 is None:
            return
        ms = self._t0.msecsTo(self._QTime.currentTime())
        s = ms // 1000
        m, s = divmod(s, 60)
        ttft_txt = f"  · TTFT {self._ttft_ms/1000:.1f}s" if self._ttft_ms else ""
        self.elapsed_lbl.setText(f"⏱️  {m:02d}:{s:02d}{ttft_txt}")

    def _update_tokens_lbl(self):
        parts = []
        if self._model_name:
            parts.append(self._model_name)
        if self._input_tokens:
            parts.append(f"in: {self._input_tokens}")
        if self._output_tokens:
            parts.append(f"out: {self._output_tokens}")
        if self._cost_usd:
            parts.append(f"${self._cost_usd:.4f}")
        self.tokens_lbl.setText("  ·  ".join(parts))

    def _on_started(self):
        """Cuando el proceso ya está vivo, le pasamos el prompt por stdin."""
        if not self.proc:
            return
        prompt = getattr(self, "_pending_prompt", "")
        data = (prompt + "\n").encode("utf-8")
        self.proc.write(data)
        self.proc.waitForBytesWritten(3000)
        self.proc.closeWriteChannel()
        kb = len(data) // 1024
        self.status_lbl.setText(
            f"⏳ Esperando respuesta… (prompt: {kb} KB enviados)"
        )

    def _on_error(self, err):
        from PyQt6.QtCore import QProcess as _QP
        names = {
            _QP.ProcessError.FailedToStart: "FailedToStart (binario no encontrado o sin permisos)",
            _QP.ProcessError.Crashed: "Crashed",
            _QP.ProcessError.Timedout: "Timedout",
            _QP.ProcessError.WriteError: "WriteError (no se pudo escribir a stdin)",
            _QP.ProcessError.ReadError: "ReadError",
            _QP.ProcessError.UnknownError: "UnknownError",
        }
        self.status_lbl.setText(f"❌ {names.get(err, err)}")

    def _on_stderr(self):
        if not self.proc:
            return
        err = self.proc.readAllStandardError().data().decode(errors="replace")
        if err:
            # Defensa-en-profundidad: si algún CLI imprime su API key
            # accidentalmente en stderr, la redactamos antes de mostrar.
            err = _redact_secrets(err)
            self.err_box.moveCursor(self.err_box.textCursor().MoveOperation.End)
            self.err_box.insertPlainText(err)
            self.err_box.moveCursor(self.err_box.textCursor().MoveOperation.End)

    def _on_output(self):
        if not self.proc:
            return
        chunk = self.proc.readAllStandardOutput().data().decode(errors="replace")
        if not chunk:
            return
        if self._parser is None:
            # Modo texto plano (provider sin parser registrado): append directo
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            self.out.insertPlainText(chunk)
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            self._current_assistant_buf.append(chunk)
            return
        # Modo stream estructurado: parsear líneas completas
        self._stdout_buffer += chunk
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            evt = self._parser(line)
            if evt:
                self._handle_event(evt)

    def _handle_event(self, evt: dict):
        """Canonical event handler. Receives the normalised dict from
        the per-provider parser in `stream_parsers.py`. All fields
        are optional — the handler updates UI for whatever's present."""
        # Model name
        if evt.get("model") and not self._model_name:
            self._model_name = evt["model"]
            self._update_tokens_lbl()

        # TTFT (only set once — first delivered token wins)
        if evt.get("ttft_ms") is not None and self._ttft_ms is None:
            self._ttft_ms = evt["ttft_ms"]

        # Token counts — additive when monotonic, replace when full
        if evt.get("input_tokens") is not None:
            self._input_tokens = evt["input_tokens"]
            self._update_tokens_lbl()
        if evt.get("output_tokens") is not None:
            self._output_tokens = evt["output_tokens"]
            self._update_tokens_lbl()
        if evt.get("cache_read_tokens") is not None:
            self._cache_read_tokens = evt["cache_read_tokens"]
        if evt.get("cache_creation_tokens") is not None:
            self._cache_creation_tokens = evt["cache_creation_tokens"]

        # Status / tool-use feedback
        if evt.get("status"):
            self.status_lbl.setText(evt["status"])

        # Text delta — append to output pane + history
        delta = evt.get("text_delta")
        if delta:
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            self.out.insertPlainText(delta)
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            self._current_assistant_buf.append(delta)

        # Cost: prefer agent-reported (Claude `result.total_cost_usd`),
        # otherwise compute locally from token counts + cost_tracker.PRICING
        if evt.get("cost_usd") is not None:
            self._cost_usd = evt["cost_usd"]
            self._update_tokens_lbl()
        elif self._model_name and (self._input_tokens or self._output_tokens):
            try:
                from cost_tracker import cost_for
                cost, _known = cost_for(
                    self._model_name,
                    self._input_tokens,
                    self._output_tokens,
                    getattr(self, "_cache_creation_tokens", 0) or 0,
                    getattr(self, "_cache_read_tokens", 0) or 0,
                )
                self._cost_usd = cost
                self._update_tokens_lbl()
            except Exception:
                pass

    def _on_finished(self, code, exit_status):
        self._timer.stop()
        # Vuelco residual de stdout
        if self.proc:
            rest = self.proc.readAllStandardOutput().data().decode(errors="replace")
            if rest:
                if self._parser is not None:
                    self._stdout_buffer += rest
                    while "\n" in self._stdout_buffer:
                        line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        evt = self._parser(line)
                        if evt:
                            self._handle_event(evt)
                    # Última línea sin newline (best-effort parse)
                    if self._stdout_buffer.strip():
                        evt = self._parser(self._stdout_buffer.strip())
                        if evt:
                            self._handle_event(evt)
                        self._stdout_buffer = ""
                else:
                    self.out.moveCursor(self.out.textCursor().MoveOperation.End)
                    self.out.insertPlainText(rest)
            # Vuelco residual de stderr
            err_rest = self.proc.readAllStandardError().data().decode(errors="replace")
            if err_rest:
                self.err_box.moveCursor(self.err_box.textCursor().MoveOperation.End)
                self.err_box.insertPlainText(err_rest)

        from PyQt6.QtCore import QProcess as _QP
        crash_str = "" if exit_status == _QP.ExitStatus.NormalExit else "  (crash)"
        if code == 0:
            # Persistir el turno del assistant en el historial
            assistant_text = "".join(self._current_assistant_buf).strip()
            if assistant_text:
                self._messages.append({
                    "role": "assistant",
                    "content": assistant_text,
                })
            n_assistant = sum(1 for m in self._messages if m["role"] == "assistant")
            self.status_lbl.setText(
                f"✅ Turno {n_assistant} completado{crash_str}. "
                "Responde para iterar o pulsa 💾 Guardar y cerrar."
            )
            # Habilitar input de respuesta para multi-turno
            self.reply_input.setEnabled(True)
            self.send_btn.setEnabled(True)
            self.reply_input.setFocus()
        else:
            # Mostramos primera línea de stderr si la hay
            err_txt = self.err_box.toPlainText().strip().splitlines()
            first = err_txt[0] if err_txt else "(stderr vacío)"
            self.status_lbl.setText(f"⚠️ exit {code}{crash_str}  ·  {first[:120]}")
        self.cancel_btn.setEnabled(False)

    def _cancel(self):
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.status_lbl.setText("❌ Cancelado por el usuario")

    def _send_reply(self):
        """Envía la respuesta del usuario al agente: pinta separador en
        el output, añade el reply al historial y relanza el agente con
        el prompt multi-turno reconstruido."""
        reply = self.reply_input.toPlainText().strip()
        if not reply:
            return
        # Pintar el reply del usuario en el panel
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)
        self.out.insertHtml(
            "<br><br>"
            "<div style='border-top:1px solid #4ade80; margin:10px 0; "
            "padding-top:10px;'>"
            f"<b style='color:#62b4ff;'>👤 Tú:</b>"
            f"<pre style='color:#cfcfcf; margin:4px 0;'>"
            f"{_html.escape(reply)}</pre>"
            "<b style='color:#86efac;'>🤖 Agente:</b>"
            "</div><br>"
        )
        self.out.moveCursor(self.out.textCursor().MoveOperation.End)
        # Persistir y lanzar
        self._messages.append({"role": "user", "content": reply})
        self.reply_input.clear()
        self.reply_input.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.status_lbl.setText("⏳ Procesando tu respuesta…")
        self._launch_turn(self._build_multi_turn_prompt())

    def _build_multi_turn_prompt(self) -> str:
        """Reconstruye el prompt completo a enviar al agente incluyendo
        el prompt original (con sus facts y reglas) + el historial de
        la conversación hasta el último mensaje del usuario.

        Esto funciona con cualquier CLI tipo `claude --print`, `codex`,
        etc., porque no asumimos sesión persistente: cada turno se manda
        todo el contexto vía stdin.
        """
        parts = [self._original_prompt]
        # Si solo tenemos el primer user (el original) no hay nada que
        # añadir — sería el primer turno y _launch_turn se llamaría con
        # el prompt original directamente.
        if len(self._messages) <= 1:
            return self._original_prompt
        parts.append(
            "\n\n────────────────────────────────────────\n"
            "## Historial de la conversación previa\n"
            "(El usuario y tú habéis intercambiado los siguientes "
            "mensajes en este mismo análisis. No los repitas; continúa "
            "desde el último mensaje del usuario.)\n"
        )
        # Saltamos el primer user (es el prompt original ya incluido arriba).
        for msg in self._messages[1:]:
            if msg["role"] == "assistant":
                parts.append(f"\n### 🤖 Tu respuesta anterior:\n{msg['content']}\n")
            elif msg["role"] == "user":
                parts.append(f"\n### 👤 El usuario te respondió:\n{msg['content']}\n")
        parts.append(
            "\n────────────────────────────────────────\n"
            "Continúa la conversación respondiendo al ÚLTIMO mensaje "
            "del usuario. Sé directo, técnico, en español. NO repitas "
            "información de turnos previos — añade solo lo nuevo."
        )
        return "\n".join(parts)

    def accept(self):
        """Override: al cerrar el diálogo con 💾 Guardar y cerrar,
        insertamos el banner verde de confirmación (una sola vez) para
        que el texto que el caller toma de `self.out` incluya el aviso
        de que está guardado."""
        if (
            not self._final_banner_inserted
            and any(m["role"] == "assistant" for m in self._messages)
        ):
            self._final_banner_inserted = True
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
            n_turns = sum(1 for m in self._messages if m["role"] == "assistant")
            self.out.insertHtml(
                "<br><br>"
                "<div style='background:#1e3a23; border:1px solid #4ade80; "
                "border-radius:8px; padding:12px; margin:12px 0; "
                "color:#86efac;'>"
                f"<b>📋 Análisis guardado en ThemeForge ({n_turns} "
                "turno"
                + ("s" if n_turns != 1 else "")
                + ").</b><br>"
                "Cuando pulses <b>Crear proyecto</b>, este texto se "
                "inyectará automáticamente en el <code>CLAUDE.md</code> "
                "del proyecto y será lo PRIMERO que el agente IA lea al "
                "arrancar.</div>"
            )
            self.out.moveCursor(self.out.textCursor().MoveOperation.End)
        super().accept()

    def _copy_output(self):
        QApplication.clipboard().setText(self.out.toPlainText())
        self.status_lbl.setText("📋 Copiado al portapapeles.")

    def closeEvent(self, e):
        self._timer.stop()
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
        super().closeEvent(e)


class ThemeForge(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ThemeForge — ThemeForest builder")
        self.setMinimumWidth(760)
        self._github_user = gh_username()
        self._build_ui()
        self._update_preview()

    def _build_ui(self):
        title = QLabel("ThemeForge")
        f = QFont(); f.setPointSize(20); f.setBold(True)
        title.setFont(f)
        subtitle = QLabel(
            f"Builder de templates ThemeForest"
            + (f" — GitHub: @{self._github_user}" if self._github_user else " — (sin gh login)")
        )
        subtitle.setStyleSheet("color: #888;")

        # ── Datos básicos ────────────────────────────────────────────
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ej. Aurora SaaS Landing")
        self.name_edit.textChanged.connect(self._update_preview)
        self.name_edit.textChanged.connect(self._maybe_autodetect_licensing)

        # En vez de combo: botón que abre el picker modal categorizado.
        # El default se lee de las preferencias (configurable en el wizard
        # de bienvenida / Settings); fallback a nextjs-tailwind.
        import app_prefs as _ap
        self._stack_key = _ap.default_stack() if _ap.default_stack() in STACKS else "nextjs-tailwind"
        # True cuando el usuario ha elegido el stack a mano → la auto-detección
        # de WordPress (al elegir/crear con una referencia) NO lo pisa.
        self._stack_manually_set = False
        self.stack_button = QPushButton()
        self.stack_button.setMinimumHeight(36)
        self.stack_button.clicked.connect(self._open_stack_picker)
        self._refresh_stack_button()

        self.type_combo = QComboBox()
        for t in TEMPLATE_TYPES:
            self.type_combo.addItem(t)
        _dt = _ap.default_type()
        if _dt:
            _idx = self.type_combo.findText(_dt)
            if _idx >= 0:
                self.type_combo.setCurrentIndex(_idx)

        # Nicho — editable: el user puede elegir uno de la lista O escribir
        # el suyo a mano. El valor se inyecta en CLAUDE.md/AGENTS.md como
        # contexto de industria para que la IA acierte tono, paleta, copy
        # y demo data coherentes.
        self.niche_combo = QComboBox()
        self.niche_combo.setEditable(True)
        self.niche_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for n in TEMPLATE_NICHES:
            self.niche_combo.addItem(n)
        self.niche_combo.setToolTip(
            "Industria / nicho objetivo del template. Elige uno de la lista "
            "o escribe el tuyo (ej: 'Tienda de surf en Tarifa').\n\n"
            "Se inyecta en CLAUDE.md como contexto para que la IA use:\n"
            "  · Paleta coherente con el sector (cálida vs corporativa vs juvenil)\n"
            "  · Copy y CTAs del mismo dominio\n"
            "  · Imágenes Unsplash/Pexels temáticas\n"
            "  · Demo data realista (productos, testimonios, precios)\n\n"
            "Si dejas '(Sin nicho)' la IA trabaja en modo genérico."
        )

        self.provider_picker = ProviderPicker(self, label="Provider IA:")
        try:
            self.provider_picker.set_current_key(_ap.default_provider())
        except Exception:
            pass

        self.autoskills_check = QCheckBox("npx autoskills (auto-install skills for the stack)")
        self.autoskills_check.setChecked(True)

        self.uipro_check = QCheckBox(
            "uipro UI/UX Pro Max (design system · 67 styles · 161 palettes)"
        )
        # Auto-check para stacks UI; OFF para backend puro.
        self.uipro_check.setChecked(self._is_ui_stack(self._stack_key))

        self.mcp_check = QCheckBox(
            "📡 Pre-configure MCP servers (.mcp.json for Claude Code / Cursor / Windsurf)"
        )
        self.mcp_check.setToolTip(
            "ThemeForge generates a `.mcp.json` at the project root with a "
            "curated set of MCP servers relevant to the stack:\n"
            "  · filesystem · fetch · memory · github (always)\n"
            "  · playwright · chrome-devtools · figma-context · browsermcp (web/CMS)\n"
            "  · shopify-dev (Shopify only)\n"
            "  · postgres (when a DB is provisioned)\n"
            "  · themeforge (always — exposes create_project / deploy_demo / etc.)\n\n"
            "Your AI client (Claude Code, Cursor, Windsurf) reads it on startup "
            "and downloads each MCP via npx/uvx on first use. GPL-v3 compatible: "
            "every MCP is MIT/Apache-2.0, never bundled — config only."
        )
        self.mcp_check.setChecked(True)

        # ── Vibe scaffolder (input opcional) ────────────────────────
        # Si el user describe lo que quiere en lenguaje natural y le
        # da al botón, una IA pre-rellena el resto del form (stack,
        # tipo, theme, dev prompt) en una sola llamada.
        self.vibe_input = QPlainTextEdit()
        self.vibe_input.setPlaceholderText(
            "✨ Vibe scaffolder (optional) — describe in natural language "
            "what you want to build and the AI pre-fills the form.\n"
            "Example: 'Premium landing page for a dental clinic in Madrid, "
            "warm palette, conversion-optimized'"
        )
        self.vibe_input.setMaximumHeight(70)
        self.btn_vibe = QPushButton("✨ Pre-fill form with AI")
        self.btn_vibe.setToolTip(
            "Sends a description to the active AI (Claude / Codex / "
            "Gemini / OpenCode) and auto-fills: stack, template type, "
            "app theme, autoskills/uipro toggles and a dev prompt for "
            "the agent."
        )
        self.btn_vibe.clicked.connect(self._on_vibe)
        # Persisted dev_prompt from vibe (used as ai_analysis in scratch mode)
        self._vibe_dev_prompt: str = ""

        # NOTE: form layout was replaced by sub-tabs (assembled below).
        # Widgets above remain as instance attributes so all the signal
        # wiring and validation logic stays untouched.

        # ── Mode ─────────────────────────────────────────────────────
        mode_box = QGroupBox("Mode")
        self.mode_scratch = QRadioButton("From scratch — scaffold + agent only")
        self.mode_recreate = QRadioButton("Recreate from reference — study and re-implement")
        self.mode_adopt = QRadioButton("Adopt local template — copy as-is and work in-place (mono-repos supported)")
        self.mode_existing = QRadioButton("Work on existing GitHub repo")
        self.mode_scratch.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_scratch, 0)
        self.mode_group.addButton(self.mode_recreate, 1)
        self.mode_group.addButton(self.mode_adopt, 2)
        self.mode_group.addButton(self.mode_existing, 3)

        # — Sub-form recreate
        self.ref_kind_combo = QComboBox()
        self.ref_kind_combo.addItem("Carpeta local", userData="folder")
        self.ref_kind_combo.addItem("Archivo .zip", userData="zip")
        self.ref_kind_combo.addItem("URL de demo", userData="url")
        self.ref_kind_combo.addItem("Figma (URL del frame)", userData="figma")
        self.ref_path_edit = QLineEdit()
        self.ref_path_edit.setPlaceholderText("Ruta o URL de la referencia…")
        self.ref_browse_btn = QPushButton("Examinar…")
        self.ref_browse_btn.clicked.connect(self._browse_reference)
        ref_row = QHBoxLayout()
        ref_row.addWidget(self.ref_path_edit, 1)
        ref_row.addWidget(self.ref_browse_btn)
        # Botón análisis IA
        self.ref_analyze_btn = QPushButton("🔍 Analizar referencia con IA")
        self.ref_analyze_btn.setToolTip(
            "Detecta el stack del template y pide a la IA (Claude/Codex) "
            "una recomendación de qué stack moderno usar para tu reimplementación."
        )
        self.ref_analyze_btn.clicked.connect(self._analyze_reference)
        # Estado del análisis (QProcess vivo + label + último resultado)
        self._analyze_proc: QProcess | None = None
        self._last_analysis: tuple[str, str] | None = None
        # Tipo de análisis: "reference" (default, recreate/adopt),
        # "vibe" (dev_prompt del Vibe scaffolder),
        # "market" (pestaña Market → el agente decide stack/nicho).
        self._last_analysis_kind: str = "reference"
        self.analysis_status_lbl = QLabel("")
        self.analysis_status_lbl.setWordWrap(True)
        self.analysis_status_lbl.setStyleSheet(
            "color:#86efac; font-size:11pt; font-weight:bold; "
            "padding:8px 12px; background:#1e3a23; border:1px solid #4ade80; "
            "border-radius:6px;"
        )
        self.analysis_status_lbl.setVisible(False)
        ref_form = QFormLayout()
        ref_form.addRow("Tipo de referencia:", self.ref_kind_combo)
        ref_form.addRow("Origen:", ref_row)
        ref_form.addRow("", self.ref_analyze_btn)
        ref_form.addRow("", self.analysis_status_lbl)
        self.ref_widget = QWidget(); self.ref_widget.setLayout(ref_form); self.ref_widget.setEnabled(False)

        # — Sub-form adopt
        self.adopt_path_edit = QLineEdit()
        self.adopt_path_edit.setPlaceholderText("Ruta a la carpeta del template (se copiará a project_dir)…")
        self.adopt_browse_btn = QPushButton("Examinar…")
        self.adopt_browse_btn.clicked.connect(self._browse_adopt)
        adopt_row = QHBoxLayout()
        adopt_row.addWidget(self.adopt_path_edit, 1)
        adopt_row.addWidget(self.adopt_browse_btn)
        # Botón de análisis IA: útil sobre todo para design-exports de
        # claude.ai/design o v0.dev donde la IA sugerirá stack moderno.
        self.adopt_analyze_btn = QPushButton("🔍 Analizar con IA (sugiere stack)")
        self.adopt_analyze_btn.setToolTip(
            "Si la carpeta es un export de claude.ai/design / v0.dev / Figma Make "
            "(HTML/JSX/CSS sin package.json), la IA te recomienda qué stack "
            "moderno usar para construir el producto real sobre tu diseño. "
            "Si es un mono-repo o proyecto existente, hace análisis técnico + "
            "estrategia de mercado."
        )
        self.adopt_analyze_btn.clicked.connect(self._analyze_adopt)
        # Label de status para el análisis adopt (sugerencia de stack)
        self.adopt_analysis_status_lbl = QLabel("")
        self.adopt_analysis_status_lbl.setWordWrap(True)
        self.adopt_analysis_status_lbl.setStyleSheet(
            "color:#86efac; font-size:11pt; font-weight:bold; "
            "padding:8px 12px; background:#1e3a23; border:1px solid #4ade80; "
            "border-radius:6px;"
        )
        self.adopt_analysis_status_lbl.setVisible(False)
        adopt_form = QFormLayout()
        adopt_form.addRow("Carpeta origen:", adopt_row)
        adopt_hint = QLabel(
            "<span style='color:#888;font-size:9pt'>Se copia tal cual al proyecto. "
            "Soporta: (1) mono-repos CodeCanyon con varios stacks que ThemeForge "
            "detectará automáticamente, (2) proyectos existentes que quieres "
            "adoptar, (3) exports de diseño tipo claude.ai/design / v0.dev / "
            "Figma Make — pulsa <b>Analizar con IA</b> y te sugerirá stack moderno.</span>"
        )
        adopt_hint.setWordWrap(True)
        adopt_form.addRow("", adopt_hint)
        adopt_form.addRow("", self.adopt_analyze_btn)
        adopt_form.addRow("", self.adopt_analysis_status_lbl)
        self.adopt_widget = QWidget(); self.adopt_widget.setLayout(adopt_form); self.adopt_widget.setEnabled(False)

        # — Sub-form existing
        self.repo_combo = QComboBox()
        self.repo_combo.setEditable(True)
        self.repo_combo.setPlaceholderText("owner/repo o selecciona de la lista…")
        self.repo_load_btn = QPushButton("↻ Load my repos")
        self.repo_load_btn.clicked.connect(self._load_repos)
        repo_row = QHBoxLayout()
        repo_row.addWidget(self.repo_combo, 1)
        repo_row.addWidget(self.repo_load_btn)
        existing_form = QFormLayout()
        existing_form.addRow("Repo:", repo_row)
        self.existing_widget = QWidget(); self.existing_widget.setLayout(existing_form); self.existing_widget.setEnabled(False)

        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.mode_scratch)
        mode_layout.addWidget(self.mode_recreate)
        mode_layout.addWidget(self.ref_widget)
        mode_layout.addWidget(self.mode_adopt)
        mode_layout.addWidget(self.adopt_widget)
        mode_layout.addWidget(self.mode_existing)
        mode_layout.addWidget(self.existing_widget)
        mode_box.setLayout(mode_layout)
        self.mode_group.idToggled.connect(self._mode_changed)
        # Hide inactive sub-forms at startup. Default is scratch, so all
        # three sub-form widgets should be hidden by default.
        self.ref_widget.setVisible(False)
        self.adopt_widget.setVisible(False)
        self.existing_widget.setVisible(False)

        # ── GitHub repo crear (deshabilitado en wizard) ──────────────
        # El repo se crea bajo demanda desde el botón "📦 GitHub" del
        # ProjectWindow, no automáticamente al crear el proyecto.
        # Mantenemos el atributo para no romper el resto del código,
        # pero como QCheckBox oculto.
        self.github_create_check = QCheckBox()
        self.github_create_check.setChecked(False)
        self.github_create_check.setVisible(False)

        # ── Postgres opcional ────────────────────────────────────────
        self.postgres_check = QCheckBox(
            "🐘 Provision Postgres (dedicated Docker container + DATABASE_URL in .env)"
        )
        self.postgres_check.setToolTip(
            "Spins up a postgres:17-alpine container with a unique port for "
            "this project and injects DATABASE_URL into .env. Useful for "
            "stacks that don't ship a DB by default but you intend to use "
            "one (Next, Nuxt, Express, Laravel, Rails…). Requires Docker "
            "accessible without sudo."
        )
        self.postgres_check.setChecked(False)

        # ── licensing integration ────────────────────────────────────
        self.licensing_check = QCheckBox(
            "🔑 Enable licensing system (generates verify-license + setup wizard for the stack)"
        )
        self.licensing_check.setToolTip(
            "Marca esto si vas a vender el theme bajo tu sistema de licencias "
            "configurado (ver `~/.config/themeforge/licensing.json`). "
            "Drops automáticos según la familia del stack:\n"
            "  · Next.js → /api/verify-license + /setup wizard + Zustand store + middleware\n"
            "  · Laravel → SetupWizardController + middleware + model + migration + Blade view\n"
            "  · WordPress → clase License + página admin de licencia\n"
            "  · Hono/Nest/Bun-Elysia → route stub de verificación\n"
            "Spec en context/LICENSING-SYSTEM.template.md. Versión real "
            "del usuario en ~/.config/themeforge/context-private/."
        )
        # Auto-check si el slug aparece en la lista privada del usuario
        # (~/.config/themeforge/known-product-slugs.txt). Si la lista no
        # existe no se preselecciona.
        self.licensing_check.setChecked(False)

        self.licensing_gh_check = QCheckBox(
            "    └─ Crear repo gh `<your-gh-org>/<slug>` (Phase 3)"
        )
        self.licensing_gh_check.setToolTip(
            "Tras el scaffold, ejecuta `gh repo create <your-gh-org>/<slug> "
            "--private --source . --remote origin`. Requiere `gh` autenticado "
            "con permisos sobre la org GitHub configurada en `licensing.json` (campo `github_org`)."
        )
        self.licensing_gh_check.setChecked(False)
        self.licensing_gh_check.setEnabled(False)

        self.licensing_force_check = QCheckBox(
            "    └─ Forzar también en modos `adopt` / `existing`"
        )
        self.licensing_force_check.setToolTip(
            "Por defecto el licensing scaffold SOLO corre en `scratch` y "
            "`recreate` para no chocar con proyectos que ya tienen estructura. "
            "Marca esto si adoptas o clonas un theme y SABES que no tiene aún "
            "la integración de licencias."
        )
        self.licensing_force_check.setChecked(False)
        self.licensing_force_check.setEnabled(False)

        # Solo habilitamos los sub-checkboxes si el padre está activo
        self.licensing_check.toggled.connect(self.licensing_gh_check.setEnabled)
        self.licensing_check.toggled.connect(self.licensing_force_check.setEnabled)

        # ── Vista previa ─────────────────────────────────────────────
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(170)
        self.preview.setStyleSheet("background:#1e1e1e;color:#cfcfcf;font-family:monospace;")

        # ── Buttons ──────────────────────────────────────────────────
        self.create_btn = QPushButton("Create project and launch agent")
        self.create_btn.clicked.connect(self.create_project)
        self.create_btn.setMinimumHeight(40)
        self.create_btn.setStyleSheet("font-weight:bold;")
        self.cancel_btn = QPushButton("Quit")
        self.cancel_btn.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(self.cancel_btn); btns.addStretch(); btns.addWidget(self.create_btn)

        # ── Sub-tabs (rediseño: dividir el form pesado en 5 sub-pestañas) ──
        # Cada widget construido arriba se agrupa por afinidad. Footer
        # con Salir/Crear queda fijo siempre visible.
        self.new_project_subtabs = QTabWidget()

        # Sub-tab 1: ✨ Vibe (hero, opcional)
        vibe_tab = QWidget()
        vibe_lay = QVBoxLayout(vibe_tab)
        vibe_intro = QLabel(
            "<h3>✨ Vibe scaffolder</h3>"
            "<small>Describe in natural language what you want to build "
            "and the AI pre-fills the other sub-tabs (Stack, Type, Theme, "
            "skills) plus a full dev prompt. <b>Optional</b> — if you "
            "prefer to configure manually, jump to the <b>🏗️ Setup</b> tab.</small>"
        )
        vibe_intro.setTextFormat(Qt.TextFormat.RichText)
        vibe_intro.setWordWrap(True)
        self.vibe_input.setMaximumHeight(140)  # más alto en la sub-tab dedicada
        vibe_lay.addWidget(vibe_intro)
        vibe_lay.addWidget(self.vibe_input, 1)
        vibe_btn_row = QHBoxLayout()
        vibe_btn_row.addStretch()
        vibe_btn_row.addWidget(self.btn_vibe)
        vibe_lay.addLayout(vibe_btn_row)
        vibe_lay.addStretch()
        self.new_project_subtabs.addTab(vibe_tab, "✨ Vibe")  # same in English

        # Sub-tab 2: 🏗️ Setup (lo básico)
        setup_tab = QWidget()
        setup_form = QFormLayout(setup_tab)
        setup_form.addRow("Name:", self.name_edit)
        setup_form.addRow("Stack:", self.stack_button)
        setup_form.addRow("Type:", self.type_combo)
        setup_form.addRow("Niche:", self.niche_combo)
        setup_form.addRow("Provider:", self.provider_picker)
        setup_form.addRow("", self.autoskills_check)
        setup_form.addRow("", self.uipro_check)
        setup_form.addRow("", self.mcp_check)
        self.new_project_subtabs.addTab(setup_tab, "🏗️ Setup")  # same in English

        # Sub-tab 3: 📦 Modo (el viejo mode_box, ahora dedicado)
        mode_tab = QWidget()
        mode_tab_lay = QVBoxLayout(mode_tab)
        mode_tab_lay.addWidget(mode_box)
        mode_tab_lay.addStretch()
        self.new_project_subtabs.addTab(mode_tab, "📦 Mode")

        # Sub-tab 4: 🔌 Extras (postgres + licensing)
        extras_tab = QWidget()
        extras_lay = QVBoxLayout(extras_tab)
        extras_hint = QLabel(
            "<small>Advanced toggles that only apply if you need them. "
            "For most templates you can leave these off.</small>"
        )
        extras_hint.setTextFormat(Qt.TextFormat.RichText)
        extras_hint.setWordWrap(True)
        extras_lay.addWidget(extras_hint)
        extras_lay.addSpacing(6)
        extras_lay.addWidget(self.postgres_check)
        extras_lay.addSpacing(10)
        extras_lay.addWidget(self.licensing_check)
        extras_lay.addWidget(self.licensing_gh_check)
        extras_lay.addWidget(self.licensing_force_check)
        extras_lay.addStretch()
        self.new_project_subtabs.addTab(extras_tab, "🔌 Extras")  # same

        # Sub-tab 5: 👁 Preview (vista previa antes de crear)
        preview_tab = QWidget()
        preview_lay = QVBoxLayout(preview_tab)
        preview_lay.addWidget(QLabel(
            "<small>Preview of the scaffold command that will run. "
            "Confirm with the <b>Create project</b> button below.</small>"
        ))
        preview_lay.addWidget(self.preview, 1)
        self.new_project_subtabs.addTab(preview_tab, "👁 Preview")  # same

        # ── Root ─────────────────────────────────────────────────────
        root = QVBoxLayout()
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(6)
        root.addWidget(self.new_project_subtabs, 1)
        root.addLayout(btns)
        self.setLayout(root)

        # señales para preview
        for w in (self.type_combo, self.ref_kind_combo, self.repo_combo):
            w.currentIndexChanged.connect(self._update_preview)
        # Persistir el provider elegido como default → lo usan las ventanas de
        # proyecto (galería / abrir otro) para abrir SOLO esa IA.
        self.provider_picker.providerChanged.connect(
            lambda k: (_ap.set_defaults(provider=k), self._update_preview()))
        self.ref_path_edit.textChanged.connect(self._update_preview)
        self.ref_path_edit.textChanged.connect(self._invalidate_analysis_if_path_changed)
        # Sin análisis IA: al terminar de teclear/pegar una ruta, intenta
        # detectar WordPress y fijar el stack automáticamente.
        self.ref_path_edit.editingFinished.connect(self._autodetect_wp_stack)
        self.adopt_path_edit.textChanged.connect(self._update_preview)
        self.repo_combo.editTextChanged.connect(self._update_preview)
        self.github_create_check.toggled.connect(self._update_preview)
        self.licensing_check.toggled.connect(self._update_preview)
        self.ref_kind_combo.currentIndexChanged.connect(self._ref_kind_changed)
        self._ref_kind_changed()

    def _refresh_stack_button(self):
        s = STACKS.get(self._stack_key) or STACKS["none"]
        self.stack_button.setText(f"  {s['name']}   —   {s['category']}     (click para cambiar)")
        self.stack_button.setStyleSheet(
            "text-align:left; padding:6px 10px; font-weight:bold;"
        )

    def _is_ui_stack(self, stack_key: str) -> bool:
        """Returns True if the stack has a visual UI surface (frontend,
        mobile, e-commerce, CMS, game, desktop, etc.) where UI/UX Pro Max
        adds value. Backend-only stacks return False."""
        s = STACKS.get(stack_key) or {}
        cat = s.get("category", "")
        return cat not in ("Backend · API", "Sin definir", "")

    def _open_stack_picker(self):
        dlg = StackPickerDialog(self, initial=self._stack_key)
        if dlg.exec() == StackPickerDialog.DialogCode.Accepted and dlg.selected_key:
            self._stack_key = dlg.selected_key
            self._stack_manually_set = True
            self._refresh_stack_button()
            # Re-evaluate uipro auto-check based on new stack category
            if hasattr(self, "uipro_check"):
                self.uipro_check.setChecked(self._is_ui_stack(self._stack_key))
            self._update_preview()

    def _on_vibe(self):
        """✨ Vibe scaffolder: el user describe el proyecto en lenguaje
        natural, una IA propone stack + tipo + theme + dev prompt, y
        el form se auto-rellena. El dev_prompt se inyecta luego como
        ai_analysis en CLAUDE.md cuando se crea el proyecto."""
        text = self.vibe_input.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Vibe scaffolder",
                "Escribe primero una descripción de lo que quieres construir.",
            )
            return
        agent_key = self.provider_picker.current_key()
        state, info = aip.detect_status(agent_key)
        if state != "ok":
            QMessageBox.warning(
                self, "Vibe scaffolder",
                f"Provider {agent_key} no listo: {info}",
            )
            return

        try:
            from vibe_scaffolder import VibeDialog
        except Exception as e:
            QMessageBox.critical(self, "Vibe scaffolder", f"No se pudo cargar: {e}")
            return

        # Builtin themes for the agent to pick from
        try:
            import themes as _t
            theme_names = [t.name for t in _t.list_themes() if not t.is_user]
        except Exception:
            theme_names = ["themeforge-dark"]

        dlg = VibeDialog(self, text, agent_key, STACKS, TEMPLATE_TYPES, theme_names)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.proposal:
            return
        proposal = dlg.proposal

        # Apply stack
        if proposal.stack_key in STACKS:
            self._stack_key = proposal.stack_key
            self._refresh_stack_button()
        # Apply template type
        idx = self.type_combo.findText(proposal.template_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        # Apply toggles
        self.autoskills_check.setChecked(proposal.run_autoskills)
        if hasattr(self, "uipro_check"):
            # Override the auto-check based on what the AI proposed
            self.uipro_check.setChecked(proposal.run_uipro)

        # Store dev_prompt for injection as ai_analysis in scratch mode
        self._vibe_dev_prompt = proposal.dev_prompt
        # Reuse the _last_analysis pipeline: (None, text) means "use in scratch"
        self._last_analysis = (None, proposal.dev_prompt)
        self._last_analysis_kind = "vibe"

        # NOTA: el `theme_hint` es solo una SUGERENCIA estética para el
        # proyecto (ya va escrita dentro del dev_prompt que recibe el
        # agente). NO tocamos el theme de ThemeForge: la app mantiene el
        # tema que el user tenga elegido en Settings. Antes esto aplicaba
        # y persistía el theme en la propia UI, lo que la dejaba en blanco.

        # Auto-suggest a project name if empty
        if not self.name_edit.text().strip():
            # Derive a snake-case name from the first words of the dev_prompt
            slug = re.sub(r"[^a-z0-9]+", "-",
                          " ".join(proposal.dev_prompt.split()[:4]).lower())
            slug = slug.strip("-")[:32]
            if slug:
                self.name_edit.setText(slug)

        # ── ¿Crear directamente? ────────────────────────────────────────
        # Si el user pulsó "🚀 Crear proyecto ya" en el diálogo, forzamos
        # modo scratch (el dev_prompt del vibe solo se inyecta en scratch,
        # ver create_project) y lanzamos la creación sin volver al form.
        if getattr(dlg, "create_now", False):
            self.mode_scratch.setChecked(True)
            self.create_project()
            return

        QMessageBox.information(
            self, "✨ Vibe aplicado",
            f"Form pre-rellenado con la propuesta:\n\n"
            f"  Stack: {STACKS[proposal.stack_key]['name']}\n"
            f"  Tipo:  {proposal.template_type}\n"
            f"  Theme: {proposal.theme_hint}\n\n"
            f"El dev prompt se inyectará en CLAUDE.md cuando crees el proyecto."
        )

    def _mode_changed(self, _id, checked):
        is_recreate = self.mode_recreate.isChecked()
        is_adopt = self.mode_adopt.isChecked()
        is_existing = self.mode_existing.isChecked()
        # Visibility: solo se ve el sub-form del modo seleccionado.
        # (Antes se hacía setEnabled — los demás quedaban grises y
        # ocupaban espacio. Ahora se ocultan completamente.)
        self.ref_widget.setVisible(is_recreate)
        self.ref_widget.setEnabled(is_recreate)
        self.adopt_widget.setVisible(is_adopt)
        self.adopt_widget.setEnabled(is_adopt)
        self.existing_widget.setVisible(is_existing)
        self.existing_widget.setEnabled(is_existing)
        # En modo existing o adopt el scaffolding no aplica (ya hay código).
        self.stack_button.setEnabled(not (is_existing or is_adopt))
        # En modo existing/adopt no creamos repo nuevo en GitHub por defecto
        if is_existing or is_adopt:
            self.github_create_check.setChecked(False)
        self.github_create_check.setEnabled(
            not is_existing and bool(self._github_user)
        )
        self._update_preview()

    def _ref_kind_changed(self):
        kind = self.ref_kind_combo.currentData()
        if kind == "url":
            self.ref_browse_btn.setVisible(False)
            self.ref_path_edit.setPlaceholderText("https://demo.tema.com/")
        else:
            self.ref_browse_btn.setVisible(True)
            self.ref_path_edit.setPlaceholderText(
                "Selecciona la carpeta…" if kind == "folder" else "Selecciona el .zip…"
            )

    def _browse_reference(self):
        kind = self.ref_kind_combo.currentData()
        if kind == "folder":
            p = QFileDialog.getExistingDirectory(self, "Carpeta de referencia", str(HOME))
        elif kind == "zip":
            p, _ = QFileDialog.getOpenFileName(self, "Archivo .zip", str(HOME), "ZIP (*.zip)")
        else:
            return
        if p:
            self.ref_path_edit.setText(p)
            self._autodetect_wp_stack()

    def _autodetect_wp_stack(self):
        """Sin análisis IA: si la referencia (carpeta/.zip, incluida subcarpeta
        o mono-repo) es un theme/plugin de WordPress, fija el stack a WordPress
        para que al crear se auto-instale WP en Docker. Respeta una elección
        manual de stack hecha para ESTA misma referencia."""
        if not self.mode_recreate.isChecked():
            return
        kind = self.ref_kind_combo.currentData()
        if kind not in ("folder", "zip"):
            return  # una URL no se puede inspeccionar en local
        val = self.ref_path_edit.text().strip()
        if not val:
            return
        p = Path(val)
        if not p.exists():
            return
        # Una referencia nueva re-habilita la auto-detección.
        if val != getattr(self, "_last_ref_for_stack", None):
            self._stack_manually_set = False
            self._last_ref_for_stack = val
        if self._stack_manually_set:
            return
        try:
            from reference_analyzer import detect_wordpress_stack
            wp_stack = detect_wordpress_stack(p)
        except Exception:
            wp_stack = None
        if not wp_stack or wp_stack == self._stack_key:
            return
        self._stack_key = wp_stack
        self._refresh_stack_button()
        if hasattr(self, "uipro_check"):
            self.uipro_check.setChecked(self._is_ui_stack(self._stack_key))
        self._update_preview()
        self.analysis_status_lbl.setStyleSheet(
            "color:#93c5fd; font-size:10pt; font-weight:bold; "
            "padding:8px 12px; background:#1e293b; border:1px solid #3b82f6; "
            "border-radius:6px;"
        )
        self.analysis_status_lbl.setText(
            f"🔌 Referencia WordPress detectada → stack fijado a «{STACKS[wp_stack]['name']}». "
            f"Al crear, ThemeForge auto-instala WordPress en Docker "
            f"(puedes cambiarlo en el selector de stack)."
        )
        self.analysis_status_lbl.setVisible(True)

    def _browse_adopt(self):
        p = QFileDialog.getExistingDirectory(self, "Carpeta del template a adoptar", str(HOME))
        if p:
            self.adopt_path_edit.setText(p)

    def _analyze_adopt(self):
        """Mismo flujo que _analyze_reference pero sobre la ruta del modo
        adopt. Útil sobre todo para design-exports (claude.ai/design,
        v0.dev, Figma Make) donde el detector reconocerá HTML/JSX sin
        package.json y la IA recomendará stack moderno."""
        path_str = self.adopt_path_edit.text().strip()
        if not path_str:
            QMessageBox.warning(self, "ThemeForge", "Specify the folder to adopt first.")
            return
        path = Path(path_str)
        if not path.is_dir():
            QMessageBox.warning(self, "ThemeForge", f"Folder does not exist:\n{path}")
            return
        try:
            from reference_analyzer import gather_facts, build_prompt
        except Exception as e:
            QMessageBox.critical(self, "Análisis IA", f"No se pudo cargar el analizador:\n{e}")
            return

        facts = gather_facts(path)
        prompt = build_prompt(facts)
        agent_key = self.provider_picker.current_key()
        agent_meta = AGENTS.get(agent_key) or AGENTS["claude"]

        state, info = aip.detect_status(agent_key)
        if state != "ok":
            QMessageBox.critical(
                self, "Análisis IA",
                f"Provider {agent_meta['name']} no listo: {info}",
            )
            return

        argv = aip.oneshot_argv(agent_key, allow_web=True)
        parser_kind = aip.PROVIDERS[agent_key]["command"]

        # Env vars del provider (API keys) heredadas por el subproceso
        extra_env = aip.get_env(agent_key)

        dlg = _ReferenceAnalysisDialog(self, agent_meta["name"], facts, parser_kind)
        dlg.run(prompt, argv, extra_env=extra_env)
        dlg.exec()
        result_text = dlg.out.toPlainText().strip()
        if result_text:
            # Guardamos el análisis para inyectarlo en CLAUDE.md igual que
            # el de modo recreate. Reutilizamos _last_analysis con (path, text).
            self._last_analysis = (path_str, result_text)
            self._last_analysis_kind = "reference"
            kind = facts.get("kind", "")
            if kind == "design-export":
                self.adopt_analysis_status_lbl.setText(
                    "✓ Stack recomendado por IA — se inyectará en CLAUDE.md al crear el proyecto. "
                    "El agente leerá la recomendación y propondrá el plan de migración del diseño."
                )
            else:
                self.adopt_analysis_status_lbl.setText(
                    "✓ Análisis IA listo — se inyectará en CLAUDE.md al crear el proyecto."
                )
            self.adopt_analysis_status_lbl.setVisible(True)
        else:
            self._last_analysis = None
            self._last_analysis_kind = "reference"
            self.adopt_analysis_status_lbl.setVisible(False)

    def _analyze_reference(self):
        """Recopila facts del path de referencia y los manda a la IA
        (claude/codex CLI) en una llamada one-shot. Muestra el resultado
        en un diálogo modal."""
        path_str = self.ref_path_edit.text().strip()
        if not path_str:
            QMessageBox.warning(self, "ThemeForge", "Indica primero la ruta de la referencia.")
            return
        path = Path(path_str)
        kind = self.ref_kind_combo.currentData()
        if kind == "url":
            QMessageBox.information(
                self, "Análisis IA",
                "El análisis automático funciona con carpetas y archivos .zip. "
                "Para una URL, primero descárgala (modo recreate la baja a "
                "reference/) y luego ejecuta el análisis sobre esa carpeta.",
            )
            return
        if kind == "folder" and not path.is_dir():
            QMessageBox.warning(self, "ThemeForge", f"Folder does not exist:\n{path}")
            return
        if kind == "zip" and not (path.is_file() and path_str.lower().endswith(".zip")):
            QMessageBox.warning(self, "ThemeForge", "El .zip no existe o no es un .zip.")
            return

        # Carga lazy del analyzer
        try:
            from reference_analyzer import gather_facts, build_prompt
        except Exception as e:
            QMessageBox.critical(self, "Análisis IA", f"No se pudo cargar el analizador:\n{e}")
            return

        facts = gather_facts(path)

        # Si la referencia es WordPress, fijamos el stack a WordPress
        # (theme/plugin). Eso dispara, al crear: auto-instalación de WP en
        # Docker, el §B WordPress y el preview apuntando al contenedor. El
        # prompt de análisis (build_prompt) recomendará SOLO enfoques WordPress.
        _wp_kind = facts.get("kind") if isinstance(facts, dict) else None
        if _wp_kind in ("wordpress-theme", "wordpress-plugin"):
            # Respeta una elección manual de variante WP (bricks/elementor/divi/
            # breakdance). Si el user ya picó un theme-builder WP a mano, no
            # bajamos el stack a «Block Theme» — eso se cargaba el pack UX
            # configurado (instalaría plugins FSE en vez de los del builder).
            if _wp_kind == "wordpress-theme" and self._stack_key in _WORDPRESS_THEME_STACKS:
                _new_stack = self._stack_key
            else:
                _new_stack = "wordpress-block" if _wp_kind == "wordpress-theme" else "wordpress-plugin"
            if self._stack_key != _new_stack:
                self._stack_key = _new_stack
                self._refresh_stack_button()
                if hasattr(self, "uipro_check"):
                    self.uipro_check.setChecked(self._is_ui_stack(self._stack_key))
                self._update_preview()
            self.analysis_status_lbl.setText(
                f"🔌 Referencia WordPress detectada → stack fijado a «{STACKS[_new_stack]['name']}». "
                f"Al crear, ThemeForge auto-instala WordPress en Docker y el preview apuntará ahí."
            )
            self.analysis_status_lbl.setVisible(True)

        prompt = build_prompt(facts)

        agent_key = self.provider_picker.current_key()
        agent_meta = AGENTS.get(agent_key) or AGENTS["claude"]

        state, info = aip.detect_status(agent_key)
        if state != "ok":
            QMessageBox.critical(
                self, "Análisis IA",
                f"Provider {agent_meta['name']} no listo: {info}",
            )
            return

        argv = aip.oneshot_argv(agent_key, allow_web=True)
        parser_kind = aip.PROVIDERS[agent_key]["command"]
        extra_env = aip.get_env(agent_key)

        dlg = _ReferenceAnalysisDialog(self, agent_meta["name"], facts, parser_kind)
        dlg.run(prompt, argv, extra_env=extra_env)
        dlg.exec()
        # Tras cerrar el diálogo, guardar el resultado si se obtuvo respuesta
        result_text = dlg.out.toPlainText().strip()
        if result_text:
            self._last_analysis = (path_str, result_text)
            self._last_analysis_kind = "reference"
            self.analysis_status_lbl.setText(
                "✓ Análisis IA listo — se inyectará en CLAUDE.md al crear el proyecto. "
                "Claude lo leerá nada más arrancar y te confirmará qué entiende que tiene que hacer."
            )
            self.analysis_status_lbl.setVisible(True)
        else:
            self._last_analysis = None
            self._last_analysis_kind = "reference"
            self.analysis_status_lbl.setText("")
            self.analysis_status_lbl.setVisible(False)

    def _maybe_autodetect_licensing(self, _text: str):
        """Pre-marca el checkbox del sistema de licencias si el slug aparece en la
        lista privada del usuario (`~/.config/themeforge/known-product-slugs.txt`).
        Si esa lista no existe no hay auto-detección. El usuario siempre
        puede marcar/desmarcar el checkbox manualmente."""
        try:
            from licensing_scaffold import likely_known_product
            slug = slugify(self.name_edit.text().strip())
            if slug and likely_known_product(slug):
                self.licensing_check.setChecked(True)
        except Exception:
            pass

    def _invalidate_analysis_if_path_changed(self):
        """Si el user cambia la ruta de referencia, el análisis previo
        deja de ser válido."""
        if self._last_analysis and self._last_analysis[0] != self.ref_path_edit.text().strip():
            self._last_analysis = None
            self._last_analysis_kind = "reference"
            self.analysis_status_lbl.setStyleSheet(
                "color:#fbbf24; font-size:10pt; font-weight:bold; "
                "padding:8px 12px; background:#3a2e1e; border:1px solid #f59e0b; "
                "border-radius:6px;"
            )
            self.analysis_status_lbl.setText(
                "ℹ️ Ruta cambiada — vuelve a ejecutar el análisis si quieres inyectarlo."
            )
            self.analysis_status_lbl.setVisible(True)

    def _load_repos(self):
        if not self._github_user:
            QMessageBox.warning(self, "GitHub", "No active gh session. Run `gh auth login` first.")
            return
        self.repo_load_btn.setText("Cargando…")
        self.repo_load_btn.setEnabled(False)
        QApplication.processEvents()
        try:
            repos = gh_list_repos()
            self.repo_combo.clear()
            for r in sorted(repos, key=lambda x: x.get("updatedAt", ""), reverse=True):
                vis = (r.get("visibility") or "").lower()
                label = f"{r['nameWithOwner']}  ({vis})"
                self.repo_combo.addItem(label, userData=r["nameWithOwner"])
            if repos:
                # Auto-open the dropdown so the user immediately sees
                # the list (otherwise the editable combo looks empty
                # and there's no clear affordance to expand it).
                self.repo_combo.setCurrentIndex(0)
                self.repo_load_btn.setText(f"✓ {len(repos)} repos cargados")
                # Defer showPopup so the button-text update renders first
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(150, self.repo_combo.showPopup)
            else:
                QMessageBox.information(
                    self, "GitHub",
                    "No se encontraron repos. Verifica que `gh` esté "
                    "autenticado (`gh auth status`) y que la cuenta "
                    "tenga repositorios."
                )
                self.repo_load_btn.setText("↻ Load my repos")
        except Exception as e:
            QMessageBox.critical(self, "GitHub", f"Error cargando repos: {e}")
            self.repo_load_btn.setText("↻ Load my repos")
        finally:
            self.repo_load_btn.setEnabled(True)

    def _current_repo_id(self) -> str:
        # Devuelve el nameWithOwner si fue seleccionado de la lista,
        # o el texto escrito si el usuario lo metió manualmente.
        d = self.repo_combo.currentData()
        if d:
            return d
        txt = self.repo_combo.currentText().strip()
        # Si trae el sufijo " (public/private)" lo limpiamos
        return re.sub(r"\s*\(.*\)$", "", txt)

    def _update_preview(self):
        name = self.name_edit.text() or "(sin nombre)"
        slug = slugify(name) if not self.mode_existing.isChecked() else (
            self._current_repo_id().split("/")[-1] or slugify(name)
        )
        stack_key = self._stack_key or list(STACKS)[0]
        stack = STACKS[stack_key]
        agent = AGENTS[self.provider_picker.current_key()]
        ttype = self.type_combo.currentText()
        path = PROJECTS_DIR / slug
        mode = (
            "recreate" if self.mode_recreate.isChecked()
            else "existing" if self.mode_existing.isChecked()
            else "scratch"
        )

        lines = [
            f"Nombre:    {name}",
            f"Slug:      {slug}",
            f"Ruta:      {path}",
            f"Tipo:      {ttype}",
            f"Agente:    {agent['name']}  →  {agent['command']}",
            f"Modo:      {mode}",
        ]
        if mode == "existing":
            lines.append(f"Repo:      {self._current_repo_id() or '(falta)'}")
            lines.append(f"Stack:     (detectado del repo, no se hace scaffolding)")
        else:
            lines.append(f"Stack:     {stack['name']}  ({stack['min_version']})")
            if self.github_create_check.isChecked() and self._github_user:
                lines.append(f"GH:        crear {self._github_user}/{slug} (privado) al terminar")
        if mode == "recreate":
            ref_kind = self.ref_kind_combo.currentData()
            ref_val = self.ref_path_edit.text().strip()
            lines.append(f"Referencia [{ref_kind}]: {ref_val or '(falta)'}")
        if self.licensing_check.isChecked():
            try:
                from licensing_scaffold import detect_family
                fam = detect_family(stack_key) or "—"
                lines.append(f"licensing: ON (slug={slug}, family={fam})")
                if self.licensing_gh_check.isChecked():
                    lines.append(f"           + gh repo create <org>/{slug}")
                if self.licensing_force_check.isChecked():
                    lines.append(f"           + forzado en adopt/existing")
            except Exception:
                lines.append("licensing: ON")
        self.preview.setText("\n".join(lines))

    def create_project(self):
        mode = (
            "recreate" if self.mode_recreate.isChecked()
            else "existing" if self.mode_existing.isChecked()
            else "adopt" if self.mode_adopt.isChecked()
            else "scratch"
        )

        name = self.name_edit.text().strip()
        # Slug. En modo "existing" NO se pide nombre: se usa el de la repo.
        if mode == "existing":
            repo_id = self._current_repo_id()
            if not repo_id or "/" not in repo_id:
                QMessageBox.warning(self, "ThemeForge", "Pick or type a repo as owner/name.")
                return
            slug = repo_id.split("/")[-1]
            if not name:
                name = slug  # nombre del proyecto = nombre de la repo
        else:
            if not name:
                QMessageBox.warning(self, "ThemeForge", "Pon un nombre.")
                return
            slug = slugify(name)

        project_dir = PROJECTS_DIR / slug
        if project_dir.exists() and any(project_dir.iterdir()):
            r = QMessageBox.question(
                self, "Carpeta no vacía",
                f"{project_dir} ya existe y tiene contenido.\n"
                "Los scaffoldings y `gh repo clone` FALLARÁN si no está vacía.\n"
                "¿Continuar igualmente?",
            )
            if r != QMessageBox.StandardButton.Yes:
                return

        stack_key = self._stack_key if mode not in ("existing", "adopt") else "none"
        ttype = self.type_combo.currentText()
        tniche = self.niche_combo.currentText().strip()
        agent_key = self.provider_picker.current_key()
        run_autoskills = self.autoskills_check.isChecked()
        run_uipro = self.uipro_check.isChecked()
        ref_kind = self.ref_kind_combo.currentData() if mode == "recreate" else None
        ref_val = self.ref_path_edit.text().strip() if mode == "recreate" else None
        existing_repo = self._current_repo_id() if mode == "existing" else None
        adopt_src = self.adopt_path_edit.text().strip() if mode == "adopt" else None
        create_gh = self.github_create_check.isChecked() and bool(self._github_user)

        if mode == "recreate":
            if not ref_val:
                QMessageBox.warning(self, "ThemeForge", "Indica la referencia.")
                return
            if ref_kind == "folder" and not Path(ref_val).is_dir():
                QMessageBox.warning(self, "ThemeForge", f"Folder does not exist:\n{ref_val}")
                return
            if ref_kind == "zip" and not (Path(ref_val).is_file() and ref_val.lower().endswith(".zip")):
                QMessageBox.warning(self, "ThemeForge", "El .zip no existe o no es un .zip.")
                return
            if ref_kind == "url" and not re.match(r"^https?://", ref_val):
                QMessageBox.warning(self, "ThemeForge", "La URL debe empezar por http:// o https://")
                return
        elif mode == "adopt":
            if not adopt_src or not Path(adopt_src).is_dir():
                QMessageBox.warning(self, "ThemeForge", f"Folder to adopt does not exist:\n{adopt_src}")
                return

        # ── Red de seguridad: stack WordPress sin análisis IA ───────────
        # Si la referencia es un theme/plugin de WordPress y el usuario no
        # eligió el stack a mano, lo fijamos a WordPress aquí también (por si
        # no pasó por el browse/editingFinished). Así la auto-instalación de
        # WP en Docker funciona aunque no se haya analizado con IA.
        if (mode == "recreate" and not self._stack_manually_set
                and ref_kind in ("folder", "zip") and ref_val
                and stack_key not in _FORMAT_WORDPRESS):
            try:
                from reference_analyzer import detect_wordpress_stack
                _wp = detect_wordpress_stack(Path(ref_val))
            except Exception:
                _wp = None
            if _wp:
                stack_key = _wp
                self._stack_key = _wp
                self._refresh_stack_button()

        # ── Provisión automática de BD ─────────────────────────────────
        # Solo aplica en modo "existing": el repo clonado puede ya tener
        # drizzle.config.ts / prisma. Para "scratch" la BD se detectará
        # cuando el scaffold genere los archivos, pero eso es más complejo;
        # de momento solo aprovisionamos cuando el repo existente lo pide.
        db_prov = None
        if mode == "existing" and project_dir.exists():
            try:
                from db_provisioner import detect_db_kind, provision_postgres_for, docker_available
                # Clonamos primero a tmp para inspeccionar drizzle/prisma — no
                # podemos detectar en project_dir aún porque está vacío. Como
                # alternativa simple, detectamos tras el clone en el propio
                # script (ver bloque más abajo).
                # Aquí pre-aprovisionamos asumiendo Postgres si el repo
                # remoto tiene drizzle.config.ts (lo comprobamos vía gh).
                pass
            except Exception:
                pass

        # Para "scratch" sí podemos saber por el stack (Laravel + Postgres,
        # Next + drizzle, etc.). Más adelante. Por ahora solo "existing"
        # via detección POST-clone embebida en el setup.

        force_postgres = self.postgres_check.isChecked()
        is_licensed = self.licensing_check.isChecked()
        licensing_gh = is_licensed and self.licensing_gh_check.isChecked()
        licensing_force_all = is_licensed and self.licensing_force_check.isChecked()

        # Análisis IA inyectable. Tres caminos:
        #   recreate/adopt → path-gated (debe coincidir con la ref activa).
        #   scratch        → vibe scaffolder (cached_path is None means "vibe").
        ai_analysis_text = None
        if self._last_analysis:
            cached_path, cached_text = self._last_analysis
            if mode == "recreate" and cached_path == (ref_val or ""):
                ai_analysis_text = cached_text
            elif mode == "adopt" and cached_path == (adopt_src or ""):
                ai_analysis_text = cached_text
            elif mode == "scratch" and cached_path is None:
                # Vibe scaffolder dev_prompt
                ai_analysis_text = cached_text

        # ── Runtimes del stack (PHP/Java/Rust/Go/Bun/Deno/Python/Ruby…) ──
        # Si el stack elegido necesita un runtime que NO está instalado,
        # ofrecemos abrir el wizard para instalarlo antes de scaffoldear
        # (si no, create-next-app/composer/etc. fallaría en el setup).
        try:
            import dependency_setup as _ds
            _missing = _ds.missing_tools_for_stack(stack_key)
            if _missing:
                _names = ", ".join(t.name for t in _missing)
                _r = QMessageBox.question(
                    self, "Faltan runtimes para este stack",
                    f"El stack «{stack_key}» necesita: {_names}.\n\n"
                    f"No están instalados. ¿Abrir el wizard de dependencias "
                    f"para instalarlos ahora?\n\n"
                    f"(Si continúas sin ellos, el scaffold avisará y se "
                    f"detendrá.)",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                )
                if _r == QMessageBox.StandardButton.Cancel:
                    return
                if _r == QMessageBox.StandardButton.Yes:
                    from dependency_wizard import DependencyWizard
                    DependencyWizard(self).exec()
        except Exception as _e:
            print(f"[deps] check stack runtimes: {_e}", file=sys.stderr)

        try:
            setup = write_setup_script(
                project_dir, stack_key, ttype, name, agent_key, run_autoskills,
                mode, ref_kind, ref_val, existing_repo, create_gh, self._github_user,
                db_provision=db_prov,
                force_postgres=force_postgres,
                adopt_src=adopt_src,
                ai_analysis=ai_analysis_text,
                ai_analysis_kind=getattr(self, "_last_analysis_kind", "reference"),
                is_licensed_product=is_licensed,
                licensing_create_gh_repo=licensing_gh,
                licensing_force_all_modes=licensing_force_all,
                run_uipro=run_uipro,
                niche=tniche,
            )
        except Exception as e:
            QMessageBox.critical(self, "Error generando setup", str(e))
            return

        # En modo "existing" el `gh repo clone` quiere crear la carpeta
        # él mismo. Si la creamos vacía antes, ProjectWindow se abre
        # mostrando el árbol vacío y el setup la borra/recrea con git
        # historia intacta. Si no, esperamos a que el setup la cree.
        if mode == "existing":
            project_dir.mkdir(parents=True, exist_ok=True)

        # Pre-configurar MCP servers para Claude Code / Cursor / Windsurf.
        # Drop `.mcp.json` con un set curado relevante al stack. El user
        # puede deshabilitar el toggle desde Setup sub-tab.
        if getattr(self, "mcp_check", None) and self.mcp_check.isChecked():
            try:
                import mcp_catalog as _mc
                project_dir.mkdir(parents=True, exist_ok=True)
                stack_meta = STACKS.get(stack_key, {})
                recs = _mc.recommend_for_stack(stack_key, stack_meta)
                # Import de Figma → asegurar el MCP figma-context aunque el
                # stack no lo recomiende por relevancia (el agente lo necesita
                # para leer el diseño).
                if (mode == "recreate"
                        and self.ref_kind_combo.currentData() == "figma"
                        and not any(getattr(e, "key", "") == "figma-context" for e in recs)):
                    _fig = next((e for e in _mc.CATALOG if e.key == "figma-context"), None)
                    if _fig:
                        recs.append(_fig)
                _mc.write_mcp_json(project_dir, recs)
            except Exception as e:
                print(f"[mcp] could not write .mcp.json: {e}", file=sys.stderr)

        # Crear la carpeta del proyecto ANTES de abrir el terminal: éste
        # arranca con cwd=project_dir, y node-pty (Windows) falla si el cwd
        # no existe. El setup script hace `mkdir -p` igualmente (idempotente);
        # en modo existing el setup borra la carpeta vacía antes de `gh clone`.
        try:
            project_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        # Abrir el ProjectWindow embebiendo el setup en su primera pestaña
        # de terminal en lugar de lanzar una Konsole externa.
        try:
            # as_posix() → forward slashes; el wrapper hace `bash <ruta>` y
            # en git-bash (Windows) los backslashes romperían la ruta.
            open_project_window(project_dir, initial_cmd=setup.as_posix(), provider_key=agent_key)
        except Exception as e:
            QMessageBox.critical(self, "Error lanzando ProjectWindow", str(e))
            return

        self.name_edit.clear()
        self.name_edit.setFocus()


class GalleryPanel(QWidget):
    """Lista los proyectos creados y permite continuarlos con el agente AI."""

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        header = QLabel(f"Templates en <code>{PROJECTS_DIR}</code>")
        header.setTextFormat(Qt.TextFormat.RichText)

        # Búsqueda + filtros
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filtrar por nombre / stack…")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.fav_only = QCheckBox("Solo favoritos ★")
        self.fav_only.toggled.connect(self._apply_filter)
        # Filtro opcional aportado por el plugin privado (ausente en OSS).
        self.leads_only = _np.make_gallery_filter(self) if _np else None
        self.show_archived = QCheckBox("📦 Archivados")
        self.show_archived.setToolTip(
            f"Mostrar proyectos archivados (movidos a {ARCHIVE_DIR}). "
            "Los archivados son reversibles: restáuralos con ↩️ y "
            "vuelven a PROJECTS_DIR."
        )
        self.show_archived.toggled.connect(self._toggle_archive_view)
        self.cat_filter = QComboBox()
        self.cat_filter.addItem("Todas las categorías", userData="*")
        for cat in sorted({s.get("category", "") for s in STACKS.values()}):
            if cat:
                self.cat_filter.addItem(cat, userData=cat)
        self.cat_filter.currentIndexChanged.connect(self._apply_filter)

        # Toggle vista lista / cards. Estado persistido en QSettings
        # (no añadimos otro archivo de config para algo tan pequeño).
        from PyQt6.QtCore import QSettings
        self._settings = QSettings("themeforge", "themeforge")
        self.view_toggle = QPushButton("🖼️ Cards")
        self.view_toggle.setCheckable(True)
        saved_mode = self._settings.value("gallery/view_mode", "list", type=str)
        self.view_toggle.setChecked(saved_mode == "cards")
        self.view_toggle.setToolTip(
            "Alternar entre vista lista (rápido + denso) y cards "
            "(thumbnails grandes, visual). El thumbnail viene del "
            "screenshot capturado con 📸 en ProjectWindow; si no hay, "
            "se genera un placeholder con el color del stack."
        )
        self.view_toggle.toggled.connect(self._on_view_mode_changed)

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.search_edit, 2)
        filter_row.addWidget(self.cat_filter, 1)
        filter_row.addWidget(self.fav_only)
        if self.leads_only is not None:
            filter_row.addWidget(self.leads_only)
        filter_row.addWidget(self.show_archived)
        filter_row.addWidget(self.view_toggle)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(lambda _i: self._open_project_window())
        self.list_widget.currentItemChanged.connect(self._on_select)
        self._apply_view_mode(self.view_toggle.isChecked())

        self.info = QLabel("Selecciona un template (doble-click abre la ventana del proyecto)")
        self.info.setStyleSheet("color:#888;")

        self.btn_refresh = QPushButton("↻ Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_fav = QPushButton("★ Favorito")
        self.btn_fav.setToolTip("Marcar/desmarcar como favorito")
        self.btn_fav.clicked.connect(self._toggle_favorite)
        self.btn_tags = QPushButton("🏷️ Tags…")
        self.btn_tags.setToolTip(
            "Editar tags del proyecto seleccionado. Separa por comas. "
            "Filtra escribiendo `tag:nombre` en la barra de búsqueda."
        )
        self.btn_tags.clicked.connect(self._edit_tags)
        self.btn_archive = QPushButton("📦 Archivar")
        self.btn_archive.setToolTip(
            f"Mover el proyecto seleccionado a {ARCHIVE_DIR}. "
            "Reversible — usa el checkbox 📦 Archivados arriba y "
            "luego ↩️ Restaurar."
        )
        self.btn_archive.clicked.connect(self._toggle_archive_project)
        self.btn_regen = QPushButton("🔄 Regenerar contexto")
        self.btn_regen.setToolTip("Regenera CLAUDE.md / AGENTS.md con los MDs actuales del builder")
        self.btn_regen.clicked.connect(self._regenerate_context)
        self.btn_folder = QPushButton("Abrir carpeta")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_vscode = QPushButton("VSCode")
        self.btn_vscode.clicked.connect(self._open_vscode)
        self.btn_codex = QPushButton("Codex")
        self.btn_codex.clicked.connect(lambda: self._open_with("codex"))
        self.btn_claude = QPushButton("Claude Code")
        self.btn_claude.clicked.connect(lambda: self._open_with("claude"))
        self.btn_project = QPushButton("📺 Abrir proyecto (preview)")
        self.btn_project.setStyleSheet("font-weight:bold;")
        self.btn_project.clicked.connect(self._open_project_window)
        # Hermes — OPCIONAL: solo visible si Hermes está instalado.
        self.btn_operator = QPushButton("🤖 Hermes")
        self.btn_operator.setToolTip("Automatizar este proyecto con Hermes "
                                     "— opcional")
        self.btn_operator.clicked.connect(self._automate_with_operator)
        try:
            from hermes_panel import hermes_available
            self.btn_operator.setVisible(hermes_available())
        except Exception:
            self.btn_operator.setVisible(False)
        self.btn_delete = QPushButton("🗑️ Eliminar")
        self.btn_delete.setToolTip(
            "Eliminar el proyecto del disco completamente: directorio, "
            "container Postgres asociado, volumen de datos, entrada en "
            "ports.json y favoritos. IRREVERSIBLE."
        )
        self.btn_delete.setStyleSheet("color:#ed1c57;")
        self.btn_delete.clicked.connect(self._delete_project)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_refresh)
        btns.addWidget(self.btn_fav)
        btns.addWidget(self.btn_tags)
        btns.addWidget(self.btn_archive)
        btns.addWidget(self.btn_regen)
        btns.addWidget(self.btn_delete)
        btns.addStretch()
        btns.addWidget(self.btn_folder)
        btns.addWidget(self.btn_vscode)
        btns.addWidget(self.btn_codex)
        btns.addWidget(self.btn_claude)
        btns.addWidget(self.btn_operator)
        btns.addWidget(self.btn_project)

        root = QVBoxLayout()
        root.addWidget(header)
        root.addLayout(filter_row)
        root.addWidget(self.list_widget)
        root.addWidget(self.info)
        root.addLayout(btns)
        self.setLayout(root)

    def refresh(self):
        self.favorites = load_favorites()
        self.projects_meta = load_projects_meta()
        # Marcas opcionales del plugin privado (webs generadas desde el CRM).
        self._lead_slugs = _np.gallery_marks() if _np else set()
        self.list_widget.clear()
        archived_view = (self.show_archived.isChecked()
                         if hasattr(self, "show_archived") else False)
        items = list_projects(archived=archived_view)
        self._all_items = []
        cards_mode = self.view_toggle.isChecked() if hasattr(self, "view_toggle") else False
        from PyQt6.QtGui import QIcon
        for it in items:
            dt = datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d %H:%M") if it["mtime"] else "?"
            git_mark = "git ✓" if it["has_git"] else "git —"
            ctx_mark = "claude.md" if it["has_claude"] else ("agents.md" if it["has_agents"] else "—")
            star = "★ " if it["name"] in self.favorites else "☆ "
            pm_entry = self.projects_meta.get(it["name"]) or {}
            tags = pm_entry.get("tags") or []
            tags_str = "  ·  " + " ".join(f"#{t}" for t in tags) if tags else ""
            # Marca opcional (plugin privado); sin plugin siempre False.
            slug = it["name"]
            from_lead = _np.item_marked(pm_entry, slug, getattr(self, "_lead_slugs", set())) if _np else False
            lead_mark = "🎯 " if from_lead else ""
            ai_ts = last_ai_activity(it["path"])
            ai_rel = format_relative_time(ai_ts)
            ai_mark = f"🤖 {ai_rel}" if ai_ts else "🤖 sin sesiones"

            if cards_mode:
                # En vista cards el espacio para texto es estrecho; resumen
                # de 2-3 líneas: nombre, stack, IA + tags (si hay).
                tags_line = " ".join(f"#{t}" for t in tags[:3])
                if len(tags) > 3:
                    tags_line += f"  +{len(tags)-3}"
                meta_line = f"{ai_mark}"
                if tags_line:
                    meta_line += f"  {tags_line}"
                line = f"{star}{lead_mark}{it['name']}\n{it['stack']}\n{meta_line}"
            else:
                line = (f"{star}{lead_mark}{it['name']}\n"
                        f"     Stack: {it['stack']:<22}  ·  Mod: {dt}  ·  "
                        f"{git_mark}  ·  {ctx_mark}  ·  {ai_mark}{tags_str}")

            li = QListWidgetItem(line)
            li.setData(Qt.ItemDataRole.UserRole, str(it["path"]))
            li.setData(Qt.ItemDataRole.UserRole + 1, it)   # meta para filtro
            li.setData(Qt.ItemDataRole.UserRole + 2, tags) # tags para filtro
            li.setData(Qt.ItemDataRole.UserRole + 3, from_lead)  # marca del plugin

            if cards_mode:
                stack_key = detected_stack_to_key(it["stack"])
                pm = get_or_make_thumbnail(it["name"], stack_key, it["name"])
                li.setIcon(QIcon(pm))

            self.list_widget.addItem(li)
            self._all_items.append(li)
        self.info.setText(f"{len(items)} templates encontrados.")
        self._apply_filter()

    def _apply_filter(self):
        text = (self.search_edit.text() if hasattr(self, 'search_edit') else "").strip().lower()
        cat = self.cat_filter.currentData() if hasattr(self, 'cat_filter') else "*"
        only_fav = self.fav_only.isChecked() if hasattr(self, 'fav_only') else False
        only_leads = bool(getattr(self, 'leads_only', None) and self.leads_only.isChecked())

        # Si el search empieza con "tag:foo" → filtro por tag (igualdad
        # exacta del tag tras el prefijo, en lowercase). Se pueden
        # encadenar varios separados por espacio: "tag:venta tag:aurora".
        tag_filters: list[str] = []
        text_clean = text
        if "tag:" in text_clean:
            tokens = text_clean.split()
            tag_filters = [t[4:].strip().lstrip("#") for t in tokens if t.startswith("tag:")]
            text_clean = " ".join(t for t in tokens if not t.startswith("tag:")).strip()

        visible = 0
        for li in getattr(self, '_all_items', []):
            meta = li.data(Qt.ItemDataRole.UserRole + 1) or {}
            tags = li.data(Qt.ItemDataRole.UserRole + 2) or []
            from_lead = bool(li.data(Qt.ItemDataRole.UserRole + 3))
            name = (meta.get("name") or "").lower()
            stack = (meta.get("stack") or "").lower()
            stack_key = detected_stack_to_key(meta.get("stack") or "")
            stack_cat = STACKS.get(stack_key, {}).get("category", "")
            show = True
            if text_clean and text_clean not in name and text_clean not in stack:
                show = False
            if cat and cat != "*" and stack_cat != cat:
                show = False
            if only_fav and meta.get("name") not in self.favorites:
                show = False
            if only_leads and not from_lead:
                show = False
            if tag_filters and not all(tf in tags for tf in tag_filters):
                show = False
            li.setHidden(not show)
            if show: visible += 1
        if hasattr(self, 'info'):
            total = len(getattr(self, '_all_items', []))
            tag_note = f" · tag:{','.join(tag_filters)}" if tag_filters else ""
            fav_note = " · solo favoritos" if only_fav else ""
            mark_note = " · 🎯 filtro activo" if only_leads else ""
            self.info.setText(
                f"{visible} / {total} visibles{tag_note}{fav_note}{mark_note}")

    def _selected_path(self) -> Path | None:
        item = self.list_widget.currentItem()
        if not item:
            return None
        return Path(item.data(Qt.ItemDataRole.UserRole))

    def _on_select(self, current, _prev):
        if not current:
            self.info.setText("Selecciona un template")
            return
        p = Path(current.data(Qt.ItemDataRole.UserRole))
        self.info.setText(f"→ {p}")

    def _open_with(self, command: str):
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Gallery", "Pick a template first.")
            return
        if not shutil.which(command):
            QMessageBox.warning(self, "Missing command", f"`{command}` not found on PATH.")
            return
        # Build full argv: claude → ["claude", "--dangerously-skip-permissions"].
        # Others stay as-is. Quote shell-safely when joining.
        argv = aip.interactive_argv_for_binary(command)
        cmd_str = " ".join(shlex.quote(a) for a in argv)
        if pc.open_in_terminal(p, command=cmd_str) is None:
            QMessageBox.critical(self, "No terminal",
                                 "No supported terminal emulator found.")

    def _open_folder(self):
        p = self._selected_path()
        if not p: return
        if pc.open_in_file_manager(p) is None:
            QMessageBox.warning(self, "Folder",
                                "No encuentro un file manager en el sistema.")

    def _open_vscode(self):
        p = self._selected_path()
        if not p: return
        if pc.IS_LINUX:
            for cmd in ("code", "codium", "code-oss"):
                if shutil.which(cmd):
                    subprocess.Popen([cmd, str(p)])
                    return
        argv = pc.vscode_argv(p)
        if argv:
            subprocess.Popen(argv)
            return
        QMessageBox.warning(self, "VSCode", "No encuentro VS Code instalado.")

    def _open_project_window(self):
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Galería", "Selecciona primero un template.")
            return
        # Abrir desde galería → auto-ejecutar el agente con el contexto del tema.
        open_project_window(p, auto_agent=True)

    def _automate_with_operator(self):
        """Lanza Hermes sobre el proyecto seleccionado."""
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Galería", "Selecciona primero un template.")
            return
        try:
            from hermes_panel import HermesMissionDialog, hermes_available
            if not hermes_available():
                QMessageBox.information(
                    self, "Hermes",
                    "Instala Hermes Agent (opcional) para automatizar proyectos "
                    "con Hermes. Settings → 🔧 Setup dependencies → Hermes.")
                return
            HermesMissionDialog(p.name, p, self).exec()
        except Exception as e:
            QMessageBox.warning(self, "Hermes", f"Error: {e}")

    def _toggle_favorite(self):
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Favoritos", "Selecciona primero un template.")
            return
        name = p.name
        favs = load_favorites()
        if name in favs:
            favs.remove(name)
        else:
            favs.add(name)
        save_favorites(favs)
        self.refresh()

    def _apply_view_mode(self, cards: bool):
        """Configura QListWidget para modo cards o lista. No refresca
        — el caller debe llamar refresh() después si quiere regenerar
        items con thumbnails."""
        from PyQt6.QtWidgets import QListView
        from PyQt6.QtCore import QSize
        if cards:
            self.list_widget.setViewMode(QListView.ViewMode.IconMode)
            self.list_widget.setIconSize(QSize(THUMB_WIDTH, THUMB_HEIGHT))
            self.list_widget.setGridSize(QSize(THUMB_WIDTH + 24, THUMB_HEIGHT + 70))
            self.list_widget.setResizeMode(QListView.ResizeMode.Adjust)
            self.list_widget.setMovement(QListView.Movement.Static)
            self.list_widget.setWordWrap(True)
            self.list_widget.setSpacing(8)
            self.list_widget.setUniformItemSizes(True)
            self.view_toggle.setText("📋 Lista")
        else:
            self.list_widget.setViewMode(QListView.ViewMode.ListMode)
            self.list_widget.setSpacing(0)
            self.list_widget.setIconSize(QSize(0, 0))
            self.view_toggle.setText("🖼️ Cards")

    def _on_view_mode_changed(self, checked: bool):
        self._apply_view_mode(checked)
        self._settings.setValue("gallery/view_mode", "cards" if checked else "list")
        self.refresh()

    def _toggle_archive_view(self, checked: bool):
        """Alterna entre vista de proyectos activos y archivados.
        Cambia el botón Archivar↔Restaurar consecuentemente."""
        if checked:
            self.btn_archive.setText("↩️ Restaurar")
            self.btn_archive.setToolTip(
                f"Mover el proyecto archivado de vuelta a {PROJECTS_DIR}."
            )
        else:
            self.btn_archive.setText("📦 Archivar")
            self.btn_archive.setToolTip(
                f"Mover el proyecto a {ARCHIVE_DIR}. Reversible."
            )
        self.refresh()

    def _toggle_archive_project(self):
        """Archiva o restaura el proyecto seleccionado, según el modo
        de vista activo."""
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Archivar", "Selecciona primero un proyecto.")
            return
        slug = p.name
        archived = (self.show_archived.isChecked()
                    if hasattr(self, "show_archived") else False)
        if archived:
            # Restaurar
            r = QMessageBox.question(
                self, "Restaurar proyecto",
                f"¿Restaurar `{slug}` a {PROJECTS_DIR}?\n\n"
                "Pasará a aparecer de nuevo en la vista normal.",
            )
            if r != QMessageBox.StandardButton.Yes:
                return
            ok, msg = unarchive_project(slug)
        else:
            r = QMessageBox.question(
                self, "Archivar proyecto",
                f"¿Archivar `{slug}`?\n\n"
                f"Se moverá a {ARCHIVE_DIR}/{slug}.\n"
                "NO se borra nada — puedes restaurarlo cuando quieras\n"
                "marcando '📦 Archivados' arriba y pulsando ↩️ Restaurar.",
            )
            if r != QMessageBox.StandardButton.Yes:
                return
            ok, msg = archive_project(slug)
        if ok:
            self.info.setText(msg)
            self.refresh()
        else:
            QMessageBox.warning(self, "Archivar", msg)

    def _edit_tags(self):
        """Editar los tags del proyecto seleccionado. Input: lista
        separada por comas o espacios. Se persisten lowercased sin '#'.

        Para filtrar por tag, escribe `tag:foo` en la barra de búsqueda
        (encadenable: `tag:foo tag:bar` exige ambos)."""
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Tags", "Selecciona primero un template.")
            return
        slug = p.name
        current = get_project_tags(slug)
        from PyQt6.QtWidgets import QInputDialog
        default_text = ", ".join(current)
        text, ok = QInputDialog.getText(
            self, f"Tags — {slug}",
            "Tags separados por coma o espacio (sin '#'). Ej: "
            "venta-gumroad, demo-cliente-x, borrador.\n"
            "Vacío para borrar todos.",
            text=default_text,
        )
        if not ok:
            return
        # Aceptar comas o espacios como separador
        raw = [t for t in re.split(r"[,\s]+", text) if t.strip()]
        set_project_tags(slug, raw)
        self.refresh()

    def _delete_project(self):
        """Borra el proyecto del disco + container Postgres + volumen +
        entradas en ports.json, db_provisions.json y favoritos. Acción
        IRREVERSIBLE — pide confirmación explícita con nombre."""
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Eliminar", "Selecciona primero un proyecto.")
            return
        slug = p.name
        # Calcular qué se va a borrar para listarlo en el diálogo de
        # confirmación.
        items = []
        # 1) directorio
        try:
            size_mb = sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) // (1024 * 1024)
        except Exception:
            size_mb = 0
        items.append(f"📁 Directorio <code>{p}</code> ({size_mb} MB aprox)")
        # 2) Postgres provisionado
        db_info = None
        try:
            from db_provisioner import get_provision
            db_info = get_provision(slug)
        except Exception:
            pass
        if db_info:
            items.append(
                f"🐘 Container Postgres <code>{db_info['container']}</code> "
                f"(puerto {db_info['port']})"
            )
            items.append(f"💾 Volumen Docker <code>{db_info['volume']}</code> (datos de BD)")
        # 3) puerto preview
        try:
            from preview import PORTS_FILE
            ports = json.loads(PORTS_FILE.read_text(encoding="utf-8")) if PORTS_FILE.exists() else {}
            if slug in ports:
                items.append(f"🔌 Entrada en <code>ports.json</code> (puerto preview)")
        except Exception:
            pass
        # 4) favorito
        try:
            favs = load_favorites()
            if slug in favs:
                items.append(f"⭐ Marca de favorito")
        except Exception:
            pass

        items_plain = "\n".join(
            '  · ' + x.replace('<code>', '').replace('</code>', '').replace('<br>', '')
            for x in items
        )
        reply = QMessageBox.question(
            self, f"Eliminar «{slug}»",
            f"¿Eliminar el proyecto «{slug}»?\n\n{items_plain}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        errors = []
        # 1) Container + volumen Postgres explícito
        if db_info:
            try:
                from db_provisioner import cleanup_for
                cleanup_for(slug, also_volume=True)
            except Exception as e:
                errors.append(f"db cleanup: {e}")
        # 2) Otros containers con bind-mount al directorio del proyecto
        #    (e.g. meilisearch, redis, etc. que docker-compose haya
        #    levantado y dejado archivos como root).
        try:
            killed = _stop_containers_using_path(p)
            if killed:
                print(f"[delete] parados/eliminados {len(killed)} containers con mount al proyecto: {killed}")
        except Exception as e:
            errors.append(f"stop containers: {e}")
        # 3) Directorio — primer intento normal
        rmtree_failed = False
        try:
            shutil.rmtree(p)
        except Exception as e:
            rmtree_failed = True
            errors.append(f"rmtree {p}: {e}")
        # 4) Si falló por permisos (archivos creados por containers
        #    como root), ofrecer al user el comando con sudo.
        if rmtree_failed and p.exists():
            from PyQt6.QtWidgets import QInputDialog
            cmd = f"sudo rm -rf {shell_quote(str(p))}"
            reply = QMessageBox.question(
                self, "Permiso denegado al borrar",
                f"Algunos archivos están como root (probablemente containers "
                f"Docker que escribieron como root: meilisearch, mysql, etc.).\n\n"
                f"¿Quieres que ejecute con sudo?\n\n"
                f"<code>{cmd}</code>\n\n"
                f"Si dices SÍ se te pedirá la contraseña sudo en una terminal "
                f"externa (Konsole). Si dices NO, los datos siguen en disco "
                f"y los borras manualmente cuando quieras.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                # sudo interactivo necesita TTY → abrir terminal externa.
                # platform_compat se encarga del emulador por OS.
                full = (
                    f'echo "Ejecutando: {cmd}"; {cmd} && echo "" && '
                    f'echo "✓ Borrado completado. Pulsa Enter para cerrar." && read'
                )
                if pc.open_in_terminal(self._selected_path() or Path.home(),
                                       command=full, hold=True) is not None:
                    QMessageBox.information(
                        self, "Lanzado",
                        "Se abrió una terminal externa con sudo rm -rf. "
                        "Introduce tu contraseña ahí. Cuando termine, vuelve "
                        "aquí y pulsa ↻ Refrescar.",
                    )
                else:
                    QMessageBox.warning(
                        self, "Sin terminal externa",
                        f"No encuentro un emulador de terminal para ejecutar "
                        f"sudo interactivamente.\n\n"
                        f"Ejecuta manualmente:\n\n{cmd}",
                    )
        # 3) ports.json
        try:
            from preview import PORTS_FILE
            if PORTS_FILE.exists():
                ports = json.loads(PORTS_FILE.read_text(encoding="utf-8"))
                changed = False
                # Borrar la clave del slug y cualquier sub-clave "slug:..."
                for k in list(ports.keys()):
                    if k == slug or k.startswith(f"{slug}:"):
                        del ports[k]
                        changed = True
                if changed:
                    PORTS_FILE.write_text(json.dumps(ports, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as e:
            errors.append(f"ports.json: {e}")
        # 4) Favorito
        try:
            favs = load_favorites()
            if slug in favs:
                favs.remove(slug)
                save_favorites(favs)
        except Exception as e:
            errors.append(f"favorites: {e}")

        self.refresh()
        if errors:
            QMessageBox.warning(
                self, "Eliminado con errores",
                f"El proyecto «{slug}» se eliminó pero hubo errores:\n\n" + "\n".join(errors),
            )
        else:
            QMessageBox.information(
                self, "Eliminado",
                f"✓ Proyecto «{slug}» eliminado completamente.",
            )

    def _regenerate_context(self):
        p = self._selected_path()
        if not p:
            QMessageBox.warning(self, "Galería", "Selecciona primero un template.")
            return

        # Detectar stack y mapear a key
        detected = detect_stack(p)
        stack_key = detected_stack_to_key(detected)

        # Decidir qué archivos regenerar (los que existan; si no existe ninguno,
        # creamos CLAUDE.md por defecto).
        targets = []
        if (p / "CLAUDE.md").exists(): targets.append(("CLAUDE.md", "claude"))
        if (p / "AGENTS.md").exists(): targets.append(("AGENTS.md", "codex"))
        if not targets:
            targets.append(("CLAUDE.md", "claude"))

        # Hacer backup de los actuales
        backed_up = []
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        for filename, _ in targets:
            f = p / filename
            if f.exists():
                bak = p / f"{filename}.bak.{ts}"
                try:
                    bak.write_bytes(f.read_bytes())
                    backed_up.append(bak.name)
                except Exception:
                    pass

        # Regenerar (modo scratch, tipo "Sin tipo" para no sesgar). El usuario
        # puede ejecutar el agente y darle objetivos concretos directamente.
        body = render_context(
            stack_key=stack_key,
            template_type="(Sin tipo — detectar de la referencia)",
            project_name=p.name,
            mode="scratch",
            reference_kind=None,
            reference_value=None,
            existing_repo=None,
        )

        wrote = []
        for filename, _agent in targets:
            try:
                (p / filename).write_text(body, encoding="utf-8")
                wrote.append(filename)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"No se pudo escribir {filename}:\n{e}")

        if wrote:
            QMessageBox.information(
                self, "Regenerado",
                f"Stack detectado: {detected} → {stack_key}\n"
                f"Escritos: {', '.join(wrote)}\n"
                f"Backups: {', '.join(backed_up) if backed_up else '(ninguno)'}",
            )
            self.refresh()


class _CommandPalette(QDialog):
    """Paleta de comandos estilo VSCode (Ctrl+K).

    Filtra fuzzy entre las acciones registradas y al pulsar Enter
    ejecuta la callback. Cerrar con Esc.

    Cada acción es una tupla: (label, category, callback).
    El filtro hace match contra label + category (substring case-insensitive
    + score por orden de aparición de los chars del query en el label).
    """

    def __init__(self, parent, actions: list[tuple[str, str, object]]):
        super().__init__(parent)
        self.setWindowTitle("Paleta de comandos")
        self.setModal(True)
        self.resize(620, 460)
        # Sin marco para look "spotlight". Si molesta, quitar esta línea.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setStyleSheet(
            "QDialog { background:#1a1d24; border:1px solid #3a3f4d; "
            "border-radius:10px; }"
        )

        self._actions = actions
        self._filtered: list[tuple[str, str, object]] = list(actions)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Escribe para buscar… (Esc para cerrar)")
        self.search.setStyleSheet(
            "QLineEdit { background:#0f1115; color:#e6e9ef; "
            "border:1px solid #232838; border-radius:6px; padding:10px 14px; "
            "font-size:15px; }"
        )
        self.search.textChanged.connect(self._on_filter)

        self.results = QListWidget()
        self.results.setStyleSheet(
            "QListWidget { background:#1a1d24; color:#e6e9ef; "
            "border:none; padding:6px; font-size:14px; }"
            "QListWidget::item { padding:8px 10px; border-radius:6px; }"
            "QListWidget::item:selected { background:#2a3548; color:#fff; }"
        )
        self.results.itemActivated.connect(self._run_selected)

        hint = QLabel("↑↓ navegar  ·  Enter ejecutar  ·  Esc cerrar")
        hint.setStyleSheet("color:#888; font-size:11px; padding:6px 8px;")

        lay = QVBoxLayout()
        lay.setContentsMargins(12, 12, 12, 8)
        lay.addWidget(self.search)
        lay.addWidget(self.results)
        lay.addWidget(hint)
        self.setLayout(lay)

        self._render(self._actions)
        self.search.setFocus()

    def _on_filter(self, text: str):
        q = (text or "").strip().lower()
        if not q:
            self._render(self._actions)
            return
        # Match: substring sobre "label + category". Score = posición del
        # match (menor = mejor) + bonus si el label empieza por la query.
        scored = []
        for label, category, cb in self._actions:
            hay = (label + " " + category).lower()
            idx = hay.find(q)
            if idx < 0:
                # Fallback: si el query es multi-palabra, exigir que todas
                # aparezcan al menos como substring (cualquier orden)
                parts = q.split()
                if len(parts) > 1 and all(p in hay for p in parts):
                    scored.append((100 + len(parts), label, category, cb))
                continue
            bonus = 0 if hay.startswith(q) else 50
            scored.append((idx + bonus, label, category, cb))
        scored.sort(key=lambda x: x[0])
        self._render([(l, c, cb) for _, l, c, cb in scored])

    def _render(self, items):
        self.results.clear()
        self._filtered = list(items)
        for label, category, _cb in items[:200]:  # cap visual
            item = QListWidgetItem(f"{label}\n   {category}")
            self.results.addItem(item)
        if items:
            self.results.setCurrentRow(0)

    def _run_selected(self, item):
        row = self.results.row(item)
        if 0 <= row < len(self._filtered):
            _label, _cat, cb = self._filtered[row]
            self.accept()
            # Ejecutar DESPUÉS de cerrar para que el cb pueda abrir
            # diálogos modales sin chocar con esta paleta.
            QTimer.singleShot(0, cb)

    def keyPressEvent(self, e):
        from PyQt6.QtCore import Qt as _Qt
        if e.key() in (_Qt.Key.Key_Down,):
            row = self.results.currentRow()
            self.results.setCurrentRow(min(row + 1, self.results.count() - 1))
            e.accept(); return
        if e.key() in (_Qt.Key.Key_Up,):
            row = self.results.currentRow()
            self.results.setCurrentRow(max(row - 1, 0))
            e.accept(); return
        if e.key() in (_Qt.Key.Key_Return, _Qt.Key.Key_Enter):
            item = self.results.currentItem()
            if item:
                self._run_selected(item)
            e.accept(); return
        if e.key() == _Qt.Key.Key_Escape:
            self.reject(); return
        super().keyPressEvent(e)


class _CostTrackerPanel(QWidget):
    """Panel agregado de uso/coste de IAs.

    Lee de cada provider conocido (Claude Code, Codex, …) sus
    sesiones persistidas y calcula coste con tarifas embebidas en
    `cost_tracker.PRICING`. La UI muestra:

      · Header con totales (all-time, mes en curso, últimos 30 días).
      · Tabla por proveedor.
      · Tabla por modelo (top N).
      · Tabla por proyecto (top N).
      · Mini bar chart de los últimos 30 días.
      · Estado de cada scanner (instalado / no soportado).
    """

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.header_lbl = QLabel("Cargando…")
        self.header_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.header_lbl.setStyleSheet("padding:8px 0;")

        self.provider_filter = QComboBox()
        self.provider_filter.addItem("Todos los proveedores", userData=None)
        for p in ("claude", "codex", "gemini", "opencode"):
            self.provider_filter.addItem(p, userData=p)
        self.provider_filter.currentIndexChanged.connect(lambda _i: self.refresh())

        self.btn_refresh = QPushButton("↻ Re-scan")
        self.btn_refresh.clicked.connect(self.refresh)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Filtrar por:"))
        top_row.addWidget(self.provider_filter)
        top_row.addStretch()
        top_row.addWidget(self.btn_refresh)

        # Tres tablas: by_provider, by_model, by_project
        self.table_providers = self._make_table(
            ["Provider", "Cost", "Events", "Tokens in", "Tokens out", "Notes"],
            [160, 100, 80, 110, 110, -1])
        self.table_models = self._make_table(
            ["Model", "Cost", "Events", "Tokens in", "Tokens out", "Pricing"],
            [220, 100, 80, 110, 110, 100])
        self.table_projects = self._make_table(
            ["Project", "Cost", "Events", "Provider"],
            [430, 100, 80, 100])

        # 3 charts QtCharts (mejor look + animations + hover):
        #   1. Donut: coste por proveedor (top-level breakdown).
        #   2. H-bar: top 10 proyectos.
        #   3. V-bar stacked: últimos 30 días, segmentado por proveedor.
        from PyQt6.QtCharts import QChartView
        from PyQt6.QtGui import QPainter as _QPainter
        self.chart_donut = QChartView()
        self.chart_donut.setRenderHint(_QPainter.RenderHint.Antialiasing)
        self.chart_donut.setMinimumHeight(280)

        self.chart_projects = QChartView()
        self.chart_projects.setRenderHint(_QPainter.RenderHint.Antialiasing)
        self.chart_projects.setMinimumHeight(280)

        self.chart_daily = QChartView()
        self.chart_daily.setRenderHint(_QPainter.RenderHint.Antialiasing)
        self.chart_daily.setMinimumHeight(220)

        # Notas / estado de scanners
        self.scanners_lbl = QLabel("")
        self.scanners_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.scanners_lbl.setStyleSheet("color:#9ca3af; padding:6px 0; font-size:12px;")
        self.scanners_lbl.setWordWrap(True)

        # Layout:
        #   Fila 1: header (totales)
        #   Fila 2: filtro + refresh
        #   Fila 3: [donut por proveedor] | [h-bar top proyectos]
        #   Fila 4: bar stacked 30 días (full width)
        #   Fila 5: tabla por modelo (más detalle del top 10)
        #   Fila 6: estado scanners
        root = QVBoxLayout()
        root.addLayout(top_row)
        root.addWidget(self.header_lbl)

        charts_row = QHBoxLayout()
        charts_row.addWidget(self.chart_donut, 1)
        charts_row.addWidget(self.chart_projects, 1)
        root.addLayout(charts_row)

        root.addWidget(self.chart_daily)

        root.addWidget(QLabel("<b>Por modelo</b>  (top 10)"))
        root.addWidget(self.table_models)

        # Mantenemos las dos tablas en una fila plegable abajo
        bottom_tables = QHBoxLayout()
        provs_box = QVBoxLayout()
        provs_box.addWidget(QLabel("<b>Por proveedor</b>"))
        provs_box.addWidget(self.table_providers)
        proj_box = QVBoxLayout()
        proj_box.addWidget(QLabel("<b>Por proyecto</b>  (detalle)"))
        proj_box.addWidget(self.table_projects)
        bottom_tables.addLayout(provs_box, 1)
        bottom_tables.addLayout(proj_box, 1)
        root.addLayout(bottom_tables)

        root.addWidget(self.scanners_lbl)
        self.setLayout(root)

    def _make_table(self, headers: list[str], widths: list[int]) -> QTableWidget:
        from PyQt6.QtWidgets import QTableWidget, QHeaderView
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        for i, w in enumerate(widths):
            if w > 0:
                t.setColumnWidth(i, w)
            else:
                t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        t.setStyleSheet(
            "QTableWidget { background:#1a1d24; color:#e6e9ef; "
            "alternate-background-color:#1f222b; border:1px solid #2d3340; }"
            "QHeaderView::section { background:#2d3340; color:#e6e9ef; "
            "padding:6px; border:none; font-weight:bold; }"
        )
        return t

    def refresh(self):
        from PyQt6.QtWidgets import QTableWidgetItem
        from PyQt6.QtGui import QColor
        try:
            import cost_tracker as ct
        except Exception as e:
            self.header_lbl.setText(f"<span style='color:#ed1c57;'>Error: {e}</span>")
            return

        provider_filter = self.provider_filter.currentData()
        providers = [provider_filter] if provider_filter else None
        report = ct.aggregate(providers=providers)

        # Header
        self.header_lbl.setText(
            f"<div style='font-size:14px;'>"
            f"💰 <b>Total all-time:</b> <span style='color:#62b4ff;'>${report.total_cost_usd:,.2f}</span>  "
            f"·  <b>Este mes:</b> <span style='color:#86efac;'>${report.this_month_usd:,.2f}</span>  "
            f"·  <b>Últimos 30 días:</b> <span style='color:#86efac;'>${report.last_30_days_usd:,.2f}</span>"
            f"<br><span style='color:#9ca3af; font-size:12px;'>"
            f"Tokens totales: {report.total_input:,} input · {report.total_output:,} output"
            f"</span></div>"
        )

        # Tabla proveedores
        self.table_providers.setRowCount(0)
        for prov, data in sorted(report.by_provider.items(), key=lambda x: -x[1]["cost"]):
            r = self.table_providers.rowCount()
            self.table_providers.insertRow(r)
            self.table_providers.setItem(r, 0, QTableWidgetItem(prov))
            self.table_providers.setItem(r, 1, QTableWidgetItem(f"${data['cost']:,.2f}"))
            self.table_providers.setItem(r, 2, QTableWidgetItem(f"{data['events']:,}"))
            self.table_providers.setItem(r, 3, QTableWidgetItem(f"{data['in']:,}"))
            self.table_providers.setItem(r, 4, QTableWidgetItem(f"{data['out']:,}"))
            note = (report.providers.get(prov).notes if report.providers.get(prov) else "") or ""
            self.table_providers.setItem(r, 5, QTableWidgetItem(note[:120]))

        # Tabla modelos
        self.table_models.setRowCount(0)
        top_models = sorted(report.by_model.items(), key=lambda x: -x[1]["cost"])[:10]
        for model, data in top_models:
            r = self.table_models.rowCount()
            self.table_models.insertRow(r)
            self.table_models.setItem(r, 0, QTableWidgetItem(model))
            self.table_models.setItem(r, 1, QTableWidgetItem(f"${data['cost']:,.2f}"))
            self.table_models.setItem(r, 2, QTableWidgetItem(f"{data['events']:,}"))
            self.table_models.setItem(r, 3, QTableWidgetItem(f"{data['in']:,}"))
            self.table_models.setItem(r, 4, QTableWidgetItem(f"{data['out']:,}"))
            tarifa = "✓ known" if data.get("pricing_known", True) else "⚠ default"
            it = QTableWidgetItem(tarifa)
            if not data.get("pricing_known", True):
                it.setForeground(QColor("#fbbf24"))
            self.table_models.setItem(r, 5, it)

        # Tabla proyectos
        self.table_projects.setRowCount(0)
        top_proj = sorted(report.by_project.items(), key=lambda x: -x[1]["cost"])[:10]
        for proj, data in top_proj:
            r = self.table_projects.rowCount()
            self.table_projects.insertRow(r)
            # Decodificar el path encoded de Claude para display
            label = proj.replace("-home-uther-", "~/").replace("-", "/")
            self.table_projects.setItem(r, 0, QTableWidgetItem(label[:60]))
            self.table_projects.setItem(r, 1, QTableWidgetItem(f"${data['cost']:,.2f}"))
            self.table_projects.setItem(r, 2, QTableWidgetItem(f"{data['events']:,}"))
            self.table_projects.setItem(r, 3, QTableWidgetItem(data.get("provider", "?")))

        # Charts QtCharts
        self._render_donut(report)
        self._render_projects_hbar(report)
        self._render_daily_stacked(report)

        # Estado scanners
        notes = []
        for prov, pr in report.providers.items():
            icon = "✓" if pr.available else "✗"
            color = "#86efac" if pr.available else "#9ca3af"
            sup = "" if pr.supported else " (no soportado)"
            notes.append(
                f"<span style='color:{color};'>{icon} {prov}</span>{sup}: "
                f"{pr.notes[:120]}"
            )
        self.scanners_lbl.setText("<br>".join(notes))

    # ── Renderers de charts (QtCharts) ───────────────────────────────

    # Paleta consistente entre charts. Proveedores siempre el mismo color.
    _PROVIDER_COLORS = {
        "claude":   "#62b4ff",
        "codex":    "#86efac",
        "gemini":   "#fbbf24",
        "opencode": "#c084fc",
    }
    _PROJECT_COLORS = (
        "#62b4ff", "#86efac", "#fbbf24", "#c084fc", "#f472b6",
        "#fb923c", "#34d399", "#60a5fa", "#a78bfa", "#fb7185",
    )

    def _empty_chart(self, view, title: str):
        """Si no hay datos, mostrar un chart vacío con título informativo."""
        from PyQt6.QtCharts import QChart
        ch = QChart()
        ch.setTitle(f"{title}\n(sin datos)")
        ch.setTheme(QChart.ChartTheme.ChartThemeDark)
        ch.setBackgroundVisible(False)
        view.setChart(ch)

    def _render_donut(self, report):
        from PyQt6.QtCharts import QChart, QPieSeries
        from PyQt6.QtGui import QColor
        from PyQt6.QtCore import Qt as _Qt

        items = [(p, d["cost"]) for p, d in report.by_provider.items() if d["cost"] > 0]
        if not items:
            self._empty_chart(self.chart_donut, "Cost per provider")
            return

        total = sum(v for _, v in items)
        series = QPieSeries()
        series.setHoleSize(0.45)
        for prov, cost in items:
            pct = (cost / total * 100) if total else 0
            sl = series.append(f"{prov}  ${cost:,.2f}  ({pct:.1f}%)", cost)
            sl.setLabelVisible(True)
            sl.setLabelPosition(sl.LabelPosition.LabelOutside)
            color = self._PROVIDER_COLORS.get(prov, "#888888")
            sl.setBrush(QColor(color))

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle(f"Cost per provider — Total ${total:,.2f}")
        chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        chart.setBackgroundVisible(False)
        chart.legend().setAlignment(_Qt.AlignmentFlag.AlignRight)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        self.chart_donut.setChart(chart)

    def _render_projects_hbar(self, report):
        from PyQt6.QtCharts import (
            QChart, QHorizontalBarSeries, QBarSet,
            QValueAxis, QBarCategoryAxis,
        )
        from PyQt6.QtGui import QColor
        from PyQt6.QtCore import Qt as _Qt

        top = sorted(report.by_project.items(), key=lambda x: -x[1]["cost"])[:10]
        if not top:
            self._empty_chart(self.chart_projects, "Top proyectos")
            return

        # Más arriba = más coste → invertimos para QtCharts (que muestra
        # el primer item abajo por defecto).
        top.reverse()
        labels = []
        values = []
        for proj, data in top:
            short = proj.replace("-home-uther-", "~/").replace("-", "/")
            labels.append(short[:42])
            values.append(data["cost"])

        bar_set = QBarSet("Cost")
        bar_set.append(values)
        bar_set.setColor(QColor(self._PROJECT_COLORS[0]))

        series = QHorizontalBarSeries()
        series.append(bar_set)
        series.setLabelsVisible(True)
        series.setLabelsFormat("$@value")
        series.setLabelsPosition(series.LabelsPosition.LabelsOutsideEnd)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Top 10 projects by cost")
        chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        chart.setBackgroundVisible(False)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.legend().setVisible(False)

        ax_y = QBarCategoryAxis()
        ax_y.append(labels)
        chart.addAxis(ax_y, _Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(ax_y)

        ax_x = QValueAxis()
        ax_x.setLabelFormat("$%d")
        chart.addAxis(ax_x, _Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(ax_x)

        self.chart_projects.setChart(chart)

    def _render_daily_stacked(self, report):
        from PyQt6.QtCharts import (
            QChart, QStackedBarSeries, QBarSet,
            QValueAxis, QBarCategoryAxis,
        )
        from PyQt6.QtGui import QColor
        from PyQt6.QtCore import Qt as _Qt
        from datetime import datetime, timezone, timedelta

        today = datetime.now(timezone.utc).date()
        days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
        day_keys = [d.isoformat() for d in days]
        day_labels = [d.strftime("%d/%m") for d in days]

        # Set de proveedores con coste >0 en los últimos 30 días
        providers_in_range = set()
        for day in day_keys:
            for prov in (report.by_day_by_provider.get(day) or {}).keys():
                providers_in_range.add(prov)
        if not providers_in_range:
            self._empty_chart(self.chart_daily, "Últimos 30 días")
            return

        # Un QBarSet por proveedor con los 30 valores
        series = QStackedBarSeries()
        for prov in sorted(providers_in_range):
            bset = QBarSet(prov)
            for day in day_keys:
                bset.append(
                    (report.by_day_by_provider.get(day) or {}).get(prov, 0.0)
                )
            color = self._PROVIDER_COLORS.get(prov, "#888888")
            bset.setColor(QColor(color))
            series.append(bset)

        chart = QChart()
        chart.addSeries(series)
        chart.setTitle("Daily cost (last 30 days) — stacked by provider")
        chart.setTheme(QChart.ChartTheme.ChartThemeDark)
        chart.setBackgroundVisible(False)
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)
        chart.legend().setAlignment(_Qt.AlignmentFlag.AlignBottom)

        ax_x = QBarCategoryAxis()
        ax_x.append(day_labels)
        chart.addAxis(ax_x, _Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(ax_x)

        ax_y = QValueAxis()
        ax_y.setLabelFormat("$%d")
        chart.addAxis(ax_y, _Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(ax_y)

        self.chart_daily.setChart(chart)


class _DailyCostChart(QWidget):
    """Mini bar chart por día, dibujado con QPainter. Sin dependencia de
    QtCharts para no añadir un módulo opcional."""

    def __init__(self):
        super().__init__()
        self._labels: list[str] = []
        self._values: list[float] = []

    def set_data(self, labels: list[str], values: list[float]):
        self._labels = labels
        self._values = values
        self.update()

    def paintEvent(self, _e):
        from PyQt6.QtGui import QPainter, QColor, QPen, QFont
        from PyQt6.QtCore import QRect
        if not self._values:
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w = self.width()
            h = self.height()
            n = len(self._values)
            margin_l, margin_r = 40, 12
            margin_t, margin_b = 8, 22
            chart_w = w - margin_l - margin_r
            chart_h = h - margin_t - margin_b
            if chart_w <= 0 or chart_h <= 0:
                return
            max_v = max(self._values) or 1.0
            bar_w = chart_w / n
            # Ejes Y: 0 y max
            p.setPen(QPen(QColor("#3a3f4d")))
            p.drawLine(margin_l, margin_t, margin_l, margin_t + chart_h)
            p.drawLine(margin_l, margin_t + chart_h, w - margin_r, margin_t + chart_h)
            # Labels Y
            font = QFont(); font.setPointSize(8)
            p.setFont(font)
            p.setPen(QPen(QColor("#9ca3af")))
            p.drawText(QRect(0, margin_t - 6, margin_l - 4, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"${max_v:.0f}")
            p.drawText(QRect(0, margin_t + chart_h - 6, margin_l - 4, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       "$0")
            # Barras
            for i, v in enumerate(self._values):
                bh = (v / max_v) * chart_h if max_v else 0
                x = margin_l + i * bar_w
                y = margin_t + chart_h - bh
                color = QColor("#62b4ff") if v > 0 else QColor("#2d3340")
                p.fillRect(int(x + 1), int(y), int(bar_w - 2), int(bh), color)
            # Labels X: cada 5 días para no saturar
            p.setPen(QPen(QColor("#9ca3af")))
            for i, lbl in enumerate(self._labels):
                if i % 5 == 0 or i == n - 1:
                    x = margin_l + i * bar_w
                    p.drawText(QRect(int(x - 20), margin_t + chart_h + 4, 40, 16),
                               Qt.AlignmentFlag.AlignCenter, lbl)
        finally:
            p.end()


class _AgentPane(QWidget):
    """A single agent's output pane in the multi-agent compare tab."""

    def __init__(self, agent_key: str, agent_name: str, color: str,
                 on_done=None, parent=None):
        super().__init__(parent)
        self.agent_key = agent_key
        self.color = color
        self.on_done = on_done
        self.proc: QProcess | None = None
        self.start_time = 0.0
        self.ttft: float | None = None

        title = QLabel(f"<b style='color:{color}; font-size:14px;'>{agent_name}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        self.stats = QLabel("⏳ idle")
        self.stats.setStyleSheet("color: #888;")

        h_header = QHBoxLayout()
        h_header.addWidget(title)
        h_header.addStretch()
        h_header.addWidget(self.stats)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("monospace", 10))

        btn_copy = QPushButton("📋 Copiar")
        btn_copy.clicked.connect(self._copy)
        h_footer = QHBoxLayout()
        h_footer.addWidget(btn_copy)
        h_footer.addStretch()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(h_header)
        lay.addWidget(self.output, 1)
        lay.addLayout(h_footer)

    def run(self, argv: list[str], cwd: str | None = None) -> None:
        self.output.clear()
        self.ttft = None
        self.start_time = time.time()
        self.stats.setText("▶ corriendo…")
        self.stats.setStyleSheet(f"color: {self.color};")

        self.proc = QProcess(self)
        if cwd:
            self.proc.setWorkingDirectory(cwd)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)

        cmd = " ".join(shlex.quote(a) for a in argv)
        _sh, _args = pc.shell_program_and_args(cmd)
        self.proc.start(_sh, _args)

    def _read(self) -> None:
        if not self.proc:
            return
        data = self.proc.readAllStandardOutput().data().decode(errors="replace")
        if not data:
            return
        if self.ttft is None:
            self.ttft = time.time() - self.start_time
            self.stats.setText(f"⏱ TTFT {self.ttft:.1f}s · corriendo…")
        self.output.insertPlainText(data)
        sb = self.output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _finished(self, exit_code: int, _status) -> None:
        total = time.time() - self.start_time
        ttft_str = f"{self.ttft:.1f}s" if self.ttft is not None else "—"
        if exit_code == 0:
            self.stats.setText(f"✅ TTFT {ttft_str} · total {total:.1f}s")
            self.stats.setStyleSheet("color: #86efac;")
        else:
            self.stats.setText(f"❌ exit {exit_code} · {total:.1f}s")
            self.stats.setStyleSheet("color: #f87171;")
        if self.on_done:
            self.on_done()

    def stop(self) -> None:
        if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
            self.stats.setText("■ cancelado")
            self.stats.setStyleSheet("color: #f59e0b;")

    def _copy(self) -> None:
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self.output.toPlainText())


class _MultiAgentPanel(QWidget):
    """Tab "Comparar agentes": run the same prompt across multiple AI
    CLIs in parallel and display the outputs side-by-side."""

    def __init__(self, parent=None):
        super().__init__(parent)
        import multi_agent as ma

        title = QLabel(
            "<h3>🤝 Comparar agentes</h3>"
            "<small>Ejecuta el mismo prompt en varios CLIs de IA "
            "(Claude / Codex / Gemini / OpenCode) en paralelo y compara "
            "los resultados lado a lado. Cada agente se invoca en modo "
            "one-shot non-interactive.</small>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)

        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Escribe el prompt aquí…\n\n"
            "Ej: 'Explica en un párrafo cómo configurar un sitemap.xml en Next.js.'"
        )
        self.prompt.setMaximumHeight(160)

        self.agent_checks: dict[str, QCheckBox] = {}
        agents_row = QHBoxLayout()
        agents_row.addWidget(QLabel("<b>Agentes:</b>"))
        for key, spec in ma.AGENTS.items():
            avail = ma.check_agent_available(key)
            cb = QCheckBox(spec.name)
            cb.setChecked(avail)
            cb.setEnabled(avail)
            if not avail:
                cb.setText(f"{spec.name} (no instalado)")
                cb.setStyleSheet("color: #888;")
            else:
                cb.setStyleSheet(f"color: {spec.color}; font-weight: 600;")
            self.agent_checks[key] = cb
            agents_row.addWidget(cb)
        agents_row.addStretch()

        self.btn_run = QPushButton("▶ Ejecutar")
        self.btn_run.clicked.connect(self._run_all)
        self.btn_stop = QPushButton("■ Cancelar")
        self.btn_stop.clicked.connect(self._stop_all)
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton("🧹 Limpiar")
        self.btn_clear.clicked.connect(self._clear)

        actions_row = QHBoxLayout()
        actions_row.addWidget(self.btn_run)
        actions_row.addWidget(self.btn_stop)
        actions_row.addStretch()
        actions_row.addWidget(self.btn_clear)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.panes: list[_AgentPane] = []
        self._running_count = 0

        empty = QLabel(
            "Los paneles de respuesta aparecerán aquí al pulsar <b>▶ Ejecutar</b>.<br>"
            "<small>Tip: para comparaciones rápidas, escribe un prompt simple y "
            "deja los dos agentes seleccionados. Cuanto más largo el prompt, "
            "más vas a esperar.</small>"
        )
        empty.setTextFormat(Qt.TextFormat.RichText)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: #888;")
        self.splitter.addWidget(empty)
        self._empty_widget = empty

        lay = QVBoxLayout(self)
        lay.addWidget(title)
        lay.addWidget(QLabel("<b>Prompt:</b>"))
        lay.addWidget(self.prompt)
        lay.addLayout(agents_row)
        lay.addLayout(actions_row)
        lay.addWidget(self.splitter, 1)

    def _run_all(self) -> None:
        import multi_agent as ma
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Multi-agent", "Escribe un prompt primero.")
            return
        selected = [k for k, cb in self.agent_checks.items()
                    if cb.isChecked() and cb.isEnabled()]
        if not selected:
            QMessageBox.warning(self, "Multi-agent",
                                "Selecciona al menos un agente disponible.")
            return

        self._clear()

        for key in selected:
            spec = ma.AGENTS[key]
            pane = _AgentPane(key, spec.name, spec.color,
                              on_done=self._on_pane_finished)
            self.splitter.addWidget(pane)
            self.panes.append(pane)

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._running_count = len(selected)

        for pane, key in zip(self.panes, selected):
            argv = ma.build_argv(key, prompt)
            pane.run(argv)

    def _on_pane_finished(self) -> None:
        self._running_count -= 1
        if self._running_count <= 0:
            self.btn_run.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def _stop_all(self) -> None:
        for p in self.panes:
            p.stop()
        self.btn_stop.setEnabled(False)
        self.btn_run.setEnabled(True)

    def _clear(self) -> None:
        for p in self.panes:
            p.stop()
            p.deleteLater()
        self.panes.clear()
        # Restore the empty hint widget if needed
        if self.splitter.count() == 0:
            self.splitter.addWidget(self._empty_widget)


class ThemeForgeApp(QWidget):
    """Ventana raíz con pestañas: Nuevo proyecto + Galería."""

    def __init__(self):
        super().__init__()
        # Registrar como ventana principal (focus_new_project vuelve a
        # "New project" desde una ProjectWindow sin cerrar lo que corre).
        global _MAIN_APP
        _MAIN_APP = self
        self.setWindowTitle("ThemeForge")
        self.setMinimumWidth(820)
        self.setMinimumHeight(640)

        from settings_panel import SettingsPanel
        from licensing_panel import LicensingPanel
        self.builder = ThemeForge()
        self.gallery = GalleryPanel()
        self.licensing = LicensingPanel()
        self.settings = SettingsPanel()
        self.cost = _CostTrackerPanel()
        self.multi_agent = _MultiAgentPanel()
        # Hermes (centro de control de agentes) — TOTALMENTE OPCIONAL. El tab
        # solo aparece si Hermes está instalado. Sin Hermes, ThemeForge funciona
        # exactamente igual y NO muestra el tab: nunca se fuerza la dependencia.
        self.operator = None
        try:
            from hermes_panel import HermesPanel, find_hermes
            if find_hermes():
                self.operator = HermesPanel()
        except Exception as e:
            print(f"[hermes] panel no disponible: {e}")
            self.operator = None

        # Market analysis tab (carga lazy — si falla, no rompe la app).
        try:
            from market_tab import MarketTab
            self.market = MarketTab()
            # El banner «sin key» del Market emite esta señal cuando el user
            # pulsa «Configurar OpenRouter»: saltamos a la pestaña Settings.
            self.market.request_open_credentials.connect(self._open_settings_tab)
            # «🚀 Crear proyecto desde este análisis» → cargamos el markdown
            # del análisis en el pipeline _last_analysis del builder (igual
            # que hace Vibe) y saltamos a la pestaña New project, modo
            # scratch, sin stack/nicho prefijados.
            self.market.request_create_from_analysis.connect(self._create_from_market_analysis)
        except Exception as e:
            print(f"[market] tab no disponible: {e}")
            self.market = None

        # Pestañas opcionales aportadas por el plugin privado (ausentes en OSS):
        # se crean ahora y se añaden al final del orden de pestañas.
        _extra_tabs = _np.native_tabs(self) if _np else []

        self.tabs = QTabWidget()
        # Tabs use Lucide SVG icons (theme-aware: re-colored on theme change).
        # `_tab_specs` is the source of truth; `_apply_tab_icons` paints icons
        # in the current theme's accent color and is re-called when the user
        # switches theme via Settings.
        self._tab_specs: list[tuple[QWidget, str, str]] = [
            (self.builder,     "box",      "New project"),
            (self.gallery,     "gallery",  "Gallery"),
            (self.cost,        "dollar",   "AI cost"),
            (self.multi_agent, "users",    "Compare"),
            (self.licensing,   "key",      "Licensing"),
            (self.settings,    "settings", "Settings"),
        ]
        if getattr(self, "operator", None) is not None:
            # Tras "Compare": New project · Gallery · AI cost · Compare · Hermes · …
            self._tab_specs.insert(4, (self.operator, "sparkles", "Hermes"))
        if getattr(self, "market", None) is not None:
            # Tras "Compare" (idx 3): New project · Gallery · AI cost · Compare · Market · …
            self._tab_specs.insert(4, (self.market, "globe", "Market"))
        self._tab_specs.extend(_extra_tabs)
        for widget, icon_name, label in self._tab_specs:
            self.tabs.addTab(widget, label)
        self._apply_tab_icons()

        # Refresh icons when the user picks a different theme so the
        # accent color in the SVG strokes follows.
        try:
            import themes as _t
            _t.theme_signals.theme_changed.connect(lambda _name: self._apply_tab_icons())
        except Exception:
            pass

        def _on_tab_change(i):
            w = self.tabs.widget(i)
            if w is self.gallery: self.gallery.refresh()
            elif w is self.settings: self.settings.refresh_status()
            elif w is self.cost: self.cost.refresh()
        self.tabs.currentChanged.connect(_on_tab_change)

        # Method bound below via class scope (defined after __init__ exits
        # in cleaner OOP, but inlined here for proximity to the tab specs).
        # We attach `_apply_tab_icons` as an instance method via setattr
        # right after __init__ to keep the diff minimal.

        # Atmósfera Neo-Tokyo: contenedor que pinta grid + glows detrás de
        # las pestañas cuando el tema activo es `neotokyo` (coste cero con
        # cualquier otro tema). Fallback seguro si el módulo no carga.
        root = QVBoxLayout()
        self._atmos = None
        try:
            from neotokyo_fx import AtmosphereContainer
            self._atmos = AtmosphereContainer()
            self._atmos.layout().addWidget(self.tabs)
            root.addWidget(self._atmos)
        except Exception as e:
            print(f"[neotokyo] atmósfera no disponible: {e}", file=sys.stderr)
            root.addWidget(self.tabs)
        self.setLayout(root)
        # Aplica el estado de la atmósfera + transparencia según el tema
        # actual, y re-aplícalo en cada cambio de tema.
        self._apply_neotokyo_fx()
        try:
            import themes as _t
            _t.theme_signals.theme_changed.connect(lambda _n: self._apply_neotokyo_fx())
        except Exception:
            pass

        # Atajo global Ctrl+K → command palette
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._palette_shortcut.activated.connect(self._open_command_palette)

    def _build_palette_actions(self) -> list[tuple[str, str, object]]:
        """Genera la lista de acciones disponibles en la paleta. Se
        regenera en cada apertura para reflejar el estado actual
        (proyectos nuevos, etc.)."""
        actions: list[tuple[str, str, object]] = []

        # Navegación a pestañas
        for i in range(self.tabs.count()):
            tab_label = self.tabs.tabText(i)
            actions.append((
                f"Ir a: {tab_label}",
                "Navegación",
                lambda i=i: self.tabs.setCurrentIndex(i),
            ))

        # Abrir proyectos (activos y archivados)
        try:
            for it in list_projects(archived=False):
                actions.append((
                    f"Abrir proyecto: {it['name']}",
                    f"Galería · {it['stack']}",
                    lambda p=it["path"]: open_project_window(p),
                ))
            for it in list_projects(archived=True):
                actions.append((
                    f"Abrir archivado: {it['name']}",
                    f"Archivados · {it['stack']}",
                    lambda p=it["path"]: open_project_window(p),
                ))
        except Exception:
            pass

        # Acciones rápidas
        actions += [
            (
                "Nuevo proyecto…",
                "Acciones",
                lambda: (self.tabs.setCurrentIndex(0),
                         self.builder.name_edit.setFocus()),
            ),
            (
                "Refrescar galería",
                "Acciones",
                lambda: (self.tabs.setCurrentIndex(1), self.gallery.refresh()),
            ),
            (
                "Vista cards (galería)",
                "Vista",
                lambda: (self.tabs.setCurrentIndex(1),
                         self.gallery.view_toggle.setChecked(True)),
            ),
            (
                "Vista lista (galería)",
                "Vista",
                lambda: (self.tabs.setCurrentIndex(1),
                         self.gallery.view_toggle.setChecked(False)),
            ),
            (
                "Ajustes",
                "Navegación",
                lambda: self.tabs.setCurrentIndex(self.tabs.count() - 1),
            ),
        ]
        return actions

    def _open_command_palette(self):
        dlg = _CommandPalette(self, self._build_palette_actions())
        dlg.exec()

    def _open_settings_tab(self):
        """Switches the main QTabWidget to the Settings tab. Invoked when
        a sub-component (e.g. the Market tab's «Configure OpenRouter»
        button) wants to redirect the user to credential setup."""
        for i, (w, _icon, _label) in enumerate(self._tab_specs):
            if w is self.settings:
                self.tabs.setCurrentIndex(i)
                return

    def _create_from_market_analysis(self, content: str):
        """Carga el markdown del análisis de mercado en el builder y salta a
        la pestaña New project (subtab Setup), modo scratch, stack=none y
        nicho por defecto, para que el agente decida con el contexto entero."""
        if not content:
            return
        b = self.builder
        # Reusamos el pipeline existente: (None, text) = analisis "scratch".
        b._last_analysis = (None, content)
        b._last_analysis_kind = "market"
        # Limpiar la elección manual de stack/niche para señalizar "decide tú".
        if "none" in STACKS:
            b._stack_key = "none"
            b._refresh_stack_button()
        if hasattr(b, "niche_combo"):
            idx0 = 0
            b.niche_combo.setCurrentIndex(idx0)
        # Modo scratch (sin referencia).
        if hasattr(b, "mode_scratch"):
            b.mode_scratch.setChecked(True)
        # Subtab «Setup» dentro de New project, luego pestaña principal.
        if hasattr(b, "new_project_subtabs"):
            for i in range(b.new_project_subtabs.count()):
                if "Setup" in b.new_project_subtabs.tabText(i):
                    b.new_project_subtabs.setCurrentIndex(i)
                    break
        for i, (w, _icon, _label) in enumerate(self._tab_specs):
            if w is self.builder:
                self.tabs.setCurrentIndex(i)
                break
        b._update_preview()

    # Kanji eyebrows del tema Neo-Tokyo (detalle JP del design pack). Solo
    # se añaden cuando el tema activo es `neotokyo`; con cualquier otro tema
    # las pestañas muestran su etiqueta limpia.
    _NEOTOKYO_KANJI = {
        "New project": "新規",
        "Gallery":     "制作庫",
        "AI cost":     "費用",
        "Compare":     "比較",
        "Hermes":      "司令室",
        "Market":      "市場",
        "Licensing":   "認可",
        "Settings":    "設定",
    }

    def _apply_neotokyo_fx(self):
        """Activa/desactiva la atmósfera Neo-Tokyo y la transparencia del
        pane según el tema activo. Se llama al iniciar y en cada cambio de
        tema (el QSS base ya está aplicado cuando llega la señal, así que
        añadir la transparencia aquí no la pisa nada)."""
        try:
            import themes as _t
            neotokyo = _t.current_theme_name() == "neotokyo"
        except Exception:
            neotokyo = False
        if self._atmos is not None:
            self._atmos.set_active(neotokyo)
        try:
            from neotokyo_fx import NEOTOKYO_TRANSPARENCY_QSS
            app = QApplication.instance()
            if app is not None:
                base = app.styleSheet()
                if neotokyo and NEOTOKYO_TRANSPARENCY_QSS not in base:
                    app.setStyleSheet(base + NEOTOKYO_TRANSPARENCY_QSS)
                # Al cambiar a otro tema, apply_theme ya reescribió el QSS
                # base (sin la transparencia), así que no hay que quitarla.
        except Exception:
            pass

    def _apply_tab_icons(self):
        """Renders tab icons in the current theme's accent color and
        applies them to the QTabWidget. Called once at startup and
        every time the user switches theme via Settings. For the
        Neo-Tokyo theme it also appends the kanji eyebrow to each tab."""
        theme_name = "themeforge-dark"
        try:
            import themes as _t
            theme_name = _t.current_theme_name()
            pack = _t.load_theme(theme_name)
            color = pack.color.accent
        except Exception:
            color = "#62b4ff"  # fallback
        neotokyo = theme_name == "neotokyo"
        try:
            for i, (_w, icon_name, label) in enumerate(self._tab_specs):
                icon = _t.tf_icon(icon_name, color=color, size=18)
                self.tabs.setTabIcon(i, icon)
                _kanji_map = dict(self._NEOTOKYO_KANJI)
                if _np:
                    _kanji_map.update(_np.kanji())
                kanji = _kanji_map.get(label) if neotokyo else None
                self.tabs.setTabText(i, f"{label}  {kanji}" if kanji else label)
        except Exception as e:
            print(f"[tabs] could not apply icons: {e}")


def main():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    # Carga API keys de ~/.config/themeforge/keys.json en os.environ para que
    # las hereden el terminal server y todos los PTYs que arranquen los CLIs.
    try:
        aip.apply_all_known_keys()
    except Exception as e:
        print(f"[ai_providers] error cargando keys: {e}")

    # Carga plugins del usuario (~/.config/themeforge/plugins/*.py).
    # Cada plugin puede registrar stacks, template types o agents extra
    # vía las helpers de `themeforge_plugins`. Se ejecuta ANTES de
    # construir la UI para que el form lea STACKS ya con los plugins
    # aplicados.
    try:
        from themeforge_plugins import load_user_plugins, PLUGINS_DIR
        loaded, plugin_errors = load_user_plugins()
        if loaded:
            print(f"[plugins] cargados {loaded} plugins de {PLUGINS_DIR}")
        for err in plugin_errors:
            print(f"[plugins] ERROR: {err}", file=sys.stderr)
    except Exception as e:
        print(f"[plugins] error cargando plugins: {e}", file=sys.stderr)

    # Compartir contexto OpenGL entre Qt y WebEngine (requerido por Qt docs).
    # NO añadimos QTWEBENGINE_CHROMIUM_FLAGS — los flags de aceleración
    # GPU crashean QWebEnginePage en ciertos drivers mesa/AMD en Wayland.
    # Para sesiones largas o demos pesadas usa el botón "🚀 Abrir en
    # navegador" que lanza Brave/Chromium externo nativo.
    from PyQt6.QtCore import Qt
    # USE_SOFTWARE_GL se resolvió al cargar el módulo (arriba), donde ya
    # se pusieron QT_OPENGL y QTWEBENGINE_CHROMIUM_FLAGS antes de importar
    # Qt. Aquí solo falta el atributo, que debe ir antes de QApplication.
    if USE_SOFTWARE_GL:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        print("[gl] render por software activado (entorno sin GPU)", flush=True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)

    # Apply theme. Reads `~/.config/themeforge/settings.json` for the
    # saved theme; falls back to default if missing. Applied before
    # any window opens so the splash / first dialog already match.
    try:
        import themes
        _pack = themes.load_theme(themes.current_theme_name())
        themes.apply_theme(app, _pack)
    except Exception as e:
        print(f"[themes] could not apply theme: {e}", file=sys.stderr)

    # Set app-wide window icon. Qt propaga este icono a todas las
    # QWidget de la app (titlebar, taskbar, alt-tab) salvo que se
    # sobrescriba en la ventana concreta. Cargamos múltiples tamaños
    # para que Qt elija el mejor según DPI y contexto (titlebar 16px,
    # taskbar 32-48px, alt-tab 64-128px, dock 256px).
    from PyQt6.QtCore import QSize
    from PyQt6.QtGui import QIcon
    _assets_dir = Path(__file__).parent / "assets"
    if (_assets_dir / "themeforge.png").is_file():
        _icon = QIcon()
        for sz in (16, 32, 48, 64, 128, 256):
            p = _assets_dir / f"themeforge-{sz}.png"
            if p.is_file():
                _icon.addFile(str(p), QSize(sz, sz))
        _icon.addFile(str(_assets_dir / "themeforge.png"))
        app.setWindowIcon(_icon)

    # Auto-launch del visualizer pixel-art (pixel-office-openclaw fork MIT
    # con reader de Claude Code añadido). Lee directo de
    # ~/.claude/projects/*/*.jsonl así que NO necesita registrar hooks.
    pixel_proc = None
    try:
        import pixel_office
        if not pixel_office.find_install_dir():
            r = QMessageBox.question(
                None, "🎮 Pixel Office",
                "Pixel Office no está instalado. Es un visualizador pixel-art "
                "que muestra tus sesiones de Claude Code (y OpenClaw) como "
                "avatares en una oficina virtual.\n\n"
                "¿Instalar ahora? (clona el repo en "
                "~/.local/share/themeforge/pixel-office-openclaw/, ejecuta "
                "npm install + build. Tarda ~1-2 min.)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                print("[pixel-office] instalando…", flush=True)
                ok, msg = pixel_office.install()
                print(f"[pixel-office] {'OK' if ok else 'FAIL'}: {msg}", flush=True)
                if not ok:
                    QMessageBox.warning(
                        None, "Pixel Office",
                        f"Instalación falló:\n{msg}\n\n"
                        "Puedes reintentar desde Settings → 🎮 Office.",
                    )
        # Una vez instalado (o si ya lo estaba) → auto-launch
        pixel_proc = pixel_office.launch_background()
        if pixel_proc is not None:
            print("[pixel-office] dashboard arrancado en background (PID", pixel_proc.pid, ")")
        elif pixel_office.is_dashboard_up():
            print("[pixel-office] dashboard ya estaba arriba — usando el existente")
        else:
            print("[pixel-office] no instalado — actívalo desde Settings → 🎮 Office")
    except Exception as e:
        print(f"[pixel-desk] error al auto-launch: {e}")

    def cleanup():
        try:
            import pixel_office
            pixel_office.stop(pixel_proc)
        except Exception:
            pass

    app.aboutToQuit.connect(cleanup)

    # UI principal: por defecto la interfaz Neo-Tokyo (web prototype exacto
    # renderizado en WebEngine con datos reales vía puente). La UI clásica de
    # widgets sigue disponible con THEMEFORGE_CLASSIC=1 (acceso a todo lo que
    # aún no está cableado en la web).
    # Modo de UI: 'web' (Neo-Tokyo WebEngine, por defecto) o 'classic' (QWidgets
    # nativo). Lo decide app_prefs.ui_mode() (el usuario lo cambia desde
    # Settings → Temas) o el env THEMEFORGE_CLASSIC=1 / THEMEFORGE_WEB=1.
    try:
        import app_prefs as _ap
        _mode = _ap.ui_mode()
    except Exception:
        _mode = "web"
    if os.environ.get("THEMEFORGE_CLASSIC") == "1":
        _mode = "classic"
    elif os.environ.get("THEMEFORGE_WEB") == "1":
        _mode = "web"
    w = None
    if _mode != "classic":
        try:
            from web_shell import WebShell
            w = WebShell()
            w.resize(1320, 860)
            w.setWindowTitle("ThemeForge // Neo-Tokyo")
        except Exception as e:
            print(f"[webshell] UI web no disponible, uso la clásica: {e}",
                  file=sys.stderr)
            w = None
    if w is None:
        w = ThemeForgeApp()

    def _enter_app():
        # Primer arranque: asistente de bienvenida completo (deps +
        # credenciales IA + defaults). Arranques posteriores: solo el wizard
        # de dependencias si faltan herramientas REQUERIDAS (Node/git).
        try:
            from onboarding_wizard import maybe_run_onboarding
            if not maybe_run_onboarding(w):
                from dependency_wizard import maybe_run_first_run_setup
                maybe_run_first_run_setup(w)
        except Exception as e:
            print(f"[onboarding] error: {e}", file=sys.stderr)
        w.show()
        w.raise_()
        w.activateWindow()

    # Splash de bienvenida Neo-Tokyo (boot sequence): animación de arranque
    # estilo terminal sobre la atmósfera cyberpunk. Es QPainter puro — sin
    # multimedia ni OpenGL — así que funciona también en entornos sin GPU
    # (USE_SOFTWARE_GL) sin dejar la ventana negra. El usuario puede saltarlo
    # con clic/tecla; una red de seguridad garantiza la entrada a la app.
    # THEMEFORGE_NO_SPLASH=1 lo desactiva.
    _splash = None
    _no_splash = os.environ.get("THEMEFORGE_NO_SPLASH") == "1"
    # El splash completo solo el PRIMER arranque (animación de marca). En
    # arranques posteriores se entra directo a la app para abrir más rápido.
    if not _no_splash:
        try:
            import app_prefs as _ap_splash
            if _ap_splash.get("splash_seen", False):
                _no_splash = True
            else:
                _ap_splash.set("splash_seen", True)
        except Exception:
            pass
    if not _no_splash:
        try:
            from boot_splash import BootSplash
            _splash = BootSplash()
            _splash.finished.connect(_enter_app)
            _splash.start()
        except Exception as e:
            print(f"[splash] no se pudo mostrar el boot splash: {e}", file=sys.stderr)
            _splash = None

    if _splash is None:
        _enter_app()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
