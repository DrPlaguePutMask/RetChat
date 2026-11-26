"""Send keyboard / mouse input that games actually receive.

Why the old version failed
--------------------------
The ``keyboard`` package sends *virtual-key* events through ``keybd_event``.
Most games read input through DirectInput / Raw Input, which only look at
hardware **scan codes**, so those presses were silently ignored.  Presses were
also only 50 ms long, which a game running its input poll once per frame can
miss, and nothing reported when Windows blocked the input.

This module uses ``SendInput`` with ``KEYEVENTF_SCANCODE`` (plus the extended
flag for arrows, Insert/Delete, right Ctrl/Alt, …), holds keys for a
configurable time, and runs every press on one worker thread so overlapping
triggers never interleave.

Key strings look like ``"Ctrl+Shift+A"``, ``"F9"``, ``"Num5"``, ``"Space"``,
``"MouseLeft"``, ``"Alt+MouseX1"``.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"

# ── Virtual-key table ──────────────────────────────────────────────────────────
VK = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D, "pause": 0x13,
    "capslock": 0x14, "esc": 0x1B, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E,
    "lwin": 0x5B, "rwin": 0x5C, "apps": 0x5D,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "num*": 0x6A, "num+": 0x6B, "num-": 0x6D, "num.": 0x6E, "num/": 0x6F,
    "numlock": 0x90, "scrolllock": 0x91,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3, "lalt": 0xA4, "ralt": 0xA5,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for _i in range(1, 25):
    VK[f"f{_i}"] = 0x6F + _i
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK[_c.lower()] = ord(_c)

ALIASES = {
    "control": "ctrl", "ctl": "ctrl", "menu": "alt", "option": "alt",
    "win": "lwin", "meta": "lwin", "super": "lwin", "windows": "lwin",
    "del": "delete", "ins": "insert", "pgup": "pageup", "pgdn": "pagedown",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "spacebar": "space", "bksp": "backspace", "caps": "capslock",
    "+": "=", "minus": "-", "plus": "=", "equal": "=", "comma": ",", "period": ".", "slash": "/",
    "semicolon": ";", "quote": "'", "backslash": "\\", "grave": "`", "tilde": "`",
    "numpad0": "num0", "numpad1": "num1", "numpad2": "num2", "numpad3": "num3",
    "numpad4": "num4", "numpad5": "num5", "numpad6": "num6", "numpad7": "num7",
    "numpad8": "num8", "numpad9": "num9", "numenter": "enter",
}

MODIFIERS = {"ctrl", "shift", "alt", "lwin", "rwin", "lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt"}

# keys that need KEYEVENTF_EXTENDEDKEY with scan codes
EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
            0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5}

MOUSE_BUTTONS = {
    "mouseleft": "left", "mouseright": "right", "mousemiddle": "middle",
    "mousex1": "x1", "mousex2": "x2", "mousewheelup": "wheelup", "mousewheeldown": "wheeldown",
}

# Pretty names for VK codes (used by the key-capture dialog)
VK_NAMES = {}
for _name, _code in VK.items():
    VK_NAMES.setdefault(_code, _name)
_PRETTY = {"num*": "Num*", "num+": "Num+", "num-": "Num-", "num.": "Num.", "num/": "Num/"}


def pretty_key(name: str) -> str:
    if name in _PRETTY:
        return _PRETTY[name]
    if name.startswith("num") and name[3:].isdigit():
        return "Num" + name[3:]
    if len(name) == 1:
        return name.upper()
    if name.startswith("f") and name[1:].isdigit():
        return name.upper()
    return name[:1].upper() + name[1:]


# ── Parsing ────────────────────────────────────────────────────────────────────
class KeySpec:
    def __init__(self, mods: List[int], key_vk: Optional[int], mouse: Optional[str]):
        self.mods, self.key_vk, self.mouse = mods, key_vk, mouse

    def __repr__(self):
        return f"KeySpec(mods={self.mods}, vk={self.key_vk}, mouse={self.mouse})"


def parse_key(raw: str) -> KeySpec:
    """Parse ``"Ctrl+Shift+A"`` → :class:`KeySpec`.  Raises ValueError."""
    s = (raw or "").strip().strip("<>")
    if not s:
        raise ValueError("empty key")
    # split on '+' but allow the '+' key itself ("Ctrl++", "Num+")
    tokens, cur = [], ""
    for ch in s:
        if ch == "+" and cur and not cur.lower().endswith("num"):
            tokens.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        tokens.append(cur)
    mods, key_vk, mouse = [], None, None
    for idx, t in enumerate(tokens):
        n = t.strip().lower().replace(" ", "").replace("_", "")
        n = ALIASES.get(n, n)
        if n in MOUSE_BUTTONS:
            mouse = MOUSE_BUTTONS[n]
        elif n in MODIFIERS and idx < len(tokens) - 1:
            mods.append(VK[n])
        elif n in VK:
            key_vk = VK[n]
        elif n.startswith("key") and n[3:].isdigit():          # e.g. "Key_123"
            key_vk = int(n[3:])
        else:
            raise ValueError(f"unknown key '{t}'")
    if key_vk is None and mouse is None:
        if mods:                     # a lone modifier, e.g. "Shift"
            key_vk = mods.pop()
        else:
            raise ValueError("no key given")
    return KeySpec(mods, key_vk, mouse)


# ── Win32 SendInput structures ────────────────────────────────────────────────
if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x1, 0x2, 0x8
_MOUSE_FLAGS = {
    "left": (0x0002, 0x0004, 0), "right": (0x0008, 0x0010, 0), "middle": (0x0020, 0x0040, 0),
    "x1": (0x0080, 0x0100, 1), "x2": (0x0080, 0x0100, 2),
}
MOUSEEVENTF_WHEEL = 0x0800


def _key_input(vk: int, up: bool, use_scancode: bool) -> "INPUT":
    inp = INPUT(type=INPUT_KEYBOARD)
    flags = KEYEVENTF_KEYUP if up else 0
    if use_scancode:
        scan = user32.MapVirtualKeyW(vk, 0) & 0xFF        # MAPVK_VK_TO_VSC
        if vk in (0x13,):                                  # Pause has no scancode mapping
            inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
            return inp
        flags |= KEYEVENTF_SCANCODE
        if vk in EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        inp.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    else:
        if vk in EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return inp


def _mouse_input(button: str, up: bool) -> "INPUT":
    inp = INPUT(type=INPUT_MOUSE)
    if button in ("wheelup", "wheeldown"):
        delta = 120 if button == "wheelup" else -120
        inp.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(delta).value, MOUSEEVENTF_WHEEL, 0, 0)
        return inp
    down_f, up_f, data = _MOUSE_FLAGS[button]
    inp.mi = MOUSEINPUT(0, 0, data, up_f if up else down_f, 0, 0)
    return inp


def _send(inputs: List["INPUT"]) -> Tuple[bool, int]:
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    return n == len(inputs), (ctypes.get_last_error() if n != len(inputs) else 0)


# ── Elevation helpers ──────────────────────────────────────────────────────────
def is_admin() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def foreground_is_elevated() -> Optional[bool]:
    """True if the focused window belongs to an elevated (admin) process.

    Windows UIPI silently drops SendInput aimed at elevated windows when we are
    not elevated ourselves – that is the #1 reason presses "do nothing".
    """
    if not IS_WINDOWS:
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)       # QUERY_LIMITED_INFORMATION
        if not h:
            return True                                      # access denied ⇒ almost surely elevated
        try:
            tok = wintypes.HANDLE()
            if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):
                return True
            try:
                elev = wintypes.DWORD()
                ret = wintypes.DWORD()
                adv.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(ret))
                return bool(elev.value)
            finally:
                k32.CloseHandle(tok)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def foreground_title() -> str:
    if not IS_WINDOWS:
        return ""
    try:
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def relaunch_as_admin() -> bool:
    """Restart the app elevated (UAC prompt). Returns True if launched."""
    if not IS_WINDOWS:
        return False
    import subprocess
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe, params = sys.executable, subprocess.list2cmdline(sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


# ── Sender ─────────────────────────────────────────────────────────────────────
class InputSender:
    """Queues presses and performs them on one background thread.

    ``on_result(key_str, ok, message)`` is called from the worker thread.
    """

    def __init__(self, on_result: Optional[Callable[[str, bool, str], None]] = None):
        self.on_result = on_result
        self.hold_ms = 80
        self.use_scancode = True
        self._q: "queue.Queue[tuple]" = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="InputSender").start()

    def press(self, key: str, hold_ms: Optional[int] = None, repeat: int = 1):
        self._q.put((key, self.hold_ms if hold_ms is None else hold_ms, max(1, repeat)))

    def _worker(self):
        while True:
            key, hold, repeat = self._q.get()
            try:
                ok, msg = True, ""
                for i in range(repeat):
                    ok, msg = self._do(key, hold)
                    if not ok:
                        break
                    if i + 1 < repeat:
                        time.sleep(0.05)
            except Exception as exc:
                ok, msg = False, str(exc)
            if self.on_result:
                try:
                    self.on_result(key, ok, msg)
                except Exception:
                    pass

    def _do(self, key: str, hold_ms: int) -> Tuple[bool, str]:
        if not IS_WINDOWS:
            return False, "Key sending is only supported on Windows"
        spec = parse_key(key)
        hold = max(10, hold_ms) / 1000.0
        down: List[INPUT] = [_key_input(m, False, self.use_scancode) for m in spec.mods]
        up: List[INPUT] = []
        if spec.mouse:
            if spec.mouse.startswith("wheel"):
                down.append(_mouse_input(spec.mouse, False))
            else:
                down.append(_mouse_input(spec.mouse, False))
                up.append(_mouse_input(spec.mouse, True))
        else:
            down.append(_key_input(spec.key_vk, False, self.use_scancode))
            up.append(_key_input(spec.key_vk, True, self.use_scancode))
        up += [_key_input(m, True, self.use_scancode) for m in reversed(spec.mods)]

        # modifiers first, small gap so games register them before the key
        if spec.mods:
            ok, err = _send(down[:len(spec.mods)])
            if not ok:
                return False, self._explain(err)
            time.sleep(0.02)
            rest = down[len(spec.mods):]
        else:
            rest = down
        ok, err = _send(rest)
        if not ok:
            if up:
                _send(up)
            return False, self._explain(err)
        time.sleep(hold)
        if up:
            ok, err = _send(up)
            if not ok:
                return False, self._explain(err)
        # UIPI drops input to elevated windows *without* reporting an error
        if foreground_is_elevated() and not is_admin():
            return False, ("Sent, but the focused app runs as administrator so Windows "
                           "probably blocked it. Restart RetChat as administrator.")
        return True, ""

    @staticmethod
    def _explain(err: int) -> str:
        if err == 5 or (foreground_is_elevated() and not is_admin()):
            return ("Blocked by Windows: the focused app runs as administrator. "
                    "Restart RetChat as administrator.")
        return f"SendInput failed (error {err})"
