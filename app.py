#!/usr/bin/env python3
"""RetChat 2 – multi-platform live-chat reader that turns chat words into key presses.

Supported:  Twitch · Kick · YouTube · Aparat · OneFa   (no browser needed)

    pip install -r requirements.txt
    python app.py
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
                             QFontComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                             QSizeGrip, QSlider, QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
                             QWidget)

import i18n
import input_sender as isend
import theme
from i18n import T, translate_tree
from binding_dialog import BindingDialog
from bindings import DEFAULT_BOTS, Binding, BindingManager, bot_names, is_bot
from chat_view import FX_ROLES, ChatStyle, ChatView, ScreenRain, _readable, effect_for, rain_symbol
from input_block import InputBlocker
from obs_server import ObsServer
from progress import GlowBar, ProgressStrip
from connectors import PLATFORM_NAMES, PLATFORMS, ChatHub, Target, parse_target, proxy_label, resolve_proxy
from images import BADGE_STYLE, ImageCache, _logo_path, all_badge_kinds, badge_icon, platform_icon

APP_NAME = "RetChat"
VERSION = "3.5"
SETTINGS = Path.home() / ".retchat2_settings.json"
# Theme presets (Appearance ▸ Theme): message text, name, message box, name tab, border, chat area
def _theme(text, user, bubble, name_bg, border, bg="#12131a", alpha=0.88):
    return {"color_text": text, "color_user": user, "bubble_bg": bubble, "name_bg": name_bg,
            "border_color": border, "bg": bg, "bubble_alpha": alpha}


FX_LABELS = (("none", "None"), ("glow", "Glow"), ("pulse", "Pulse"), ("rainbow", "Rainbow glow"),
             ("rborder", "Rainbow border"), ("shine", "Shine"))

THEMES = [
    ("Midnight", _theme("#e6e8ef", "#7cc4ff", "#1d2130", "#2a3046", "#3a4158")),
    ("Neon", _theme("#f5f3ff", "#c084fc", "#1e1033", "#3b1d6e", "#7c3aed", "#0d0618")),
    ("Ocean", _theme("#e0f2fe", "#38bdf8", "#0c2236", "#11405f", "#1e6a96", "#06121c")),
    ("Forest", _theme("#ecfdf5", "#4ade80", "#0f241a", "#1a3d2b", "#2f6b4a", "#07130d")),
    ("Sunset", _theme("#fff7ed", "#fb923c", "#2a160c", "#4a2412", "#c2410c", "#140a05")),
    ("Rose", _theme("#fff1f2", "#fb7185", "#2a1018", "#4c1d2b", "#be123c", "#14070b")),
    ("Gold", _theme("#fefce8", "#facc15", "#1f1a0a", "#3d3210", "#a16207", "#0f0c04")),
    ("Light", _theme("#1f2430", "#2563eb", "#f4f6fb", "#dfe6f5", "#c3cbe0", "#e9edf5", 0.95)),
    ("Glass", _theme("#ffffff", "#a5f3fc", "#000000", "#000000", "#8090a0", "#000000", 0.35)),
]

FA_EN_RESTART = {"fa": "برای تغییر زبان به فارسی، RetChat دوباره اجرا شود؟",
                 "en": "Restart RetChat to switch the language to English?"}
OLD_SETTINGS = Path.home() / ".ret_chat_settings.json"


def resource(rel: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def lan_ips() -> List[str]:
    """This PC's IPv4 addresses on local networks, best guess first.

    The UDP "connect" sends no packet; it only asks Windows which adapter it
    would use for the internet, which is normally the one the OBS PC shares.
    """
    import ipaddress
    import socket
    found: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out: List[str] = []
    for ip in found:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.is_loopback or a.is_link_local or ip in out:
            continue
        out.append(ip)
    # Home/office routers almost always use 192.168.x.x; VPN, Docker and WSL adapters
    # usually take 172.16-31.x or 10.x and may even carry the internet route – so rank by
    # range first, and use "carries the internet route" only as a tie-breaker.
    default = found[0] if found else ""

    def rank(ip: str):
        cls = 0 if ip.startswith("192.168.") else 1 if ip.startswith("10.") else 2
        return (cls, 0 if ip == default else 1)
    out.sort(key=rank)
    return out or ["127.0.0.1"]


class Bridge(QObject):
    """Moves callbacks from background threads onto the GUI thread."""
    message = pyqtSignal(dict)
    status = pyqtSignal(str, str, str)
    key_result = pyqtSignal(str, bool, str)
    proxy_result = pyqtSignal(bool, str)
    obs_result = pyqtSignal(bool, str)
    block_state = pyqtSignal(str)


# ══════════════════════════════════════════════════════════════════════════════
# Small widgets
# ══════════════════════════════════════════════════════════════════════════════

def label(text="", obj=None, muted=False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    if muted:
        l.setProperty("muted", True)
    return l


def button(text, cb=None, obj=None, tip=None) -> QPushButton:
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if tip:
        b.setToolTip(tip)
    if cb:
        b.clicked.connect(cb)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


ROUTES = (("direct", "Direct"), ("custom", "Proxy"), ("system", "System proxy"))


def route_combo(tip: str = "") -> QComboBox:
    cb = QComboBox()
    cb.setObjectName("small")
    for key, text in ROUTES:
        cb.addItem(text, key)
    if tip:
        cb.setToolTip(tip)
    return cb


class ChannelRow(QFrame):
    def __init__(self, target: Target, on_toggle, on_remove, on_route=None, route: str = "direct"):
        super().__init__()
        self.setObjectName("row")
        self.target = target
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 8, 8)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(platform_icon(target.platform, 26))
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = label(target.channel, "h2")
        name.setProperty("noTranslate", True)
        col.addWidget(name)
        self.status = label(f"{PLATFORM_NAMES[target.platform]} · not connected", muted=True)
        from PyQt6.QtWidgets import QSizePolicy
        for w in (name, self.status):
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            w.setMinimumWidth(40)
        col.addWidget(self.status)
        rr = QHBoxLayout()
        rr.setContentsMargins(0, 3, 0, 0)
        rr.setSpacing(6)
        rr.addWidget(label("Route", muted=True))
        self.route = route_combo("How this channel connects:\n"
                                 "Direct – no proxy\n"
                                 "Proxy – the proxy server set above (e.g. v2ray 127.0.0.1:10808)\n"
                                 "System proxy – Windows proxy settings")
        self.route.setCurrentIndex(max(0, self.route.findData(route)))
        if on_route:
            self.route.currentIndexChanged.connect(lambda _: on_route(self))
        rr.addWidget(self.route)
        rr.addStretch()
        col.addLayout(rr)
        lay.addLayout(col, 1)
        self.toggle = button("Connect", lambda: on_toggle(self), tip="Connect / disconnect")
        self.toggle.setFixedWidth(96)
        lay.addWidget(self.toggle)
        rm = button("✕", lambda: on_remove(self), "ghost", "Remove channel")
        lay.addWidget(rm)
        self.count = 0
        self.state = "stopped"
        self.text = ""
        translate_tree(self)

    @property
    def route_mode(self) -> str:
        return self.route.currentData() or "direct"

    def set_state(self, state: str, text: str = ""):
        self.state, self.text = state, text or self.text
        self.refresh()

    def refresh(self):
        col = theme.STATUS_COLORS.get(self.state, theme.MUTED)
        plat = PLATFORM_NAMES[self.target.platform]
        if i18n.LANG == "fa":
            txt = T("not connected") if self.state == "stopped" else T(self.text or "Connected")
        else:
            txt = {"live": (self.text or "connected").replace("Connected", "connected"),
                   "stopped": "not connected"}.get(self.state, self.text)
            if self.state == "error":
                txt = self.text
        cnt = (" · " + T("{n} msgs").format(n=self.count)) if self.count else ""
        self.status.setText(f"<span style='color:{col}'>●</span> {plat} · {txt}{cnt}")
        self.status.setToolTip(self.text)
        on = self.state in ("live", "connecting", "error")
        self.toggle.setText(T("Disconnect") if on else T("Connect"))
        self.toggle.setObjectName("" if on else "primary")
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)


class GroupHeader(QFrame):
    """Group title row: collapse arrow, Active checkbox, counts, add / rename / delete."""

    def __init__(self, name: str, info: dict, count: int, on_active, on_collapse, on_add,
                 on_rename, on_delete):
        super().__init__()
        self.setObjectName("groupHead")
        self.setProperty("active", bool(info.get("active", True)))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(6)
        lay.addWidget(button("▸" if info.get("collapsed") else "▾", lambda: on_collapse(name), "ghost",
                             "Show / hide this group's triggers"))
        self.active = QCheckBox(name)
        self.active.setObjectName("groupCheck")
        self.active.setChecked(bool(info.get("active", True)))
        self.active.setToolTip("Active: this group's triggers count points, press keys and show bars.\n"
                               "Inactive: they are ignored and their bars are hidden.")
        self.active.toggled.connect(lambda on: on_active(name, on))
        lay.addWidget(self.active)
        lay.addWidget(label(T("{n} trigger" if count == 1 else "{n} triggers").format(n=count), muted=True))
        lay.addStretch()
        lay.addWidget(button("+", lambda: on_add(name), "ghost", "Add a trigger to this group"))
        lay.addWidget(button("✎", lambda: on_rename(name), "ghost", "Rename group"))
        lay.addWidget(button("✕", lambda: on_delete(name), "ghost", "Delete group"))
        if name != "General":
            self.active.setProperty("noTranslate", True)    # user-made group names stay as typed
        translate_tree(self)


class BindingRow(QFrame):
    def __init__(self, b: Binding, on_edit, on_test, on_delete, on_toggle):
        super().__init__()
        self.setObjectName("row")
        self.b = b
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 6, 8)
        v.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.en = QCheckBox()
        self.en.setChecked(b.enabled)
        self.en.setToolTip("Enable / disable this trigger")
        self.en.toggled.connect(lambda on: on_toggle(self, on))
        top.addWidget(self.en)
        self.word = label(b.word, "wordChip")
        top.addWidget(self.word)
        top.addWidget(label("→", muted=True))
        self.key = label(b.action_text(), "keyChip")
        top.addWidget(self.key)
        top.addStretch()
        top.addWidget(button("▶", lambda: on_test(self), "ghost", "Test: run this trigger in 3 s"))
        top.addWidget(button("✎", lambda: on_edit(self), "ghost", "Edit"))
        top.addWidget(button("✕", lambda: on_delete(self), "ghost", "Delete"))
        v.addLayout(top)
        bot = QHBoxLayout()
        self.bar = GlowBar(b.color, height=8, show_text=False)
        bot.addWidget(self.bar, 1)
        self.info = label("", muted=True)
        self.info.setMinimumWidth(110)
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bot.addWidget(self.info)
        v.addLayout(bot)
        self.word.setProperty("noTranslate", True)
        self.key.setProperty("noTranslate", True)
        translate_tree(self)
        self.refresh()

    def refresh(self):
        b = self.b
        self.word.setText(b.word)
        self.key.setText(b.action_text())
        self.bar.set_color(b.color)
        self.bar.set_progress(b.acc, b.threshold)
        cd = b.cooling()
        extra = (" · " + T("cooldown {s}s").format(s=f"{cd:.0f}")) if cd else \
                (" · " + T("fired {n}×").format(n=b.fired_count) if b.fired_count else "")
        self.info.setText(f"{b.acc}/{b.threshold}{extra}")
        on = b.enabled and getattr(self, "group_active", True)
        self.word.setEnabled(on)
        self.key.setEnabled(on)
        self.bar.setEnabled(on)
        self.setToolTip("" if on else T("Group is inactive" if b.enabled else "Trigger is disabled"))


# ══════════════════════════════════════════════════════════════════════════════
# Overlay window
# ══════════════════════════════════════════════════════════════════════════════

class OverlayWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, images: ImageCache, style: ChatStyle):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("RetChat overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(420, 600)
        self._drag: Optional[QPoint] = None
        self.locked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.bar = QWidget()
        bl = QHBoxLayout(self.bar)
        bl.setContentsMargins(4, 0, 4, 0)
        t = label("RetChat overlay – drag to move", muted=True)
        bl.addWidget(t, 1)
        bl.addWidget(button("✕", self.close, "ghost", "Close overlay"))
        self.bar.setStyleSheet("background: rgba(20,22,32,0.85); border-radius: 8px;")
        lay.addWidget(self.bar)
        self.progress = ProgressStrip(style.bar_height, style.bar_font)
        lay.addWidget(self.progress)
        self.view = ChatView(images, style)
        lay.addWidget(self.view, 1)
        grip = QHBoxLayout()
        grip.addStretch()
        self.grip = QSizeGrip(self)
        grip.addWidget(self.grip)
        lay.addLayout(grip)
        translate_tree(self)

    def set_locked(self, locked: bool):
        """Locked = click-through (mouse goes to the game underneath)."""
        self.locked = locked
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, locked)
        self.bar.setVisible(not locked)
        self.grip.setVisible(not locked)
        self.setGeometry(geo)
        self.show()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


# ══════════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1240, 780)
        self.setMinimumSize(900, 560)

        self.bridge = Bridge()
        self.bridge.message.connect(self.on_message)
        self.bridge.status.connect(self.on_status)
        self.bridge.key_result.connect(self.on_key_result)
        self.bridge.proxy_result.connect(self.on_proxy_result)
        self.bridge.obs_result.connect(self.on_obs_result)
        self.hub = ChatHub(self.bridge.message.emit, self.bridge.status.emit)
        self.sender = isend.InputSender(self.bridge.key_result.emit)
        self.blocker = InputBlocker(self.bridge.block_state.emit)
        self.bridge.block_state.connect(self._on_block_state)
        self._shutdown_box = None
        self.images = ImageCache(self)
        self.style_ = ChatStyle()
        self.bm = BindingManager()
        self._bots = bot_names(DEFAULT_BOTS)
        self.obs = ObsServer(self.hub.loop, _logo_path("x").parent, self._render_icons())
        self.triggers_on = True
        self.messages: deque = deque(maxlen=1000)
        self.rows: Dict[str, ChannelRow] = {}
        self.brows: List[BindingRow] = []
        self._bind_widgets: List[QWidget] = []
        self.exclusive_groups = False
        self.overlay: Optional[OverlayWindow] = None
        self.screen_rain: Optional[ScreenRain] = None    # full-screen emoji rain window
        self._rate: deque = deque(maxlen=600)

        self._build()
        self.load_settings()

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._periodic)
        self._tick.start(500)
        self._elev_tick = QTimer(self)
        self._elev_tick.timeout.connect(self._check_elevation)
        self._elev_tick.start(2000)
        translate_tree(self)

    # ── layout ────────────────────────────────────────────────────────────────
    def _build(self):
        split = QSplitter()
        split.setHandleWidth(1)
        self.setCentralWidget(split)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(360)
        side.setMaximumWidth(520)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(16, 14, 16, 12)
        sv.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        if os.path.exists(resource("logo/app.jpg")):
            logo.setPixmap(QPixmap(resource("logo/app.jpg")).scaled(
                36, 36, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            head.addWidget(logo)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        tcol.addWidget(label(APP_NAME, "brand"))
        tcol.addWidget(label(T("v{v} · by DrPlague & R3sTivE").format(v=VERSION), "brandSub"))
        head.addLayout(tcol, 1)
        sv.addLayout(head)

        # second row: language + admin status (own row so nothing gets cut off)
        head2 = QHBoxLayout()
        head2.addWidget(label("🌐", muted=True))
        self.lang_box = QComboBox()
        self.lang_box.setObjectName("small")
        for code, name_ in i18n.LANGUAGES:
            self.lang_box.addItem(name_, code)
        self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(i18n.LANG)))
        self.lang_box.setToolTip("Language")
        self.lang_box.setProperty("noTranslate", True)
        self.lang_box.currentIndexChanged.connect(self._change_language)
        head2.addWidget(self.lang_box)
        head2.addStretch()
        self.admin_pill = QLabel()
        head2.addWidget(self.admin_pill)
        self.admin_btn = button("🛡  Run as admin", self.restart_admin, "adminBtn",
                                "Games that run as administrator ignore key presses from normal apps. "
                                "Restart RetChat with admin rights so keys reach them.")
        head2.addWidget(self.admin_btn)
        sv.addLayout(head2)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_channels(), "Channels")
        self.tabs.addTab(self._tab_triggers(), "Triggers")
        self.tabs.addTab(self._tab_look(), "Appearance")
        sv.addWidget(self.tabs, 1)
        split.addWidget(side)

        # chat pane
        pane = QWidget()
        pane.setObjectName("chatPane")
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(16, 14, 16, 12)
        pv.setSpacing(8)
        bar = QHBoxLayout()
        bar.addWidget(label("Live chat", "brand"))
        self.rate_lbl = label("", "pill")
        bar.addWidget(self.rate_lbl)
        bar.addStretch()
        self.overlay_btn = button("⧉  Overlay", self.toggle_overlay, tip="Open a transparent always-on-top chat overlay")
        bar.addWidget(self.overlay_btn)
        self.lock_btn = button("🔓", self.toggle_lock, "iconBtn", "Lock overlay (click-through)")
        self.lock_btn.setEnabled(False)
        bar.addWidget(self.lock_btn)
        bar.addWidget(button("💾", self.save_json, "iconBtn", "Save chat as JSON"))
        bar.addWidget(button("🧹", self.clear_chat, "iconBtn", "Clear chat"))
        pv.addLayout(bar)
        self.progress = ProgressStrip(self.style_.bar_height, self.style_.bar_font)
        pv.addWidget(self.progress)
        self.view = ChatView(self.images, self.style_, main=True)
        pv.addWidget(self.view, 1)
        self.last_lbl = label("", muted=True)
        pv.addWidget(self.last_lbl)
        split.addWidget(pane)
        split.setStretchFactor(1, 1)
        split.setSizes([400, 840])

    def _scroll(self, inner: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner.setObjectName("scrollInner")
        sa.setWidget(inner)
        sa.viewport().setAutoFillBackground(False)
        return sa

    def _tab_channels(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(8)
        r = QHBoxLayout()
        self.target_in = QLineEdit()
        self.target_in.setPlaceholderText("Paste a channel link…")
        self.target_in.returnPressed.connect(self.add_target)
        r.addWidget(self.target_in, 1)
        self.add_route = route_combo("Route for the channel you add (can be changed per channel later)")
        r.addWidget(self.add_route)
        r.addWidget(button("Add", self.add_target, "primary"))
        v.addLayout(r)
        hint = label("twitch.tv/name · kick.com/name · youtube.com/@name or watch link · "
                     "aparat.com/name · onefa.ir/name", muted=True)
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.add_err = label("")
        self.add_err.setStyleSheet("color:#ff8a8a; font-size:12px;")
        self.add_err.hide()
        v.addWidget(self.add_err)

        # proxy server card
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(12, 10, 12, 10)
        cv.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label("Proxy server", "h2"))
        top.addStretch()
        self.sys_proxy_lbl = label("", muted=True)
        top.addWidget(self.sys_proxy_lbl)
        cv.addLayout(top)
        pr = QHBoxLayout()
        pr.setSpacing(6)
        self.proxy_type = QComboBox()
        self.proxy_type.addItem("SOCKS5", "socks5")
        self.proxy_type.addItem("HTTP", "http")
        pr.addWidget(self.proxy_type)
        self.proxy_host = QLineEdit("127.0.0.1")
        self.proxy_host.setPlaceholderText("host")
        pr.addWidget(self.proxy_host, 1)
        pr.addWidget(label(":", muted=True))
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(10808)
        self.proxy_port.setFixedWidth(74)
        pr.addWidget(self.proxy_port)
        self.proxy_test_btn = button("Test", self.test_proxy, tip="Check the proxy can reach the internet")
        pr.addWidget(self.proxy_test_btn)
        cv.addLayout(pr)
        self.proxy_result = label("v2ray / xray default: SOCKS5 127.0.0.1:10808 (HTTP 10809). "
                                  "Channels set to Route ▸ Proxy use this.", muted=True)
        self.proxy_result.setWordWrap(True)
        cv.addWidget(self.proxy_result)
        v.addWidget(card)
        self._proxy_timer = QTimer(self)
        self._proxy_timer.setSingleShot(True)
        self._proxy_timer.timeout.connect(self._proxy_changed)
        self.proxy_type.currentIndexChanged.connect(self._on_proxy_type)
        self.proxy_host.textChanged.connect(lambda _: self._proxy_timer.start(900))
        self.proxy_port.valueChanged.connect(lambda _: self._proxy_timer.start(900))

        inner = QWidget()
        self.chan_lay = QVBoxLayout(inner)
        self.chan_lay.setContentsMargins(0, 0, 4, 0)
        self.chan_lay.setSpacing(6)
        self.chan_lay.addStretch()
        v.addWidget(self._scroll(inner), 1)
        self.empty_chan = label("No channels yet. Add one above, then press Connect.", muted=True)
        self.empty_chan.setWordWrap(True)
        self.chan_lay.insertWidget(0, self.empty_chan)

        r = QHBoxLayout()
        r.addWidget(button("Connect all", self.connect_all, "primary"))
        r.addWidget(button("Disconnect all", self.disconnect_all))
        v.addLayout(r)
        return w

    def _tab_triggers(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(8)

        r = QHBoxLayout()
        self.master = button("", self.toggle_triggers)
        self.master.setMinimumHeight(36)
        r.addWidget(self.master, 1)
        v.addLayout(r)

        r = QHBoxLayout()
        r.addWidget(label("Send keys as", muted=True))
        self.key_mode = QComboBox()
        self.key_mode.addItem("Scan codes (games – recommended)", True)
        self.key_mode.addItem("Virtual keys (desktop apps)", False)
        self.key_mode.currentIndexChanged.connect(
            lambda: setattr(self.sender, "use_scancode", self.key_mode.currentData()))
        r.addWidget(self.key_mode, 1)
        v.addLayout(r)

        self.count_bots_cb = QCheckBox("Bot messages count toward triggers")
        self.count_bots_cb.setToolTip("Off: messages from bots (e.g. RestreamBot relaying another chat) "
                                      "never add points, so relayed words aren't counted twice.")
        self.count_bots_cb.toggled.connect(lambda on: setattr(self.bm, "count_bots", on))
        v.addWidget(self.count_bots_cb)

        self.elev_warn = QLabel()
        self.elev_warn.setWordWrap(True)
        self.elev_warn.setObjectName("pillWarn")
        self.elev_warn.hide()
        v.addWidget(self.elev_warn)

        self.exclusive_cb = QCheckBox("Only one group active at a time (e.g. switch game)")
        self.exclusive_cb.setToolTip("Ticking a group's Active box un-ticks all other groups")
        self.exclusive_cb.toggled.connect(lambda on: setattr(self, "exclusive_groups", on))
        v.addWidget(self.exclusive_cb)

        inner = QWidget()
        self.bind_lay = QVBoxLayout(inner)
        self.bind_lay.setContentsMargins(0, 0, 4, 0)
        self.bind_lay.setSpacing(6)
        self.bind_lay.addStretch()
        self.empty_bind = label("No triggers yet. A trigger presses a key when chat types a word "
                                "enough times.", muted=True)
        self.empty_bind.setWordWrap(True)
        self.bind_lay.insertWidget(0, self.empty_bind)
        v.addWidget(self._scroll(inner), 3)

        r = QHBoxLayout()
        r.addWidget(button("+  Add trigger", lambda: self.add_binding(), "primary"))
        r.addWidget(button("+  New group", self.add_group))
        r.addWidget(button("Reset points", self.reset_points))
        v.addLayout(r)

        v.addWidget(label("Activity", "h2"))
        self.activity = QListWidget()
        self.activity.setStyleSheet("QListWidget{background:#151821;border:1px solid #2a3042;"
                                    "border-radius:8px;padding:4px;} QListWidget::item{padding:3px;}")
        v.addWidget(self.activity, 1)
        self._refresh_master()
        return w

    def _tab_look(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 4, 0)
        v.setSpacing(10)
        st = self.style_

        def row(text, widget, stretch=True):
            r = QHBoxLayout()
            l = label(text)
            l.setFixedWidth(130)
            r.addWidget(l)
            r.addWidget(widget, 1 if stretch else 0)
            if not stretch:
                r.addStretch()
            v.addLayout(r)

        self.font_box = QFontComboBox()
        self.font_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_box.setMinimumContentsLength(8)
        self.font_box.currentFontChanged.connect(lambda f: self._set("font_family", f.family()))
        row("Font", self.font_box)

        self.size_sl = QSlider(Qt.Orientation.Horizontal)
        self.size_sl.setRange(8, 40)
        self.size_lbl = label("", muted=True)
        self.size_lbl.setFixedWidth(46)
        self.size_sl.valueChanged.connect(lambda x: (self.size_lbl.setText(f"{x}px"), self._set("font_size", x)))
        r = QHBoxLayout()
        l = label("Size")
        l.setMinimumWidth(120)
        r.addWidget(l)
        r.addWidget(self.size_sl, 1)
        r.addWidget(self.size_lbl)
        v.addLayout(r)

        self.layout_box = QComboBox()
        self.layout_box.addItem("Bubbles – name on top, rounded", "bubbles")
        self.layout_box.addItem("Compact – one line per message", "compact")
        self.layout_box.currentIndexChanged.connect(lambda: self._set("layout", self.layout_box.currentData()))
        row("Layout", self.layout_box)

        # theme presets: one click sets all chat colours
        r = QHBoxLayout()
        l = label("Theme")
        l.setFixedWidth(130)
        r.addWidget(l, 0, Qt.AlignmentFlag.AlignTop)
        from PyQt6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(6)
        for n_, (name_, th) in enumerate(THEMES):
            b = QPushButton()
            b.setFixedSize(28, 28)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(name_)
            b.setStyleSheet(
                "QPushButton{border:2px solid %s;border-radius:14px;background:qlineargradient("
                "x1:0,y1:0,x2:1,y2:1,stop:0 %s,stop:0.5 %s,stop:0.51 %s,stop:1 %s);}"
                "QPushButton:hover{border-color:white;}"
                % (th["border_color"], th["bubble_bg"], th["bubble_bg"], th["color_user"], th["color_user"]))
            b.clicked.connect(lambda _, t=th: self.apply_theme(t))
            grid.addWidget(b, n_ // 5, n_ % 5)           # 5 per row so all fit in the sidebar
        r.addLayout(grid)
        r.addStretch()
        v.addLayout(r)

        self.color_btns = {}
        for key, text in (("color_text", "Message colour"), ("color_user", "Name colour"),
                          ("bubble_bg", "Message background"), ("name_bg", "Name background"),
                          ("border_color", "Message border"),
                          ("bg", "Chat area background")):
            b = QPushButton()
            b.setFixedSize(46, 26)
            b.clicked.connect(lambda _, k=key: self._pick_color(k))
            self.color_btns[key] = b
            row(text, b, stretch=False)

        def pct_slider(text, key, lo=0, hi=100, scale=100.0, unit="%"):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            val = label("", muted=True)
            val.setFixedWidth(46)
            sl.valueChanged.connect(lambda x: (val.setText(f"{x}{unit}"), self._set(key, x / scale if scale != 1 else x)))
            r = QHBoxLayout()
            l = label(text)
            l.setFixedWidth(130)
            r.addWidget(l)
            r.addWidget(sl, 1)
            r.addWidget(val)
            v.addLayout(r)
            return sl, val
        self.bub_sl, self.bub_lbl = pct_slider("Message opacity", "bubble_alpha")
        self.alpha_sl, self.alpha_lbl = pct_slider("Chat area opacity", "bg_alpha")
        self.ns_sl, self.ns_lbl = pct_slider("Name size", "name_scale", 50, 130)
        self.ns_sl.setToolTip("Size of the user name compared with the message text")
        self.rad_sl, self.rad_lbl = pct_slider("Corner roundness", "radius", 0, 30, 1, "px")
        self.bw_sl, self.bw_lbl = pct_slider("Border thickness", "border_width", 0, 6, 1, "px")

        self.anim_box = QComboBox()
        for k, t in (("side", "Slide in from its side"), ("right", "Slide in from the right"),
                     ("left", "Slide in from the left"), ("fade", "Fade in"), ("none", "No animation")):
            self.anim_box.addItem(t, k)
        self.anim_box.setToolTip("How new messages appear. Older messages glide up to make room.")
        self.anim_box.currentIndexChanged.connect(lambda: self._set("anim_in", self.anim_box.currentData()))
        row("New message", self.anim_box)

        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(0, 3600)
        self.fade_spin.setSuffix(" s")
        self.fade_spin.setSpecialValueText("never")
        self.fade_spin.setToolTip("Each message fades out this many seconds after it appears (0 = never)")
        self.fade_spin.valueChanged.connect(lambda x: self._set("fade_after", float(x)))
        row("Fade out after", self.fade_spin, stretch=False)
        self.fade_only_cb = QCheckBox("Only fade in the overlay and OBS (keep all messages in the app)")
        self.fade_only_cb.toggled.connect(lambda on: self._set("fade_overlay_only", on))
        v.addWidget(self.fade_only_cb)

        self.dir_box = QComboBox()
        self.dir_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for k, t in (("auto", "Automatic per message"), ("rtl", "Right-to-left (Persian)"),
                     ("ltr", "Left-to-right")):
            self.dir_box.addItem(t, k)
        self.dir_box.currentIndexChanged.connect(lambda: self._set("direction", self.dir_box.currentData()))
        row("Text direction", self.dir_box)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 1000)
        self.max_spin.setToolTip("Only the newest this-many messages are shown, e.g. 5")
        self.max_spin.valueChanged.connect(lambda x: self._set("max_messages", x))
        row("Messages shown", self.max_spin, stretch=False)

        self.checks = {}
        for key, text in (("use_user_colors", "Use each viewer's name colour"),
                          ("show_platform", "Show platform icon"),
                          ("show_badges", "Show badges"),
                          ("show_time", "Show time"),
                          ("show_history", "Show messages sent before connecting"),
                          ("show_bots", "Show bot messages"),
                          ("show_avatars", "Show profile pictures"),
                          ("highlight_triggers", "Glow on messages that count toward a trigger")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda on, k=key: self._set(k, on))
            self.checks[key] = cb
            v.addWidget(cb)
        self.anim_cb = QCheckBox("Animate GIF emotes")
        self.anim_cb.toggled.connect(lambda on: setattr(self.images, "animate", on))
        v.addWidget(self.anim_cb)

        v.addSpacing(8)
        v.addWidget(label("Emoji rain", "h2"))
        self.rain_cb = QCheckBox("Rain the emoji / GIF emote of a message over the chat")
        self.rain_cb.toggled.connect(lambda on: self._set("rain_enabled", on))
        v.addWidget(self.rain_cb)
        self.rain_trig_cb = QCheckBox("Only for messages that count toward a trigger")
        self.rain_trig_cb.toggled.connect(lambda on: self._set("rain_triggers_only", on))
        v.addWidget(self.rain_trig_cb)
        self.rain_amt_sl, self.rain_amt_lbl = pct_slider("Amount", "rain_amount", 5, 120, 1, "")
        self.rain_cd_sl, self.rain_cd_lbl = pct_slider("Wait between rains", "rain_cooldown", 0, 60, 1, "s")
        rs = QHBoxLayout()
        self.rain_screen_cb = QCheckBox("Also rain over the whole screen")
        self.rain_screen_cb.setToolTip("Drops fall over your whole monitor, on top of every window (click-through).\n"
                                       "Works over games in borderless / windowed mode, not exclusive full screen.")
        self.rain_screen_cb.toggled.connect(lambda on: (self._set("rain_screen", on),
                                                        self.rain_mon_box.setEnabled(on)))
        rs.addWidget(self.rain_screen_cb)
        self.rain_mon_box = QComboBox()
        self.rain_mon_box.setProperty("noTranslate", True)
        for i_, scr in enumerate(QApplication.screens()):
            g_ = scr.geometry()
            self.rain_mon_box.addItem(f"{i_ + 1}: {g_.width()}×{g_.height()}", i_)
        self.rain_mon_box.currentIndexChanged.connect(
            lambda i: self._set("rain_screen_monitor", int(self.rain_mon_box.itemData(i) or 0)))
        rs.addWidget(self.rain_mon_box)
        rs.addWidget(button("Test", self._test_rain, tip="Drop a test rain now"))
        rs.addStretch()
        v.addLayout(rs)
        self.rain_obs_cb = QCheckBox("Rain on the OBS chat page too (the OBS \"Rain only\" page always rains)")
        self.rain_obs_cb.toggled.connect(lambda on: (self._set("rain_obs_chat", on), self._obs_config()))
        v.addWidget(self.rain_obs_cb)
        v.addSpacing(8)

        v.addWidget(label("Special effects", "h2"))
        fx_hint = label("Subscribers, VIPs and OG users can get an effect on their messages. Pick one per site.",
                        muted=True)
        fx_hint.setWordWrap(True)
        v.addWidget(fx_hint)
        from PyQt6.QtWidgets import QGridLayout
        fxg = QGridLayout()
        fxg.setHorizontalSpacing(6)
        fxg.setVerticalSpacing(4)
        for col, title in enumerate(("Sub", "VIP", "OG"), start=1):
            fxg.addWidget(label(title, muted=True), 0, col, Qt.AlignmentFlag.AlignCenter)
        self.fx_boxes = {}
        for r_, plat in enumerate(PLATFORMS, start=1):
            ic = QLabel()
            ic.setPixmap(platform_icon(plat, 20))
            ic.setToolTip(PLATFORM_NAMES[plat])
            fxg.addWidget(ic, r_, 0)
            for col, role in enumerate(FX_ROLES, start=1):
                if role == "og" and plat not in ("kick", "onefa"):
                    fxg.addWidget(label("–", muted=True), r_, col, Qt.AlignmentFlag.AlignCenter)
                    continue
                cb = QComboBox()
                cb.setObjectName("small")
                for code, text in FX_LABELS:
                    cb.addItem(text, code)
                cb.currentIndexChanged.connect(lambda _, p_=plat, ro=role, c_=cb: self._set_fx(p_, ro, c_.currentData()))
                fxg.addWidget(cb, r_, col)
                self.fx_boxes[(plat, role)] = cb
        v.addLayout(fxg)
        v.addSpacing(8)

        self.bot_edit = QLineEdit(DEFAULT_BOTS)
        self.bot_edit.setToolTip("Names treated as bots (comma separated). Names of 7+ letters ending "
                                 "in 'bot' and platform-marked bots are detected automatically.")
        self.bot_edit.textChanged.connect(lambda t: setattr(self, "_bots", bot_names(t)))
        row("Bot names", self.bot_edit)

        v.addSpacing(8)
        v.addWidget(label("Progress bars", "h2"))
        v.addWidget(label("Each trigger's bar colour is set in the trigger editor (✎).", muted=True))

        def slider_row(text, lo, hi, key):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            val = label("", muted=True)
            val.setFixedWidth(46)
            sl.valueChanged.connect(lambda x: (val.setText(f"{x}px"), self._set(key, x)))
            r = QHBoxLayout()
            l = label(text)
            l.setFixedWidth(130)
            r.addWidget(l)
            r.addWidget(sl, 1)
            r.addWidget(val)
            v.addLayout(r)
            return sl, val
        self.barh_sl, self.barh_lbl = slider_row("Bar height", 6, 60, "bar_height")
        self.barf_sl, self.barf_lbl = slider_row("Bar text size", 8, 32, "bar_font")

        v.addSpacing(8)
        v.addWidget(label("OBS browser source", "h2"))
        r = QHBoxLayout()
        self.obs_cb = QCheckBox("Serve chat as a web page, port")
        self.obs_cb.toggled.connect(self.toggle_obs)
        r.addWidget(self.obs_cb)
        self.obs_port = QSpinBox()
        self.obs_port.setRange(1024, 65535)
        self.obs_port.setValue(8787)
        self.obs_port.setFixedWidth(80)
        self.obs_port.editingFinished.connect(lambda: self.obs_cb.isChecked() and self.toggle_obs(True))
        r.addWidget(self.obs_port)
        r.addStretch()
        v.addLayout(r)

        self.obs_lan = QCheckBox("Allow other PCs on my network (OBS on another PC)")
        self.obs_lan.setToolTip("Listen on your network address instead of only this PC, so a "
                                "streaming PC on the same Wi-Fi/LAN can open the page.")
        self.obs_lan.toggled.connect(self._on_obs_lan)
        v.addWidget(self.obs_lan)
        r = QHBoxLayout()
        l = label("This PC's address")
        l.setFixedWidth(110)
        r.addWidget(l)
        self.obs_ip = QComboBox()
        self.obs_ip.setEditable(True)
        self.obs_ip.setMinimumWidth(60)
        self.obs_ip.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.obs_ip.setToolTip("Pick the address on the same network as the OBS computer "
                               "(usually 192.168.x.x)")
        self.obs_ip.addItems(lan_ips())
        self.obs_ip.currentTextChanged.connect(lambda _: self._refresh_obs_links())
        r.addWidget(self.obs_ip, 1)
        self.fw_btn = button("Open firewall", self.open_firewall,
                             tip="Adds a Windows Firewall rule allowing this port on private networks "
                                 "(asks for administrator permission)")
        r.addWidget(self.fw_btn)
        v.addLayout(r)
        self.obs_lan_row = [l, self.obs_ip, self.fw_btn]
        for w_ in self.obs_lan_row:
            w_.setEnabled(False)

        self.obs_links = {}
        for key, text, q in (("all", "Chat + bars", ""), ("chat", "Chat only", "?bars=0"),
                             ("bars", "Bars only", "?chat=0"), ("rain", "Rain only", "?rain=only")):
            r = QHBoxLayout()
            l = label(text)
            l.setFixedWidth(90)
            r.addWidget(l)
            url = QLineEdit()
            url.setReadOnly(True)
            url.setMinimumWidth(60)
            r.addWidget(url, 1)
            r.addWidget(button("Copy", lambda _, u=url: (QApplication.clipboard().setText(u.text()),
                                                          self.obs_status.setText(T("✓ Copied – in OBS: Sources ▸ + ▸ Browser ▸ paste the URL")))))
            v.addLayout(r)
            self.obs_links[key] = (url, q)
        self.obs_status = label("In OBS add a Browser source, paste the URL, size e.g. 400×600. "
                                "Add &fade=30 to hide messages after 30 s. For \"Rain only\" use the full "
                                "canvas size (e.g. 1920×1080) so the emoji rain covers the whole stream.", muted=True)
        self.obs_status.setWordWrap(True)
        v.addWidget(self.obs_status)
        self._refresh_obs_links()
        v.addStretch()
        return self._scroll(w)

    # ── appearance ────────────────────────────────────────────────────────────
    def _sync_look_widgets(self):
        st = self.style_
        extra = (self.layout_box, self.bub_sl, self.ns_sl, self.rad_sl, self.bw_sl, self.anim_box, self.fade_spin,
                 self.rain_cb, self.rain_trig_cb,
                 self.rain_amt_sl, self.rain_cd_sl, self.rain_screen_cb, self.rain_mon_box, self.rain_obs_cb)
        for w in (self.font_box, self.size_sl, self.alpha_sl, self.dir_box, self.max_spin,
                  self.barh_sl, self.barf_sl, *extra, *self.checks.values()):
            w.blockSignals(True)
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(st.layout)))
        self.bub_sl.setValue(int(st.bubble_alpha * 100))
        self.bub_lbl.setText(f"{int(st.bubble_alpha * 100)}%")
        self.rad_sl.setValue(st.radius)
        self.rad_lbl.setText(f"{st.radius}px")
        self.rain_cb.setChecked(st.rain_enabled)
        self.rain_trig_cb.setChecked(st.rain_triggers_only)
        self.rain_amt_sl.setValue(st.rain_amount)
        self.rain_amt_lbl.setText(str(st.rain_amount))
        self.rain_cd_sl.setValue(int(st.rain_cooldown))
        self.rain_cd_lbl.setText(f"{int(st.rain_cooldown)}s")
        self.rain_screen_cb.setChecked(st.rain_screen)
        self.rain_mon_box.setEnabled(st.rain_screen)
        self.rain_mon_box.setCurrentIndex(max(0, self.rain_mon_box.findData(st.rain_screen_monitor)))
        self.rain_obs_cb.setChecked(st.rain_obs_chat)
        self.bw_sl.setValue(st.border_width)
        self.bw_lbl.setText(f"{st.border_width}px")
        self.anim_box.setCurrentIndex(max(0, self.anim_box.findData(st.anim_in)))
        self.fade_spin.setValue(int(st.fade_after))
        self.fade_only_cb.blockSignals(True)
        self.fade_only_cb.setChecked(st.fade_overlay_only)
        self.fade_only_cb.blockSignals(False)
        self.ns_sl.setValue(int(round(st.name_scale * 100)))
        self.ns_lbl.setText(f"{int(round(st.name_scale * 100))}%")
        self.barh_sl.setValue(st.bar_height)
        self.barh_lbl.setText(f"{st.bar_height}px")
        self.barf_sl.setValue(st.bar_font)
        self.barf_lbl.setText(f"{st.bar_font}px")
        self.font_box.setCurrentFont(QFont(st.font_family))
        self.size_sl.setValue(st.font_size)
        self.size_lbl.setText(f"{st.font_size}px")
        self.alpha_sl.setValue(int(st.bg_alpha * 100))
        self.alpha_lbl.setText(f"{int(st.bg_alpha * 100)}%")
        self.dir_box.setCurrentIndex(max(0, self.dir_box.findData(st.direction)))
        self.max_spin.setValue(st.max_messages)
        for k, cb in self.checks.items():
            cb.setChecked(getattr(st, k))
        for w in (self.font_box, self.size_sl, self.alpha_sl, self.dir_box, self.max_spin,
                  self.barh_sl, self.barf_sl, *extra, *self.checks.values()):
            w.blockSignals(False)
        for k, b in self.color_btns.items():
            b.setStyleSheet(f"background:{getattr(st, k)}; border:1px solid #3a4158; border-radius:6px;")
        for (plat, role), cb in self.fx_boxes.items():
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData((st.effects or {}).get(plat, {}).get(role, "none"))))
            cb.blockSignals(False)

    def _set(self, key, value):
        setattr(self.style_, key, value)
        if not hasattr(self, "_restyle"):
            self._restyle = QTimer(self)
            self._restyle.setSingleShot(True)
            self._restyle.timeout.connect(self._apply_style)
        self._restyle.start(150)

    def _apply_style(self):
        self.view.apply_style()
        self.progress.set_size(self.style_.bar_height, self.style_.bar_font)
        if self.overlay:
            self.overlay.view.apply_style()
            self.overlay.progress.set_size(self.style_.bar_height, self.style_.bar_font)
        self._obs_config()

    # ── OBS browser source ────────────────────────────────────────────────────
    def _render_icons(self) -> Dict[str, bytes]:
        from PyQt6.QtCore import QBuffer, QIODevice
        out = {}
        for kind in all_badge_kinds():
            pm = badge_icon(kind, 36)
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            pm.toImage().save(buf, "PNG")
            out[kind] = bytes(buf.data())
        return out

    def _refresh_obs_links(self):
        host = (self.obs_ip.currentText().strip() or "127.0.0.1") if self.obs_lan.isChecked() else "127.0.0.1"
        base = f"http://{host}:{self.obs_port.value()}/"
        for url, q in self.obs_links.values():
            url.setText(base + q)
            url.setCursorPosition(0)            # show the start of the link, not the end
        if self.obs_ip.lineEdit():
            self.obs_ip.lineEdit().setCursorPosition(0)

    def _on_obs_lan(self, on: bool):
        for w_ in self.obs_lan_row:
            w_.setEnabled(on)
        if on and self.obs_ip.count() == 0:
            self.obs_ip.addItems(lan_ips())
        self._refresh_obs_links()
        if self.obs_cb.isChecked():
            self.toggle_obs(True)                  # restart on the new interface

    def open_firewall(self):
        """Ask Windows (UAC prompt) to allow incoming connections on the OBS port."""
        import ctypes
        port = self.obs_port.value()
        args = (f'advfirewall firewall add rule name="RetChat OBS {port}" dir=in action=allow '
                f'protocol=TCP localport={port} profile=private,domain')
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0)
        except Exception:
            rc = 0
        if rc > 32:
            self.obs_status.setText(T("✓ Firewall rule added for port {port} (private networks). "
                                      "Now open the link on the OBS PC.").format(port=port))
            self.obs_status.setStyleSheet(f"color:{theme.GREEN}; font-size:12px;")
        else:
            self.obs_status.setText(T("✗ Firewall rule not added (permission was declined)."))
            self.obs_status.setStyleSheet("color:#ff8a8a; font-size:12px;")

    def toggle_obs(self, on: bool):
        self._refresh_obs_links()
        if on:
            self.obs_status.setText(T("Starting…"))
            self.obs.start(self.obs_port.value(), lambda ok, msg: self.bridge.obs_result.emit(ok, msg),
                           lan=self.obs_lan.isChecked())
        else:
            self.obs.stop()
            self.obs_status.setText(T("Off."))

    def on_obs_result(self, ok: bool, msg: str):
        if ok:
            if self.obs.lan:
                self.obs_status.setText(T(
                    "✓ Running on your network. On the OBS PC: Sources ▸ + ▸ Browser ▸ paste a URL above. "
                    "If it doesn't load there, click 'Open firewall' and make sure both PCs are on "
                    "the same network (Windows network type: Private)."))
            else:
                self.obs_status.setText(T("✓ Running – in OBS: Sources ▸ + ▸ Browser ▸ paste a URL above "
                                          "(width 400, height 600 works well). Add &fade=30 to hide old messages."))
            self.obs_status.setStyleSheet(f"color:{theme.GREEN}; font-size:12px;")
            self._obs_config()
            self._obs_progress()
            for m in list(self.messages)[-60:]:
                if self.view.visible(m):
                    self.obs.publish("msg", self._obs_msg(m))
        else:
            self.obs_status.setText("✗ " + msg)
            self.obs_status.setStyleSheet("color:#ff8a8a; font-size:12px;")
            self.obs_cb.blockSignals(True)
            self.obs_cb.setChecked(False)
            self.obs_cb.blockSignals(False)

    def _obs_on(self) -> bool:
        return self.obs_cb.isChecked() and self.obs.port is not None

    def _obs_config(self):
        if not hasattr(self, "obs_cb") or not self.obs_cb.isChecked():
            return
        st = self.style_
        c = QColor(st.bg)
        cfg = {k: getattr(st, k) for k in ("font_family", "font_size", "color_text", "color_user",
                                           "show_platform", "show_badges", "max_messages",
                                           "bar_height", "bar_font")}
        cfg["bg_rgba"] = f"rgba({c.red()},{c.green()},{c.blue()},{st.bg_alpha:.2f})"
        bc = QColor(st.bubble_bg)
        cfg["bubble_rgba"] = f"rgba({bc.red()},{bc.green()},{bc.blue()},{st.bubble_alpha:.2f})"
        cfg.update(layout=st.layout, radius=st.radius, show_time=st.show_time, anim_in=st.anim_in,
                   fade_after=st.fade_after, border_width=st.border_width, border_color=st.border_color,
                   name_scale=st.name_scale, show_avatars=st.show_avatars, rain_in_chat=st.rain_obs_chat)
        nc = QColor(st.name_bg)
        cfg["name_rgba"] = f"rgba({nc.red()},{nc.green()},{nc.blue()},{st.bubble_alpha:.2f})"
        self.obs.publish("config", cfg)

    def _obs_msg(self, m: dict) -> dict:
        st = self.style_
        return {
            "id": f"{m.get('source', '')}|{m.get('id', '')}",
            "username": m.get("username", "?"),
            "color": _readable(m.get("color"), st.color_user) if st.use_user_colors else st.color_user,
            "parts": m.get("parts") or [{"type": "text", "text": m.get("text", "")}],
            "badges": m.get("badges") or [],
            "platform": m.get("platform", ""),
            "reply": m.get("reply"),
            "rtl": self.view.is_rtl(m),
            "trig": bool(m.get("_trigger") and st.highlight_triggers),
            "trig_color": m.get("_trigger_color") or "#7c5cff",
            **dict(zip(("fx", "fxc"), effect_for(m, st.effects))),
            "proxy": m.get("proxy") or "",
            "avatar": m.get("avatar") or "",
            "user_key": m.get("user_key") or "",
        }

    def _obs_progress(self):
        if not self.obs_cb.isChecked():
            return
        out = []
        for b in self.visible_bars():
            if True:
                out.append({"id": str(id(b)), "color": b.color, "acc": min(b.acc, b.threshold),
                            "threshold": b.threshold, "label": b.bar_label()})
        self.obs.publish("progress", out)

    def _set_fx(self, plat: str, role: str, code: str):
        eff = {k: dict(v_) for k, v_ in (self.style_.effects or {}).items()}
        eff.setdefault(plat, {})[role] = code
        self._set("effects", eff)

    def apply_theme(self, theme_: dict):
        for k, val in theme_.items():
            setattr(self.style_, k, val)
        self._sync_look_widgets()
        self._apply_style()
        self.save_settings()

    def _pick_color(self, key):
        c = QColorDialog.getColor(QColor(getattr(self.style_, key)), self, T("Choose colour"))
        if c.isValid():
            self._set(key, c.name())
            self._sync_look_widgets()

    # ── channels ──────────────────────────────────────────────────────────────
    # ── proxy ─────────────────────────────────────────────────────────────────
    def proxy_spec(self) -> str:
        host = self.proxy_host.text().strip() or "127.0.0.1"
        return f"{self.proxy_type.currentData()}://{host}:{self.proxy_port.value()}"

    def row_proxy(self, row: ChannelRow) -> Optional[str]:
        mode = row.route_mode
        if mode == "custom":
            return self.proxy_spec()
        if mode == "system":
            return "system"
        return None

    def _start_row(self, row: ChannelRow):
        spec = self.row_proxy(row)
        self.hub.start(row.target, spec)
        via = proxy_label(spec)
        row.set_state("connecting", "Connecting…" if via == "direct" else T("Connecting via {p}…").format(p=via))

    def _restart_row(self, row: ChannelRow):
        if row.state == "stopped":
            return
        self.hub.stop(row.target.key)
        self._start_row(row)

    def on_route_changed(self, row: ChannelRow):
        self._restart_row(row)
        self.save_settings()

    def _on_proxy_type(self):
        # flip between the usual v2ray ports when the type changes
        if self.proxy_port.value() in (10808, 10809):
            self.proxy_port.blockSignals(True)
            self.proxy_port.setValue(10808 if self.proxy_type.currentData() == "socks5" else 10809)
            self.proxy_port.blockSignals(False)
        self._proxy_timer.start(300)

    def _proxy_changed(self):
        for row in self.rows.values():
            if row.route_mode == "custom":
                self._restart_row(row)

    def test_proxy(self):
        spec = self.proxy_spec()
        self.proxy_test_btn.setEnabled(False)
        self.proxy_result.setText(T("Testing {p} …").format(p=spec))
        self.proxy_result.setStyleSheet("")
        self.hub.test_proxy(spec, lambda ok, msg: self.bridge.proxy_result.emit(ok, msg))

    def on_proxy_result(self, ok: bool, msg: str):
        self.proxy_test_btn.setEnabled(True)
        self.proxy_result.setText(("✓ " if ok else "✗ ") + msg)
        self.proxy_result.setStyleSheet(f"color: {theme.GREEN if ok else '#ff8a8a'}; font-size: 12px;")

    def _refresh_system_proxy(self):
        url = resolve_proxy("system")
        self.sys_proxy_lbl.setText(T("System: {p}").format(p=url.split('://')[-1]) if url else T("System proxy: off"))
        self.sys_proxy_lbl.setToolTip(url or "Windows has no proxy configured")

    # ── channels ──────────────────────────────────────────────────────────────
    def add_target(self, raw: Optional[str] = None, connect: bool = True, route: Optional[str] = None):
        text = raw if isinstance(raw, str) else self.target_in.text()
        t = parse_target(text)
        if not t:
            self.add_err.setText(T("⚠  Not a supported link. Use a Twitch, Kick, YouTube, Aparat or OneFa channel URL."))
            self.add_err.show()
            return
        self.add_err.hide()
        if t.key in self.rows:
            self.target_in.clear()
            return
        row = ChannelRow(t, self.toggle_channel, self.remove_channel, self.on_route_changed,
                         route or self.add_route.currentData() or "direct")
        self.rows[t.key] = row
        self.chan_lay.insertWidget(self.chan_lay.count() - 1, row)
        self.empty_chan.hide()
        self.target_in.clear()
        if connect:
            self._start_row(row)

    def toggle_channel(self, row: ChannelRow):
        if row.state in ("live", "connecting", "error"):
            self.hub.stop(row.target.key)
            row.set_state("stopped")
        else:
            self._start_row(row)

    def remove_channel(self, row: ChannelRow):
        self.hub.stop(row.target.key)
        self.rows.pop(row.target.key, None)
        row.deleteLater()
        self.empty_chan.setVisible(not self.rows)

    def connect_all(self):
        for row in self.rows.values():
            if row.state == "stopped":
                self.toggle_channel(row)

    def disconnect_all(self):
        for row in self.rows.values():
            if row.state != "stopped":
                self.toggle_channel(row)

    def on_status(self, key: str, state: str, text: str):
        row = self.rows.get(key)
        if not row:
            return
        if state == "stopped" and row.state == "stopped":
            return
        if state == "stopped":
            return            # user-initiated stop already reflected
        row.set_state(state, text)
        if state == "error":
            self.view.log(f"{row.target.label()}: {text}", "#ff8a8a")

    # ── messages & triggers ───────────────────────────────────────────────────
    def on_message(self, msg: dict):
        if msg.get("type") == "avatar":                 # a looked-up profile picture
            for m in self.messages:
                if m.get("user_key") == msg["user_key"] and not m.get("avatar"):
                    m["avatar"] = msg["avatar"]
            self.view.update_avatar(msg["user_key"], msg["avatar"], msg.get("proxy") or None)
            if self.overlay:
                self.overlay.view.update_avatar(msg["user_key"], msg["avatar"], msg.get("proxy") or None)
            if self.obs_cb.isChecked():
                self.obs.publish("avatar", {"user_key": msg["user_key"], "avatar": msg["avatar"],
                                            "proxy": msg.get("proxy") or ""})
            return
        if msg.get("type") == "delete":                 # a moderator deleted / banned / cleared
            self._on_delete(msg)
            return
        row = self.rows.get(msg.get("source", ""))
        if row is None or row.state == "stopped":
            return                                  # late message from a stopped channel
        row.count += 1
        if row.state != "live":
            row.set_state("live", row.text if row.text.startswith("Connected") else "Connected")
        if not msg.get("history"):
            self._rate.append(time.time())
        msg["bot"] = is_bot(msg, self._bots)
        fired = self.bm.process(msg) if self.triggers_on else []   # paused = triggers off
        self.messages.append(msg)
        self.view.add_message(msg)
        if self.overlay:
            self.overlay.view.add_message(msg)
        if self.obs_cb.isChecked() and self.view.visible(msg):
            self.obs.publish("msg", self._obs_msg(msg))
        if msg.get("_trigger"):
            self._dirty_bindings = True
        self._maybe_rain(msg)
        for b in fired:
            self.progress.celebrate(b)
            if self.overlay:
                self.overlay.progress.celebrate(b)
            if self.obs_cb.isChecked():
                self.obs.publish("celebrate", {"id": str(id(b))})
            who = msg.get("username", "?")
            if self.triggers_on:
                self.run_action(b)
                self.log_activity(T("🔑 '{word}' reached {n} → {key}  (last: {who})").format(
                    word=b.word, n=b.threshold, key=b.action_text(), who=who))
            else:
                self.log_activity(T("⏸ '{word}' reached {n} but triggers are paused").format(word=b.word, n=b.threshold))

    def _on_delete(self, ev: dict):
        """Remove messages a moderator deleted from the app, the overlay and OBS."""
        src = ev.get("source", "")
        ids = set(ev.get("ids") or [])
        uk, uid, every = ev.get("user_key") or "", ev.get("uid") or "", bool(ev.get("all"))

        def gone(m: dict) -> bool:
            if m.get("system") or m.get("source") != src:
                return False
            return (every or str(m.get("id", "")) in ids
                    or (uk and m.get("user_key") == uk) or (uid and str(m.get("uid", "")) == uid))

        hit = [m for m in self.messages if gone(m)]
        if not hit:
            return
        keep = [m for m in self.messages if not gone(m)]
        self.messages.clear()
        self.messages.extend(keep)
        self.view.remove_messages(gone)
        if self.overlay:
            self.overlay.view.remove_messages(gone)
        if self.obs_cb.isChecked():
            self.obs.publish("delete", {"ids": [f"{src}|{m.get('id', '')}" for m in hit]})

    def _maybe_rain(self, msg: dict):
        st = self.style_
        if not st.rain_enabled or msg.get("history") or not self.view.visible(msg):
            return
        if st.rain_triggers_only and not msg.get("_trigger"):
            return
        now = time.time()
        if now - getattr(self, "_last_rain", 0) < st.rain_cooldown:
            return
        sym = rain_symbol(msg)
        if not sym:
            return
        self._last_rain = now
        proxy = msg.get("proxy") or None
        self._rain_everywhere(sym, proxy)

    def _rain_everywhere(self, sym: dict, proxy=None):
        st = self.style_
        self.view.rain(sym, proxy)
        if self.overlay:
            self.overlay.view.rain(sym, proxy)
        if st.rain_screen:
            if self.screen_rain is None:
                self.screen_rain = ScreenRain(self.images)
            self.screen_rain.rain(sym, st.rain_amount, proxy, st.rain_screen_monitor)
        if self.obs_cb.isChecked():
            self.obs.publish("rain", {**sym, "amount": st.rain_amount})

    def _test_rain(self):
        self._rain_everywhere({"emoji": random.choice(["🎉", "🔥", "😂", "❤️", "⭐", "🍕", "👑", "💎"])})

    def on_key_result(self, key: str, ok: bool, err: str):
        if ok:
            self.last_lbl.setText(T("✓ Pressed {key} at {t}  →  focused window: {w}").format(
                key=key, t=time.strftime('%H:%M:%S'), w=isend.foreground_title()[:60] or '?'))
        else:
            self.last_lbl.setText(f"✗ {key}: {err}")
            self.log_activity(f"✗ {key}: {err}", error=True)

    def log_activity(self, text: str, error=False):
        self.activity.insertItem(0, f"{time.strftime('%H:%M:%S')}  {text}")
        it = self.activity.item(0)
        it.setForeground(QColor("#ff8a8a" if error else theme.TEXT))
        while self.activity.count() > 200:
            self.activity.takeItem(self.activity.count() - 1)

    def toggle_triggers(self):
        self.triggers_on = not self.triggers_on
        self._refresh_master()
        self.refresh_bars()                       # paused → no bars anywhere

    def _refresh_master(self):
        if self.triggers_on:
            self.master.setText(T("●  Triggers ON – key presses will be sent"))
            self.master.setObjectName("toggleOn")
        else:
            self.master.setText(T("⏸  Triggers PAUSED – click to resume"))
            self.master.setObjectName("")
        self.master.style().unpolish(self.master)
        self.master.style().polish(self.master)

    # ── bindings UI ───────────────────────────────────────────────────────────
    def visible_bars(self) -> List[Binding]:
        """Bars to show: none while paused; otherwise active triggers with a bar."""
        if not self.triggers_on:
            return []
        return [b for b in self.bm.bindings if self.bm.is_active(b) and b.show_progress]

    def refresh_bars(self):
        vis = self.visible_bars()
        self.progress.rebuild(vis)
        if self.overlay:
            self.overlay.progress.rebuild(vis)
        self._obs_progress()

    def rebuild_bindings(self):
        self.bm.ensure_groups()
        for w_ in self._bind_widgets:
            w_.deleteLater()
        self._bind_widgets, self.brows = [], []

        def add(widget):
            self.bind_lay.insertWidget(self.bind_lay.count() - 1, widget)
            self._bind_widgets.append(widget)

        for name, info in self.bm.groups.items():
            members = [b for b in self.bm.bindings if b.group == name]
            add(GroupHeader(name, info, len(members), self.set_group_active, self.toggle_group_collapsed,
                            self.add_binding, self.rename_group, self.delete_group))
            if info.get("collapsed"):
                continue
            for b in members:
                r = BindingRow(b, self.edit_binding, self.test_binding, self.delete_binding,
                               self.enable_binding)
                r.group_active = bool(info.get("active", True))
                r.refresh()
                holder = QWidget()                    # indent rows under their group
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(16, 0, 0, 0)
                hl.addWidget(r)
                add(holder)
                self.brows.append(r)
            if not members:
                hint = label("   No triggers in this group yet – click + on the group.", muted=True)
                add(hint)
        self.empty_bind.setVisible(not self.bm.bindings)
        self.refresh_bars()

    # ── groups ────────────────────────────────────────────────────────────────
    def set_group_active(self, name: str, on: bool):
        if on and self.exclusive_groups:
            for g in self.bm.groups:
                self.bm.groups[g]["active"] = False
        self.bm.groups.setdefault(name, {"collapsed": False})["active"] = on
        state = "activated" if on else "deactivated"
        self.log_activity(T("Group '{name}' activated" if on else "Group '{name}' deactivated").format(name=name))
        QTimer.singleShot(0, self.rebuild_bindings)   # don't delete the checkbox inside its own signal
        self.save_settings()

    def toggle_group_collapsed(self, name: str):
        g = self.bm.groups.setdefault(name, {"active": True})
        g["collapsed"] = not g.get("collapsed", False)
        QTimer.singleShot(0, self.rebuild_bindings)
        self.save_settings()

    def add_group(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, T("New group"), T("Group name (e.g. CS GO, Valorant):"))
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self.bm.groups:
            QMessageBox.information(self, T("New group"), T("A group called '{name}' already exists.").format(name=name))
            return
        self.bm.groups[name] = {"active": not self.exclusive_groups, "collapsed": False}
        self.rebuild_bindings()
        self.save_settings()

    def rename_group(self, old: str):
        from PyQt6.QtWidgets import QInputDialog
        new, ok = QInputDialog.getText(self, T("Rename group"), T("New name:"), text=old)
        new = (new or "").strip()
        if not ok or not new or new == old:
            return
        if new in self.bm.groups:
            QMessageBox.information(self, T("Rename group"), T("A group called '{name}' already exists.").format(name=new))
            return
        self.bm.groups = {(new if k == old else k): v for k, v in self.bm.groups.items()}
        for b in self.bm.bindings:
            if b.group == old:
                b.group = new
        self.rebuild_bindings()
        self.save_settings()

    def delete_group(self, name: str):
        members = [b for b in self.bm.bindings if b.group == name]
        msg = (T("Delete the group '{name}' and its {n} trigger(s)?").format(name=name, n=len(members)) if members
               else T("Delete the empty group '{name}'?").format(name=name))
        if QMessageBox.question(self, T("Delete group"), msg) != QMessageBox.StandardButton.Yes:
            return
        self.bm.bindings = [b for b in self.bm.bindings if b.group != name]
        self.bm.groups.pop(name, None)
        self.rebuild_bindings()
        self.save_settings()

    # ── triggers ──────────────────────────────────────────────────────────────
    def _default_group(self) -> str:
        for g, info in self.bm.groups.items():
            if info.get("active"):
                return g
        return next(iter(self.bm.groups), "General")

    def add_binding(self, group: Optional[str] = None):
        self.bm.ensure_groups()
        d = BindingDialog(None, self.sender, self, groups=list(self.bm.groups),
                          group=group or self._default_group(), run_action=self.run_action)
        if d.exec():
            nb = d.binding()
            if nb.group not in self.bm.groups:          # typed a new group name
                self.bm.groups[nb.group] = {"active": not self.exclusive_groups, "collapsed": False}
            self.bm.bindings.append(nb)
            self.rebuild_bindings()
            self.save_settings()

    def edit_binding(self, row: BindingRow):
        d = BindingDialog(row.b, self.sender, self, groups=list(self.bm.groups), run_action=self.run_action)
        if d.exec():
            i = self.bm.bindings.index(row.b)
            nb = d.binding()
            nb.acc = row.b.acc if nb.threshold == row.b.threshold else 0
            if nb.group not in self.bm.groups:
                self.bm.groups[nb.group] = {"active": not self.exclusive_groups, "collapsed": False}
            self.bm.bindings[i] = nb
            self.rebuild_bindings()
            self.save_settings()

    def delete_binding(self, row: BindingRow):
        if QMessageBox.question(self, T("Delete trigger"),
                                T("Delete the trigger '{word}' → {key}?").format(word=row.b.word, key=row.b.action_text())) \
                == QMessageBox.StandardButton.Yes:
            self.bm.bindings.remove(row.b)
            self.rebuild_bindings()
            self.save_settings()

    def enable_binding(self, row: BindingRow, on: bool):
        row.b.enabled = on
        row.refresh()
        self.refresh_bars()

    def test_binding(self, row: BindingRow):
        b = row.b
        if b.action == "shutdown":
            self.log_activity(T("Shut down triggers can't be tested (it would shut down the PC)"))
            return
        self.log_activity(T("Test: {key} in 3 s – switch to your game now").format(key=b.action_text()))
        QTimer.singleShot(3000, lambda: self.run_action(b))

    # ── trigger actions ──────────────────────────────────────────────────────
    def run_action(self, b: Binding):
        """Do what a fired trigger is set to do (press / block / shut down)."""
        a = b.action
        try:
            if a == "block_key":
                self.blocker.block_keys(b.key, b.duration)
            elif a == "block_keyboard":
                self.blocker.block_keyboard(b.duration)
            elif a == "block_mouse":
                self.blocker.block_mouse(b.duration)
            elif a == "shutdown":
                self._schedule_shutdown(int(max(10, b.duration)), b.word)
            else:
                self.sender.press(b.key, b.hold_ms, b.repeat)
        except Exception as exc:
            self.log_activity(f"✗ {b.action_text()}: {exc}", error=True)

    def _on_block_state(self, state: str):
        if state == "blocking":
            self.last_lbl.setText(T("⛔ Blocking input: {what}  ·  press Esc 5× to unblock").format(
                what=self.blocker.describe() or "…"))
            if isend.foreground_is_elevated() and not isend.is_admin():
                self.log_activity(T("✗ The focused app runs as administrator – Windows doesn't let RetChat block "
                                    "its input. Restart RetChat as administrator."), error=True)
        elif state == "unblocked":
            self.log_activity(T("✓ Esc pressed 5× – all input unblocked"))
        elif state == "ended":
            self.last_lbl.setText(T("✓ Input unblocked at {t}").format(t=time.strftime('%H:%M:%S')))
        elif state == "error":
            self.log_activity(T("✗ Could not block input (Windows refused the input hook)"), error=True)

    def _schedule_shutdown(self, secs: int, word: str):
        import subprocess
        if self._shutdown_box is not None:
            return                                        # one is already counting down
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(["shutdown", "/s", "/t", str(secs), "/c",
                            f"RetChat: chat trigger '{word}' – shutting down in {secs} s"],
                           capture_output=True, creationflags=flags)
        if r.returncode != 0:
            self.log_activity(T("✗ Shut down failed: {e}").format(
                e=(r.stderr or r.stdout or b"").decode(errors="replace").strip() or r.returncode), error=True)
            return
        self.log_activity(T("⏻ Shutting down the PC in {s} s (trigger '{word}')").format(s=secs, word=word),
                          error=True)
        box = QMessageBox(QMessageBox.Icon.Warning, "RetChat",
                          T("A chat trigger ('{word}') is shutting down this PC in {s} seconds.").format(
                              word=word, s=secs), parent=self)
        cancel = box.addButton(T("Cancel shut down"), QMessageBox.ButtonRole.RejectRole)
        box.addButton(T("Let it shut down"), QMessageBox.ButtonRole.AcceptRole)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        box.setModal(False)
        self._shutdown_box = box

        def done(_):
            self._shutdown_box = None
            if box.clickedButton() is cancel:
                subprocess.run(["shutdown", "/a"], capture_output=True, creationflags=flags)
                self.log_activity(T("✓ Shut down cancelled"))
        box.finished.connect(done)
        box.show()
        box.raise_()

    def reset_points(self):
        for b in self.bm.bindings:
            b.reset()
            b.last_fire = 0
        self._dirty_bindings = True

    # ── periodic ──────────────────────────────────────────────────────────────
    def _periodic(self):
        now = time.time()
        n = sum(1 for t in self._rate if now - t < 60)
        live = sum(1 for r in self.rows.values() if r.state == "live")
        self.rate_lbl.setText(T("{live} connected · {n} msg/min").format(live=live, n=n))
        cooling = any(b.cooling() for b in self.bm.bindings)
        if getattr(self, "_dirty_bindings", False) or cooling:
            self._dirty_bindings = False
            for r in self.brows:
                r.refresh()
            self.progress.refresh()
            if self.overlay:
                self.overlay.progress.refresh()
            self._obs_progress()
        for r in self.rows.values():
            r.refresh()

    def _check_elevation(self):
        self._refresh_system_proxy()
        admin = isend.is_admin()
        self.admin_pill.setVisible(admin)
        self.admin_btn.setVisible(not admin)
        if admin:
            self.admin_pill.setText(T("Admin ✓"))
            self.admin_pill.setObjectName("pillOk")
            self.admin_pill.setToolTip(T("Running as administrator – can send keys to any game"))
            self.admin_pill.style().unpolish(self.admin_pill)
            self.admin_pill.style().polish(self.admin_pill)
        if self.isActiveWindow():
            return
        title = isend.foreground_title()
        if not admin and title and isend.foreground_is_elevated():
            self.elev_warn.setText(T("⚠  '{title}' runs as administrator – Windows will block key presses "
                                     "to it. Click 'Run as admin' (top right).").format(title=title[:50]))
            self.elev_warn.show()
        else:
            self.elev_warn.hide()

    def _change_language(self):
        code = self.lang_box.currentData()
        if code == i18n.LANG:
            return
        if QMessageBox.question(self, "RetChat", FA_EN_RESTART[code]) != QMessageBox.StandardButton.Yes:
            self.lang_box.blockSignals(True)
            self.lang_box.setCurrentIndex(max(0, self.lang_box.findData(i18n.LANG)))
            self.lang_box.blockSignals(False)
            return
        self._lang_next = code
        self.save_settings()
        import subprocess
        args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        # The one-file exe unpacks itself to a temp folder that is deleted when this copy closes.
        # Without this flag the new copy would reuse that folder and fail with
        # "no Qt platform plugin could be initialized" once it disappears.
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen([sys.executable] + args, env=env, close_fds=True)
        self.close()
        QApplication.quit()

    def restart_admin(self):
        if isend.is_admin():
            return
        self.save_settings()
        if isend.relaunch_as_admin():
            self.hub.shutdown()
            QApplication.quit()

    # ── overlay ───────────────────────────────────────────────────────────────
    def toggle_overlay(self):
        if self.overlay:
            self.overlay.close()
            return
        self.overlay = OverlayWindow(self.images, self.style_)
        self.overlay.closed.connect(self._overlay_closed)
        self.overlay.view.set_messages(list(self.messages))
        self.overlay.progress.rebuild(self.visible_bars())
        geo = getattr(self, "_overlay_geo", None)
        if geo:
            self.overlay.setGeometry(*geo)
        self.overlay.show()
        self.overlay_btn.setText(T("⧉  Close overlay"))
        self.lock_btn.setEnabled(True)

    def _overlay_closed(self):
        g = self.overlay.geometry()
        self._overlay_geo = (g.x(), g.y(), g.width(), g.height())
        self.overlay = None
        self.overlay_btn.setText(T("⧉  Overlay"))
        self.lock_btn.setEnabled(False)
        self.lock_btn.setText("🔓")
        self.lock_btn.setProperty("active", False)

    def toggle_lock(self):
        if not self.overlay:
            return
        lock = not self.overlay.locked
        self.overlay.set_locked(lock)
        self.lock_btn.setText("🔒" if lock else "🔓")
        self.lock_btn.setProperty("active", lock)
        self.lock_btn.style().unpolish(self.lock_btn)
        self.lock_btn.style().polish(self.lock_btn)

    # ── misc ──────────────────────────────────────────────────────────────────
    def clear_chat(self):
        self.messages.clear()
        self.view.clear_chat()
        if self.overlay:
            self.overlay.view.clear_chat()
        if self.obs_cb.isChecked():
            self.obs.publish("clear", {})

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, T("Save chat"), "chat.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(list(self.messages), f, ensure_ascii=False, indent=2)
            self.view.log(T("Saved {n} messages → {path}").format(n=len(self.messages), path=path))

    # ── settings ──────────────────────────────────────────────────────────────
    def save_settings(self):
        data = {
            "version": VERSION,
            "geometry": bytes(self.saveGeometry().toBase64()).decode(),
            "targets": [r.target.to_str() for r in self.rows.values()],
            "connected": [r.target.to_str() for r in self.rows.values() if r.state != "stopped"],
            "routes": {r.target.to_str(): r.route_mode for r in self.rows.values()},
            "proxy": {"type": self.proxy_type.currentData(), "host": self.proxy_host.text().strip(),
                      "port": self.proxy_port.value()},
            "add_route": self.add_route.currentData(),
            "bindings": [b.to_dict() for b in self.bm.bindings],
            "groups": [{"name": k, **v} for k, v in self.bm.groups.items()],
            "exclusive_groups": self.exclusive_groups,
            "style": self.style_.to_dict(),
            "scancode": self.sender.use_scancode,
            "animate": self.images.animate,
            "bots": self.bot_edit.text(),
            "count_bots": self.bm.count_bots,
            "obs": {"enabled": self.obs_cb.isChecked(), "port": self.obs_port.value(),
                    "lan": self.obs_lan.isChecked(), "ip": self.obs_ip.currentText().strip()},
            "overlay_geo": getattr(self, "_overlay_geo", None),
            "tab": self.tabs.currentIndex(),
            "lang": getattr(self, "_lang_next", i18n.LANG),
        }
        try:
            SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.view.log(f"Could not save settings: {e}", "#ff8a8a")

    def load_settings(self):
        data, migrated = {}, False
        try:
            if SETTINGS.exists():
                data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            elif OLD_SETTINGS.exists():
                old = json.loads(OLD_SETTINGS.read_text(encoding="utf-8"))
                migrated = True
                data = {
                    "targets": old.get("targets", []),
                    "bindings": old.get("bindings", []),
                    "style": {"font_size": max(10, old.get("font_size", 13)),
                              "color_text": old.get("color_msg", "#e6e8ef"),
                              "color_user": old.get("color_user", "#7cc4ff"),
                              "bg_alpha": old.get("bg_alpha", 1.0)},
                }
        except Exception as e:
            self.view.log(f"Could not read settings: {e}", "#ff8a8a")
        if data.get("geometry"):
            from PyQt6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(data["geometry"].encode()))
        saved_style = data.get("style", {}) or {}
        self.style_.__dict__.update(ChatStyle.from_dict(saved_style).__dict__)
        if saved_style and "name_bg" not in saved_style:    # before the name tab existed
            self.style_.name_scale = ChatStyle().name_scale
        if saved_style and "layout" not in saved_style:     # settings from before bubbles existed
            self.style_.bg_alpha = 0.0                          # → background only behind messages
        self.sender.use_scancode = data.get("scancode", True)
        self.key_mode.setCurrentIndex(0 if self.sender.use_scancode else 1)
        self.images.animate = data.get("animate", True)
        self.anim_cb.setChecked(self.images.animate)
        self.bot_edit.setText(data.get("bots", DEFAULT_BOTS))
        self.bm.count_bots = bool(data.get("count_bots", False))
        self.count_bots_cb.setChecked(self.bm.count_bots)
        obs = data.get("obs") or {}
        self.obs_port.setValue(int(obs.get("port", 8787)))
        ip = obs.get("ip")
        if ip and ip in [self.obs_ip.itemText(i) for i in range(self.obs_ip.count())]:
            self.obs_ip.setCurrentText(ip)          # only if this PC still has that address
        self.obs_lan.blockSignals(True)
        self.obs_lan.setChecked(bool(obs.get("lan")))
        self.obs_lan.blockSignals(False)
        for w_ in self.obs_lan_row:
            w_.setEnabled(self.obs_lan.isChecked())
        self._refresh_obs_links()
        if obs.get("enabled"):
            self.obs_cb.setChecked(True)
        self._overlay_geo = data.get("overlay_geo")
        self.bm.bindings = [Binding.from_dict(d) for d in data.get("bindings", [])]
        self.bm.groups = {}
        for g in data.get("groups") or []:
            if g.get("name"):
                self.bm.groups[g["name"]] = {"active": bool(g.get("active", True)),
                                             "collapsed": bool(g.get("collapsed", False))}
        self.exclusive_groups = bool(data.get("exclusive_groups", False))
        self.exclusive_cb.setChecked(self.exclusive_groups)
        self.rebuild_bindings()
        self._sync_look_widgets()
        self._apply_style()
        px = data.get("proxy") or {}
        for w in (self.proxy_type, self.proxy_host, self.proxy_port):
            w.blockSignals(True)
        self.proxy_type.setCurrentIndex(max(0, self.proxy_type.findData(px.get("type", "socks5"))))
        self.proxy_host.setText(px.get("host") or "127.0.0.1")
        self.proxy_port.setValue(int(px.get("port") or 10808))
        for w in (self.proxy_type, self.proxy_host, self.proxy_port):
            w.blockSignals(False)
        self.add_route.setCurrentIndex(max(0, self.add_route.findData(data.get("add_route", "direct"))))
        self._refresh_system_proxy()
        routes = data.get("routes") or {}
        connected = set(data.get("connected", []))
        for t in data.get("targets", []):
            pt = parse_target(t)
            self.add_target(t, connect=pt is not None and pt.to_str() in connected,
                            route=routes.get(pt.to_str() if pt else t, "direct"))
        self.add_err.hide()
        self.tabs.setCurrentIndex(int(data.get("tab", 0)))
        if migrated:
            self.view.log(T("Imported your channels and triggers from RetChat 1.x. Press Connect to start."))
        elif not self.rows:
            self.view.log(T("Welcome! Add a channel in the Channels tab, then set up triggers."))

    def closeEvent(self, e):
        self.save_settings()
        if self.overlay:
            self.overlay.close()
        self.hub.shutdown()
        super().closeEvent(e)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("drplague.retchat.2")
        except Exception:
            pass
    try:
        i18n.LANG = json.loads(SETTINGS.read_text(encoding="utf-8")).get("lang", "en") if SETTINGS.exists() else "en"
    except Exception:
        i18n.LANG = "en"
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if i18n.LANG == "fa":
        app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLE + theme.checkbox_css())
    if os.path.exists(resource("logo/app.jpg")):
        app.setWindowIcon(QIcon(resource("logo/app.jpg")))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
