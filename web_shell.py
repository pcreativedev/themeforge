"""web_shell.py — POC: render the Neo-Tokyo web prototype inside a Qt window.

This is the "Forma 1" proof-of-concept: the EXACT design (the React/HTML
prototype Claude Design produced) rendered pixel-for-pixel inside the app
via QWebEngineView (same Chromium engine), wired to the real ThemeForge
Python backend through a QWebChannel bridge.

What it proves:
  - The prototype runs unmodified inside Qt (served over a local HTTP
    origin so its `type="text/babel" src=` files load correctly).
  - A native bridge object (`window.tfBridge`) exposes real Python methods
    to the page. The POC wires ONE real action: `list_stacks()` returns the
    actual ThemeForge STACKS, and the page shows a confirmation banner.

Run standalone:

    python3 web_shell.py

Later, the same WebShell widget can be embedded as a tab in the main app
and the bridge grown to cover create_project / run_preflight / build_zip /
gallery / cost / etc.
"""
from __future__ import annotations

import json
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSlot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

WEBUI_DIR = Path(__file__).resolve().parent / "webui" / "neotokyo"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(directory: Path, port: int) -> ThreadingHTTPServer:
    """Arranca un servidor HTTP en un hilo daemon sirviendo `directory`."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


class ThemeForgeBridge(QObject):
    """Objeto puente expuesto a la página como `window.tfBridge`. Cada
    @pyqtSlot es invocable desde JavaScript. Aquí va la lógica REAL de
    ThemeForge (de momento, solo la acción del POC)."""

    @pyqtSlot(result=str)
    def list_stacks(self) -> str:
        """Acción real: devuelve los stacks de verdad de ThemeForge."""
        try:
            from stacks import STACKS
            data = [
                {"key": k, "name": v.get("name", k),
                 "category": v.get("category", ""),
                 "language": v.get("language", "")}
                for k, v in STACKS.items() if k != "none"
            ]
            return json.dumps(data)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @pyqtSlot(str, result=str)
    def ping(self, msg: str) -> str:
        return json.dumps({"pong": msg})


class WebShell(QWidget):
    """Ventana/widget que sirve el prototipo y lo embebe en un WebEngineView
    con el puente nativo conectado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._httpd = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWebChannel import QWebChannel
        except Exception as e:
            root.addWidget(QLabel(f"QtWebEngine no disponible: {e}"))
            return

        if not (WEBUI_DIR / "index.html").is_file():
            root.addWidget(QLabel(f"No se encuentra el prototipo en {WEBUI_DIR}"))
            return

        port = _free_port()
        self._httpd = _serve(WEBUI_DIR, port)

        self._view = QWebEngineView()
        self._bridge = ThemeForgeBridge()
        self._channel = QWebChannel(self._view.page())
        self._channel.registerObject("bridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._view.setUrl(QUrl(f"http://127.0.0.1:{port}/index.html"))
        root.addWidget(self._view)

    def shutdown(self):
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            self._httpd = None

    def closeEvent(self, ev):  # noqa: N802
        self.shutdown()
        super().closeEvent(ev)


def main():
    import sys
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    # QtWebEngine exige compartir contexto OpenGL antes de crear la QApplication.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    w = WebShell()
    w.resize(1280, 820)
    w.setWindowTitle("ThemeForge // Neo-Tokyo (WebEngine POC)")
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
