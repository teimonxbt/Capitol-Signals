/* Capitol Signals – drei Strategien: Cluster, Ausschuss-Insider, Top-Politiker.
   Alle Daten kommen vorberechnet aus data/dash.json (siehe signals.py). Nur Käufe, Haltedauer 30/60/90 Tage. */
(() => {
"use strict";
const HD = { "30": 21, "60": 42, "90": 63 };
const S = { h: "60", mn: "3", cm: "all", show: {} };
try { Object.assign(S, JSON.parse(localStorage.getItem("cs2") || "{}")); } catch (e) {}
if (!HD[S.h]) S.h = "60";
const save = () => { try { localStorage.setItem("cs2", JSON.stringify({ h: S.h, mn: S.mn, cm: S.cm })); } catch (e) {} };

let D, META, LAST, DATES;
const PX = new Map(), PXB = new Map(), TR = new Map();
let charts = [];

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
const mean = a => a.length ? a.reduce((s, v) => s + v, 0) / a.length : null;
const $ = s => document.querySelector(s);
const tok = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const amt = (lo, hi) => { const f = v => v >= 1e6 ? (v / 1e6).toFixed(v % 1e6 ? 1 : 0).replace(".0", "") + "M" : Math.round(v / 1e3) + "K"; if (!hi || hi === lo) return lo ? "$" + f(lo) : "–"; return "$" + f(lo) + "–" + f(hi); };
const money = v => v >= 1e6 ? "$" + nf1.format(v / 1e6) + " Mio." : v >= 1e3 ? "$" + nf0.format(v / 1e3) + "K" : "$" + nf0.format(v);
const mem = i => D.members[i] || { name: "?" };
const short = n => { const p = String(n).split(/\s+/).filter(w => !/^(Hon\.?|Jr\.?|Sr\.?|II|III|IV|Mr\.?|Mrs\.?|Ms\.?|Dr\.?)$/.test(w)); return p.length > 1 ? p[0] + " " + p[p.length - 1] : n; };
const party = m => m.chamber === "executive" ? "Reg." : (m.party || "I") + (m.state ? "-" + m.state : "");
const pspan = m => `<span class="party ${esc(m.chamber === "executive" ? "E" : m.party || "I")}">${esc(party(m))}</span>`;
const TH = () => D.themes || {};
const thName = k => TH()[k] || k;
const tickLink = t => `<a class="tick" href="#t.${encodeURIComponent(t)}">${esc(t)}</a>`;
function seg(id, opts, val) { return `<div class="seg" id="${id}" role="group">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${String(v) === String(val)}">${l}</button>`).join("")}</div>`; }
function onSeg(id, fn) { const el = document.getElementById(id); if (el) el.addEventListener("click", e => { const b = e.target.closest("button"); if (b) fn(b.dataset.v); }); }
function killCharts() { charts.forEach(c => { try { c.remove(); } catch (e) {} }); charts = []; }
function bindRows(root) { root.querySelectorAll("tr[data-t]").forEach(tr => tr.addEventListener("click", e => { if (e.target.closest("a")) return; location.hash = "t." + encodeURIComponent(tr.dataset.t); })); }

// Handelstage → Datum (Zukunft: Wochentage, ohne Feiertage = ca.)
function dateAt(i) {
  if (i <= LAST) return DATES[i];
  const d = new Date(DATES[LAST] + "T12:00:00Z"); let k = i - LAST;
  while (k > 0) { d.setUTCDate(d.getUTCDate() + 1); const w = d.getUTCDay(); if (w && w < 6) k--; }
  return d.toISOString().slice(0, 10);
}
// Status eines Kaufs/Signals für die gewählte Haltedauer
function status(s, h = S.h) {
  const H = HD[h];
  if (s.i == null) return { open: true, pending: true, left: H, exit: dateAt(LAST + 1 + H), prog: 0 };
  const left = s.i + H - LAST;
  return { open: left > 0, pending: false, left, exit: dateAt(s.i + H), prog: Math.min(1, (LAST - s.i) / H) };
}
const isOpen = (s, h) => status(s, h).open;

// ------------------------------------------------------------------ data
async function j(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " → HTTP " + r.status); return r.json(); }
async function load() {
  const [dash, meta, sec] = await Promise.all([j("data/dash.json"), j("data/meta.json"), j("data/sectors.json").catch(() => ({}))]);
  D = dash; META = meta; DATES = D.dates; LAST = DATES.length - 1; D.themes = sec.themes || {};
  $("#stand").textContent = `Kurse bis ${dDE(D.asof)} · täglich aktualisiert · ${nf0.format(META.trades)} gemeldete Trades seit 2020`;
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
function stats(list, h) {
  const done = list.filter(s => s["r" + h] != null && s["s" + h] != null);
  const r = done.map(s => s["r" + h]), ex = done.map(s => s["r" + h] - s["s" + h]);
  const exq = done.filter(s => s["q" + h] != null).map(s => s["r" + h] - s["q" + h]);
  const years = {};
  for (const s of done) { const y = s.d.slice(0, 4); (years[y] = years[y] || []).push(s); }
  return {
    n: done.length, r: mean(r), ex: mean(ex), exq: mean(exq),
    hit: done.length ? 100 * r.filter(v => v > 0).length / done.length : null,
    beat: done.length ? 100 * ex.filter(v => v > 0).length / done.length : null,
    med: (() => { if (!ex.length) return null; const b = [...ex].sort((a, b) => a - b); const m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; })(),
    years: Object.keys(years).sort().reverse().map(y => { const a = years[y]; const e = a.map(s => s["r" + h] - s["s" + h]); return { y, n: a.length, r: mean(a.map(s => s["r" + h])), ex: mean(e), beat: 100 * e.filter(v => v > 0).length / a.length }; }),
  };
}
// Kapitalkurve ab Startdatum neu normieren
function curveFrom(v, startDate) {
  const cd = D.curveDates; let k = 0;
  if (startDate) while (k < cd.length - 1 && cd[k] < startDate) k++;
  const base = v[k], bs = D.bench.SPY[k], bq = D.bench.QQQ ? D.bench.QQQ[k] : null;
  const pts = [];
  for (let i = k; i < v.length && i < cd.length; i++) pts.push({ time: cd[i], s: v[i] / base, spy: D.bench.SPY[i] / bs, qqq: bq ? D.bench.QQQ[i] / bq : null });
  return pts;
}
function cstats(pts, key) {
  if (pts.length < 2) return { cagr: null, mdd: null, tot: null };
  const yrs = (Date.parse(pts[pts.length - 1].time) - Date.parse(pts[0].time)) / 864e5 / 365.25;
  let peak = 0, mdd = 0;
  for (const p of pts) { const v = p[key]; if (v == null) continue; peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1); }
  const end = pts[pts.length - 1][key];
  return { cagr: end == null ? null : 100 * (Math.pow(end, 1 / yrs) - 1), mdd: 100 * mdd, tot: end == null ? null : 100 * (end - 1) };
}

// ------------------------------------------------------------------ Bausteine
function verdict(st, what) {
  if (!st.n) return `<div class="verdict">Für diese Einstellung gibt es noch keine abgeschlossenen ${what}.</div>`;
  const good = st.ex > 0;
  return `<div class="verdict">${what} brachten über <b>${S.h} Tage</b> im Schnitt <b class="${cls(st.r)}">${pct(st.r)}</b>, das sind <b class="${cls(st.ex)}">${pct(st.ex)}</b> ${good ? "mehr" : "weniger"} als der S&amp;P 500 im selben Zeitraum. <b>${q(st.beat)}</b> schlugen den S&amp;P (${nf0.format(st.n)} abgeschlossene Fälle).</div>`;
}
function tiles(st, pts, label) {
  const a = cstats(pts, "s"), sp = cstats(pts, "spy"), qq = cstats(pts, "qqq");
  return `<div class="tiles">
    <div class="tile"><div class="k">Ø pro ${label} vs S&amp;P</div><div class="v ${cls(st.ex)}">${pct(st.ex)}</div><div class="d">Ø Rendite ${pct(st.r)} · Median vs S&amp;P ${pct(st.med)}</div></div>
    <div class="tile"><div class="k">Schlägt den S&amp;P</div><div class="v">${q(st.beat)}</div><div class="d">im Plus: ${q(st.hit)} · vs Nasdaq ${pct(st.exq)}</div></div>
    <div class="tile"><div class="k">Portfolio pro Jahr</div><div class="v ${cls(a.cagr - sp.cagr)}">${pct(a.cagr)}</div><div class="d">S&amp;P ${pct(sp.cagr)} · Nasdaq ${pct(qq.cagr)}</div></div>
    <div class="tile"><div class="k">Max. Rückgang</div><div class="v neg">${pct(a.mdd)}</div><div class="d">S&amp;P ${pct(sp.mdd)}</div></div>
    <div class="tile"><div class="k">Abgeschlossen</div><div class="v">${nf0.format(st.n)}</div><div class="d">${label === "Signal" ? "Signale" : "Käufe"} mit ${S.h}-Tage-Ergebnis</div></div>
  </div>`;
}
function eqPanel(id, title) {
  return `<div class="panel"><div class="panel-h"><h2>${title}</h2><div class="legend-row"><span><span class="sw" style="background:var(--accent)"></span>Strategie</span><span><span class="sw" style="background:var(--chart-spy)"></span>S&amp;P 500</span><span><span class="sw dash" style="border-color:var(--ink-2)"></span>Nasdaq 100</span></div></div><div class="panel-b"><div class="chart sm" id="${id}"></div><p class="hint" style="margin:8px 0 0">Alle offenen Positionen gleich gewichtet, Ausstieg nach ${S.h} Tagen, ungenutztes Geld bleibt in Cash (0 %).</p></div></div>`;
}
function chartOpts(el, pf) {
  return { autoSize: true,
    layout: { background: { type: "solid", color: tok("--surface") }, textColor: tok("--muted"), fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: tok("--line") } },
    rightPriceScale: { borderColor: tok("--line") }, timeScale: { borderColor: tok("--line") }, crosshair: { mode: 0 },
    localization: { locale: "de-DE", ...(pf ? { priceFormatter: pf } : {}) }, handleScroll: false, handleScale: false };
}
function drawEq(id, pts) {
  const el = document.getElementById(id); if (!el) return;
  if (!window.LightweightCharts) { el.innerHTML = `<div class="empty">Chart-Bibliothek nicht geladen.</div>`; return; }
  if (pts.length < 2) { el.innerHTML = `<div class="empty">Noch zu wenig Daten.</div>`; return; }
  const c = LightweightCharts.createChart(el, chartOpts(el, v => (v > 0 ? "+" : "") + nf0.format(v) + " %")); charts.push(c);
  const add = (key, color, style, title) => { const s = c.addLineSeries({ color, lineWidth: 2, lineStyle: style, priceLineVisible: false, lastValueVisible: true, title }); s.setData(pts.filter(p => p[key] != null).map(p => ({ time: p.time, value: (p[key] - 1) * 100 }))); };
  add("spy", tok("--chart-spy"), 0, "S&P");
  if (pts[0].qqq != null) add("qqq", tok("--ink-2"), 2, "Nasdaq");
  add("s", tok("--accent"), 0, "Strategie");
  c.timeScale().fitContent();
}
function yearTable(st) {
  if (!st.years.length) return "";
  return `<div class="panel"><div class="panel-h"><h2>Nach Jahr</h2><span class="sub">Ø je ${S.h}-Tage-Trade</span></div><div class="tbl-wrap"><table><thead><tr><th>Jahr</th><th class="n">Anzahl</th><th class="n">Ø Rendite</th><th class="n">Ø vs S&amp;P</th><th class="n">schlägt S&amp;P</th></tr></thead><tbody>${st.years.map(y => `<tr><td class="num">${y.y}</td><td class="n">${y.n}</td><td class="n">${pc(y.r)}</td><td class="n">${pc(y.ex)}</td><td class="n">${q(y.beat)}</td></tr>`).join("")}</tbody></table></div></div>`;
}
function liveNums(s, h) {
  const st = status(s, h);
  const ex = s.rn != null && s.sn != null ? s.rn - s.sn : null;
  return `<div class="cnums">
    <div><span class="k">seit Einstieg</span><b class="${cls(s.rn)}">${st.pending ? "–" : pct(s.rn)}</b></div>
    <div><span class="k">vs S&amp;P</span><b class="${cls(ex)}">${st.pending ? "–" : pct(ex)}</b></div>
    <div><span class="k">Verkauf ${st.pending ? "ca." : st.exit > DATES[LAST] ? "ca." : ""}</span><b>${dS(st.exit)}</b></div>
  </div>
  <div class="prog" title="${st.pending ? "Einstieg zum nächsten Schlusskurs" : `noch ${st.left} Handelstage`}"><i style="width:${Math.round(st.prog * 100)}%"></i></div>
  <div class="hint">${st.pending ? "Gerade gemeldet – Einstieg zum nächsten Schlusskurs" : `Einstieg ${dDE(DATES[s.i])} · noch ${st.left} Handelstage`}</div>`;
}
function pastTable(list, h, key, cols) {
  const done = list.filter(s => s["r" + h] != null);
  const lim = S.show[key] || 25;
  return `<div class="panel"><div class="panel-h"><h2>Vergangene Fälle</h2><span class="sub">${nf0.format(done.length)} abgeschlossen · Klick öffnet den Chart</span></div>
  <div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Aktie</th>${cols.map(c => `<th>${c[0]}</th>`).join("")}<th class="n">Rendite</th><th class="n">S&amp;P</th><th class="n">vs S&amp;P</th></tr></thead>
  <tbody>${done.slice(0, lim).map(s => `<tr class="click" data-t="${esc(s.t)}"><td class="num">${dDE(s.d)}</td><td>${tickLink(s.t)}</td>${cols.map(c => `<td style="white-space:normal;min-width:160px">${c[1](s)}</td>`).join("")}<td class="n">${pc(s["r" + h])}</td><td class="n mut">${pct(s["s" + h])}</td><td class="n">${pc(s["r" + h] - s["s" + h])}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">Noch keine abgeschlossenen Fälle.</td></tr>`}</tbody></table></div>
  ${done.length > lim ? `<div class="more"><button class="btn" data-more="${key}">Weitere ${Math.min(50, done.length - lim)} anzeigen</button></div>` : ""}</div>`;
}
function bindMore(root, rerender) { root.querySelectorAll("[data-more]").forEach(b => b.addEventListener("click", () => { const k = b.dataset.more; S.show[k] = (S.show[k] || (k[0] === "o" ? 15 : 25)) + 50; rerender(true); })); }
const names = (ids, cmset, max = 5) => ids.slice(0, max).map(i => { const m = mem(i); return `<span title="${esc(m.name)}${m.c ? " · " + esc(m.c.join(", ")) : ""}">${esc(short(m.name))}${cmset && cmset.has(i) ? '<span class="cmk" title="sitzt in einem Ausschuss für diese Branche"> ★</span>' : ""}</span>`; }).join(", ") + (ids.length > max ? ` +${ids.length - max}` : "");
function helpBox(items) { return `<details class="help panel" style="padding:12px 16px"><summary>So funktioniert die Strategie</summary><ul>${items.map(x => `<li>${x}</li>`).join("")}</ul></details>`; }
function keepScroll(fn) { const y = window.scrollY; fn(); window.scrollTo(0, y); }

// ================================================================== 1) CLUSTER
function viewCluster(app, keep) {
  const h = S.h, C = D.clusters[S.mn];
  const all = C.signals;
  const isDip = s => s.fh != null && s.fh <= D.dip;
  const list = S.cm === "cm" ? all.filter(s => s.cm.length) : S.cm === "dip" ? all.filter(isDip) : all;
  const open = list.filter(s => isOpen(s, h));
  const st = stats(list, h);
  const pts = curveFrom(C.curves[h + (S.cm === "cm" ? "c" : S.cm === "dip" ? "d" : "")] || C.curves[h]);
  const render = () => {
    app.innerHTML = `
    <div class="view-head"><div><div class="eyebrow">Strategie 1</div><h1>Cluster-Käufe</h1><p>Mehrere Politiker kaufen innerhalb von ${D.win} Tagen dieselbe Aktie. Gekauft wird zum Schlusskurs nach der Meldung, verkauft nach ${h} Tagen.</p></div>
      <div class="controls"><label class="ctl"><span>Mindestens Käufer</span>${seg("mn", [["2", "2"], ["3", "3"], ["4", "4"]], S.mn)}</label>
      <label class="ctl"><span>Filter</span>${seg("cmf", [["all", "Alle"], ["cm", "Ausschuss-Bonus"], ["dip", `Dip (≥${-D.dip} % unter Hoch)`]], S.cm)}</label></div></div>
    <h3 class="sec">Jetzt aktiv <small>${open.length ? `${open.length} offene Signal${open.length === 1 ? "" : "e"} bei ${h} Tagen Haltedauer` : ""}</small></h3>
    ${open.length ? `<div class="cards">${open.map(s => clusterCard(s, h)).join("")}</div>` : `<div class="panel empty">Gerade kein offenes Signal. Neue Signale kommen als Benachrichtigung.</div>`}
    <h3 class="sec">Backtest seit 2020 <small>${S.mn}+ Käufer · ${S.cm === "cm" ? "nur mit Ausschuss-Bonus" : S.cm === "dip" ? `nur Dip-Cluster (≥${-D.dip} % unter 52W-Hoch)` : "alle Cluster"} · ${h} Tage halten</small></h3>
    ${S.cm === "dip" ? `<div class="note"><b>Ehrlich:</b> Dip-Cluster waren in unserer Forschung der einzige Bereich, der in beiden Testzeiträumen (2020–23 und 2024–26) in über 60 % der Fälle den S&amp;P geschlagen hat, am besten mit 2+ Käufern und 30 Tagen Haltedauer. Es sind aber nur rund 10–20 Fälle pro Jahr, ein großer Teil stammt aus Erholungen nach Crashs (2020, April 2025), und 2026 lag die Quote nur bei etwa 50 %. Als Zusatzfilter sinnvoll, nicht als Garantie.</div>` : ""}
    ${verdict(st, "Cluster-Signale")}
    ${tiles(st, pts, "Signal")}
    ${eqPanel("eq", "Kapitalkurve")}
    <div class="grid2">${yearTable(st)}${cmCompare(all, h)}</div>
    ${pastTable(list, h, "cl" + S.mn + S.cm, [["Käufer", s => `<b>${s.n}</b> · ${names(s.m, new Set(s.cm), 4)}`]])}
    ${helpBox([
      `Signal: mindestens ${S.mn} verschiedene Politiker melden innerhalb von ${D.win} Tagen einen Kauf derselben Aktie, und es gibt mehr Käufer als Verkäufer.`,
      `Einstieg zum Schlusskurs des ersten Handelstags nach der auslösenden Meldung, Ausstieg nach ${h} Kalendertagen (${HD[h]} Handelstage).`,
      `Pro Aktie höchstens ein Signal je ${D.cooldown} Handelstage. Dividenden-Reinvestitionen zählen nicht als Kauf.`,
      `<span class="badge dip">▼ Dip</span>: die Aktie notiert beim Signal ${-D.dip} % oder mehr unter ihrem 52-Wochen-Hoch.`,
      `<span class="cmk">★ Ausschuss-Bonus</span>: mindestens ein Käufer sitzt in einem Ausschuss, der die Branche der Aktie beaufsichtigt (aktuelle Mitgliedschaften).`,
    ])}`;
    onSeg("mn", v => { S.mn = v; save(); keepScroll(() => viewCluster(app, true)); });
    onSeg("cmf", v => { S.cm = v; save(); keepScroll(() => viewCluster(app, true)); });
    bindRows(app); bindMore(app, () => keepScroll(() => viewCluster(app, true)));
    drawEq("eq", pts);
  };
  killCharts(); render();
}
function clusterCard(s, h) {
  const cm = new Set(s.cm), t = D.tickers[s.t] || {};
  return `<a class="card" href="#t.${encodeURIComponent(s.t)}">
    <div class="card-h"><div class="ctk"><b>${esc(s.t)}</b><span>${esc(t.a || "")}</span></div>
      <div style="display:grid;gap:4px;justify-items:end">${s.i == null || LAST - s.i < 5 ? '<span class="badge new">neu</span>' : ""}${s.fh != null && s.fh <= D.dip ? `<span class="badge dip">▼ Dip ${nf0.format(s.fh)} %</span>` : ""}${cm.size ? '<span class="badge cm">★ Ausschuss-Bonus</span>' : ""}</div></div>
    <div class="cwho"><b>${s.n} Käufer</b>${s.o ? ` · <span class="neg">${s.o} Verkäufer</span>` : ""} · bis ${dS(s.d)} gemeldet · ~${money(s.vol)}${s.fh != null ? ` · ${nf0.format(s.fh)} % zum 52W-Hoch` : ""}<br>${names(s.m, cm, 6)}</div>
    ${liveNums(s, h)}</a>`;
}
function cmCompare(all, h) {
  const a = stats(all.filter(s => s.cm.length), h), b = stats(all.filter(s => !s.cm.length), h);
  const dp = s => s.fh != null && s.fh <= D.dip, c = stats(all.filter(dp), h), d = stats(all.filter(s => !dp(s)), h);
  return `<div class="panel"><div class="panel-h"><h2>Teilbereiche im Vergleich</h2><span class="sub">${S.mn}+ Käufer · ${h} Tage</span></div><div class="tbl-wrap"><table><thead><tr><th></th><th class="n">Anzahl</th><th class="n">Ø Rendite</th><th class="n">Ø vs S&amp;P</th><th class="n">schlägt S&amp;P</th></tr></thead><tbody>
    <tr><td><span class="cmk">★</span> mit Bonus</td><td class="n">${a.n}</td><td class="n">${pc(a.r)}</td><td class="n">${pc(a.ex)}</td><td class="n">${q(a.beat)}</td></tr>
    <tr><td>ohne Bonus</td><td class="n">${b.n}</td><td class="n">${pc(b.r)}</td><td class="n">${pc(b.ex)}</td><td class="n">${q(b.beat)}</td></tr>
    <tr><td><span class="badge dip">▼ Dip</span> ≥${-D.dip} % unter Hoch</td><td class="n">${c.n}</td><td class="n">${pc(c.r)}</td><td class="n">${pc(c.ex)}</td><td class="n">${q(c.beat)}</td></tr>
    <tr><td>kein Dip</td><td class="n">${d.n}</td><td class="n">${pc(d.r)}</td><td class="n">${pc(d.ex)}</td><td class="n">${q(d.beat)}</td></tr></tbody></table></div>
    <p class="hint" style="margin:0;padding:10px 16px">Ausschuss-Mitgliedschaften sind nur für den aktuellen Kongress (seit 2025) verfügbar; ältere Signale werden mit den heutigen Ausschüssen bewertet.</p></div>`;
}

// ================================================================== 2) AUSSCHUSS-INSIDER
function viewCommittee(app) {
  const h = S.h, B = D.committee.buys;
  const open = B.filter(s => isOpen(s, h));
  const st = stats(B, h);
  const pts = curveFrom(D.committee.curves[h], D.committeeStart);
  // nach Branche
  const byTh = {};
  for (const s of B) for (const t of s.th) (byTh[t] = byTh[t] || []).push(s);
  const thRows = Object.entries(byTh).map(([k, a]) => ({ k, ...stats(a, h) })).filter(x => x.n).sort((a, b) => b.ex - a.ex);
  app.innerHTML = `
    <div class="view-head"><div><div class="eyebrow">Strategie 2</div><h1>Ausschuss-Insider</h1><p>Politiker kauft eine Aktie aus genau der Branche, die sein Ausschuss beaufsichtigt, z.&nbsp;B. ein Mitglied des Streitkräfte-Ausschusses kauft Rüstung. Verkauf nach ${h} Tagen.</p></div></div>
    <h3 class="sec">Jetzt aktiv <small>${open.length} offene Käufe bei ${h} Tagen Haltedauer</small></h3>
    ${open.length ? openTable(open, h, true, "ocm") : `<div class="panel empty">Gerade keine offenen Ausschuss-Käufe.</div>`}
    <h3 class="sec">Backtest seit ${dDE(D.committeeStart)} <small>${h} Tage halten</small></h3>
    ${verdict(st, "Ausschuss-Käufe")}
    ${tiles(st, pts, "Kauf")}
    ${eqPanel("eq", "Kapitalkurve seit 2025")}
    <div class="grid2">
      <div class="panel"><div class="panel-h"><h2>Nach Branche</h2><span class="sub">${h} Tage</span></div><div class="tbl-wrap"><table><thead><tr><th>Branche</th><th class="n">Käufe</th><th class="n">Ø vs S&amp;P</th><th class="n">schlägt S&amp;P</th></tr></thead><tbody>${thRows.map(x => `<tr><td>${esc(thName(x.k))}</td><td class="n">${x.n}</td><td class="n">${pc(x.ex)}</td><td class="n">${q(x.beat)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">–</td></tr>`}</tbody></table></div></div>
      ${yearTable(st)}
    </div>
    ${pastTable(B, h, "cm", [["Politiker · Ausschuss", s => { const m = mem(s.m); return `<b>${esc(short(m.name))}</b> ${pspan(m)}<br><span class="hint">${esc(s.th.map(thName).join(", "))}</span>`; }]])}
    <div class="note"><b>Ehrlicher Hinweis:</b> Ausschuss-Käufe allein schlagen den Markt in unseren Tests nicht verlässlich. Stark waren sie vor allem <b>zusammen mit einem Cluster</b> (siehe Filter „Nur mit Ausschuss-Bonus" bei Cluster). Mitgliedschaften stammen aus dem aktuellen Kongress, daher startet der Test im Januar 2025.</div>
    ${helpBox([
      "Ausschüsse und ihre Branchen: z. B. Streitkräfte → Verteidigung, Banken/Finanzen → Banken & Versicherer, Energie & Handel → Gesundheit, Energie, Tech, Landwirtschaft → Agrar & Lebensmittel.",
      "Bei Regierungsmitgliedern zählt die Behörde (z. B. Verteidigungsministerium → Verteidigung).",
      "Branchen der Aktien laut Nasdaq-Klassifikation, ergänzt um große Rüstungs- und Agrarwerte.",
      `Einstieg zum Schlusskurs nach der Meldung, Verkauf nach ${h} Tagen. Dividenden-Reinvestitionen zählen nicht.`,
    ])}`;
  bindRows(app); bindMore(app, () => keepScroll(() => viewCommittee(app)));
  drawEq("eq", pts);
}
function openTable(list, h, committee, key) {
  const lim = S.show[key] || 15, all = list; list = list.slice(0, lim);
  return `<div class="panel"><div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Aktie</th><th>Politiker</th>${committee ? "<th>Ausschuss-Branche</th>" : ""}<th class="n">Betrag</th><th class="n">seit Einstieg</th><th class="n">vs S&amp;P</th><th class="n">Verkauf</th></tr></thead><tbody>
  ${list.map(s => { const m = mem(s.m), st = status(s, h), ex = s.rn != null && s.sn != null ? s.rn - s.sn : null; const t = D.tickers[s.t] || {};
    return `<tr class="click" data-t="${esc(s.t)}"><td class="num">${dDE(s.d)}${s.i == null || LAST - s.i < 5 ? ' <span class="badge new">neu</span>' : ""}</td><td>${tickLink(s.t)}<div class="hint" style="max-width:220px;overflow:hidden;text-overflow:ellipsis">${esc(t.a || "")}</div></td><td><b>${esc(short(m.name))}</b> ${pspan(m)}${committee && m.c ? `<div class="hint" style="max-width:260px;overflow:hidden;text-overflow:ellipsis" title="${esc(m.c.join(", "))}">${esc(m.c.slice(0, 2).join(", "))}</div>` : ""}</td>${committee ? `<td>${esc((s.th || []).map(thName).join(", "))}</td>` : ""}<td class="n">${amt(s.lo, s.hi)}</td><td class="n">${st.pending ? '<span class="mut">Einstieg folgt</span>' : pc(s.rn)}</td><td class="n">${st.pending ? "–" : pc(ex)}</td><td class="n">${dS(st.exit)}<div class="hint">noch ${st.left} HT</div></td></tr>`; }).join("")}
  </tbody></table></div>${all.length > lim ? `<div class="more"><button class="btn" data-more="${key}">Weitere ${Math.min(50, all.length - lim)} anzeigen</button></div>` : ""}</div>`;
}

// ================================================================== 3) TOP-POLITIKER
function viewTop(app) {
  const h = S.h, T = D.top[h];
  const top10 = new Set(T.rank.slice(0, D.topN).map(x => x.m));
  const openAll = D.topBuys.filter(s => top10.has(s.m) && isOpen(s, h));
  const per = {}; const open = openAll.filter(s => (per[s.m] = (per[s.m] || 0) + 1) <= 5);
  const hidden = Object.entries(per).filter(([, n]) => n > 5).map(([m, n]) => `${esc(short(mem(m).name))} +${n - 5}`);
  const st = stats(T.follow, h);
  const pts = curveFrom(T.curve);
  app.innerHTML = `
    <div class="view-head"><div><div class="eyebrow">Strategie 3</div><h1>Top-Politiker</h1><p>Wer hat mit seinen Käufen über ${h} Tage am meisten besser abgeschnitten als der S&amp;P 500? Neue Käufe der Top ${D.topN} werden zum Schlusskurs nach der Meldung gekauft.</p></div></div>
    <h3 class="sec">Neue Käufe der Top ${D.topN} <small>${openAll.length} offen bei ${h} Tagen Haltedauer${hidden.length ? ` · höchstens 5 je Politiker gezeigt (${hidden.join(", ")} weitere)` : ""}</small></h3>
    ${open.length ? openTable(open, h, false, "otp") : `<div class="panel empty">Die Top ${D.topN} haben zuletzt nichts gekauft.</div>`}
    <h3 class="sec">Rangliste <small>Käufe mit ${h}-Tage-Ergebnis, mindestens ${D.topMin}</small></h3>
    <div class="panel"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Politiker</th><th class="n">Käufe</th><th class="n">Ø Rendite</th><th class="n">Ø vs S&amp;P</th><th class="n">schlägt S&amp;P</th><th class="n" title="Ø vs S&amp;P, bei wenigen Käufen Richtung 0 gezogen">Score</th><th>Ausschüsse</th></tr></thead><tbody>
    ${T.rank.map((x, k) => { const m = mem(x.m); return `<tr${k < D.topN ? "" : ' class="mut"'}><td class="rank">${k + 1}</td><td><b>${esc(m.name)}</b> ${pspan(m)}${m.chamber === "executive" ? `<div class="hint">${esc(m.office || m.agency || "")}</div>` : ""}</td><td class="n">${x.n}</td><td class="n">${pc(x.r)}</td><td class="n">${pc(x.ex)}</td><td class="n">${q(x.hit)}</td><td class="n"><b>${pct(x.score)}</b></td><td style="white-space:normal;min-width:200px;font-size:12px;color:var(--ink-2)">${esc((m.c || []).slice(0, 3).join(", ")) || "–"}</td></tr>`; }).join("")}
    </tbody></table></div><p class="hint" style="margin:0;padding:10px 16px">Score = Summe der Übertreffung ÷ (Käufe + 10). So landet niemand mit zwei Glückstreffern oben. Die ersten ${D.topN} gelten als Top-Politiker, die übrigen sind ausgegraut.</p></div>
    <h3 class="sec">Backtest „Top ${D.topN} folgen" <small>ohne Blick in die Zukunft</small></h3>
    ${verdict(st, "Käufe der jeweiligen Top-Politiker")}
    ${tiles(st, pts, "Kauf")}
    ${eqPanel("eq", "Kapitalkurve")}
    ${yearTable(st)}
    ${pastTable(T.follow, h, "tp" + h, [["Politiker", s => { const m = mem(s.m); return `${esc(short(m.name))} ${pspan(m)}`; }]])}
    <div class="note"><b>Wichtig:</b> Die Rangliste oben nutzt alle Daten bis heute. Der Backtest dagegen kennt zu jedem Zeitpunkt nur die Käufe, die damals schon abgeschlossen waren: Er kauft, sobald ein Politiker <b>zu diesem Zeitpunkt</b> unter den Top ${D.topN} war. Das zeigt, ob gute Bilanzen sich fortsetzen.</div>`;
  bindRows(app); bindMore(app, () => keepScroll(() => viewTop(app)));
  drawEq("eq", pts);
}

// ================================================================== Aktie
async function viewTicker(app, t) {
  const info = D.tickers[t] || {};
  app.innerHTML = `<button type="button" class="btn ghost" id="back" style="justify-self:start;padding-left:0">← Zurück</button>
  <div class="view-head"><div><div class="eyebrow">Aktie${info.ind ? " · " + esc(info.ind) : ""}</div><h1 style="font-family:var(--f-mono)">${esc(t)}</h1><p>${esc(info.a || "")}${info.th && info.th.length ? ` · Branche: ${esc(info.th.map(thName).join(", "))}` : ""}</p></div></div>
  <div id="sigs"></div>
  <div class="panel"><div class="panel-h"><h2>Kurs mit Politiker-Trades</h2><div class="legend-row"><span><span class="mk up"></span>Kauf (Tag nach Meldung)</span><span><span class="mk dn"></span>Verkauf</span><span><span class="sw" style="background:var(--accent)"></span>Cluster-Signal</span></div></div><div class="panel-b"><div class="chart" id="pc"><div class="loading">Lade Kurs …</div></div></div></div>
  <div id="trl"></div>`;
  $("#back").addEventListener("click", () => history.length > 1 ? history.back() : (location.hash = "cluster"));
  const sigs = D.clusters["2"].signals.filter(s => s.t === t);
  const h = S.h;
  if (sigs.length) $("#sigs").innerHTML = `<div class="panel"><div class="panel-h"><h2>Cluster-Signale in ${esc(t)}</h2><span class="sub">2+ Käufer · ${h} Tage</span></div><div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th class="n">Käufer</th><th>Wer</th><th class="n">Rendite</th><th class="n">vs S&amp;P</th></tr></thead><tbody>${sigs.map(s => { const o = isOpen(s, h); return `<tr><td class="num">${dDE(s.d)}</td><td class="n">${s.n}</td><td style="white-space:normal">${names(s.m, new Set(s.cm), 8)}</td><td class="n">${o ? `<span class="badge cm">offen</span> ${pc(s.rn)}` : pc(s["r" + h])}</td><td class="n">${o ? pc(s.rn != null && s.sn != null ? s.rn - s.sn : null) : pc(s["r" + h] != null ? s["r" + h] - s["s" + h] : null)}</td></tr>`; }).join("")}</tbody></table></div></div>`;
  const { p, tr } = await loadPx(t);
  if (location.hash.slice(1) !== "t." + encodeURIComponent(t) && decodeURIComponent(location.hash.slice(1)) !== "t." + t) return;
  const el = $("#pc");
  tr.sort((a, b) => a[3] < b[3] ? 1 : -1);
  $("#trl").innerHTML = `<div class="panel"><div class="panel-h"><h2>Gemeldete Trades</h2><span class="sub">${tr.length} seit 2020</span></div><div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Trade</th><th>Politiker</th><th></th><th class="n">Betrag</th></tr></thead><tbody>${tr.slice(0, 60).map(x => { const m = mem(x[0]); return `<tr${x[6] ? ' class="mut" title="Dividenden-Reinvestition, zählt nicht"' : ""}><td class="num">${dDE(x[3])}</td><td class="num">${dDE(x[2])}</td><td>${esc(m.name)} ${m.name !== "?" ? pspan(m) : ""}</td><td><span class="side ${x[1]}">${x[1] === "P" ? "KAUF" : "VERKAUF"}</span></td><td class="n">${amt(x[4], x[5])}</td></tr>`; }).join("")}</tbody></table></div></div>`;
  el.innerHTML = "";
  if (!p) { el.innerHTML = `<div class="empty">Keine Kursdaten für ${esc(t)}.</div>`; return; }
  if (!window.LightweightCharts) { el.innerHTML = `<div class="empty">Chart-Bibliothek nicht geladen.</div>`; return; }
  const c = LightweightCharts.createChart(el, { ...chartOpts(el), handleScroll: true, handleScale: true }); charts.push(c);
  const line = tok("--chart-line");
  const s = c.addAreaSeries({ lineColor: line, topColor: line + "30", bottomColor: line + "00", lineWidth: 2, priceLineVisible: false });
  const data = []; for (let k = 0; k < p.v.length; k++) if (p.v[k] != null) data.push({ time: DATES[p.f + k], value: p.v[k] });
  s.setData(data);
  const first = DATES[p.f], agg = new Map();
  const nextDay = d => { let lo = 0, hi = DATES.length; while (lo < hi) { const m = (lo + hi) >> 1; if (DATES[m] <= d) lo = m + 1; else hi = m; } return lo <= LAST ? DATES[lo] : null; };
  for (const x of tr) { if (x[6]) continue; const d = nextDay(x[3]); if (!d || d < first) continue; const k = d + x[1]; agg.set(k, (agg.get(k) || 0) + 1); }
  const mk = [];
  for (const [k, n] of agg) { const d = k.slice(0, 10), sd = k.slice(10); mk.push({ time: d, position: sd === "P" ? "belowBar" : "aboveBar", color: sd === "P" ? tok("--pos") : tok("--neg"), shape: sd === "P" ? "arrowUp" : "arrowDown", text: n > 1 ? n + "×" : "" }); }
  for (const g of sigs) if (g.i != null && DATES[g.i] >= first) mk.push({ time: DATES[g.i], position: "belowBar", color: tok("--accent"), shape: "circle", text: "Cluster " + g.n });
  mk.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
  s.setMarkers(mk);
  const from = DATES[Math.max(p.f, LAST - 520)];
  c.timeScale().setVisibleRange({ from, to: DATES[LAST] });
}

// ------------------------------------------------------------------ Router
function route() {
  killCharts();
  const h = decodeURIComponent(location.hash.slice(1)) || "cluster";
  const v = h.split(".")[0];
  const tab = { cluster: "cluster", ausschuss: "ausschuss", top: "top" }[v] || (v === "t" ? "" : "cluster");
  document.querySelectorAll("#tabs a").forEach(a => a.toggleAttribute("aria-current", false));
  if (tab) $(`#tabs a[data-v="${tab}"]`)?.setAttribute("aria-current", "page");
  document.querySelectorAll("#hold button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === S.h)));
  const app = $("#app");
  try {
    if (v === "t") viewTicker(app, h.slice(2));
    else if (v === "ausschuss") viewCommittee(app);
    else if (v === "top") viewTop(app);
    else viewCluster(app);
  } catch (e) { console.error(e); app.innerHTML = `<div class="err">Fehler beim Anzeigen: ${esc(e.message)}</div>`; }
}
onSeg("hold", v => { S.h = v; save(); const y = window.scrollY; route(); window.scrollTo(0, y); });
window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => route());
load().then(route).catch(e => { console.error(e); $("#app").innerHTML = `<div class="err"><b>Daten konnten nicht geladen werden.</b><br>${esc(e.message)}</div>`; });
})();
