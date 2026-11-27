"""Local web page for OBS (Browser Source): live chat + trigger progress bars.

Runs inside the ChatHub asyncio loop, listens on 127.0.0.1 only.

    http://127.0.0.1:8787/              chat + progress bars
    http://127.0.0.1:8787/?bars=0       chat only
    http://127.0.0.1:8787/?chat=0       progress bars only
    extra options: &fade=30 (hide messages after 30 s)  &max=50
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict, deque
from pathlib import Path
from typing import Dict, Optional, Set

import aiohttp
from aiohttp import web

import fonts
from connectors import UA, make_tcp_connector

CACHE_DIR = Path.home() / ".ret_chat_cache" / "img2"     # shared with the app's image cache


def _sniff(data: bytes) -> str:
    if data[:3] == b"GIF":
        return "image/gif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data.lstrip()[:4] in (b"<svg", b"<?xm"):
        return "image/svg+xml"
    return "application/octet-stream"


class ObsServer:
    def __init__(self, loop: asyncio.AbstractEventLoop, logo_dir: Path, icons: Dict[str, bytes]):
        self.loop = loop
        self.logo_dir = Path(logo_dir)
        self.icons = icons
        self.port: Optional[int] = None
        self.error = ""
        self._runner: Optional[web.AppRunner] = None
        self._clients: Set[asyncio.Queue] = set()
        self._recent: deque = deque(maxlen=150)
        self._config: dict = {}
        self._progress: list = []
        self._sessions: Dict[str, aiohttp.ClientSession] = {}
        self.lan = False
        # image URLs that appeared in chat → proxy route. /img only fetches these, so the
        # page can't be abused as an open web proxy by other devices on the network.
        self._allowed: "OrderedDict[str, str]" = OrderedDict()

    # ── lifecycle (call from any thread) ──────────────────────────────────────
    def start(self, port: int, on_done=None, lan: bool = False):
        """Listen on 127.0.0.1, or on every network interface when *lan* is True
        (so OBS on another computer in the same network can open the page)."""
        async def _go():
            await self._stop()
            ok, msg = True, ""
            try:
                app = web.Application()
                app.router.add_get("/", self._page)
                app.router.add_get("/events", self._events)
                app.router.add_get("/img", self._img)
                app.router.add_get("/logo/{name}", self._logo)
                app.router.add_get("/icon/{name}", self._icon)
                app.router.add_get("/font/{key}", self._font)
                self._runner = web.AppRunner(app, access_log=None)
                await self._runner.setup()
                await web.TCPSite(self._runner, "0.0.0.0" if lan else "127.0.0.1", port).start()
                self.port = port
                self.lan = lan
                # find installed font files in the background, then resend the config with the font
                asyncio.get_running_loop().run_in_executor(None, self._fonts_then_config)
            except OSError as exc:
                ok, msg = False, f"Port {port} is in use or blocked ({exc.strerror or exc})"
                self.port = None
                if self._runner:
                    await self._runner.cleanup()
                    self._runner = None
            self.error = msg
            if on_done:
                on_done(ok, msg)
        asyncio.run_coroutine_threadsafe(_go(), self.loop)

    def stop(self):
        asyncio.run_coroutine_threadsafe(self._stop(), self.loop)

    async def _stop(self):
        for q in list(self._clients):
            q.put_nowait(None)
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        for s in self._sessions.values():
            await s.close()
        self._sessions.clear()
        self.port = None

    # ── publishing (call from any thread) ────────────────────────────────────
    def publish(self, event: str, data):
        if event == "config":                         # attach the chosen font's files (index lookup is quick)
            data = self._with_font(dict(data))

        def _go():
            if event == "config":
                self._config = data
            elif event == "progress":
                self._progress = data
            elif event == "msg":
                data["_t"] = time.time()             # so replays know how old the message is
                self._recent.append(data)
                route = data.get("proxy") or ""
                urls = [b.get("url") for b in data.get("badges") or []]
                urls += [p.get("url") for p in data.get("parts") or [] if p.get("type") == "emote"]
                urls.append(data.get("avatar"))
                for u in urls:
                    if u:
                        self._allowed[u] = route
                        self._allowed.move_to_end(u)
                while len(self._allowed) > 5000:
                    self._allowed.popitem(last=False)
            elif event == "avatar":
                if data.get("avatar"):
                    self._allowed[data["avatar"]] = data.get("proxy") or ""
                for m in self._recent:                  # replays get the picture too
                    if m.get("user_key") == data.get("user_key") and not m.get("avatar"):
                        m["avatar"] = data.get("avatar")
            elif event == "clear":
                self._recent.clear()
            elif event == "delete":                     # moderator deleted these messages
                gone = set(data.get("ids") or [])
                keep = [m for m in self._recent if m.get("id") not in gone]
                self._recent.clear()
                self._recent.extend(keep)
            line = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            for q in list(self._clients):
                if q.qsize() < 500:
                    q.put_nowait(line)
        self.loop.call_soon_threadsafe(_go)

    # ── handlers ──────────────────────────────────────────────────────────────
    async def _page(self, request):
        return web.Response(text=PAGE, content_type="text/html", charset="utf-8",
                            headers={"Cache-Control": "no-store"})

    async def _events(self, request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                           "Cache-Control": "no-cache", "Connection": "keep-alive"})
        await resp.prepare(request)
        q: asyncio.Queue = asyncio.Queue()
        self._clients.add(q)
        try:
            def ev(name, data):
                return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode()
            await resp.write(ev("config", self._config))
            await resp.write(ev("progress", self._progress))
            for m in list(self._recent):
                await resp.write(ev("msg", {**m, "old": True, "age": time.time() - m.get("_t", time.time())}))
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), 20)
                except asyncio.TimeoutError:
                    line = ": ping\n\n"
                if line is None:
                    break
                await resp.write(line.encode())
        except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
            pass
        finally:
            self._clients.discard(q)
        return resp

    async def _img(self, request):
        url = request.query.get("u", "")
        if not url.startswith(("http://", "https://")):
            raise web.HTTPBadRequest()
        if url not in self._allowed:
            raise web.HTTPForbidden()           # only images that were shown in chat
        route = self._allowed[url] or None      # the channel's own route, not the client's
        path = CACHE_DIR / hashlib.sha1(url.encode("utf-8")).hexdigest()
        data = None
        if path.exists():
            data = path.read_bytes()
        else:
            sess = self._sessions.get(route or "")
            if sess is None or sess.closed:
                sess = aiohttp.ClientSession(connector=make_tcp_connector(route),
                                             headers={"User-Agent": UA},
                                             timeout=aiohttp.ClientTimeout(total=20))
                self._sessions[route or ""] = sess
            try:
                async with sess.get(url) as r:
                    if r.status != 200:
                        raise web.HTTPNotFound()
                    data = await r.read()
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except web.HTTPException:
                raise
            except Exception:
                raise web.HTTPBadGateway()
        return web.Response(body=data, content_type=_sniff(data),
                            headers={"Cache-Control": "max-age=86400"})

    async def _logo(self, request):
        name = Path(request.match_info["name"]).name
        p = self.logo_dir / name
        if not p.exists():
            raise web.HTTPNotFound()
        return web.Response(body=p.read_bytes(), content_type="image/png",
                            headers={"Cache-Control": "max-age=86400"})

    def _fonts_then_config(self):
        fonts.build_index()
        if self._config:
            self.publish("config", self._config)

    def _with_font(self, cfg: dict) -> dict:
        """Attach the chosen font's files so the page can load them with @font-face."""
        if not hasattr(self, "_font_files"):
            self._font_files = {}
        files = []
        for path, weight, style in fonts.resolve(cfg.get("font_family", "")):
            key = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
            self._font_files[key] = path
            files.append({"url": f"/font/{key}", "weight": weight, "style": style})
        cfg["font_files"] = files
        return cfg

    async def _font(self, request):
        path = getattr(self, "_font_files", {}).get(request.match_info["key"])
        if not path or not Path(path).exists():
            raise web.HTTPNotFound()
        ext = Path(path).suffix.lower()
        return web.Response(body=Path(path).read_bytes(), content_type=fonts.MIME.get(ext, "font/ttf"),
                            headers={"Cache-Control": "max-age=86400", "Access-Control-Allow-Origin": "*"})

    async def _icon(self, request):
        name = Path(request.match_info["name"]).stem
        data = self.icons.get(name)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type="image/png",
                            headers={"Cache-Control": "max-age=86400"})


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>RetChat overlay</title>
<style>
:root{--font:'Segoe UI',sans-serif;--size:16px;--text:#e6e8ef;--user:#7cc4ff;--muted:#a0a4b8;
      --bg:rgba(0,0,0,0);--barh:22px;--barfont:12px;--gap:4px}
html,body{margin:0;padding:0;background:transparent;overflow:hidden;font-family:var(--font);
          font-size:var(--size);color:var(--text)}
#wrap{position:fixed;inset:0;display:flex;flex-direction:column;padding:8px;box-sizing:border-box}
#bars{display:flex;flex-direction:column;gap:6px;margin-bottom:8px}
.bar{position:relative;height:var(--barh);border-radius:calc(var(--barh)/2);background:rgba(20,22,32,.78);
     border:1px solid color-mix(in srgb,var(--c) 45%,transparent);overflow:visible}
.fill{position:absolute;left:0;top:0;bottom:0;border-radius:inherit;width:0;
      background:linear-gradient(90deg,color-mix(in srgb,var(--c) 75%,#000),color-mix(in srgb,var(--c) 70%,#fff));
      transition:width .45s cubic-bezier(.2,.8,.2,1)}
.fill::after{content:"";position:absolute;left:3px;right:3px;top:1px;height:45%;border-radius:inherit;
             background:rgba(255,255,255,.14)}
.label{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-weight:700;
       font-size:var(--barfont);color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.7);white-space:nowrap}
.bar.glow{animation:glow .7s ease-in-out 3}
.bar.glow .fill{width:100%!important;transition:width .25s}
@keyframes glow{0%,100%{box-shadow:0 0 4px var(--c)}50%{box-shadow:0 0 18px 6px var(--c),0 0 36px 10px var(--c)}}
#chat{flex:1;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden;
      background:var(--bg);border-radius:10px;padding:6px 12px}
.row{display:flex;align-items:flex-start;gap:8px;margin-top:calc(var(--gap) + 6px);max-width:100%;
     align-self:flex-start;animation:var(--inanim,fadein) .38s cubic-bezier(.2,.8,.2,1) both}
.row[dir=rtl]{align-self:flex-end}   /* dir=rtl already lays the row out right-to-left: avatar on the right */
body:not(.bubbles) .row{align-self:stretch;margin-top:var(--gap)}
/* fade-out is an animation so it replaces the held slide-in animation (a plain opacity
   change would be overridden by it and the message would just vanish) */
.row.out{animation:fadeout .8s ease forwards}
@keyframes fadeout{from{opacity:1}to{opacity:0}}
@keyframes inL{from{opacity:0;transform:translateX(-80px)}to{opacity:1;transform:none}}
@keyframes inR{from{opacity:0;transform:translateX(80px)}to{opacity:1;transform:none}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@keyframes noanim{from{opacity:1}to{opacity:1}}
.avatar{--av:calc(var(--size) * 2.4);width:var(--av);height:var(--av);border-radius:50%;object-fit:cover;
        flex:none;border:1px solid var(--bc,#3a4158);box-sizing:border-box;background:#2a3046;
        display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;
        font-size:calc(var(--av) * .45);overflow:hidden}
body:not(.bubbles) .avatar{--av:calc(var(--size) * 1.6)}
body.noav .avatar{display:none}
.msg{line-height:1.45;overflow-wrap:anywhere;min-width:0;max-width:100%;box-sizing:border-box;
     text-shadow:0 1px 2px rgba(0,0,0,.85)}
.msg img{height:1.45em;vertical-align:middle;margin:0 2px}
.msg img.emote{height:1.9em}
.name{font-weight:700;color:var(--user)}
.head{font-size:calc(var(--ns,.8) * 1em)}
.sep{color:var(--muted)}
.time{font-size:.75em;color:var(--muted);margin:0 6px}
.reply{display:block;font-size:.8em;font-style:italic;color:var(--muted)}
/* compact: one line, optional border */
body:not(.bubbles) .msg{flex:1;border:var(--bw,0px) solid var(--bc,#3a4158);border-radius:6px;padding:0 4px}
body:not(.bubbles) .msg.trig{background:color-mix(in srgb,var(--tc,#7c5cff) 24%,transparent)}
/* bubbles: name tab on top of the message box, one smooth outline */
body.bubbles .msg{display:flex;flex-direction:column;align-items:stretch;text-shadow:none}
/* the box stretches to the message width, which is at least name tab + corner radius, so the
   tab never sticks out past the box (same rule as the app) */
body.bubbles .msg .head{align-self:flex-start;margin-inline-end:var(--radius)}
/* dir=rtl already puts the start on the right, so the name tab sits on the right edge (like the app) */
body.bubbles .msg .sep{display:none}
body.bubbles .msg .head{background:var(--namebg);border:var(--bw,0px) solid var(--bc,#3a4158);border-bottom:none;
     border-radius:min(var(--radius),12px) min(var(--radius),12px) 0 0;padding:3px 10px 4px;
     position:relative;z-index:1;margin-bottom:calc(-1 * var(--bw,0px));white-space:nowrap;max-width:100%;
     overflow:hidden;text-overflow:ellipsis;box-sizing:border-box}
body.bubbles .msg .box{background:var(--bubble);border:var(--bw,0px) solid var(--bc,#3a4158);
     border-radius:var(--radius);border-top-left-radius:0;padding:6px 12px;box-sizing:border-box;max-width:100%}
body.bubbles .msg[dir=rtl] .box{border-top-left-radius:var(--radius);border-top-right-radius:0}
body.bubbles .msg.trig .head,body.bubbles .msg.trig .box{border-color:var(--tc)}
body.bubbles .msg.trig{filter:drop-shadow(0 0 4px var(--tc)) drop-shadow(0 0 8px var(--tc));
     animation:tglow .8s ease-in-out .38s 3}
@keyframes tglow{50%{filter:drop-shadow(0 0 8px var(--tc)) drop-shadow(0 0 18px var(--tc))}}
/* special effects for subscribers / VIP / OG */
.msg.fx-glow{filter:drop-shadow(0 0 4px var(--fxc)) drop-shadow(0 0 8px var(--fxc))}
/* glow-type effects also tint the outline, like the app */
body.bubbles .msg.fx-glow .head,body.bubbles .msg.fx-glow .box,body.bubbles .msg.fx-pulse .head,
body.bubbles .msg.fx-pulse .box,body:not(.bubbles) .msg.fx-glow,body:not(.bubbles) .msg.fx-pulse
  {border-color:color-mix(in srgb,var(--fxc) 85%,transparent)}
body.bubbles .msg.fx-rainbow .head,body.bubbles .msg.fx-rainbow .box,body:not(.bubbles) .msg.fx-rainbow
  {animation:fxborder 6s linear infinite}
.msg.fx-pulse{animation:fxpulse 2s ease-in-out infinite}
@keyframes fxpulse{0%,100%{filter:drop-shadow(0 0 1px var(--fxc))}50%{filter:drop-shadow(0 0 7px var(--fxc)) drop-shadow(0 0 12px var(--fxc))}}
.msg.fx-rainbow{animation:fxrain 6s linear infinite}
@keyframes fxrain{0%,100%{filter:drop-shadow(0 0 6px #ff4d4d)}17%{filter:drop-shadow(0 0 6px #ffb84d)}
  33%{filter:drop-shadow(0 0 6px #e8ff4d)}50%{filter:drop-shadow(0 0 6px #4dff88)}
  67%{filter:drop-shadow(0 0 6px #4dc3ff)}83%{filter:drop-shadow(0 0 6px #b84dff)}}
body.bubbles .msg.fx-rborder .head,body.bubbles .msg.fx-rborder .box,body:not(.bubbles) .msg.fx-rborder
  {border-width:2px;animation:fxborder 3s linear infinite}
@keyframes fxborder{0%,100%{border-color:#ff4d4d}17%{border-color:#ffb84d}33%{border-color:#e8ff4d}
  50%{border-color:#4dff88}67%{border-color:#4dc3ff}83%{border-color:#b84dff}}
body.bubbles .msg.fx-shine .box,body:not(.bubbles) .msg.fx-shine{position:relative;overflow:hidden}
body.bubbles .msg.fx-shine .box::after,body:not(.bubbles) .msg.fx-shine::after{content:"";position:absolute;
  top:0;bottom:0;width:40%;left:-60%;pointer-events:none;
  background:linear-gradient(105deg,transparent,rgba(255,255,255,.3),transparent);animation:fxshine 3.2s ease-in-out infinite}
@keyframes fxshine{0%{left:-60%}28%,100%{left:120%}}
/* long names: one line with … */
body:not(.bubbles) .name{display:inline-block;max-width:60%;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;vertical-align:bottom}
/* emoji / emote rain */
.drop{position:fixed;top:-60px;pointer-events:none;z-index:10;animation:fall linear forwards;
      font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif;line-height:1}
.drop img{height:100%;display:block}
body.rainonly{background:transparent!important} body.rainonly #wrap{display:none!important}
@keyframes fall{0%{transform:translate(0,0) rotate(0)}85%{opacity:1}
  100%{transform:translate(var(--dx),calc(100vh + 120px)) rotate(var(--rot));opacity:0}}
</style></head><body><div id="wrap"><div id="bars"></div><div id="chat"></div></div>
<script>
const Q=new URLSearchParams(location.search);
const showChat=Q.get('chat')!=='0', showBars=Q.get('bars')!=='0';
const fade=+(Q.get('fade')||0); let maxMsgs=+(Q.get('max')||0)||60;
const RAINONLY=Q.get('rain')==='only', NORAIN=Q.get('rain')==='0';   // separate full-canvas rain source
if(RAINONLY)document.body.classList.add('rainonly');
const chat=document.getElementById('chat'), bars=document.getElementById('bars');
if(!showChat) chat.style.display='none'; if(!showBars) bars.style.display='none';
let cfg={};
function img(src,cls,title,fallback){const i=document.createElement('img');i.src=src;if(cls)i.className=cls;
  if(title)i.title=title;if(fallback)i.onerror=()=>{i.onerror=null;i.src=fallback};return i}
function via(u,p){return '/img?u='+encodeURIComponent(u)+'&p='+encodeURIComponent(p||'')}
function applyCfg(c){cfg=c||{};const r=document.documentElement.style;
  if(c.font_files&&c.font_files.length){            // RetChat sends the font file itself
    let fs=document.getElementById('rcfont');
    if(!fs){fs=document.createElement('style');fs.id='rcfont';document.head.append(fs)}
    fs.textContent=c.font_files.map(f=>`@font-face{font-family:'RetChatFont';src:url('${f.url}');`+
      `font-weight:${f.weight};font-style:${f.style};font-display:block}`).join('');
    r.setProperty('--font',`'RetChatFont','${c.font_family}','Segoe UI',sans-serif`);
  } else if(c.font_family){
    const old=document.getElementById('rcfont'); if(old)old.remove();      // don't keep the previous font
    r.setProperty('--font',`'${c.font_family}','Segoe UI',sans-serif`);
  }
  if(c.font_size)r.setProperty('--size',(c.font_size*1.333).toFixed(1)+'px');
  if(c.color_text)r.setProperty('--text',c.color_text); if(c.color_user)r.setProperty('--user',c.color_user);
  if(c.bar_height)r.setProperty('--barh',c.bar_height+'px'); if(c.bar_font)r.setProperty('--barfont',c.bar_font+'px');
  r.setProperty('--bg',c.bg_rgba||'rgba(0,0,0,0)'); if(c.max_messages&&!Q.get('max'))maxMsgs=c.max_messages;
  r.setProperty('--bubble',c.bubble_rgba||'rgba(29,33,48,.88)'); r.setProperty('--radius',(c.radius??14)+'px');
  document.body.classList.toggle('bubbles',(c.layout||'bubbles')!=='compact');
  r.setProperty('--bw',(c.border_width??0)+'px'); r.setProperty('--bc',c.border_color||'#3a4158');
  r.setProperty('--ns',c.name_scale??.8); r.setProperty('--namebg',c.name_rgba||'rgba(42,48,70,.88)');
  document.body.classList.toggle('noav',c.show_avatars===false)}
function fadeSecs(){return fade>0?fade:(+cfg.fade_after||0)}
function inAnim(m){const a=cfg.anim_in||'side';
  if(m.old||a==='none')return 'noanim'; if(a==='fade')return 'fadein';
  if(a==='right')return 'inR'; if(a==='left')return 'inL';
  return (m.rtl&&document.body.classList.contains('bubbles'))?'inR':'inL'}
const seen=new Set();
function avatarEl(m){
  let a;
  if(m.avatar){a=img(via(m.avatar,m.proxy),'avatar',m.username)}
  else{a=document.createElement('div');a.className='avatar';
    const ch=[...(m.username||'?')].find(c=>/[\p{L}\p{N}]/u.test(c))||'?';a.textContent=ch.toUpperCase();
    if(m.color)a.style.background=`color-mix(in srgb,${m.color} 45%,#111)`}
  return a}
function addMsg(m){
  if(m.id){if(seen.has(m.id))return; seen.add(m.id); if(seen.size>3000)seen.clear()}
  const bubbles=document.body.classList.contains('bubbles');
  const row=document.createElement('div');row.className='row';row.dir=m.rtl?'rtl':'ltr';
  if(m.user_key)row.dataset.uk=m.user_key; if(m.id)row.dataset.mid=m.id;
  const d=document.createElement('div');d.className='msg'+(m.trig?' trig':'');d.dir=m.rtl?'rtl':'ltr';
  if(m.trig)d.style.setProperty('--tc',m.trig_color||'#7c5cff');
  if(m.fx){d.classList.add('fx-'+m.fx);d.style.setProperty('--fxc',m.fxc||'#a78bfa')}
  const replyEl=()=>{const r=document.createElement('span');r.className='reply';
    const b=document.createElement('bdi');b.textContent=(m.reply.user?'@'+m.reply.user+': ':'')+(m.reply.text||'').slice(0,70);
    r.append('↪ ',b);return r};
  const hasReply=m.reply&&(m.reply.user||m.reply.text);
  const head=document.createElement('span');head.className='head';
  if(cfg.show_platform!==false&&m.platform)head.append(img('/logo/'+m.platform+'.png','plat',m.platform));
  if(cfg.show_badges!==false)for(const b of m.badges||[]){
    const fb=b.icon?'/icon/'+b.icon+'.png':null;
    if(b.url)head.append(img(via(b.url,m.proxy),'badge',b.title,fb)); else if(fb)head.append(img(fb,'badge',b.title))}
  const n=document.createElement('bdi');n.className='name';n.textContent=m.username||'?';
  if(m.color)n.style.color=m.color; head.append(n);
  if(bubbles&&cfg.show_time){const tm=document.createElement('span');tm.className='time';
    tm.textContent=new Date().toTimeString().slice(0,5);head.append(tm)}
  const t=document.createElement('bdi');t.className='body';
  for(const p of m.parts||[]){if(p.type==='text')t.append(p.text);
    else if(p.type==='emote'){const e=img(via(p.url,m.proxy),'emote',p.name);e.alt=p.name||'';t.append(e)}}
  if(bubbles){
    const box=document.createElement('div');box.className='box';
    if(hasReply)box.append(replyEl());
    box.append(t);d.append(head,box);
  }else{
    if(hasReply)d.append(replyEl());
    const s=document.createElement('span');s.className='sep';s.textContent=': ';
    d.append(head,s,t);
  }
  row.append(avatarEl(m),d);
  row.style.setProperty('--inanim',inAnim(m));
  // FLIP: remember where the others are, add the row, then glide them to their new place
  const others=[...chat.children], before=new Map(others.map(k=>[k,k.getBoundingClientRect().top]));
  chat.append(row);
  while(chat.children.length>maxMsgs)chat.firstChild.remove();
  if(!m.old&&(cfg.anim_in||'side')!=='none')for(const k of others){if(!k.isConnected)continue;
    const dy=before.get(k)-k.getBoundingClientRect().top;
    if(Math.abs(dy)>0.5)k.animate([{transform:`translateY(${dy}px)`},{transform:'none'}],{duration:260,easing:'ease-out'})}
  const fs=fadeSecs();
  if(fs>0){const left=m.old?Math.max(0,fs-(m.age||0)):fs;
    setTimeout(()=>{row.classList.add('out');setTimeout(()=>row.remove(),900)},left*1000)}
}
function setAvatar(a){
  for(const row of chat.querySelectorAll('.row')){
    if(row.dataset.uk!==a.user_key)continue;
    const old=row.querySelector('.avatar');
    if(old&&old.tagName!=='IMG')old.replaceWith(img(via(a.avatar,a.proxy),'avatar',''))}}
function renderBars(list){
  const ids=new Set(list.map(b=>b.id));
  for(const el of [...bars.children]) if(!ids.has(el.dataset.id)) el.remove();
  list.forEach((b,i)=>{let el=bars.querySelector(`[data-id="${b.id}"]`);
    if(!el){el=document.createElement('div');el.className='bar';el.dataset.id=b.id;
      el.innerHTML='<div class="fill"></div><div class="label"></div>';bars.append(el)}
    el.style.setProperty('--c',b.color||'#7c5cff');
    el.querySelector('.fill').style.width=Math.min(100,100*b.acc/Math.max(1,b.threshold))+'%';
    el.querySelector('.label').textContent=b.label;
    if(bars.children[i]!==el)bars.insertBefore(el,bars.children[i])})}
function celebrate(id){const el=bars.querySelector(`[data-id="${id}"]`);if(!el)return;
  el.classList.remove('glow');void el.offsetWidth;el.classList.add('glow');
  setTimeout(()=>el.classList.remove('glow'),2200)}
function rain(r){
  if(NORAIN||(!RAINONLY&&cfg.rain_in_chat===false))return;
  const big=RAINONLY?Math.max(1,Math.min(3,innerHeight/600)):1;      // bigger drops on a 1080p canvas
  const n=Math.min(220,Math.round((r.amount||28)*(RAINONLY?1.5:1)));
  for(let i=0;i<n;i++){const el=document.createElement('div');el.className='drop';
    const size=(22+Math.random()*24)*big;el.style.left=(Math.random()*96)+'vw';el.style.top=-(size+14)+'px';
    el.style.setProperty('--dx',(Math.random()*80-40)+'px');el.style.setProperty('--rot',(Math.random()*500-250)+'deg');
    el.style.animationDuration=(2.2+Math.random()*1.8)+'s';el.style.animationDelay=(Math.random()*1.4)+'s';
    if(r.url){el.style.height=size+'px';el.append(img(via(r.url,''),'',r.name||''))}
    else{el.style.fontSize=size+'px';el.textContent=r.emoji||''}
    el.addEventListener('animationend',()=>el.remove());document.body.append(el)}}
function connect(){const es=new EventSource('/events');
  es.addEventListener('rain',e=>rain(JSON.parse(e.data)));
  es.addEventListener('avatar',e=>setAvatar(JSON.parse(e.data)));
  es.addEventListener('config',e=>applyCfg(JSON.parse(e.data)));
  if(!RAINONLY)es.addEventListener('msg',e=>addMsg(JSON.parse(e.data)));
  es.addEventListener('progress',e=>renderBars(JSON.parse(e.data)));
  es.addEventListener('celebrate',e=>celebrate(JSON.parse(e.data).id));
  es.addEventListener('clear',()=>{chat.innerHTML='';seen.clear()});
  es.addEventListener('delete',e=>{const ids=new Set(JSON.parse(e.data).ids||[]);
    for(const row of [...chat.children])if(ids.has(row.dataset.mid))row.remove()});
  es.onerror=()=>{es.close();setTimeout(connect,2000)}}   // keep messages; replays are de-duplicated
connect();
</script></body></html>
"""
