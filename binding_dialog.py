"""Dialogs: key capture and add/edit trigger."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout)

from i18n import T, translate_tree
from bindings import DEFAULT_WEIGHTS, MATCH_MODES, ROLE_LABELS, ROLES, Binding
from input_sender import VK_NAMES, parse_key, pretty_key

_MOD_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}


class KeyCaptureDialog(QDialog):
    """Press a key / key combo / mouse button → ``captured(str)``."""
    captured = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Press a key")
        self.setFixedSize(380, 170)
        lay = QVBoxLayout(self)
        self._lbl = QLabel("Press a key, a key combination,\na mouse button or scroll the wheel…")
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("font-size: 15px;")
        lay.addWidget(self._lbl, 1)
        hint = QLabel("Esc cancels")
        hint.setObjectName("muted")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)
        translate_tree(self)

    def showEvent(self, e):
        super().showEvent(e)
        self.grabKeyboard()

    def done(self, r):
        self.releaseKeyboard()
        super().done(r)

    def _mods(self, m) -> list:
        out = []
        if m & Qt.KeyboardModifier.ControlModifier:
            out.append("Ctrl")
        if m & Qt.KeyboardModifier.ShiftModifier:
            out.append("Shift")
        if m & Qt.KeyboardModifier.AltModifier:
            out.append("Alt")
        if m & Qt.KeyboardModifier.MetaModifier:
            out.append("Win")
        return out

    def _finish(self, name: str, mods: list):
        res = "+".join(mods + [name])
        self.captured.emit(res)
        self.accept()

    def keyPressEvent(self, ev: QKeyEvent):
        if ev.key() == Qt.Key.Key_Escape and not ev.modifiers():
            self.reject()
            return
        vk = ev.nativeVirtualKey()
        if vk in _MOD_VKS or ev.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
                                          Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return            # wait for the real key (lone modifiers: release handler)
        name = VK_NAMES.get(vk)
        if not name:
            name = f"Key_{vk}" if vk else ev.text() or f"Key_{ev.key()}"
        mods = self._mods(ev.modifiers())
        if name.startswith("num") and "Shift" in mods:
            pass
        self._finish(pretty_key(name), mods)

    def keyReleaseEvent(self, ev: QKeyEvent):
        # allow binding a modifier on its own (e.g. just "Shift")
        if ev.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt):
            self._finish({Qt.Key.Key_Shift: "Shift", Qt.Key.Key_Control: "Ctrl",
                          Qt.Key.Key_Alt: "Alt"}[ev.key()], [])

    def mousePressEvent(self, ev):
        names = {Qt.MouseButton.LeftButton: "MouseLeft", Qt.MouseButton.RightButton: "MouseRight",
                 Qt.MouseButton.MiddleButton: "MouseMiddle", Qt.MouseButton.XButton1: "MouseX1",
                 Qt.MouseButton.XButton2: "MouseX2"}
        n = names.get(ev.button())
        if n:
            self._finish(n, self._mods(ev.modifiers()))

    def wheelEvent(self, ev):
        self._finish("MouseWheelUp" if ev.angleDelta().y() > 0 else "MouseWheelDown",
                     self._mods(ev.modifiers()))


class BindingDialog(QDialog):
    """Create / edit a :class:`Binding`.  ``test_press(key, hold, repeat)`` fires a test."""

    def __init__(self, binding: Binding | None, sender, parent=None, groups=None, group: str = ""):
        super().__init__(parent)
        self.sender_ = sender
        self._groups = list(groups or ["General"])
        self.setWindowTitle("New trigger" if binding is None else "Edit trigger")
        self.setMinimumWidth(520)
        self._build()
        self._load(binding or Binding(word="", key="", match="word",
                                      group=group or self._groups[0]))
        self.group.setProperty("noTranslate", True)
        self.word.setProperty("noTranslate", True)
        self.key.setProperty("noTranslate", True)
        translate_tree(self)

    def _section(self, lay, text):
        l = QLabel(text)
        l.setObjectName("h2")
        lay.addWidget(l)

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(18, 18, 18, 18)

        gr = QHBoxLayout()
        gl = QLabel("Group")
        gl.setObjectName("h2")
        gr.addWidget(gl)
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems(self._groups)
        self.group.setToolTip("Pick a group or type a new name (e.g. CS GO, Valorant)")
        gr.addWidget(self.group, 1)
        root.addLayout(gr)

        self._section(root, "When chat says…")
        r = QHBoxLayout()
        self.word = QLineEdit()
        self.word.setPlaceholderText("e.g.  gg   or   سلام")
        r.addWidget(self.word, 2)
        self.match = QComboBox()
        for k, v in MATCH_MODES.items():
            self.match.addItem(v, k)
        r.addWidget(self.match, 3)
        root.addLayout(r)

        self._section(root, "…press")
        r = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setPlaceholderText("Click Record, or type e.g. Ctrl+F1, Space, MouseMiddle")
        self.key.textChanged.connect(self._validate_key)
        r.addWidget(self.key, 1)
        rec = QPushButton("⏺  Record")
        rec.clicked.connect(self._record)
        r.addWidget(rec)
        root.addLayout(r)
        self.key_err = QLabel("")
        self.key_err.setStyleSheet("color:#ff8a8a; font-size:12px;")
        root.addWidget(self.key_err)

        r = QHBoxLayout()
        r.addWidget(QLabel("Hold for"))
        self.hold = QSpinBox()
        self.hold.setRange(10, 5000)
        self.hold.setSuffix(" ms")
        self.hold.setToolTip("How long the key stays down. Games often need 50–150 ms.")
        r.addWidget(self.hold)
        r.addSpacing(12)
        r.addWidget(QLabel("Repeat"))
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 50)
        self.repeat.setSuffix("×")
        r.addWidget(self.repeat)
        r.addStretch()
        self.test_btn = QPushButton("▶  Test in 3 s")
        self.test_btn.setToolTip("Switch to your game – the key is pressed after 3 seconds")
        self.test_btn.clicked.connect(self._test)
        r.addWidget(self.test_btn)
        root.addLayout(r)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#2a3042;")
        root.addWidget(line)

        self._section(root, "Who counts, and how much")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.addWidget(QLabel("Role"), 0, 0)
        hdr = QLabel("Points per message")
        hdr.setObjectName("muted")
        grid.addWidget(hdr, 0, 1)
        self.role_cb, self.weight = {}, {}
        for i, role in enumerate(ROLES, start=1):
            cb = QCheckBox(ROLE_LABELS[role])
            sp = QSpinBox()
            sp.setRange(0, 1_000_000)
            cb.toggled.connect(sp.setEnabled)
            self.role_cb[role], self.weight[role] = cb, sp
            grid.addWidget(cb, i, 0)
            grid.addWidget(sp, i, 1)
        root.addLayout(grid)

        r = QHBoxLayout()
        r.addWidget(QLabel("Fire when points reach"))
        self.threshold = QSpinBox()
        self.threshold.setRange(1, 100_000_000)
        r.addWidget(self.threshold)
        r.addStretch()
        root.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(QLabel("Cooldown after firing"))
        self.cooldown = QDoubleSpinBox()
        self.cooldown.setRange(0, 3600)
        self.cooldown.setDecimals(1)
        self.cooldown.setSuffix(" s")
        r.addWidget(self.cooldown)
        r.addStretch()
        root.addLayout(r)
        self.unique = QCheckBox("Each viewer counts only once per round (stops one person spamming)")
        root.addWidget(self.unique)
        pr = QHBoxLayout()
        self.progress = QCheckBox("Show progress bar above the chat / overlay / OBS")
        pr.addWidget(self.progress)
        pr.addStretch()
        pr.addWidget(QLabel("Bar colour"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(46, 24)
        self.color_btn.setToolTip("Colour of this trigger's progress bar and its glow")
        self.color_btn.clicked.connect(self._pick_color)
        pr.addWidget(self.color_btn)
        root.addLayout(pr)
        self.show_key = QCheckBox("Show the key on the bar  (off: only the trigger word, e.g. \"shot\")")
        self.show_key.setToolTip("On: shot  →  MouseLeft    3 / 10\nOff: shot    3 / 10")
        self.progress.toggled.connect(self.show_key.setEnabled)
        root.addWidget(self.show_key)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addSpacing(6)
        root.addLayout(btns)

    def _load(self, b: Binding):
        if b.group not in self._groups:
            self.group.addItem(b.group)
        self.group.setCurrentText(b.group)
        self.word.setText(b.word)
        i = self.match.findData(b.match)
        self.match.setCurrentIndex(max(0, i))
        self.key.setText(b.key)
        self.hold.setValue(b.hold_ms)
        self.repeat.setValue(b.repeat)
        for role in ROLES:
            self.role_cb[role].setChecked(role in b.allowed_roles)
            self.weight[role].setValue(int(b.weights.get(role, DEFAULT_WEIGHTS[role])))
            self.weight[role].setEnabled(role in b.allowed_roles)
        self.threshold.setValue(b.threshold)
        self.cooldown.setValue(b.cooldown)
        self.unique.setChecked(b.unique_users)
        self.progress.setChecked(b.show_progress)
        self.show_key.setChecked(b.show_key)
        self.show_key.setEnabled(b.show_progress)
        self._enabled = b.enabled
        self._set_color(b.color)

    def _set_color(self, c: str):
        self._color = c
        self.color_btn.setStyleSheet(f"background:{c}; border:1px solid #3a4158; border-radius:6px;")

    def _pick_color(self):
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self._color), self, T("Progress bar colour"))
        if c.isValid():
            self._set_color(c.name())

    def _record(self):
        d = KeyCaptureDialog(self)
        d.captured.connect(self.key.setText)
        d.exec()

    def _validate_key(self) -> bool:
        try:
            if self.key.text().strip():
                parse_key(self.key.text())
            self.key_err.setText("")
            return True
        except ValueError as e:
            self.key_err.setText(f"⚠  {e}")
            return False

    def _test(self):
        if not self.key.text().strip() or not self._validate_key():
            return
        self._count = 3
        self.test_btn.setEnabled(False)

        def tick():
            if self._count == 0:
                self.sender_.press(self.key.text().strip(), self.hold.value(), self.repeat.value())
                self.test_btn.setText(T("▶  Test in 3 s"))
                self.test_btn.setEnabled(True)
                return
            self.test_btn.setText(T("Pressing in {n}…").format(n=self._count))
            self._count -= 1
            QTimer.singleShot(1000, tick)
        tick()

    def _accept(self):
        if not self.word.text().strip():
            self.word.setFocus()
            self.word.setStyleSheet("border-color:#ef4444;")
            return
        if not self.key.text().strip() or not self._validate_key():
            self.key.setFocus()
            self.key.setStyleSheet("border-color:#ef4444;")
            return
        if not any(cb.isChecked() for cb in self.role_cb.values()):
            self.key_err.setText(T("⚠  Allow at least one role"))
            return
        self.accept()

    def binding(self) -> Binding:
        return Binding(
            word=self.word.text().strip(), key=self.key.text().strip(),
            allowed_roles={r for r, cb in self.role_cb.items() if cb.isChecked()},
            threshold=self.threshold.value(),
            weights={r: sp.value() for r, sp in self.weight.items()},
            match=self.match.currentData(), cooldown=self.cooldown.value(),
            unique_users=self.unique.isChecked(), hold_ms=self.hold.value(),
            repeat=self.repeat.value(), enabled=getattr(self, "_enabled", True),
            show_progress=self.progress.isChecked(),
            show_key=self.show_key.isChecked(),
            group=self.group.currentText().strip() or "General",
            color=getattr(self, "_color", "#7c5cff"),
        )
