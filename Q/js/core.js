// js/core.js — ЗАМЕНИТЬ ЦЕЛИКОМ
window.AURA = {
  games: {}, state: { user: null, tops: {}, plays: {}, integrity: { ok: true }, me: null },
  settings: { sound: true, music: true, musicVol: 35 }, quality: { dpr: 1.25, pmul: 1, parts: 55 },
  registerGame(g) { this.games[g.id] = g; }, u: {}, api: {}, sfx: null, music: null, bus: null
};
(() => {
  const U = AURA.u;
  U.$ = s => document.querySelector(s); U.$$ = s => [...document.querySelectorAll(s)];
  U.esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  U.fmt = n => String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  U.fmtT = ms => { const s = Math.max(0, Math.round(ms / 1000)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  U.relD = ts => { const d = Date.now() - ts; if (d < 6e4) return "только что"; if (d < 36e5) return Math.floor(d / 6e4) + " мин назад"; if (d < 864e5) return Math.floor(d / 36e5) + " ч назад"; if (d < 12096e5) return Math.floor(d / 864e5) + " дн назад"; const t = new Date(ts); return String(t.getDate()).padStart(2, "0") + "." + String(t.getMonth() + 1).padStart(2, "0"); };
  U.clamp = (v, a, b) => v < a ? a : v > b ? b : v; U.lerp = (a, b, t) => a + (b - a) * t;
  U.rand = (a = 1, b) => b === undefined ? Math.random() * a : a + Math.random() * (b - a);
  U.randi = (a, b) => Math.floor(U.rand(a, b + 1)); U.choice = a => a[Math.floor(Math.random() * a.length)];
  U.hueOf = s => { let h = 5381; for (let i = 0; i < s.length; i++) h = (h * 33 ^ s.charCodeAt(i)) >>> 0; return h % 360; };
  U.lerpA = (a, b, t) => a + (((b - a + Math.PI * 3) % (Math.PI * 2)) - Math.PI) * t;
  U.ease = t => 1 - Math.pow(1 - t, 3);
  U.rr = (c, x, y, w, h, r) => { r = Math.min(r, w / 2, h / 2); c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
  U.txt = (c, s, x, y, sz, col, al = "center", w = 700, mono = true) => { c.font = `${w} ${sz}px ${mono ? "Consolas,monospace" : '"Segoe UI",Arial,sans-serif'}`; c.fillStyle = col; c.textAlign = al; c.textBaseline = "middle"; c.fillText(s, x, y); };
  const GLOW = {};
  U.glow = (c, x, y, r, hue, a = 1) => { let g = GLOW[hue]; if (!g) { g = document.createElement("canvas"); g.width = g.height = 64; const q = g.getContext("2d"), gr = q.createRadialGradient(32, 32, 0, 32, 32, 32); gr.addColorStop(0, `hsla(${hue},95%,68%,.85)`); gr.addColorStop(.4, `hsla(${hue},95%,60%,.32)`); gr.addColorStop(1, `hsla(${hue},95%,60%,0)`); q.fillStyle = gr; q.fillRect(0, 0, 64, 64); GLOW[hue] = g; } const pa = c.globalAlpha; c.globalAlpha = pa * a; c.drawImage(g, x - r, y - r, r * 2, r * 2); c.globalAlpha = pa; };
  U.avatar = nick => { const h = U.hueOf(nick); return `<svg viewBox="0 0 64 64" width="100%" height="100%"><rect width="64" height="64" fill="hsl(${h},55%,13%)"/><path d="M14 24L21 5L27 22Z" fill="hsl(${h},70%,45%)"/><path d="M50 24L43 5L37 22Z" fill="hsl(${h},70%,45%)"/><circle cx="32" cy="37" r="19" fill="hsl(${h},45%,26%)"/><rect x="19" y="31" width="10" height="4.5" rx="2" transform="rotate(12 24 33)" fill="hsl(${h},95%,68%)"/><rect x="35" y="31" width="10" height="4.5" rx="2" transform="rotate(-12 40 33)" fill="hsl(${h},95%,68%)"/><path d="M24 47l4-3 4 3 4-3 4 3" stroke="hsl(${h},80%,70%)" stroke-width="2.2" fill="none"/></svg>`; };
  U.DIFFS = ["Лёгкий", "Нормальный", "Хард"];

  async function req(path, method = "GET", body) {
    const opt = { method, credentials: "include", headers: { "X-AURA": "1" } };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt); const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || "Ошибка сервера"); return j;
  }
  AURA.api = { get: p => req(p), post: (p, b) => req(p, "POST", b), del: p => req(p, "DELETE") };

  const Bus = {
    ctx: null, master: null, sfx: null, music: null,
    init() { if (this.ctx) return true; try { const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return false; this.ctx = new AC(); this.master = this.ctx.createGain(); this.master.gain.value = .9; this.master.connect(this.ctx.destination); this.sfx = this.ctx.createGain(); this.sfx.gain.value = .5; this.sfx.connect(this.master); this.music = this.ctx.createGain(); this.music.gain.value = .16; this.music.connect(this.master); return true; } catch (e) { return false; } },
    resume() { if (this.ctx && this.ctx.state === "suspended") this.ctx.resume(); },
    mute(m) { if (this.master) this.master.gain.setTargetAtTime(m ? 0 : .9, this.ctx.currentTime, .03); }
  }; AURA.bus = Bus;

  const Sfx = {
    last: {},
    tone(f0, f1, d, type = "sine", v = .2, dl = 0) { if (!Bus.ctx || !AURA.settings.sound) return; const t = Bus.ctx.currentTime + dl, o = Bus.ctx.createOscillator(), g = Bus.ctx.createGain(); o.type = type; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + d); g.gain.setValueAtTime(v, t); g.gain.exponentialRampToValueAtTime(.0001, t + d); o.connect(g); g.connect(Bus.sfx); o.start(t); o.stop(t + d + .02); },
    noise(d, v = .25, fc = 1200) { if (!Bus.ctx || !AURA.settings.sound) return; const t = Bus.ctx.currentTime, n = Math.floor(Bus.ctx.sampleRate * d), b = Bus.ctx.createBuffer(1, n, Bus.ctx.sampleRate), data = b.getChannelData(0); for (let i = 0; i < n; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / n); const s = Bus.ctx.createBufferSource(); s.buffer = b; const f = Bus.ctx.createBiquadFilter(); f.type = "lowpass"; f.frequency.setValueAtTime(fc, t); f.frequency.exponentialRampToValueAtTime(120, t + d); const g = Bus.ctx.createGain(); g.gain.value = v; s.connect(f); f.connect(g); g.connect(Bus.sfx); s.start(t); },
    play(n) { if (!Bus.ctx || !AURA.settings.sound) return; const now = performance.now(); if (this.last[n] && now - this.last[n] < 40) return; this.last[n] = now; const T = (...a) => this.tone(...a), N = (...a) => this.noise(...a);
      if (n === "ui") T(640, 880, .07, "sine", .12); else if (n === "shoot") { N(.07, .12, 2400); T(300, 120, .08, "sawtooth", .08); } else if (n === "eshoot") T(220, 90, .12, "square", .06); else if (n === "hit") { T(150, 60, .18, "triangle", .3); N(.12, .2, 900); } else if (n === "boom") { N(.35, .35, 1400); T(90, 40, .3, "sine", .35); } else if (n === "bigboom") { N(.6, .45, 900); T(70, 30, .55, "sine", .45); } else if (n === "pop") { T(520, 820, .1, "sine", .18); T(1240, 1600, .08, "sine", .08, .03); } else if (n === "swap") T(340, 420, .06, "sine", .12); else if (n === "bad") T(140, 90, .14, "square", .14); else if (n === "plant") T(240, 300, .08, "triangle", .16); else if (n === "harvest") { T(660, 660, .09, "sine", .18); T(990, 990, .12, "sine", .14, .06); } else if (n === "coin") T(1320, 1760, .09, "sine", .14); else if (n === "ready") T(880, 1100, .1, "sine", .07); else if (n === "tick") T(980, 980, .04, "sine", .06); else if (n === "thit") { T(820, 1240, .07, "sine", .18); N(.05, .08, 3000); } else if (n === "miss") T(160, 80, .16, "square", .12); else if (n === "power") T(520, 1040, .2, "sawtooth", .12); else if (n === "wave") { T(392, 392, .16, "sine", .16); T(494, 494, .16, "sine", .16, .09); T(587, 587, .24, "sine", .16, .18); } else if (n === "over") { T(440, 110, .7, "sawtooth", .16); N(.4, .15, 600); } else if (n === "record") [523, 659, 784, 1046].forEach((f, i) => T(f, f, .18, "sine", .16, i * .09)); }
  }; AURA.sfx = Sfx;

  const Music = {
    playing: false, timer: 0, step: 0, next: 0, vol: .35,
    start() { if (!Bus.init()) return; Bus.resume(); if (this.playing) return; this.playing = true; this.step = 0; this.next = Bus.ctx.currentTime + .05; this.timer = setInterval(() => this.tick(), 90); },
    stop() { this.playing = false; clearInterval(this.timer); this.timer = 0; },
    setVol(v) { this.vol = v; if (Bus.music) Bus.music.gain.setTargetAtTime(v * .45, Bus.ctx.currentTime, .05); },
    midi(m) { return 440 * Math.pow(2, (m - 69) / 12); },
    env(g, t, a, d, p) { g.gain.setValueAtTime(.0001, t); g.gain.exponentialRampToValueAtTime(p, t + a); g.gain.exponentialRampToValueAtTime(.0001, t + d); },
    osc(type, f, t, d, v) { const o = Bus.ctx.createOscillator(), g = Bus.ctx.createGain(), fl = Bus.ctx.createBiquadFilter(); o.type = type; o.frequency.value = f; fl.type = "lowpass"; fl.frequency.value = type === "sawtooth" ? 900 : 2400; this.env(g, t, .02, d, v); o.connect(fl); fl.connect(g); g.connect(Bus.music); o.start(t); o.stop(t + d + .05); },
    kick(t) { const o = Bus.ctx.createOscillator(), g = Bus.ctx.createGain(); o.type = "sine"; o.frequency.setValueAtTime(120, t); o.frequency.exponentialRampToValueAtTime(40, t + .16); this.env(g, t, .005, .18, .4); o.connect(g); g.connect(Bus.music); o.start(t); o.stop(t + .2); },
    hat(t, v = .04) { const n = Bus.ctx.sampleRate * .03, b = Bus.ctx.createBuffer(1, n, Bus.ctx.sampleRate), d = b.getChannelData(0); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n); const s = Bus.ctx.createBufferSource(), f = Bus.ctx.createBiquadFilter(), g = Bus.ctx.createGain(); s.buffer = b; f.type = "highpass"; f.frequency.value = 6000; g.gain.value = v; s.connect(f); f.connect(g); g.connect(Bus.music); s.start(t); },
    snare(t) { this.hat(t, .09); this.osc("triangle", 180, t, .1, .08); },
    tick() { if (!this.playing || !Bus.ctx) return; const ahead = Bus.ctx.currentTime + .25; while (this.next < ahead) { this.schedule(this.step, this.next); this.next += (60 / 84) / 4; this.step = (this.step + 1) % 64; } },
    schedule(st, t) { const bar = Math.floor(st / 16), s = st % 16, roots = [45, 41, 48, 43], root = roots[bar], ch = [0, 3, 7, 10]; if (s === 0) { [0, 3, 7].forEach((iv, i) => this.osc("sawtooth", this.midi(root + iv + 12), t, 3.4, .025 / (i + 1))); this.kick(t); } if (s % 4 === 0) this.osc("sawtooth", this.midi(root), t, .32, .11); if (s % 2 === 0) this.osc("triangle", this.midi(root + 24 + ch[(s / 2) % 4]), t, .13, .05); if (s === 4 || s === 12) this.snare(t); if (s % 2 === 1) this.hat(t); }
  }; AURA.music = Music;

  addEventListener("pointerdown", () => { Bus.init(); Bus.resume(); if (AURA.settings.music) Music.start(); }, { once: false });
  addEventListener("keydown", () => { Bus.init(); Bus.resume(); if (AURA.settings.music) Music.start(); }, { once: true });

  AURA.fx = () => ({
    parts: [], pops: [], shk: 0, hur: 0, ban: "", banT: 0, banHue: 265,
    burst(x, y, h, n = 12, sp = 170, g = 0) { n = Math.round(n * (AURA.quality?.pmul || 1)); for (let i = 0; i < n; i++) { const a = U.rand(Math.PI * 2), v = U.rand(.3, 1) * sp; this.parts.push({ x, y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, t: 0, life: U.rand(.3, .75), r: U.rand(1.5, 3.6), h, g }); } },
    pop(x, y, s, h = 265, size = 17) { this.pops.push({ x, y, s, t: 0, life: .95, h, size }); },
    banner(s, h = 265) { this.ban = s; this.banT = 1.4; this.banHue = h; },
    shake(a) { this.shk = Math.min(14, this.shk + a); }, hurt() { this.hur = .55; },
    update(dt) { this.shk = Math.max(0, this.shk * (1 - 6 * dt)); this.hur = Math.max(0, this.hur - dt); this.banT = Math.max(0, this.banT - dt); for (let i = this.parts.length - 1; i >= 0; i--) { const p = this.parts[i]; p.t += dt; if (p.t >= p.life) { this.parts.splice(i, 1); continue; } p.x += p.vx * dt; p.y += p.vy * dt; p.vy += p.g * dt; p.vx *= 1 - 1.6 * dt; p.vy *= 1 - 1.6 * dt; } for (let i = this.pops.length - 1; i >= 0; i--) { const p = this.pops[i]; p.t += dt; p.y -= 32 * dt; if (p.t >= p.life) this.pops.splice(i, 1); } },
    render(c, W, H) { c.save(); c.globalCompositeOperation = "lighter"; for (const p of this.parts) { c.globalAlpha = 1 - p.t / p.life; c.fillStyle = `hsla(${p.h},95%,66%,1)`; c.beginPath(); c.arc(p.x, p.y, p.r, 0, 7); c.fill(); } c.restore(); c.globalAlpha = 1; for (const p of this.pops) { c.globalAlpha = 1 - p.t / p.life; U.txt(c, p.s, p.x, p.y, p.size, `hsla(${p.h},95%,75%,1)`); } c.globalAlpha = 1; if (this.banT > 0) { c.globalAlpha = Math.min(1, this.banT); U.txt(c, this.ban, W / 2, H * .3, 34, `hsla(${this.banHue},95%,75%,1)`); c.globalAlpha = 1; } if (this.hur > 0) { c.fillStyle = `rgba(255,40,70,${this.hur * .3})`; c.fillRect(0, 0, W, H); } }
  });
})();