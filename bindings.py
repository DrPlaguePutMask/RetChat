"""Chat-word → key bindings with role-weighted point thresholds."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Set

ROLES = ("moderator", "subscription", "vip", "regular")
ROLE_LABELS = {"moderator": "Moderator", "subscription": "Subscriber",
               "vip": "VIP", "regular": "Regular"}
DEFAULT_WEIGHTS = {"moderator": 100, "subscription": 75, "vip": 50, "regular": 25}

MATCH_MODES = {
    "exact":    "Whole message equals the word",
    "word":     "Message contains the word",
    "contains": "Message contains the text anywhere",
    "starts":   "Message starts with the word",
}

_ARABIC_TO_PERSIAN = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})


def normalize(s: str) -> str:
    """Case-fold and unify Persian/Arabic letter variants, digits and spacing."""
    s = unicodedata.normalize("NFKC", s or "").translate(_ARABIC_TO_PERSIAN)
    s = re.sub(r"[ً-ٰٟـ‌‍‎‏]", "", s)  # harakat, tatweel, ZWNJ…
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return s


@dataclass
class Binding:
    word: str
    key: str
    allowed_roles: Set[str] = field(default_factory=lambda: set(ROLES))
    threshold: int = 1
    weights: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    match: str = "exact"
    cooldown: float = 0.0          # seconds after firing during which nothing counts
    unique_users: bool = False     # each user counts once per cycle
    hold_ms: int = 80
    repeat: int = 1
    enabled: bool = True
    show_progress: bool = True     # progress bar above the chat
    color: str = "#7c5cff"         # progress bar / glow colour
    show_key: bool = True          # show "→ key" on the progress bar
    group: str = "General"         # e.g. "CS GO", "Valorant"

    # runtime state (not saved)
    acc: int = field(default=0, init=False, repr=False)
    last_fire: float = field(default=0.0, init=False, repr=False)
    fired_count: int = field(default=0, init=False, repr=False)
    _users: Set[str] = field(default_factory=set, init=False, repr=False)

    def reset(self):
        self.acc = 0
        self._users.clear()

    def matches(self, norm_text: str) -> bool:
        w = normalize(self.word)
        if not w or not norm_text:
            return False
        if self.match == "exact":
            return norm_text == w
        if self.match == "contains":
            return w in norm_text
        if self.match == "starts":
            return norm_text == w or norm_text.startswith(w + " ")
        # "word": whole-word match (works for Persian too – \b is unreliable there)
        return re.search(r"(?:^|[\s\W])" + re.escape(w) + r"(?:$|[\s\W])", norm_text) is not None

    def bar_label(self) -> str:
        """Text on the progress bar, e.g. 'shot  →  MouseLeft    3 / 10' (key optional)."""
        cd = self.cooling()
        name = f"{self.word}  →  {self.key}" if self.show_key else self.word
        from i18n import T
        return f"{name}    " + (T("cooldown {s}s").format(s=f"{cd:.0f}") if cd else f"{self.acc} / {self.threshold}")

    def cooling(self) -> float:
        left = self.cooldown - (time.time() - self.last_fire)
        return left if self.cooldown > 0 and self.last_fire and left > 0 else 0.0

    def to_dict(self) -> dict:
        return {"word": self.word, "key": self.key, "allowed_roles": sorted(self.allowed_roles),
                "threshold": self.threshold, "weights": dict(self.weights), "match": self.match,
                "cooldown": self.cooldown, "unique_users": self.unique_users, "hold_ms": self.hold_ms,
                "repeat": self.repeat, "enabled": self.enabled, "show_progress": self.show_progress,
                "show_key": self.show_key, "group": self.group,
                "color": self.color}

    @staticmethod
    def from_dict(d: dict) -> "Binding":
        return Binding(
            word=d.get("word", ""), key=d.get("key", ""),
            allowed_roles=set(d.get("allowed_roles", ROLES)),
            threshold=max(1, int(d.get("threshold", 1))),
            weights={**DEFAULT_WEIGHTS, **(d.get("weights") or {})},
            match=d.get("match", "exact"), cooldown=float(d.get("cooldown", 0)),
            unique_users=bool(d.get("unique_users", False)), hold_ms=int(d.get("hold_ms", 80)),
            repeat=int(d.get("repeat", 1)), enabled=bool(d.get("enabled", True)),
            show_progress=bool(d.get("show_progress", True)),
            color=d.get("color") or "#7c5cff",
            show_key=bool(d.get("show_key", True)),
            group=(d.get("group") or "General").strip() or "General",
        )


DEFAULT_BOTS = ("RestreamBot, Nightbot, StreamElements, Streamlabs, Moobot, Fossabot, Wizebot, "
                "BotRix, BotRixOficial, KickBot, Sery_Bot, CommanderRoot, SoundAlerts, "
                "PokemonCommunityGame, StreamlootsBot, Kofistreambot, Blerp, LumiaStream, "
                "MixItUpBot, Own3d, SongListBot, DeepBot, PhantomBot, Supibot")


def bot_names(text: str) -> Set[str]:
    return {n.strip().lower() for n in re.split(r"[,\s]+", text or "") if n.strip()}


def is_bot(msg: dict, names: Set[str], suffix_rule: bool = True) -> bool:
    """Bot if the platform says so, the name is in *names*, or it ends with 'bot'."""
    if msg.get("bot"):
        return True
    u = (msg.get("username") or "").strip().lower()
    if not u:
        return False
    return u in names or (suffix_rule and len(u) >= 7 and u.endswith("bot"))


class BindingManager:
    def __init__(self):
        self.bindings: List[Binding] = []
        self.count_bots = False                # bot messages normally never count
        # group name → {"active": bool, "collapsed": bool}; dict order = display order
        self.groups: Dict[str, dict] = {}

    def ensure_groups(self):
        """Every trigger's group exists; there is always at least one group."""
        for b in self.bindings:
            self.groups.setdefault(b.group, {"active": True, "collapsed": False})
        if not self.groups:
            self.groups["General"] = {"active": True, "collapsed": False}

    def group_active(self, name: str) -> bool:
        return bool(self.groups.get(name, {}).get("active", True))

    def is_active(self, b: Binding) -> bool:
        """A trigger works only when it is enabled AND its group is active."""
        return b.enabled and self.group_active(b.group)

    def process(self, msg: dict) -> List[Binding]:
        """Add points for *msg*; return bindings whose threshold was reached."""
        if msg.get("history"):
            return []                              # never fire on old chat backlog
        if msg.get("bot") and not self.count_bots:
            return []                              # e.g. RestreamBot relaying the same message
        text = normalize(msg.get("text", ""))
        if not text:
            return []
        roles = msg.get("role") or ["regular"]
        if isinstance(roles, str):
            roles = [roles]
        user = f"{msg.get('platform')}:{(msg.get('username') or '').lower()}"
        fired = []
        for b in self.bindings:
            if not self.is_active(b) or not b.matches(text) or b.cooling():
                continue
            valid = [r for r in roles if r in b.allowed_roles]
            if not valid:
                continue
            if b.unique_users:
                if user in b._users:
                    continue
                b._users.add(user)
            b.acc += max(int(b.weights.get(r, 1)) for r in valid)
            msg["_trigger"] = True
            msg.setdefault("_trigger_color", b.color)
            if b.acc >= b.threshold:
                b.reset()
                b.last_fire = time.time()
                b.fired_count += 1
                fired.append(b)
        return fired
