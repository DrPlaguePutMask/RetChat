"""Find the font file behind a font family name (for the OBS page).

Browsers only know a font's base family name, so many fonts that Windows / Qt
list separately ("Rage Italic", "Bahnschrift SemiBold Condensed", "Segoe UI
Semilight" …) silently fall back to a default font in OBS.  RetChat therefore
looks up the actual file and serves it to the OBS page with @font-face, which
also makes the font work when OBS runs on another PC that doesn't have it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_INDEX: Dict[str, List[Tuple[str, str, int]]] = {}    # family (lower) → [(style, path, ttc index)]
_READY = threading.Event()
_LOCK = threading.Lock()

FONT_EXT = (".ttf", ".otf", ".ttc")
MIME = {".ttf": "font/ttf", ".otf": "font/otf", ".ttc": "font/collection"}


def _font_dirs() -> List[Path]:
    dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")   # fonts installed for this user only
    return [d for d in dirs if d.is_dir()]


def build_index() -> None:
    """Read the family/style name of every installed font file (runs once, ~1–3 s)."""
    if _READY.is_set():
        return
    with _LOCK:
        if _READY.is_set():
            return
        try:
            from PIL import ImageFont
        except ImportError:
            _READY.set()
            return
        for d in _font_dirs():
            for f in d.iterdir():
                if f.suffix.lower() not in FONT_EXT:
                    continue
                for idx in range(8 if f.suffix.lower() == ".ttc" else 1):
                    try:
                        fam, style = ImageFont.truetype(str(f), 12, index=idx).getname()
                    except Exception:
                        break
                    if fam:
                        _INDEX.setdefault(fam.strip().lower(), []).append((style or "Regular", str(f), idx))
        _READY.set()


def ready() -> bool:
    return _READY.is_set()


def resolve(family: str) -> List[Tuple[str, int, str]]:
    """Files for *family* as [(path, css weight, css style)], regular first. Empty if unknown."""
    if not family or not _READY.is_set():
        return []
    name = family.strip().lower()
    entries = _INDEX.get(name)
    wanted = ""                                       # style words Windows put in the name, e.g. "semilight"
    if not entries:                                   # "Segoe UI Semilight" → family "Segoe UI", style "Semilight"
        words = name.split()
        dropped: List[str] = []
        while len(words) > 1 and not entries:
            dropped.insert(0, words.pop())
            entries = _INDEX.get(" ".join(words))
        wanted = " ".join(dropped)
    if not entries:                                   # short family name: "Rage" → "Rage Italic",
        words = name.split()                          # "Eras ITC" → "Eras Medium ITC"
        cands = [k for k in _INDEX if all(w in k.split() for w in words)]
        if cands:
            def rank(k):
                extra = set(k.split()) - set(words)
                regularish = bool(extra & {"regular", "book", "medium", "roman", "normal"})
                return (not regularish, len(extra), k)
            entries = _INDEX[min(cands, key=rank)]
            wanted = ""
    if not entries:
        return []
    if wanted:                                        # use the face whose style matches the dropped words
        match = [e for e in entries if e[0].lower().replace(" ", "") == wanted.replace(" ", "")]
        if match:
            return [(match[0][1], 400, "normal")]     # shown as the normal weight, like in the app
    out = []
    for style, path, idx in entries:
        s = style.lower()
        if idx:                                       # browsers only read the first font of a collection
            continue
        weight = 700 if ("bold" in s or "black" in s or "heavy" in s) else 400
        css_style = "italic" if ("italic" in s or "oblique" in s) else "normal"
        if any(w in s for w in ("light", "thin", "semibold", "medium", "condensed", "narrow", "black", "heavy")) \
                and s not in ("bold", "bold italic"):
            continue                                  # keep only regular / bold / italic faces of the family
        out.append((path, weight, css_style))
    # regular upright first, then the rest; at most four faces
    out.sort(key=lambda e: (e[1] != 400, e[2] != "normal"))
    seen, uniq = set(), []
    for e in out:
        if (e[1], e[2]) not in seen:
            seen.add((e[1], e[2]))
            uniq.append(e)
    return uniq[:4]
