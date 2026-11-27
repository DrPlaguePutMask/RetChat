"""Block keyboard / mouse input for a few seconds (trigger actions).

Uses Windows low-level hooks (WH_KEYBOARD_LL / WH_MOUSE_LL) that swallow the
user's real input.  The hooks are only installed while something is blocked
and removed as soon as every block has run out, so normal play is never
slowed down.  Input that RetChat itself sends (trigger key presses) is let
through.

Safety:
* every block ends by itself (at most MAX_SECONDS);
* pressing Esc 5 times quickly ends all blocks at once;
* Ctrl+Alt+Del always works (Windows never passes it to hooks).

Like key presses, Windows doesn't let a normal program block input to a game
that runs as administrator – run RetChat as administrator then.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Dict, Optional, Set

from input_sender import parse_key

IS_WINDOWS = sys.platform == "win32"
MAX_SECONDS = 600.0
ESC_TAPS, ESC_WINDOW = 5, 2.0

# generic modifier → the left/right codes a hook actually sees
_SIDES = {0x10: (0x10, 0xA0, 0xA1), 0x11: (0x11, 0xA2, 0xA3), 0x12: (0x12, 0xA4, 0xA5),
          0x5B: (0x5B, 0x5C)}

WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEHWHEEL = 0x020A, 0x020B, 0x020C, 0x020E
WM_TIMER, WM_QUIT = 0x0113, 0x0012
LLKHF_INJECTED, LLMHF_INJECTED = 0x10, 0x01

_BTN_DOWN = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right", WM_MBUTTONDOWN: "middle"}
_BTN_UP = {WM_LBUTTONUP: "left", WM_RBUTTONUP: "right", WM_MBUTTONUP: "middle"}

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
    user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
    user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
    user32.SetTimer.restype = ctypes.c_size_t
    user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def split_keys(text: str):
    """"W, A, S, D" → ["W", "A", "S", "D"] (a lone "," key is not supported here)."""
    return [k.strip() for k in (text or "").split(",") if k.strip()]


class InputBlocker:
    """``block_keys("W", 5)``, ``block_keyboard(10)``, ``block_mouse(3)``, ``unblock_all()``.

    ``on_change(text)`` is called (from the hook thread) when blocking starts or ends.
    """

    def __init__(self, on_change: Optional[Callable[[str], None]] = None):
        self.on_change = on_change
        self._lock = threading.Lock()
        self._keys: Dict[int, float] = {}          # vk → until
        self._buttons: Dict[str, float] = {}       # "left"/"right"/"middle"/"x1"/"x2"/"wheel…" → until
        self._kb_until = 0.0
        self._mouse_until = 0.0
        self._swallowed: Set[int] = set()          # keys whose key-down we ate (eat their key-up too)
        self._swallowed_btn: Set[str] = set()
        self._esc: list = []
        self._thread: Optional[threading.Thread] = None
        self._tid = 0
        self._procs = None                         # keep ctypes callbacks alive

    # ── public ────────────────────────────────────────────────────────────────
    def block_keys(self, keys: str, seconds: float) -> None:
        """Block keys / mouse buttons, comma separated: "W", "W, A, S, D", "Space", "MouseLeft".
        In a combo like "Ctrl+A" only the main key (A) is blocked."""
        specs = [parse_key(k) for k in split_keys(keys)]
        until = time.time() + self._clamp(seconds)
        with self._lock:
            for spec in specs:
                if spec.key_vk:
                    for v in _SIDES.get(spec.key_vk, (spec.key_vk,)):
                        self._keys[v] = max(self._keys.get(v, 0), until)
                if spec.mouse:
                    name = spec.mouse if not spec.mouse.startswith("wheel") else "wheel"
                    self._buttons[name] = max(self._buttons.get(name, 0), until)
        self._ensure()

    def block_keyboard(self, seconds: float) -> None:
        with self._lock:
            self._kb_until = max(self._kb_until, time.time() + self._clamp(seconds))
        self._ensure()

    def block_mouse(self, seconds: float) -> None:
        with self._lock:
            self._mouse_until = max(self._mouse_until, time.time() + self._clamp(seconds))
        self._ensure()

    def unblock_all(self) -> None:
        with self._lock:
            self._keys.clear()
            self._buttons.clear()
            self._kb_until = self._mouse_until = 0.0

    def active(self) -> bool:
        now = time.time()
        with self._lock:
            return (self._kb_until > now or self._mouse_until > now
                    or any(t > now for t in self._keys.values()) or any(t > now for t in self._buttons.values()))

    def describe(self) -> str:
        now = time.time()
        out = []
        with self._lock:
            if self._kb_until > now:
                out.append(f"keyboard {self._kb_until - now:.0f}s")
            if self._mouse_until > now:
                out.append(f"mouse {self._mouse_until - now:.0f}s")
            n = sum(1 for t in list(self._keys.values()) + list(self._buttons.values()) if t > now)
            if n:
                out.append(f"{n} key(s)")
        return ", ".join(out)

    # ── internals ─────────────────────────────────────────────────────────────
    @staticmethod
    def _clamp(seconds: float) -> float:
        return max(0.2, min(MAX_SECONDS, float(seconds or 0)))

    def _ensure(self):
        if not IS_WINDOWS:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, daemon=True, name="InputBlocker")
            self._thread.start()

    def _notify(self, text: str):
        if self.on_change:
            try:
                self.on_change(text)
            except Exception:
                pass

    def _esc_tap(self) -> bool:
        """Esc pressed 5 times within 2 s → emergency unblock."""
        now = time.time()
        self._esc = [t for t in self._esc if now - t < ESC_WINDOW] + [now]
        if len(self._esc) >= ESC_TAPS:
            self._esc.clear()
            self.unblock_all()
            return True
        return False

    def _kb_proc(self, code, wparam, lparam):
        if code == 0:
            k = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (k.flags & LLKHF_INJECTED):
                vk = k.vkCode
                down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if down and vk == 0x1B and self._esc_tap():
                    self._notify("unblocked")
                elif down:
                    now = time.time()
                    if self._kb_until > now or self._keys.get(vk, 0) > now:
                        self._swallowed.add(vk)
                        return 1
                elif vk in self._swallowed:          # key-up of a key-down we ate
                    self._swallowed.discard(vk)
                    return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _ms_proc(self, code, wparam, lparam):
        if code == 0:
            m = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (m.flags & LLMHF_INJECTED):
                now = time.time()
                all_ = self._mouse_until > now
                if wparam == WM_MOUSEMOVE:
                    if all_:
                        return 1
                elif wparam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
                    if all_ or self._buttons.get("wheel", 0) > now:
                        return 1
                else:
                    if wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                        btn = "x1" if (m.mouseData >> 16) & 0xFFFF == 1 else "x2"
                        down = wparam == WM_XBUTTONDOWN
                    elif wparam in _BTN_DOWN:
                        btn, down = _BTN_DOWN[wparam], True
                    elif wparam in _BTN_UP:
                        btn, down = _BTN_UP[wparam], False
                    else:
                        btn, down = "", False
                    if btn:
                        if down and (all_ or self._buttons.get(btn, 0) > now):
                            self._swallowed_btn.add(btn)
                            return 1
                        if not down and btn in self._swallowed_btn:
                            self._swallowed_btn.discard(btn)
                            return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self):
        self._tid = kernel32.GetCurrentThreadId()
        kb, ms = HOOKPROC(self._kb_proc), HOOKPROC(self._ms_proc)
        self._procs = (kb, ms)
        hmod = kernel32.GetModuleHandleW(None)
        h_kb = user32.SetWindowsHookExW(13, kb, hmod, 0)     # WH_KEYBOARD_LL
        h_ms = user32.SetWindowsHookExW(14, ms, hmod, 0)     # WH_MOUSE_LL
        if not h_kb and not h_ms:
            self._notify("error")
            return
        self._notify("blocking")
        user32.SetTimer(None, 0, 100, None)                  # wake up to check for expiry
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_TIMER and not self.active():
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if h_kb:
                user32.UnhookWindowsHookEx(h_kb)
            if h_ms:
                user32.UnhookWindowsHookEx(h_ms)
            self._swallowed.clear()
            self._swallowed_btn.clear()
            with self._lock:
                self._thread = None
            self._notify("ended")
            if self.active():                                # a new block arrived while closing
                self._ensure()
