/* Capitol Signals – Cluster-Signale (Seite #sig). Nutzt die Daten aus data/signals.json,
   die update.py täglich erzeugt. Regeln stehen in signals.py. */
(() => {
"use strict";
let SIG = null, view = { side: "all", page: 0 };
const $ = s => document.querySelector(s);

async function loadSig() {
  if (SIG) return SIG;
  const r = await fetch("data/signals.json");
  if (!r.ok) throw new Error("data/signals.json fehlt – der nächste Daten-Lauf erzeugt sie.");
  SIG = await r.json();
  return SIG;
}
function statsOf(list) {
  const xs = list.filter(s => !s.active && s.ex != null);
  const m = a => a.length ? a.reduce((p, c) => p + c, 0) / a.length : null;
  const q = xs.filter(s => s.exq != null);
  return { n: xs.length, ex: m(xs.map(s => s.ex)), win: xs.length ? xs.filter(s => s.ex > 0).length / xs.length * 100 : null, exq: m(q.map(s => s.exq)), r: m(xs.map(s => s.r)) };
}

async function viewSig(app) {
  const C = window.CS;
  app.innerHTML = `<div class="loading">Lade Signale …</div>`;
  let d;
  try { d = await loadSig(); } catch (e) { app.innerHTML = `<div class="err">${C.esc(e.message)}</div>`; return; }
  const R = d.rules, S = d.signals, DATES = C.DATES, last = DATES.length - 1;
  const act = S.filter(s => s.active);
  const recentCut = new Date(Date.parse(DATES[last]) - 7 * 864e5).toISOString().slice(0, 10);
  const L = statsOf(S.filter(s => s.s === "L")), SH = statsOf(S.filter(s => s.s === "S"));
  const pctS = v => C.pct(v), f0 = v => v == null ? "–" : C.nf0.format(v);
  const card = s => {
    const p = R[s.s], long = s.s === "L";
    const held = s.i == null ? 0 : Math.min(p.hold, last - s.i);
    const exitD = s.i == null ? null : (s.i + p.hold <= last ? DATES[s.i + p.hold] : null);
    const names = s.m.map(i => C.M[i]).filter(Boolean);
    return `<a class="sgcard ${long ? "L" : "S"}" href="#t.${encodeURIComponent(s.t)}">
      <div class="sghead"><span class="sgdir ${long ? "L" : "S"}">${long ? "LONG" : "SHORT"}</span>${s.d >= recentCut ? '<span class="pill new">neu</span>' : ""}${s.warn.length ? `<span class="pill late" title="Gegentrades seit dem Signal">⚠ ${s.warn.length} Gegen-${long ? "Verkäufe" : "Käufe"}</span>` : ""}</div>
      <div class="sgtick"><b>${C.esc(s.t)}</b><span>${C.esc(s.asset || "")}</span></div>
      <div class="sgwho"><div><b>${s.n} ${long ? "Käufer" : "Verkäufer"}</b>${s.o ? ` <span class="mut">· ${s.o} ${long ? "Verkäufer" : "Käufer"}</span>` : ""}</div><div class="chips">${names.slice(0, 5).map(m => `<span class="chip">${C.pty(m)} ${C.esc(m.name.split(" ").slice(-1)[0])}</span>`).join("")}${names.length > 5 ? `<span class="mut">+${names.length - 5}</span>` : ""}</div></div>
      <div class="sgnums">
        <div><span class="k">Gemeldet</span><b>${C.dDE(s.d)}</b></div>
        <div><span class="k">Einstieg</span><b>${s.i == null ? "nächster Handelstag" : C.dDE(DATES[s.i])}</b></div>
        <div><span class="k">${long ? "Seit Einstieg" : "Short-Ergebnis"}</span><b class="${C.cls(s.r)}">${pctS(s.r)}</b></div>
        <div><span class="k">vs S&amp;P</span><b class="${C.cls(s.ex)}">${pctS(s.ex)}</b></div>
      </div>
      <div class="sgbar" title="Haltedauer ${p.hold} Handelstage"><i style="width:${held / p.hold * 100}%"></i></div>
      <div class="hint">Tag ${held} von ${p.hold}${exitD ? ` · Ausstieg ${C.dDE(exitD)}` : ""} · Volumen ca. ${C.money(s.vol)}</div>
    </a>`;
  };
  const longA = act.filter(s => s.s === "L"), shortA = act.filter(s => s.s === "S");
  app.innerHTML = `
  <div class="view-head"><div><div class="eyebrow">Cluster-Signale · Kurse bis ${C.dDE(DATES[last])}</div><h1>Wo mehrere Politiker gleichzeitig handeln</h1>
    <p><b>LONG:</b> mindestens ${R.L.min_n} verschiedene Politiker kaufen dieselbe Aktie innerhalb von ${R.L.win} Tagen, mehr Käufer als Verkäufer, Haltedauer ${R.L.hold} Handelstage. <b>SHORT:</b> mindestens ${R.S.min_n} verkaufen innerhalb von ${R.S.win} Tagen, mehr Verkäufer als Käufer, Haltedauer ${R.S.hold} Handelstage. Einstieg immer am Handelstag nach der Meldung.</p></div></div>
  <div class="sgtrack">
    <div class="tile"><div class="k">Long-Signale bisher</div><div class="v ${C.cls(L.ex)}">${pctS(L.ex)}</div><div class="d">Ø vs S&amp;P je Signal · ${f0(L.n)} Signale · ${L.win == null ? "–" : C.nf0.format(L.win)} % Treffer · vs Nasdaq-100 ${pctS(L.exq)}</div></div>
    <div class="tile"><div class="k">Short-Signale bisher</div><div class="v ${C.cls(SH.ex)}">${pctS(SH.ex)}</div><div class="d">Ø Vorsprung des Shorts vs S&amp;P · ${f0(SH.n)} Signale · ${SH.win == null ? "–" : C.nf0.format(SH.win)} % Treffer</div></div>
    <div class="tile"><div class="k">Gerade aktiv</div><div class="v">${longA.length} <span class="pos" style="font-size:14px">Long</span> · ${shortA.length} <span class="neg" style="font-size:14px">Short</span></div><div class="d">${act.filter(s => s.d >= recentCut).length} davon neu in den letzten 7 Tagen</div></div>
  </div>
  <div class="panel"><div class="panel-h"><h2>Aktive Long-Signale</h2><span class="sub">${longA.length} Aktien · Klick öffnet Chart und alle Trades</span></div>
    <div class="panel-b">${longA.length ? `<div class="sggrid">${longA.map(card).join("")}</div>` : `<div class="empty">Gerade kein aktives Long-Signal.</div>`}</div></div>
  <div class="panel"><div class="panel-h"><h2>Aktive Short-Signale</h2><span class="sub">relativ zum S&amp;P 500 gemeint</span></div>
    <div class="panel-b" style="display:grid;gap:12px">${shortA.length ? `<div class="sggrid">${shortA.map(card).join("")}</div>` : `<div class="empty">Gerade kein aktives Short-Signal.</div>`}
    <div class="note">Short-Signale wurden gegen den S&amp;P 500 gemessen: Die Aktie lief danach im Schnitt schwächer als der Markt. In einem steigenden Markt kann ein reiner Short trotzdem Geld kosten. Abgesichert wäre das zum Beispiel Aktie short und S&amp;P 500 long in gleicher Höhe. Für Langfrist-Anleger ist es eher ein Grund, die Aktie zu meiden oder zu reduzieren.</div></div></div>
  <div class="panel"><div class="panel-h"><h2>Signal-Backtest</h2><div class="legend-row"><span><span class="sw" style="background:var(--pos)"></span>Long-Signale</span><span><span class="sw" style="background:var(--neg)"></span>Short-Signale (marktneutral)</span><span><span class="sw" style="background:var(--chart-spy)"></span>S&amp;P 500</span><span><span class="sw dash" style="border-color:var(--ink-2)"></span>Nasdaq-100</span></div></div>
    <div class="panel-b" style="display:grid;gap:12px"><div class="tiles" id="sgbt"><div class="loading">Rechne …</div></div><div class="chart" id="sgc"></div>
    <div class="hint">Gleich gewichtet über alle offenen Signale, ohne Signal liegt das Geld in Cash. Short-Linie: je Signal Aktie short und S&amp;P 500 long. Keine Gebühren, Zinsen oder Leihkosten. Die Regeln wurden auf denselben Daten gefunden; echte Zukunftsergebnisse fallen meist schwächer aus.</div></div></div>
  <div class="panel"><div class="panel-h"><h2>Alle bisherigen Signale</h2><div class="controls">${C.seg("sgf", [["all", "Alle"], ["L", "Long"], ["S", "Short"]], view.side)}</div></div><div id="sgtbl"></div></div>`;
  C.onSeg("sgf", v => { view.side = v; view.page = 0; table(); document.querySelectorAll("#sgf button").forEach(b => b.setAttribute("aria-pressed", b.dataset.v === v)); });
  function table() {
    const rows = S.filter(s => view.side === "all" || s.s === view.side), per = 100, pages = Math.max(1, Math.ceil(rows.length / per));
    view.page = Math.min(view.page, pages - 1);
    $("#sgtbl").innerHTML = `<div class="tbl-wrap"><table><thead><tr><th>Gemeldet</th><th>Ticker</th><th>Richtung</th><th class="n">Politiker</th><th>Einstieg</th><th>Ausstieg</th><th class="n">Ergebnis</th><th class="n">vs S&amp;P</th><th class="n">vs Nasdaq</th><th>Status</th></tr></thead><tbody>${rows.slice(view.page * per, view.page * per + per).map(s => `<tr class="click" data-t="${C.esc(s.t)}"><td class="num">${C.dDE(s.d)}</td><td>${C.tickLink(s.t)}</td><td><span class="side ${s.s === "L" ? "P" : "S"}">${s.s === "L" ? "LONG" : "SHORT"}</span></td><td class="n">${s.n}${s.o ? `<span class="mut"> / ${s.o}</span>` : ""}</td><td class="num">${s.i == null ? "–" : C.dDE(DATES[s.i])}</td><td class="num">${s.active ? '<span class="mut">läuft</span>' : s.x == null ? "–" : C.dDE(DATES[s.x])}</td><td class="n">${C.pc(s.r)}</td><td class="n"><b>${C.pc(s.ex)}</b></td><td class="n">${C.pc(s.exq)}</td><td>${s.active ? '<span class="pill new">aktiv</span>' : '<span class="mut">abgeschlossen</span>'}</td></tr>`).join("")}</tbody></table></div>
      <div class="pager"><button class="btn ghost" id="sgp" ${view.page ? "" : "disabled"}>← Zurück</button> Seite ${view.page + 1} von ${pages} <button class="btn ghost" id="sgn" ${view.page < pages - 1 ? "" : "disabled"}>Weiter →</button></div>`;
    $("#sgp").addEventListener("click", () => { view.page--; table(); }); $("#sgn").addEventListener("click", () => { view.page++; table(); });
    C.bindRowLinks($("#sgtbl"));
  }
  table();
  backtest(S, R);
}

async function backtest(S, R) {
  const C = window.CS, DATES = C.DATES, SPY = C.SPY, last = DATES.length - 1;
  const ts = new Set(S.filter(s => s.i != null).map(s => s.t)); ts.add("QQQ");
  await C.loadPx(ts);
  const P = t => C.PX.get(t);
  const s0 = DATES.findIndex(d => d >= "2020-06-01");
  function run(side) {
    const pos = S.filter(s => s.s === side && s.i != null && s.i >= s0 && s.i < last).map(s => ({ t: s.t, e: s.i, x: Math.min(s.i + R[side].hold, last) })).sort((a, b) => a.e - b.e);
    let v = 1, peak = 1, mdd = 0, act = [], k = 0, rets = [], eq = [];
    for (let d = s0; d <= last; d++) {
      act = act.filter(p => p.x >= d);
      let sum = 0, n = 0;
      for (const p of act) { if (p.e >= d) continue; const a = C.pxAt(P(p.t), d - 1), c = C.pxAt(P(p.t), d); if (a > 0 && c > 0) { const r = c / a - 1, sr = SPY[d] / SPY[d - 1] - 1; sum += side === "L" ? r : sr - r; n++; } }
      const r = n ? sum / n : 0;
      if (d > s0) { v *= 1 + r; rets.push(r); }
      peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1);
      eq.push({ time: DATES[d], value: (v - 1) * 100 });
      while (k < pos.length && pos[k].e === d) act.push(pos[k++]);
    }
    const yrs = (last - s0) / 252, m = rets.reduce((a, b) => a + b, 0) / rets.length, sd = Math.sqrt(rets.reduce((a, b) => a + (b - m) ** 2, 0) / rets.length);
    return { eq, total: (v - 1) * 100, cagr: (v ** (1 / yrs) - 1) * 100, mdd: mdd * 100, sharpe: sd ? m / sd * Math.sqrt(252) : null, n: pos.length };
  }
  const bench = get => { const out = []; const b0 = get(s0); for (let d = s0; d <= last; d++) { const v = get(d); if (v > 0 && b0 > 0) out.push({ time: DATES[d], value: (v / b0 - 1) * 100 }); } return out; };
  const L = run("L"), Sh = run("S");
  const spy = bench(d => SPY[d]), qqq = bench(d => C.pxAt(P("QQQ"), d));
  const yrs = (last - s0) / 252, cg = arr => arr.length ? ((1 + arr[arr.length - 1].value / 100) ** (1 / yrs) - 1) * 100 : null;
  const el = $("#sgbt"); if (!el) return;
  el.innerHTML = `
    <div class="tile"><div class="k">Long-Signale p. a.</div><div class="v ${C.cls(L.cagr)}">${C.pct(L.cagr)}</div><div class="d">${L.n} Signale · Max. Drawdown ${C.pct(L.mdd)} · Sharpe ${L.sharpe == null ? "–" : C.nf2.format(L.sharpe)}</div></div>
    <div class="tile"><div class="k">Short-Signale p. a. (marktneutral)</div><div class="v ${C.cls(Sh.cagr)}">${C.pct(Sh.cagr)}</div><div class="d">${Sh.n} Signale · Max. Drawdown ${C.pct(Sh.mdd)} · Sharpe ${Sh.sharpe == null ? "–" : C.nf2.format(Sh.sharpe)}</div></div>
    <div class="tile"><div class="k">Vergleich p. a.</div><div class="v">${C.pct(cg(spy))}</div><div class="d">S&amp;P 500 · Nasdaq-100 ${C.pct(cg(qqq))} · seit ${C.dDE(DATES[s0])}</div></div>`;
  const box = $("#sgc"); if (!box || !window.LightweightCharts) return;
  const ch = LightweightCharts.createChart(box, { ...C.chartOpts(box), localization: { locale: "de-DE", priceFormatter: v => (v > 0 ? "+" : "") + C.nf0.format(v) + " %" } });
  C.addChart(ch);
  const line = (data, color, title, style = 0, w = 2) => { const s = ch.addLineSeries({ color, lineWidth: w, lineStyle: style, priceLineVisible: false, title }); s.setData(data); };
  line(spy, C.tok("--chart-spy"), "S&P 500");
  line(qqq, C.tok("--ink-2"), "Nasdaq", 2, 1);
  line(Sh.eq, C.tok("--neg"), "Short");
  line(L.eq, C.tok("--pos"), "Long");
  ch.timeScale().fitContent();
}

window.CS_SIG = { view: viewSig };
})();
