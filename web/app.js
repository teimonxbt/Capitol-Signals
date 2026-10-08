/* Capitol Signals – Dashboard
   Alle Renditen werden AB VERÖFFENTLICHUNG gemessen: Einstieg zum Schlusskurs des ersten
   Handelstags NACH dem Meldedatum. "Ab Trade-Datum" wird nur zum Vergleich gezeigt. */
(() => {
"use strict";

// ------------------------------------------------------------------ state
const H = { "30": 21, "90": 63, "180": 126, "365": 252 };
const HL = { "30": "30 T", "90": "90 T", "180": "180 T", "365": "1 J" };
const S = {
  h: "90", dir: "P", chamber: "all", party: "all", period: "all", minN: 10, minAmt: 0,
  sort: "win", asc: false, q: "",
  hotWin: 30, hotQual: "all", hotSort: "buyers",
  tr: { side: "all", chamber: "all", party: "all", q: "", page: 0, sort: "filed", asc: false, period: "all" },
  mt: { side: "all", sort: "filed", asc: false, allMembers: false, ticker: null },
  bt: { mode: "top5", custom: [], h: "90", shorts: false, minAmt: 0, start: 2020, minKnown: 10, minWin: 55, entry: "pub" },
};
try { const s = JSON.parse(localStorage.getItem("cs-state") || "null"); if (s) { for (const k of ["h","dir","chamber","party","period","minN","minAmt","sort","asc","hotWin","hotQual","hotSort"]) if (k in s) S[k] = s[k]; if (s.bt) Object.assign(S.bt, s.bt); } } catch (e) {}
function save() { try { localStorage.setItem("cs-state", JSON.stringify({ h: S.h, dir: S.dir, chamber: S.chamber, party: S.party, period: S.period, minN: S.minN, minAmt: S.minAmt, sort: S.sort, asc: S.asc, hotWin: S.hotWin, hotQual: S.hotQual, hotSort: S.hotSort, bt: S.bt })); } catch (e) {} }

let META, M = [], T = [], CAL, DATES, SPY, BYM = [], BYT = new Map(), QUAL = [];
const PX = new Map(); const BUCKETS = new Map();
let charts = [];

// ------------------------------------------------------------------ favorites
// Lokal: localStorage. Als veröffentlichte Seite zusätzlich privat im Konto gespeichert (geräteübergreifend).
const FAV = new Set();
let favRemote = null, favTimer = null;
try { (JSON.parse(localStorage.getItem("cs-fav") || "[]") || []).forEach(id => FAV.add(id)); } catch (e) {}
const isFav = id => FAV.has(id);
function saveFav() {
  try { localStorage.setItem("cs-fav", JSON.stringify([...FAV])); } catch (e) {}
  if (favRemote) { clearTimeout(favTimer); favTimer = setTimeout(() => favRemote.set({ ids: [...FAV], updated: new Date().toISOString() }).catch(e => console.warn("Favoriten nicht gespeichert", e)), 400); }
}
function toggleFav(id) { if (FAV.has(id)) FAV.delete(id); else FAV.add(id); saveFav(); }
async function initFavRemote() {
  try {
    if (!window.claude?.use) return;
    const [db, user] = await Promise.all([window.claude.use("db"), window.claude.use("user")]);
    if (!db || !user) return;
    const uid = await user.id(); if (!uid) return;
    const ref = db.collection("data/users/" + uid).doc("favorites");
    const snap = await ref.get();
    favRemote = ref;
    const ids = snap.exists ? (snap.data()?.ids || []) : null;
    if (ids && Array.isArray(ids)) { FAV.clear(); ids.forEach(id => typeof id === "string" && FAV.add(id)); try { localStorage.setItem("cs-fav", JSON.stringify([...FAV])); } catch (e) {} route(); }
    else if (FAV.size) saveFav();
  } catch (e) { console.warn("Favoriten-Sync nicht verfügbar", e); }
}
function star(id) { const on = isFav(id); return `<button type="button" class="star" data-fav="${esc(id)}" aria-pressed="${on}" title="${on ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen"}" aria-label="${on ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen"}">${on ? "★" : "☆"}</button>`; }
function bindStars(root, after) {
  root.querySelectorAll("[data-fav]").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation(); e.preventDefault(); toggleFav(b.dataset.fav);
    const on = isFav(b.dataset.fav);
    root.querySelectorAll(`[data-fav="${CSS.escape(b.dataset.fav)}"]`).forEach(x => { x.setAttribute("aria-pressed", on); x.textContent = on ? "★" : "☆"; x.title = on ? "Aus Favoriten entfernen" : "Zu Favoriten hinzufügen"; });
    after && after();
  }));
}

// ------------------------------------------------------------------ format
const nf1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v, sign = true) => v == null || isNaN(v) ? "–" : (sign && v > 0 ? "+" : "") + nf1.format(v) + " %";
const cls = v => v == null || isNaN(v) ? "mut" : v > 0 ? "pos" : v < 0 ? "neg" : "";
const pc = (v) => `<span class="${cls(v)}">${pct(v)}</span>`;
const dDE = s => s ? s.slice(8, 10) + "." + s.slice(5, 7) + "." + s.slice(0, 4) : "–";
const days = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
function money(v) { if (v >= 1e6) return "$" + nf0.format(v / 1e6) + " Mio."; if (v >= 1e3) return "$" + nf0.format(v / 1e3) + "K"; return "$" + nf0.format(v); }
function amt(lo, hi) { const f = v => v >= 1e6 ? (v / 1e6).toFixed(v % 1e6 ? 1 : 0).replace(".0", "") + "M" : Math.round(v / 1e3) + "K"; if (!hi || hi === lo) return lo ? "$" + f(lo) : "–"; return "$" + f(lo) + "–" + f(hi); }
const mean = a => a.length ? a.reduce((s, v) => s + v, 0) / a.length : null;
const median = a => { if (!a.length) return null; const b = [...a].sort((x, y) => x - y); const m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; };
const al = (v, side) => v == null ? null : side === "P" ? v : -v;   // signalgerichtet
const docUrl = d => !d ? "" : d.startsWith("h:") ? `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/${d.slice(2)}.pdf` : d.startsWith("s:") ? `https://efdsearch.senate.gov/search/view/${d.slice(2)}/` : d;
const initials = n => n.split(/\s+/).filter(w => /^[A-Z]/.test(w)).map(w => w[0]).slice(0, 2).join("") || "?";
const chamberDE = c => c === "senate" ? "Senat" : "Repräsentantenhaus";
const partyDE = p => p === "D" ? "Demokrat" : p === "R" ? "Republikaner" : "Unabhängig";
function tok(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

// ------------------------------------------------------------------ data
async function j(url) { const r = await fetch(url); if (!r.ok) throw new Error(url + " → HTTP " + r.status); return r.json(); }
async function load() {
  const [meta, members, trades, cal] = await Promise.all([j("data/meta.json"), j("data/members.json"), j("data/trades.json"), j("data/calendar.json")]);
  META = meta; M = members; CAL = cal; DATES = cal.dates; SPY = cal.spy;
  const F = trades.fields;
  T = trades.rows.map(r => { const o = {}; F.forEach((f, i) => o[f] = r[i]); o.delay = days(o.tx, o.filed); return o; });
  M.forEach((m, i) => { m.i = i; BYM[i] = []; });
  for (const t of T) { BYM[t.m].push(t); if (!BYT.has(t.t)) BYT.set(t.t, []); BYT.get(t.t).push(t); }
  // Qualität je Abgeordnetem: Käufe, 90 T ab Veröffentlichung, über gesamten Zeitraum
  QUAL = M.map((m, i) => { const s = BYM[i].filter(t => t.side === "P" && t.kind === "st" && t.x90 != null); const w = s.filter(t => t.x90 > 0).length; return { n: s.length, win: s.length ? w / s.length : null, ex: mean(s.map(t => t.x90)) }; });
  document.getElementById("stand").innerHTML = `Kurse bis ${dDE(META.lastPrice)}<br>${nf0.format(META.trades)} Trades · ${META.members} Politiker`;
  initSearch();
}
async function loadPx(tickers) {
  const need = new Set();
  for (const t of tickers) if (!PX.has(t)) { const b = /^[A-Z]/.test(t) ? t[0] : "0"; if (META.buckets.includes(b) && !BUCKETS.has(b)) need.add(b); }
  await Promise.all([...need].map(async b => { const p = j(`data/prices/${b}.json`).then(d => { for (const k in d) PX.set(k, { f: d[k][0], v: d[k][1] }); }); BUCKETS.set(b, p); return p; }));
  await Promise.all([...new Set([...tickers].map(t => /^[A-Z]/.test(t) ? t[0] : "0"))].map(b => BUCKETS.get(b)).filter(Boolean));
}
const pxAt = (p, i) => { if (!p) return null; const v = p.v[i - p.f]; return v == null ? null : v; };

// ------------------------------------------------------------------ stats
function periodCut(p) { if (p === "all") return "0000"; const d = new Date(META.lastPrice); d.setMonth(d.getMonth() - (p === "12" ? 12 : 24)); return d.toISOString().slice(0, 10); }
function memberStats(i, o = {}) {
  const h = o.h || S.h, dir = o.dir || S.dir, cut = periodCut(o.period || S.period), minAmt = o.minAmt ?? S.minAmt;
  const all = BYM[i].filter(t => t.filed >= cut && t.lo >= minAmt && (dir === "all" || t.side === dir));
  const sc = all.filter(t => t.kind === "st" && t["x" + h] != null);
  const ex = sc.map(t => al(t["x" + h], t.side)), rr = sc.map(t => al(t["r" + h], t.side));
  const txe = sc.map(t => al(t["tx" + h], t.side)).filter(v => v != null);
  const lag = sc.map(t => al(t.lagx, t.side)).filter(v => v != null);
  const wins = ex.filter(v => v > 0).length;
  return {
    i, total: all.length, n: sc.length, wins, win: sc.length ? wins / sc.length * 100 : null,
    ret: mean(rr), ex: mean(ex), med: median(ex), txex: mean(txe), lag: mean(lag),
    delay: mean(all.map(t => t.delay)), last: all.length ? all.reduce((a, t) => t.filed > a ? t.filed : a, "") : null,
  };
}

// ------------------------------------------------------------------ ui helpers
function seg(id, opts, val) { return `<div class="seg" id="${id}" role="group">${opts.map(([v, l]) => `<button type="button" data-v="${v}" aria-pressed="${String(v) === String(val)}">${l}</button>`).join("")}</div>`; }
function onSeg(id, fn) { const el = document.getElementById(id); if (!el) return; el.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; fn(b.dataset.v); }); }
function avatar(m, lg) { const ini = esc(initials(m.name)); return `<span class="av${lg ? " lg" : ""}">${m.photo ? `<img src="${esc(m.photo)}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${ini}'))">` : ini}</span>`; }
function pty(m) { const ex = m.chamber === "executive"; const k = m.party || (ex ? "E" : "I"); return `<span class="party ${esc(k)}" title="${ex ? "Regierung" : esc(partyDE(m.party))}">${esc(m.party || (ex ? "Reg" : "I"))}</span>`; }
function where(m) { return m.chamber === "executive" ? esc([m.office, m.agency].filter(Boolean).join(" · ")) : `${m.chamber === "senate" ? "Senat" : "House"} · ${esc(m.state || "")}`; }
function who(m) { return `<div class="who">${avatar(m)}<div style="min-width:0"><b>${esc(m.name)}</b><div class="meta" style="white-space:normal">${pty(m)} ${where(m)}</div></div></div>`; }
function winBar(w) { if (w == null) return "–"; return `<span class="bar"><i class="${w >= 55 ? "good" : ""}" style="width:${Math.max(0, Math.min(100, w))}%"></i></span>${nf1.format(w)} %`; }
function sideTag(t) { return `<span class="side ${t.side}">${t.side === "P" ? "KAUF" : t.partial ? "VERK. T" : "VERKAUF"}</span>${t.kind === "opt" ? ' <span class="pill warn">Option</span>' : ""}`; }
function tickLink(t) { return `<a class="tick" href="#t.${encodeURIComponent(t)}">${esc(t)}</a>`; }
function sortRows(rows, key, asc) { const k = typeof key === "function" ? key : r => r[key]; return rows.sort((a, b) => { const x = k(a), y = k(b); if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (x < y ? -1 : x > y ? 1 : 0) * (asc ? 1 : -1); }); }
function th(label, key, st, cls = "", title = "") { const on = st.sort === key; return `<th class="sortable ${cls}${on ? " sorted" + (st.asc ? " asc" : "") : ""}" data-sort="${key}"${title ? ` title="${esc(title)}"` : ""}>${label}</th>`; }
function onSort(root, st, rerender) { root.querySelectorAll("th[data-sort]").forEach(h => h.addEventListener("click", () => { const k = h.dataset.sort; if (st.sort === k) st.asc = !st.asc; else { st.sort = k; st.asc = false; } rerender(); })); }
function killCharts() { charts.forEach(c => { try { c.remove(); } catch (e) {} }); charts = []; }
const $ = s => document.querySelector(s);

// ------------------------------------------------------------------ router
function route() {
  killCharts();
  const h = decodeURIComponent(location.hash.slice(1)) || "top";
  const v = h.split(".")[0];
  document.querySelectorAll("#tabs a").forEach(a => a.toggleAttribute("aria-current", false));
  const tab = { top: "top", hot: "hot", fav: "fav", members: "members", m: "members", trades: "trades", t: "trades", bt: "bt" }[v] || "top";
  document.querySelector(`#tabs a[data-v="${tab}"]`)?.setAttribute("aria-current", "page");
  const app = $("#app");
  try {
    if (v === "members") viewMembers(app);
    else if (v === "m") viewMember(app, h.slice(2));
    else if (v === "trades") viewTrades(app);
    else if (v === "t") viewTicker(app, h.slice(2));
    else if (v === "bt") viewBacktest(app);
    else if (v === "fav") viewFav(app);
    else if (v === "hot") viewHot(app);
    else viewTop(app);
  } catch (e) { console.error(e); app.innerHTML = `<div class="err">Fehler beim Anzeigen: ${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}

// ================================================================== SCORE / WEEKLY TOP 5
// Capitol Score 0–100: Perzentil-Rang in fünf Kriterien, gewichtet. Nur Käufe, 90 Tage ab Veröffentlichung.
// Wenige Trades werden Richtung Durchschnitt gezogen (10 "Phantom-Trades" mit 50 % Winrate und 0 % Outperformance).
const SW = { win: 25, ex: 30, ret: 15, act: 20, risk: 10 };
const SWL = { win: "Trefferquote", ex: "Outperformance vs S&P", ret: "Rendite", act: "Aktivität", risk: "Verlustbegrenzung" };
const SCORE_H = "90", SCORE_MIN = 10, SHRINK = 10;
const scoreCache = new Map();
function lowerBound(a, v) { let lo = 0, hi = a.length; while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] < v) lo = mid + 1; else hi = mid; } return lo; }
function scoreAll(asOf) {
  if (scoreCache.has(asOf)) return scoreCache.get(asOf);
  const h = SCORE_H, Hd = H[h], today = DATES[asOf], cut12 = DATES[Math.max(0, asOf - 252)];
  const rows = [];
  for (let i = 0; i < M.length; i++) {
    let n = 0, w = 0, se = 0, sr = 0, sneg = 0, last = "";
    for (const t of BYM[i]) {
      if (t.filed > today) continue;
      if (t.filed > last) last = t.filed;
      if (t.kind !== "st" || t.side !== "P" || t.pi == null || t["x" + h] == null || t.pi + Hd > asOf) continue;
      const x = t["x" + h]; n++; if (x > 0) w++; se += x; sr += t["r" + h]; if (x < 0) sneg += x;
    }
    if (n < SCORE_MIN || last < cut12) continue;
    rows.push({ i, n, wins: w, winRaw: w / n * 100, exRaw: se / n, retRaw: sr / n, lossRaw: sneg / n, last,
      win: (w + SHRINK / 2) / (n + SHRINK), ex: se / (n + SHRINK), ret: sr / (n + SHRINK), act: Math.log1p(n), risk: sneg / (n + SHRINK) });
  }
  for (const k of Object.keys(SW)) { const srt = rows.map(r => r[k]).sort((a, b) => a - b); rows.forEach(r => r["p_" + k] = rows.length > 1 ? lowerBound(srt, r[k]) / (rows.length - 1) * 100 : 50); }
  rows.forEach(r => r.score = Object.keys(SW).reduce((s, k) => s + SW[k] * r["p_" + k], 0) / 100);
  rows.sort((a, b) => b.score - a.score); rows.forEach((r, k) => r.rank = k + 1);
  scoreCache.set(asOf, rows);
  return rows;
}
function fridayIdx(before) { for (let k = before; k >= 0; k--) if (new Date(DATES[k] + "T12:00:00Z").getUTCDay() === 5) return k; return before; }
function isoWeek(d) { const t = new Date(d + "T12:00:00Z"); const day = (t.getUTCDay() + 6) % 7; t.setUTCDate(t.getUTCDate() - day + 3); const f = new Date(Date.UTC(t.getUTCFullYear(), 0, 4)); return 1 + Math.round(((t - f) / 864e5 - 3 + ((f.getUTCDay() + 6) % 7)) / 7); }
function scoreBars(r) { return `<div class="sbars">${Object.keys(SW).map(k => `<div class="sbar" title="${SWL[k]}: besser als ${nf0.format(r["p_" + k])} % der bewerteten Politiker"><span>${SWL[k]}</span><i><b style="width:${Math.max(2, r["p_" + k])}%"></b></i><em>${nf0.format(r["p_" + k])}</em></div>`).join("")}</div>`; }
function rankMove(r, prev) { const p = prev.get(r.i); if (!p) return `<span class="pill new">neu</span>`; const d = p.rank - r.rank; return d > 0 ? `<span class="pos mv">▲ ${d}</span>` : d < 0 ? `<span class="neg mv">▼ ${-d}</span>` : `<span class="mut mv">±0</span>`; }

function viewTop(app) {
  const wk = fridayIdx(DATES.length - 1), pw = fridayIdx(wk - 1);
  const rows = scoreAll(wk), prev = new Map(scoreAll(pw).map(r => [r.i, r]));
  const top = rows.slice(0, 5);
  const c30 = DATES[Math.max(0, DATES.length - 22)];
  const picks = i => BYM[i].filter(t => t.side === "P" && t.kind === "st").slice(0, 3);
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Weekly Top 5 · KW ${isoWeek(DATES[wk])} · Stand ${dDE(DATES[wk])}</div><h1>Die fünf stärksten Trader der Woche</h1>
    <p>Automatisch aus allen ${M.length} Politikern in Kongress und Regierung gefiltert. Der Capitol Score bewertet Trefferquote, Outperformance gegenüber dem S&amp;P 500, Rendite, Aktivität und Verlustbegrenzung zusammen, gemessen ab Veröffentlichung.</p></div>
    <button class="btn primary" id="t5bt">Top 5 im Backtest testen</button></div>
  <div class="top5">${top.map(r => { const m = M[r.i]; return `<article class="t5card">
      <div class="t5rank">${r.rank}</div>
      <div class="t5main">
        <div class="t5head"><a href="#m.${esc(m.id)}" class="t5who">${who(m)}</a><div class="t5score"><b>${nf0.format(r.score)}</b><span>Score</span>${rankMove(r, prev)}</div>${star(m.id)}</div>
        <div class="t5stats">
          <div><span class="k">Treffer</span><b>${r.wins} / ${r.n}</b><span class="hint">${nf0.format(r.winRaw)} %</span></div>
          <div><span class="k">Ø vs S&amp;P</span><b class="${cls(r.exRaw)}">${pct(r.exRaw)}</b><span class="hint">90 T</span></div>
          <div><span class="k">Ø Rendite</span><b class="${cls(r.retRaw)}">${pct(r.retRaw)}</b><span class="hint">90 T</span></div>
          <div><span class="k">Ø Verlust</span><b>${pct(r.lossRaw)}</b><span class="hint">Verlierer vs S&amp;P</span></div>
        </div>
        ${scoreBars(r)}
        <div class="t5picks"><span class="k">Neueste Käufe</span>${picks(r.i).map(t => `<span class="pick">${tickLink(t.t)} <span class="mut">${dDE(t.filed)}</span>${t.filed >= c30 ? ' <span class="pill new">neu</span>' : ""} ${pc(t.rn)}</span>`).join("") || '<span class="mut">–</span>'}</div>
      </div></article>`; }).join("")}</div>
  <div class="panel"><div class="panel-h"><h2>Gesamtwertung</h2><span class="sub">${rows.length} Politiker erfüllen die Mindestanforderungen · Plätze 6 bis 40</span></div>
    <div class="tbl-wrap"><table><thead><tr><th>#</th><th>±</th><th>★</th><th>Politiker</th><th class="n">Score</th><th class="n">Treffer</th><th class="n">Ø vs S&amp;P</th><th class="n">Ø Rendite</th><th class="n">Trades</th><th class="n">Ø Verlust</th><th>Letzte Meldung</th></tr></thead>
    <tbody>${rows.slice(5, 40).map(r => `<tr class="click" data-m="${esc(M[r.i].id)}"><td class="rank">${r.rank}</td><td>${rankMove(r, prev)}</td><td>${star(M[r.i].id)}</td><td>${who(M[r.i])}</td><td class="n"><b>${nf0.format(r.score)}</b></td><td class="n">${r.wins} / ${r.n}<div class="hint">${nf0.format(r.winRaw)} %</div></td><td class="n">${pc(r.exRaw)}</td><td class="n">${pc(r.retRaw)}</td><td class="n">${r.n}</td><td class="n">${pct(r.lossRaw)}</td><td class="num">${dDE(r.last)}</td></tr>`).join("")}</tbody></table></div></div>
  <details class="help note"><summary>Wie entsteht der Capitol Score?</summary>
    <p>Gewertet werden nur <b>Aktienkäufe</b>, jeweils <b>90 Tage ab Veröffentlichung</b>. Teilnehmen darf, wer mindestens ${SCORE_MIN} abgeschlossene Käufe hat und in den letzten 12 Monaten noch etwas gemeldet hat. Für jedes Kriterium wird ermittelt, wie viel Prozent der anderen jemand schlägt (0 bis 100). Daraus entsteht der Score mit dieser Gewichtung: ${Object.keys(SW).map(k => `${SWL[k]} ${SW[k]} %`).join(", ")}. Damit drei Glückstreffer nicht reichen, werden alle Werte mit 10 neutralen Trades verrechnet. Wer viel tradet und trotzdem gut ist, landet so vorne. Die Wertung wird jede Woche zum Freitag neu berechnet; ± zeigt die Veränderung zur Vorwoche.</p></details>`;
  $("#t5bt").addEventListener("click", () => { S.bt.mode = "top5"; save(); location.hash = "bt"; });
  bindStars(app);
  bindRowLinks(app);
}

// ------------------------------------------------------------------ globale Suche
const norm = s => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
function initSearch() {
  const inp = $("#gs"), box = $("#gres"); if (!inp) return;
  let items = [], sel = 0;
  const close = () => { box.hidden = true; items = []; };
  const go = it => { if (!it) return; inp.value = ""; close(); inp.blur(); location.hash = it.href; };
  const render = () => {
    box.innerHTML = items.length ? items.map((it, k) => `<a href="#${esc(it.href)}" class="gr${k === sel ? " on" : ""}" data-k="${k}">${it.html}</a>`).join("") : `<div class="gr empty">Nichts gefunden.</div>`;
    box.hidden = false;
    box.querySelectorAll("a.gr").forEach(a => a.addEventListener("mousedown", e => { e.preventDefault(); go(items[+a.dataset.k]); }));
  };
  inp.addEventListener("input", () => {
    const q = norm(inp.value.trim()); if (!q) return close();
    const toks = q.split(/\s+/);
    const ppl = M.filter(m => { const n = norm(m.name + " " + (m.office || "") + " " + (m.agency || "") + " " + (m.state || "")); return toks.every(t => n.includes(t)); })
      .sort((a, b) => BYM[b.i].length - BYM[a.i].length).slice(0, 6)
      .map(m => ({ href: "m." + m.id, html: `${avatar(m)}<span class="grt"><b>${esc(m.name)}</b><span class="mut">${pty(m)} ${where(m)}</span></span><span class="grn">${BYM[m.i].length} Trades</span>` }));
    const Q = q.toUpperCase();
    const tks = [...BYT.keys()].filter(t => t.startsWith(Q) || norm(BYT.get(t)[0].asset).includes(q))
      .sort((a, b) => (b === Q) - (a === Q) || BYT.get(b).length - BYT.get(a).length).slice(0, 5)
      .map(t => ({ href: "t." + t, html: `<span class="grtick">${esc(t)}</span><span class="grt"><b>${esc(BYT.get(t)[0].asset || t)}</b><span class="mut">Aktie</span></span><span class="grn">${BYT.get(t).length} Trades</span>` }));
    items = [...ppl, ...tks]; sel = 0; render();
  });
  inp.addEventListener("keydown", e => {
    if (box.hidden) return;
    if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter") { go(items[sel]); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });
  inp.addEventListener("blur", () => setTimeout(close, 120));
  document.addEventListener("keydown", e => { if (e.key === "/" && document.activeElement?.tagName !== "INPUT") { e.preventDefault(); inp.focus(); } });
}

// ================================================================== HOT
function viewHot(app) {
  const today = META.lastPrice;
  const cut = (() => { const d = new Date(today); d.setDate(d.getDate() - S.hotWin); return d.toISOString().slice(0, 10); })();
  const top = i => QUAL[i].n >= 10 && QUAL[i].win >= .55;
  const recent = T.filter(t => t.filed >= cut && t.kind === "st");
  const g = new Map();
  for (const t of recent) {
    if (S.hotQual === "top" && t.side === "P" && !top(t.m)) continue;
    if (S.hotQual === "fav" && t.side === "P" && !isFav(M[t.m].id)) continue;
    let e = g.get(t.t); if (!e) g.set(t.t, e = { t: t.t, buys: [], sells: [], asset: t.asset });
    (t.side === "P" ? e.buys : e.sells).push(t);
  }
  let rows = [...g.values()].filter(e => e.buys.length).map(e => {
    const buyers = [...new Set(e.buys.map(t => t.m))];
    const first = e.buys.reduce((a, t) => t.filed < a.filed ? t : a);
    const q = buyers.map(i => QUAL[i]).filter(q => q.n >= 5);
    return { ...e, buyers, nb: buyers.length, vol: e.buys.reduce((s, t) => s + (t.lo + (t.hi || t.lo)) / 2, 0),
      first: first.filed, since: first.rn, lag: mean(e.buys.map(t => t.lag).filter(v => v != null)),
      qual: q.length ? mean(q.map(q => q.win * 100)) : null, ns: new Set(e.sells.map(t => t.m)).size };
  });
  const sk = { buyers: r => r.nb * 1e12 + r.vol, vol: "vol", qual: "qual", since: "since" }[S.hotSort];
  sortRows(rows, sk, false);
  const topN = rows.slice(0, 25);
  const feed = T.slice(0, 40);
  const topTraders = QUAL.map((q, i) => ({ ...q, i })).filter(q => q.n >= 10).sort((a, b) => b.win - a.win || b.ex - a.ex).slice(0, 8);

  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Aktuell gemeldet</div><h1>Was der Kongress gerade kauft</h1>
    <p>Aktien, die in den letzten ${S.hotWin} Tagen als Kauf offengelegt wurden. „Vorlauf“ zeigt, wie weit die Aktie zwischen Trade-Datum und Veröffentlichung schon gelaufen ist, also den Teil, den du verpasst hast.</p></div></div>
  <div class="panel"><div class="panel-b controls">
    <label class="ctl"><span>Zeitfenster</span>${seg("hw", [[14, "14 T"], [30, "30 T"], [60, "60 T"], [90, "90 T"]], S.hotWin)}</label>
    <label class="ctl"><span>Käufer</span>${seg("hq", [["all", "Alle Abgeordneten"], ["top", "Nur Top-Trader"], ["fav", "Nur Favoriten" + (FAV.size ? " (" + FAV.size + ")" : "")]], S.hotQual)}</label>
    <label class="ctl"><span>Sortieren nach</span>${seg("hs", [["buyers", "Anzahl Käufer"], ["vol", "Volumen"], ["qual", "Käufer-Qualität"], ["since", "Seit Meldung"]], S.hotSort)}</label>
  </div>${S.hotQual === "top" ? `<div class="panel-b" style="padding-top:0"><div class="hint">Top-Trader: mindestens 10 bewertete Käufe und über 55 % davon schlagen den S&amp;P 500 nach 90 Tagen (gemessen ab Veröffentlichung).</div></div>` : ""}</div>
  <div class="grid2">
    <div class="panel"><div class="panel-h"><h2>Heiße Ticker</h2><span class="sub">${rows.length} Ticker mit Käufen</span></div>
      <div class="tbl-wrap"><table><thead><tr><th>#</th><th>Ticker</th><th class="n">Käufer</th><th>Wer</th><th class="n">Volumen ca.</th><th class="n" title="Ø Winrate der Käufer (90 T, ab Veröffentlichung)">Qualität</th><th class="n" title="Kursbewegung zwischen Trade-Datum und Veröffentlichung">Vorlauf</th><th class="n" title="Kurs seit der ersten Veröffentlichung im Zeitfenster">Seit Meldung</th><th class="n">Verkäufer</th></tr></thead>
      <tbody>${topN.map((r, k) => `<tr class="click" data-t="${esc(r.t)}"><td class="rank">${k + 1}</td><td>${tickLink(r.t)}<div class="hint" style="max-width:190px;overflow:hidden;text-overflow:ellipsis">${esc(r.asset)}</div></td>
        <td class="n"><b>${r.nb}</b></td><td>${r.buyers.slice(0, 3).map(i => `${pty(M[i])} ${esc(M[i].name.split(" ").slice(-1)[0])}`).join(", ")}${r.buyers.length > 3 ? ` <span class="mut">+${r.buyers.length - 3}</span>` : ""}</td>
        <td class="n">${money(r.vol)}</td><td class="n">${r.qual == null ? "–" : nf0.format(r.qual) + " %"}</td><td class="n">${pc(r.lag)}</td><td class="n">${pc(r.since)}</td><td class="n ${r.ns ? "neg" : "mut"}">${r.ns || "–"}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">${S.hotQual === "fav" && !FAV.size ? "Du hast noch keine Favoriten. Markiere Abgeordnete in der Rangliste mit ☆." : "Keine Käufe in diesem Zeitfenster."}</td></tr>`}</tbody></table></div></div>
    <div class="panel"><div class="panel-h"><h2>Beste Trefferquote</h2><span class="sub">Käufe · 90 T · ab Veröffentlichung · mind. 10 Käufe · <a class="back" href="#members">Ganze Rangliste →</a></span></div>
      <div class="tops">${topTraders.map(q => `<a href="#m.${esc(M[q.i].id)}">${who(M[q.i])}<span class="num" style="text-align:right;flex:none"><b>${nf1.format(q.win * 100)} %</b><div class="hint">${q.n} Käufe · ${pct(q.ex)}</div></span></a>`).join("")}</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Neueste Meldungen</h2><span class="sub">Sortiert nach Veröffentlichung</span></div>
    ${tradesTable(feed, { member: true, compact: true })}</div>`;
  onSeg("hw", v => { S.hotWin = +v; save(); route(); });
  onSeg("hq", v => { S.hotQual = v; save(); route(); });
  onSeg("hs", v => { S.hotSort = v; save(); route(); });
  bindRowLinks(app);
}
function bindRowLinks(root) {
  root.querySelectorAll("tr[data-t]").forEach(r => r.addEventListener("click", e => { if (e.target.closest("a")) return; location.hash = "t." + r.dataset.t; }));
  root.querySelectorAll("tr[data-m]").forEach(r => r.addEventListener("click", e => { if (e.target.closest("a")) return; location.hash = "m." + r.dataset.m; }));
}

// ------------------------------------------------------------------ generic trades table
function tradesTable(rows, o = {}) {
  const st = o.st;
  const h = (l, k, c, ti) => st ? th(l, k, st, c, ti) : `<th class="${c || ""}"${ti ? ` title="${esc(ti)}"` : ""}>${l}</th>`;
  const head = `<tr>${h("Gemeldet", "filed")}${h("Trade", "tx")}${h("Verzug", "delay", "n", "Tage zwischen Trade und Meldung (gesetzlich max. 45)")}${o.member ? h("Abgeordneter", "name") : ""}${h("Ticker", "t")}<th>Art</th>${h("Betrag", "lo", "n")}${o.compact ? "" : "<th>Eigentümer</th>"}${h("Vorlauf", "lag", "n", "Kursbewegung zwischen Trade-Datum und Veröffentlichung")}${o.compact ? h("30 T", "x30", "n", "Rendite vs S&P 500, 30 Tage ab Veröffentlichung") : ["30", "90", "180", "365"].map(k => h(HL[k], "x" + k, "n", `Rendite minus S&P 500, ${HL[k]} ab Veröffentlichung`)).join("")}${h("Seit Meldung", "rn", "n", "Kursentwicklung seit Einstieg nach Veröffentlichung")}<th>Beleg</th></tr>`;
  const body = rows.map(t => { const m = M[t.m]; return `<tr class="click${o.selT && t.t === o.selT ? " sel" : ""}" ${o.rowTicker ? `data-row-t="${esc(t.t)}"` : `data-t="${esc(t.t)}"`}>
    <td class="num">${dDE(t.filed)}</td><td class="num mut">${dDE(t.tx)}</td><td class="n">${t.delay}${t.delay > 45 ? ' <span class="pill late">spät</span>' : ""}</td>
    ${o.member ? `<td><a class="back" href="#m.${esc(m.id)}">${pty(m)} ${esc(m.name)}</a></td>` : ""}
    <td>${tickLink(t.t)}</td><td>${sideTag(t)}</td><td class="n">${amt(t.lo, t.hi)}</td>${o.compact ? "" : `<td class="mut">${esc(t.owner)}</td>`}
    <td class="n">${pc(t.lag)}</td>${(o.compact ? ["30"] : ["30", "90", "180", "365"]).map(k => `<td class="n">${pc(t["x" + k])}</td>`).join("")}<td class="n">${pc(t.rn)}</td>
    <td>${t.doc ? `<a class="back" href="${esc(docUrl(t.doc))}" target="_blank" rel="noopener">PDF ↗</a>` : ""}</td></tr>`; }).join("");
  return `<div class="tbl-wrap"><table><thead>${head}</thead><tbody>${body || `<tr><td colspan="16" class="empty">Keine Trades für diese Filter.</td></tr>`}</tbody></table></div>`;
}

// ================================================================== FAVORITEN
function viewFav(app) {
  const st = S.fv || (S.fv = { win: 30, side: "P" });
  const favs = M.filter(m => isFav(m.id));
  if (!favs.length) {
    app.innerHTML = `<div class="view-head"><div><div class="eyebrow">Watchlist</div><h1>Meine Favoriten</h1>
      <p>Hier siehst du die Abgeordneten, denen du folgst, und ihre neuesten Aktien-Picks auf einen Blick.</p></div></div>
      <div class="panel"><div class="empty" style="display:grid;gap:12px;justify-items:center"><div style="font-size:30px;color:var(--accent)">☆</div>
      <div>Noch keine Favoriten. Öffne die Rangliste und klicke beim Namen auf den Stern.</div><a class="btn primary" href="#members" style="text-decoration:none">Zur Rangliste</a></div></div>`;
    return;
  }
  const cut = (() => { if (st.win === "all") return "0000"; const d = new Date(META.lastPrice); d.setDate(d.getDate() - st.win); return d.toISOString().slice(0, 10); })();
  const idx = new Set(favs.map(m => m.i));
  const feed = T.filter(t => idx.has(t.m) && t.filed >= cut && (st.side === "all" || t.side === st.side));
  const c30 = (() => { const d = new Date(META.lastPrice); d.setDate(d.getDate() - 30); return d.toISOString().slice(0, 10); })();
  const cards = favs.map(m => ({ m, s: memberStats(m.i, { period: "all", minAmt: 0 }), recent: BYM[m.i].filter(t => t.filed >= c30).length }))
    .sort((a, b) => (b.s.win ?? -1) - (a.s.win ?? -1));
  // gemeinsame Käufe mehrerer Favoriten
  const byT = new Map(); for (const t of feed) if (t.side === "P") { if (!byT.has(t.t)) byT.set(t.t, new Set()); byT.get(t.t).add(t.m); }
  const shared = [...byT].filter(([, s]) => s.size > 1).sort((a, b) => b[1].size - a[1].size);
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Watchlist</div><h1>Meine Favoriten</h1>
    <p>${favs.length} Abgeordnete. Kennzahlen: ${S.dir === "P" ? "Käufe" : S.dir === "S" ? "Verkäufe" : "Käufe und Verkäufe"}, ${HL[S.h]} ab Veröffentlichung (einstellbar in der Rangliste).</p></div>
    <button class="btn" id="favbt">Favoriten im Backtest testen</button></div>
  <div class="favgrid">${cards.map(({ m, s, recent }) => `<a class="favcard" href="#m.${esc(m.id)}">
    <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">${who(m)}${star(m.id)}</div>
    <div class="favstats"><div><span class="k">Winrate</span><b>${s.win == null ? "–" : nf0.format(s.win) + " %"}</b><span class="hint">${s.wins ?? 0} / ${s.n}</span></div>
      <div><span class="k">Ø vs S&amp;P</span><b class="${cls(s.ex)}">${pct(s.ex)}</b></div>
      <div><span class="k">Zuletzt</span><b>${dDE(s.last)}</b>${recent ? `<span class="pill warn">${recent} neu (30 T)</span>` : ""}</div></div></a>`).join("")}</div>
  ${shared.length ? `<div class="note"><b>Mehrere Favoriten kaufen dasselbe:</b> ${shared.slice(0, 8).map(([t, set]) => `${tickLink(t)} (${[...set].map(i => esc(M[i].name.split(" ").slice(-1)[0])).join(", ")})`).join(" · ")}</div>` : ""}
  <div class="panel"><div class="panel-h"><h2>Neue Picks deiner Favoriten</h2>
    <div class="controls">${seg("fw", [[30, "30 T"], [90, "90 T"], [365, "1 J"], ["all", "Alle"]], st.win)}${seg("fs2", [["P", "Käufe"], ["S", "Verkäufe"], ["all", "Beide"]], st.side)}</div></div>
    ${tradesTable(feed.slice(0, 200), { member: true })}
    ${feed.length > 200 ? `<div class="pager">Neueste 200 von ${feed.length}</div>` : ""}</div>`;
  onSeg("fw", v => { st.win = v === "all" ? "all" : +v; route(); });
  onSeg("fs2", v => { st.side = v; route(); });
  $("#favbt").addEventListener("click", () => { S.bt.mode = "custom"; S.bt.custom = favs.map(m => m.id); save(); location.hash = "bt"; });
  bindStars(app, () => route());
  bindRowLinks(app);
}

// ================================================================== MEMBERS (Rangliste)
function rankingFilters() {
  return `<div class="panel"><div class="panel-b controls">
    <label class="ctl"><span>Haltedauer</span>${seg("fh", Object.keys(H).map(k => [k, HL[k]]), S.h)}</label>
    <label class="ctl"><span>Signal</span>${seg("fd", [["P", "Käufe"], ["S", "Verkäufe"], ["all", "Beide"]], S.dir)}</label>
    <label class="ctl"><span>Bereich</span>${seg("fc", [["all", "Alle"], ["house", "House"], ["senate", "Senat"], ["executive", "Regierung"]], S.chamber)}</label>
    <label class="ctl"><span>Partei</span>${seg("fp", [["all", "Alle"], ["D", "Dem."], ["R", "Rep."]], S.party)}</label>
    <label class="ctl"><span>Gemeldet</span>${seg("fz", [["all", "Seit 2020"], ["24", "24 Monate"], ["12", "12 Monate"]], S.period)}</label>
    <label class="ctl"><span>Min. Betrag</span>${seg("fa", [[0, "Alle"], [15001, "≥ 15K"], [50001, "≥ 50K"], [250001, "≥ 250K"]], S.minAmt)}</label>
    <label class="ctl" for="fn"><span>Min. Trades</span><input type="number" id="fn" min="1" max="500" value="${S.minN}"></label>
    <label class="ctl" for="fq"><span>Suche</span><input type="search" id="fq" placeholder="Name oder Bundesstaat" value="${esc(S.q)}"></label>
  </div></div>`;
}
function bindRankingFilters(rerender) {
  onSeg("fh", v => { S.h = v; save(); rerender(); }); onSeg("fd", v => { S.dir = v; save(); rerender(); });
  onSeg("fc", v => { S.chamber = v; save(); rerender(); }); onSeg("fp", v => { S.party = v; save(); rerender(); });
  onSeg("fz", v => { S.period = v; save(); rerender(); }); onSeg("fa", v => { S.minAmt = +v; save(); rerender(); });
  $("#fn").addEventListener("change", e => { S.minN = Math.max(1, +e.target.value || 1); save(); rerender(); });
  $("#fq").addEventListener("input", e => { S.q = e.target.value; clearTimeout(bindRankingFilters.t); bindRankingFilters.t = setTimeout(() => { rerender(); const q = $("#fq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }, 200); });
}
function ranking() {
  const q = S.q.trim().toLowerCase();
  let rows = M.filter(m => (S.chamber === "all" || m.chamber === S.chamber) && (S.party === "all" || m.party === S.party) && (!q || m.name.toLowerCase().includes(q) || (m.state || "").toLowerCase() === q))
    .map(m => memberStats(m.i)).filter(s => s.n >= S.minN);
  const key = { win: r => r.win * 1e3 + r.n / 1e3, ret: "ret", ex: "ex", med: "med", n: "n", txex: "txex", lag: "lag", delay: "delay", last: "last", name: r => M[r.i].name }[S.sort] || "win";
  return sortRows(rows, key, S.asc);
}
function viewMembers(app) {
  const rows = ranking();
  const all = rows.length ? { n: rows.reduce((s, r) => s + r.n, 0), beat: rows.filter(r => r.ex > 0).length } : null;
  const avgEx = mean(rows.map(r => r.ex).filter(v => v != null));
  const dirL = { P: "Käufe", S: "Verkäufe (Gewinn, wenn die Aktie danach schwächer als der S&P läuft)", all: "Käufe und Verkäufe" }[S.dir];
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Rangliste</div><h1>Wer im Kongress wirklich tradet</h1>
    <p>Jeder Trade wird ab dem ersten Handelstag nach der Veröffentlichung bewertet, also so, wie du ihn frühestens hättest nachmachen können. Gewertet: ${esc(dirL)}.</p></div>
    <div class="ctl"><span>Sortieren nach</span>${seg("fs", [["win", "Winrate"], ["ret", "Rendite"], ["ex", "Outperformance"], ["n", "Anzahl Trades"]], S.sort)}</div></div>
  ${rankingFilters()}
  <div class="tiles">
    <div class="tile"><div class="k">Abgeordnete in Auswahl</div><div class="v">${rows.length}</div><div class="d">mit ≥ ${S.minN} bewerteten Trades</div></div>
    <div class="tile"><div class="k">Bewertete Trades</div><div class="v">${all ? nf0.format(all.n) : "–"}</div><div class="d">Haltedauer ${HL[S.h]}</div></div>
    <div class="tile"><div class="k">Schlagen den S&amp;P im Schnitt</div><div class="v">${all ? all.beat + " / " + rows.length : "–"}</div><div class="d">Ø Outperformance aller: ${pct(avgEx)}</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Rangliste</h2><span class="sub">Klick auf eine Zeile öffnet alle Trades</span></div>
  <div class="tbl-wrap"><table id="rk"><thead><tr><th>#</th><th title="Favorit">★</th>${th("Abgeordneter", "name", S)}${th("Treffer / bewertet", "n", S, "n", "Treffer = schlägt den S&P. Bewertet = Aktien-Trades mit Kursdaten und abgeschlossener Haltedauer. Darunter: alle Trades im Filter.")}${th("Winrate", "win", S, "", "Anteil Trades, die den S&P 500 geschlagen haben")}${th("Ø Rendite", "ret", S, "n")}${th("Ø vs S&amp;P", "ex", S, "n")}${th("Median vs S&amp;P", "med", S, "n")}${th("Ab Trade-Datum", "txex", S, "n", "Theoretische Outperformance, wenn man am Trade-Datum eingestiegen wäre")}${th("Ø Vorlauf", "lag", S, "n", "Ø Bewegung vs S&P zwischen Trade und Meldung")}${th("Ø Verzug", "delay", S, "n")}${th("Letzte Meldung", "last", S)}</tr></thead>
  <tbody>${rows.map((r, k) => `<tr class="click" data-m="${esc(M[r.i].id)}"><td class="rank">${k + 1}</td><td>${star(M[r.i].id)}</td><td>${who(M[r.i])}</td><td class="n"><b>${r.wins}</b> / ${r.n}<div class="hint">${r.total} Trades gesamt</div></td><td>${winBar(r.win)}</td><td class="n">${pc(r.ret)}</td><td class="n"><b>${pc(r.ex)}</b></td><td class="n">${pc(r.med)}</td><td class="n mut">${pct(r.txex)}</td><td class="n">${pc(r.lag)}</td><td class="n">${r.delay == null ? "–" : nf0.format(r.delay) + " T"}</td><td class="num">${dDE(r.last)}</td></tr>`).join("") || `<tr><td colspan="12" class="empty">Niemand erfüllt diese Filter. Senke „Min. Trades“ oder erweitere den Zeitraum.</td></tr>`}</tbody></table></div></div>
  <details class="help note"><summary>Wie wird gerechnet?</summary>
    <p><b>Treffer / bewertet:</b> „9 / 10“ heißt: 10 Trades konnten bewertet werden, 9 davon haben den S&amp;P geschlagen, also 90 % Winrate. Nicht bewertet werden Trades, deren Haltedauer noch läuft, Optionen und Aktien ohne Kursdaten (z. B. delistet). Die Zahl darunter zählt alle Trades im Filter.</p>
    <p><b>Einstieg:</b> Schlusskurs des ersten Handelstags nach dem Meldedatum. <b>Ausstieg:</b> nach 21 / 63 / 126 / 252 Handelstagen (≈ 30 / 90 / 180 / 365 Kalendertage). <b>Winrate:</b> Anteil der Trades, die in dieser Zeit besser liefen als der SPY. Bei Verkäufen zählt ein Treffer, wenn die Aktie danach schwächer als der SPY lief. <b>Vorlauf:</b> Bewegung zwischen Trade-Datum und Meldung relativ zum SPY, also der Teil, der für dich schon weg war. Betragsangaben sind gesetzliche Spannen, keine exakten Summen. Winraten mit wenigen Trades sind Zufall, deshalb der Filter „Min. Trades“.</p></details>`;
  bindRankingFilters(() => route());
  onSeg("fs", v => { S.sort = v; S.asc = false; save(); route(); });
  onSort(app, S, () => { save(); route(); });
  bindStars(app);
  bindRowLinks(app);
}

// ================================================================== MEMBER detail
function viewMember(app, id) {
  const m = M.find(x => x.id === id);
  if (!m) { app.innerHTML = `<div class="err">Abgeordneter nicht gefunden.</div>`; return; }
  const st = S.mt;
  const s = memberStats(m.i, { period: "all", minAmt: 0 });
  const sb = memberStats(m.i, { dir: "P", period: "all", minAmt: 0 }), ss = memberStats(m.i, { dir: "S", period: "all", minAmt: 0 });
  let list = BYM[m.i].filter(t => st.side === "all" || t.side === st.side);
  sortRows(list, st.sort === "name" ? "filed" : st.sort, st.asc);
  const tickCount = new Map(); BYM[m.i].forEach(t => tickCount.set(t.t, (tickCount.get(t.t) || 0) + 1));
  const topTicks = [...tickCount].sort((a, b) => b[1] - a[1]).slice(0, 12);
  if (!st.ticker || !tickCount.has(st.ticker) || st.forM !== m.id) { st.ticker = BYM[m.i][0]?.t; st.forM = m.id; st.showAll = false; }

  app.innerHTML = `
  <a class="back" href="#members">← Rangliste</a>
  <div class="member-head">${avatar(m, true)}<div><h1 style="display:flex;align-items:center;gap:10px">${esc(m.name)} ${star(m.id)}</h1><div class="mut">${pty(m)} ${m.chamber === "executive" ? where(m) : partyDE(m.party) + " · " + esc(m.office || chamberDE(m.chamber))}</div></div>
    <div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" id="tobt">Im Backtest testen</button></div></div>
  <div class="panel"><div class="panel-b controls"><label class="ctl"><span>Haltedauer für Kennzahlen</span>${seg("fh", Object.keys(H).map(k => [k, HL[k]]), S.h)}</label>
    <label class="ctl"><span>Kennzahlen für</span>${seg("fd", [["P", "Käufe"], ["S", "Verkäufe"], ["all", "Beide"]], S.dir)}</label></div></div>
  <div class="tiles">
    <div class="tile"><div class="k">Trades seit 2020</div><div class="v">${BYM[m.i].length}</div><div class="d">${BYM[m.i].filter(t => t.side === "P").length} Käufe · ${BYM[m.i].filter(t => t.side === "S").length} Verkäufe</div></div>
    <div class="tile"><div class="k">Winrate ${HL[S.h]}</div><div class="v">${s.win == null ? "–" : nf1.format(s.win) + " %"}</div><div class="d">${s.wins} Treffer von ${s.n} bewerteten · Käufe ${sb.win == null ? "–" : nf0.format(sb.win) + " %"} · Verk. ${ss.win == null ? "–" : nf0.format(ss.win) + " %"}</div></div>
    <div class="tile"><div class="k">Ø vs S&amp;P ${HL[S.h]}</div><div class="v ${cls(s.ex)}">${pct(s.ex)}</div><div class="d">Median ${pct(s.med)} · Ø Rendite ${pct(s.ret)}</div></div>
    <div class="tile"><div class="k">Ab Trade-Datum</div><div class="v mut">${pct(s.txex)}</div><div class="d">theoretisch, nicht handelbar</div></div>
    <div class="tile"><div class="k">Ø Meldeverzug</div><div class="v">${s.delay == null ? "–" : nf0.format(s.delay) + " Tage"}</div><div class="d">Ø Vorlauf ${pct(s.lag)}</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2 id="ct-title">Chart</h2>
    <div class="controls"><label class="ctl"><span>Marker</span>${seg("ma", [["0", "Nur " + esc(m.name.split(" ").slice(-1)[0])], ["1", "Alle Politiker"]], st.allMembers ? "1" : "0")}</label></div></div>
    <div class="panel-b" style="display:grid;gap:10px"><div class="chips">${topTicks.map(([t, n]) => `<button type="button" class="chip" data-ct="${esc(t)}" aria-pressed="${t === st.ticker}"><b class="mono">${esc(t)}</b><span class="mut">${n}</span></button>`).join("")}</div>
    <div class="chart" id="pc"></div>${chartLegendHTML()}</div></div>
  <div class="panel"><div class="panel-h"><h2>Alle Trades</h2><div class="controls">${seg("ms", [["all", "Alle"], ["P", "Käufe"], ["S", "Verkäufe"]], st.side)}</div></div>
    <div id="mtbl">${tradesTable(st.showAll ? list : list.slice(0, 150), { st, rowTicker: true, selT: st.ticker })}</div>${list.length > 150 && !st.showAll ? `<div class="pager"><button class="btn" id="mall">Alle ${list.length} Trades anzeigen</button></div>` : ""}
    <div class="pager">Klick auf einen Trade zeigt ihn im Chart. Renditen = vs S&amp;P ab Veröffentlichung.</div></div>`;
  onSeg("fh", v => { S.h = v; save(); route(); });
  onSeg("fd", v => { S.dir = v; save(); route(); });
  onSeg("ms", v => { st.side = v; route(); });
  onSeg("ma", v => { st.allMembers = v === "1"; drawTicker(); });
  onSort($("#mtbl"), st, () => route());
  $("#mall")?.addEventListener("click", () => { st.showAll = true; route(); });
  $("#tobt").addEventListener("click", () => { S.bt.mode = "custom"; S.bt.custom = [m.id]; save(); location.hash = "bt"; });
  bindStars(app);
  app.querySelectorAll("[data-ct]").forEach(b => b.addEventListener("click", () => { st.ticker = b.dataset.ct; syncSel(); drawTicker(); }));
  app.querySelectorAll("tr[data-row-t]").forEach(r => r.addEventListener("click", e => { if (e.target.closest("a")) return; st.ticker = r.dataset.rowT; syncSel(); drawTicker(); $("#pc").scrollIntoView({ behavior: "smooth", block: "center" }); }));
  function syncSel() { app.querySelectorAll("[data-ct]").forEach(b => b.setAttribute("aria-pressed", b.dataset.ct === st.ticker)); app.querySelectorAll("tr[data-row-t]").forEach(r => r.classList.toggle("sel", r.dataset.rowT === st.ticker)); }
  function drawTicker() {
    if (!st.ticker) return;
    const tr = st.allMembers ? BYT.get(st.ticker) : BYM[m.i].filter(t => t.t === st.ticker);
    $("#ct-title").innerHTML = `${tickLink(st.ticker)} <span class="mut" style="font-weight:400">· ${tr.length} Trade${tr.length === 1 ? "" : "s"}</span>`;
    priceChart($("#pc"), st.ticker, tr);
  }
  drawTicker();
}
function chartLegendHTML() { return `<div class="legend-row"><span><span class="sw" style="background:var(--chart-line)"></span>Kurs (dividendenbereinigt)</span><span><span class="mk up"></span>Kauf, Einstieg nach Meldung</span><span><span class="mk dn"></span>Verkauf, nach Meldung</span><span><span class="dot"></span>Tatsächliches Trade-Datum</span></div>`; }

// ------------------------------------------------------------------ price chart
async function priceChart(el, ticker, trades) {
  killCharts(); el.innerHTML = `<div class="loading">Lade Kurs …</div>`;
  await loadPx([ticker]);
  const p = PX.get(ticker);
  el.innerHTML = "";
  if (!p) { el.innerHTML = `<div class="empty">Für ${esc(ticker)} gibt es keine Kursdaten bei Yahoo (z. B. delistet oder kein US-Ticker).</div>`; return; }
  if (!window.LightweightCharts) { el.innerHTML = `<div class="empty">Chart-Bibliothek konnte nicht geladen werden (Internet?).</div>`; return; }
  const c = LightweightCharts.createChart(el, chartOpts(el));
  charts.push(c);
  const line = tok("--chart-line");
  const s = c.addAreaSeries({ lineColor: line, topColor: line + "30", bottomColor: line + "00", lineWidth: 2, priceLineVisible: false });
  const data = []; for (let k = 0; k < p.v.length; k++) if (p.v[k] != null) data.push({ time: DATES[p.f + k], value: p.v[k] });
  s.setData(data);
  const first = DATES[p.f];
  const pos = tok("--pos"), neg = tok("--neg"), mut = tok("--muted");
  const agg = new Map(); const byDay = new Map();
  for (const t of trades) {
    if (t.pi != null && DATES[t.pi] >= first) { const k = DATES[t.pi] + t.side; agg.set(k, (agg.get(k) || 0) + 1); }
    for (const [i, lab] of [[t.pi, "Meldung"], [t.ti, "Trade"]]) if (i != null) { const d = DATES[i]; if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push([lab, t]); }
  }
  const mk = [];
  for (const [k, n] of agg) { const d = k.slice(0, 10), sd = k.slice(10); mk.push({ time: d, position: sd === "P" ? "belowBar" : "aboveBar", color: sd === "P" ? pos : neg, shape: sd === "P" ? "arrowUp" : "arrowDown", text: n > 1 ? n + "×" : "" }); }
  const txs = new Set(); for (const t of trades) if (t.ti != null && DATES[t.ti] >= first) txs.add(DATES[t.ti]);
  for (const d of txs) mk.push({ time: d, position: "inBar", color: mut, shape: "circle", size: 0.6 });
  mk.sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
  s.setMarkers(mk);
  c.timeScale().fitContent();
  const lg = document.createElement("div"); lg.className = "chart-legend"; el.appendChild(lg);
  const base = `<b>${esc(ticker)}</b> ${nf2.format(data[data.length - 1]?.value ?? 0)}`;
  lg.innerHTML = base;
  c.subscribeCrosshairMove(prm => {
    if (!prm.time) { lg.innerHTML = base; return; }
    const v = prm.seriesData.get(s)?.value; const ev = byDay.get(prm.time) || [];
    lg.innerHTML = `<b>${esc(ticker)}</b> ${dDE(prm.time)} · ${v != null ? nf2.format(v) : "–"}` + ev.slice(0, 5).map(([lab, t]) => `<br><span class="${t.side === "P" ? "pos" : "neg"}">${lab === "Trade" ? "Trade" : "Einstieg"} ${t.side === "P" ? "Kauf" : "Verkauf"}</span> · ${esc(M[t.m].name)} · ${amt(t.lo, t.hi)}${lab === "Meldung" ? ` · gemeldet ${dDE(t.filed)}` : ""}`).join("") + (ev.length > 5 ? `<br>+${ev.length - 5} weitere` : "");
  });
}
function chartOpts(el) {
  return { width: el.clientWidth, height: el.clientHeight, autoSize: true,
    layout: { background: { type: "solid", color: tok("--surface") }, textColor: tok("--muted"), fontFamily: "IBM Plex Mono, ui-monospace, monospace", fontSize: 11 },
    grid: { vertLines: { visible: false }, horzLines: { color: tok("--line") } },
    rightPriceScale: { borderColor: tok("--line") }, timeScale: { borderColor: tok("--line") },
    crosshair: { mode: 0 }, localization: { locale: "de-DE" } };
}

// ================================================================== TICKER
function viewTicker(app, ticker) {
  const list = BYT.get(ticker) || [];
  const st = S.tr;
  const buys = list.filter(t => t.side === "P"), sells = list.filter(t => t.side === "S");
  const mem = new Set(list.map(t => t.m));
  const last = PX.get(ticker);
  app.innerHTML = `
  <button type="button" class="btn ghost" id="goback" style="justify-self:start;padding-left:0">← Zurück</button>
  <div class="view-head"><div><div class="eyebrow">Ticker</div><h1 class="mono" style="font-family:var(--f-mono)">${esc(ticker)}</h1><p>${esc(list[0]?.asset || "")}</p></div></div>
  <div class="tiles">
    <div class="tile"><div class="k">Trades seit 2020</div><div class="v">${list.length}</div><div class="d">von ${mem.size} Abgeordneten</div></div>
    <div class="tile"><div class="k">Käufe / Verkäufe</div><div class="v"><span class="pos">${buys.length}</span> / <span class="neg">${sells.length}</span></div><div class="d">letzte Meldung ${dDE(list[0]?.filed)}</div></div>
    <div class="tile"><div class="k">Ø Käufe vs S&amp;P 90 T</div><div class="v ${cls(mean(buys.map(t => t.x90).filter(v => v != null)))}">${pct(mean(buys.map(t => t.x90).filter(v => v != null)))}</div><div class="d">ab Veröffentlichung</div></div>
    <div class="tile"><div class="k">Ø Vorlauf Käufe</div><div class="v">${pct(mean(buys.map(t => t.lagx).filter(v => v != null)))}</div><div class="d">vs S&amp;P, Trade → Meldung</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Kurs mit allen Kongress-Trades</h2></div><div class="panel-b" style="display:grid;gap:10px"><div class="chart" id="pc"></div>${chartLegendHTML()}</div></div>
  <div class="panel"><div class="panel-h"><h2>Alle Trades in ${esc(ticker)}</h2></div>${tradesTable(list, { member: true })}</div>`;
  $("#goback").addEventListener("click", () => history.length > 1 ? history.back() : (location.hash = "trades"));
  priceChart($("#pc"), ticker, list);
}

// ================================================================== ALL TRADES
function viewTrades(app) {
  const st = S.tr, q = st.q.trim().toLowerCase(), cut = periodCut(st.period);
  let rows = T.filter(t => (st.side === "all" || t.side === st.side) && t.filed >= cut && (st.chamber === "all" || M[t.m].chamber === st.chamber) && (st.party === "all" || M[t.m].party === st.party)
    && (!q || t.t.toLowerCase() === q || M[t.m].name.toLowerCase().includes(q) || t.asset.toLowerCase().includes(q)));
  if (!(st.sort === "filed" && !st.asc)) sortRows(rows, st.sort === "name" ? t => M[t.m].name : st.sort, st.asc);
  const per = 100, pages = Math.max(1, Math.ceil(rows.length / per)); st.page = Math.min(st.page, pages - 1);
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Journal</div><h1>Alle offengelegten Trades</h1><p>${nf0.format(rows.length)} Trades. Spalten sind sortierbar; Suche nach Ticker (exakt), Name oder Firmenname.</p></div></div>
  <div class="panel"><div class="panel-b controls">
    <label class="ctl"><span>Art</span>${seg("ts", [["all", "Alle"], ["P", "Käufe"], ["S", "Verkäufe"]], st.side)}</label>
    <label class="ctl"><span>Bereich</span>${seg("tc", [["all", "Alle"], ["house", "House"], ["senate", "Senat"], ["executive", "Regierung"]], st.chamber)}</label>
    <label class="ctl"><span>Partei</span>${seg("tp", [["all", "Alle"], ["D", "Dem."], ["R", "Rep."]], st.party)}</label>
    <label class="ctl"><span>Gemeldet</span>${seg("tz", [["all", "Seit 2020"], ["24", "24 Monate"], ["12", "12 Monate"]], st.period)}</label>
    <label class="ctl" for="tq"><span>Suche</span><input type="search" id="tq" placeholder="NVDA, Pelosi, Microsoft …" value="${esc(st.q)}"></label>
  </div></div>
  <div class="panel" id="ttbl">${tradesTable(rows.slice(st.page * per, st.page * per + per), { member: true, st })}
    <div class="pager"><button class="btn ghost" id="pp" ${st.page ? "" : "disabled"}>← Zurück</button> Seite ${st.page + 1} von ${pages} <button class="btn ghost" id="pn" ${st.page < pages - 1 ? "" : "disabled"}>Weiter →</button></div></div>`;
  const re = () => { st.page = 0; route(); };
  onSeg("ts", v => { st.side = v; re(); }); onSeg("tc", v => { st.chamber = v; re(); }); onSeg("tp", v => { st.party = v; re(); }); onSeg("tz", v => { st.period = v; re(); });
  $("#tq").addEventListener("input", e => { st.q = e.target.value; clearTimeout(viewTrades.t); viewTrades.t = setTimeout(() => { re(); const i = $("#tq"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 250); });
  $("#pp").addEventListener("click", () => { st.page--; route(); }); $("#pn").addEventListener("click", () => { st.page++; route(); });
  onSort($("#ttbl"), st, re);
  bindRowLinks(app);
}

// ================================================================== BACKTEST
function viewBacktest(app) {
  const b = S.bt;
  const years = []; for (let y = +DATES[0].slice(0, 4) + 1; y <= +META.lastPrice.slice(0, 4) - 1; y++) years.push(y);
  if (!years.includes(b.start)) b.start = years[0];
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Backtest</div><h1>Hätte sich Nachhandeln gelohnt?</h1>
    <p>Jede Position wird erst am Handelstag nach der Veröffentlichung eröffnet und nach der Haltedauer geschlossen. Alle offenen Positionen sind gleich gewichtet; ohne Signal liegt das Geld in Cash. Die gestrichelte Linie zeigt denselben Test ab Trade-Datum, also den Vorteil, den nur der Abgeordnete hatte.</p></div></div>
  <div class="panel"><div class="panel-b" style="display:grid;gap:16px">
    <div class="controls">
      <label class="ctl"><span>Wessen Trades?</span>${seg("bm", [["top5", "Weekly Top 5"], ["roll", "Top-Trader (rollierend)"], ["all", "Alle Politiker"], ["custom", "Eigene Auswahl"]], b.mode)}</label>
      <label class="ctl"><span>Haltedauer</span>${seg("bh", Object.keys(H).map(k => [k, HL[k]]), b.h)}</label>
      <label class="ctl"><span>Signale</span>${seg("bs", [["0", "Nur Käufe (long)"], ["1", "Käufe long + Verkäufe short"]], b.shorts ? "1" : "0")}</label>
      <label class="ctl"><span>Min. Betrag</span>${seg("ba", [[0, "Alle"], [15001, "≥ 15K"], [50001, "≥ 50K"], [250001, "≥ 250K"]], b.minAmt)}</label>
      <label class="ctl" for="by"><span>Start</span><select id="by">${years.map(y => `<option ${y === b.start ? "selected" : ""}>${y}</option>`).join("")}</select></label>
    </div>
    <div id="bmode"></div>
    <div><button class="btn primary" id="brun">Backtest starten</button> <span class="hint" id="bstat"></span></div>
  </div></div>
  <div id="bres"></div>`;
  const modeBox = () => {
    const el = $("#bmode");
    if (b.mode === "roll") el.innerHTML = `<div class="controls"><label class="ctl" for="bk"><span>Min. bekannte Trades</span><input type="number" id="bk" min="3" max="100" value="${b.minKnown}"></label>
      <label class="ctl" for="bw"><span>Min. Winrate %</span><input type="number" id="bw" min="0" max="100" value="${b.minWin}"></label>
      <div class="note" style="flex:1 1 320px">Ohne Rückblick-Vorteil: Ein Abgeordneter zählt nur, wenn er <b>zum Zeitpunkt der Meldung</b> schon mindestens ${b.minKnown} abgeschlossene Trades mit ≥ ${b.minWin} % Winrate hatte. Es fließt nur ein, was man damals wissen konnte.</div></div>`;
    else if (b.mode === "top5") el.innerHTML = `<div class="note">Jede Woche zum Freitag wird der Capitol Score mit dem damaligen Wissensstand berechnet. Kopiert werden nur die Käufe der fünf Bestplatzierten, die in der Folgewoche gemeldet werden. Genau so, wie du die Weekly Top 5 nutzen würdest, ohne Rückblick-Vorteil.</div>`;
    else if (b.mode === "all") el.innerHTML = `<div class="note">Kopiert jeden Aktien-Trade aller Abgeordneten. Das ist die Basis-Strategie, ähnlich wie die Kongress-ETFs sie umsetzen.</div>`;
    else {
      el.innerHTML = `<div class="controls"><label class="ctl" for="bq"><span>Abgeordneten hinzufügen</span><input type="search" id="bq" list="bml" placeholder="Name tippen …"><datalist id="bml">${M.map(m => `<option value="${esc(m.name)}">`).join("")}</datalist></label>
        <button class="btn" id="bfav">Favoriten übernehmen${FAV.size ? " (" + FAV.size + ")" : ""}</button><button class="btn" id="btop">Top 10 aus Rangliste übernehmen</button><button class="btn ghost" id="bclr">Leeren</button></div>
        <div class="chips" id="bch" style="margin-top:10px"></div>
        <div class="note" style="margin-top:10px"><b>Achtung Rückblick-Vorteil:</b> Wenn du Abgeordnete auswählst, weil sie in der Rangliste gut aussehen, testest du mit Wissen aus der Zukunft. Das Ergebnis ist dann zu optimistisch. Für einen fairen Test nutze „Top-Trader (rollierend)“.</div>`;
      const chips = () => { $("#bch").innerHTML = b.custom.map(id => { const m = M.find(x => x.id === id); return m ? `<span class="chip" data-rm="${esc(id)}">${pty(m)}${esc(m.name)} <span class="x">×</span></span>` : ""; }).join("") || `<span class="hint">Noch niemand ausgewählt.</span>`;
        $("#bch").querySelectorAll("[data-rm]").forEach(c => c.addEventListener("click", () => { b.custom = b.custom.filter(x => x !== c.dataset.rm); save(); chips(); })); };
      chips();
      $("#bq").addEventListener("change", e => { const m = M.find(x => x.name === e.target.value); if (m && !b.custom.includes(m.id)) { b.custom.push(m.id); save(); chips(); } e.target.value = ""; });
      $("#btop").addEventListener("click", () => { b.custom = ranking().slice(0, 10).map(r => M[r.i].id); save(); chips(); });
      $("#bfav").addEventListener("click", () => { b.custom = [...FAV].filter(id => M.some(m => m.id === id)); save(); chips(); });
      $("#bclr").addEventListener("click", () => { b.custom = []; save(); chips(); });
    }
    $("#bk")?.addEventListener("change", e => { b.minKnown = Math.max(1, +e.target.value || 10); save(); modeBox(); });
    $("#bw")?.addEventListener("change", e => { b.minWin = Math.max(0, Math.min(100, +e.target.value || 0)); save(); modeBox(); });
  };
  modeBox();
  onSeg("bm", v => { b.mode = v; save(); document.querySelectorAll("#bm button").forEach(x => x.setAttribute("aria-pressed", x.dataset.v === v)); modeBox(); });
  onSeg("bh", v => { b.h = v; save(); document.querySelectorAll("#bh button").forEach(x => x.setAttribute("aria-pressed", x.dataset.v === v)); });
  onSeg("bs", v => { b.shorts = v === "1"; save(); document.querySelectorAll("#bs button").forEach(x => x.setAttribute("aria-pressed", x.dataset.v === v)); });
  onSeg("ba", v => { b.minAmt = +v; save(); document.querySelectorAll("#ba button").forEach(x => x.setAttribute("aria-pressed", x.dataset.v === v)); });
  $("#by").addEventListener("change", e => { b.start = +e.target.value; save(); });
  $("#brun").addEventListener("click", runBacktest);
  runBacktest();
}

function selectSignals(b) {
  const Hd = H[b.h], start = b.start + "-01-01";
  let cand = T.filter(t => t.kind === "st" && t.px && t.pi != null && t.filed >= start && t.lo >= b.minAmt && (t.side === "P" || (b.shorts && t.side === "S")));
  if (b.mode === "custom") { const set = new Set(b.custom.map(id => M.findIndex(m => m.id === id))); cand = cand.filter(t => set.has(t.m)); }
  if (b.mode === "top5") {
    // Top 5 jeder Woche (Freitag) mit dem damaligen Wissensstand; gilt für Meldungen der Folgewoche
    const fr = []; for (let k = 0; k < DATES.length; k++) if (new Date(DATES[k] + "T12:00:00Z").getUTCDay() === 5) fr.push(k);
    const sets = fr.map(k => new Set(scoreAll(k).slice(0, 5).map(r => r.i)));
    cand = cand.filter(t => { const j = lowerBound(fr, t.pi) - 1; return j >= 0 && sets[j].has(t.m) && t.side === "P"; });
  }
  if (b.mode === "roll") {
    // pro Abgeordnetem: welche Trades waren zum Meldezeitpunkt schon abgeschlossen (pi + H <= jetzt)?
    const res = new Map();
    for (let i = 0; i < M.length; i++) {
      const known = BYM[i].filter(t => t.kind === "st" && t["x" + b.h] != null && (t.side === "P" || b.shorts)).map(t => [t.pi + Hd, al(t["x" + b.h], t.side) > 0 ? 1 : 0]).sort((a, c) => a[0] - c[0]);
      res.set(i, known);
    }
    cand = cand.filter(t => { const k = res.get(t.m); let n = 0, w = 0; for (const [r, win] of k) { if (r > t.pi) break; n++; w += win; } return n >= b.minKnown && w / n * 100 >= b.minWin; });
  }
  return cand;
}
function simulate(sig, b, entryKey) {
  const Hd = H[b.h], last = DATES.length - 1;
  const s0 = DATES.findIndex(d => d >= b.start + "-01-01");
  const pos = new Map();
  for (const t of sig) {
    const e = t[entryKey]; if (e == null || e < s0 || e >= last) continue;
    const k = t.t + "|" + e + "|" + t.side; const p = pos.get(k);
    if (p) { p.who.add(t.m); continue; }
    pos.set(k, { t: t.t, s: t.side === "P" ? 1 : -1, e, x: Math.min(e + Hd, last), who: new Set([t.m]), tr: t });
  }
  const P = [...pos.values()].sort((a, c) => a.e - c.e);
  const eq = [], spy = [], dd = []; let v = 1, sv = 1, peak = 1, mdd = 0, act = [], pi = 0, expo = 0, rets = [], npos = 0;
  for (let d = s0; d <= last; d++) {
    act = act.filter(p => p.x >= d);
    let sum = 0, n = 0;
    for (const p of act) { if (p.e >= d) continue; const px = PX.get(p.t); const a = pxAt(px, d - 1), c = pxAt(px, d); if (a > 0 && c > 0) { sum += p.s * (c / a - 1); n++; } }
    const r = n ? sum / n : 0; if (n) expo++; npos += n;
    if (d > s0) { v *= 1 + r; rets.push(r); const sa = SPY[d - 1], sc = SPY[d]; if (sa > 0 && sc > 0) sv *= sc / sa; }
    peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1);
    eq.push({ time: DATES[d], value: (v - 1) * 100 }); spy.push({ time: DATES[d], value: (sv - 1) * 100 });
    while (pi < P.length && P[pi].e === d) act.push(P[pi++]);
  }
  const nd = last - s0, yrs = nd / 252;
  const m = mean(rets), sd = Math.sqrt(mean(rets.map(r => (r - m) ** 2)) || 0);
  const trades = P.map(p => { const px = PX.get(p.t); const a = pxAt(px, p.e), c = pxAt(px, p.x); const r = a > 0 && c > 0 ? p.s * (c / a - 1) * 100 : null; const sr = (SPY[p.x] / SPY[p.e] - 1) * 100; return { ...p, r, ex: null, sr, open: p.e + H[b.h] > last }; });
  trades.forEach(t => { if (t.r != null) t.ex = t.r - t.sr * (t.s === 1 ? 1 : -1); });
  const closed = trades.filter(t => t.r != null && !t.open);
  return { eq, spy, total: (v - 1) * 100, spyTotal: (sv - 1) * 100, cagr: (Math.pow(v, 1 / yrs) - 1) * 100, spyCagr: (Math.pow(sv, 1 / yrs) - 1) * 100,
    mdd: mdd * 100, sharpe: sd ? m / sd * Math.sqrt(252) : null, expo: expo / (nd + 1) * 100, avgPos: expo ? npos / expo : 0,
    n: P.length, win: closed.length ? closed.filter(t => t.r > 0).length / closed.length * 100 : null,
    beat: closed.length ? closed.filter(t => t.ex > 0).length / closed.length * 100 : null, avg: mean(closed.map(t => t.r)), trades };
}
async function runBacktest() {
  const b = S.bt, stat = $("#bstat"), res = $("#bres");
  if (b.mode === "custom" && !b.custom.length) { res.innerHTML = `<div class="note">Wähle mindestens einen Abgeordneten aus oder übernimm die Top 10 aus der Rangliste.</div>`; return; }
  const sig = selectSignals(b);
  if (!sig.length) { res.innerHTML = `<div class="note">Mit diesen Einstellungen gibt es keine Signale. Senke die Anforderungen oder wähle einen früheren Start.</div>`; return; }
  stat.textContent = `Lade Kurse für ${new Set(sig.map(t => t.t)).size} Ticker …`;
  killCharts();
  await loadPx(new Set(sig.map(t => t.t)));
  stat.textContent = "Rechne …";
  await new Promise(r => setTimeout(r, 20));
  const A = simulate(sig, b, "pi"), B = simulate(sig, b, "ti");
  stat.textContent = `${nf0.format(sig.length)} Signale → ${nf0.format(A.n)} Positionen`;
  const members = new Set(sig.map(t => t.m));
  const recent = [...A.trades].sort((x, y) => y.e - x.e).slice(0, 150);
  res.innerHTML = `
  <div class="tiles">
    <div class="tile"><div class="k">Gesamtrendite</div><div class="v ${cls(A.total)}">${pct(A.total)}</div><div class="d">S&amp;P 500: ${pct(A.spyTotal)}</div></div>
    <div class="tile"><div class="k">Rendite p. a.</div><div class="v ${cls(A.cagr)}">${pct(A.cagr)}</div><div class="d">S&amp;P 500: ${pct(A.spyCagr)} · Differenz ${pc(A.cagr - A.spyCagr)}</div></div>
    <div class="tile"><div class="k">Max. Drawdown</div><div class="v neg">${pct(A.mdd)}</div><div class="d">Sharpe ${A.sharpe == null ? "–" : nf2.format(A.sharpe)}</div></div>
    <div class="tile"><div class="k">Trefferquote</div><div class="v">${A.win == null ? "–" : nf1.format(A.win) + " %"}</div><div class="d">${A.beat == null ? "" : nf0.format(A.beat) + " % schlagen den S&amp;P"} · Ø ${pct(A.avg)}</div></div>
    <div class="tile"><div class="k">Positionen</div><div class="v">${nf0.format(A.n)}</div><div class="d">${members.size} Abgeordnete · Ø ${nf0.format(A.avgPos)} gleichzeitig · ${nf0.format(A.expo)} % investiert</div></div>
    <div class="tile"><div class="k">Kosten des Meldeverzugs</div><div class="v ${cls(A.cagr - B.cagr)}">${pct(A.cagr - B.cagr)}</div><div class="d">p. a. vs. Einstieg am Trade-Datum (${pct(B.cagr)})</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Kapitalkurve</h2><div class="legend-row"><span><span class="sw" style="background:var(--accent)"></span>Strategie ab Veröffentlichung</span><span><span class="sw dash" style="border-color:var(--ink-2)"></span>Theoretisch ab Trade-Datum</span><span><span class="sw" style="background:var(--chart-spy)"></span>S&amp;P 500 (SPY)</span></div></div>
    <div class="panel-b"><div class="chart" id="eqc"></div></div></div>
  <div class="panel"><div class="panel-h"><h2>Positionen im Backtest</h2><span class="sub">Neueste ${recent.length} von ${nf0.format(A.n)} · Klick öffnet den Chart</span></div>
    <div class="tbl-wrap"><table><thead><tr><th>Einstieg</th><th>Ausstieg</th><th>Ticker</th><th>Richtung</th><th>Abgeordnete</th><th class="n">Rendite</th><th class="n">S&amp;P</th><th class="n">vs S&amp;P</th></tr></thead>
    <tbody>${recent.map(p => `<tr class="click" data-t="${esc(p.t)}"><td class="num">${dDE(DATES[p.e])}</td><td class="num">${p.open ? '<span class="pill warn">offen</span>' : dDE(DATES[p.x])}</td><td>${tickLink(p.t)}</td><td><span class="side ${p.s > 0 ? "P" : "S"}">${p.s > 0 ? "LONG" : "SHORT"}</span></td><td>${[...p.who].map(i => esc(M[i].name)).join(", ")}</td><td class="n">${pc(p.r)}</td><td class="n mut">${pct(p.sr)}</td><td class="n">${pc(p.ex)}</td></tr>`).join("")}</tbody></table></div></div>
  <div class="note"><b>Grenzen des Tests:</b> keine Gebühren, Spreads oder Steuern; Einstieg zum Schlusskurs; Betragsangaben der Meldungen sind Spannen und werden nicht zur Gewichtung genutzt; Aktien ohne Yahoo-Kurse (z. B. delistet) fehlen, was das Ergebnis leicht beschönigen kann.</div>`;
  bindRowLinks(res);
  const el = $("#eqc");
  const c = LightweightCharts.createChart(el, { ...chartOpts(el), localization: { locale: "de-DE", priceFormatter: v => (v > 0 ? "+" : "") + nf0.format(v) + " %" } });
  charts.push(c);
  const sp = c.addLineSeries({ color: tok("--chart-spy"), lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "SPY" }); sp.setData(A.spy);
  const th2 = c.addLineSeries({ color: tok("--ink-2"), lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: true, title: "Trade-Datum" }); th2.setData(B.eq);
  const st = c.addLineSeries({ color: tok("--accent"), lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title: "Strategie" }); st.setData(A.eq);
  c.timeScale().fitContent();
}

// ------------------------------------------------------------------ boot
window.addEventListener("hashchange", route);
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => route());
new MutationObserver(() => route()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
load().then(() => { route(); initFavRemote(); }).catch(e => { console.error(e); $("#app").innerHTML = `<div class="err"><b>Daten konnten nicht geladen werden.</b><br>${esc(e.message)}<br><br>Lokal: Starte das Dashboard mit <span class="mono">bash start.sh</span> (öffnet es über einen kleinen Webserver). Direkt per Doppelklick auf index.html blockiert der Browser das Laden der Daten.</div>`; });
})();
