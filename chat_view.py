"""Chat display.

Every message is laid out in QTextDocuments and drawn on one canvas:

* **Bubbles** layout – a *name tab* (icons + name, own background) sits on top
  of the *message box*; both share one continuous outline, so there is no line
  where they meet.  Optional round profile picture beside the message.
* **Compact** layout – the classic one line per message.

Messages that count toward a trigger glow in that trigger's colour, new
messages slide in while older ones glide up, messages can fade out after N
seconds, and an optional rain layer drops the message's emoji / emote.
"""

from __future__ import annotations

import math
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QUrl, QVariantAnimation
from PyQt6.QtGui import (QAbstractTextDocumentLayout, QColor, QConicalGradient, QFont, QFontMetricsF,
                         QLinearGradient, QMovie, QPainter, QPainterPath,
                         QPalette, QPen, QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor,
                         QTextDocument, QTextImageFormat, QTextOption)
from PyQt6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from images import ImageCache, badge_icon, platform_icon

RTL_RE = re.compile("[֑-ࣿיִ-﷽ﹰ-ﻼ]")
LTR_RE = re.compile(r"[A-Za-z]")
# one emoji "character" incl. flags, skin tones, variation selectors and ZWJ sequences
EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2})"
    "|(?:[\U0001F300-\U0001FAFF☀-➿⬀-⯿⌀-⏿]"
    "[\U0001F3FB-\U0001F3FF️]?"
    "(?:‍[\U0001F300-\U0001FAFF☀-➿][\U0001F3FB-\U0001F3FF️]?)*)")


@dataclass
class ChatStyle:
    font_family: str = "Segoe UI"
    font_size: int = 13
    color_text: str = "#e6e8ef"
    color_user: str = "#7cc4ff"
    color_reply: str = "#8b90a5"
    use_user_colors: bool = True       # platform colour per user (Twitch/Kick/OneFa)
    bg: str = "#12131a"                # chat AREA background (behind all bubbles)
    bg_alpha: float = 0.0
    direction: str = "auto"            # auto | rtl | ltr
    show_platform: bool = True
    show_badges: bool = True
    show_time: bool = False
    show_history: bool = True
    highlight_triggers: bool = True    # glow on messages that count toward a trigger
    max_messages: int = 150
    line_gap: int = 4
    show_bots: bool = True
    bar_height: int = 22               # trigger progress bars
    bar_font: int = 12
    layout: str = "bubbles"            # bubbles | compact
    bubble_bg: str = "#1d2130"         # message box background
    bubble_alpha: float = 0.88
    name_bg: str = "#2a3046"           # name tab background (bubbles layout)
    radius: int = 14
    rain_enabled: bool = False         # emoji / emote rain
    rain_triggers_only: bool = False
    rain_cooldown: float = 4.0
    rain_amount: int = 28
    anim_in: str = "side"              # side | right | left | fade | none  (new-message animation)
    fade_after: float = 0.0            # seconds before a message fades out (0 = never)
    border_width: int = 1              # border around each message (0 = none)
    border_color: str = "#3a4158"
    name_scale: float = 0.8            # name size relative to the message text
    show_avatars: bool = True          # profile pictures
    # special effects per site and role, e.g. {"kick": {"og": "rainbow", "vip": "glow"}}
    effects: dict = field(default_factory=dict)

    def to_dict(self):
        return dict(self.__dict__)

    @staticmethod
    def from_dict(d: dict) -> "ChatStyle":
        s = ChatStyle()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                try:
                    setattr(s, k, type(getattr(s, k))(v))
                except (TypeError, ValueError):
                    pass
        return s


def _readable(color: Optional[str], fallback: str) -> str:
    """Brighten user colours that would be unreadable on a dark background."""
    if not color:
        return fallback
    c = QColor(color)
    if not c.isValid():
        return fallback
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    if lum < 0.42:
        h, s, l, _ = c.getHslF()
        c.setHslF(h if h >= 0 else 0, min(s, 0.9), max(l, 0.68), 1.0)
    return c.name()


FX_CODES = ("none", "glow", "pulse", "rainbow", "rborder", "shine")
FX_COLORS = {"og": "#fbbf24", "vip": "#f472b6", "sub": "#a78bfa"}
FX_ROLES = ("sub", "vip", "og")
FX_ANIMATED = {"pulse", "rainbow", "rborder", "shine"}


def effect_for(msg: dict, effects: dict):
    """(effect, colour) for a message from its site + role, or (None, None).

    OG beats VIP beats Subscriber when someone has several."""
    eff = (effects or {}).get(msg.get("platform", ""), {}) or {}
    if not eff:
        return None, None
    icons = {b.get("icon") for b in msg.get("badges") or []}
    roles = set(msg.get("role") or [])
    for key, has in (("og", bool(icons & {"og", "kick_og"})),
                     ("vip", "vip" in roles or bool(icons & {"vip", "kick_vip"})),
                     ("sub", "subscription" in roles)):
        code = eff.get(key, "none")
        if has and code and code != "none":
            return code, FX_COLORS[key]
    return None, None


def rain_symbol(msg: dict) -> Optional[dict]:
    """First emote (``{"url": …}``) or emoji (``{"emoji": …}``) in a message, if any."""
    for p in msg.get("parts") or []:
        if p.get("type") == "emote" and p.get("url"):
            return {"url": p["url"], "name": p.get("name", "")}
        if p.get("type") == "text":
            m = EMOJI_RE.search(p.get("text", ""))
            if m:
                return {"emoji": m.group(0)}
    return None


class _Item:
    __slots__ = ("msg", "doc", "head", "urls", "rtl", "system", "x", "y", "w", "h", "tw", "th",
                 "ax", "av", "born", "glow", "yd", "anim", "cache", "shp", "avpm", "fx", "fxc", "nm", "fhw")

    def __init__(self, msg: dict):
        self.msg = msg
        self.doc: Optional[QTextDocument] = None      # message text (or whole line in compact)
        self.head: Optional[QTextDocument] = None     # name tab (bubbles layout)
        self.urls: Dict[str, str] = {}                # resource name → image url
        self.rtl = False
        self.system = bool(msg.get("system"))
        self.x = self.y = self.w = self.h = 0.0       # message box (bubbles) / line (compact)
        self.tw = self.th = 0.0                       # name tab size
        self.ax: Optional[float] = None               # avatar x (None = no avatar)
        self.av: Optional[str] = msg.get("avatar") or None
        now = time.time()
        self.born = msg.setdefault("_shown_at", now)  # shared by all views → same fade timing
        self.anim = (now - self.born) < 0.4 and not msg.get("history")
        self.yd: Optional[float] = None               # drawn y (eases toward y → smooth slide)
        self.glow: Optional[str] = None               # glow colour for trigger messages
        self.cache: Optional[QPixmap] = None          # text drawn once; repaints just copy it
        self.shp = None                               # cached outline paths (relative to the item)
        self.avpm: Optional[tuple] = None             # cached round avatar (state, pixmap)
        self.fx: Optional[str] = None                 # special effect (sub / VIP / OG)
        self.fxc: Optional[str] = None
        self.nm: Optional[str] = None                 # shortened name in use (None = full name)
        self.fhw = 0.0                                # name-tab width with the full name


# ══════════════════════════════════════════════════════════════════════════════
# Canvas
# ══════════════════════════════════════════════════════════════════════════════

class _Canvas(QWidget):
    def __init__(self, view: "ChatView"):
        super().__init__()
        self.view = view
        self.setAutoFillBackground(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            self.view._relayout_soon()

    def paintEvent(self, e):
        v = self.view
        st = v.style_
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = e.rect()
        bubbles = st.layout == "bubbles"
        alpha_bg = max(0.0, min(1.0, st.bubble_alpha))
        bub = QColor(st.bubble_bg)
        bub.setAlphaF(alpha_bg)
        tabc = QColor(st.name_bg)
        tabc.setAlphaF(alpha_bg)
        border = QColor(st.border_color)
        now = time.time()
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(QPalette.ColorRole.Text, QColor(st.color_text))
        for it in v._items:
            y = it.yd if it.yd is not None else it.y
            if y + it.h < clip.top() - 20 or y > clip.bottom() + 20:
                continue
            alpha, dx = v._anim_state(it, now)
            if alpha <= 0.01:
                continue
            p.save()
            p.setOpacity(alpha)
            glow = bool(it.glow and st.highlight_triggers)
            if it.system:
                p.drawPixmap(QPointF(it.x + dx, y), v._text_pixmap(it, ctx))
                p.restore()
                continue
            if it.ax is not None:
                v._draw_avatar(p, it, it.ax + dx, y + (v._tab_pad()[1] if bubbles else v._pads(it)[1]))
            if bubbles:
                if it.shp is None:
                    it.shp = v._shapes(it, 0.0, 0.0)
                _tab, _body, shape, tab_path, body_path = it.shp
                p.translate(it.x + dx, y)
                fx = it.fx
                if glow:
                    self._glow(p, shape, QColor(it.glow), v._glow_strength(it, now))
                elif fx in ("glow", "pulse", "rainbow"):
                    self._glow(p, shape, v._fx_color(it, now), v._fx_strength(it, now))
                p.fillPath(body_path, bub)
                p.fillPath(tab_path, tabc)
                if glow:
                    c = QColor(it.glow)
                    c.setAlphaF(min(1.0, 0.55 + 0.45 * v._glow_strength(it, now)))
                    p.setPen(QPen(c, 1.6))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(shape)
                elif fx == "rborder":
                    v._rainbow_border(p, shape, now)
                elif fx in ("glow", "pulse", "rainbow"):
                    c = v._fx_color(it, now)
                    c.setAlphaF(0.85)
                    p.setPen(QPen(c, 1.4))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(shape)
                elif st.border_width > 0:
                    p.setPen(QPen(border, st.border_width))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(shape)                  # one outline – no line where tab meets box
                if fx == "shine":
                    v._shine(p, shape, it, now)
                p.drawPixmap(QPointF(0, 0), v._text_pixmap(it, ctx))
            else:
                r = QRectF(it.x + dx, y, it.w, it.h)
                line = QPainterPath()
                line.addRoundedRect(r, 6, 6)
                fx = it.fx
                if glow:
                    c = QColor(it.glow)
                    c.setAlphaF(0.22)
                    p.fillPath(line, c)
                elif fx in ("glow", "pulse", "rainbow"):
                    self._glow(p, line, v._fx_color(it, now), v._fx_strength(it, now) * 0.7)
                if fx == "rborder" and not glow:
                    v._rainbow_border(p, line, now)
                elif fx == "shine":
                    v._shine(p, line, it, now)
                if st.border_width > 0 and not (fx == "rborder" and not glow):
                    p.setPen(QPen(border, st.border_width))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    hw = st.border_width / 2
                    p.drawRoundedRect(r.adjusted(hw, hw, -hw, -hw), 6, 6)
                p.drawPixmap(QPointF(r.x(), r.y()), v._text_pixmap(it, ctx))
            p.restore()
        p.end()

    @staticmethod
    def _glow(p: QPainter, shape: QPainterPath, c: QColor, s: float):
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(9, 0, -1):
            cc = QColor(c)
            cc.setAlphaF(max(0.0, min(1.0, s * 0.22 * (1 - i / 10))))
            p.setPen(QPen(cc, i * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(shape)


# ══════════════════════════════════════════════════════════════════════════════
# Emoji / emote rain
# ══════════════════════════════════════════════════════════════════════════════

class RainLayer(QWidget):
    """Transparent layer on top of the chat that drops emoji / emote images."""

    MAX_PARTICLES = 320

    def __init__(self, parent: QWidget, images: ImageCache):
        super().__init__(parent)
        self.images = images
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.parts: List[dict] = []
        self._emoji_pm: Dict[str, QPixmap] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _emoji_pixmap(self, emoji: str) -> QPixmap:
        """Colour emoji are very slow to draw as text – render once at 64 px."""
        pm = self._emoji_pm.get(emoji)
        if pm is None:
            dpr = self.devicePixelRatioF() or 1.0
            size = 64
            pm = QPixmap(int(size * dpr), int(size * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(int(size * 0.82))
            p.setFont(f)
            p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, emoji)
            p.end()
            if len(self._emoji_pm) > 200:
                self._emoji_pm.clear()
            self._emoji_pm[emoji] = pm
        return pm

    def start(self, sym: dict, amount: int = 28, proxy: Optional[str] = None):
        if self.width() < 20 or self.height() < 20:
            return
        if sym.get("url"):
            self.images.get(sym["url"], proxy)          # make sure it's loading
        elif sym.get("emoji"):
            self._emoji_pixmap(sym["emoji"])
        t0 = time.time()
        room = self.MAX_PARTICLES - len(self.parts)
        for _ in range(max(0, min(amount, room))):
            size = random.uniform(22, 46)
            self.parts.append({
                "url": sym.get("url"), "emoji": sym.get("emoji"),
                "x": random.uniform(size / 2, max(size, self.width() - size / 2)),
                "size": size, "t0": t0 + random.uniform(0, 1.4),
                "speed": random.uniform(150, 330), "sway": random.uniform(6, 34),
                "phase": random.uniform(0, 6.28), "spin": random.uniform(-110, 110),
            })
        self.raise_()
        if not self._timer.isActive():
            self._timer.start(16)

    def _tick(self):
        now, h = time.time(), self.height()
        self.parts = [q for q in self.parts
                      if now < q["t0"] or -q["size"] + q["speed"] * (now - q["t0"]) < h + q["size"]]
        if not self.parts:
            self._timer.stop()
        self.update()

    def paintEvent(self, _):
        if not self.parts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        now, h = time.time(), self.height()
        font = QFont("Segoe UI Emoji")
        for q in self.parts:
            age = now - q["t0"]
            if age < 0:
                continue
            y = -q["size"] + q["speed"] * age
            x = q["x"] + q["sway"] * math.sin(q["phase"] + age * 2.2)
            p.save()
            p.setOpacity(max(0.0, min(1.0, (h - y) / 90.0)))
            p.translate(x, y)
            p.rotate(q["spin"] * age)
            s = q["size"]
            if q["url"]:
                img = self.images._imgs.get(q["url"])
                pm = img.currentPixmap() if isinstance(img, QMovie) else img
                if isinstance(pm, QPixmap) and not pm.isNull():
                    ratio = pm.width() / max(1, pm.height())
                    w = s * ratio
                    p.drawPixmap(QRectF(-w / 2, -s / 2, w, s), pm, QRectF(pm.rect()))
            elif q["emoji"]:
                pm = self._emoji_pixmap(q["emoji"])
                p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), pm, QRectF(pm.rect()))
            p.restore()
        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# Chat view
# ══════════════════════════════════════════════════════════════════════════════

class ChatView(QWidget):
    SIDE = 12          # left/right margin (room for the glow)
    ENTRY = 0.38       # seconds for the slide/fade-in
    FADE = 0.8         # seconds for the fade-out

    def __init__(self, images: ImageCache, style: ChatStyle, parent=None):
        super().__init__(parent)
        self.setObjectName("chatView")
        self.images = images
        self.style_ = style
        self._items: List[_Item] = []
        self._msgs: List[dict] = []
        self._stick = True                          # follow new messages

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none}")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background:transparent")   # only messages get a background
        self.canvas = _Canvas(self)
        self.canvas.setStyleSheet("background:transparent")
        self.scroll.setWidget(self.canvas)
        lay.addWidget(self.scroll)
        sb = self.scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll)
        sb.rangeChanged.connect(self._on_range)

        self.rain_layer = RainLayer(self, images)
        images.ready.connect(self._on_image_ready)

        self._anim = QTimer(self)                   # GIF frames + glow pulse + fade check
        self._anim.timeout.connect(self._tick)
        self._anim.start(50)
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.timeout.connect(self._relayout)
        self._frame = QTimer(self)                  # entry / slide / fade animation (~60 fps)
        self._frame.timeout.connect(self._frame_tick)
        self._last_frame = time.time()
        self._scroll_anim = QVariantAnimation(self)  # smooth follow when new messages arrive
        self._scroll_anim.setDuration(260)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.valueChanged.connect(lambda v: self.scroll.verticalScrollBar().setValue(int(v)))
        self.apply_style()

    # ── public API ────────────────────────────────────────────────────────────
    def apply_style(self):
        self.update()
        self.rerender()

    def visible(self, msg: dict) -> bool:
        st = self.style_
        if msg.get("history") and not st.show_history:
            return False
        if msg.get("bot") and not st.show_bots:
            return False
        return True

    def is_rtl(self, msg: dict) -> bool:
        return self._direction(msg.get("text", ""), msg.get("platform", ""))

    def set_messages(self, msgs: List[dict]):
        self._msgs = list(msgs)
        self.rerender()

    def add_message(self, msg: dict):
        if not msg.get("system") and not self.visible(msg):
            return
        self._msgs.append(msg)
        it = self._build(msg)
        self._items.append(it)
        over = len(self._items) - self.style_.max_messages
        if over > 0:
            del self._items[:over]
            del self._msgs[:max(0, len(self._msgs) - self.style_.max_messages)]
        self._layout_item(it, self._avail())
        self._positions()
        self._kick()

    def update_avatar(self, user_key: str, url: str, proxy: Optional[str] = None):
        """A profile picture arrived (Twitch/Kick are looked up after the message)."""
        hit = False
        for it in self._items:
            if it.msg.get("user_key") == user_key and not it.av:
                it.msg["avatar"] = url
                it.av = url
                hit = True
        for m in self._msgs:
            if m.get("user_key") == user_key and not m.get("avatar"):
                m["avatar"] = url
        if hit:
            self.images.get(url, proxy)
            self.canvas.update()

    def log(self, text: str, color: str = "#8b90a5"):
        self.add_message({"system": True, "text": text, "color": color, "id": str(time.time())})

    def clear_chat(self):
        self._msgs.clear()
        self.rerender()

    def rerender(self):
        msgs = [m for m in self._msgs if (m.get("system") or self.visible(m)) and not self._expired(m)]
        self._msgs = msgs[-self.style_.max_messages:]
        self._items = [self._build(m) for m in self._msgs]
        self._relayout()

    def scroll_to_bottom(self):
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def rain(self, sym: dict, proxy: Optional[str] = None):
        self.rain_layer.start(sym, self.style_.rain_amount, proxy)

    # ── geometry ──────────────────────────────────────────────────────────────
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.rain_layer.setGeometry(self.rect())
        self._relayout_soon()                       # keep messages anchored to the bottom

    def paintEvent(self, e):
        st = self.style_
        if st.bg_alpha <= 0:
            return
        c = QColor(st.bg)
        c.setAlphaF(max(0.0, min(1.0, st.bg_alpha)))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, c)
        p.end()

    def _avail(self) -> float:
        return float(max(120, self.scroll.viewport().width()))

    def _pads(self, it: _Item):
        if it.system:
            return 4.0, 2.0
        if self.style_.layout == "bubbles":
            return 12.0, 7.0
        return 6.0, 2.0

    @staticmethod
    def _tab_pad():
        return 10.0, 4.0

    def _av_size(self) -> int:
        st = self.style_
        if not st.show_avatars:
            return 0
        return int(st.font_size * (2.6 if st.layout == "bubbles" else 1.7))

    def _layout_item(self, it: _Item, avail: float):
        st = self.style_
        px, py = self._pads(it)
        av = 0 if it.system else self._av_size()
        avgap = 8 if av else 0
        inner = max(40.0, avail - 2 * self.SIDE - av - avgap - 2 * px)
        if not it.system:                          # shorten names that don't fit with …
            full = it.msg.get("username", "?")
            fm = QFontMetricsF(self._name_font())
            if st.layout == "bubbles":
                room = inner - (it.fhw - fm.horizontalAdvance(full)) - 4
            else:
                room = inner * 0.6
            self._apply_name(it, self._fit_name(full, room, fm))
        it.doc.setTextWidth(inner)
        if st.layout == "bubbles" and not it.system:
            hx, hy = self._tab_pad()
            it.head.setTextWidth(-1)
            hw = min(inner, math.ceil(it.head.idealWidth()) + 2)
            it.head.setTextWidth(hw)
            it.tw = hw + 2 * hx
            it.th = it.head.size().height() + 2 * hy
            bw = min(inner, math.ceil(it.doc.idealWidth()) + 2)
            box_w = min(inner + 2 * px, max(bw + 2 * px, it.tw + st.radius))
            it.doc.setTextWidth(box_w - 2 * px)    # full width so RTL text sits flush right
            it.w = box_w
            it.h = it.th - 1 + it.doc.size().height() + 2 * py
        else:
            it.w = inner + 2 * px
            it.h = max(it.doc.size().height() + 2 * py, av + 2 * py if av else 0)
        it.cache = None
        it.shp = None
        right = it.rtl and st.layout == "bubbles"
        if av:
            if right or (it.rtl and st.layout != "bubbles"):
                it.ax = avail - self.SIDE - av
                it.x = (it.ax - avgap - it.w) if right else self.SIDE
            else:
                it.ax = self.SIDE
                it.x = self.SIDE + av + avgap
        else:
            it.ax = None
            it.x = avail - self.SIDE - it.w if right else self.SIDE

    def _text_pixmap(self, it: _Item, ctx) -> QPixmap:
        """Message text (name tab + body) rendered once into an image."""
        if it.cache is not None:
            return it.cache
        dpr = self.devicePixelRatioF() or 1.0
        w, h = max(1, math.ceil(it.w)), max(1, math.ceil(it.h))
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        px, py = self._pads(it)
        if it.head is not None and self.style_.layout == "bubbles" and not it.system:
            hx, hy = self._tab_pad()
            p.save()
            p.translate((it.w - it.tw if it.rtl else 0) + hx, hy)
            it.head.documentLayout().draw(p, ctx)
            p.restore()
            p.translate(px, it.th - 1 + py)
        else:
            p.translate(px, py)
        it.doc.documentLayout().draw(p, ctx)
        p.end()
        it.cache = pm
        return pm

    def _name_font(self) -> QFont:
        st = self.style_
        f = QFont(st.font_family)
        f.setPointSizeF(max(6.0, round(st.font_size * st.name_scale, 1)))
        f.setBold(True)
        return f

    @staticmethod
    def _fit_name(full: str, room: float, fm: QFontMetricsF) -> Optional[str]:
        """None if the full name fits, otherwise the name cut with … to fit *room*."""
        if fm.horizontalAdvance(full) <= room:
            return None
        return fm.elidedText(full, Qt.TextElideMode.ElideRight, max(room, fm.horizontalAdvance("…") * 3))

    def _apply_name(self, it: _Item, name: Optional[str]):
        if name == it.nm:
            return
        fresh = self._build(it.msg, name=name)
        it.doc, it.head, it.urls, it.nm = fresh.doc, fresh.head, fresh.urls, name

    @staticmethod
    def _seed(it: _Item) -> float:
        return (it.born * 7.31) % 1.0

    def _fx_color(self, it: _Item, now: float) -> QColor:
        if it.fx == "rainbow":
            return QColor.fromHsvF((now * 0.12 + self._seed(it)) % 1.0, 0.75, 1.0)
        return QColor(it.fxc or "#a78bfa")

    def _fx_strength(self, it: _Item, now: float) -> float:
        if it.fx == "pulse":
            return 0.25 + 0.5 * (0.5 + 0.5 * math.sin(now * 3.2 + self._seed(it) * 6.28))
        return 0.6 if it.fx == "rainbow" else 0.5

    @staticmethod
    def _rainbow_border(p: QPainter, shape: QPainterPath, now: float):
        r = shape.boundingRect()
        g = QConicalGradient(r.center(), (now * 120) % 360)
        for i, h in enumerate((0.0, 0.16, 0.33, 0.5, 0.66, 0.83, 1.0)):
            g.setColorAt(i / 6, QColor.fromHsvF(h % 1.0, 0.85, 1.0))
        p.setPen(QPen(g, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)

    def _shine(self, p: QPainter, shape: QPainterPath, it: _Item, now: float):
        period = 3.2
        phase = ((now + self._seed(it) * period) % period) / 0.9   # sweep takes 0.9 s, then rests
        if phase >= 1:
            return
        r = shape.boundingRect()
        x = r.left() - r.width() * 0.4 + phase * r.width() * 1.8
        g = QLinearGradient(x, r.top(), x + r.width() * 0.35, r.bottom())
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 80))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.save()
        p.setClipPath(shape)
        p.fillRect(r, g)
        p.restore()

    def _shapes(self, it: _Item, x: float, y: float):
        """Name tab + message box as one outline (no seam where they meet)."""
        rad = float(self.style_.radius)
        body = QRectF(x, y + it.th - 1, it.w, it.h - it.th + 1)
        tx = x + it.w - it.tw if it.rtl else x
        tab = QRectF(tx, y, it.tw, it.th)
        trad = min(rad, it.th / 2)
        tab_path = QPainterPath()
        tab_path.addRoundedRect(tab, trad, trad)
        sq = QPainterPath()                          # square off the tab's bottom corners
        sq.addRect(QRectF(tab.x(), tab.y() + tab.height() / 2, tab.width(), tab.height() / 2 + 1))
        tab_path = tab_path.united(sq)
        body_path = QPainterPath()
        body_path.addRoundedRect(body, rad, rad)
        corner = QPainterPath()                      # square the box corner under the tab
        cw = min(rad + 1, it.tw)
        corner.addRect(QRectF(body.right() - cw if it.rtl else body.x(), body.y(), cw, min(rad + 1, body.height())))
        body_path = body_path.united(corner)
        return tab, body, tab_path.united(body_path), tab_path, body_path

    def _draw_avatar(self, p: QPainter, it: _Item, x: float, y: float):
        img = self.images._imgs.get(it.av) if it.av else None
        if isinstance(img, QMovie):                  # animated avatar: draw live
            self._paint_avatar(p, it, x, y)
            return
        state = (it.av if img is not None else None, self._av_size(), self.style_.border_color)
        if it.avpm is None or it.avpm[0] != state:
            size = self._av_size()
            dpr = self.devicePixelRatioF() or 1.0
            pm = QPixmap(int((size + 2) * dpr), int((size + 2) * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            self._paint_avatar(q, it, 1.0, 1.0)
            q.end()
            it.avpm = (state, pm)
        p.drawPixmap(QPointF(x - 1, y - 1), it.avpm[1])

    def _paint_avatar(self, p: QPainter, it: _Item, x: float, y: float):
        size = float(self._av_size())
        r = QRectF(x, y, size, size)
        circle = QPainterPath()
        circle.addEllipse(r)
        img = self.images._imgs.get(it.av) if it.av else None
        pm = img.currentPixmap() if isinstance(img, QMovie) else img
        if isinstance(pm, QPixmap) and not pm.isNull():
            p.save()
            p.setClipPath(circle)
            src = QRectF(pm.rect())
            side = min(src.width(), src.height())    # centre-crop to a square
            src = QRectF(src.x() + (src.width() - side) / 2, src.y() + (src.height() - side) / 2, side, side)
            p.drawPixmap(r, pm, src)
            p.restore()
        else:                                        # placeholder: coloured circle with initial
            st = self.style_
            col = QColor(_readable(it.msg.get("color"), st.color_user))
            col = col.darker(170)
            p.fillPath(circle, col)
            name = (it.msg.get("username") or "?").strip()
            ch = next((c for c in name if c.isalnum()), "?").upper()
            f = QFont(st.font_family)
            f.setBold(True)
            f.setPixelSize(int(size * 0.45))
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, ch)
        ring = QColor(self.style_.border_color)
        p.setPen(QPen(ring, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))

    def _positions(self):
        gap = self.style_.line_gap + (6 if self.style_.layout == "bubbles" else 0)
        total = 10.0 + sum(it.h + gap for it in self._items) + 8
        vh = float(self.scroll.viewport().height())
        y = 10.0 + max(0.0, vh - total)              # few messages → sit at the bottom
        for it in self._items:
            it.y = y
            if it.yd is None or self.style_.anim_in == "none":
                it.yd = y                            # new messages appear in place (slide in sideways)
            y += it.h + gap
        self.canvas.setFixedHeight(int(max(total, vh)))
        self.canvas.update()

    def _relayout_soon(self):
        self._relayout_timer.start(40)

    def _relayout(self):
        avail = self._avail()
        for it in self._items:
            self._layout_item(it, avail)
        self._positions()

    def _on_scroll(self, value: int):
        sb = self.scroll.verticalScrollBar()
        self._stick = value >= sb.maximum() - 40

    def _on_range(self, _lo: int, hi: int):
        if not self._stick:
            return
        sb = self.scroll.verticalScrollBar()
        if self.style_.anim_in == "none" or hi - sb.value() > 600:
            sb.setValue(hi)
        else:                                        # glide up instead of jumping
            self._scroll_anim.stop()
            self._scroll_anim.setStartValue(float(sb.value()))
            self._scroll_anim.setEndValue(float(hi))
            self._scroll_anim.start()

    # ── building one message ──────────────────────────────────────────────────
    def _direction(self, text: str, platform: str = "") -> bool:
        if self.style_.direction == "rtl":
            return True
        if self.style_.direction == "ltr":
            return False
        rtl, ltr = len(RTL_RE.findall(text)), len(LTR_RE.findall(text))
        if rtl == ltr:                       # emote-only / numbers: follow the platform
            return platform in ("aparat", "onefa")
        return rtl > ltr

    def _new_doc(self, rtl: bool, wrap: bool = True) -> QTextDocument:
        st = self.style_
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setUndoRedoEnabled(False)
        base = QFont(st.font_family)
        base.setPointSizeF(st.font_size)
        doc.setDefaultFont(base)
        opt = QTextOption()
        opt.setTextDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere if wrap
                        else QTextOption.WrapMode.NoWrap)
        doc.setDefaultTextOption(opt)
        return doc

    def _build(self, m: dict, name: Optional[str] = None) -> _Item:
        """*name* replaces the user name (used to shorten long names with …)."""
        st = self.style_
        it = _Item(m)
        it.nm = name
        it.rtl = False if it.system else self.is_rtl(m)
        it.glow = (m.get("_trigger_color") or "#7c5cff") if m.get("_trigger") else None
        if not it.system:
            it.fx, it.fxc = effect_for(m, st.effects)
        it.doc = self._new_doc(it.rtl)
        proxy = m.get("proxy") or None
        if it.av and st.show_avatars:
            self.images.get(it.av, proxy)

        def blk(top=0.0):
            b = QTextBlockFormat()
            b.setLayoutDirection(Qt.LayoutDirection.RightToLeft if it.rtl else Qt.LayoutDirection.LeftToRight)
            b.setAlignment((Qt.AlignmentFlag.AlignRight if it.rtl else Qt.AlignmentFlag.AlignLeft)
                           | Qt.AlignmentFlag.AlignAbsolute)
            b.setTopMargin(top)
            return b

        def fmt(color, size=st.font_size, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            font = QFont(st.font_family)
            font.setPointSizeF(size)
            font.setBold(bold)
            font.setItalic(italic)
            f.setFont(font)
            return f

        cur = QTextCursor(it.doc)
        cur.setBlockFormat(blk())
        if it.system:
            cur.insertText(m.get("text", ""), fmt(m.get("color") or st.color_reply,
                                                  max(8, st.font_size - 1), italic=True))
            return it

        fs = st.font_size
        name_fs = max(6.0, round(fs * st.name_scale, 1))
        bubbles = st.layout == "bubbles"
        ico = int((name_fs if bubbles else fs) * 1.45)
        emo = int(fs * 1.9)
        mark = "‏" if it.rtl else "‎"
        reply = m.get("reply")
        has_reply = bool(reply and (reply.get("user") or reply.get("text")))

        def reply_text() -> str:
            txt = (reply.get("text") or "").replace("\n", " ")
            txt = txt[:70] + ("…" if len(txt) > 70 else "")
            who = f"⁨@{reply['user']}⁩:{mark} " if reply.get("user") else ""
            return f"↪{mark} {who}⁨{txt}⁩"

        ucol = _readable(m.get("color"), st.color_user) if st.use_user_colors else st.color_user

        def header(c: QTextCursor, doc_for_images: QTextDocument):
            if st.show_platform and m.get("platform"):
                self._img(doc_for_images, c, f"plat:{m['platform']}", platform_icon(m["platform"], ico), ico)
                c.insertText(" ", fmt(st.color_text, name_fs))
            if st.show_badges:
                for b in m.get("badges") or []:
                    if self._badge(it, doc_for_images, c, b, ico, proxy):
                        c.insertText(" ", fmt(st.color_text, name_fs))
            shown = name if name is not None else m.get("username", "?")
            c.insertText(mark + "⁨" + shown + "⁩" + mark, fmt(ucol, name_fs, bold=True))

        if bubbles:
            # name tab: [platform] [badges] name [time]  – one line, never wraps
            it.head = self._new_doc(it.rtl, wrap=False)
            hc = QTextCursor(it.head)
            hc.setBlockFormat(blk())
            header(hc, it.head)
            if st.show_time:
                hc.insertText("  " + time.strftime("%H:%M", time.localtime(m.get("ts", time.time()))),
                              fmt(st.color_reply, max(7, name_fs - 2)))
            if name is None:
                it.fhw = it.head.idealWidth()          # width the tab needs with the full name
            # message box: [reply] text
            if has_reply:
                cur.insertText(reply_text(), fmt(st.color_reply, max(8, fs - 2), italic=True))
                cur.insertBlock(blk(2))
        else:
            if has_reply:
                cur.insertText(reply_text() + " ", fmt(st.color_reply, max(8, fs - 2), italic=True))
            if st.show_time:
                cur.insertText(time.strftime("%H:%M ", time.localtime(m.get("ts", time.time()))),
                               fmt(st.color_reply, max(8, fs - 2)))
            header(cur, it.doc)
            cur.insertText(":" + mark + " ", fmt(st.color_reply))

        tf = fmt(st.color_text)
        cur.insertText("⁨", tf)
        for part in m.get("parts") or [{"type": "text", "text": m.get("text", "")}]:
            if part["type"] == "text":
                cur.insertText(part["text"], tf)
            elif part["type"] == "emote":
                self._url_img(it, it.doc, cur, part["url"], emo, part.get("name", ""), proxy)
        cur.insertText("⁩", tf)
        return it

    def _badge(self, it, doc, cur, b: dict, size: int, proxy) -> bool:
        if b.get("url"):
            self._url_img(it, doc, cur, b["url"], size, b.get("title", ""), proxy, square=True,
                          fallback_icon=b.get("icon"))
            return True
        pm = badge_icon(b.get("icon") or "", size)
        if pm is not None:
            self._img(doc, cur, f"icon:{b['icon']}:{size}", pm, size, b.get("title", ""))
            return True
        return False

    @staticmethod
    def _img(doc, cur, name: str, pm: QPixmap, size: int, tooltip: str = ""):
        doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), pm)
        f = QTextImageFormat()
        f.setName(name)
        f.setWidth(size)
        f.setHeight(size)
        f.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        if tooltip:
            f.setToolTip(tooltip)
        cur.insertImage(f)

    def _url_img(self, it, doc, cur, url: str, height: int, tooltip: str = "", proxy=None,
                 square=False, fallback_icon: Optional[str] = None):
        img = self.images.get(url, proxy)
        name = "url:" + url
        width = height
        if img is not None:
            sz = self.images.size_of(url)
            if sz and sz[1] and not square:
                width = max(1, round(height * sz[0] / sz[1]))
            pm = img.currentPixmap() if isinstance(img, QMovie) else img
        else:
            pm = badge_icon(fallback_icon, height) if fallback_icon else None
            if pm is None:
                pm = QPixmap(height, height)
                pm.fill(Qt.GlobalColor.transparent)
        if pm is not None and not pm.isNull():
            doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), pm)
        it.urls[name] = url
        f = QTextImageFormat()
        f.setName(name)
        f.setWidth(width)
        f.setHeight(height)
        f.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignMiddle)
        if tooltip:
            f.setToolTip(tooltip)
        cur.insertImage(f)

    # ── async images, animation, glow ─────────────────────────────────────────
    @staticmethod
    def _docs(it: _Item):
        return [d for d in (it.doc, it.head) if d is not None]

    def _on_image_ready(self, url: str):
        name = "url:" + url
        img = self.images._imgs.get(url)
        if img is None:
            return
        pm = img.currentPixmap() if isinstance(img, QMovie) else img
        sz = self.images.size_of(url)
        wide = bool(sz and sz[1] and abs(sz[0] / sz[1] - 1.0) > 0.25)
        changed = False
        for i, it in enumerate(self._items):
            if it.av == url:
                changed = True
            if name not in it.urls:
                continue
            if wide:                                  # rebuild so the emote keeps its shape
                fresh = self._build(it.msg)
                fresh.yd = it.yd
                self._items[i] = fresh
                self._layout_item(fresh, self._avail())
            elif pm is not None and not pm.isNull():
                for d in self._docs(it):
                    d.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), pm)
                    d.markContentsDirty(0, d.characterCount())
                it.cache = None
            changed = True
        if changed:
            self._positions()

    def _expired(self, m: dict) -> bool:
        fa = self.style_.fade_after
        return fa > 0 and time.time() - m.get("_shown_at", time.time()) > fa + self.FADE

    def _anim_state(self, it: _Item, now: float):
        """(opacity, x-offset) for an item right now."""
        st = self.style_
        a, dx = 1.0, 0.0
        if it.anim and st.anim_in != "none":
            t = (now - it.born) / self.ENTRY
            if t < 1:
                e = 1 - (1 - max(0.0, t)) ** 3
                a = e
                if st.anim_in != "fade":
                    if st.anim_in == "side":
                        sign = 1 if (it.rtl and st.layout == "bubbles") else -1
                    else:
                        sign = 1 if st.anim_in == "right" else -1
                    dx = (1 - e) * 80 * sign
        if st.fade_after > 0:
            over = now - it.born - st.fade_after
            if over > 0:
                a *= max(0.0, 1 - over / self.FADE)
        return a, dx

    def _kick(self):
        if not self._frame.isActive():
            self._last_frame = time.time()
            self._frame.start(16)

    def _frame_tick(self):
        now = time.time()
        dt = min(0.1, now - self._last_frame)
        self._last_frame = now
        st = self.style_
        active = False
        for it in self._items:
            if it.yd is not None and abs(it.y - it.yd) > 0.5:
                it.yd += (it.y - it.yd) * min(1.0, dt * 14)
                active = True
            elif it.yd is not None:
                it.yd = it.y
            if it.anim and now - it.born < self.ENTRY:
                active = True
            if st.fade_after > 0 and now - it.born > st.fade_after:
                active = True
        if st.fade_after > 0:                        # drop messages that finished fading
            gone = [it for it in self._items if now - it.born > st.fade_after + self.FADE]
            if gone:
                ids = {id(it.msg) for it in gone}
                self._items = [it for it in self._items if id(it.msg) not in ids]
                self._msgs = [m for m in self._msgs if id(m) not in ids]
                self._positions()
        self.canvas.update()
        if not active:
            self._frame.stop()

    def _glow_strength(self, it: _Item, now: float) -> float:
        age = now - it.born
        if age < 2.4:
            return 0.62 + 0.38 * abs(math.sin(age * math.pi / 0.8))
        return 0.62

    def _tick(self):
        if not self.isVisible() or not self._items:
            return
        fa = self.style_.fade_after
        if fa > 0 and any(time.time() - it.born > fa for it in self._items):
            self._kick()
        vr = self.scroll.viewport().rect().translated(0, self.scroll.verticalScrollBar().value())
        now = time.time()
        for it in self._items:
            if it.y + it.h < vr.top() or it.y > vr.bottom():
                continue
            dirty = bool(it.glow and now - it.born < 2.5 and self.style_.highlight_triggers) or it.fx in FX_ANIMATED
            for name, url in it.urls.items():
                img = self.images._imgs.get(url)
                if isinstance(img, QMovie):
                    pm = img.currentPixmap()
                    if not pm.isNull():
                        for d in self._docs(it):
                            d.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), pm)
                        it.cache = None
                        dirty = True
            if it.av and isinstance(self.images._imgs.get(it.av), QMovie):
                dirty = True
            if dirty:
                self.canvas.update(int(it.x) - 60, int(it.y) - 12, int(it.w) + 120, int(it.h) + 24)
