"""
Capitol Signals – Test: Branchen-Limit (läuft in GitHub Actions, nach research/pubdate.py)

Höchstens 1 / 2 / 3 offene Trades pro Branche (Yahoo-Sektor). Konto: 10 % je Trade, max. 8 bzw. 15 gleichzeitig.
Getestet mit allen Signalen (Meldedatum) und mit den wirklich handelbaren (pünktlich in den Daten, siehe pubdate.py).
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge  # noqa: E402
import expand  # noqa: E402
import robust  # noqa: E402

log = edge.log


def sectors(tickers):
    f = os.path.join(edge.CACHE, "sectors.json")
    S = json.load(open(f)) if os.path.exists(f) else {}
    todo = [t for t in tickers if t not in S]
    if todo:
        import yfinance as yf
        for t in todo:
            try:
                S[t] = (yf.Ticker(t).get_info() or {}).get("sector") or "?"
            except Exception:  # noqa
                S[t] = "?"
            time.sleep(0.3)
        json.dump({k: v for k, v in S.items() if v != "?"}, open(f, "w"))   # Fehlschläge nicht dauerhaft merken
    return S


def sim(P, dates, res, sec, cap=None, mx=8, pp=0.10, rest="cash", L=100):
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    spy = P.spy
    ma = pd.Series(spy).rolling(L, min_periods=20).mean().values
    by = {}
    for e in sorted(res, key=lambda e: (e["i"], -e["n"])):
        by.setdefault(e["i"], []).append(e)
    cash, opn, eq, taken, skip_sec, peak_sec = 1.0, [], [], 0, 0, 0
    for k in range(i0, P.n):
        if rest == "ma" and k > i0 and spy[k - 1] > ma[k - 1] and spy[k] > 0 and spy[k - 1] > 0:
            cash *= spy[k] / spy[k - 1]
        for o in [o for o in opn if o["x"] == k]:
            cash += o["size"] * o["path"][-1]
            opn.remove(o)
        val = cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn)
        for e in by.get(k, []):
            if len(opn) >= mx:
                continue
            s = sec.get(e["t"], "?")
            if cap and s != "?" and sum(1 for o in opn if sec.get(o["t"]) == s) >= cap:
                skip_sec += 1
                continue
            want = val * pp
            size = min(want, cash)
            if size < want * 0.5:
                continue
            cash -= size
            opn.append({**e, "size": size})
            taken += 1
        cnt = {}
        for o in opn:
            cnt[sec.get(o["t"], "?")] = cnt.get(sec.get(o["t"], "?"), 0) + 1
        peak_sec = max([peak_sec] + [v for kk, v in cnt.items() if kk != "?"])
        eq.append(cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn))
    eq = np.array(eq)
    d = eq[1:] / eq[:-1] - 1
    p = robust.perf(eq)
    return {**p, "taken": taken, "skip_sec": skip_sec, "peak_sec": peak_sec, "worst_day": round(100 * float(d.min()), 1),
            "worst_month": round(100 * float(min(np.prod(1 + d[j:j + 21]) - 1 for j in range(0, len(d) - 21))), 1)}


def run():
    t0 = time.time()
    edge.openinsider = lambda *a, **k: None
    members, dates, P, by, _, FH, RK = expand.prepare()
    base = robust.outcomes(P, expand.gen({"single": 100000}, dates, P, by, {}, FH, RK))
    sets = {"alle Signale": base}
    tf = os.path.join(edge.OUT, "tradable.json")
    if os.path.exists(tf):
        ok = json.load(open(tf))
        ev = [{"t": t, "d": d, "i": i, "n": 2} for t, d, i in ok if i is not None]
        sets["nur pünktlich handelbare"] = robust.outcomes(P, ev)
    sec = sectors(sorted({e["t"] for e in base}))
    cnt = {}
    for e in base:
        cnt[sec.get(e["t"], "?")] = cnt.get(sec.get(e["t"], "?"), 0) + 1
    log("Sektoren:", cnt)
    L = [f"# Branchen-Limit (Kurse bis {dates[-1]})", "", "Signale je Branche: " + ", ".join(f"{k}: {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])), "",
         "| Signale | Freies Geld | Max. gleichzeitig | Limit pro Branche | p.a. | Max-DD | schlechtester Tag | schlechtester Monat | Trades | wegen Branche ausgelassen | max. gleiche Branche offen |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for nm, res in sets.items():
        for rest in ("cash", "ma"):
            for mx in (8, 15):
                for cap in (None, 3, 2, 1):
                    r = sim(P, dates, res, sec, cap, mx, rest=rest)
                    L.append(f"| {nm} | {'Cash' if rest == 'cash' else 'S&P > MA100'} | {mx} | {cap or 'keins'} | {r['cagr']} % | {r['mdd']} % | "
                             f"{r['worst_day']} % | {r['worst_month']} % | {r['taken']} | {r['skip_sec']} | {r['peak_sec']} |")
    md = "\n".join(L) + "\n"
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md)
    print(md)
    log(f"fertig in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    run()
