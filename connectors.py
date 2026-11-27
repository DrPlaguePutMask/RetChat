"""Native live-chat connectors for Twitch, Kick, YouTube, Aparat and OneFa.

Every connector talks to the platform's own realtime API (no browser needed)
and produces *normalised* message dicts:

    {
      "platform": "twitch",            # twitch | kick | youtube | aparat | onefa
      "channel":  "hasanabi",
      "source":   "twitch:hasanabi",   # unique per connection
      "id":       "...",
      "username": "Display Name",
      "color":    "#8A2BE2" | None,
      "text":     "plain text (emotes as their names)",
      "parts":    [{"type": "text", "text": ...},
                   {"type": "emote", "url": ..., "name": ...}],
      "badges":   [{"url": ... | None, "icon": "moderator" | None, "title": ...}],
      "role":     ["moderator", "subscription", "vip", "regular"],
      "reply":    {"user": ..., "text": ...} | None,
      "history":  True when the message existed before we connected,
      "ts":       unix time,
    }

All connectors run as asyncio tasks inside one background thread
(:class:`ChatHub`) and reconnect automatically.

Run ``python connectors.py <url>`` to print a channel's chat in the terminal.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

PLATFORMS = ("twitch", "kick", "youtube", "aparat", "onefa")

PLATFORM_NAMES = {
    "twitch": "Twitch", "kick": "Kick", "youtube": "YouTube",
    "aparat": "Aparat", "onefa": "OneFa",
}


# ══════════════════════════════════════════════════════════════════════════════
# Target parsing
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Target:
    platform: str
    channel: str          # slug / login / video id / @handle

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel.lower()}"

    def label(self) -> str:
        return f"{PLATFORM_NAMES.get(self.platform, self.platform)} · {self.channel}"

    def to_str(self) -> str:
        return f"{self.platform}:{self.channel}"


def parse_target(raw: str) -> Optional[Target]:
    """Turn a URL or ``platform:name`` string into a :class:`Target`."""
    s = (raw or "").strip()
    if not s:
        return None

    m = re.match(r"^(twitch|kick|youtube|yt|aparat|onefa)\s*:\s*(\S+)$", s, re.I)
    if m:
        plat = m.group(1).lower()
        plat = "youtube" if plat == "yt" else plat
        return Target(plat, m.group(2).strip("/"))

    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    u = urlparse(s)
    host = (u.netloc or "").lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    segs = [p for p in u.path.split("/") if p]

    if host.endswith("twitch.tv"):
        if segs and segs[0] == "popout" and len(segs) > 1:
            segs = segs[1:]
        return Target("twitch", segs[0].lower()) if segs else None
    if host.endswith("kick.com"):
        if segs and segs[0] == "popout" and len(segs) > 1:
            segs = segs[1:]
        return Target("kick", segs[0].lower()) if segs else None
    if host == "youtu.be":
        return Target("youtube", segs[0]) if segs else None
    if host.endswith("youtube.com"):
        q = parse_qs(u.query)
        if "v" in q:
            return Target("youtube", q["v"][0])
        if len(segs) >= 2 and segs[0] in ("live", "shorts", "embed"):
            return Target("youtube", segs[1])
        if segs and segs[0].startswith("@"):
            return Target("youtube", segs[0])
        if len(segs) >= 2 and segs[0] in ("channel", "c", "user"):
            return Target("youtube", f"{segs[0]}/{segs[1]}")
        return None
    if host.endswith("aparat.com"):
        return Target("aparat", segs[0]) if segs else None
    if host.endswith("onefa.ir"):
        return Target("onefa", segs[0]) if segs else None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _roles(mod=False, sub=False, vip=False) -> List[str]:
    r = []
    if mod:
        r.append("moderator")
    if sub:
        r.append("subscription")
    if vip:
        r.append("vip")
    return r or ["regular"]


def _text_of(parts: List[dict]) -> str:
    out = []
    for p in parts:
        if p["type"] == "text":
            out.append(p["text"])
        elif p.get("name"):
            out.append(p["name"])
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def _split_tokens(text: str, emotes: Dict[str, str]) -> List[dict]:
    """Split *text* wherever one of the *emotes* codes appears (even mid-word)."""
    if not emotes:
        return [{"type": "text", "text": text}] if text else []
    pat = re.compile("|".join(re.escape(k) for k in sorted(emotes, key=len, reverse=True)))
    parts: List[dict] = []
    pos = 0
    for m in pat.finditer(text):
        if m.start() > pos:
            parts.append({"type": "text", "text": text[pos:m.start()]})
        parts.append({"type": "emote", "url": emotes[m.group(0)], "name": m.group(0)})
        pos = m.end()
    if pos < len(text) and text[pos:].strip():
        parts.append({"type": "text", "text": text[pos:]})
    return parts


class ConnectorError(Exception):
    """Fatal problem (channel not found etc.). Retried slowly."""


# ══════════════════════════════════════════════════════════════════════════════
# Network: proxy + DNS
# ══════════════════════════════════════════════════════════════════════════════
# Proxy "spec" strings stored per channel:
#   "" / "direct"           no proxy
#   "system"                Windows proxy settings (Internet Options / v2rayN "system proxy")
#   "socks5://host:port"    SOCKS5 (v2ray / xray default 127.0.0.1:10808)
#   "http://host:port"      HTTP proxy (v2ray default 127.0.0.1:10809)

def resolve_proxy(spec: Optional[str]) -> Optional[str]:
    """Turn a proxy spec into a proxy URL, or None for a direct connection."""
    spec = (spec or "").strip()
    if not spec or spec == "direct":
        return None
    if spec == "system":
        import urllib.request
        p = urllib.request.getproxies()          # reads the Windows registry
        url = p.get("https") or p.get("http") or p.get("socks") or p.get("all")
        if not url:
            return None
        spec = url
    if spec.startswith("socks://"):
        spec = "socks5://" + spec[len("socks://"):]
    if "://" not in spec:
        spec = "http://" + spec
    return spec


def proxy_label(spec: Optional[str]) -> str:
    if not spec or spec == "direct":
        return "direct"
    if spec == "system":
        url = resolve_proxy("system")
        return f"system proxy ({url.split('://')[-1]})" if url else "system proxy (none set → direct)"
    return spec


_SSL_CTX = None


def ssl_context():
    """HTTPS verification that behaves like the browser.

    ``truststore`` asks Windows itself to verify certificates, so sites work
    wherever Chrome/Edge work – including PCs whose antivirus (Kaspersky, ESET,
    Avast…) or network re-signs HTTPS traffic with its own trusted root.
    """
    global _SSL_CTX
    if _SSL_CTX is None:
        import ssl
        try:
            import truststore
            _SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            _SSL_CTX = ssl.create_default_context()
    return _SSL_CTX


def make_tcp_connector(spec: Optional[str]) -> aiohttp.BaseConnector:
    """aiohttp connector for *spec*.

    Always uses the OS resolver (ThreadedResolver): aiohttp picks c-ares
    (aiodns) when it is installed, and c-ares fails on many Windows networks /
    VPNs with "Could not contact DNS servers".  Through a proxy, host names are
    resolved by the proxy itself (rdns), which also avoids poisoned local DNS.
    """
    url = resolve_proxy(spec)
    if url:
        try:
            from aiohttp_socks import ProxyConnector
        except ImportError as exc:
            raise ConnectorError("Proxy support needs: pip install aiohttp-socks") from exc
        return ProxyConnector.from_url(url, rdns=True, resolver=aiohttp.ThreadedResolver(),
                                       ssl=ssl_context())
    return aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver(), ssl=ssl_context())


_WINERR = {
    10013: "Windows or an antivirus/firewall blocked RetChat (permission denied)",
    10050: "the network is down",
    10051: "the network is unreachable",
    10054: "the connection was reset by the network",
    10060: "the connection timed out",
    10061: "the server refused the connection",
    10065: "no route to the host",
    1225: "the connection was refused",
    11001: "host not found",
}


def _reason(exc: BaseException) -> str:
    """Windows' own reason for a socket failure, in plain words."""
    os_err = getattr(exc, "os_error", None) or exc.__cause__ or exc
    code = getattr(os_err, "winerror", None) or getattr(os_err, "errno", None)
    if code in _WINERR:
        return f"{_WINERR[code]} [error {code}]"
    msg = str(os_err) or type(os_err).__name__
    return msg.split("] ", 1)[-1][:120]


def friendly_error(exc: BaseException, spec: Optional[str]) -> str:
    """Short, actionable explanation for network failures (with the real cause)."""
    url = resolve_proxy(spec)
    name = type(exc).__name__
    text = str(exc)
    tip = "" if url else " If a browser on this PC opens the site, set Route to System proxy."
    if "Proxy" in name or ("proxy" in text.lower() and url):
        where = url.split("://")[-1] if url else "proxy"
        if "Timeout" in name:
            return f"Proxy {where} timed out – is v2ray / your VPN connected?"
        return f"Proxy {where} not reachable – is v2ray / your VPN running? ({_reason(exc)})"
    host = getattr(exc, "host", None) or ""
    port = getattr(exc, "port", None) or 443
    where = f"{host}:{port}" if host else "the site"
    if isinstance(exc, aiohttp.ClientConnectorCertificateError):
        ce = getattr(exc, "certificate_error", None) or exc
        why = ce.args[0] if ce.args and isinstance(ce.args[0], str) else str(ce)
        why = why.strip("()'\",. ")[:110]
        if "validity" in why.lower() or "expired" in why.lower():
            return (f"{where}: HTTPS certificate rejected as expired ({why}). "
                    "Check this PC's date and time are correct.")
        return (f"{where}: HTTPS certificate not trusted ({why}). Usually antivirus HTTPS "
                "scanning or a filtering network – turn off HTTPS/SSL scanning for RetChat or use a proxy.")
    if isinstance(exc, aiohttp.ClientConnectorDNSError) or "getaddrinfo" in text or "DNS" in text:
        return f"DNS lookup for {host or 'the site'} failed ({_reason(exc)}). Pick a proxy for this channel."
    if isinstance(exc, aiohttp.ClientSSLError):
        return (f"{where}: secure (TLS) handshake failed ({_reason(exc)}) – an antivirus or the "
                "network is interfering." + tip)
    if isinstance(exc, aiohttp.ClientConnectorError):
        code = getattr(getattr(exc, "os_error", None), "winerror", None)
        if code == 10013:
            return (f"Windows or your antivirus/firewall blocked RetChat from reaching {where}. "
                    "Allow RetChat in the firewall/antivirus.")
        return f"Can't connect to {where} – {_reason(exc)}." + tip
    if isinstance(exc, aiohttp.WSServerHandshakeError):
        return (f"Chat server refused the live connection (HTTP {exc.status}) – an antivirus, proxy "
                "or network is blocking WebSockets." + tip)
    if isinstance(exc, (asyncio.TimeoutError, aiohttp.ServerTimeoutError)):
        return "Connection timed out" + ("" if url else " – try a proxy")
    if isinstance(exc, aiohttp.ClientResponseError) and exc.status == 403:
        return "Access denied (403) – the site may block this IP; try a proxy"
    if isinstance(exc, aiohttp.ServerDisconnectedError):
        return "The server closed the connection – reconnecting"
    return f"{name}: {text}"[:200]


async def test_proxy(spec: Optional[str], url: str = "https://www.google.com/generate_204") -> tuple:
    """Returns (ok, message)."""
    t0 = time.time()
    try:
        async with aiohttp.ClientSession(connector=make_tcp_connector(spec),
                                         timeout=aiohttp.ClientTimeout(total=12),
                                         headers={"User-Agent": UA}) as s:
            async with s.get(url) as r:
                await r.read()
                return True, f"OK – HTTP {r.status} in {int((time.time() - t0) * 1000)} ms via {proxy_label(spec)}"
    except Exception as exc:
        return False, friendly_error(exc, spec)


# ══════════════════════════════════════════════════════════════════════════════
# Base connector
# ══════════════════════════════════════════════════════════════════════════════

class BaseConnector:
    platform = "base"

    def __init__(self, target: Target, emit: Callable[[dict], None],
                 status: Callable[[str, str, str], None], proxy: Optional[str] = None):
        self.target = target
        self.proxy = proxy
        self._emit = emit
        self._status = status
        self.session: Optional[aiohttp.ClientSession] = None
        self._stop = False
        self._av_cache: Dict[str, str] = {}          # user_key → avatar url ("" = none)
        self._av_wanted: Dict[str, str] = {}         # user_key → lookup id, waiting for a lookup

    AV_BATCH = 30

    # -- avatars (platforms that don't send them with each message) -------------
    def avatar_for(self, user_key: str, lookup_id: str) -> Optional[str]:
        """Cached avatar, or None while a background lookup is queued."""
        if user_key in self._av_cache:
            return self._av_cache[user_key] or None
        if len(self._av_cache) < 20000:
            self._av_wanted.setdefault(user_key, lookup_id)
        return None

    async def lookup_avatars(self, ids: List[str]) -> Dict[str, str]:
        return {}

    async def _avatar_worker(self):
        while not self._stop:
            await asyncio.sleep(0.7)
            if not self._av_wanted or self.session is None or self.session.closed:
                continue
            batch = list(self._av_wanted.items())[:self.AV_BATCH]
            for k, _ in batch:
                self._av_wanted.pop(k, None)
            try:
                found = await self.lookup_avatars([lid for _, lid in batch])
            except Exception:
                found = {}
            for key, lid in batch:
                url = found.get(lid) or ""
                self._av_cache[key] = url
                if url:
                    self._emit({"type": "avatar", "platform": self.platform, "source": self.target.key,
                                "user_key": key, "avatar": url,
                                "proxy": getattr(self, "route", self.proxy) or ""})

    # -- public -----------------------------------------------------------------
    async def run(self):
        """Connect, keep reconnecting, and fall back to the Windows proxy if
        direct connections keep failing while a system proxy is configured
        (typical when the browser works through v2rayN but RetChat is Direct)."""
        delay, fails = 2.0, 0
        self.route = self.proxy
        while not self._stop:
            try:
                connector = make_tcp_connector(self.route)
            except ConnectorError as exc:
                self.set_status("error", str(exc))
                return
            switch = False
            async with aiohttp.ClientSession(
                    connector=connector,
                    headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                    timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None),
            ) as self.session:
                av_task = asyncio.create_task(self._avatar_worker())
                while not self._stop:
                    try:
                        auto = self.route != self.proxy
                        self.set_status("connecting", "Connecting via system proxy (automatic)…"
                                        if auto else "Connecting…")
                        await self.connect()
                        delay, fails = 2.0, 0
                        if not self._stop:
                            self.set_status("connecting", "Disconnected – reconnecting…")
                    except asyncio.CancelledError:
                        raise
                    except ConnectorError as exc:
                        self.set_status("error", str(exc))
                        delay = 30.0
                    except Exception as exc:  # network etc.
                        fails += 1
                        self.set_status("error", friendly_error(exc, self.route))
                        delay = min(delay * 2, 30.0)
                        if not self.route and fails >= 2 and resolve_proxy("system"):
                            self.route, fails, delay, switch = "system", 0, 1.0, True
                    if self._stop:
                        break
                    await asyncio.sleep(delay)
                    if switch:
                        break
                av_task.cancel()
        self.set_status("stopped", "Stopped")

    def stop(self):
        self._stop = True

    # -- for subclasses -------------------------------------------------------
    async def connect(self):
        raise NotImplementedError

    def set_status(self, state: str, text: str):
        self._status(self.target.key, state, text)

    def emit(self, msg: dict):
        msg.setdefault("platform", self.platform)
        msg.setdefault("channel", self.target.channel)
        msg.setdefault("source", self.target.key)
        msg["proxy"] = getattr(self, "route", self.proxy) or ""   # images use the same route
        msg.setdefault("ts", time.time())
        msg.setdefault("history", False)
        msg.setdefault("reply", None)
        msg.setdefault("color", None)
        msg.setdefault("badges", [])
        msg.setdefault("role", ["regular"])
        msg.setdefault("avatar", None)
        msg.setdefault("user_key", f"{self.platform}:{(msg.get('username') or '').lower()}")
        if "text" not in msg:
            msg["text"] = _text_of(msg.get("parts", []))
        self._emit(msg)

    def emit_delete(self, ids=None, user_key: str = "", uid: str = "", everything: bool = False):
        """A moderator deleted messages: by message id, by user (ban/timeout) or the whole chat."""
        self._emit({"type": "delete", "platform": self.platform, "source": self.target.key,
                    "ids": [str(i) for i in ids or [] if i], "user_key": user_key or "",
                    "uid": str(uid or ""), "all": everything})

    async def get_json(self, url, **kw):
        async with self.session.get(url, **kw) as r:
            if r.status == 404:
                raise ConnectorError("Channel not found (404)")
            r.raise_for_status()
            return await r.json(content_type=None)


# ══════════════════════════════════════════════════════════════════════════════
# Twitch – anonymous IRC over WebSocket
# ══════════════════════════════════════════════════════════════════════════════

_TW_GQL = "https://gql.twitch.tv/gql"
_TW_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # public web client id


def _irc_unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append({"s": " ", ":": ";", "\\": "\\", "r": "\r", "n": "\n"}.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


class TwitchConnector(BaseConnector):
    platform = "twitch"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.badge_urls: Dict[str, str] = {}

    async def lookup_avatars(self, logins: List[str]) -> Dict[str, str]:
        logins = [l for l in logins if re.fullmatch(r"[a-z0-9_]{1,25}", l)]
        if not logins:
            return {}
        q = "{" + " ".join(f'u{n}:user(login:"{l}"){{profileImageURL(width:70)}}'
                           for n, l in enumerate(logins)) + "}"
        async with self.session.post(_TW_GQL, json={"query": q}, headers={"Client-Id": _TW_CLIENT_ID}) as r:
            d = (await r.json(content_type=None)).get("data") or {}
        return {l: (d.get(f"u{n}") or {}).get("profileImageURL") or "" for n, l in enumerate(logins)}

    async def _load_badges(self):
        q = ('{badges{setID version title imageURL(size:DOUBLE)} '
             'user(login:%s){broadcastBadges{setID version title imageURL(size:DOUBLE)}}}'
             % json.dumps(self.target.channel.lower()))
        try:
            async with self.session.post(
                    _TW_GQL, json={"query": q},
                    headers={"Client-Id": _TW_CLIENT_ID}) as r:
                d = (await r.json(content_type=None)).get("data") or {}
            for b in d.get("badges") or []:
                self.badge_urls[f"{b['setID']}/{b['version']}"] = b["imageURL"]
            user = d.get("user")
            if user is None:
                raise ConnectorError("Twitch channel not found")
            for b in user.get("broadcastBadges") or []:
                self.badge_urls[f"{b['setID']}/{b['version']}"] = b["imageURL"]
        except ConnectorError:
            raise
        except Exception:
            pass   # badges are optional; fall back to built-in icons

    async def connect(self):
        if not self.badge_urls:
            await self._load_badges()
        chan = self.target.channel.lower()
        async with self.session.ws_connect("wss://irc-ws.chat.twitch.tv:443",
                                           heartbeat=60) as ws:
            await ws.send_str("CAP REQ :twitch.tv/tags twitch.tv/commands")
            await ws.send_str("PASS SCHMOOPIIE")
            await ws.send_str(f"NICK justinfan{int(time.time()) % 90000 + 10000}")
            await ws.send_str(f"JOIN #{chan}")
            async for m in ws:
                if self._stop:
                    return
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                for line in m.data.split("\r\n"):
                    if not line:
                        continue
                    if line.startswith("PING"):
                        await ws.send_str("PONG" + line[4:])
                    elif " PRIVMSG " in line:
                        self._on_privmsg(line)
                    elif " CLEARMSG " in line:          # a moderator deleted one message
                        m = re.search(r"(?:^@|;)target-msg-id=([^; ]+)", line)
                        if m:
                            self.emit_delete(ids=[m.group(1)])
                    elif " CLEARCHAT " in line:         # ban / timeout (with a login) or /clear
                        _, _, who = line.partition(" CLEARCHAT ")
                        _, _, login = who.partition(" :")
                        if login.strip():
                            self.emit_delete(user_key=f"twitch:{login.strip().lower()}")
                        else:
                            self.emit_delete(everything=True)
                    elif " JOIN #" in line or " ROOMSTATE " in line:
                        self.set_status("live", "Connected")
                    elif " RECONNECT" in line:
                        return

    def _on_privmsg(self, line: str):
        tags: Dict[str, str] = {}
        if line.startswith("@"):
            raw_tags, line = line[1:].split(" ", 1)
            for kv in raw_tags.split(";"):
                k, _, v = kv.partition("=")
                tags[k] = _irc_unescape(v)
        prefix, _, rest = line.partition(" PRIVMSG ")
        _, _, text = rest.partition(" :")
        login = prefix.lstrip(":").split("!")[0]
        if text.startswith("\x01ACTION ") and text.endswith("\x01"):
            text = text[8:-1]

        # emotes:  "25:0-4,12-16/1902:6-10"   (indices in code points)
        spans = []
        for spec in filter(None, tags.get("emotes", "").split("/")):
            eid, _, ranges = spec.partition(":")
            for rg in ranges.split(","):
                a, _, b = rg.partition("-")
                if a.isdigit() and b.isdigit():
                    spans.append((int(a), int(b), eid))
        spans.sort()
        parts, pos = [], 0
        for a, b, eid in spans:
            if a > pos:
                parts.append({"type": "text", "text": text[pos:a]})
            parts.append({"type": "emote", "name": text[a:b + 1],
                          "url": f"https://static-cdn.jtvnw.net/emoticons/v2/{eid}/default/dark/2.0"})
            pos = b + 1
        if pos < len(text):
            parts.append({"type": "text", "text": text[pos:]})

        badges, sets = [], []
        for spec in filter(None, tags.get("badges", "").split(",")):
            set_id, _, ver = spec.partition("/")
            sets.append(set_id)
            url = self.badge_urls.get(f"{set_id}/{ver}")
            if set_id == "bot-badge":
                tags["_bot"] = "1"
            icon = set_id if set_id in ("broadcaster", "moderator", "vip",
                                         "subscriber", "founder", "partner") else None
            if url or icon:
                badges.append({"url": url, "icon": icon, "title": set_id.replace("-", " ").title()})

        is_mod = tags.get("mod") == "1" or "broadcaster" in sets or "moderator" in sets
        is_sub = tags.get("subscriber") == "1" or "subscriber" in sets or "founder" in sets
        is_vip = "vip" in sets or bool(tags.get("vip"))

        reply = None
        if tags.get("reply-parent-display-name"):
            reply = {"user": tags["reply-parent-display-name"],
                     "text": tags.get("reply-parent-msg-body", "")}
            # Twitch prefixes replies with "@user " – drop it from the body
            if parts and parts[0]["type"] == "text":
                parts[0]["text"] = re.sub(r"^@\S+\s*", "", parts[0]["text"])

        self.emit({
            "id": tags.get("id") or uuid.uuid4().hex,
            "username": tags.get("display-name") or login,
            "user_key": f"twitch:{login.lower()}",
            "avatar": self.avatar_for(f"twitch:{login.lower()}", login.lower()),
            "color": tags.get("color") or None,
            "parts": parts,
            "badges": badges,
            "role": _roles(is_mod, is_sub, is_vip),
            "reply": reply,
            "bot": tags.get("_bot") == "1",
        })


# ══════════════════════════════════════════════════════════════════════════════
# Kick – Centrifugo websocket (2026 realtime platform), Pusher as fallback
# ══════════════════════════════════════════════════════════════════════════════

_KICK_HDRS = {"Accept": "application/json", "Origin": "https://kick.com",
              "Referer": "https://kick.com/"}


class KickConnector(BaseConnector):
    platform = "kick"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.channel_id = 0
        self.chatroom_id = 0
        self.sub_badges: List[tuple] = []   # [(months, url)] sorted

    AV_BATCH = 6

    async def lookup_avatars(self, slugs: List[str]) -> Dict[str, str]:
        async def one(slug):
            if not re.fullmatch(r"[\w-]{1,40}", slug or ""):
                return slug, ""
            try:
                async with self.session.get(
                        f"https://kick.com/api/v2/channels/{self.target.channel}/users/{slug}",
                        headers=_KICK_HDRS) as r:
                    if r.status != 200:
                        return slug, ""
                    d = await r.json(content_type=None)
                return slug, (d or {}).get("profile_pic") or ""
            except Exception:
                return slug, ""
        return dict(await asyncio.gather(*(one(s_) for s_ in slugs)))

    async def _load_channel(self):
        d = await self.get_json(f"https://kick.com/api/v2/channels/{self.target.channel}",
                                headers=_KICK_HDRS)
        self.channel_id = int(d["id"])
        self.chatroom_id = int(d["chatroom"]["id"])
        self.sub_badges = sorted(
            (int(b.get("months") or 0), (b.get("badge_image") or {}).get("src"))
            for b in d.get("subscriber_badges") or [] if (b.get("badge_image") or {}).get("src"))

    async def connect(self):
        if not self.chatroom_id:
            await self._load_channel()
        client_id = str(uuid.uuid4())
        body = {"client": {"id": client_id, "type": "web"},
                "capabilities": {"accepted_providers": [{"provider": "centrifugo"},
                                                        {"provider": "pusher"}]}}
        conns = []
        try:
            async with self.session.post(
                    f"https://web.kick.com/api/v1/realtime/channels/{self.channel_id}/chat/connection",
                    json=body, headers=_KICK_HDRS) as r:
                conns = ((await r.json(content_type=None)).get("data") or {}).get("connections") or []
        except Exception:
            pass
        for c in conns:
            creds = c.get("credentials") or {}
            if c.get("provider") == "centrifugo" and creds.get("url"):
                return await self._centrifugo(creds["url"], client_id)
            if c.get("provider") == "pusher" and creds.get("app_key"):
                return await self._pusher(creds["app_key"], creds.get("cluster", "us2"))
        raise ConnectorError("Kick realtime endpoint unavailable")

    async def _centrifugo(self, url: str, client_id: str):
        token = None
        async with self.session.post("https://web.kick.com/api/v1/realtime/auth/connection",
                                     json={"client_id": client_id}, headers=_KICK_HDRS) as r:
            if r.ok:
                token = ((await r.json(content_type=None)).get("data") or {}).get("token")
        channel = f"chatrooms.{self.chatroom_id}.v2"
        async with self.session.ws_connect(url, headers={"Origin": "https://kick.com"}) as ws:
            con = {"name": "js"}
            if token:
                con["token"] = token
            await ws.send_str(json.dumps({"id": 1, "connect": con}))
            async for m in ws:
                if self._stop:
                    return
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                for line in m.data.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line == "{}":                    # server ping
                        await ws.send_str("{}")
                        continue
                    d = json.loads(line)
                    if d.get("id") == 1:
                        if d.get("error"):
                            raise ConnectorError(f"Kick connect error: {d['error']}")
                        await ws.send_str(json.dumps({"id": 2, "subscribe": {"channel": channel}}))
                    elif d.get("id") == 2:
                        if d.get("error"):
                            raise ConnectorError(f"Kick subscribe error: {d['error']}")
                        self.set_status("live", "Connected")
                    elif "push" in d:
                        pub = (d["push"].get("pub") or {}).get("data") or {}
                        self._on_event(pub.get("event", ""), pub.get("data"))

    async def _pusher(self, key: str, cluster: str):
        url = (f"wss://ws-{cluster}.pusher.com/app/{key}"
               "?protocol=7&client=js&version=8.4.0&flash=false")
        async with self.session.ws_connect(url, heartbeat=60) as ws:
            async for m in ws:
                if self._stop:
                    return
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                d = json.loads(m.data)
                ev = d.get("event", "")
                if ev == "pusher:connection_established":
                    await ws.send_str(json.dumps({"event": "pusher:subscribe", "data": {
                        "auth": "", "channel": f"chatrooms.{self.chatroom_id}.v2"}}))
                elif ev == "pusher_internal:subscription_succeeded":
                    self.set_status("live", "Connected")
                elif ev == "pusher:ping":
                    await ws.send_str(json.dumps({"event": "pusher:pong", "data": {}}))
                else:
                    self._on_event(ev, d.get("data"))

    def _sub_badge(self, months: int) -> Optional[str]:
        best = None
        for mo, url in self.sub_badges:
            if mo <= months:
                best = url
        return best or (self.sub_badges[0][1] if self.sub_badges else None)

    def _on_event(self, event: str, data):
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                return
        if not isinstance(data, dict):
            data = {}
        if event.endswith("MessageDeletedEvent"):      # a moderator deleted one message
            mid = (data.get("message") or {}).get("id") or data.get("id")
            if mid:
                self.emit_delete(ids=[mid])
            return
        if event.endswith("UserBannedEvent"):          # ban / timeout removes the user's messages
            u = data.get("user") or {}
            slug = (u.get("slug") or u.get("username") or "").lower()
            if slug:
                self.emit_delete(user_key=f"kick:{slug}")
            return
        if event.endswith("ChatroomClearEvent"):
            self.emit_delete(everything=True)
            return
        if not event.endswith("ChatMessageEvent"):
            return
        sender = data.get("sender") or {}
        ident = sender.get("identity") or {}
        badges, types = [], set()
        for b in ident.get("badges") or []:
            t = b.get("type", "")
            types.add(t)
            if t == "subscriber":
                url = self._sub_badge(int(b.get("count") or 1))
                badges.append({"url": url, "icon": "kick_subscriber",
                               "title": f"Subscriber ({b.get('count', 1)} mo)"})
            else:
                # Kick-style icon when we have one (kick_moderator, kick_vip, kick_og, …)
                from images import KICK_STYLE
                icon = f"kick_{t}" if f"kick_{t}" in KICK_STYLE else t
                badges.append({"url": None, "icon": icon, "title": b.get("text") or t})
        for b in ident.get("badges_v2") or []:
            if b.get("image_url") and b.get("name") not in types:
                lvl = (b.get("metadata") or {}).get("level")
                badges.append({"url": b["image_url"], "icon": None,
                               "title": f"Level {lvl}" if lvl else b.get("name", "")})

        content = data.get("content") or ""
        parts, pos = [], 0
        for m in re.finditer(r"\[emote:(\d+):([^\]]*)\]", content):
            if m.start() > pos:
                parts.append({"type": "text", "text": content[pos:m.start()]})
            parts.append({"type": "emote", "name": m.group(2),
                          "url": f"https://files.kick.com/emotes/{m.group(1)}/fullsize"})
            pos = m.end()
        if pos < len(content):
            parts.append({"type": "text", "text": content[pos:]})

        reply = None
        meta = data.get("metadata") or {}
        if data.get("type") == "reply" and meta.get("original_sender"):
            reply = {"user": meta["original_sender"].get("username", ""),
                     "text": re.sub(r"\[emote:\d+:([^\]]*)\]", r"\1",
                                    (meta.get("original_message") or {}).get("content", ""))}

        self.emit({
            "id": data.get("id") or uuid.uuid4().hex,
            "username": sender.get("username", "?"),
            "user_key": f"kick:{(sender.get('slug') or sender.get('username') or '').lower()}",
            "avatar": self.avatar_for(f"kick:{(sender.get('slug') or sender.get('username') or '').lower()}",
                                      sender.get("slug") or sender.get("username") or ""),
            "color": ident.get("color"),
            "parts": parts,
            "badges": badges,
            "role": _roles(bool(types & {"broadcaster", "moderator"}),
                           bool(types & {"subscriber", "founder"}),
                           "vip" in types),
            "reply": reply,
        })


# ══════════════════════════════════════════════════════════════════════════════
# YouTube – innertube live_chat polling
# ══════════════════════════════════════════════════════════════════════════════

_YT_COOKIES = {"SOCS": "CAI", "CONSENT": "YES+1"}   # skip the EU consent wall


class YouTubeConnector(BaseConnector):
    platform = "youtube"

    async def _get(self, url: str) -> str:
        async with self.session.get(url, cookies=_YT_COOKIES) as r:
            r.raise_for_status()
            return await r.text()

    async def _resolve_video(self) -> str:
        ch = self.target.channel
        if re.fullmatch(r"[\w-]{11}", ch):
            return ch
        page = await self._get(f"https://www.youtube.com/{ch}/live")
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', page)
        if m and ('"isLive":true' in page or '"isLiveNow":true' in page):
            return m.group(1)
        raise ConnectorError("Channel is not live right now – retrying in 30 s")

    async def connect(self):
        vid = await self._resolve_video()
        page = await self._get(f"https://www.youtube.com/live_chat?is_popout=1&v={vid}")
        key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
        ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page)
        m = re.search(r'(?:window\["ytInitialData"\]|var ytInitialData)\s*=\s*(\{.+?\});\s*</script>', page, re.S)
        if not (key and ver and m):
            raise ConnectorError("Could not read YouTube chat page")
        data = json.loads(m.group(1))
        lcr = (data.get("contents") or {}).get("liveChatRenderer")
        if not lcr:
            msg = json.dumps(data.get("contents", {}), ensure_ascii=False)
            if "disabled" in msg.lower():
                raise ConnectorError("Chat is disabled for this live stream")
            raise ConnectorError("No live chat for this video")

        cont = self._all_messages_continuation(lcr) or self._continuation(lcr.get("continuations"))[0]
        for a in lcr.get("actions") or []:
            self._on_action(a, history=True)
        self.set_status("live", "Connected")

        api = (f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
               f"?key={key.group(1)}&prettyPrint=false")
        ctx = {"client": {"clientName": "WEB", "clientVersion": ver.group(1)}}
        first = True
        while not self._stop and cont:
            async with self.session.post(api, json={"context": ctx, "continuation": cont},
                                         cookies=_YT_COOKIES) as r:
                r.raise_for_status()
                j = await r.json(content_type=None)
            lc = (j.get("continuationContents") or {}).get("liveChatContinuation")
            if not lc:
                raise ConnectorError("Live stream ended")
            for a in lc.get("actions") or []:
                self._on_action(a, history=first)
            first = False
            cont, timeout = self._continuation(lc.get("continuations"))
            await asyncio.sleep(max(0.8, min(timeout / 1000.0, 4.0)))

    @staticmethod
    def _continuation(conts):
        for c in conts or []:
            for v in c.values():
                if isinstance(v, dict) and v.get("continuation"):
                    return v["continuation"], int(v.get("timeoutMs", 2000))
        return None, 2000

    @staticmethod
    def _all_messages_continuation(lcr) -> Optional[str]:
        """Prefer the 'Live chat' (all messages) view over 'Top chat'."""
        try:
            items = (lcr["header"]["liveChatHeaderRenderer"]["viewSelector"]
                     ["sortFilterSubMenuRenderer"]["subMenuItems"])
            return items[-1]["continuation"]["reloadContinuationData"]["continuation"]
        except Exception:
            return None

    def _on_action(self, action: dict, history: bool):
        for k in ("markChatItemAsDeletedAction", "removeChatItemAction"):
            if k in action:                             # a moderator deleted one message
                self.emit_delete(ids=[(action[k] or {}).get("targetItemId")])
                return
        for k in ("markChatItemsByAuthorAsDeletedAction", "removeChatItemByAuthorAction"):
            if k in action:                             # ban / timeout removes the user's messages
                uid = (action[k] or {}).get("externalChannelId")
                if uid:
                    self.emit_delete(uid=uid)
                return
        item = (action.get("addChatItemAction") or {}).get("item") or {}
        r = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not r:
            return
        parts = []
        for run in (r.get("message") or {}).get("runs") or []:
            if "text" in run:
                parts.append({"type": "text", "text": run["text"]})
            elif "emoji" in run:
                e = run["emoji"]
                thumbs = (e.get("image") or {}).get("thumbnails") or []
                name = (e.get("shortcuts") or [e.get("emojiId", "")])[0]
                if e.get("isCustomEmoji") and thumbs:
                    parts.append({"type": "emote", "url": thumbs[-1]["url"], "name": name})
                else:
                    parts.append({"type": "text", "text": e.get("emojiId", name)})
        if "purchaseAmountText" in r:
            amt = r["purchaseAmountText"].get("simpleText", "")
            parts.insert(0, {"type": "text", "text": f"[{amt}] "})

        badges, is_mod, is_sub = [], False, False
        for b in r.get("authorBadges") or []:
            br = b.get("liveChatAuthorBadgeRenderer") or {}
            tip = br.get("tooltip", "")
            icon = ((br.get("icon") or {}).get("iconType") or "").lower()
            thumbs = (br.get("customThumbnail") or {}).get("thumbnails") or []
            if thumbs:
                is_sub = True
                badges.append({"url": thumbs[-1]["url"], "icon": "subscriber", "title": tip})
            elif icon:
                if icon in ("owner", "moderator"):
                    is_mod = True
                badges.append({"url": None,
                               "icon": {"owner": "broadcaster"}.get(icon, icon),
                               "title": tip})
        self.emit({
            "id": r.get("id") or uuid.uuid4().hex,
            "username": (r.get("authorName") or {}).get("simpleText", "?").lstrip("@"),
            "avatar": (((r.get("authorPhoto") or {}).get("thumbnails") or [{}])[-1]).get("url"),
            "uid": r.get("authorExternalChannelId") or "",
            "parts": parts,
            "badges": badges,
            "role": _roles(is_mod, is_sub, False),
            "history": history,
        })


# ══════════════════════════════════════════════════════════════════════════════
# Minimal socket.io client (Engine.IO v3 and v4) over aiohttp
# ══════════════════════════════════════════════════════════════════════════════

class _SocketIO:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse, eio: int):
        self.ws, self.eio = ws, eio
        self._ack = 0
        self.acks: Dict[int, asyncio.Future] = {}
        self.ping_interval = 25.0

    async def emit(self, event: str, data, want_ack=False):
        self._ack += 1
        aid = self._ack if want_ack else ""
        fut = None
        if want_ack:
            fut = asyncio.get_running_loop().create_future()
            self.acks[self._ack] = fut
        await self.ws.send_str(f"42{aid}" + json.dumps([event, data], ensure_ascii=False))
        return fut

    async def _pinger(self):
        while True:
            await asyncio.sleep(self.ping_interval)
            await self.ws.send_str("2")

    async def events(self):
        """Yield (event, data) tuples; handles handshake, pings and acks."""
        pinger = None
        try:
            async for m in self.ws:
                if m.type != aiohttp.WSMsgType.TEXT:
                    break
                p = m.data
                if p.startswith("0"):
                    info = json.loads(p[1:])
                    self.ping_interval = info.get("pingInterval", 25000) / 1000.0
                    if self.eio == 4:
                        await self.ws.send_str("40")
                    elif pinger is None:
                        pinger = asyncio.create_task(self._pinger())
                elif p == "2":
                    await self.ws.send_str("3")
                elif p.startswith("40"):
                    yield "connect", None
                elif p.startswith("41"):
                    return
                elif p.startswith("43"):
                    mm = re.match(r"43(\d+)(.*)", p, re.S)
                    if mm:
                        fut = self.acks.pop(int(mm.group(1)), None)
                        if fut and not fut.done():
                            args = json.loads(mm.group(2))
                            fut.set_result(args[0] if args else None)
                elif p.startswith("42"):
                    mm = re.match(r"42\d*(.*)", p, re.S)
                    arr = json.loads(mm.group(1))
                    if arr:
                        yield arr[0], (arr[1] if len(arr) > 1 else None)
        finally:
            if pinger:
                pinger.cancel()


# ══════════════════════════════════════════════════════════════════════════════
# Aparat – socket.io (EIO 3) at lws.aparat.com
# ══════════════════════════════════════════════════════════════════════════════

class AparatConnector(BaseConnector):
    platform = "aparat"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.info: dict = {}
        self.recent: Dict[str, dict] = {}       # guid → {user,text} for replies

    async def _load(self):
        d = await self.get_json(
            f"https://www.aparat.com/api/fa/v2/Live/LiveStream/show/username/{self.target.channel}")
        if not d.get("jwt"):
            raise ConnectorError("Aparat channel not found or not streaming")
        rtmp = ((d.get("stream_line") or {}).get("rtmp") or "").rstrip("/")
        vip = d.get("vip_users") or []
        self.info = {
            "jwt": d["jwt"],
            # chat room code: Aparat now sends it as "live_code" (the RTMP URL it used to be
            # taken from is empty since late 2026); keep the old source as a fallback
            "key": (d.get("live_code") or (rtmp.split("/")[-1] if rtmp else "") or self.target.channel),
            "badges": sorted(((int(k), v) for k, v in (d.get("badge_data") or {}).items()
                              if str(k).isdigit()), key=lambda x: x[0]),
            "mods": {u.lower() for u in d.get("moderator_data") or []},
            "admins": {str(u).lower() for u in d.get("admins") or []},     # Aparat staff
            "vips": {u.lower() for u in (vip if isinstance(vip, list) else str(vip).split(","))
                     if u},
            "streamer": self.target.channel.lower(),
            "server": ((d.get("oneping") or {}).get("socket_server") or "https://lws.aparat.com"),
            "live": ((d.get("live_status") or {}).get("type") == "connected"),
        }

    async def connect(self):
        await self._load()
        host = urlparse(self.info["server"]).netloc.split(":")[0] or "lws.aparat.com"
        url = f"wss://{host}/socket.io/?EIO=3&transport=websocket"
        async with self.session.ws_connect(url, headers={"Origin": "https://www.aparat.com"}) as ws:
            sio = _SocketIO(ws, eio=3)
            udid = uuid.uuid4().hex[:9]
            async for ev, data in sio.events():
                if self._stop:
                    return
                if ev == "connect":
                    fut = await sio.emit("join_room", {
                        "data": {"key": self.info["key"], "name": "Felan Room", "udid": udid},
                        "header": {"luser": "", "ltoken": "", "jwt": self.info["jwt"], "source": "web"},
                    }, want_ack=True)
                    asyncio.create_task(self._on_join(fut))
                elif ev == "comment" and isinstance(data, dict):
                    self._on_comment(data, history=False)

    async def _on_join(self, fut):
        try:
            res = await asyncio.wait_for(fut, 15)
        except Exception:
            return
        if isinstance(res, dict):
            self.set_status("live", "Connected" if self.info.get("live")
                            else "Connected (stream offline – waiting)")
            for c in res.get("history") or []:
                self._on_comment(c, history=True)

    def _on_comment(self, c: dict, history: bool):
        user = c.get("username") or "?"
        text = c.get("comment") or ""
        guid = c.get("guid") or uuid.uuid4().hex
        # Aparat sends moderator commands as normal comments (same rules as aparat.com):
        #   "/delete <id>"  – a moderator deleted a message (the command itself is never shown)
        #   "/pm …"         – chat between the streamer and moderators only
        #   "/private …"    – message from Aparat staff to moderators only
        low = user.lower()
        staff = low in self.info.get("admins", ())
        moder = staff or low in self.info.get("mods", ()) or low == self.info.get("streamer")
        if text.startswith("/delete") and moder:
            m = re.match(r"^(\S+)\s(.+)$", text.strip())
            if m:
                self.emit_delete(ids=[m.group(2).strip()])
            return
        if (text.startswith("/pm") and moder) or (text.startswith("/private") and staff):
            return
        reply = None
        m = re.match(r"^/replay\s+([\w-]+)\s*(.*)$", text, re.S)
        if m:
            text = m.group(2)
            reply = self.recent.get(m.group(1))     # None when it replies to an older message we never saw
        parts = _split_tokens(text, c.get("emote") or {})

        low = user.lower()
        try:
            months = int(c.get("subCount") or 0)
        except (TypeError, ValueError):
            months = 0
        badges = []
        is_owner = low == self.info.get("streamer")
        is_mod = low in self.info.get("mods", ())
        is_vip = low in self.info.get("vips", ())
        if is_owner:
            badges.append({"url": None, "icon": "broadcaster", "title": "استریمر"})
        elif is_mod:
            badges.append({"url": None, "icon": "moderator", "title": "مدیر"})
        if c.get("isAdmin"):
            badges.append({"url": None, "icon": "staff", "title": "Admin"})
        if is_vip:
            badges.append({"url": None, "icon": "vip", "title": "VIP"})
        if months > 0:
            url = None
            for mo, u in self.info.get("badges", []):
                if mo <= months:
                    url = u
            badges.append({"url": url, "icon": "subscriber", "title": f"مشترک {months} ماهه"})

        plain = _text_of([p for p in parts if p["type"] == "text"])
        self.recent[guid] = {"user": user, "text": plain[:120]}
        if len(self.recent) > 400:
            for k in list(self.recent)[:200]:
                self.recent.pop(k, None)
        self.emit({
            "id": guid, "username": user, "parts": parts, "badges": badges,
            "avatar": c.get("avatar") or None,
            "role": _roles(is_owner or is_mod or bool(c.get("isAdmin")), months > 0, is_vip),
            "reply": reply, "history": history,
        })


# ══════════════════════════════════════════════════════════════════════════════
# OneFa – socket.io (EIO 4) at onefa.ir
# ══════════════════════════════════════════════════════════════════════════════

_ONEFA = "https://onefa.ir"
_ONEFA_SUB = {1: "/assets/img/sub.png", 3: "/assets/img/sub3.png", 6: "/assets/img/sub6.png",
              9: "/assets/img/sub9.png", 12: "/assets/img/sub12.png"}


class OneFaConnector(BaseConnector):
    platform = "onefa"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.emotes: Dict[str, str] = {}

    def _abs(self, u: Optional[str]) -> Optional[str]:
        if not u:
            return None
        return u if u.startswith(("http", "data:")) else _ONEFA + u

    async def connect(self):
        async with self.session.ws_connect("wss://onefa.ir/socket.io/?EIO=4&transport=websocket",
                                           headers={"Origin": _ONEFA}) as ws:
            sio = _SocketIO(ws, eio=4)
            async for ev, data in sio.events():
                if self._stop:
                    return
                if ev == "connect":
                    fut = await sio.emit("room:join", {"username": self.target.channel}, want_ack=True)
                    asyncio.create_task(self._on_join(fut))
                elif ev == "chat:msg" and isinstance(data, dict):
                    self._on_msg(data, history=False)
                elif ev == "chat:deleted" and isinstance(data, dict):   # a moderator deleted a message
                    self.emit_delete(ids=[data.get("id")])
                elif ev == "chat:purged" and isinstance(data, dict):    # ban / timeout
                    if data.get("userId") is not None:
                        self.emit_delete(uid=data["userId"])
                elif ev == "chat:cleared":
                    self.emit_delete(everything=True)
                elif ev == "chat:bot" and isinstance(data, dict):
                    self.emit({"id": str(data.get("id") or uuid.uuid4().hex),
                               "username": data.get("name") or "Bot",
                               "parts": self._split(data.get("text") or ""),
                               "badges": [{"url": None, "icon": "verified", "title": "Bot"}],
                               "bot": True})

    async def _on_join(self, fut):
        try:
            res = await asyncio.wait_for(fut, 15)
        except Exception:
            return
        if not isinstance(res, dict):
            return
        if res.get("error"):
            self.set_status("error", f"OneFa: {res['error']}")
            return
        ch = res.get("channel") or {}
        cid = ch.get("id")
        em = res.get("emojis") or {}
        for f in em.get("global") or []:
            self.emotes[":" + re.sub(r"\.[^.]+$", "", f).lower() + ":"] = f"{_ONEFA}/assets/emoji/{f}"
        for f in em.get("channel") or []:
            self.emotes[":" + re.sub(r"\.[^.]+$", "", f).lower() + ":"] = f"{_ONEFA}/assets/useremoji/{cid}/{f}"
        self.sub_badges = ch.get("subBadges") or {}
        self.set_status("live", "Connected" + ("" if ch.get("live") else " (offline)"))
        for m in res.get("history") or []:
            self._on_msg(m, history=True)

    def _split(self, text: str) -> List[dict]:
        parts, pos = [], 0
        for m in re.finditer(r":[\w-]+:", text):
            url = self.emotes.get(m.group(0).lower())
            if not url:
                continue
            if m.start() > pos:
                parts.append({"type": "text", "text": text[pos:m.start()]})
            parts.append({"type": "emote", "url": url, "name": m.group(0)})
            pos = m.end()
        if pos < len(text):
            parts.append({"type": "text", "text": text[pos:]})
        return parts

    def _on_msg(self, m: dict, history: bool):
        if m.get("audience", "public") != "public" or m.get("deleted"):
            return
        u = m.get("user") or {}
        badges = []
        if u.get("owner"):
            badges.append({"url": None, "icon": "broadcaster", "title": "استریمر"})
        elif u.get("mod"):
            badges.append({"url": None, "icon": "moderator", "title": "مدیر کانال"})
        if u.get("staff"):
            badges.append({"url": None, "icon": "staff", "title": "Staff"})
        if u.get("vip"):
            badges.append({"url": None, "icon": "vip", "title": "VIP"})
        if u.get("og"):
            badges.append({"url": None, "icon": "og", "title": "OG"})
        if u.get("friend"):
            badges.append({"url": None, "icon": "friend", "title": "دوست استریمر"})
        days = int(u.get("subDays") or 0)
        if days > 0:
            months = max(1, round(days / 30))
            url = u.get("subBadge")
            if not url:
                for mo in sorted(_ONEFA_SUB):
                    if mo <= months:
                        url = _ONEFA_SUB[mo]
            badges.append({"url": self._abs(url), "icon": "subscriber", "title": f"مشترک · {months} ماه"})
        if int(u.get("gifted") or 0) > 0:
            badges.append({"url": None, "icon": "sub_gifter", "title": f"هدیه‌دهنده · {u['gifted']}"})

        reply = None
        if m.get("reply"):
            rp = m["reply"]
            rtext = re.sub(r":[\w-]+:", lambda mm: "" if mm.group(0).lower() in self.emotes else mm.group(0),
                           rp.get("text", "")).strip()
            reply = {"user": rp.get("name") or rp.get("username", ""), "text": rtext}

        self.emit({
            "id": str(m.get("id") or uuid.uuid4().hex),
            "username": u.get("name") or u.get("username") or "?",
            "user_key": f"onefa:{(u.get('username') or '').lower()}",
            "uid": str(u.get("id") or ""),
            "avatar": self._abs(u.get("avatar")),
            "color": u.get("color"),
            "parts": self._split(m.get("text") or ""),
            "badges": badges,
            "role": _roles(bool(u.get("owner") or u.get("mod")), days > 0, bool(u.get("vip"))),
            "reply": reply,
            "history": history,
        })


CONNECTORS = {
    "twitch": TwitchConnector, "kick": KickConnector, "youtube": YouTubeConnector,
    "aparat": AparatConnector, "onefa": OneFaConnector,
}


# ══════════════════════════════════════════════════════════════════════════════
# ChatHub – runs all connectors in one background asyncio thread
# ══════════════════════════════════════════════════════════════════════════════

class ChatHub:
    """Thread-safe owner of all live connections.

    ``on_message(dict)`` and ``on_status(key, state, text)`` are called from the
    background thread – the GUI wraps them in Qt signals.
    """

    def __init__(self, on_message: Callable[[dict], None],
                 on_status: Callable[[str, str, str], None]):
        self.on_message = on_message
        self.on_status = on_status
        self.loop = asyncio.new_event_loop()
        self._tasks: Dict[str, tuple] = {}   # key → (connector, task)
        self._thread = threading.Thread(target=self._run, daemon=True, name="ChatHub")
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self, target: Target, proxy: Optional[str] = None):
        def _go():
            if target.key in self._tasks:
                return
            cls = CONNECTORS[target.platform]
            con = cls(target, self.on_message, self.on_status, proxy)
            task = self.loop.create_task(con.run())
            self._tasks[target.key] = (con, task)
        self.loop.call_soon_threadsafe(_go)

    def stop(self, key: str):
        def _go():
            item = self._tasks.pop(key, None)
            if item:
                con, task = item
                con.stop()
                task.cancel()
                self.on_status(key, "stopped", "Stopped")
        self.loop.call_soon_threadsafe(_go)

    def test_proxy(self, spec: Optional[str], callback: Callable[[bool, str], None]):
        """Check a proxy in the background; *callback(ok, message)* runs on this thread."""
        async def _go():
            ok, msg = await test_proxy(spec)
            callback(ok, msg)
        asyncio.run_coroutine_threadsafe(_go(), self.loop)

    def stop_all(self):
        for k in list(self._tasks):
            self.stop(k)

    def is_running(self, key: str) -> bool:
        return key in self._tasks

    def shutdown(self):
        self.stop_all()
        self.loop.call_soon_threadsafe(self.loop.stop)


# ══════════════════════════════════════════════════════════════════════════════
# CLI test:  python connectors.py https://kick.com/xqc  [seconds]
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    proxy = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--proxy=")), None)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    targets = [parse_target(a) for a in args if not a.isdigit()]
    secs = next((int(a) for a in args if a.isdigit()), 30)
    print("route:", proxy_label(proxy))
    counts: Dict[str, int] = {}

    def _msg(m):
        if m.get("type") == "avatar":
            counts["avatars:" + m["platform"]] = counts.get("avatars:" + m["platform"], 0) + 1
            return
        if m.get("type") == "delete":
            print(f"[{m['source']}] DELETE ids={m['ids']} user={m['user_key']} uid={m['uid']} all={m['all']}")
            return
        counts[m["source"]] = counts.get(m["source"], 0) + 1
        b = ",".join((x.get("icon") or "img") + ("*" if x.get("url") else "") for x in m["badges"])
        emo = sum(1 for p in m["parts"] if p["type"] == "emote")
        print(f"[{m['source']}]{'[H]' if m['history'] else ''} {m['username']} "
              f"{m['role']} badges=[{b}] emotes={emo} reply={bool(m['reply'])}: {m['text'][:80]}")

    def _st(k, s, t):
        print(f"--- {k}: {s} {t}")

    hub = ChatHub(_msg, _st)
    for t in targets:
        if t:
            hub.start(t, proxy)
    time.sleep(secs)
    hub.shutdown()
    print("COUNTS", counts)
