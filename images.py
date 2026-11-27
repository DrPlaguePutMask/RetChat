"""Async image cache (badges / emotes) + built-in vector badge & platform icons."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Dict, Optional, Set, Union

from PyQt6.QtCore import (QBuffer, QByteArray, QIODevice, QObject, QPointF, QRectF, Qt, QUrl,
                          pyqtSignal)
from PyQt6.QtGui import (QColor, QFont, QImage, QMovie, QPainter, QPainterPath, QPixmap,
                         QPolygonF)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

CACHE_DIR = Path.home() / ".ret_chat_cache" / "img2"
UA = b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"

Img = Union[QPixmap, QMovie]


class ImageCache(QObject):
    """Downloads images once (memory + disk cache) and emits ``ready(url)``."""

    ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._nams: Dict[str, QNetworkAccessManager] = {}   # proxy URL ("" = direct) → manager
        self._imgs: Dict[str, Img] = {}
        self._pending: Set[str] = set()
        self._failed: Set[tuple] = set()                     # (url, proxy URL)
        self.animate = True

    # -- public -----------------------------------------------------------------
    def _nam_for(self, proxy_url: str) -> QNetworkAccessManager:
        nam = self._nams.get(proxy_url)
        if nam is None:
            nam = QNetworkAccessManager(self)
            nam.setRedirectPolicy(QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            if proxy_url:
                from urllib.parse import urlparse
                u = urlparse(proxy_url)
                kind = (QNetworkProxy.ProxyType.Socks5Proxy if u.scheme.startswith("socks")
                        else QNetworkProxy.ProxyType.HttpProxy)
                nam.setProxy(QNetworkProxy(kind, u.hostname or "127.0.0.1", u.port or 1080,
                                           u.username or "", u.password or ""))
            else:
                nam.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
            self._nams[proxy_url] = nam
        return nam

    def get(self, url: str, proxy: Optional[str] = None) -> Optional[Img]:
        """Return the image if cached, otherwise start loading it and return None.

        *proxy* is the channel's proxy spec, so emotes/badges from a blocked
        site load through the same proxy as its chat.
        """
        if not url:
            return None
        img = self._imgs.get(url)
        if img is not None:
            return img
        try:
            from connectors import resolve_proxy
            proxy_url = resolve_proxy(proxy) or ""
        except Exception:
            proxy_url = ""
        if url in self._pending or (url, proxy_url) in self._failed:
            return None
        path = self._path(url)
        if path.exists():
            try:
                if self._store(url, path.read_bytes()):
                    return self._imgs[url]
            except Exception:
                pass
        self._pending.add(url)
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", UA)
        req.setTransferTimeout(20000)
        reply = self._nam_for(proxy_url).get(req)
        reply.finished.connect(lambda r=reply, u=url, p=proxy_url: self._on_reply(r, u, p))
        return None

    def size_of(self, url: str) -> Optional[tuple]:
        img = self._imgs.get(url)
        if isinstance(img, QMovie):
            pm = img.currentPixmap()
            return (pm.width(), pm.height()) if not pm.isNull() else None
        if isinstance(img, QPixmap):
            return img.width(), img.height()
        return None

    def movies(self):
        return [m for m in self._imgs.values() if isinstance(m, QMovie)]

    # -- internals --------------------------------------------------------------
    @staticmethod
    def _path(url: str) -> Path:
        return CACHE_DIR / hashlib.sha1(url.encode("utf-8")).hexdigest()

    def _on_reply(self, reply: QNetworkReply, url: str, proxy_url: str = ""):
        self._pending.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._failed.add((url, proxy_url))
                return
            data = bytes(reply.readAll())
            if self._store(url, data):
                try:
                    self._path(url).write_bytes(data)
                except Exception:
                    pass
                self.ready.emit(url)
            else:
                self._failed.add((url, proxy_url))
        finally:
            reply.deleteLater()

    def _store(self, url: str, data: bytes) -> bool:
        if not data:
            return False
        # animated GIF / WebP → QMovie
        if self.animate and (data[:3] == b"GIF" or (data[:4] == b"RIFF" and b"ANIM" in data[:64])):
            buf = QBuffer()
            buf.setData(QByteArray(data))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            mv = QMovie()
            mv.setDevice(buf)
            mv._buf = buf                      # keep the buffer alive
            if mv.isValid() and mv.frameCount() != 1:
                mv.setCacheMode(QMovie.CacheMode.CacheAll)
                mv.jumpToFrame(0)
                mv.start()
                self._imgs[url] = mv
                return True
        img = QImage.fromData(data)
        if img.isNull():
            img = self._pil_decode(data)
        if img is None or img.isNull():
            return False
        self._imgs[url] = QPixmap.fromImage(img)
        return True

    @staticmethod
    def _pil_decode(data: bytes) -> Optional[QImage]:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            im.seek(0)
            out = io.BytesIO()
            im.convert("RGBA").save(out, "PNG")
            return QImage.fromData(out.getvalue())
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════════════════════
# Built-in icons (drawn, so they look sharp at any size)
# ══════════════════════════════════════════════════════════════════════════════

BADGE_STYLE = {
    #  kind          background  glyph   glyph colour
    "broadcaster": ("#e91916", "play",  "#ffffff"),
    "moderator":   ("#00ad03", "shield", "#ffffff"),
    "vip":         ("#e005b9", "◆",     "#ffffff"),
    "subscriber":  ("#8b5cf6", "★",     "#ffffff"),
    "founder":     ("#d4a017", "★",     "#ffffff"),
    "og":          ("#f59e0b", "OG",    "#1a1a1a"),
    "staff":       ("#2563eb", "⚙",     "#ffffff"),
    "verified":    ("#6b7280", "✓",     "#ffffff"),
    "partner":     ("#9146ff", "✓",     "#ffffff"),
    "friend":      ("#14b8a6", "♥",     "#ffffff"),
    "sub_gifter":  ("#f97316", "✚",     "#ffffff"),
    "member":      ("#16a34a", "★",     "#ffffff"),
}

PLATFORM_STYLE = {
    "twitch":  ("#9146ff", "T", "#ffffff"),
    "kick":    ("#53fc18", "K", "#0b0b0b"),
    "youtube": ("#ff0033", "play", "#ffffff"),
    "aparat":  ("#ed145b", "A", "#ffffff"),
    "onefa":   ("#2db5aa", "1", "#ffffff"),
}

_icon_cache: Dict[tuple, QPixmap] = {}


def _draw(bg: str, glyph: str, fg: str, size: int, round_: bool) -> QPixmap:
    scale = 2                                     # draw at 2x for crispness
    s = size * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(bg))
    r = QRectF(0, 0, s, s).adjusted(s * 0.04, s * 0.04, -s * 0.04, -s * 0.04)
    if round_:
        p.drawEllipse(r)
    else:
        p.drawRoundedRect(r, s * 0.22, s * 0.22)
    p.setBrush(QColor(fg))
    c = s / 2
    if glyph == "play":
        p.drawPolygon(QPolygonF([QPointF(c - s * 0.16, c - s * 0.22),
                                 QPointF(c - s * 0.16, c + s * 0.22),
                                 QPointF(c + s * 0.24, c)]))
    elif glyph == "shield":
        path = QPainterPath()
        path.moveTo(c, s * 0.18)
        path.lineTo(s * 0.78, s * 0.30)
        path.quadTo(s * 0.78, s * 0.70, c, s * 0.84)
        path.quadTo(s * 0.22, s * 0.70, s * 0.22, s * 0.30)
        path.closeSubpath()
        p.drawPath(path)
    else:
        p.setPen(QColor(fg))
        f = QFont("Segoe UI Symbol" if len(glyph) == 1 and not glyph.isalnum() else "Segoe UI")
        f.setBold(True)
        f.setPixelSize(int(s * (0.42 if len(glyph) > 1 else 0.6)))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


# Kick-style badges: Kick's colour gradients with a dark symbol on top.
# The symbols are RetChat's own drawings (not Kick's artwork).
KICK_STYLE = {
    #  kind                gradient from / to     glyph      shape
    "kick_moderator":   ("#00c7ff", "#0095ff", "gavel",   "square"),
    "kick_verified":    ("#1eff00", "#00ff8c", "check",   "seal"),
    "kick_founder":     ("#ffd84d", "#ffa31a", "star",    "square"),
    "kick_vip":         ("#ffb000", "#ff7a00", "crown",   "square"),   # Kick shows VIP as a crown
    "kick_og":          ("#00e5ff", "#c6ff3d", "ogstack", "dark"),     # gradient O/G letters on dark
    "kick_broadcaster": ("#ff6a4a", "#c70c00", "play",    "square"),
    "kick_staff":       ("#c58bff", "#7b2cff", "star",    "square"),
    "kick_sub_gifter":  ("#53fc18", "#32970e", "gift",    "square"),
    "kick_subscriber":  ("#deb2ff", "#bc66ff", "star",    "square"),
}


def _draw_kick(c1: str, c2: str, glyph: str, shape: str, size: int) -> QPixmap:
    from PyQt6.QtGui import QLinearGradient, QPen, QTransform
    scale = 2
    s = size * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    m = s * 0.04
    if shape == "dark":                          # dark tile, the gradient goes on the glyph instead
        p.setBrush(QColor("#141414"))
        p.drawRoundedRect(QRectF(m, m, s - 2 * m, s - 2 * m), s * 0.2, s * 0.2)
        if glyph == "ogstack":
            f = QFont("Segoe UI")
            f.setBold(True)
            f.setPixelSize(int(s * 0.5))
            path = QPainterPath()
            path.addText(0, 0, f, "O")
            path2 = QPainterPath()
            path2.addText(0, 0, f, "G")
            for pp, cy in ((path, s * 0.30), (path2, s * 0.70)):    # O on top, G below
                br = pp.boundingRect()
                pp.translate(s / 2 - br.center().x(), cy - br.center().y())
            p.setBrush(g)
            p.drawPath(path)
            p.drawPath(path2)
        p.end()
        pm.setDevicePixelRatio(scale)
        return pm
    if shape == "seal":                          # scalloped round seal
        path = QPainterPath()
        n, c = 12, s / 2
        import math
        for i in range(n * 2 + 1):
            a = math.pi * i / n - math.pi / 2
            rad = (s / 2 - m) * (1.0 if i % 2 == 0 else 0.84)
            pt = QPointF(c + rad * math.cos(a), c + rad * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
    else:
        p.drawRoundedRect(QRectF(m, m, s - 2 * m, s - 2 * m), s * 0.2, s * 0.2)
    ink = QColor("#0b0b0b")
    p.setBrush(ink)
    c = s / 2
    if glyph == "gavel":
        p.save()
        p.translate(c, c)
        p.rotate(-45)
        p.drawRoundedRect(QRectF(-s * 0.22, -s * 0.30, s * 0.44, s * 0.17), s * 0.03, s * 0.03)   # head
        p.drawRect(QRectF(-s * 0.045, -s * 0.15, s * 0.09, s * 0.42))                           # handle
        p.restore()
        p.drawRoundedRect(QRectF(s * 0.20, s * 0.74, s * 0.34, s * 0.07), s * 0.02, s * 0.02)   # block
    elif glyph == "check":
        pen = QPen(ink, s * 0.11)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(QPolygonF([QPointF(s * 0.30, s * 0.52), QPointF(s * 0.44, s * 0.65), QPointF(s * 0.70, s * 0.36)]))
    elif glyph == "crown":
        p.drawPolygon(QPolygonF([QPointF(s * 0.22, s * 0.68), QPointF(s * 0.18, s * 0.32), QPointF(s * 0.36, s * 0.48),
                                 QPointF(s * 0.50, s * 0.24), QPointF(s * 0.64, s * 0.48), QPointF(s * 0.82, s * 0.32),
                                 QPointF(s * 0.78, s * 0.68)]))
        p.drawRect(QRectF(s * 0.22, s * 0.71, s * 0.56, s * 0.07))
    elif glyph == "diamond":
        p.drawPolygon(QPolygonF([QPointF(s * 0.30, s * 0.30), QPointF(s * 0.70, s * 0.30), QPointF(s * 0.82, s * 0.43),
                                 QPointF(c, s * 0.80), QPointF(s * 0.18, s * 0.43)]))
    elif glyph == "play":
        p.drawPolygon(QPolygonF([QPointF(c - s * 0.15, c - s * 0.22), QPointF(c - s * 0.15, c + s * 0.22),
                                 QPointF(c + s * 0.23, c)]))
    elif glyph == "gift":
        p.drawRect(QRectF(s * 0.24, s * 0.46, s * 0.52, s * 0.30))      # box
        p.drawRect(QRectF(s * 0.20, s * 0.34, s * 0.60, s * 0.11))      # lid
        p.setBrush(QColor(c2))
        p.drawRect(QRectF(c - s * 0.04, s * 0.34, s * 0.08, s * 0.42))  # ribbon
        p.setBrush(ink)
        p.drawEllipse(QRectF(s * 0.34, s * 0.20, s * 0.14, s * 0.14))
        p.drawEllipse(QRectF(s * 0.52, s * 0.20, s * 0.14, s * 0.14))
    elif glyph == "star":
        import math
        pts = []
        for i in range(10):
            a = math.pi * i / 5 - math.pi / 2
            rad = s * (0.32 if i % 2 == 0 else 0.14)
            pts.append(QPointF(c + rad * math.cos(a), c + s * 0.03 + rad * math.sin(a)))
        p.drawPolygon(QPolygonF(pts))
    else:                                        # text glyph, e.g. "OG"
        p.setPen(ink)
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(int(s * 0.46))
        p.setFont(f)
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def all_badge_kinds():
    return list(BADGE_STYLE) + list(KICK_STYLE)


def badge_icon(kind: str, size: int = 18) -> Optional[QPixmap]:
    k = ("b", kind, size)
    if k in _icon_cache:
        return _icon_cache[k]
    if kind in KICK_STYLE:
        _icon_cache[k] = _draw_kick(*KICK_STYLE[kind], size)
        return _icon_cache[k]
    st = BADGE_STYLE.get(kind)
    if not st:
        return None
    _icon_cache[k] = _draw(*st, size, round_=False)
    return _icon_cache[k]


def _logo_path(platform: str) -> Path:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "logo" / f"{platform}.png"


def platform_icon(platform: str, size: int = 18) -> QPixmap:
    """Official platform logo from logo/<platform>.png (drawn fallback if missing)."""
    k = ("p", platform, size)
    if k not in _icon_cache:
        pm = QPixmap(str(_logo_path(platform)))
        if not pm.isNull():
            scale = 2                                # keep it crisp on HiDPI screens
            pm = pm.scaled(size * scale, size * scale, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(scale)
        else:
            st = PLATFORM_STYLE.get(platform, ("#64748b", "?", "#ffffff"))
            pm = _draw(*st, size, round_=True)
        _icon_cache[k] = pm
    return _icon_cache[k]
