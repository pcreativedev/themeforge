"""
LicensingPanel — pestaña que se conecta al panel admin propio (URL
configurada en `~/.config/themeforge/licensing.json`, clave
`panel_base`).

Si no hay archivo de config la URL será un placeholder y el panel
quedará desactivado en la práctica (las llamadas fallarán).

Funciones:
  - Listar versiones de productos (GET /api/products/versions)
  - Listar licencias (GET /api/licenses)
  - Crear licencia dev/test (POST /api/licenses)
  - Listar últimas ventas Gumroad (GET /api/gumroad)
  - Lanzar release (POST /api/products/versions/release)
  - Notify-update (POST /api/tools/notify-update)
"""
from __future__ import annotations

import json
from urllib import error as urlerr
from urllib import request as urlreq

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from licensing_config import load as _load_licensing_config

PANEL_BASE = _load_licensing_config()["panel_base"]
TIMEOUT = 8


def _api(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    """Llamada simple al panel admin definido en licensing.json."""
    url = PANEL_BASE.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urlreq.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urlreq.urlopen(req, timeout=TIMEOUT) as r:
            text = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(text)
            except Exception:
                return r.status, {"raw": text}
    except urlerr.HTTPError as e:
        return e.code, {"error": e.reason}
    except Exception as e:
        return 0, {"error": str(e)}


class LicensingPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        from licensing_config import load as _load_cfg
        cfg = _load_cfg()
        title_text = cfg.get("panel_label") or "Panel admin"
        title = QLabel(title_text)
        f = QFont(); f.setPointSize(18); f.setBold(True)
        title.setFont(f)
        subtitle = QLabel(f"Conectando a <code>{PANEL_BASE}</code>")
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        subtitle.setStyleSheet("color:#888;")

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_licenses_tab(), "Licencias")
        self.tabs.addTab(self._build_products_tab(), "Productos / Versiones")
        self.tabs.addTab(self._build_gumroad_tab(), "Ventas (Gumroad)")
        self.tabs.addTab(self._build_tools_tab(), "Tools")

        root = QVBoxLayout(self)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.tabs, 1)

    # ── LICENCIAS ────────────────────────────────────────────────────
    def _build_licenses_tab(self) -> QWidget:
        w = QWidget()

        self.lic_table = QTableWidget()
        self.lic_table.setColumnCount(6)
        self.lic_table.setHorizontalHeaderLabels(["Key", "Product", "Type", "Email", "Domains", "Status"])
        self.lic_table.horizontalHeader().setStretchLastSection(True)

        self.btn_lic_refresh = QPushButton("↻ Cargar licencias")
        self.btn_lic_refresh.clicked.connect(self._load_licenses)
        self.lic_filter = QLineEdit()
        self.lic_filter.setPlaceholderText("Filtrar por product (vacío = todos)")

        # Crear licencia dev/test
        self.new_product = QLineEdit()
        self.new_product.setPlaceholderText("aurora")
        self.new_email = QLineEdit()
        self.new_email.setPlaceholderText("buyer@example.com")
        self.new_type = QComboBox()
        for t in ("regular", "pro", "extended", "developer"):
            self.new_type.addItem(t)
        self.new_max = QSpinBox()
        self.new_max.setRange(1, 999); self.new_max.setValue(1)
        self.btn_lic_create = QPushButton("Crear licencia")
        self.btn_lic_create.clicked.connect(self._create_license)

        create_form = QFormLayout()
        create_form.addRow("Product slug:", self.new_product)
        create_form.addRow("Email comprador:", self.new_email)
        create_form.addRow("Tipo:", self.new_type)
        create_form.addRow("Max domains:", self.new_max)
        create_form.addRow("", self.btn_lic_create)
        create_box = QGroupBox("Crear licencia (dev / test)")
        create_box.setLayout(create_form)

        top = QHBoxLayout()
        top.addWidget(self.lic_filter, 1)
        top.addWidget(self.btn_lic_refresh)

        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.lic_table, 1)
        lay.addWidget(create_box)
        return w

    def _load_licenses(self):
        prod = self.lic_filter.text().strip()
        path = "/api/licenses" + (f"?product={prod}" if prod else "")
        code, data = _api(path)
        if code != 200:
            QMessageBox.warning(self, "Licencias", f"HTTP {code}: {data.get('error','')}")
            return
        licenses = data.get("licenses", [])
        self.lic_table.setRowCount(0)
        for lic in licenses:
            r = self.lic_table.rowCount()
            self.lic_table.insertRow(r)
            self.lic_table.setItem(r, 0, QTableWidgetItem(lic.get("key", "")))
            self.lic_table.setItem(r, 1, QTableWidgetItem(lic.get("product", "")))
            self.lic_table.setItem(r, 2, QTableWidgetItem(lic.get("type", "")))
            self.lic_table.setItem(r, 3, QTableWidgetItem(lic.get("email", "")))
            doms = lic.get("domains") or []
            self.lic_table.setItem(r, 4, QTableWidgetItem(f"{len(doms)}/{lic.get('max_domains','?')}"))
            status = "revoked" if lic.get("revoked") else ("expired" if lic.get("expired") else "active")
            self.lic_table.setItem(r, 5, QTableWidgetItem(status))
        self.lic_table.resizeColumnsToContents()

    def _create_license(self):
        product = self.new_product.text().strip()
        email = self.new_email.text().strip()
        if not product or not email:
            QMessageBox.warning(self, "Faltan datos", "Product y email son obligatorios.")
            return
        body = {
            "product": product,
            "email": email,
            "type": self.new_type.currentText(),
            "max_domains": self.new_max.value(),
        }
        code, data = _api("/api/licenses", "POST", body)
        if code in (200, 201):
            # Backend devuelve {"license": {key, type, product, email, ...}}.
            lic = data.get("license") if isinstance(data, dict) else None
            key = (lic or {}).get("key") or data.get("key") or "(sin key)"
            QMessageBox.information(self, "Licencia creada",
                f"Key: {key}\n\nLa licencia ya está activa.")
            self._load_licenses()
        else:
            QMessageBox.warning(self, "Error", f"HTTP {code}: {data.get('error','')}")

    # ── PRODUCTOS ────────────────────────────────────────────────────
    def _build_products_tab(self) -> QWidget:
        w = QWidget()
        self.prod_table = QTableWidget()
        self.prod_table.setColumnCount(6)
        self.prod_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Current", "Latest release", "Tags", "Repo"]
        )
        self.prod_table.horizontalHeader().setStretchLastSection(True)
        self.btn_prod_refresh = QPushButton("↻ Cargar versiones")
        self.btn_prod_refresh.clicked.connect(self._load_products)
        lay = QVBoxLayout(w)
        lay.addWidget(self.btn_prod_refresh)
        lay.addWidget(self.prod_table, 1)
        return w

    def _load_products(self):
        code, data = _api("/api/products/versions")
        if code != 200:
            QMessageBox.warning(self, "Productos", f"HTTP {code}: {data.get('error','')}")
            return
        products = data.get("products") or []
        self.prod_table.setRowCount(0)
        for p in products:
            r = self.prod_table.rowCount()
            self.prod_table.insertRow(r)
            self.prod_table.setItem(r, 0, QTableWidgetItem(str(p.get("id") or "?")))
            self.prod_table.setItem(r, 1, QTableWidgetItem(str(p.get("name") or "?")))
            self.prod_table.setItem(r, 2, QTableWidgetItem(str(p.get("currentVersion") or "—")))
            latest = p.get("latestRelease")
            if isinstance(latest, dict):
                latest_txt = f"{latest.get('tag_name') or latest.get('name') or '—'}"
                if latest.get("published_at"):
                    latest_txt += f"  ({latest['published_at'][:10]})"
            else:
                latest_txt = "—"
            self.prod_table.setItem(r, 3, QTableWidgetItem(latest_txt))
            self.prod_table.setItem(r, 4, QTableWidgetItem(str(len(p.get("tags") or []))))
            self.prod_table.setItem(r, 5, QTableWidgetItem(str(p.get("repo") or "?")))
        self.prod_table.resizeColumnsToContents()

    # ── GUMROAD ──────────────────────────────────────────────────────
    def _build_gumroad_tab(self) -> QWidget:
        w = QWidget()
        self.gum_table = QTableWidget()
        self.gum_table.setColumnCount(5)
        self.gum_table.setHorizontalHeaderLabels(["Date", "Product", "Buyer", "Price", "License"])
        self.gum_table.horizontalHeader().setStretchLastSection(True)
        self.btn_gum_refresh = QPushButton("↻ Cargar ventas Gumroad")
        self.btn_gum_refresh.clicked.connect(self._load_gumroad)
        lay = QVBoxLayout(w)
        lay.addWidget(self.btn_gum_refresh)
        lay.addWidget(self.gum_table, 1)
        return w

    def _load_gumroad(self):
        code, data = _api("/api/gumroad")
        if code != 200:
            QMessageBox.warning(self, "Gumroad", f"HTTP {code}: {data.get('error','')}")
            return
        sales = data.get("sales") or data.get("data") or (data if isinstance(data, list) else [])
        self.gum_table.setRowCount(0)
        for s in sales or []:
            r = self.gum_table.rowCount()
            self.gum_table.insertRow(r)
            self.gum_table.setItem(r, 0, QTableWidgetItem(str(s.get("created_at") or s.get("date") or "?")))
            self.gum_table.setItem(r, 1, QTableWidgetItem(str(s.get("product_name") or s.get("product") or "?")))
            self.gum_table.setItem(r, 2, QTableWidgetItem(str(s.get("email") or s.get("buyer") or "?")))
            self.gum_table.setItem(r, 3, QTableWidgetItem(str(s.get("formatted_display_price") or s.get("price") or "?")))
            self.gum_table.setItem(r, 4, QTableWidgetItem(str(s.get("license_key") or "")))
        self.gum_table.resizeColumnsToContents()

    # ── INTEGRATIONS STATUS ──────────────────────────────────────────
    def _build_tools_tab(self) -> QWidget:
        w = QWidget()
        self.tool_output = QTextEdit()
        self.tool_output.setReadOnly(True)
        self.tool_output.setMinimumHeight(180)
        self.tool_output.setStyleSheet("background:#1e1e25;color:#e6e6e6;font-family:monospace;font-size:13px;")

        self.btn_integrations = QPushButton("↻ Comprobar estado de integraciones")
        self.btn_integrations.clicked.connect(self._check_integrations)

        # Ping URL externa (usa /api/tools/ping del panel)
        self.ping_url = QLineEdit()
        self.ping_url.setPlaceholderText("https://gumroad.com/")
        self.btn_ping_url = QPushButton("📡 Hacer ping a esa URL")
        self.btn_ping_url.clicked.connect(self._ping_url)
        ping_form = QFormLayout()
        ping_form.addRow("URL:", self.ping_url)
        ping_form.addRow("", self.btn_ping_url)
        ping_box = QGroupBox("Probar URL desde el panel (uptime check)")
        ping_box.setLayout(ping_form)

        lay = QVBoxLayout(w)
        lay.addWidget(self.btn_integrations)
        lay.addWidget(ping_box)
        lay.addWidget(QLabel("Output:"))
        lay.addWidget(self.tool_output, 1)
        return w

    def _check_integrations(self):
        code, data = _api("/api/integrations/status")
        if code != 200:
            self.tool_output.append(f"HTTP {code}: {json.dumps(data)}\n")
            return
        status = data.get("status", {})
        summary = data.get("summary", "")
        lines = [f"=== Integraciones panel admin — {summary} ===", ""]
        for key, ok in sorted(status.items()):
            mark = "✓" if ok else "✗"
            lines.append(f"  {mark}  {key}")
        self.tool_output.setPlainText("\n".join(lines))

    def _ping_url(self):
        url = self.ping_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Faltan datos", "Pon una URL.")
            return
        code, data = _api("/api/tools/ping", "POST", {"url": url})
        self.tool_output.append(f"POST /api/tools/ping {{url:{url}}} → {code}\n{json.dumps(data, indent=2)}\n")
