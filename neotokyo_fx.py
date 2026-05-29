"""neotokyo_fx.py — Neo-Tokyo atmosphere for the main window.

A cheap, **static** background layer (cyberpunk grid + two radial glows)
that sits behind the app content when the Neo-Tokyo theme is active. No
animation, no per-frame cost — it only repaints on resize. Scanlines /
neon rain (the prototype's animated extras) are intentionally left out
to keep the desktop app light; this is the "grid + glows only" budget
option from the integration guide.

Usage (main window):

    from neotokyo_fx import AtmosphereContainer
    container = AtmosphereContainer()       # paints atmosphere in its bg
    container.layout().addWidget(self.tabs) # tabs float on top
    container.set_active(theme == "neotokyo")
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget, QVBoxLayout

ACCENT = "#00f0ff"      # cyan
ACCENT_2 = "#ff2e88"    # magenta
GRID_RGB = (120, 160, 255)
GRID_ALPHA = 0.045      # rgba(120,160,255,0.045)
GRID_STEP = 46


class AtmosphereContainer(QWidget):
    """Contenedor que pinta la atmósfera Neo-Tokyo en su fondo y aloja el
    contenido (las pestañas) encima. Cuando no está activo, no pinta nada
    extra (solo el fondo del tema) — coste cero para los otros temas."""

    def __init__(self, glow: float = 1.0, parent=None):
        super().__init__(parent)
        self._active = False
        self._glow = max(0.0, min(1.4, glow))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # El propio widget pinta; los hijos van encima.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_active(self, on: bool):
        if on != self._active:
            self._active = on
            self.update()

    def set_glow(self, glow: float):
        self._glow = max(0.0, min(1.4, glow))
        if self._active:
            self.update()

    def paintEvent(self, _ev):  # noqa: N802
        if not self._active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Glow cian (arriba-izquierda).
        ga = QRadialGradient(QPointF(w * 0.10, h * -0.05), max(w, h) * 0.7)
        ca = QColor(ACCENT); ca.setAlphaF(0.16 * self._glow)
        ga.setColorAt(0.0, ca)
        ga.setColorAt(0.6, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), ga)

        # Glow magenta (abajo-derecha).
        gb = QRadialGradient(QPointF(w * 0.95, h * 1.05), max(w, h) * 0.7)
        cb = QColor(ACCENT_2); cb.setAlphaF(0.13 * self._glow)
        gb.setColorAt(0.0, cb)
        gb.setColorAt(0.6, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), gb)

        # Grid 46px, alpha pesando hacia arriba (mask radial del prototipo).
        pen = QPen()
        pen.setWidthF(1.0)
        for y in range(0, h, GRID_STEP):
            fade = max(0.0, 1.0 - (y / max(1, h)) * 0.9)
            c = QColor(*GRID_RGB); c.setAlphaF(GRID_ALPHA * fade)
            pen.setColor(c); p.setPen(pen)
            p.drawLine(0, y, w, y)
        for x in range(0, w, GRID_STEP):
            c = QColor(*GRID_RGB); c.setAlphaF(GRID_ALPHA * 0.5)
            pen.setColor(c); p.setPen(pen)
            p.drawLine(x, 0, x, h)
        p.end()


# QSS extra que se aplica SOLO con el tema Neo-Tokyo activo, para que la
# atmósfera del contenedor asome entre los paneles (pane transparente).
NEOTOKYO_TRANSPARENCY_QSS = """
QTabWidget::pane { background: transparent; border: none; }
"""
