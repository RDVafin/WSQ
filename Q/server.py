# server.py — ЗАМЕНИТЬ ЦЕЛИКОМ И ПЕРЕЗАПУСТИТЬ (start.bat)
# Что исправлено:
#  • Твоя база осталась от старой версии (в users не было колонки device) — теперь
#    сервер САМ обновляет структуру базы при запуске, ничего удалять не нужно.
#  • Любая ошибка внутри API теперь отдаёт понятный JSON, а не рвёт соединение
#    (из-за этого в браузере вылезало «Failed to fetch»).
#  • Рекорд сохраняется, даже если /api/run/start не сработал.
import os, re, json, time, hmac, hashlib, secrets, sqlite3, functools, webbrowser, threading, socket, random, traceback
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data"); os.makedirs(DATA, exist_ok=True)
FAN = os.path.join(ROOT, "assets", "fan"); os.makedirs(FAN, exist_ok=True)
DB = os.path.join(DATA, "arcade.db")
KEY_FILE = os.path.join(DATA, "secret.key")
SECRET = open(KEY_FILE, encoding="utf-8").read().strip() if os.path.exists(KEY_FILE) else secrets.token_hex(32)
if not os.path.exists(KEY_FILE): open(KEY_FILE, "w", encoding="utf-8").write(SECRET)

GAMES = ["tanks", "shooter", "match3", "farm", "reflex"]
BASE_PLAYS = {"tanks": 128, "shooter": 96, "match3": 143, "farm": 61, "reflex": 87}
RATE = {}

def now(): return int(time.time() * 1000)
def jdump(o): return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=10); con.row_factory = sqlite3.Row
    try: yield con; con.commit()
    except Exception: con.rollback(); raise
    finally: con.close()

def canon(r): return f'{r["user_id"]}|{r["game"]}|{r["score"]}|{r["diff"]}|{r["dur"]}|{r["created"]}|{jdump(r["counters"])}'
def sign(r): return hmac.new(SECRET.encode(), canon(r).encode(), hashlib.sha256).hexdigest()

def lan_info(port=8000):
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ":" not in ip: ips.add(ip)
    except Exception: pass
    for probe in ("10.255.255.255", "8.8.8.8"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(.4); s.connect((probe, 1)); ips.add(s.getsockname()[0]); s.close()
        except Exception: pass
    def rank(ip):
        if ip.startswith("192.168."): return 0
        if ip.startswith("10."): return 1
        if ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31: return 2
        return 9
    ips = sorted([i for i in ips if not i.startswith("127.")], key=rank) or ["127.0.0.1"]
    return {"ips": ips, "primary": ips[0], "port": port,
            "url": f"http://{ips[0]}:{port}/",
            "alternatives": [f"http://{ip}:{port}/" for ip in ips]}

def write_lan_files(info):
    txt = "AURA//ARCADE — адрес для друга\n\n" + "\n".join("  " + u for u in info["alternatives"]) + "\n\nОба устройства должны быть в одной Wi-Fi/локальной сети.\n"
    open(os.path.join(ROOT, "LAN-ADDRESS.txt"), "w", encoding="utf-8").write(txt)
    open(os.path.join(DATA, "server-info.json"), "w", encoding="utf-8").write(jdump(info))

def migrate_users(c):
    """Старая база (nick/email/salt/pw) → новая (device/nick). Данные и id сохраняются."""
    cols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
    if not cols: return
    if "device" in cols and "email" not in cols: return
    print("  Обновляю структуру базы под версию без паролей…")
    old = [dict(r) for r in c.execute("SELECT * FROM users")]
    c.execute("ALTER TABLE users RENAME TO users_legacy")
    c.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, device TEXT UNIQUE, nick TEXT, created INTEGER, bot INTEGER DEFAULT 0)")
    for r in old:
        uid = r["id"]; nick = (r.get("nick") or f"player_{uid}"); created = r.get("created") or now()
        bot = r.get("bot") or 0
        dev = "legacy_" + hashlib.sha1(f"{uid}:{nick}".encode()).hexdigest()[:16]
        c.execute("INSERT INTO users(id,device,nick,created,bot) VALUES(?,?,?,?,?)", (uid, dev, nick, created, bot))
    c.execute("DROP TABLE users_legacy")
    print(f"  Готово: перенесено профилей — {len(old)}. Рекорды на месте.")

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, device TEXT UNIQUE, nick TEXT, created INTEGER, bot INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS scores(id INTEGER PRIMARY KEY, user_id INTEGER, game TEXT, score INTEGER, diff INTEGER, dur INTEGER, counters TEXT, bot INTEGER DEFAULT 0, created INTEGER, sig TEXT, UNIQUE(user_id, game));
        CREATE TABLE IF NOT EXISTS stats(user_id INTEGER, game TEXT, plays INTEGER DEFAULT 0, ms INTEGER DEFAULT 0, PRIMARY KEY(user_id, game));
        CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, user_id INTEGER, game TEXT, diff INTEGER, issued INTEGER, used INTEGER DEFAULT 0);
        """)
        migrate_users(c)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_device ON users(device)")
        if c.execute("SELECT COUNT(*) n FROM scores").fetchone()["n"] == 0: seed(c)

def seed(c):
    nicks = ["Kage_04","Yukino","Они_77","Aurelia","Синигами","NeoRonin","Мидзу","KuroNeko","Aki_09","VoidFox","Сэнсэй","Hana_04"]
    for game in GAMES:
        for nick in random.sample(nicks, 7):
            dev = "bot_" + hashlib.sha1(nick.encode()).hexdigest()[:12]
            row = c.execute("SELECT id FROM users WHERE device=?", (dev,)).fetchone()
            uid = row["id"] if row else c.execute("INSERT INTO users(device,nick,created,bot) VALUES(?,?,?,1)", (dev, nick, now()-random.randint(2,20)*86400000)).lastrowid
            if game == "tanks":
                diff = random.randint(0,2); dur = random.randint(90,420)*1000; kills = round(dur/1000*random.uniform(.22,.6))
                counters = {"kills":kills,"waves":max(0,kills//random.randint(4,7))}
            elif game == "shooter":
                diff = random.randint(0,2); dur = random.randint(60,300)*1000; waves = int(dur/1000/random.uniform(9,16))
                counters = {"ks":round(dur/1000*random.uniform(.5,1.2)),"kl":waves//3,"waves":waves}
            elif game == "match3":
                diff = 1; dur = 90000; g = round(90*random.uniform(.45,1)); c5 = g//20; c4 = g*3//20
                counters = {"c3":g-c4-c5,"c4":c4,"c5":c5,"casc":int(g*random.uniform(.2,.5)),"rockets":c4//3,"bombs":c5//2,"planes":0}
            elif game == "farm":
                diff = 1; dur = 180000; h = random.randint(18,55); counters = {"harvests":h,"value":h*random.randint(12,20),"planted":h+random.randint(2,8)}
            else:
                diff = 1; dur = 30000; h = random.randint(26,56); counters = {"hits":h,"points":h*random.randint(14,22),"misses":random.randint(2,12),"streak":random.randint(4,14)}
            score = score_of(game, counters); created = now()-random.randint(1,14)*86400000
            rec = {"user_id":uid,"game":game,"score":score,"diff":diff,"dur":dur,"created":created,"counters":counters}
            c.execute("INSERT INTO scores(user_id,game,score,diff,dur,counters,bot,created,sig) VALUES(?,?,?,?,?,?,?,?,?)",
                      (uid,game,score,diff,dur,jdump(counters),1,created,sign(rec)))

def score_of(game, c):
    if game == "tanks": return c["kills"]*100 + c["waves"]*250
    if game == "shooter": return c["ks"]*50 + c["kl"]*120 + c["waves"]*200
    if game == "match3": return c["c3"]*30+c["c4"]*80+c["c5"]*150+c["casc"]*25 + c.get("rockets",0)*70+c.get("bombs",0)*140+c.get("planes",0)*180
    if game == "farm": return c["value"]
    if game == "reflex": return c["points"]
    return 0

def validate(game, c, dur, diff):
    s = dur/1000
    if dur < 1000 or dur > 3600000: return "время вне границ"
    for v in c.values():
        if not isinstance(v, int) or v < 0 or v > 1000000: return "счётчики повреждены"
    if game == "tanks":
        if c["waves"]*3 > c["kills"]: return "волны без убийств"
        if c["kills"] > 4+s*1.6: return "слишком быстрый темп"
    elif game == "shooter":
        if c["kl"] > c["waves"]//3+2: return "лишние тяжёлые"
        if c["ks"]+c["kl"] > s*5+6: return "слишком быстрый темп"
    elif game == "match3":
        t = [120,90,60][diff]; g = c["c3"]+c["c4"]+c["c5"]; sp = c.get("rockets",0)+c.get("bombs",0)+c.get("planes",0)
        if dur < t*1000-3000 or dur > t*1000+8000: return "время вне таймера"
        if g > s*2.4+8: return "слишком много комбо"
        if sp > g+6: return "слишком много усилителей"
        if c["casc"] > g+sp: return "каскады без комбо"
    elif game == "farm":
        t = [210,180,150][diff]
        if dur < t*1000-3000 or dur > t*1000+8000: return "время вне таймера"
        if c["value"] < c["harvests"]*12 or c["value"] > c["harvests"]*24: return "урожай вне границ"
        if c["harvests"] > 12*(s/4.2)+2: return "слишком быстрый урожай"
        if c["planted"] < c["harvests"]: return "собрано больше, чем посажено"
    elif game == "reflex":
        if dur < 24000 or dur > 38000: return "время вне 30 секунд"
        if c["points"] < c["hits"]*10 or c["points"] > c["hits"]*24: return "очки вне границ"
        if c["hits"] > s*2.8+2: return "слишком быстрый темп"
    return True

def rate_ok(ip, key, limit=60, window=60):
    t = time.time(); arr = RATE.setdefault((ip,key), []); arr[:] = [x for x in arr if t-x < window]
    if len(arr) >= limit: return False
    arr.append(t); return True

def read_json(h):
    n = int(h.headers.get("Content-Length","0") or 0)
    if n > 200000: raise ValueError("too big")
    return json.loads(h.rfile.read(n).decode("utf-8") or "{}")

def send_json(h, obj, status=200, cookie=None):
    body = jdump(obj).encode()
    h.send_response(status); h.send_header("Content-Type","application/json; charset=utf-8")
    h.send_header("Content-Length",str(len(body))); h.send_header("Cache-Control","no-store")
    if cookie: h.send_header("Set-Cookie", cookie)
    h.end_headers(); h.wfile.write(body)

def device_token(h):
    ck = SimpleCookie(h.headers.get("Cookie",""))
    return ck["aura_device"].value if "aura_device" in ck else None

def device_cookie(tok): return f"aura_device={tok}; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000"

def get_user(h):
    tok = device_token(h)
    if not tok: return None, None
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE device=?", (tok,)).fetchone()
        return (dict(u) if u else None), tok

def ensure_device(h):
    tok = device_token(h)
    if tok: return tok, False
    return secrets.token_urlsafe(24), True

def public(u):
    if not u: return None
    return {"uid":u["id"],"nick":u["nick"],"created":u["created"],"device":(u["device"] or "")[:8]}

def rows_for(game, diff="all", limit=100):
    with db() as c:
        q = "SELECT s.*,u.nick FROM scores s JOIN users u ON u.id=s.user_id WHERE s.game=?"; args=[game]
        if diff != "all": q += " AND s.diff=?"; args.append(int(diff))
        q += " ORDER BY s.score DESC, s.created ASC LIMIT ?"; args.append(limit)
        rows = c.execute(q,args).fetchall()
    out, dropped = [], 0
    for r in rows:
        rec = {"user_id":r["user_id"],"game":r["game"],"score":r["score"],"diff":r["diff"],"dur":r["dur"],"created":r["created"],"counters":json.loads(r["counters"])}
        if hmac.compare_digest(sign(rec), r["sig"]):
            out.append({"uid":r["user_id"],"nick":r["nick"],"score":r["score"],"diff":r["diff"],"dur":r["dur"],"ts":r["created"],"bot":bool(r["bot"])})
        else: dropped += 1
    return out, dropped

class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js":"text/javascript", ".css":"text/css", ".gif":"image/gif", ".webp":"image/webp", ".svg":"image/svg+xml"}
    def end_headers(self):
        self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Cache-Control","no-cache"); super().end_headers()
    def log_message(self, *a): pass
    def fail(self, e):
        traceback.print_exc()
        try: send_json(self, {"error": "Внутренняя ошибка сервера: " + str(e)}, 500)
        except Exception: pass
    def do_GET(self):
        p = urlparse(self.path).path
        if p.startswith("/api/"):
            try: return self.api_get(p, parse_qs(urlparse(self.path).query))
            except Exception as e: return self.fail(e)
        if p == "/": self.path = "/index.html"
        return super().do_GET()
    def do_POST(self):
        p = urlparse(self.path).path
        if not p.startswith("/api/"): return send_json(self, {"error":"not found"}, 404)
        if self.headers.get("X-AURA") != "1": return send_json(self, {"error":"bad request"}, 400)
        try: d = read_json(self)
        except Exception: return send_json(self, {"error":"bad json"}, 400)
        try: return self.api_post(p, d)
        except Exception as e: return self.fail(e)
    def do_DELETE(self):
        if self.headers.get("X-AURA") != "1": return send_json(self, {"error":"bad request"}, 400)
        try: return self.api_delete(urlparse(self.path).path)
        except Exception as e: return self.fail(e)

    def api_get(self, p, q):
        if p == "/api/ping": return send_json(self, {"ok": True})
        if p == "/api/lan": return send_json(self, lan_info(self.server.server_address[1]))
        if p == "/api/fan":
            files = [f for f in os.listdir(FAN) if f.lower().endswith((".gif",".webp",".png",".jpg",".jpeg"))]
            return send_json(self, {"files": files})
        if p == "/api/me":
            u, tok = get_user(self)
            if tok: return send_json(self, {"user": public(u)})
            return send_json(self, {"user": None}, cookie=device_cookie(secrets.token_urlsafe(24)))
        if p == "/api/bootstrap":
            tops, plays, dropped = {}, {}, 0
            with db() as c:
                for g in GAMES:
                    rows, d = rows_for(g, "all", 3); tops[g] = rows; dropped += d
                    n = c.execute("SELECT COALESCE(SUM(plays),0) n FROM stats WHERE game=?", (g,)).fetchone()["n"]
                    plays[g] = BASE_PLAYS[g] + n
            return send_json(self, {"tops":tops, "plays":plays, "integrity":{"ok":dropped==0,"dropped":dropped}})
        if p == "/api/leaderboard":
            g = q.get("game",["tanks"])[0]
            if g not in GAMES: return send_json(self, {"error":"unknown game"}, 400)
            rows, dropped = rows_for(g, q.get("diff",["all"])[0], 100)
            return send_json(self, {"rows":rows, "integrity":{"ok":dropped==0,"dropped":dropped}})
        return send_json(self, {"error":"not found"}, 404)

    def api_post(self, p, d):
        ip = self.client_address[0]
        if p == "/api/me":
            nick = re.sub(r"\s+", " ", str(d.get("nick","")).strip())
            if not re.fullmatch(r"[\wА-Яа-яЁё\- ]{2,18}", nick): return send_json(self, {"error":"Ник: 2–18 символов, буквы/цифры/_"}, 400)
            tok, is_new = ensure_device(self)
            with db() as c:
                row = c.execute("SELECT * FROM users WHERE device=?", (tok,)).fetchone()
                if row:
                    c.execute("UPDATE users SET nick=? WHERE device=?", (nick, tok)); uid = row["id"]; created = row["created"]
                else:
                    uid = c.execute("INSERT INTO users(device,nick,created,bot) VALUES(?,?,?,0)", (tok,nick,now())).lastrowid; created = now()
            return send_json(self, {"user":{"uid":uid,"nick":nick,"created":created,"device":tok[:8]}}, cookie=device_cookie(tok) if is_new else None)
        if p == "/api/run/start":
            u, tok = get_user(self); g = d.get("game"); diff = int(d.get("diff",1))
            if g not in GAMES or diff not in (0,1,2): return send_json(self, {"error":"bad game"}, 400)
            rid = secrets.token_urlsafe(18)
            with db() as c: c.execute("INSERT INTO runs(run_id,user_id,game,diff,issued) VALUES(?,?,?,?,?)", (rid, u["id"] if u else None, g, diff, now()))
            return send_json(self, {"run_id":rid})
        if p == "/api/run/finish":
            if not rate_ok(ip,"finish",60): return send_json(self, {"saved":False,"reason":"слишком много отправок, подожди минуту"})
            u, tok = get_user(self)
            if not u: return send_json(self, {"saved":False, "reason":"nick"})
            counters = d.get("counters"); dur = int(d.get("duration_ms",0))
            if not isinstance(counters, dict): return send_json(self, {"saved":False,"reason":"bad counters"})
            rid = d.get("run_id"); game = d.get("game"); diff = int(d.get("diff",1))
            with db() as c:
                if rid:
                    run = c.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone()
                    if run and not run["used"]:
                        game, diff = run["game"], run["diff"]
                        c.execute("UPDATE runs SET used=1,user_id=? WHERE run_id=?", (u["id"], rid))
                if game not in GAMES or diff not in (0,1,2): return send_json(self, {"saved":False,"reason":"bad game"})
                v = validate(game, counters, dur, diff)
                if v is not True: return send_json(self, {"saved":False,"reason":v})
                score = score_of(game, counters)
                if score <= 0: return send_json(self, {"saved":False,"reason":"нулевой счёт","score":0})
                old = c.execute("SELECT score FROM scores WHERE user_id=? AND game=?", (u["id"], game)).fetchone()
                improved = not old or score > old["score"]; created = now()
                rec = {"user_id":u["id"],"game":game,"score":score,"diff":diff,"dur":dur,"created":created,"counters":counters}
                if improved:
                    c.execute("""INSERT INTO scores(user_id,game,score,diff,dur,counters,bot,created,sig) VALUES(?,?,?,?,?,?,0,?,?)
                        ON CONFLICT(user_id,game) DO UPDATE SET score=excluded.score,diff=excluded.diff,dur=excluded.dur,counters=excluded.counters,created=excluded.created,sig=excluded.sig""",
                        (u["id"],game,score,diff,dur,jdump(counters),created,sign(rec)))
                c.execute("""INSERT INTO stats(user_id,game,plays,ms) VALUES(?,?,1,?) ON CONFLICT(user_id,game) DO UPDATE SET plays=plays+1,ms=ms+excluded.ms""", (u["id"],game,dur))
            return send_json(self, {"saved":True,"score":score,"improved":improved,"best":max(score, old["score"] if old else 0)})
        return send_json(self, {"error":"not found"}, 404)

    def api_delete(self, p):
        if p == "/api/my/scores":
            u, _ = get_user(self)
            if not u: return send_json(self, {"error":"сначала выбери ник"}, 400)
            with db() as c: c.execute("DELETE FROM scores WHERE user_id=? AND bot=0", (u["id"],))
            return send_json(self, {"ok":True})
        return send_json(self, {"error":"not found"}, 404)

def main():
    init_db()
    for port in range(8000, 8030):
        try: httpd = ThreadingHTTPServer(("0.0.0.0", port), functools.partial(Handler, directory=ROOT)); httpd.daemon_threads = True; break
        except OSError: continue
    else: print("Нет свободного порта 8000–8029"); return
    info = lan_info(port); write_lan_files(info)
    print("=" * 64)
    print("  AURA//ARCADE запущена")
    print(f"  У тебя:    http://127.0.0.1:{port}/")
    for u in info["alternatives"]: print(f"  Для друга: {u}")
    print("  Адрес также сохранён в файл LAN-ADDRESS.txt")
    print("  Если друг не подключается — разреши Python в брандмауэре (частная сеть).")
    print("  Стоп: Ctrl+C")
    print("=" * 64)
    threading.Timer(.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    try: httpd.serve_forever()
    except KeyboardInterrupt: pass
    finally: httpd.server_close(); print("\nОстановлено.")

if __name__ == "__main__": main()