/* Capitol Signals – nur noch Dip-Cluster.
   Signal: 2+ Politiker kaufen dieselbe Aktie innerhalb von 30 Tagen, Aktie ≥40 % unter 52-Wochen-Hoch.
   Kauf zum Schlusskurs nach der Meldung, Verkauf nach 30 Tagen. Daten: data/dash.json (signals.py). */
(() => {
"use strict";
let D, META, LAST, DATES, RU;
const PX = new Map(), PXB = new Map(), TR = new Map();
let charts = [];
const S = { show: 25, jf: "alle", jshow: 60, sel: null };
let CAL = null, SIM = null, SIMKEY = "";
// Einstellungen (Journal + Positionsgröße), gespeichert im Browser
// Zwei getrennte Backtests mit eigenen Einstellungen: "sp" = Trades + S&P 500, "tr" = nur Trades (Rest Cash)
const DEFS = { sp: { cap: 10000, risk: 2.5, stop: 25, max: 8, sec: 2, rest: "ma", ma: 100 },
               tr: { cap: 10000, risk: 2.5, stop: 25, max: 8, sec: 2, rest: "cash", ma: 100 } };
const CFGS = { sp: { ...DEFS.sp }, tr: { ...DEFS.tr } };
try {
  const c = JSON.parse(localStorage.getItem("cs-cfg") || "null");
  if (c) Object.assign(CFGS.sp, c); else { const d = Number(localStorage.getItem("cs-depot")); if (d > 0) CFGS.sp.cap = CFGS.tr.cap = d; }
  const t = JSON.parse(localStorage.getItem("cs-cfg-tr") || "null");
  if (t) Object.assign(CFGS.tr, t); else if (c) Object.assign(CFGS.tr, { cap: c.cap, risk: c.risk, stop: c.stop, max: c.max });
} catch (e) {}
if (CFGS.sp.rest === "cash") CFGS.sp.rest = "ma";
CFGS.tr.rest = "cash";
let CFG = CFGS.sp, MODE = "sp";
// Branchen (Yahoo-Sektor) – höchstens CFG.sec offene Trades aus derselben Branche (research/sector.py)
const SEC_DE = { "Technology": "Technologie", "Healthcare": "Gesundheit", "Consumer Cyclical": "Zyklischer Konsum", "Consumer Defensive": "Basiskonsum",
  "Financial Services": "Finanzen", "Industrials": "Industrie", "Energy": "Energie", "Communication Services": "Kommunikation",
  "Basic Materials": "Rohstoffe", "Real Estate": "Immobilien", "Utilities": "Versorger" };
const secOf = t => (D && D.sec || {})[t] || null, secDE = sc => SEC_DE[sc] || sc;
const saveCfg = () => { try { localStorage.setItem("cs-cfg", JSON.stringify(CFGS.sp)); localStorage.setItem("cs-cfg-tr", JSON.stringify(CFGS.tr)); } catch (e) {} };
const posPct = () => Math.min(100, CFG.risk / CFG.stop * 100);
const restTxt = () => CFG.rest === "spy" ? "Zwischen den Trades liegt das freie Geld im S&amp;P 500." : CFG.rest === "ma" ? `Zwischen den Trades liegt das freie Geld im S&amp;P 500, solange er über seinem ${CFG.ma}-Tage-Durchschnitt schließt, sonst als Cash.` : "Zwischen den Trades liegt das Geld als Cash (ohne Zinsen).";
let MAC = { L: 0, v: null };
const spyMA = L => { if (MAC.L === L && MAC.v) return MAC.v; const o = []; let s = 0, n = 0, q = []; for (let k = 0; k < CAL.length; k++) { const x = CAL[k] > 0 ? CAL[k] : (k ? CAL[k - 1] : 0); q.push(x); s += x; if (q.length > L) s -= q.shift(); o.push(s / q.length); } MAC = { L, v: o }; return o; };

// ------------------------------------------------------------------ helpers
const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = v => v == null || isNaN(v) ? "–" : (v > 0 ? "+" : "") + nf1.format(v) + " %";
const cls = v => v == null || isNaN(v) ? "mut" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const pc = v => `<span class="${cls(v)}">${pct(v)}</span>`;
const q = v => v == null ? "–" : nf0.format(v) + " %";
const dDE = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) + "." + s.slice(0, 4) : "–";
const dS = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) + "." : "–";
const usd = v => v == null ? "–" : "$" + nf2.format(v);
const money = v => v >= 1e6 ? "$" + nf1.format(v / 1e6) + " Mio." : v >= 1e3 ? "$" + nf0.format(v / 1e3) + "K" : "$" + nf0.format(v);
const amt = (lo, hi) => { const f = v => v >= 1e6 ? (v / 1e6).toFixed(v % 1e6 ? 1 : 0).replace(".0", "") + "M" : Math.round(v / 1e3) + "K"; if (!hi || hi === lo) return lo ? "$" + f(lo) : "–"; return "$" + f(lo) + "–" + f(hi); };
const $ = s => document.querySelector(s);
const tok = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const mem = i => D.members[i] || { name: "?" };
const short = n => { const p = String(n).split(/\s+/).filter(w => !/^(Hon\.?|Jr\.?|Sr\.?|II|III|IV|Mr\.?|Mrs\.?|Ms\.?|Dr\.?)$/.test(w)); return p.length > 1 ? p[0] + " " + p[p.length - 1] : n; };
const party = m => m.chamber === "executive" ? "Reg." : (m.party || "I") + (m.state ? "-" + m.state : "");
const pspan = m => `<span class="party ${esc(m.chamber === "executive" ? "E" : m.party || "I")}">${esc(party(m))}</span>`;
const names = (ids, max = 6) => ids.slice(0, max).map(i => esc(short(mem(i).name))).join(", ") + (ids.length > max ? ` +${ids.length - max}` : "");
const who = s => `${s.n} ${s.n === 1 ? "Politiker" : "Käufer"}${s.ins ? " + Firmen-Insider" : ""}${s.big ? ` (Kauf ab ${money(s.big)})` : ""}`;
const tickLink = t => `<a class="tick" href="#t.${encodeURIComponent(t)}">${esc(t)}</a>`;
function killCharts() { charts.forEach(c => { try { c.remove(); } catch (e) {} }); charts = []; }
function dateAt(i) {
  if (i <= LAST) return DATES[i];
  const d = new Date(DATES[LAST] + "T12:00:00Z"); let k = i - LAST;
  while (k > 0) { d.setUTCDate(d.getUTCDate() + 1); const w = d.getUTCDay(); if (w && w < 6) k--; }
  return d.toISOString().slice(0, 10);
}
function status(s) {
  const H = RU.hold;
  if (s.i == null) return { open: true, pending: true, left: H, exit: dateAt(LAST + 1 + H), prog: 0 };
  const left = s.i + H - LAST;
  return { open: left > 0, pending: false, left, exit: dateAt(s.i + H), prog: Math.min(1, (LAST - s.i) / H) };
}

// ------------------------------------------------------------------ data
async function j(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " → HTTP " + r.status); return r.json(); }
async function load() {
  const [dash, meta, cal] = await Promise.all([j("data/dash.json"), j("data/meta.json"), j("data/calendar.json").catch(() => null)]);
  D = dash; META = meta; DATES = D.dates; LAST = DATES.length - 1; RU = D.rules;
  // Signale, die erst mehr als RU.late Handelstage zu spät in den Daten standen, werden nicht gehandelt (research/pubdate.py)
  D.late = D.signals.filter(s => s.late); D.signals = D.signals.filter(s => !s.late);
  CAL = cal && cal.spy && cal.dates.length === DATES.length ? cal.spy : null;
  $("#stand").textContent = `Kurse bis ${dDE(D.asof)} · täglich aktualisiert`;
}
const bucket = t => /^[A-Z]/.test(t) ? t[0] : "0";
async function loadPx(t) {
  const b = bucket(t);
  if (!PXB.has(b)) PXB.set(b, (META.buckets || []).includes(b) ? j(`data/prices/${b}.json`).then(d => { for (const k in d) PX.set(k, { f: d[k][0], v: d[k][1] }); }).catch(() => {}) : Promise.resolve());
  if (!TR.has(b)) TR.set(b, j(`data/tr/${b}.json`).catch(() => ({})));
  await PXB.get(b);
  return { p: PX.get(t), tr: ((await TR.get(b)) || {})[t] || [] };
}

// ------------------------------------------------------------------ Statistik
function stats(list) {
  const d = list.filter(s => s.r != null && s.s != null);
  const ex = d.map(s => s.r - s.s);
  const years = {};
  for (const s of d) (years[s.d.slice(0, 4)] = years[s.d.slice(0, 4)] || []).push(s);
  const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : null;
  const med = a => { if (!a.length) return null; const b = [...a].sort((x, y) => x - y); const m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; };
  return {
    n: d.length, r: mean(d.map(s => s.r)), ex: mean(ex), med: med(ex),
    beat: d.length ? 100 * ex.filter(v => v > 0).length / d.length : null,
    hit: d.length ? 100 * d.filter(s => s.r > 0).length / d.length : null,
    years: Object.keys(years).sort().reverse().map(y => { const a = years[y], e = a.map(s => s.r - s.s); return { y, n: a.length, ex: mean(e), beat: 100 * e.filter(v => v > 0).length / a.length }; }),
  };
}
function chartOpts(pf) {
  return { autoSize: true,
    layout: { background: { type: "solid", color: tok("--surface") }, textColor: tok("--muted"), fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: tok("--line") } },
    rightPriceScale: { borderColor: tok("--line") }, timeScale: { borderColor: tok("--line") }, crosshair: { mode: 0 },
    localization: { locale: "de-DE", ...(pf ? { priceFormatter: pf } : {}) } };
}

// ------------------------------------------------------------------ Journal-Simulation
// Tägliche Bewertung: Konto startet 2020 mit CFG.cap in Cash. Jedes Dip-Cluster bekommt Risiko ÷ Stop
// vom aktuellen Kontowert (wenn genug Cash da ist und weniger als CFG.max Trades offen sind).
// Verkauf beim ersten Schlusskurs unter dem Stop oder nach 21 Handelstagen. Freies Geld: Cash, S&P oder S&P nur über
// seinem Durchschnitt (Entscheidung zum Schlusskurs, gilt ab dem nächsten Tag).
function sim() {
  const key = JSON.stringify(CFG) + D.asof;
  if (SIM && SIMKEY === key) return SIM;
  const i0 = Math.max(0, DATES.findIndex(d => d >= "2020-01-01"));
  const sl = 1 - CFG.stop / 100, pp = posPct() / 100, H = RU.hold;
  const T = D.signals.filter(s => s.i != null && s.i >= i0 && s.path && s.path.length).map(s => {
    const p = []; let lv = 1;
    for (const v of s.path) { if (v != null) lv = v; p.push(lv); }
    let x = p.length - 1, why = p.length - 1 >= H ? "30 Tage" : "offen";
    for (let k = 1; k < p.length; k++) if (p[k] <= sl) { x = k; why = "Stop"; break; }
    return { s, t: s.t, p, x, why, ei: s.i, xi: s.i + x, size: 0, skip: null };
  }).sort((a, b) => a.ei - b.ei || b.s.n - a.s.n);
  const byEntry = new Map();
  for (const t of T) { if (!byEntry.has(t.ei)) byEntry.set(t.ei, []); byEntry.get(t.ei).push(t); }
  let cash = CFG.cap; const open = new Set(), eq = [], nOpen = [], inSpy = [];
  const rest = CAL ? CFG.rest : "cash", MAv = rest === "ma" ? spyMA(Math.max(5, Math.round(CFG.ma))) : null;
  let sw = 0;
  for (let k = i0; k <= LAST; k++) {
    const on = k > i0 && (rest === "spy" || (rest === "ma" && CAL[k - 1] > MAv[k - 1]));
    if (on && CAL[k] > 0 && CAL[k - 1] > 0) cash *= CAL[k] / CAL[k - 1];
    if (k > i0 + 1 && rest === "ma" && (CAL[k - 1] > MAv[k - 1]) !== (CAL[k - 2] > MAv[k - 2])) sw++;
    inSpy.push(rest === "spy" || (rest === "ma" && CAL[k] > MAv[k]));
    for (const t of [...open]) if (t.why !== "offen" && t.xi === k) { cash += t.size * t.p[t.x]; open.delete(t); }
    let e = cash; for (const t of open) e += t.size * t.p[k - t.ei];
    for (const t of byEntry.get(k) || []) {
      if (open.size >= CFG.max) { t.skip = `schon ${CFG.max} offen`; continue; }
      const sc = secOf(t.t);
      if (CFG.sec && sc && [...open].filter(o => secOf(o.t) === sc).length >= CFG.sec) { t.skip = `schon ${CFG.sec} aus ${secDE(sc)} offen`; continue; }
      const want = e * pp, size = Math.min(want, cash);
      if (size < want * 0.5) { t.skip = "kein Cash frei"; continue; }
      t.size = size; cash -= size; open.add(t);
    }
    e = cash; for (const t of open) e += t.size * t.p[k - t.ei];
    eq.push(e); nOpen.push(open.size);
  }
  // Drawdown
  let peak = -Infinity, pk = i0, mdd = 0, mddK = i0, mddPk = i0;
  const dd = eq.map((v, n) => { if (v > peak) { peak = v; pk = i0 + n; } const d = v / peak - 1; if (d < mdd) { mdd = d; mddK = i0 + n; mddPk = pk; } return d; });
  const E = k => eq[k - i0], SP = k => CAL ? CAL[k] : null;
  for (const t of T) {
    if (t.skip) continue;
    const seg = t.p.slice(0, t.x + 1);
    t.ret = (t.p[t.x] - 1) * 100; t.pnl = t.size * (t.p[t.x] - 1); t.R = t.ret / CFG.stop;
    t.mae = (Math.min(...seg) - 1) * 100; t.mfe = (Math.max(...seg) - 1) * 100; t.maeUsd = t.size * t.mae / 100;
    t.maeK = t.ei + seg.indexOf(Math.min(...seg));
    t.sp = SP(t.ei) > 0 && SP(t.xi) > 0 ? (SP(t.xi) / SP(t.ei) - 1) * 100 : null;
    t.bal = t.why === "offen" ? null : E(t.xi);
    t.pos = t.size / E(t.ei) * 100;
    let w = 0; for (let k = t.ei; k <= t.xi; k++) w = Math.min(w, dd[k - i0]); t.acctDD = w * 100;
  }
  const taken = T.filter(t => !t.skip), done = taken.filter(t => t.why !== "offen");
  const wins = done.filter(t => t.pnl > 0), loss = done.filter(t => t.pnl <= 0);
  const sum = a => a.reduce((x, y) => x + y, 0), mean = a => a.length ? sum(a) / a.length : null;
  let streak = 0, ls = 0;
  for (const t of [...done].sort((a, b) => a.xi - b.xi)) { if (t.pnl <= 0) { streak++; ls = Math.max(ls, streak); } else streak = 0; }
  const yrs = (Date.parse(DATES[LAST]) - Date.parse(DATES[i0])) / 864e5 / 365.25;
  const end = eq[eq.length - 1];
  let spMdd = 0; if (CAL) { let p = 0; for (let k = i0; k <= LAST; k++) { if (!(CAL[k] > 0)) continue; p = Math.max(p, CAL[k]); spMdd = Math.min(spMdd, CAL[k] / p - 1); } }
  const years = [];
  for (let k = i0, y0 = k; k <= LAST + 1; k++) {
    if (k <= LAST && DATES[k].slice(0, 4) === DATES[y0].slice(0, 4)) continue;
    const a = y0 === i0 ? i0 : y0 - 1, b = k - 1, y = DATES[y0].slice(0, 4);
    let p = -Infinity, m = 0; for (let n = a; n <= b; n++) { p = Math.max(p, E(n)); m = Math.min(m, E(n) / p - 1); }
    const yd = done.filter(t => DATES[t.xi].slice(0, 4) === y);
    years.push({ y, ret: (E(b) / E(a) - 1) * 100, sp: SP(a) > 0 && SP(b) > 0 ? (SP(b) / SP(a) - 1) * 100 : null, n: yd.length,
      win: yd.length ? 100 * yd.filter(t => t.pnl > 0).length / yd.length : null, pnl: sum(yd.map(t => t.pnl)), mdd: m * 100, endv: E(b) });
    y0 = k;
  }
  const byRet = [...done].sort((a, b) => b.ret - a.ret);
  SIM = { i0, T, taken, done, eq, dd, nOpen, inSpy, rest, swYr: sw / yrs, spyTime: 100 * inSpy.filter(Boolean).length / inSpy.length, end, mdd: mdd * 100, mddK, mddPk,
    cagr: (Math.pow(end / CFG.cap, 1 / yrs) - 1) * 100, tot: (end / CFG.cap - 1) * 100,
    spCagr: CAL && CAL[i0] > 0 ? (Math.pow(CAL[LAST] / CAL[i0], 1 / yrs) - 1) * 100 : null, spMdd: spMdd * 100,
    win: done.length ? 100 * wins.length / done.length : null,
    beat: done.length ? 100 * done.filter(t => t.sp != null && t.ret > t.sp).length / done.length : null,
    avgW: mean(wins.map(t => t.ret)), avgL: mean(loss.map(t => t.ret)),
    pf: sum(loss.map(t => -t.pnl)) > 0 ? sum(wins.map(t => t.pnl)) / sum(loss.map(t => -t.pnl)) : null,
    expR: mean(done.map(t => t.R)), ls, stops: done.filter(t => t.why === "Stop").length,
    best: byRet[0], worst: byRet[byRet.length - 1], skipped: T.length - taken.length, perYear: done.length / yrs,
    years: years.reverse() };
  SIMKEY = key;
  return SIM;
}

// ================================================================== Hauptseite
function viewMain(app) {
  const open = D.signals.filter(s => status(s).open);
  const st = stats(D.signals);
  const J = sim();
  const cmp = D.compare;
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Strategie</div><h1>Dip-Cluster</h1>
    <p>Mindestens ${RU.min_n} Politiker kaufen innerhalb von ${RU.win} Tagen dieselbe Aktie (oder ein einzelner Politiker kauft für ${money(RU.big || 100000)} oder mehr), die ${-RU.dip} % oder mehr unter ihrem 52-Wochen-Hoch steht. Kaufen zum Schlusskurs nach der Meldung, nach ${RU.days} Tagen verkaufen.</p></div></div>

  <h3 class="sec">Jetzt offen <small>${open.length ? `${open.length} Signal${open.length === 1 ? "" : "e"}` : ""}</small></h3>
  ${open.length ? `<div class="cards">${open.map(card).join("")}</div>` : `<div class="panel empty">Gerade kein offenes Dip-Cluster. Neue Signale kommen per Discord.</div>`}
  ${latePanel()}
  ${livePanel()}

  <h3 class="sec">Backtest seit 2020 <small>${RU.days} Tage halten · Einstieg ab Erscheinen in den Daten · verspätete ausgelassen</small></h3>
  <div class="verdict">${st.n ? `<b>${q(st.beat)}</b> der ${nf0.format(st.n)} Dip-Cluster schlugen den S&amp;P 500 in den 30 Tagen danach, im Schnitt um <b class="${cls(st.ex)}">${pct(st.ex)}</b> (Median ${pct(st.med)}). Zum Vergleich: alle Cluster ohne Dip-Filter nur ${q(cmp.ohne_dip.beat)} (Ø ${pct(cmp.ohne_dip.ex)}).` : "Noch keine abgeschlossenen Signale."}</div>
  <div class="tiles">
    <div class="tile"><div class="k">Schlägt den S&amp;P</div><div class="v">${q(st.beat)}</div><div class="d">im Plus: ${q(st.hit)}</div></div>
    <div class="tile"><div class="k">Ø pro Trade vs S&amp;P</div><div class="v ${cls(st.ex)}">${pct(st.ex)}</div><div class="d">Median ${pct(st.med)} · Ø Rendite ${pct(st.r)}</div></div>
    <div class="tile"><div class="k">Konto pro Jahr</div><div class="v ${cls(J.cagr)}">${pct(J.cagr)}</div><div class="d">S&amp;P 500 gehalten: ${pct(J.spCagr)}</div></div>
    <div class="tile"><div class="k">Max. Rückgang Konto</div><div class="v neg">${pct(J.mdd)}</div><div class="d">S&amp;P 500 gehalten: ${pct(J.spMdd)}</div></div>
    <div class="tile"><div class="k">Signale</div><div class="v">${nf0.format(st.n)}</div><div class="d">≈ ${nf0.format(st.n / Math.max(1, (Date.parse(D.asof) - Date.parse("2020-01-01")) / 3.156e10))} pro Jahr</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Konto nach den Regeln</h2><div class="legend-row"><span><span class="sw" style="background:var(--accent)"></span>Dip-Cluster</span><span><span class="sw" style="background:var(--chart-spy)"></span>S&amp;P 500 gehalten</span><a class="btn primary" href="#journal">Journal öffnen →</a></div></div>
    <div class="panel-b"><div class="chart sm" id="eq"></div><p class="hint" style="margin:8px 0 0">Simulation ab 2020 mit ${money(CFG.cap)}: nur die Dip-Cluster-Trades, ${nf1.format(posPct())} % des Kontos je Trade, höchstens ${CFG.max} gleichzeitig und ${CFG.sec} pro Branche, Stop −${CFG.stop} %, Verkauf nach ${RU.days} Tagen. ${restTxt()} Ohne Gebühren und Steuern. Jeden einzelnen Trade siehst du im Journal.</p></div></div>
  <div class="panel"><div class="panel-h"><h2>Nach Jahr</h2></div><div class="tbl-wrap"><table><thead><tr><th>Jahr</th><th class="n">Signale</th><th class="n">schlägt S&amp;P</th><th class="n">Ø vs S&amp;P</th></tr></thead><tbody>${st.years.map(y => `<tr><td class="num">${y.y}</td><td class="n">${y.n}</td><td class="n">${q(y.beat)}</td><td class="n">${pc(y.ex)}</td></tr>`).join("")}</tbody></table></div></div>
  ${pastTable()}`;
  app.querySelectorAll("tr[data-t]").forEach(tr => tr.addEventListener("click", e => { if (!e.target.closest("a")) location.hash = "t." + encodeURIComponent(tr.dataset.t); }));
  app.querySelector("[data-more]")?.addEventListener("click", () => { S.show += 50; const y = scrollY; route(); scrollTo(0, y); });
  drawEq(J);
}
function card(s) {
  const st = status(s), t = D.tickers[s.t] || {};
  const ex = s.rn != null && s.sn != null ? s.rn - s.sn : null;
  const ref = s.ep || s.lp;
  const stop = ref ? ref * (1 - CFG.stop / 100) : null, tgt = ref ? ref * (1 + RU.target / 100) : null;
  const pos = CFG.cap ? CFG.cap * posPct() / 100 : null;
  const sh = pos && s.lp ? Math.floor(pos / s.lp) : null;
  const run = s.ep && s.lp ? (s.lp / s.ep - 1) * 100 : null;
  return `<a class="card" href="#t.${encodeURIComponent(s.t)}">
    <div class="card-h"><div class="ctk"><b>${esc(s.t)}</b><span>${esc(t.a || "")}</span></div>
      <div style="display:grid;gap:4px;justify-items:end">${st.pending || LAST - s.i < 5 ? '<span class="badge new">neu</span>' : ""}<span class="badge dip">▼ ${nf0.format(s.fh)} % unter Hoch</span></div></div>
    <div class="cwho">${secOf(s.t) ? `<span class="mut">${esc(secDE(secOf(s.t)))}</span> · ` : ""}<b>${who(s)}</b>${s.o ? ` · <span class="neg">${s.o} Verkäufer</span>` : ""} · bis ${dS(s.d)} gemeldet${s.seen ? ` <span class="neg" title="Die Datenquelle hat die Meldung erst später geliefert. Einstieg zählt ab diesem Tag.">(in den Daten erst ${dS(s.seen)})</span>` : ""} · ~${money(s.vol)}<br>${names(s.m)}</div>
    <div class="plan">
      <div><span class="k">${st.pending ? "Kauf" : "Einstieg"}</span><b>${st.pending ? "nächster Schluss" : usd(s.ep)}</b></div>
      <div><span class="k">Stop −${CFG.stop} %</span><b class="neg">${usd(stop)}</b></div>
      <div><span class="k">Risiko</span><b class="neg">${pos ? "$" + nf0.format(pos * CFG.stop / 100) : "–"}</b></div>
      <div><span class="k">Verkauf ${st.exit > DATES[LAST] ? "ca." : ""}</span><b>${dS(st.exit)}</b></div>
    </div>
    ${ampel(s)}
    ${secFull(s)}
    ${pos ? `<div class="hint">Position: ${nf1.format(posPct())} % = <b>$${nf0.format(pos)}</b>${sh ? ` ≈ ${nf0.format(sh)} Aktien zu ${usd(s.lp)}` : ""}</div>` : ""}
    <div class="cnums">
      <div><span class="k">seit Einstieg</span><b class="${cls(s.rn)}">${st.pending ? "–" : pct(s.rn)}</b></div>
      <div><span class="k">vs S&amp;P</span><b class="${cls(ex)}">${st.pending ? "–" : pct(ex)}</b></div>
      <div><span class="k">noch</span><b>${st.left} HT</b></div>
    </div>
    <div class="prog"><i style="width:${Math.round(st.prog * 100)}%"></i></div>
    ${run != null && run > 10 ? `<div class="hint neg">Schon ${pct(run)} seit dem Einstiegstag gestiegen, der Vorteil ist eventuell weg.</div>` : ""}</a>`;
}
// Würde das Signal laut Branchenlimit ausgelassen? (gleiche Logik wie im Journal)
function secFull(s) {
  const sc = secOf(s.t); if (!sc || !CFG.sec) return "";
  const J = sim(), tr = J.T.find(x => x.s === s);
  let full;
  if (tr) full = !!(tr.skip && tr.skip.includes(" aus "));
  else {   // noch nicht gekauft: offene Trades + frühere wartende Signale derselben Branche zählen
    const wait = D.signals.filter(x => x.i == null && secOf(x.t) === sc);
    full = J.taken.filter(x => x.why === "offen" && secOf(x.t) === sc).length + wait.indexOf(s) >= CFG.sec;
  }
  return full ? `<div class="hint neg"><b>Branchenlimit:</b> schon ${CFG.sec} Trades aus ${esc(secDE(sc))} offen, laut Regel auslassen.</div>` : "";
}
const AMPL = { g: "grün", y: "gelb", r: "rot" };
function ampel(s) {
  const c = s.chk; if (!c) return "";
  return `<div class="amp ${c.lvl}"><b>Vor-Check: ${AMPL[c.lvl]}</b>${c.why.length ? `<ul>${c.why.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : `<span> · Börsenwert, Handel und Zahlen-Termin ok</span>`}</div>`;
}
function latePanel() {
  const from = DATES[Math.max(0, LAST - 42)], L = (D.late || []).filter(s => (s.seen || s.d) >= from);
  if (!L.length) return "";
  return `<details class="panel late"><summary><b>Zu spät gemeldet, ausgelassen</b> <small class="mut">${L.length} in den letzten 2 Monaten · anzeigen</small></summary>
    <p class="hint" style="margin:8px 0 0">${L.map(s => `${tickLink(s.t)} <span class="mut">gemeldet ${dS(s.d)}, in den Daten erst ${dS(s.seen)} (${s.late} Handelstage zu spät)</span>`).join(" · ")}</p></details>`;
}
function livePanel() {
  const LV = RU.live; if (!LV) return "";
  const live = D.signals.filter(s => s.d >= LV), done = live.filter(s => s.r != null && s.s != null);
  const st = stats(D.signals.filter(s => s.d < LV));
  const n = done.length, win = n ? 100 * done.filter(s => s.r > 0).length / n : null, beat = n ? 100 * done.filter(s => s.r > s.s).length / n : null;
  const avg = n ? done.reduce((a, s) => a + s.r, 0) / n : null, ex = n ? done.reduce((a, s) => a + s.r - s.s, 0) / n : null;
  return `<div class="panel live"><div class="panel-h"><h2>Live-Bilanz <small class="mut">seit ${dDE(LV)}</small></h2><span class="sub">nur Signale ab diesem Tag · kein Backtest</span></div>
  <div class="panel-b"><div class="tiles">
    <div class="tile"><div class="k">Signale live</div><div class="v">${live.length}</div><div class="d">${n} abgeschlossen · ${live.length - n} offen</div></div>
    <div class="tile"><div class="k">Treffer</div><div class="v">${q(win)}</div><div class="d">Backtest: ${q(st.hit)}</div></div>
    <div class="tile"><div class="k">Schlägt den S&amp;P</div><div class="v">${q(beat)}</div><div class="d">Backtest: ${q(st.beat)}</div></div>
    <div class="tile"><div class="k">Ø pro Trade</div><div class="v ${cls(avg)}">${pct(avg)}</div><div class="d">vs S&amp;P ${pct(ex)} · Backtest ${pct(st.ex)}</div></div>
  </div>${n < 20 ? `<p class="hint" style="margin:10px 0 0">${n ? `Erst ${n} abgeschlossene${n === 1 ? "r" : ""} Trade${n === 1 ? "" : "s"}.` : "Noch kein Live-Trade abgeschlossen."} Aussagekräftig wird die Bilanz ab etwa 20–30 Trades. Gemessen über 30 Tage ab Meldung, ohne Stop.</p>` : ""}</div></div>`;
}
function pastTable() {
  const done = D.signals.filter(s => s.r != null);
  return `<div class="panel"><div class="panel-h"><h2>Alle vergangenen Dip-Cluster</h2><span class="sub">${done.length} abgeschlossen · Klick öffnet den Chart</span></div>
  <div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Aktie</th><th>Käufer</th><th class="n">unter Hoch</th><th class="n">30 Tage</th><th class="n">S&amp;P</th><th class="n">vs S&amp;P</th></tr></thead>
  <tbody>${done.slice(0, S.show).map(s => `<tr class="click" data-t="${esc(s.t)}"><td class="num">${dDE(s.d)}</td><td>${tickLink(s.t)}</td><td style="white-space:normal;min-width:180px">${s.n}${s.ins ? " + Insider" : ""}${s.big ? " · groß" : ""} · ${names(s.m, 3)}</td><td class="n">${nf0.format(s.fh)} %</td><td class="n">${pc(s.r)}</td><td class="n mut">${pct(s.s)}</td><td class="n">${pc(s.r - s.s)}</td></tr>`).join("")}</tbody></table></div>
  ${done.length > S.show ? `<div class="more"><button class="btn" data-more>Weitere ${Math.min(50, done.length - S.show)} anzeigen</button></div>` : ""}</div>`;
}
function drawEq(J) {
  const el = $("#eq"); if (!el) return;
  if (!window.LightweightCharts || J.eq.length < 2) { el.innerHTML = `<div class="empty">Chart nicht verfügbar.</div>`; return; }
  const c = LightweightCharts.createChart(el, { ...chartOpts(v => (v > 0 ? "+" : "") + nf0.format(v) + " %"), handleScroll: false, handleScale: false, timeScale: { borderColor: tok("--line"), minBarSpacing: 0.01 } }); charts.push(c);
  const step = 3, pt = (k, v) => ({ time: DATES[k], value: v });
  if (CAL) { const s = c.addLineSeries({ color: tok("--chart-spy"), lineWidth: 2, priceLineVisible: false, title: "S&P" }); const b = CAL[J.i0]; s.setData(J.eq.map((_, n) => J.i0 + n).filter((k, n) => (n % step === 0 || k === LAST) && CAL[k] > 0).map(k => pt(k, (CAL[k] / b - 1) * 100))); }
  const s = c.addLineSeries({ color: tok("--accent"), lineWidth: 2, priceLineVisible: false, title: "Dip" });
  s.setData(J.eq.map((v, n) => [J.i0 + n, v]).filter(([k], n) => n % step === 0 || k === LAST).map(([k, v]) => pt(k, (v / CFG.cap - 1) * 100)));
  c.timeScale().fitContent();
}

// ================================================================== Journal
const WHY = { "Stop": "neg", "30 Tage": "", "offen": "new" };
const MODES = {
  tr: { nav: "trades", eyebrow: "Backtest · nur Trades", h: "Nur die Dip-Trades",
        p: "Das Konto handelt ausschließlich die Dip-Cluster-Signale. Zwischen den Trades liegt das Geld als Cash. So siehst du, was die Strategie allein bringt und wie sich das Risiko pro Trade auswirkt." },
  sp: { nav: "journal", eyebrow: "Backtest · Trades + S&P 500", h: "Dip-Trades plus S&P 500",
        p: "Die Dip-Signale haben Vorrang. Das restliche Geld liegt im S&P 500, wahlweise immer oder nur solange der Index über seinem Durchschnitt liegt. Das ist die empfohlene Kombination." },
};
function viewJournal(app, mode) {
  const M = MODES[mode];
  const J = sim();
  const f = S.jf, list = [...J.T].reverse().filter(t =>
    f === "alle" ? true : f === "gewinner" ? !t.skip && t.why !== "offen" && t.pnl > 0 : f === "verlierer" ? !t.skip && t.why !== "offen" && t.pnl <= 0 :
    f === "stop" ? !t.skip && t.why === "Stop" : f === "offen" ? !t.skip && t.why === "offen" : f === "live" ? t.s.d >= (RU.live || "9") : !!t.skip);
  const num = new Map(J.taken.map((t, n) => [t, n + 1]));
  const tile = (k, v, d, c = "") => `<div class="tile"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="d">${d}</div></div>`;
  const pend = D.signals.filter(s => s.i == null);
  app.innerHTML = `
  <div class="seg" role="tablist"><a href="#trades" class="${mode === "tr" ? "on" : ""}"><b>Nur Trades</b><small>Rest als Cash</small></a><a href="#journal" class="${mode === "sp" ? "on" : ""}"><b>Trades + S&amp;P 500</b><small>Rest im Index</small></a></div>
  <div class="view-head"><div><div class="eyebrow">${M.eyebrow}</div><h1>${M.h}</h1>
    <p>${M.p} Klick auf einen Trade zeigt ihn im Chart.</p></div></div>

  <div class="panel jset"><div class="panel-b">
    <label class="ctl"><span>Startkapital 2020 ($)</span><input type="number" data-k="cap" min="100" step="1000" value="${CFG.cap}"></label>
    <label class="ctl"><span>Risiko pro Trade (%)</span><input type="number" data-k="risk" min="0.1" max="25" step="0.5" value="${CFG.risk}"></label>
    <label class="ctl"><span>Stop (% unter Einstieg)</span><input type="number" data-k="stop" min="5" max="60" step="5" value="${CFG.stop}"></label>
    <label class="ctl"><span>Max. gleichzeitig</span><input type="number" data-k="max" min="1" max="30" step="1" value="${CFG.max}"></label>
    <label class="ctl"><span>Max. pro Branche</span><input type="number" data-k="sec" min="1" max="30" step="1" value="${CFG.sec}"></label>
    ${mode === "sp" ? `<label class="ctl"><span>S&amp;P-Anteil</span><select id="jrest"><option value="spy"${CFG.rest === "spy" ? " selected" : ""}>immer im S&amp;P 500</option><option value="ma"${CFG.rest === "ma" ? " selected" : ""}>S&amp;P 500 über Durchschnitt</option></select></label>` : ""}
    ${mode === "sp" && CFG.rest === "ma" ? `<label class="ctl"><span>Durchschnitt (Tage)</span><input type="number" data-k="ma" min="10" max="300" step="10" value="${CFG.ma}"></label>` : ""}
    <div class="jpos"><span>Positionsgröße</span><b>${nf1.format(posPct())} %</b><small>= Risiko ÷ Stop · heute ${money(CFG.cap * posPct() / 100)}</small></div>
    <button class="btn ghost" id="jreset" type="button">Standard</button>
    <div class="rq"><span>Risiko schnell wählen</span><div class="chips">${[1, 1.5, 2, 2.5, 3, 4, 5].map(r => `<button type="button" class="chip${CFG.risk === r ? " on" : ""}" data-r="${r}">${nf1.format(r)} %</button>`).join("")}</div></div>
  </div></div>

  <div class="tiles">
    ${tile("Endkapital", money(J.end), `${pct(J.tot)} seit ${DATES[J.i0].slice(0, 4)}`, cls(J.tot))}
    ${tile("Rendite pro Jahr", pct(J.cagr), `S&amp;P 500 gehalten: ${pct(J.spCagr)}`, cls(J.cagr))}
    ${tile("Max. Rückgang", pct(J.mdd), `am ${dDE(DATES[J.mddK])} · S&amp;P: ${pct(J.spMdd)}`, "neg")}
    ${tile("Trades", nf0.format(J.done.length), `≈ ${nf0.format(J.perYear)} pro Jahr · ${J.skipped} ausgelassen`)}
    ${J.rest !== "cash" ? tile("Freies Geld im S&amp;P", q(J.spyTime) + " der Zeit", J.rest === "ma" ? `≈ ${nf1.format(J.swYr)} Wechsel pro Jahr · MA${CFG.ma}` : "immer investiert") : ""}
    ${tile("Trefferquote", q(J.win), `schlägt den S&amp;P: ${q(J.beat)}`)}
    ${tile("Ø Gewinner / Verlierer", `<span class="pos">${pct(J.avgW)}</span> <span class="neg">${pct(J.avgL)}</span>`, `RR ${J.avgL ? "1 : " + nf2.format(J.avgW / -J.avgL) : "–"}`)}
    ${tile("Profit-Faktor", J.pf == null ? "–" : nf2.format(J.pf), `Ø ${J.expR == null ? "–" : (J.expR > 0 ? "+" : "") + nf2.format(J.expR)} R pro Trade`)}
    ${tile("Stops / Verlustserie", `${J.stops} / ${J.ls}`, `längste Serie: ${J.ls} Verlierer in Folge`)}
    ${tile("Bester / schlechtester", `<span class="pos">${J.best ? esc(J.best.t) + " " + pct(J.best.ret) : "–"}</span>`, `<span class="neg">${J.worst ? esc(J.worst.t) + " " + pct(J.worst.ret) : "–"}</span>`)}
  </div>

  <div class="panel" id="jchart"><div class="panel-h"><h2>Kontoverlauf</h2><div class="legend-row"><span><span class="sw" style="background:var(--accent)"></span>Konto</span>${CAL ? `<span><span class="sw" style="background:var(--chart-spy)"></span>Gleicher Betrag im S&amp;P 500</span>` : ""}<span><span class="sw dot" style="background:var(--pos)"></span>Gewinn-Trade</span><span><span class="sw dot" style="background:var(--neg)"></span>Verlust-Trade</span><button class="btn" id="jall" type="button">Alles zeigen</button></div></div>
    <div class="panel-b"><div class="chart" id="jeq"><div class="chart-legend" id="jleg"></div></div><div class="chart dd" id="jdd"></div>
    <p class="hint" style="margin:8px 0 0">Oben das Konto in $, unten der Rückgang vom letzten Höchststand. Punkte = Verkauf eines Trades (grün Gewinn, rot Verlust). ${restTxt()} Ohne Gebühren und Steuern.</p></div></div>
  <div id="jdet"></div>

  <div class="panel"><div class="panel-h"><h2>Trades</h2><div class="chips" id="jf">${[["alle", "Alle"], ["gewinner", "Gewinner"], ["verlierer", "Verlierer"], ["stop", "Stops"], ["offen", "Offen"], ["skip", "Ausgelassen"], ["live", "Live"]].map(([k, l]) => `<button type="button" class="chip${f === k ? " on" : ""}" data-f="${k}">${l}</button>`).join("")}</div></div>
  <div class="tbl-wrap"><table class="jt"><thead><tr><th class="n">#</th><th>Aktie</th><th>Kauf</th><th>Verkauf</th><th>Grund</th><th class="n">Position</th><th class="n">Ergebnis</th><th class="n">Gewinn $</th><th class="n">R</th><th class="n" title="Tiefster Stand während des Trades">Max. im Minus</th><th class="n" title="Höchster Stand während des Trades">Max. im Plus</th><th class="n">S&amp;P</th><th class="n" title="Größter Rückgang des ganzen Kontos während der Trade lief">Konto-DD</th><th class="n">Konto danach</th></tr></thead>
  <tbody>${pend.map(s => `<tr class="mut"><td class="n">–</td><td>${tickLink(s.t)}</td><td class="num">nächster Schluss</td><td class="num">–</td><td><span class="badge new">wartet</span></td><td class="n" colspan="9" style="text-align:left">Gemeldet am ${dDE(s.d)}, Kauf zum nächsten Schlusskurs</td></tr>`).join("")}
  ${list.slice(0, S.jshow).map(t => t.skip
    ? `<tr class="mut"><td class="n">–</td><td>${tickLink(t.t)}</td><td class="num">${dDE(DATES[t.ei])}</td><td class="num">–</td><td>ausgelassen</td><td class="n" colspan="9" style="text-align:left">${esc(t.skip)} · hätte ${pct((t.p[t.x] - 1) * 100)} gebracht</td></tr>`
    : `<tr class="click${S.sel === t.ei + t.t ? " sel" : ""}" data-j="${esc(t.ei + t.t)}"><td class="n mut">${num.get(t)}</td><td>${tickLink(t.t)}${RU.live && t.s.d >= RU.live ? ' <span class="badge live">live</span>' : ""}</td>
      <td class="num">${dDE(DATES[t.ei])}<br><span class="mut">${usd(t.s.ep)}</span></td>
      <td class="num">${t.why === "offen" ? "läuft" : dDE(DATES[t.xi])}<br><span class="mut">${t.s.ep ? usd(t.s.ep * t.p[t.x]) : ""}</span></td>
      <td><span class="badge ${WHY[t.why]}">${t.why === "offen" ? `offen · noch ${RU.hold - t.x} HT` : t.why}</span></td>
      <td class="n">$${nf0.format(t.size)}<br><span class="mut">${nf1.format(t.pos)} %</span></td>
      <td class="n"><b class="${cls(t.ret)}">${pct(t.ret)}</b></td><td class="n ${cls(t.pnl)}">${t.pnl >= 0 ? "+" : "−"}$${nf0.format(Math.abs(t.pnl))}</td>
      <td class="n ${cls(t.R)}">${(t.R > 0 ? "+" : "") + nf2.format(t.R)}</td>
      <td class="n neg">${pct(t.mae)}<br><span class="mut">−$${nf0.format(Math.abs(t.maeUsd))}</span></td><td class="n pos">${pct(t.mfe)}</td>
      <td class="n mut">${pct(t.sp)}</td><td class="n ${t.acctDD < -0.05 ? "neg" : "mut"}">${pct(t.acctDD)}</td><td class="n">${t.bal == null ? "–" : money(t.bal)}</td></tr>`).join("")}</tbody></table></div>
  ${list.length > S.jshow ? `<div class="more"><button class="btn" data-jmore>Weitere ${Math.min(100, list.length - S.jshow)} anzeigen</button></div>` : ""}</div>

  <div class="grid2">
    <div class="panel"><div class="panel-h"><h2>Nach Jahr</h2></div><div class="tbl-wrap"><table><thead><tr><th>Jahr</th><th class="n">Konto</th><th class="n">S&amp;P</th><th class="n">Max. Rückgang</th><th class="n">Trades</th><th class="n">Treffer</th><th class="n">Kontostand</th></tr></thead>
    <tbody>${J.years.map(y => `<tr><td class="num">${y.y}</td><td class="n"><b class="${cls(y.ret)}">${pct(y.ret)}</b></td><td class="n mut">${pct(y.sp)}</td><td class="n neg">${pct(y.mdd)}</td><td class="n">${y.n}</td><td class="n">${q(y.win)}</td><td class="n">${money(y.endv)}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="note"><b>So liest du das:</b> <b>R</b> = Ergebnis geteilt durch das Risiko (−1 R = Stop getroffen). <b>Max. im Minus</b> = tiefster Schlusskurs während des Trades, also wie weh er zwischendurch tat. <b>Konto-DD</b> = wie weit das ganze Konto unter seinem Höchststand lag, während der Trade lief. <b>Ausgelassen</b> = Signal kam, als schon ${CFG.max} Trades (oder ${CFG.sec} aus derselben Branche) offen waren oder kein Cash frei war.<br><br>Signale, die mehr als ${RU.late || 5} Handelstage zu spät in den Daten standen, sind gar nicht enthalten.<br><br>Kurse sind Schlusskurse, der Stop greift auf Schlusskurs-Basis (im echten Handel kann ein Kurs auch darunter öffnen). Keine Anlageberatung.</div>
  </div>`;

  app.querySelectorAll(".jset input").forEach(inp => inp.addEventListener("change", () => {
    const v = Number(inp.value); if (!(v > 0)) return;
    CFG[inp.dataset.k] = ["max", "ma", "sec"].includes(inp.dataset.k) ? Math.round(v) : v; saveCfg(); const y = scrollY; route(); scrollTo(0, y);
  }));
  app.querySelectorAll(".rq [data-r]").forEach(b => b.addEventListener("click", () => { CFG.risk = Number(b.dataset.r); saveCfg(); const y = scrollY; route(); scrollTo(0, y); }));
  $("#jrest")?.addEventListener("change", e => { CFG.rest = e.target.value; saveCfg(); const y = scrollY; route(); scrollTo(0, y); });
  $("#jreset").addEventListener("click", () => { Object.assign(CFG, DEFS[mode]); saveCfg(); route(); });
  app.querySelectorAll("#jf [data-f]").forEach(b => b.addEventListener("click", () => { S.jf = b.dataset.f; S.jshow = 60; const y = scrollY; route(); scrollTo(0, y); }));
  app.querySelector("[data-jmore]")?.addEventListener("click", () => { S.jshow += 100; const y = scrollY; route(); scrollTo(0, y); });
  const ch = drawJournal(J);
  const pick = (t, scroll) => {
    S.sel = t ? t.ei + t.t : null;
    app.querySelectorAll("tr[data-j]").forEach(r => r.classList.toggle("sel", r.dataset.j === S.sel));
    if (ch) ch.focus(t);
    $("#jdet").innerHTML = t ? detail(t) : "";
    if (scroll) $("#jchart").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  app.querySelectorAll("tr[data-j]").forEach(tr => tr.addEventListener("click", e => { if (e.target.closest("a")) return; pick(J.taken.find(t => t.ei + t.t === tr.dataset.j), true); }));
  $("#jall").addEventListener("click", () => pick(null));
  if (S.sel) { const t = J.taken.find(t => t.ei + t.t === S.sel); if (t) pick(t); }
}
function detail(t) {
  const s = t.s;
  return `<div class="panel jdet"><div class="panel-h"><h2>${tickLink(t.t)} · ${dDE(DATES[t.ei])} bis ${t.why === "offen" ? "heute" : dDE(DATES[t.xi])}</h2><span class="badge ${WHY[t.why]}">${t.why}</span></div>
  <div class="panel-b"><div class="plan">
    <div><span class="k">Ergebnis</span><b class="${cls(t.ret)}">${pct(t.ret)} · ${t.pnl >= 0 ? "+" : "−"}$${nf0.format(Math.abs(t.pnl))}</b></div>
    <div><span class="k">Position</span><b>$${nf0.format(t.size)} (${nf1.format(t.pos)} %)</b></div>
    <div><span class="k">Tiefster Punkt</span><b class="neg">${pct(t.mae)} am ${dS(DATES[t.maeK])}</b></div>
    <div><span class="k">Höchster Punkt</span><b class="pos">${pct(t.mfe)}</b></div>
    <div><span class="k">S&amp;P gleiche Zeit</span><b>${pct(t.sp)}</b></div>
    <div><span class="k">Unter 52W-Hoch</span><b>${nf0.format(s.fh)} %</b></div>
  </div><p class="hint" style="margin:10px 0 0">${who(s)}: ${names(s.m, 8)}${s.o ? ` · ${s.o} Verkäufer` : ""} · gemeldet ${dDE(s.d)}</p></div></div>`;
}
function drawJournal(J) {
  const el = $("#jeq"), el2 = $("#jdd");
  if (!window.LightweightCharts || J.eq.length < 2) { el.innerHTML = `<div class="empty">Chart nicht verfügbar.</div>`; return null; }
  const fmt$ = v => "$" + nf0.format(v);
  const c = LightweightCharts.createChart(el, { ...chartOpts(fmt$), timeScale: { borderColor: tok("--line"), minBarSpacing: 0.01 } }); charts.push(c);
  const c2 = LightweightCharts.createChart(el2, { ...chartOpts(v => nf0.format(v) + " %"), timeScale: { visible: false, borderColor: tok("--line"), minBarSpacing: 0.01 } }); charts.push(c2);
  const ks = J.eq.map((_, n) => J.i0 + n);
  let sp = null;
  if (CAL) { sp = c.addLineSeries({ color: tok("--chart-spy"), lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }); const b = CAL[J.i0]; sp.setData(ks.filter(k => CAL[k] > 0).map(k => ({ time: DATES[k], value: CFG.cap * CAL[k] / b }))); }
  const acc = tok("--accent");
  const s = c.addAreaSeries({ lineColor: acc, topColor: acc + "33", bottomColor: acc + "00", lineWidth: 2, priceLineVisible: false });
  s.setData(J.eq.map((v, n) => ({ time: DATES[J.i0 + n], value: v })));
  const neg = tok("--neg");
  const d = c2.addAreaSeries({ lineColor: neg, topColor: neg + "05", bottomColor: neg + "55", lineWidth: 1.5, priceLineVisible: false, invertFilledArea: false });
  d.setData(J.dd.map((v, n) => ({ time: DATES[J.i0 + n], value: v * 100 })));
  const base = J.done.map(t => ({ time: DATES[t.xi], position: "inBar", color: t.pnl > 0 ? tok("--pos") : neg, shape: "circle", size: 0.5 }));
  const sortM = m => m.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
  s.setMarkers(sortM([...base]));
  d.createPriceLine({ price: J.mdd, color: neg, lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "max" });
  // Zeitachsen koppeln
  let lock = false;
  const sync = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange(r => { if (lock || !r) return; lock = true; b.timeScale().setVisibleLogicalRange(r); lock = false; });
  sync(c, c2); sync(c2, c);
  c.timeScale().fitContent(); c2.timeScale().fitContent();
  // Legende
  const leg = $("#jleg");
  const show = k => {
    const n = k - J.i0, op = J.taken.filter(t => t.ei <= k && (t.why === "offen" || k < t.xi));
    leg.innerHTML = `<b>${dDE(DATES[k])}</b> · Konto <b>${money(J.eq[n])}</b> · Rückgang <span class="${J.dd[n] < 0 ? "neg" : ""}">${pct(J.dd[n] * 100)}</span>${CAL && sp ? ` · S&amp;P ${money(CFG.cap * CAL[k] / CAL[J.i0])}` : ""}<br>${op.length ? `offen (${op.length}): ` + op.map(t => `${esc(t.t)} <span class="${cls(t.p[k - t.ei] - 1)}">${pct((t.p[k - t.ei] - 1) * 100)}</span>`).join(", ") : '<span class="mut">keine Trades offen</span>'}${J.rest !== "cash" ? ` · freies Geld: ${J.inSpy[n] ? "im S&amp;P" : "Cash"}` : ""}`;
  };
  const idx = new Map(ks.map(k => [DATES[k], k]));
  show(LAST);
  c.subscribeCrosshairMove(p => { const k = p && p.time ? idx.get(typeof p.time === "string" ? p.time : `${p.time.year}-${String(p.time.month).padStart(2, "0")}-${String(p.time.day).padStart(2, "0")}`) : null; show(k ?? LAST); });
  return { focus(t) {
    if (!t) { s.setMarkers(sortM([...base])); c.timeScale().fitContent(); show(LAST); return; }
    const m = base.filter(x => x.time !== DATES[t.xi]);
    m.push({ time: DATES[t.ei], position: "belowBar", color: acc, shape: "arrowUp", text: "Kauf " + t.t });
    if (t.why !== "offen") m.push({ time: DATES[t.xi], position: "aboveBar", color: t.pnl > 0 ? tok("--pos") : neg, shape: "arrowDown", text: `${t.t} ${pct(t.ret)}` });
    s.setMarkers(sortM(m));
    const a = Math.max(0, t.ei - J.i0 - 30), b = Math.min(J.eq.length - 1, t.xi - J.i0 + 30);
    c.timeScale().setVisibleLogicalRange({ from: a, to: b });
    show(t.why === "offen" ? LAST : t.xi);
  } };
}

// ================================================================== Aktie
async function viewTicker(app, t) {
  const info = D.tickers[t] || {};
  const sigs = D.signals.filter(s => s.t === t);
  app.innerHTML = `<button type="button" class="btn ghost" id="back" style="justify-self:start;padding-left:0">← Zurück</button>
  <div class="view-head"><div><div class="eyebrow">Aktie</div><h1 style="font-family:var(--f-mono)">${esc(t)}</h1><p>${esc(info.a || "")}</p></div></div>
  ${sigs.length ? `<div class="panel"><div class="panel-h"><h2>Dip-Cluster in ${esc(t)}</h2></div><div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Käufer</th><th class="n">unter Hoch</th><th class="n">Ergebnis 30 T</th><th class="n">vs S&amp;P</th></tr></thead><tbody>${sigs.map(s => { const o = status(s).open; return `<tr><td class="num">${dDE(s.d)}</td><td style="white-space:normal">${s.n} · ${names(s.m, 8)}</td><td class="n">${nf0.format(s.fh)} %</td><td class="n">${o ? `<span class="badge new">offen</span> ${pc(s.rn)}` : pc(s.r)}</td><td class="n">${o ? pc(s.rn != null && s.sn != null ? s.rn - s.sn : null) : pc(s.r - s.s)}</td></tr>`; }).join("")}</tbody></table></div></div>` : ""}
  <div class="panel"><div class="panel-h"><h2>Kurs mit Politiker-Trades</h2><div class="legend-row"><span><span class="mk up"></span>Kauf (Tag nach Meldung)</span><span><span class="mk dn"></span>Verkauf</span><span><span class="sw" style="background:var(--accent)"></span>Dip-Cluster</span></div></div><div class="panel-b"><div class="chart" id="pc"><div class="loading">Lade Kurs …</div></div></div></div>
  <div id="trl"></div>`;
  $("#back").addEventListener("click", () => history.length > 1 ? history.back() : (location.hash = ""));
  const { p, tr } = await loadPx(t);
  if (decodeURIComponent(location.hash.slice(1)) !== "t." + t) return;
  const el = $("#pc");
  tr.sort((a, b) => a[3] < b[3] ? 1 : -1);
  $("#trl").innerHTML = `<div class="panel"><div class="panel-h"><h2>Gemeldete Trades</h2><span class="sub">${tr.length} seit 2020</span></div><div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Trade</th><th>Politiker</th><th></th><th class="n">Betrag</th></tr></thead><tbody>${tr.slice(0, 60).map(x => { const m = mem(x[0]); return `<tr${x[6] ? ' class="mut" title="Dividenden-Reinvestition, zählt nicht"' : ""}><td class="num">${dDE(x[3])}</td><td class="num">${dDE(x[2])}</td><td>${esc(m.name)} ${m.name !== "?" ? pspan(m) : ""}</td><td><span class="side ${x[1]}">${x[1] === "P" ? "KAUF" : "VERKAUF"}</span></td><td class="n">${amt(x[4], x[5])}</td></tr>`; }).join("")}</tbody></table></div></div>`;
  el.innerHTML = "";
  if (!p) { el.innerHTML = `<div class="empty">Keine Kursdaten für ${esc(t)}.</div>`; return; }
  if (!window.LightweightCharts) { el.innerHTML = `<div class="empty">Chart-Bibliothek nicht geladen.</div>`; return; }
  const c = LightweightCharts.createChart(el, chartOpts()); charts.push(c);
  const line = tok("--chart-line");
  const s = c.addAreaSeries({ lineColor: line, topColor: line + "30", bottomColor: line + "00", lineWidth: 2, priceLineVisible: false });
  const data = []; for (let k = 0; k < p.v.length; k++) if (p.v[k] != null) data.push({ time: DATES[p.f + k], value: p.v[k] });
  s.setData(data);
  const first = DATES[p.f], agg = new Map();
  const nextDay = d => { let lo = 0, hi = DATES.length; while (lo < hi) { const m = (lo + hi) >> 1; if (DATES[m] <= d) lo = m + 1; else hi = m; } return lo <= LAST ? DATES[lo] : null; };
  for (const x of tr) { if (x[6]) continue; const d = nextDay(x[3]); if (!d || d < first) continue; const k = d + x[1]; agg.set(k, (agg.get(k) || 0) + 1); }
  const mk = [];
  for (const [k, n] of agg) { const d = k.slice(0, 10), sd = k.slice(10); mk.push({ time: d, position: sd === "P" ? "belowBar" : "aboveBar", color: sd === "P" ? tok("--pos") : tok("--neg"), shape: sd === "P" ? "arrowUp" : "arrowDown", text: n > 1 ? n + "×" : "" }); }
  for (const g of sigs) if (g.i != null && DATES[g.i] >= first) mk.push({ time: DATES[g.i], position: "belowBar", color: tok("--accent"), shape: "circle", text: "Dip-Cluster" });
  mk.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
  s.setMarkers(mk);
  c.timeScale().setVisibleRange({ from: DATES[Math.max(p.f, LAST - 520)], to: DATES[LAST] });
}

// ------------------------------------------------------------------ Router
function route() {
  killCharts();
  const h = decodeURIComponent(location.hash.slice(1));
  const app = $("#app");
  const nav = h === "journal" || h === "trades" ? h : h.startsWith("t.") ? "" : "main";
  document.querySelectorAll("nav.tabs a").forEach(a => a.setAttribute("aria-current", a.dataset.nav === nav ? "page" : "false"));
  MODE = h === "trades" ? "tr" : "sp"; CFG = CFGS[MODE];
  try { if (h.startsWith("t.")) viewTicker(app, h.slice(2)); else if (nav === "journal" || nav === "trades") viewJournal(app, MODE); else viewMain(app); }
  catch (e) { console.error(e); app.innerHTML = `<div class="err">Fehler beim Anzeigen: ${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", () => { route(); scrollTo(0, 0); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => route());
load().then(route).catch(e => { console.error(e); $("#app").innerHTML = `<div class="err"><b>Daten konnten nicht geladen werden.</b><br>${esc(e.message)}</div>`; });
})();
