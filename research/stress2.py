"""
Capitol Signals – Stresstest 2 (läuft in GitHub Actions)

1. Veröffentlichungs-Verzögerung: Einstieg 5 / 10 / 20 Handelstage nach dem Meldedatum.
2. Parameter-Empfindlichkeit: Dip-Schwelle, Haltedauer, Stop.
3. Ohne Crash-Phasen (Feb–Mai 2020, Ende März–Mai 2025).
4. Klumpenrisiko: Signale pro Tag, Anteil des Gewinns aus den besten Monaten.
5. Überlebens-Verzerrung: Cluster in Aktien OHNE Kursdaten (meist delistet/übernommen).
Basis = Regeln der Seite: 2+ Politiker oder 1 ab 100k $, Dip >= 40 %, 21 Tage, Stop -25 %, Sperre 63 Tage.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge  # noqa: E402
import expand  # noqa: E402
import robust  # noqa: E402

log = edge.log
OUT = edge.OUT
SPLIT = "2024-01-01"


def outcomes(P, evs, delay=0, hold=21, stop=0.25):
    res = []
    for e in evs:
        c, i0 = P.cols[e["t"]], e["i"] + delay
        if i0 + hold > P.n - 1 or not (c[i0] > 0) or not (P.spy[i0] > 0):
            continue
        path, lv, x = [], 1.0, i0 + hold
        for j in range(i0, i0 + hold + 1):
            if c[j] > 0:
                lv = c[j] / c[i0]
            path.append(lv)
            if stop and j > i0 and lv <= 1 - stop:
                x = j
                break
        r = path[-1] - 1
        s = P.spy[x] / P.spy[i0] - 1 if P.spy[x] > 0 else 0.0
        res.append({**e, "i": i0, "x": x, "path": path, "r": r, "s": s})
    return res


def row(P, dates, res):
    return {"t": robust.tstats(res), "is": robust.tstats([e for e in res if e["d"] < SPLIT]),
            "oos": robust.tstats([e for e in res if e["d"] >= SPLIT]),
            "cash": robust.perf(robust.sim(P, dates, res, "cash")), "ma": robust.perf(robust.sim(P, dates, res, "ma"))}


def run():
    t0 = time.time()
    edge.openinsider = lambda *a, **k: None
    members, dates, P, by, _, FH, RK = expand.prepare()
    G = lambda **cfg: expand.gen({"single": 100000, **cfg}, dates, P, by, {}, FH, RK)
    R = {"asof": dates[-1], "rows": {}, "notes": {}}
    base_ev = G()
    base = outcomes(P, base_ev)

    def add(name, res):
        R["rows"][name] = row(P, dates, res)
        log(name, R["rows"][name]["t"], R["rows"][name]["cash"])

    add("Basis (Seite)", base)
    # 1. Verzögerung
    for d in (5, 10, 20):
        add(f"Einstieg {d} Handelstage später", outcomes(P, base_ev, delay=d))
    # 2. Parameter
    for x in (0.35, 0.45, 0.50):
        add(f"Dip -{int(x * 100)} %", outcomes(P, G(dip=("abs", -x))))
    for h in (10, 15, 30, 42):
        add(f"Haltedauer {h} Handelstage", outcomes(P, base_ev, hold=h))
    for st in (0.15, 0.20, 0.30, None):
        add(f"Stop {'kein' if st is None else '-' + str(int(st * 100)) + ' %'}", outcomes(P, base_ev, stop=st))
    add("Fenster 20 Tage", outcomes(P, G(win=20)))
    add("Fenster 45 Tage", outcomes(P, G(win=45)))
    # 3. ohne Crash-Phasen
    crash = lambda d: ("2020-02-15" <= d <= "2020-05-31") or ("2025-03-25" <= d <= "2025-05-31")
    add("ohne Crash-Phasen (2020 Feb–Mai, 2025 Ende März–Mai)", [e for e in base if not crash(e["d"])])
    add("nur Crash-Phasen", [e for e in base if crash(e["d"])])
    # 4. Klumpen
    per_day = {}
    for e in base_ev:
        per_day[e["d"]] = per_day.get(e["d"], 0) + 1
    top_days = sorted(per_day.items(), key=lambda x: -x[1])[:8]
    eq = robust.sim(P, dates, base, "cash")
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    mon = {}
    for n in range(1, len(eq)):
        m = dates[i0 + n][:7]
        mon[m] = mon.get(m, 0) + np.log(eq[n] / eq[n - 1])
    tot = np.log(eq[-1] / eq[0])
    best = sorted(mon.items(), key=lambda x: -x[1])
    R["notes"]["top_days"] = top_days
    R["notes"]["best_months"] = [(m, round(100 * (np.exp(v) - 1), 1)) for m, v in best[:6]]
    R["notes"]["share_top3"] = round(100 * sum(v for _, v in best[:3]) / tot, 0) if tot > 0 else None
    R["notes"]["share_top6"] = round(100 * sum(v for _, v in best[:6]) / tot, 0) if tot > 0 else None
    # 5. Überlebens-Verzerrung
    _, rows, _, px = edge.load_core()
    have = set(px.columns)
    buys = {}
    for r in rows:
        if r["kind"] == "st" and r["side"] == "P" and r["filed"] >= "2020-01-01" and not edge.NOISE.search(r.get("comment") or ""):
            buys.setdefault(r["t"], []).append(r)
    cl_in, cl_out, out_t = 0, 0, {}
    for t, a in buys.items():
        a.sort(key=lambda r: r["filed"])
        last = None
        for r in a:
            cut = (date.fromisoformat(r["filed"]) - timedelta(days=30)).isoformat()
            ms = {u["m"] for u in a if cut <= u["filed"] <= r["filed"]}
            big = max((u["lo"] or 0) for u in a if cut <= u["filed"] <= r["filed"])
            if len(ms) < 2 and big < 100000:
                continue
            if last and (date.fromisoformat(r["filed"]) - date.fromisoformat(last)).days < 90:
                continue
            last = r["filed"]
            if t in have:
                cl_in += 1
            else:
                cl_out += 1
                out_t[t] = out_t.get(t, 0) + 1
    R["notes"]["surv"] = {"mit_kurs": cl_in, "ohne_kurs": cl_out, "anteil": round(100 * cl_out / max(1, cl_in + cl_out), 1),
                          "beispiele": sorted(out_t.items(), key=lambda x: -x[1])[:15]}
    json.dump(R, open(os.path.join(OUT, "stress2.json"), "w"), ensure_ascii=False, indent=1)
    md = summary(R)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md)
    print(md)
    log(f"fertig in {time.time() - t0:.0f}s")


def summary(R):
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    L = [f"# Stresstest 2 (Kurse bis {R['asof']})", "",
         "Konto: 10 % je Trade, max. 8. Treffer = im Plus. 2020–23 / 2024–26 jeweils n · Treffer · schlägt S&P.", "",
         "| Szenario | Trades | Treffer | schlägt S&P | Ø Trade | Ø vs S&P | RR | 2020–23 | 2024–26 | Nur Trades p.a. / DD | Trades+S&P p.a. / DD |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in R["rows"].items():
        a, i, o = v["t"], v["is"], v["oos"]
        L.append(f"| {k} | {a.get('n')} | {f(a.get('win'), ' %')} | {f(a.get('beat'), ' %')} | {f(a.get('avg'), ' %')} | {f(a.get('ex'), ' %')} | {f(a.get('rr'))} | "
                 f"{i.get('n')} · {f(i.get('win'))} · {f(i.get('beat'))} | {o.get('n')} · {f(o.get('win'))} · {f(o.get('beat'))} | "
                 f"{v['cash']['cagr']} % / {v['cash']['mdd']} % | {v['ma']['cagr']} % / {v['ma']['mdd']} % |")
    n = R["notes"]
    L += ["", "## Klumpen", "", f"Meiste Signale an einem Tag: {n['top_days']}", "",
          f"Beste Monate (nur Trades): {n['best_months']}", "",
          f"Anteil des Gesamtgewinns aus den 3 besten Monaten: {n['share_top3']} %, aus den 6 besten: {n['share_top6']} %", "",
          "## Überlebens-Verzerrung", "",
          f"Cluster (2+ Käufer oder 100k) mit Kursdaten: {n['surv']['mit_kurs']}, OHNE Kursdaten: {n['surv']['ohne_kurs']} ({n['surv']['anteil']} %). "
          f"Beispiele ohne Kurse: {n['surv']['beispiele']}"]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run()
