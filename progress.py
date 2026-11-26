"""Animated, colourable trigger progress bars that glow when they complete."""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QSizePolicy, QVBoxLayout, QWidget


class GlowBar(QWidget):
    """Rounded progress bar.

    * ``set_progress(value, maximum)`` animates smoothly to the new value.
    * ``celebrate()`` fills the bar, pulses a glow in the bar's colour, then
      drains back to the real value (the counter resets when a trigger fires).
    """

    def __init__(self, color: str = "#7c5cff", height: int = 22, font_px: int = 12,
                 show_text: bool = True, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._value = 0.0          # displayed (animated) value
        self._target = 0.0
        self._max = 1.0
        self._text = ""
        self._font_px = font_px
        self._show_text = show_text
        self._glow_t = 0.0
        self._celebrating = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.set_bar_height(height)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(450)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(0, 0, 0, 0))
        self.setGraphicsEffect(self._glow)

        self._pulse = QVariantAnimation(self)
        self._pulse.setStartValue(0.0)
        self._pulse.setKeyValueAt(0.5, 1.0)
        self._pulse.setEndValue(0.0)
        self._pulse.setDuration(700)
        self._pulse.setLoopCount(3)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.valueChanged.connect(self._on_pulse)
        self._pulse.finished.connect(self._end_celebrate)

    # ── configuration ─────────────────────────────────────────────────────────
    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def set_bar_height(self, h: int):
        self._h = max(4, int(h))
        # leave room around the bar for the glow so it isn't clipped
        self.setFixedHeight(self._h + 14)
        self.update()

    def set_font_px(self, px: int):
        self._font_px = max(7, int(px))
        self.update()

    def set_text(self, text: str):
        if text != self._text:
            self._text = text
            self.update()

    # ── values ────────────────────────────────────────────────────────────────
    def set_progress(self, value: float, maximum: float, animate: bool = True):
        self._max = max(1.0, float(maximum))
        value = max(0.0, min(float(value), self._max))
        if self._celebrating:
            self._target = value            # applied when the glow ends
            return
        if abs(value - self._target) < 1e-9 and not self._anim.state() == QVariantAnimation.State.Running:
            return
        self._target = value
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._value)
            self._anim.setEndValue(value)
            self._anim.start()
        else:
            self._value = value
            self.update()

    def celebrate(self):
        self._celebrating = True
        self._anim.stop()
        self._anim.setDuration(250)
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(self._max)
        self._anim.start()
        self._pulse.stop()
        self._pulse.start()

    def _end_celebrate(self):
        self._celebrating = False
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(0, 0, 0, 0))
        self._anim.setDuration(900)
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(self._target)
        self._anim.start()
        QTimer.singleShot(950, lambda: self._anim.setDuration(450))

    def _on_anim(self, v):
        self._value = float(v)
        self.update()

    def _on_pulse(self, t):
        self._glow_t = float(t)
        c = QColor(self._color)
        c.setAlpha(int(90 + 165 * self._glow_t))
        self._glow.setColor(c)
        self._glow.setBlurRadius(6 + 34 * self._glow_t)
        self.update()

    # ── painting ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(7, (self.height() - self._h) / 2, self.width() - 14, self._h)
        rad = self._h / 2

        track = QPainterPath()
        track.addRoundedRect(r, rad, rad)
        p.fillPath(track, QColor(20, 22, 32, 200))

        frac = self._value / self._max if self._max else 0
        if frac > 0:
            fw = max(self._h, r.width() * frac)
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(r.x(), r.y(), fw, r.height()), rad, rad)
            g = QLinearGradient(r.x(), 0, r.x() + fw, 0)
            base = QColor(self._color)
            g.setColorAt(0, base.darker(125))
            g.setColorAt(1, base.lighter(135 + int(40 * self._glow_t)))
            p.fillPath(fill.intersected(track), g)
            # glossy highlight on the top half
            hl = QPainterPath()
            hl.addRoundedRect(QRectF(r.x() + 2, r.y() + 1, fw - 4, r.height() / 2 - 1), rad / 2, rad / 2)
            p.fillPath(hl.intersected(track), QColor(255, 255, 255, 28 + int(40 * self._glow_t)))

        border = QColor(self._color)
        border.setAlpha(70 + int(185 * self._glow_t))
        p.setPen(QPen(border, 1.2))
        p.drawPath(track)

        if self._show_text and self._text and self._h >= 12:
            f = QFont("Segoe UI")
            f.setPixelSize(min(self._font_px, int(self._h * 0.8)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(r.translated(0, 1), Qt.AlignmentFlag.AlignCenter, self._text)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class ProgressStrip(QWidget):
    """Stack of GlowBars for triggers with ``show_progress`` (chat pane + overlay)."""

    def __init__(self, height: int = 22, font_px: int = 12):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 2)
        self.lay.setSpacing(0)
        self.bars: List[tuple] = []
        self.height_px = height
        self.font_px = font_px

    def set_size(self, height: int, font_px: int):
        self.height_px, self.font_px = height, font_px
        for _, bar in self.bars:
            bar.set_bar_height(height)
            bar.set_font_px(font_px)

    def rebuild(self, bindings):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.bars = []
        for b in bindings:                       # caller passes only the bars to show
            if b.show_progress:
                bar = GlowBar(b.color, self.height_px, self.font_px)
                self.lay.addWidget(bar)
                self.bars.append((b, bar))
        self.setVisible(bool(self.bars))
        self.refresh(animate=False)

    def refresh(self, animate: bool = True):
        for b, bar in self.bars:
            bar.set_color(b.color)
            bar.set_text(b.bar_label())
            bar.set_progress(b.acc, b.threshold, animate)

    def celebrate(self, binding):
        for b, bar in self.bars:
            if b is binding:
                bar.celebrate()
