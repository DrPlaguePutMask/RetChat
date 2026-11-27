"""English / Persian (فارسی) interface text.

Widgets are built with English text; ``translate_tree`` swaps every label,
button, tooltip, placeholder, tab and combo-box item for its Persian version
when the language is Persian.  Text that changes at run time goes through
``T("…")``.
"""

from __future__ import annotations

LANG = "en"            # "en" | "fa"

LANGUAGES = (("en", "English"), ("fa", "فارسی"))

FA = {
    # ── window / header ──
    "Live chat": "چت زنده",
    "Open a transparent always-on-top chat overlay": "باز کردن پنجره‌ی شفاف چت که همیشه روی بقیه می‌ماند",
    "⧉  Overlay": "⧉  اورلی",
    "⧉  Close overlay": "⧉  بستن اورلی",
    "Lock overlay (click-through)": "قفل اورلی (کلیک‌ها به بازی زیرش می‌رسد)",
    "Save chat as JSON": "ذخیره‌ی چت به‌صورت JSON",
    "Clear chat": "پاک کردن چت",
    "v{v} · by DrPlague & R3sTivE": "نسخه‌ی {v} · ساخته‌ی DrPlague و R3sTivE",
    "Games that run as administrator ignore key presses from normal apps. Restart RetChat with admin rights so keys reach them.":
        "بازی‌هایی که با دسترسی ادمین اجرا می‌شوند کلیدهای برنامه‌های معمولی را نادیده می‌گیرند. RetChat را با دسترسی ادمین دوباره اجرا کنید تا کلیدها به بازی برسند.",
    "🛡  Run as admin": "🛡  اجرا با دسترسی ادمین",
    "Admin ✓": "ادمین ✓",
    "Running as administrator – can send keys to any game": "با دسترسی ادمین اجرا شده – می‌تواند به هر بازی کلید بفرستد",
    "Language": "زبان",
    "Restart RetChat to switch the language?": "برای تغییر زبان، RetChat دوباره اجرا شود؟",
    "Channels": "کانال‌ها",
    "Triggers": "تریگرها",
    "Appearance": "ظاهر",
    # ── appearance ──
    "Font": "فونت",
    "Size": "اندازه",
    "Layout": "چیدمان",
    "Theme": "تم",
    "Only fade in the overlay and OBS (keep all messages in the app)": "فقط در اورلی و OBS محو شود (همه‌ی پیام‌ها در برنامه بمانند)",
    "Copy message": "کپی پیام",
    "Copy text": "کپی متن",
    "Copy link": "کپی لینک",
    "Open link": "باز کردن لینک",
    "Special effects": "جلوه‌های ویژه",
    "Subscribers, VIPs and OG users can get an effect on their messages. Pick one per site.":
        "پیام مشترک‌ها، VIPها و کاربران OG می‌تواند جلوه‌ی ویژه داشته باشد. برای هر سایت یکی انتخاب کنید.",
    "Sub": "مشترک",
    "OG": "OG",
    "None": "هیچ",
    "Glow": "درخشش",
    "Pulse": "تپش",
    "Rainbow glow": "درخشش رنگین‌کمانی",
    "Rainbow border": "حاشیه‌ی رنگین‌کمانی",
    "Shine": "برق",
    "Midnight": "نیمه‌شب",
    "Neon": "نئون",
    "Ocean": "اقیانوس",
    "Forest": "جنگل",
    "Sunset": "غروب",
    "Rose": "رز",
    "Gold": "طلایی",
    "Light": "روشن",
    "Glass": "شیشه‌ای",
    "Bubbles – name on top, rounded": "حبابی – نام بالای پیام، گوشه‌گرد",
    "Compact – one line per message": "فشرده – هر پیام یک خط",
    "Message colour": "رنگ متن پیام",
    "Name colour": "رنگ نام",
    "Message background": "پس‌زمینه‌ی پیام",
    "Name background": "پس‌زمینه‌ی نام",
    "Message border": "حاشیه‌ی پیام",
    "Chat area background": "پس‌زمینه‌ی کل چت",
    "Message opacity": "شفافیت پیام",
    "Chat area opacity": "شفافیت کل چت",
    "Name size": "اندازه‌ی نام",
    "Size of the user name compared with the message text": "اندازه‌ی نام کاربر نسبت به متن پیام",
    "Corner roundness": "گردی گوشه‌ها",
    "Border thickness": "ضخامت حاشیه",
    "New message": "پیام جدید",
    "How new messages appear. Older messages glide up to make room.": "پیام‌های جدید چطور ظاهر شوند. پیام‌های قبلی نرم بالا می‌روند تا جا باز شود.",
    "Slide in from its side": "ورود از سمت خودش",
    "Slide in from the right": "ورود از راست",
    "Slide in from the left": "ورود از چپ",
    "Fade in": "ظاهر شدن تدریجی",
    "No animation": "بدون انیمیشن",
    "Fade out after": "محو شدن بعد از",
    "Each message fades out this many seconds after it appears (0 = never)": "هر پیام این‌قدر ثانیه بعد از ظاهر شدن محو می‌شود (۰ = هرگز)",
    "never": "هرگز",
    " s": " ثانیه",
    " ms": " میلی‌ثانیه",
    "Text direction": "جهت متن",
    "Automatic per message": "خودکار برای هر پیام",
    "Right-to-left (Persian)": "راست به چپ (فارسی)",
    "Left-to-right": "چپ به راست",
    "Messages shown": "تعداد پیام‌های نمایش‌داده‌شده",
    "Only the newest this-many messages are shown, e.g. 5": "فقط همین تعداد از جدیدترین پیام‌ها نشان داده می‌شود، مثلاً ۵",
    "Use each viewer's name colour": "استفاده از رنگ نام هر بیننده",
    "Show platform icon": "نمایش آیکون پلتفرم",
    "Show badges": "نمایش نشان‌ها",
    "Show time": "نمایش زمان",
    "Show messages sent before connecting": "نمایش پیام‌های قبل از اتصال",
    "Show bot messages": "نمایش پیام‌های ربات",
    "Show profile pictures": "نمایش عکس پروفایل",
    "Glow on messages that count toward a trigger": "درخشش پیام‌هایی که برای تریگر امتیاز می‌دهند",
    "Animate GIF emotes": "متحرک بودن ایموت‌های GIF",
    "Emoji rain": "باران ایموجی",
    "Rain the emoji / GIF emote of a message over the chat": "باریدن ایموجی یا ایموت GIF پیام روی چت",
    "Only for messages that count toward a trigger": "فقط برای پیام‌هایی که برای تریگر امتیاز می‌دهند",
    "Amount": "تعداد",
    "Wait between rains": "فاصله بین باران‌ها",
    "Bot names": "نام ربات‌ها",
    "Names treated as bots (comma separated). Names of 7+ letters ending in 'bot' and platform-marked bots are detected automatically.":
        "نام‌هایی که ربات حساب می‌شوند (با کاما جدا کنید). نام‌های ۷ حرفی یا بیشتر که به bot ختم می‌شوند و ربات‌هایی که پلتفرم مشخص کرده خودکار شناخته می‌شوند.",
    "Progress bars": "نوارهای پیشرفت",
    "Each trigger's bar colour is set in the trigger editor (✎).": "رنگ نوار هر تریگر در ویرایشگر تریگر (✎) تنظیم می‌شود.",
    "Bar height": "ارتفاع نوار",
    "Bar text size": "اندازه‌ی متن نوار",
    "OBS browser source": "منبع مرورگر OBS",
    "Serve chat as a web page, port": "نمایش چت به‌صورت صفحه‌ی وب، پورت",
    "Listen on your network address instead of only this PC, so a streaming PC on the same Wi-Fi/LAN can open the page.":
        "به‌جای فقط همین کامپیوتر، روی آدرس شبکه هم در دسترس باشد تا کامپیوتر استریم در همان وای‌فای/شبکه صفحه را باز کند.",
    "Allow other PCs on my network (OBS on another PC)": "اجازه به کامپیوترهای دیگر شبکه (OBS روی کامپیوتر دیگر)",
    "This PC's address": "آدرس این کامپیوتر",
    "Pick the address on the same network as the OBS computer (usually 192.168.x.x)": "آدرسی را انتخاب کنید که در همان شبکه‌ی کامپیوتر OBS است (معمولاً 192.168.x.x)",
    "Adds a Windows Firewall rule allowing this port on private networks (asks for administrator permission)":
        "یک قانون فایروال ویندوز برای این پورت در شبکه‌های خصوصی اضافه می‌کند (دسترسی ادمین می‌خواهد)",
    "Open firewall": "باز کردن فایروال",
    "Chat + bars": "چت + نوارها",
    "Copy": "کپی",
    "Chat only": "فقط چت",
    "Bars only": "فقط نوارها",
    "In OBS add a Browser source, paste the URL, size e.g. 400×600. Add &fade=30 to hide messages after 30 s.":
        "در OBS یک Browser source اضافه کنید، آدرس را بچسبانید، اندازه مثلاً ۴۰۰×۶۰۰. با اضافه کردن ‎&fade=30‎ پیام‌ها بعد از ۳۰ ثانیه محو می‌شوند.",
    "✓ Copied – in OBS: Sources ▸ + ▸ Browser ▸ paste the URL": "✓ کپی شد – در OBS: Sources ▸ + ▸ Browser ▸ آدرس را بچسبانید",
    "Starting…": "در حال شروع…",
    "Off.": "خاموش.",
    "✓ Running on your network. On the OBS PC: Sources ▸ + ▸ Browser ▸ paste a URL above. If it doesn't load there, click 'Open firewall' and make sure both PCs are on the same network (Windows network type: Private).":
        "✓ روی شبکه‌ی شما فعال است. در کامپیوتر OBS: Sources ▸ + ▸ Browser ▸ یکی از آدرس‌های بالا را بچسبانید. اگر باز نشد، «باز کردن فایروال» را بزنید و مطمئن شوید هر دو کامپیوتر در یک شبکه‌اند (نوع شبکه در ویندوز: Private).",
    "✓ Running – in OBS: Sources ▸ + ▸ Browser ▸ paste a URL above (width 400, height 600 works well). Add &fade=30 to hide old messages.":
        "✓ فعال است – در OBS: Sources ▸ + ▸ Browser ▸ یکی از آدرس‌های بالا را بچسبانید (عرض ۴۰۰ و ارتفاع ۶۰۰ مناسب است). با ‎&fade=30‎ پیام‌های قدیمی محو می‌شوند.",
    "✓ Firewall rule added for port {port} (private networks). Now open the link on the OBS PC.":
        "✓ قانون فایروال برای پورت {port} (شبکه‌های خصوصی) اضافه شد. حالا لینک را در کامپیوتر OBS باز کنید.",
    "✗ Firewall rule not added (permission was declined).": "✗ قانون فایروال اضافه نشد (دسترسی داده نشد).",
    # ── triggers ──
    "●  Triggers ON – key presses will be sent": "●  تریگرها روشن – کلیدها فرستاده می‌شوند",
    "⏸  Triggers PAUSED – click to resume": "⏸  تریگرها متوقف – برای ادامه کلیک کنید",
    "Send keys as": "ارسال کلید به‌صورت",
    "Scan codes (games – recommended)": "اسکن‌کد (بازی‌ها – پیشنهادی)",
    "Virtual keys (desktop apps)": "کلید مجازی (برنامه‌های دسکتاپ)",
    "Off: messages from bots (e.g. RestreamBot relaying another chat) never add points, so relayed words aren't counted twice.":
        "خاموش: پیام ربات‌ها (مثلاً RestreamBot که چت دیگری را بازپخش می‌کند) امتیاز نمی‌دهند تا کلمه‌ها دو بار شمرده نشوند.",
    "Bot messages count toward triggers": "پیام ربات‌ها برای تریگرها حساب شود",
    "Ticking a group's Active box un-ticks all other groups": "فعال کردن یک گروه، بقیه‌ی گروه‌ها را غیرفعال می‌کند",
    "Only one group active at a time (e.g. switch game)": "فقط یک گروه در هر لحظه فعال باشد (مثلاً عوض کردن بازی)",
    "No triggers yet. A trigger presses a key when chat types a word enough times.": "هنوز تریگری نیست. تریگر وقتی چت یک کلمه را به اندازه‌ی کافی بنویسد یک کلید را فشار می‌دهد.",
    "Show / hide this group's triggers": "نمایش / پنهان کردن تریگرهای این گروه",
    "Active: this group's triggers count points, press keys and show bars.\nInactive: they are ignored and their bars are hidden.":
        "فعال: تریگرهای این گروه امتیاز می‌شمارند، کلید می‌زنند و نوار نشان می‌دهند.\nغیرفعال: نادیده گرفته می‌شوند و نوارشان پنهان است.",
    "General": "عمومی",
    "{n} trigger": "{n} تریگر",
    "{n} triggers": "{n} تریگر",
    "Add a trigger to this group": "افزودن تریگر به این گروه",
    "Rename group": "تغییر نام گروه",
    "Delete group": "حذف گروه",
    "   No triggers in this group yet – click + on the group.": "   هنوز تریگری در این گروه نیست – روی + گروه کلیک کنید.",
    "Enable / disable this trigger": "فعال / غیرفعال کردن این تریگر",
    "Test: press this key in 3 s": "آزمایش: این کلید ۳ ثانیه بعد زده می‌شود",
    "Edit": "ویرایش",
    "Delete": "حذف",
    "+  Add trigger": "+  افزودن تریگر",
    "+  New group": "+  گروه جدید",
    "Reset points": "صفر کردن امتیازها",
    "Activity": "فعالیت‌ها",
    "Group is inactive": "گروه غیرفعال است",
    "Trigger is disabled": "تریگر غیرفعال است",
    "cooldown {s}s": "استراحت {s} ثانیه",
    "fired {n}×": "{n} بار اجرا شد",
    "New group": "گروه جدید",
    "Group name (e.g. CS GO, Valorant):": "نام گروه (مثلاً CS GO یا Valorant):",
    "A group called '{name}' already exists.": "گروهی به نام «{name}» از قبل وجود دارد.",
    "New name:": "نام جدید:",
    "Delete the group '{name}' and its {n} trigger(s)?": "گروه «{name}» و {n} تریگرش حذف شود؟",
    "Delete the empty group '{name}'?": "گروه خالی «{name}» حذف شود؟",
    "Delete trigger": "حذف تریگر",
    "Delete the trigger '{word}' → {key}?": "تریگر «{word}» ← {key} حذف شود؟",
    "Group '{name}' activated": "گروه «{name}» فعال شد",
    "Group '{name}' deactivated": "گروه «{name}» غیرفعال شد",
    "🔑 '{word}' reached {n} → pressing {key}  (last: {who})": "🔑 «{word}» به {n} رسید ← فشردن {key}  (آخرین: {who})",
    "⏸ '{word}' reached {n} but triggers are paused": "⏸ «{word}» به {n} رسید ولی تریگرها متوقف‌اند",
    "Test: pressing {key} in 3 s – switch to your game now": "آزمایش: {key} سه ثانیه دیگر زده می‌شود – حالا به بازی بروید",
    "✓ Pressed {key} at {t}  →  focused window: {w}": "✓ {key} در {t} زده شد  ←  پنجره‌ی فعال: {w}",
    "⚠  '{title}' runs as administrator – Windows will block key presses to it. Click 'Run as admin' (top right).":
        "⚠  «{title}» با دسترسی ادمین اجرا شده – ویندوز کلیدها را به آن نمی‌رساند. «اجرا با دسترسی ادمین» (بالا) را بزنید.",
    # ── channels ──
    "Paste a channel link…": "لینک کانال را اینجا بچسبانید…",
    "Route for the channel you add (can be changed per channel later)": "مسیر اتصال کانالی که اضافه می‌کنید (بعداً برای هر کانال قابل تغییر است)",
    "Direct": "مستقیم",
    "Proxy": "پروکسی",
    "System proxy": "پروکسی سیستم",
    "Add": "افزودن",
    "Proxy server": "سرور پروکسی",
    "Windows has no proxy configured": "پروکسی ویندوز تنظیم نشده",
    "System proxy: off": "پروکسی سیستم: خاموش",
    "System: {p}": "سیستم: {p}",
    "host": "آدرس",
    "Check the proxy can reach the internet": "بررسی اینکه پروکسی به اینترنت وصل است",
    "Test": "آزمایش",
    "Testing {p} …": "در حال آزمایش {p} …",
    "v2ray / xray default: SOCKS5 127.0.0.1:10808 (HTTP 10809). Channels set to Route ▸ Proxy use this.":
        "پیش‌فرض v2ray / xray: ‏SOCKS5 127.0.0.1:10808 (HTTP 10809). کانال‌هایی که مسیرشان «پروکسی» است از این استفاده می‌کنند.",
    "No channels yet. Add one above, then press Connect.": "هنوز کانالی نیست. یکی را بالا اضافه کنید و بعد «اتصال» را بزنید.",
    "Route": "مسیر",
    "How this channel connects:\nDirect – no proxy\nProxy – the proxy server set above (e.g. v2ray 127.0.0.1:10808)\nSystem proxy – Windows proxy settings":
        "این کانال چطور وصل شود:\nمستقیم – بدون پروکسی\nپروکسی – سرور پروکسی تنظیم‌شده در بالا (مثلاً v2ray 127.0.0.1:10808)\nپروکسی سیستم – تنظیمات پروکسی ویندوز",
    "Connect / disconnect": "اتصال / قطع",
    "Connect": "اتصال",
    "Disconnect": "قطع",
    "Remove channel": "حذف کانال",
    "Connect all": "اتصال همه",
    "Disconnect all": "قطع همه",
    "not connected": "وصل نیست",
    "connected": "وصل",
    "{n} msgs": "{n} پیام",
    "{live} connected · {n} msg/min": "{live} وصل · {n} پیام در دقیقه",
    "Connecting…": "در حال اتصال…",
    "Connected": "وصل شد",
    "Connected (stream offline – waiting)": "وصل (استریم خاموش است – منتظر)",
    "Connected (offline)": "وصل (آفلاین)",
    "Disconnected – reconnecting…": "قطع شد – اتصال دوباره…",
    "Connecting via system proxy (automatic)…": "اتصال از طریق پروکسی سیستم (خودکار)…",
    "Connecting via {p}…": "اتصال از طریق {p}…",
    "Channel is not live right now – retrying in 30 s": "کانال الان لایو نیست – ۳۰ ثانیه دیگر دوباره تلاش می‌شود",
    "Chat is disabled for this live stream": "چت این استریم بسته است",
    "No live chat for this video": "این ویدیو چت زنده ندارد",
    "Live stream ended": "استریم تمام شد",
    "Channel not found (404)": "کانال پیدا نشد (404)",
    "⚠  Not a supported link. Use a Twitch, Kick, YouTube, Aparat or OneFa channel URL.":
        "⚠  این لینک پشتیبانی نمی‌شود. لینک کانال Twitch، Kick، YouTube، آپارات یا OneFa بدهید.",
    # ── trigger editor ──
    "New trigger": "تریگر جدید",
    "Edit trigger": "ویرایش تریگر",
    "Group": "گروه",
    "Pick a group or type a new name (e.g. CS GO, Valorant)": "یک گروه انتخاب کنید یا نام جدید بنویسید (مثلاً CS GO یا Valorant)",
    "When chat says…": "وقتی چت بنویسد…",
    "e.g.  gg   or   سلام": "مثلاً  gg   یا   سلام",
    "Whole message equals the word": "کل پیام دقیقاً همین کلمه باشد",
    "Message contains the word": "پیام این کلمه را داشته باشد",
    "Message contains the text anywhere": "پیام این متن را هر جایی داشته باشد",
    "Message starts with the word": "پیام با این کلمه شروع شود",
    "…press": "…این کلید زده شود",
    "Click Record, or type e.g. Ctrl+F1, Space, MouseMiddle": "روی «ضبط» بزنید یا بنویسید، مثلاً Ctrl+F1، Space، MouseMiddle",
    "⏺  Record": "⏺  ضبط",
    "Hold for": "نگه داشتن به مدت",
    "How long the key stays down. Games often need 50–150 ms.": "کلید چه مدت پایین بماند. بازی‌ها معمولاً ۵۰ تا ۱۵۰ میلی‌ثانیه لازم دارند.",
    "Repeat": "تکرار",
    "Switch to your game – the key is pressed after 3 seconds": "به بازی بروید – کلید بعد از ۳ ثانیه زده می‌شود",
    "▶  Test in 3 s": "▶  آزمایش در ۳ ثانیه",
    "Pressing in {n}…": "زدن کلید در {n}…",
    "Who counts, and how much": "چه کسی و چقدر امتیاز می‌دهد",
    "Role": "نقش",
    "Points per message": "امتیاز هر پیام",
    "Moderator": "مدیر",
    "Subscriber": "مشترک",
    "VIP": "VIP",
    "Regular": "عادی",
    "Fire when points reach": "اجرا وقتی امتیاز برسد به",
    "Cooldown after firing": "استراحت بعد از اجرا",
    "Each viewer counts only once per round (stops one person spamming)": "هر بیننده در هر دور فقط یک بار حساب شود (جلوی اسپم یک نفر را می‌گیرد)",
    "Show progress bar above the chat / overlay / OBS": "نمایش نوار پیشرفت بالای چت / اورلی / OBS",
    "Bar colour": "رنگ نوار",
    "Colour of this trigger's progress bar and its glow": "رنگ نوار پیشرفت این تریگر و درخشش آن",
    "On: shot  →  MouseLeft    3 / 10\nOff: shot    3 / 10": "روشن: shot  →  MouseLeft    3 / 10\nخاموش: shot    3 / 10",
    "Show the key on the bar  (off: only the trigger word, e.g. \"shot\")": "نمایش کلید روی نوار  (خاموش: فقط کلمه‌ی تریگر، مثلاً «shot»)",
    "Cancel": "انصراف",
    "Save": "ذخیره",
    "⚠  Allow at least one role": "⚠  حداقل یک نقش را مجاز کنید",
    "Progress bar colour": "رنگ نوار پیشرفت",
    "Press a key": "یک کلید بزنید",
    "Press a key, a key combination,\na mouse button or scroll the wheel…": "یک کلید، ترکیب کلید،\nدکمه‌ی ماوس یا چرخ ماوس را بزنید…",
    "Esc cancels": "Esc برای انصراف",
    # ── overlay ──
    "RetChat overlay": "اورلی RetChat",
    "RetChat overlay – drag to move": "اورلی RetChat – برای جابه‌جایی بکشید",
    "Close overlay": "بستن اورلی",
    # ── chat log lines ──
    "Welcome! Add a channel in the Channels tab, then set up triggers.": "خوش آمدید! در تب «کانال‌ها» یک کانال اضافه کنید و بعد تریگرها را بسازید.",
    "Imported your channels and triggers from RetChat 1.x. Press Connect to start.": "کانال‌ها و تریگرهای شما از RetChat 1.x منتقل شد. برای شروع «اتصال» را بزنید.",
    "Saved {n} messages → {path}": "{n} پیام ذخیره شد ← {path}",
    "Save chat": "ذخیره‌ی چت",
    "Choose colour": "انتخاب رنگ",
    # ── 3.5: trigger actions, screen rain ──
    "…then": "…آن‌وقت",
    "Block keys (they stop working for a while)": "مسدود کردن کلیدها (مدتی کار نمی‌کنند)",
    "Block the whole keyboard": "مسدود کردن کل کیبورد",
    "Block the mouse (movement, buttons, wheel)": "مسدود کردن ماوس (حرکت، دکمه‌ها، چرخ)",
    "Shut down the PC": "خاموش کردن کامپیوتر",
    "For": "به مدت",
    "Shut down after": "خاموش شدن بعد از",
    "Keys to block, e.g.  W   or   W, A, S, D   or   MouseLeft": "کلیدهای مسدود، مثلاً  W   یا   W, A, S, D   یا   MouseLeft",
    "These keys / mouse buttons stop working for the set time. Emergency: press Esc 5 times quickly to unblock everything.": "این کلیدها / دکمه‌های ماوس برای مدت تعیین‌شده کار نمی‌کنند. حالت اضطراری: ۵ بار سریع Esc بزنید تا همه آزاد شوند.",
    "Your whole keyboard stops working for the set time (RetChat's own trigger presses still work). Emergency: press Esc 5 times quickly.": "کل کیبورد برای مدت تعیین‌شده کار نمی‌کند (کلیدهایی که خود RetChat می‌زند کار می‌کنند). حالت اضطراری: ۵ بار سریع Esc بزنید.",
    "Mouse movement, buttons and wheel stop working for the set time. Emergency: press Esc 5 times quickly.": "حرکت، دکمه‌ها و چرخ ماوس برای مدت تعیین‌شده کار نمی‌کنند. حالت اضطراری: ۵ بار سریع Esc بزنید.",
    "⚠ Windows shuts the PC down after the delay – unsaved work is lost. RetChat shows a window where you can cancel it. Use a high threshold!": "⚠ ویندوز بعد از این مدت کامپیوتر را خاموش می‌کند – کارهای ذخیره‌نشده از بین می‌روند. RetChat پنجره‌ای برای لغو نشان می‌دهد. حد امتیاز را بالا بگذارید!",
    "Not available for shut down": "برای خاموش کردن در دسترس نیست",
    "Switch to your game – the action happens after 3 seconds": "به بازی بروید – کار بعد از ۳ ثانیه انجام می‌شود",
    "Test: run this trigger in 3 s": "آزمایش: این تریگر ۳ ثانیه بعد اجرا می‌شود",
    "🔑 '{word}' reached {n} → {key}  (last: {who})": "🔑 «{word}» به {n} رسید ← {key}  (آخرین: {who})",
    "Test: {key} in 3 s – switch to your game now": "آزمایش: {key} سه ثانیه دیگر – حالا به بازی بروید",
    "Shut down triggers can't be tested (it would shut down the PC)": "تریگر خاموش کردن قابل آزمایش نیست (کامپیوتر خاموش می‌شود)",
    "⛔ Blocking input: {what}  ·  press Esc 5× to unblock": "⛔ ورودی مسدود است: {what}  ·  برای آزاد کردن ۵ بار Esc بزنید",
    "✗ The focused app runs as administrator – Windows doesn't let RetChat block its input. Restart RetChat as administrator.": "✗ برنامه‌ی فعال با دسترسی ادمین اجرا شده – ویندوز اجازه نمی‌دهد RetChat ورودی آن را مسدود کند. RetChat را با دسترسی ادمین اجرا کنید.",
    "✓ Esc pressed 5× – all input unblocked": "✓ ۵ بار Esc زده شد – همه‌ی ورودی‌ها آزاد شدند",
    "✓ Input unblocked at {t}": "✓ ورودی در {t} آزاد شد",
    "✗ Could not block input (Windows refused the input hook)": "✗ مسدود کردن ورودی ممکن نشد (ویندوز اجازه نداد)",
    "✗ Shut down failed: {e}": "✗ خاموش کردن انجام نشد: {e}",
    "⏻ Shutting down the PC in {s} s (trigger '{word}')": "⏻ کامپیوتر {s} ثانیه دیگر خاموش می‌شود (تریگر «{word}»)",
    "A chat trigger ('{word}') is shutting down this PC in {s} seconds.": "یک تریگر چت («{word}») این کامپیوتر را {s} ثانیه دیگر خاموش می‌کند.",
    "Cancel shut down": "لغو خاموش شدن",
    "Let it shut down": "خاموش شود",
    "✓ Shut down cancelled": "✓ خاموش شدن لغو شد",
    "Also rain over the whole screen": "باران روی کل صفحه‌ی نمایش هم ببارد",
    "Drops fall over your whole monitor, on top of every window (click-through).\nWorks over games in borderless / windowed mode, not exclusive full screen.": "قطره‌ها روی کل مانیتور و بالای همه‌ی پنجره‌ها می‌بارند (کلیک از آن رد می‌شود).\nروی بازی‌های پنجره‌ای / Borderless کار می‌کند، نه تمام‌صفحه‌ی انحصاری.",
    "Drop a test rain now": "همین حالا یک باران آزمایشی",
    "Rain on the OBS chat page too (the OBS \"Rain only\" page always rains)": "باران در صفحه‌ی چت OBS هم ببارد (صفحه‌ی «فقط باران» همیشه می‌بارد)",
    "Rain only": "فقط باران",
    "In OBS add a Browser source, paste the URL, size e.g. 400×600. Add &fade=30 to hide messages after 30 s. For \"Rain only\" use the full canvas size (e.g. 1920×1080) so the emoji rain covers the whole stream.": "در OBS یک منبع Browser اضافه کنید، آدرس را بچسبانید، اندازه مثلاً ۴۰۰×۶۰۰. با &fade=30 پیام‌ها بعد از ۳۰ ثانیه پنهان می‌شوند. برای «فقط باران» اندازه‌ی کل صفحه (مثلاً ۱۹۲۰×۱۰۸۰) را بدهید تا باران کل استریم را بپوشاند.",
}


def T(s: str) -> str:
    """Translate one string (returns it unchanged in English or if unknown)."""
    if LANG == "fa":
        return FA.get(s, s)
    return s


def translate_tree(root) -> None:
    """Swap the English text of *root* and all its child widgets for Persian."""
    if LANG != "fa" or root is None:
        return
    from PyQt6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QLineEdit,
                                 QSpinBox, QTabWidget, QWidget)
    widgets = [root] + root.findChildren(QWidget)
    if root.windowTitle():
        root.setWindowTitle(T(root.windowTitle()))
    for w in widgets:
        if w.property("noTranslate"):
            continue
        tip = w.toolTip()
        if tip:
            w.setToolTip(T(tip))
        if isinstance(w, (QLabel, QAbstractButton)) and w.text():
            w.setText(T(w.text()))
        elif isinstance(w, QLineEdit) and w.placeholderText():
            w.setPlaceholderText(T(w.placeholderText()))
        elif isinstance(w, QComboBox) and not w.isEditable():
            for i in range(w.count()):
                w.setItemText(i, T(w.itemText(i)))
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                w.setTabText(i, T(w.tabText(i)))
        elif isinstance(w, QGroupBox):
            w.setTitle(T(w.title()))
        elif isinstance(w, (QSpinBox, QDoubleSpinBox)):
            if w.specialValueText():
                w.setSpecialValueText(T(w.specialValueText()))
            if w.suffix():
                w.setSuffix(T(w.suffix()))
