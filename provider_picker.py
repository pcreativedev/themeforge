"""
ProviderPicker — widget para elegir provider de IA (Claude/Codex/Gemini/
OpenCode/APIs/OpenRouter) con detección de estado, botón de login y
botón de configurar API key.

Emite `providerChanged(str)` con la key del provider cuando cambia.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import ai_providers as aip


class _ApiKeyDialog(QDialog):
    """Diálogo para introducir una API key. Muestra link al portal."""
    def __init__(self, parent, provider_key: str):
        super().__init__(parent)
        p = aip.PROVIDERS[provider_key]
        self.setWindowTitle(f"API key — {p['short']}")
        self.setMinimumWidth(520)

        url = p.get("key_url", "")
        info = QLabel(
            f"<b>{p['name']}</b><br>"
            f"Pega tu API key (env var: <code>{p['env_var']}</code>).<br><br>"
            f"Obtén una en: <a href='{url}'>{url}</a>"
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        existing = aip.load_keys().get(p["key_id"], "")
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setText(existing)
        self.edit.setPlaceholderText(f"{p['env_var']}=…")

        show_btn = QPushButton("👁 Mostrar")
        show_btn.setCheckable(True)
        def _toggle():
            self.edit.setEchoMode(
                QLineEdit.EchoMode.Normal if show_btn.isChecked()
                else QLineEdit.EchoMode.Password
            )
        show_btn.toggled.connect(_toggle)

        row = QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(show_btn)

        self.delete_chk = QPushButton("Eliminar key guardada")
        self.delete_chk.clicked.connect(self._delete)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(row)
        layout.addWidget(self.delete_chk)
        layout.addWidget(btns)

        self._provider_key = provider_key

    def _delete(self):
        p = aip.PROVIDERS[self._provider_key]
        aip.delete_key(p["key_id"])
        QMessageBox.information(self, "API key", "Key eliminada.")
        self.reject()

    def get_value(self) -> str:
        return self.edit.text().strip()


class ProviderPicker(QWidget):
    providerChanged = pyqtSignal(str)

    def __init__(self, parent=None, label: str = "Provider IA:"):
        super().__init__(parent)
        self._build_ui(label)
        self._refresh_status()

    def _build_ui(self, label: str):
        self.label = QLabel(label)
        self.combo = QComboBox()
        for key, p in aip.PROVIDERS.items():
            self.combo.addItem(p["name"], userData=key)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.status_lbl = QLabel("(detectando…)")
        self.status_lbl.setStyleSheet("color:#aaa;font-family:monospace;font-size:11px;")
        self.status_lbl.setWordWrap(True)

        self.btn_login = QPushButton("Login")
        self.btn_login.setToolTip("Abre Konsole con el comando de login del provider")
        self.btn_login.clicked.connect(self._on_login)

        self.btn_key = QPushButton("🔑 API key…")
        self.btn_key.setToolTip("Configura la API key (se guarda en ~/.config/themeforge/keys.json 0600)")
        self.btn_key.clicked.connect(self._on_key)

        self.btn_refresh = QPushButton("↻")
        self.btn_refresh.setToolTip("Refrescar estado del provider")
        self.btn_refresh.clicked.connect(self._refresh_status)

        top = QHBoxLayout()
        top.addWidget(self.label)
        top.addWidget(self.combo, 1)
        top.addWidget(self.btn_login)
        top.addWidget(self.btn_key)
        top.addWidget(self.btn_refresh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addLayout(top)
        root.addWidget(self.status_lbl)

    # ── API pública ────────────────────────────────────────────────
    def current_key(self) -> str:
        return self.combo.currentData() or "claude"

    def set_current_key(self, key: str):
        for i in range(self.combo.count()):
            if self.combo.itemData(i) == key:
                self.combo.setCurrentIndex(i)
                return

    # ── Handlers ───────────────────────────────────────────────────
    def _on_combo_changed(self, _idx: int):
        self._refresh_status()
        self.providerChanged.emit(self.current_key())

    def _refresh_status(self):
        key = self.current_key()
        state, info = aip.detect_status(key)
        color = {
            "ok": "#7dd87d",
            "need_login": "#ffd57d",
            "need_key": "#ffd57d",
            "missing_cli": "#ff7d7d",
        }.get(state, "#aaa")
        self.status_lbl.setStyleSheet(
            f"color:{color};font-family:monospace;font-size:11px;"
        )
        self.status_lbl.setText(info)

        p = aip.PROVIDERS[key]
        kind = p["auth_kind"]
        # Login solo si CLI tiene login_argv (oauth)
        self.btn_login.setEnabled(bool(p.get("login_argv")) and state != "missing_cli")
        # API key solo si es api o oauth_or_api
        self.btn_key.setEnabled(kind in ("api", "oauth_or_api"))

    def _on_login(self):
        key = self.current_key()
        p = aip.PROVIDERS[key]
        argv = p.get("login_argv")
        if not argv:
            QMessageBox.information(self, "Login", "Este provider no necesita login interactivo.")
            return
        if not aip.cli_in_path(key):
            QMessageBox.warning(
                self, "Login",
                f"`{p['command']}` no está en el PATH — instálalo primero.",
            )
            return
        if aip.open_login_in_konsole(key):
            QMessageBox.information(
                self, "Login",
                f"Konsole abierta con:\n  {' '.join(argv)}\n\n"
                "Completa el flujo en esa ventana y luego pulsa ↻ aquí para refrescar.",
            )
        else:
            QMessageBox.warning(
                self, "Login",
                f"No se pudo abrir Konsole.\nEjecuta manualmente:\n  {' '.join(argv)}",
            )

    def _on_key(self):
        key = self.current_key()
        p = aip.PROVIDERS[key]
        if p["auth_kind"] not in ("api", "oauth_or_api"):
            QMessageBox.information(self, "API key", "Este provider no usa API key.")
            return
        dlg = _ApiKeyDialog(self, key)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            value = dlg.get_value()
            if not value:
                return
            aip.save_key(p["key_id"], value)
            # Para providers que requieren registro adicional (codex --with-api-key)
            if p.get("post_key_argv"):
                ok, msg = aip.register_api_key_in_cli(key, value)
                if not ok:
                    QMessageBox.warning(
                        self, "API key",
                        f"Key guardada pero el registro en el CLI falló:\n{msg}",
                    )
            # Aplicar al entorno actual para que los procesos hijos las hereden
            aip.apply_all_known_keys()
            QMessageBox.information(self, "API key", "Key guardada y exportada al entorno.")
        self._refresh_status()
