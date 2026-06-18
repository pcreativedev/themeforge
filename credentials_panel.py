"""credentials_panel.py — Widget reutilizable de gestión de credenciales IA.

Muestra los providers con su estado (detect_status de ai_providers) y
acciones contextuales: instalar el CLI, login OAuth, añadir/cambiar/quitar
API key. Toda la lógica vive en ai_providers.py; esto es solo la UI.

Se usa en dos sitios:
  - Paso "Credenciales" del onboarding wizard (onboarding_wizard.py).
  - Sección "🔑 AI credentials" del panel de Settings.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QInputDialog, QLineEdit, QMessageBox, QComboBox,
)

import ai_providers as aip
import platform_compat as pc

# Icono por estado de detect_status.
_STATE_ICON = {
    "ok": "🟢",
    "need_login": "🟡",
    "need_key": "⚪",
    "missing_cli": "🔴",
}


class CredentialsWidget(QWidget):
    """Tabla de providers IA con estado + acciones de credenciales."""

    changed = pyqtSignal()  # emitido cuando algo cambia (login/key)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._rows: dict[str, dict] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        hint = QLabel(
            "Estado de cada proveedor de IA. <b>OAuth</b> abre el login en una "
            "terminal (sigue las instrucciones en pantalla); <b>API key</b> se "
            "guarda cifrada en <code>keys.json</code> (chmod 0600)."
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        root.addWidget(hint)

        for key in aip.PROVIDERS:
            row = self._build_row(key)
            root.addWidget(row)

        # Modelo del CLI de Claude (se pasa con --model en todos los modos).
        root.addWidget(self._build_claude_model_row())

        # Integraciones (no-IA): token de Figma para el MCP figma-context.
        root.addWidget(self._build_figma_row())
        # UI components: API key de 21st.dev (MCP Magic → componentes pro `/ui`).
        root.addWidget(self._build_21st_row())
        # Búsqueda web avanzada: API key de Firecrawl (Locales → todo internet).
        root.addWidget(self._build_firecrawl_row())
        # Imágenes: API key de Runware (generación de imágenes de los templates).
        root.addWidget(self._build_runware_row())

        btns = QHBoxLayout()
        btns.addStretch()
        self._btn_refresh = QPushButton("🔄 Re-detectar")
        self._btn_refresh.clicked.connect(self.refresh)
        btns.addWidget(self._btn_refresh)
        root.addLayout(btns)

        self.refresh()

    def _build_row(self, key: str) -> QFrame:
        p = aip.PROVIDERS[key]
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-bottom: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)

        status = QLabel("…")
        status.setTextFormat(Qt.TextFormat.RichText)
        status.setWordWrap(True)
        lay.addWidget(status, 1)

        # Botones de acción (se muestran/ocultan según estado en refresh()).
        btn_install = QPushButton("⬇️ Instalar CLI")
        btn_login = QPushButton("🔓 Login")
        btn_addkey = QPushButton("🔑 Añadir key")
        btn_editkey = QPushButton("✏️ Cambiar key")
        btn_logout = QPushButton("🚪 Quitar key")
        btn_install.clicked.connect(lambda _=False, k=key: self._install_cli(k))
        btn_login.clicked.connect(lambda _=False, k=key: self._login(k))
        btn_addkey.clicked.connect(lambda _=False, k=key: self._add_key(k))
        btn_editkey.clicked.connect(lambda _=False, k=key: self._add_key(k))
        btn_logout.clicked.connect(lambda _=False, k=key: self._remove_key(k))
        for b in (btn_install, btn_login, btn_addkey, btn_editkey, btn_logout):
            lay.addWidget(b)

        self._rows[key] = {
            "status": status, "install": btn_install, "login": btn_login,
            "addkey": btn_addkey, "editkey": btn_editkey, "logout": btn_logout,
        }
        return frame

    # ── Estado ──────────────────────────────────────────────────────────
    def refresh(self):
        for key, w in self._rows.items():
            p = aip.PROVIDERS[key]
            try:
                state, info = aip.detect_status(key)
            except Exception as e:
                state, info = "missing_cli", f"error: {e}"
            icon = _STATE_ICON.get(state, "⚪")
            w["status"].setText(
                f"{icon} <b>{p['name']}</b><br>"
                f"<small style='color:#9aa'>{info}</small>"
            )
            is_api = p.get("auth_kind") in ("api", "oauth_or_api") and p.get("key_id")
            # Visibilidad de botones según estado.
            w["install"].setVisible(state == "missing_cli")
            w["login"].setVisible(state in ("need_login",) or
                                   (state == "ok" and p.get("auth_kind") in ("oauth", "oauth_or_api")
                                    and p.get("login_argv") is not None))
            w["login"].setText("🔓 Login" if state != "ok" else "🔁 Re-login")
            w["addkey"].setVisible(state == "need_key" and bool(is_api))
            w["editkey"].setVisible(state == "ok" and bool(is_api))
            w["logout"].setVisible(state == "ok" and bool(is_api))

        # Estado del token de Figma (integración MCP, no provider de IA).
        if hasattr(self, "_figma_status"):
            try:
                has_figma = bool(aip.load_keys().get("figma"))
            except Exception:
                has_figma = False
            self._figma_status.setText(
                ("🟢" if has_figma else "⚪")
                + " <b>Figma</b> <small>(token para el MCP figma-context)</small><br>"
                + "<small style='color:#9aa'>"
                + ("token guardado — el agente puede leer/importar tus diseños de Figma"
                   if has_figma else
                   "sin token — añádelo para importar/leer diseños de Figma")
                + "</small>"
            )
            self._figma_set.setText("✏️ Cambiar token" if has_figma else "🔑 Añadir token")
            self._figma_clear.setVisible(has_figma)

        # Estado de la key de 21st.dev (MCP Magic — componentes UI pro).
        if hasattr(self, "_t21_status"):
            try:
                has_21 = bool(aip.load_keys().get("twentyfirst"))
            except Exception:
                has_21 = False
            self._t21_status.setText(
                ("🟢" if has_21 else "⚪")
                + " <b>21st.dev</b> <small>(MCP Magic — componentes UI pro con "
                  "<code>/ui</code>)</small><br>"
                + "<small style='color:#9aa'>"
                + ("key guardada — el agente puede traer componentes profesionales "
                   "de 21st.dev"
                   if has_21 else
                   "sin key — gratis en 21st.dev → Settings → API (100 créditos/mes)")
                + "</small>")
            self._t21_set.setText("✏️ Cambiar key" if has_21 else "🔑 Añadir key")
            self._t21_clear.setVisible(has_21)

        # Estado de la key de Firecrawl (búsqueda web avanzada).
        if hasattr(self, "_fc_status"):
            try:
                has_fc = bool(aip.load_keys().get("firecrawl"))
            except Exception:
                has_fc = False
            self._fc_status.setText(
                ("🟢" if has_fc else "⚪")
                + " <b>Firecrawl</b> <small>(Locales → buscar en TODO internet: "
                  "scrape + extracción de anuncios)</small><br>"
                + "<small style='color:#9aa'>"
                + ("key guardada — «🌐 todo internet» usa Firecrawl"
                   if has_fc else
                   "sin key — gratis en firecrawl.dev → API Keys (500/mes); sin "
                   "ella se usa Perplexity Sonar")
                + "</small>")
            self._fc_set.setText("✏️ Cambiar key" if has_fc else "🔑 Añadir key")
            self._fc_clear.setVisible(has_fc)

        # Estado de la key de Runware (imágenes).
        if hasattr(self, "_runware_status"):
            try:
                has_rw = bool(aip.load_keys().get("runware"))
            except Exception:
                has_rw = False
            self._runware_status.setText(
                ("🟢" if has_rw else "⚪")
                + " <b>Runware</b> <small>(generación de imágenes — API key)</small><br>"
                + "<small style='color:#9aa'>"
                + ("key guardada — el operator puede generar hero/OG/logos originales"
                   if has_rw else
                   "sin key — añádela para generar imágenes (runware.ai → API keys)")
                + "</small>")
            self._runware_set.setText("✏️ Cambiar key" if has_rw else "🔑 Añadir key")
            self._runware_clear.setVisible(has_rw)

    # ── Acciones ────────────────────────────────────────────────────────
    def _install_cli(self, key: str):
        """Abre el wizard de dependencias para instalar el CLI faltante."""
        try:
            from dependency_wizard import DependencyWizard
            DependencyWizard(self).exec()
            self.refresh()
            self.changed.emit()
        except Exception as e:
            QMessageBox.warning(self, "Instalar CLI", f"Error: {e}")

    def _login(self, key: str):
        """Lanza el login OAuth del provider en una terminal (interactivo)."""
        argv = aip.login_argv(key)
        if not argv:
            QMessageBox.information(self, "Login", "Este provider no usa login OAuth.")
            return
        cmd = " ".join(argv)
        try:
            pc.open_in_terminal(str(pc.app_config_dir()), command=cmd, hold=True)
            QMessageBox.information(
                self, "Login",
                f"Se abrió una terminal ejecutando:\n  {cmd}\n\n"
                "Completa el login ahí (puede abrir el navegador) y luego pulsa "
                "🔄 Re-detectar.",
            )
        except Exception as e:
            QMessageBox.warning(self, "Login", f"No se pudo abrir la terminal: {e}\n\n"
                                               f"Ejecuta manualmente: {cmd}")

    def _add_key(self, key: str):
        """Pide la API key y la guarda cifrada."""
        p = aip.PROVIDERS[key]
        key_id = p.get("key_id")
        if not key_id:
            return
        text, ok = QInputDialog.getText(
            self, f"API key — {p['name']}",
            f"Pega tu {p.get('env_var', 'API key')}:",
            echo=QLineEdit.EchoMode.Password,
        )
        if ok and text.strip():
            try:
                aip.save_key(key_id, text.strip())
                # Algunos CLIs (Codex) necesitan un paso extra tras guardar la key.
                post = p.get("post_key_argv")
                if post and pc.IS_LINUX:  # solo informamos; el login real lo hace el user
                    pass
                self.refresh()
                self.changed.emit()
                QMessageBox.information(self, "API key", "Key guardada (chmod 0600).")
            except Exception as e:
                QMessageBox.warning(self, "API key", f"Error guardando: {e}")

    def _remove_key(self, key: str):
        p = aip.PROVIDERS[key]
        key_id = p.get("key_id")
        if not key_id:
            return
        r = QMessageBox.question(self, "Quitar key",
                                 f"¿Quitar la API key de {p['name']}?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                aip.delete_key(key_id)
                self.refresh()
                self.changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Quitar key", f"Error: {e}")

    # ── Integración Figma (token MCP) ────────────────────────────────────
    # ── Modelo de Claude Code ────────────────────────────────────────────
    def _build_claude_model_row(self) -> QFrame:
        import app_prefs
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-bottom: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 4, 4, 4)

        label = QLabel(
            "🧠 <b>Modelo Claude Code</b> — se usa automáticamente en "
            "Vibe, Recrear, Galería y multi-agente (flag <code>--model</code>)."
        )
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        lay.addWidget(label, 1)

        combo = QComboBox()
        for model_id, desc in aip.CLAUDE_MODELS:
            combo.addItem(desc, model_id)
        current = app_prefs.claude_model(aip.CLAUDE_MODEL_DEFAULT)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i: (app_prefs.set_claude_model(combo.currentData() or ""),
                        self.changed.emit()))
        lay.addWidget(combo)
        self._claude_model_combo = combo
        return frame

    def _build_figma_row(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-top: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 8, 4, 4)
        self._figma_status = QLabel("…")
        self._figma_status.setTextFormat(Qt.TextFormat.RichText)
        self._figma_status.setWordWrap(True)
        lay.addWidget(self._figma_status, 1)
        self._figma_set = QPushButton("🔑 Añadir token")
        self._figma_set.clicked.connect(self._set_figma_key)
        self._figma_clear = QPushButton("🚪 Quitar")
        self._figma_clear.clicked.connect(self._remove_figma_key)
        lay.addWidget(self._figma_set)
        lay.addWidget(self._figma_clear)
        return frame

    def _set_figma_key(self):
        import os
        text, ok = QInputDialog.getText(
            self, "Token de Figma",
            "Pega tu Figma Personal Access Token\n"
            "(figma.com → Settings → Security → Personal access tokens, scope lectura):",
            echo=QLineEdit.EchoMode.Password,
        )
        if ok and text.strip():
            try:
                aip.save_key("figma", text.strip())
                os.environ["FIGMA_API_KEY"] = text.strip()  # disponible ya en esta sesión
                self.refresh()
                self.changed.emit()
                QMessageBox.information(
                    self, "Figma",
                    "Token guardado (chmod 0600). El MCP de Figma ya puede leer "
                    "tus diseños. Copia el link de un frame en Figma (clic derecho "
                    "→ Copy link to selection) y pídeselo al agente.")
            except Exception as e:
                QMessageBox.warning(self, "Figma", f"Error guardando: {e}")

    def _remove_figma_key(self):
        import os
        r = QMessageBox.question(self, "Quitar token", "¿Quitar el token de Figma?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                aip.delete_key("figma")
                os.environ.pop("FIGMA_API_KEY", None)
                self.refresh()
                self.changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Figma", f"Error: {e}")

    # ── 21st.dev (MCP Magic — componentes UI) ────────────────────────────
    def _build_21st_row(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-top: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 8, 4, 4)
        self._t21_status = QLabel("…")
        self._t21_status.setTextFormat(Qt.TextFormat.RichText)
        self._t21_status.setWordWrap(True)
        lay.addWidget(self._t21_status, 1)
        self._t21_set = QPushButton("🔑 Añadir key")
        self._t21_set.clicked.connect(self._set_21st_key)
        self._t21_clear = QPushButton("🚪 Quitar")
        self._t21_clear.clicked.connect(self._remove_21st_key)
        lay.addWidget(self._t21_set)
        lay.addWidget(self._t21_clear)
        return frame

    def _set_21st_key(self):
        import os
        text, ok = QInputDialog.getText(
            self, "API key de 21st.dev",
            "Pega tu API key de 21st.dev\n"
            "(GRATIS: 21st.dev → Sign up → Settings → API · 100 créditos/mes):",
            echo=QLineEdit.EchoMode.Password,
        )
        if ok and text.strip():
            try:
                aip.save_key("twentyfirst", text.strip())
                os.environ["TWENTYFIRST_API_KEY"] = text.strip()
                self.refresh()
                self.changed.emit()
                QMessageBox.information(
                    self, "21st.dev",
                    "Key guardada (chmod 0600). En los proyectos React el agente "
                    "podrá usar `/ui <descripción>` para traer componentes "
                    "profesionales de 21st.dev (el MCP `magic` se cablea solo).")
            except Exception as e:
                QMessageBox.warning(self, "21st.dev", f"Error guardando: {e}")

    def _remove_21st_key(self):
        import os
        r = QMessageBox.question(self, "Quitar key", "¿Quitar la key de 21st.dev?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                aip.delete_key("twentyfirst")
                os.environ.pop("TWENTYFIRST_API_KEY", None)
                self.refresh()
                self.changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "21st.dev", f"Error: {e}")

    # ── Firecrawl (búsqueda web avanzada de locales) ─────────────────────
    def _build_firecrawl_row(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-top: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 8, 4, 4)
        self._fc_status = QLabel("…")
        self._fc_status.setTextFormat(Qt.TextFormat.RichText)
        self._fc_status.setWordWrap(True)
        lay.addWidget(self._fc_status, 1)
        self._fc_set = QPushButton("🔑 Añadir key")
        self._fc_set.clicked.connect(self._set_firecrawl_key)
        self._fc_clear = QPushButton("🚪 Quitar")
        self._fc_clear.clicked.connect(self._remove_firecrawl_key)
        lay.addWidget(self._fc_set)
        lay.addWidget(self._fc_clear)
        return frame

    def _set_firecrawl_key(self):
        import os
        text, ok = QInputDialog.getText(
            self, "API key de Firecrawl",
            "Pega tu API key de Firecrawl (empieza por fc-)\n"
            "GRATIS: firecrawl.dev → Sign up → API Keys (500 búsquedas/mes):",
            echo=QLineEdit.EchoMode.Password,
        )
        if ok and text.strip():
            try:
                aip.save_key("firecrawl", text.strip())
                os.environ["FIRECRAWL_API_KEY"] = text.strip()
                self.refresh()
                self.changed.emit()
                QMessageBox.information(
                    self, "Firecrawl",
                    "Key guardada (chmod 0600). En 🔑 Locales, «🌐 todo internet» "
                    "usará Firecrawl para buscar+scrapear anuncios reales.")
            except Exception as e:
                QMessageBox.warning(self, "Firecrawl", f"Error guardando: {e}")

    def _remove_firecrawl_key(self):
        import os
        r = QMessageBox.question(self, "Quitar key", "¿Quitar la key de Firecrawl?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                aip.delete_key("firecrawl")
                os.environ.pop("FIRECRAWL_API_KEY", None)
                self.refresh()
                self.changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Firecrawl", f"Error: {e}")

    # ── Imágenes Runware (API key) ───────────────────────────────────────
    def _build_runware_row(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("QFrame { border-top: 1px solid #2a2a33; }")
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(4, 8, 4, 4)
        self._runware_status = QLabel("…")
        self._runware_status.setTextFormat(Qt.TextFormat.RichText)
        self._runware_status.setWordWrap(True)
        lay.addWidget(self._runware_status, 1)
        self._runware_set = QPushButton("🔑 Añadir key")
        self._runware_set.clicked.connect(self._set_runware_key)
        self._runware_clear = QPushButton("🚪 Quitar")
        self._runware_clear.clicked.connect(self._remove_runware_key)
        lay.addWidget(self._runware_set)
        lay.addWidget(self._runware_clear)
        return frame

    def _set_runware_key(self):
        import os
        text, ok = QInputDialog.getText(
            self, "API key de Runware",
            "Pega tu Runware API key\n(runware.ai → Dashboard → API keys):",
            echo=QLineEdit.EchoMode.Password,
        )
        if ok and text.strip():
            try:
                aip.save_key("runware", text.strip())
                os.environ["RUNWARE_API_KEY"] = text.strip()
                self.refresh()
                self.changed.emit()
                QMessageBox.information(
                    self, "Runware",
                    "Key guardada (chmod 0600). El operator ya puede generar "
                    "imágenes. Elige el modelo en la pestaña 🎨 Imágenes de Hermes.")
            except Exception as e:
                QMessageBox.warning(self, "Runware", f"Error guardando: {e}")

    def _remove_runware_key(self):
        import os
        r = QMessageBox.question(self, "Quitar key", "¿Quitar la API key de Runware?")
        if r == QMessageBox.StandardButton.Yes:
            try:
                aip.delete_key("runware")
                os.environ.pop("RUNWARE_API_KEY", None)
                self.refresh()
                self.changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Runware", f"Error: {e}")
