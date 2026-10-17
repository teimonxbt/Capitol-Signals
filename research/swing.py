"""
Capitol Signals – Zweite Strategie: Rücksetzer im Aufwärtstrend (läuft in GitHub Actions)

Idee: Große, liquide Aktien, die über ihrem 200-Tage-Schnitt stehen (Aufwärtstrend), nach ein paar schwachen
Tagen kaufen und nach der Erholung schnell wieder verkaufen. Soll in guten Jahren (wie 2024) Trades liefern.

Universum: S&P-100-Werte (Stand 2026, damit leicht zu Gunsten der Überlebenden verzerrt) – zum Vergleich
auch alle Aktien mit Kurs >= 10 $. Einstieg/Ausstieg immer zum Schlusskurs, ohne Gebühren.
Gemessen: Trades pro Jahr, Trefferquote, Ø Gewinn/Verlust, RR, Profit-Faktor, Anteil schlägt S&P (selber
Zeitraum), 2020–23 vs 2024–26, Konto-Simulation (10 % je Trade, max. 10 gleichzeitig, Rest Cash).
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge  # noqa: E402

log = edge.log
OUT = edge.OUT
SPLIT = "2024-01-01"
SP100 = """AAPL ABBV ABT ACN ADBE AIG AMD AMGN AMT AMZN AVGO AXP BA BAC BK BKNG BLK BMY BRK-B C CAT CHTR CL CMCSA COF COP
COST CRM CSCO CVS CVX DE DHR DIS DUK EMR F FDX GD GE GILD GM GOOG GOOGL GS HD HON IBM INTC INTU ISRG JNJ JPM KO LIN LLY
LMT LOW MA MCD MDLZ MDT MET META MMM MO MRK MS MSFT NEE NFLX NKE NOW NVDA ORCL PEP PFE PG PLTR PM PYPL QCOM RTX SBUX
SCHW SO SPG T TGT TMO TMUS TSLA TXN UBER UNH UNP UPS USB V VZ WFC WMT XOM""".split()


def rsi(c, n=2):
    d = np.diff(c, prepend=np.nan)
    up = pd.Series(np.where(d > 0, d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    dn = pd.Series(np.where(d < 0, -d, 0.0)).ewm(alpha=1 / n, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def signals(P, tickers, rule, exit_rule, i0, spy_filter=False, max_days=10, stop=None):
    spy = P.spy
    spy_ma = pd.Series(spy).rolling(200, min_periods=150).mean().values
    out = []
    for t in tickers:
        c = P.cols[t].astype(float)
        c = pd.Series(c).ffill().values
        if np.isnan(c[i0:]).mean() > 0.2:
            continue
        ma200 = pd.Series(c).rolling(200, min_periods=180).mean().values
        ma5 = pd.Series(c).rolling(5).mean().values
        r2 = rsi(c, 2)
        hi10 = pd.Series(c).rolling(10).max().values
        lo5 = pd.Series(c).rolling(5).min().values
        i = i0
        while i < P.n - 1:
            ok = c[i] > 0 and ma200[i] > 0 and c[i] > ma200[i] and c[i] >= 10
            if ok and spy_filter:
                ok = spy[i] > spy_ma[i]
            if ok:
                if rule == "rsi10":
                    ok = r2[i] < 10
                elif rule == "rsi5":
                    ok = r2[i] < 5
                elif rule == "down3":
                    ok = c[i] < c[i - 1] < c[i - 2] < c[i - 3]
                elif rule == "pull5":
                    ok = c[i] <= lo5[i] and c[i] / hi10[i] - 1 <= -0.05
            if not ok:
                i += 1
                continue
            x = None
            for j in range(i + 1, min(i + max_days, P.n - 1) + 1):
                r = c[j] / c[i] - 1
                if stop and r <= -stop:
                    x = j
                    break
                if exit_rule == "ma5" and c[j] > ma5[j]:
                    x = j
                    break
                if exit_rule == "up1" and c[j] > c[j - 1]:
                    x = j
                    break
            if x is None:
                x = i + max_days
                if x > P.n - 1:
                    break
            r = c[x] / c[i] - 1
            s = spy[x] / spy[i] - 1 if spy[i] > 0 and spy[x] > 0 else 0.0
            out.append({"t": t, "i": i, "x": x, "d": P.dates[i], "r": r, "s": s, "rsi": float(r2[i]) if np.isfinite(r2[i]) else 50.0,
                        "path": [c[k] / c[i] for k in range(i, x + 1)]})
            i = x + 1
    return out


def stats(a):
    if len(a) < 10:
        return {"n": len(a)}
    r = np.array([e["r"] for e in a])
    ex = np.array([e["r"] - e["s"] for e in a])
    w, l = r[r > 0], r[r <= 0]
    aw, al = (w.mean() if len(w) else 0), (l.mean() if len(l) else 0)
    hold = np.mean([e["x"] - e["i"] for e in a])
    return {"n": len(a), "win": round(100 * len(w) / len(r), 1), "beat": round(100 * float((ex > 0).mean()), 1),
            "avg": round(100 * r.mean(), 2), "aw": round(100 * aw, 2), "al": round(100 * al, 2),
            "rr": round(aw / -al, 2) if al < 0 else None, "pf": round(w.sum() / -l.sum(), 2) if l.sum() < 0 else None,
            "ex": round(100 * ex.mean(), 3), "hold": round(float(hold), 1)}


def sim(P, dates, res, i0, pp=0.10, mx=10, cost=0.0, dip=None, dpp=0.10, dmx=8, rest_ma=None):
    """Swing-Trades (res) mit 10 % je Trade. Optional zuerst Dip-Trades (dip, Vorrang), optional Rest im S&P über MA."""
    by, dby = {}, {}
    for e in res:
        by.setdefault(e["i"], []).append(e)
    for e in dip or []:
        dby.setdefault(e["i"], []).append(e)
    spy = P.spy
    ma = pd.Series(spy).rolling(rest_ma, min_periods=20).mean().values if rest_ma else None
    cash, opn, dop, eq = 1.0, [], [], []
    taken = []
    for k in range(i0, P.n):
        if ma is not None and k > i0 and spy[k - 1] > ma[k - 1] and spy[k] > 0 and spy[k - 1] > 0:
            cash *= spy[k] / spy[k - 1]
        for o in [o for o in opn if o["x"] == k]:
            cash += o["size"] * o["path"][-1] * (1 - cost)
            opn.remove(o)
        for o in [o for o in dop if o["x"] == k]:
            cash += o["size"] * o["path"][-1]
            dop.remove(o)
        val = cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn + dop)
        for e in dby.get(k, []):
            if len(dop) >= dmx:
                continue
            want = val * dpp
            size = min(want, cash)
            if size < want * 0.5:
                continue
            cash -= size
            dop.append({**e, "size": size})
        for e in sorted(by.get(k, []), key=lambda e: e["rsi"]):
            if len(opn) >= mx:
                break
            want = val * pp
            size = min(want, cash)
            if size < want * 0.5:
                break
            cash -= size
            opn.append({**e, "size": size})
            taken.append(e)
        eq.append(cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn + dop))
    eq = np.array(eq)
    yrs = (len(eq) - 1) / 252
    pk = np.maximum.accumulate(eq)
    years = {}
    for n, d in enumerate(dates[i0:]):
        years.setdefault(d[:4], [n, n])[1] = n
    yr = {y: round(100 * (eq[b] / eq[max(a - 1, 0)] - 1), 1) for y, (a, b) in years.items()}
    return {"cagr": round(100 * (eq[-1] ** (1 / yrs) - 1), 1), "mdd": round(100 * float((eq / pk - 1).min()), 1),
            "taken": len(taken), "tpy": round(len(taken) / yrs), "years": yr, "eq": eq}


def run():
    t0 = time.time()
    members, rows, dates, px = edge.load_core()
    P = edge.Px(px, dates)
    P.dates = dates
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    sp = [t for t in SP100 if t in P.cols]
    allu = [t for t in P.cols if t not in ("SPY", "QQQ") and np.nanmedian(P.cols[t][i0:]) >= 10]
    log("Universum S&P100:", len(sp), "alle >=10$:", len(allu))
    V = {}
    for uni, U in (("S&P100", sp),):
        for rule in ("rsi10", "rsi5", "down3", "pull5"):
            for ex in ("ma5", "up1"):
                V[f"{uni} · {rule} · Ausstieg {ex}"] = dict(U=U, rule=rule, exit_rule=ex)
        V[f"{uni} · rsi10 · ma5 · Stop -8 %"] = dict(U=U, rule="rsi10", exit_rule="ma5", stop=0.08)
        V[f"{uni} · rsi10 · ma5 · nur wenn S&P > MA200"] = dict(U=U, rule="rsi10", exit_rule="ma5", spy_filter=True)
        V[f"{uni} · rsi5 · ma5 · nur wenn S&P > MA200"] = dict(U=U, rule="rsi5", exit_rule="ma5", spy_filter=True)
    V["Alle >=10 $ · rsi10 · ma5"] = dict(U=allu, rule="rsi10", exit_rule="ma5")
    V["Alle >=10 $ · rsi5 · ma5 · S&P > MA200"] = dict(U=allu, rule="rsi5", exit_rule="ma5", spy_filter=True)
    V["S&P100 · down3 · ma5 · max 5"] = dict(U=sp, rule="down3", exit_rule="ma5", mx=5)
    V["S&P100 · rsi5 · ma5 · max 5"] = dict(U=sp, rule="rsi5", exit_rule="ma5", mx=5)
    R = {"asof": dates[-1], "v": {}, "combo": {}}
    spy_eq = P.spy[i0:] / P.spy[i0]
    keep = {}
    for name, cfg in V.items():
        U = cfg.pop("U")
        mx = cfg.pop("mx", 10)
        res = signals(P, U, i0=i0, **cfg)
        keep[name] = (res, mx)
        s = sim(P, dates, res, i0, mx=mx)
        s["c01"] = sim(P, dates, res, i0, mx=mx, cost=0.001)["cagr"]
        s["c02"] = sim(P, dates, res, i0, mx=mx, cost=0.002)["cagr"]
        eq = s.pop("eq")
        # Korrelation der Tagesrenditen mit dem S&P und mit der Dip-Strategie (grob)
        d1 = np.diff(eq) / eq[:-1]
        d2 = np.diff(spy_eq) / spy_eq[:-1]
        corr = float(np.corrcoef(d1, d2)[0, 1]) if d1.std() > 0 else None
        per = {}
        for e in res:
            per[e["d"][:4]] = per.get(e["d"][:4], 0) + 1
        R["v"][name] = {"all": stats(res), "is": stats([e for e in res if e["d"] < SPLIT]), "oos": stats([e for e in res if e["d"] >= SPLIT]),
                        "per": per, "sim": s, "corr": round(corr, 2) if corr is not None else None}
        log(name, R["v"][name]["all"], s["cagr"], s["mdd"])
    # ---- Kombination mit der Dip-Strategie (Dip hat Vorrang, 10 % je Trade, max. 8)
    try:
        import expand
        import robust
        edge.openinsider = lambda *a, **k: None
        mem2, d2, P2, by2, _, FH2, RK2 = expand.prepare()
        dip = robust.outcomes(P2, expand.gen({"single": 100000}, d2, P2, by2, {}, FH2, RK2))
        C = {"Dip + Rest Cash": dict(res=[], dip=dip),
             "Dip + Rest S&P über MA100": dict(res=[], dip=dip, rest_ma=100),
             "Dip + Rest S&P über MA200": dict(res=[], dip=dip, rest_ma=200)}
        for nm in ("S&P100 · down3 · Ausstieg ma5", "S&P100 · rsi5 · Ausstieg ma5", "S&P100 · down3 · ma5 · max 5"):
            res, mx = keep[nm]
            C[f"Dip + Swing ({nm})"] = dict(res=res, dip=dip, mx=mx)
            C[f"Dip + Swing ({nm}) · 0,1 % Kosten"] = dict(res=res, dip=dip, mx=mx, cost=0.001)
            C[f"Dip + Swing ({nm}) + Rest S&P über MA100"] = dict(res=res, dip=dip, mx=mx, rest_ma=100)
        for nm, cfg in C.items():
            s = sim(P2, d2, cfg.pop("res"), i0, **cfg)
            s.pop("eq")
            R["combo"][nm] = s
            log(nm, s)
    except Exception as e:  # noqa
        log("Kombi fehlgeschlagen:", type(e).__name__, e)
    json.dump(R, open(os.path.join(OUT, "swing.json"), "w"), ensure_ascii=False, indent=1)
    md = summary(R)
    sp_ = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp_:
        open(sp_, "a").write(md)
    print(md)
    log(f"fertig in {time.time() - t0:.0f}s")


def summary(R):
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    L = [f"# Zweite Strategie: Rücksetzer im Aufwärtstrend (Kurse bis {R['asof']})", "",
         "Kauf zum Schlusskurs, wenn Aktie über MA200 (und Kurs >= 10 $) und Signal; Verkauf wenn Schluss > MA5 (ma5) bzw. erster Plus-Tag (up1), spätestens nach 10 Tagen. "
         "rsi10/rsi5 = RSI(2) unter 10/5, down3 = 3 Minus-Tage in Folge, pull5 = 5-Tage-Tief und 5 % unter 10-Tage-Hoch. "
         "Konto: 10 % je Trade, max. 10 gleichzeitig (niedrigster RSI zuerst), Rest Cash.", "",
         "| Variante | Trades | pro Jahr | Treffer | Ø Gew. / Verl. | RR | PF | Ø Tage | schlägt S&P | Treffer 20–23 / 24–26 | Ø vs S&P 20–23 / 24–26 | Konto p.a. | mit 0,1 / 0,2 % Kosten | Trades/Jahr im Konto | Max-DD | Jahre | Korr. S&P |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in R["v"].items():
        a, i, o, s = v["all"], v["is"], v["oos"], v["sim"]
        L.append(f"| {k} | {a.get('n')} | {' '.join(f'{y[2:]}:{n}' for y, n in sorted(v['per'].items()))} | {f(a.get('win'), ' %')} | "
                 f"{f(a.get('aw'))} / {f(a.get('al'))} | {f(a.get('rr'))} | {f(a.get('pf'))} | {f(a.get('hold'))} | {f(a.get('beat'), ' %')} | "
                 f"{f(i.get('win'))} / {f(o.get('win'))} | {f(i.get('ex'))} / {f(o.get('ex'))} | {s['cagr']} % | {s.get('c01')} / {s.get('c02')} % | {s.get('tpy')} | {s['mdd']} % | "
                 f"{' '.join(f'{y[2:]}:{x:+.0f}' for y, x in s['years'].items())} | {f(v['corr'])} |")
    if R.get("combo"):
        L += ["", "## Kombination mit Dip-Cluster (Dip hat Vorrang)", "", "| Kombination | p.a. | Max-DD | Swing-Trades/Jahr | Jahre |", "|---|---|---|---|---|"]
        for k, s in R["combo"].items():
            L.append(f"| {k} | {s['cagr']} % | {s['mdd']} % | {s['tpy']} | {' '.join(f'{y[2:]}:{x:+.0f}' for y, x in s['years'].items())} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run()
