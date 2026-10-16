/* Capitol Signals – nur noch Dip-Cluster.
   Signal: 2+ Politiker kaufen dieselbe Aktie innerhalb von 30 Tagen, Aktie ≥40 % unter 52-Wochen-Hoch.
   Kauf zum Schlusskurs nach der Meldung, Verkauf nach 30 Tagen. Daten: data/dash.json (signals.py). */
(() => {
"use strict";
let D, META, LAST, DATES, RU;
const PX = new Map(), PXB = new Map(), TR = new Map();
let charts = [];
const S = { show: 25, depot: null };
try { S.depot = Number(localStorage.getItem("cs-depot")) || null; } catch (e) {}

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
  const [dash, meta] = await Promise.all([j("data/dash.json"), j("data/meta.json")]);
  D = dash; META = meta; DATES = D.dates; LAST = DATES.length - 1; RU = D.rules;
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
function curvePts() {
  const cd = D.curveDates, v = D.curve, pts = [];
  for (let i = 0; i < v.length && i < cd.length; i++) pts.push({ time: cd[i], s: v[i], spy: D.bench.SPY[i], qqq: D.bench.QQQ ? D.bench.QQQ[i] : null });
  return pts;
}
function cstats(pts, key) {
  if (pts.length < 2) return {};
  const yrs = (Date.parse(pts[pts.length - 1].time) - Date.parse(pts[0].time)) / 864e5 / 365.25;
  let peak = 0, mdd = 0;
  for (const p of pts) { const v = p[key]; if (v == null) continue; peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1); }
  const end = pts[pts.length - 1][key];
  return { cagr: end == null ? null : 100 * (Math.pow(end, 1 / yrs) - 1), mdd: 100 * mdd };
}
function chartOpts(pf) {
  return { autoSize: true,
    layout: { background: { type: "solid", color: tok("--surface") }, textColor: tok("--muted"), fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: tok("--line") } },
    rightPriceScale: { borderColor: tok("--line") }, timeScale: { borderColor: tok("--line") }, crosshair: { mode: 0 },
    localization: { locale: "de-DE", ...(pf ? { priceFormatter: pf } : {}) } };
}

// ================================================================== Hauptseite
function viewMain(app) {
  const open = D.signals.filter(s => status(s).open);
  const st = stats(D.signals);
  const pts = curvePts();
  const a = cstats(pts, "s"), sp = cstats(pts, "spy");
  const cmp = D.compare;
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Strategie</div><h1>Dip-Cluster</h1>
    <p>Mindestens ${RU.min_n} Politiker kaufen innerhalb von ${RU.win} Tagen dieselbe Aktie, die ${-RU.dip} % oder mehr unter ihrem 52-Wochen-Hoch steht. Kaufen zum Schlusskurs nach der Meldung, nach ${RU.days} Tagen verkaufen.</p></div>
    <label class="ctl"><span>Dein Depot (für Positionsgröße)</span><input type="number" id="depot" min="0" step="1000" placeholder="z. B. 50000" value="${S.depot || ""}" style="width:160px"></label></div>

  <h3 class="sec">Jetzt offen <small>${open.length ? `${open.length} Signal${open.length === 1 ? "" : "e"}` : ""}</small></h3>
  ${open.length ? `<div class="cards">${open.map(card).join("")}</div>` : `<div class="panel empty">Gerade kein offenes Dip-Cluster. Neue Signale kommen per E-Mail (GitHub-Benachrichtigung).</div>`}

  <div class="panel" style="padding:14px 16px"><h2 style="font:600 15px/1.2 var(--f-body);margin:0 0 8px">So wird getradet</h2>
    <ol class="rules">
      <li><b>Signal kommt</b> per E-Mail oder steht oben bei „Jetzt offen“.</li>
      <li><b>Kurz prüfen (5 Min.):</b> Warum ist die Aktie gefallen? Bei Betrugsverdacht, Insolvenzgefahr oder Delisting nicht kaufen. Kurs über 5 $, Börsenwert über ca. 2 Mrd. $. Ist sie seit dem Signal schon über 10–15 % gestiegen, auslassen.</li>
      <li><b>Kaufen</b> am nächsten Handelstag zum Schlusskurs, <b>${RU.size} % des Depots</b> je Trade, höchstens 5 Trades gleichzeitig und höchstens 2 aus derselben Branche.</li>
      <li><b>Notfall-Stop ${RU.stop} %</b> auf Schlusskurs-Basis, kein enger Stop. Optional Gewinn bei <b>+${RU.target} %</b> mitnehmen.</li>
      <li><b>Nach ${RU.days} Tagen verkaufen</b>, egal wie der Trade steht.</li>
      <li><b>Jeden Trade notieren.</b> Nach 20–30 Trades prüfen: Schlagen weniger als die Hälfte den S&amp;P, aufhören.</li>
    </ol></div>

  <h3 class="sec">Backtest seit 2020 <small>${RU.days} Tage halten · gemessen ab Veröffentlichung</small></h3>
  <div class="verdict">${st.n ? `<b>${q(st.beat)}</b> der ${nf0.format(st.n)} Dip-Cluster schlugen den S&amp;P 500 in den 30 Tagen danach, im Schnitt um <b class="${cls(st.ex)}">${pct(st.ex)}</b> (Median ${pct(st.med)}). Zum Vergleich: alle Cluster ohne Dip-Filter nur ${q(cmp.ohne_dip.beat)} (Ø ${pct(cmp.ohne_dip.ex)}).` : "Noch keine abgeschlossenen Signale."}</div>
  <div class="tiles">
    <div class="tile"><div class="k">Schlägt den S&amp;P</div><div class="v">${q(st.beat)}</div><div class="d">im Plus: ${q(st.hit)}</div></div>
    <div class="tile"><div class="k">Ø pro Trade vs S&amp;P</div><div class="v ${cls(st.ex)}">${pct(st.ex)}</div><div class="d">Median ${pct(st.med)} · Ø Rendite ${pct(st.r)}</div></div>
    <div class="tile"><div class="k">Portfolio pro Jahr</div><div class="v ${cls(a.cagr - sp.cagr)}">${pct(a.cagr)}</div><div class="d">S&amp;P ${pct(sp.cagr)} · Geld oft ungenutzt</div></div>
    <div class="tile"><div class="k">Max. Rückgang</div><div class="v neg">${pct(a.mdd)}</div><div class="d">S&amp;P ${pct(sp.mdd)}</div></div>
    <div class="tile"><div class="k">Signale</div><div class="v">${nf0.format(st.n)}</div><div class="d">≈ ${nf0.format(st.n / Math.max(1, (Date.parse(D.asof) - Date.parse("2020-01-01")) / 3.156e10))} pro Jahr</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Kapitalkurve</h2><div class="legend-row"><span><span class="sw" style="background:var(--accent)"></span>Dip-Cluster</span><span><span class="sw" style="background:var(--chart-spy)"></span>S&amp;P 500</span><span><span class="sw dash" style="border-color:var(--ink-2)"></span>Nasdaq 100</span></div></div>
    <div class="panel-b"><div class="chart sm" id="eq"></div><p class="hint" style="margin:8px 0 0">Alle offenen Positionen gleich gewichtet, ohne Stop, ungenutztes Geld in Cash (0 %). Da es nur wenige Signale gibt, ist das Geld oft nicht investiert. Die Kurve zeigt deshalb weniger als die Ø-Werte pro Trade.</p></div></div>
  <div class="grid2">
    <div class="panel"><div class="panel-h"><h2>Nach Jahr</h2></div><div class="tbl-wrap"><table><thead><tr><th>Jahr</th><th class="n">Signale</th><th class="n">schlägt S&amp;P</th><th class="n">Ø vs S&amp;P</th></tr></thead><tbody>${st.years.map(y => `<tr><td class="num">${y.y}</td><td class="n">${y.n}</td><td class="n">${q(y.beat)}</td><td class="n">${pc(y.ex)}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="note"><b>Ehrlich:</b> Nur rund 15 Signale pro Jahr. Ein großer Teil der Gewinne kam nach Markt-Crashs (2020, April 2025). In ruhigen Märkten gibt es weniger und schwächere Signale. Getestet wurden auch normale Cluster, Ausschuss-Käufe, Top-Politiker, Firmen-Insider, technische Filter sowie Haltedauern von 60 und 90 Tagen: Nichts davon schlug den S&amp;P verlässlich, deshalb ist es nicht mehr auf der Seite. Keine Anlageberatung.</div>
  </div>
  ${pastTable()}`;
  const dep = $("#depot");
  dep.addEventListener("change", () => { S.depot = Number(dep.value) || null; try { localStorage.setItem("cs-depot", S.depot || ""); } catch (e) {} const y = scrollY; route(); scrollTo(0, y); });
  app.querySelectorAll("tr[data-t]").forEach(tr => tr.addEventListener("click", e => { if (!e.target.closest("a")) location.hash = "t." + encodeURIComponent(tr.dataset.t); }));
  app.querySelector("[data-more]")?.addEventListener("click", () => { S.show += 50; const y = scrollY; route(); scrollTo(0, y); });
  drawEq(pts);
}
function card(s) {
  const st = status(s), t = D.tickers[s.t] || {};
  const ex = s.rn != null && s.sn != null ? s.rn - s.sn : null;
  const ref = s.ep || s.lp;
  const stop = ref ? ref * (1 + RU.stop / 100) : null, tgt = ref ? ref * (1 + RU.target / 100) : null;
  const pos = S.depot ? S.depot * RU.size / 100 : null;
  const sh = pos && s.lp ? Math.floor(pos / s.lp) : null;
  const run = s.ep && s.lp ? (s.lp / s.ep - 1) * 100 : null;
  return `<a class="card" href="#t.${encodeURIComponent(s.t)}">
    <div class="card-h"><div class="ctk"><b>${esc(s.t)}</b><span>${esc(t.a || "")}</span></div>
      <div style="display:grid;gap:4px;justify-items:end">${st.pending || LAST - s.i < 5 ? '<span class="badge new">neu</span>' : ""}<span class="badge dip">▼ ${nf0.format(s.fh)} % unter Hoch</span></div></div>
    <div class="cwho"><b>${s.n} Käufer</b>${s.o ? ` · <span class="neg">${s.o} Verkäufer</span>` : ""} · bis ${dS(s.d)} gemeldet · ~${money(s.vol)}<br>${names(s.m)}</div>
    <div class="plan">
      <div><span class="k">${st.pending ? "Kauf" : "Einstieg"}</span><b>${st.pending ? "nächster Schluss" : usd(s.ep)}</b></div>
      <div><span class="k">Stop ${RU.stop} %</span><b class="neg">${usd(stop)}</b></div>
      <div><span class="k">Ziel +${RU.target} %</span><b class="pos">${usd(tgt)}</b></div>
      <div><span class="k">Verkauf ${st.exit > DATES[LAST] ? "ca." : ""}</span><b>${dS(st.exit)}</b></div>
    </div>
    ${pos ? `<div class="hint">Position: ${RU.size} % = <b>$${nf0.format(pos)}</b>${sh ? ` ≈ ${nf0.format(sh)} Aktien zu ${usd(s.lp)}` : ""}</div>` : ""}
    <div class="cnums">
      <div><span class="k">seit Einstieg</span><b class="${cls(s.rn)}">${st.pending ? "–" : pct(s.rn)}</b></div>
      <div><span class="k">vs S&amp;P</span><b class="${cls(ex)}">${st.pending ? "–" : pct(ex)}</b></div>
      <div><span class="k">noch</span><b>${st.left} HT</b></div>
    </div>
    <div class="prog"><i style="width:${Math.round(st.prog * 100)}%"></i></div>
    ${run != null && run > 10 ? `<div class="hint neg">Schon ${pct(run)} seit dem Einstiegstag gestiegen, der Vorteil ist eventuell weg.</div>` : ""}</a>`;
}
function pastTable() {
  const done = D.signals.filter(s => s.r != null);
  return `<div class="panel"><div class="panel-h"><h2>Alle vergangenen Dip-Cluster</h2><span class="sub">${done.length} abgeschlossen · Klick öffnet den Chart</span></div>
  <div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Aktie</th><th>Käufer</th><th class="n">unter Hoch</th><th class="n">30 Tage</th><th class="n">S&amp;P</th><th class="n">vs S&amp;P</th></tr></thead>
  <tbody>${done.slice(0, S.show).map(s => `<tr class="click" data-t="${esc(s.t)}"><td class="num">${dDE(s.d)}</td><td>${tickLink(s.t)}</td><td style="white-space:normal;min-width:180px">${s.n} · ${names(s.m, 3)}</td><td class="n">${nf0.format(s.fh)} %</td><td class="n">${pc(s.r)}</td><td class="n mut">${pct(s.s)}</td><td class="n">${pc(s.r - s.s)}</td></tr>`).join("")}</tbody></table></div>
  ${done.length > S.show ? `<div class="more"><button class="btn" data-more>Weitere ${Math.min(50, done.length - S.show)} anzeigen</button></div>` : ""}</div>`;
}
function drawEq(pts) {
  const el = $("#eq"); if (!el) return;
  if (!window.LightweightCharts || pts.length < 2) { el.innerHTML = `<div class="empty">Chart nicht verfügbar.</div>`; return; }
  const c = LightweightCharts.createChart(el, { ...chartOpts(v => (v > 0 ? "+" : "") + nf0.format(v) + " %"), handleScroll: false, handleScale: false }); charts.push(c);
  const add = (key, color, style, title) => { const s = c.addLineSeries({ color, lineWidth: 2, lineStyle: style, priceLineVisible: false, lastValueVisible: true, title }); s.setData(pts.filter(p => p[key] != null).map(p => ({ time: p.time, value: (p[key] - 1) * 100 }))); };
  add("spy", tok("--chart-spy"), 0, "S&P");
  if (pts[0].qqq != null) add("qqq", tok("--ink-2"), 2, "Nasdaq");
  add("s", tok("--accent"), 0, "Dip-Cluster");
  c.timeScale().fitContent();
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
  try { if (h.startsWith("t.")) viewTicker(app, h.slice(2)); else viewMain(app); }
  catch (e) { console.error(e); app.innerHTML = `<div class="err">Fehler beim Anzeigen: ${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", () => { route(); scrollTo(0, 0); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => route());
load().then(route).catch(e => { console.error(e); $("#app").innerHTML = `<div class="err"><b>Daten konnten nicht geladen werden.</b><br>${esc(e.message)}</div>`; });
})();
