"""
Capitol Signals – Robustheits-Tests (läuft in GitHub Actions)

Strategie wie auf der Seite: Dip-Cluster (2+ Politiker ODER 1 Politiker ab 100k $, Aktie >= 40 % unter 52W-Hoch),
21 Handelstage halten, Stop -25 % (Schlusskurs), 10 % je Trade, max. 8 gleichzeitig.
Freies Geld: Cash oder S&P 500 solange über 100-Tage-Durchschnitt.

1. Stresstest: beste Trades raus, späterer Einstieg, Kosten, Stop einen Tag später, ohne Regierungs-Meldungen.
2. Monte-Carlo: Trades neu ziehen (Bootstrap) + Tagesrenditen in Monatsblöcken neu mischen.
3. S&P-Trendfilter über lange Historie (S&P 500 seit 1960, SPY seit 1993) mit allen großen Crashs.
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

HOLD, STOP = 21, 0.25
log = edge.log
OUT = edge.OUT
RNG = np.random.default_rng(7)


# =============================================================================== Trades
def outcomes(P, evs, delay=0, cost=0.0, stop_lag=0):
    res = []
    for e in evs:
        c, i0 = P.cols[e["t"]], e["i"] + delay
        if i0 + HOLD + stop_lag > P.n - 1 or not (c[i0] > 0) or not (P.spy[i0] > 0):
            continue
        path, lv, x = [], 1.0, i0 + HOLD
        for j in range(i0, i0 + HOLD + 1):
            if c[j] > 0:
                lv = c[j] / c[i0]
            path.append(lv)
            if j > i0 and lv <= 1 - STOP:
                x = j
                break
        if x < i0 + HOLD and stop_lag:          # Stop erst am nächsten Tag ausgeführt
            for j in range(x + 1, x + stop_lag + 1):
                if c[j] > 0:
                    lv = c[j] / c[i0]
                path.append(lv)
            x += stop_lag
        path[-1] *= (1 - cost)
        r = path[-1] - 1
        s = P.spy[x] / P.spy[i0] - 1 if P.spy[x] > 0 else 0.0
        res.append({**e, "i": i0, "x": x, "path": path, "r": r, "s": s})
    return res


def sim(P, dates, res, rest="ma", L=100, pp=0.10, mx=8):
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    spy = P.spy
    ma = pd.Series(spy).rolling(L, min_periods=20).mean().values
    by = {}
    for e in sorted(res, key=lambda e: (e["i"], -e["n"])):
        by.setdefault(e["i"], []).append(e)
    cash, opn, eq = 1.0, [], []
    for k in range(i0, P.n):
        if k > i0 and (rest == "spy" or (rest == "ma" and spy[k - 1] > ma[k - 1])) and spy[k] > 0 and spy[k - 1] > 0:
            cash *= spy[k] / spy[k - 1]
        for o in [o for o in opn if o["x"] == k]:
            cash += o["size"] * o["path"][-1]
            opn.remove(o)
        val = cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn)
        for e in by.get(k, []):
            if len(opn) >= mx:
                continue
            want = val * pp
            size = min(want, cash)
            if size < want * 0.5:
                continue
            cash -= size
            opn.append({**e, "size": size})
        eq.append(cash + sum(o["size"] * o["path"][min(k - o["i"], len(o["path"]) - 1)] for o in opn))
    return np.array(eq)


def perf(eq, n_days=None):
    yrs = (len(eq) - 1) / 252
    peak = np.maximum.accumulate(eq)
    return {"cagr": round(100 * (eq[-1] / eq[0]) ** (1 / yrs) - 100, 1), "mdd": round(100 * float((eq / peak - 1).min()), 1)}


def tstats(res):
    if not res:
        return {"n": 0}
    r = np.array([e["r"] for e in res])
    ex = np.array([e["r"] - e["s"] for e in res])
    w, l = r[r > 0], r[r <= 0]
    return {"n": len(r), "win": round(100 * len(w) / len(r), 1), "beat": round(100 * float((ex > 0).mean()), 1),
            "avg": round(100 * r.mean(), 2), "ex": round(100 * ex.mean(), 2),
            "rr": round(w.mean() / -l.mean(), 2) if len(l) and len(w) else None}


# =============================================================================== Langfrist-Trendfilter
def long_trend():
    import yfinance as yf
    out = {}
    for sym, start in (("^GSPC", "1955-01-01"), ("SPY", "1993-01-29")):
        try:
            df = yf.download(sym, start=start, auto_adjust=True, progress=False)
            c = df["Close"]
            if isinstance(c, pd.DataFrame):
                c = c.iloc[:, 0]
            c = c.dropna()
            if len(c) < 1000:
                raise ValueError("zu wenig Daten")
        except Exception as e:  # noqa
            log("Langfrist-Daten", sym, "fehlgeschlagen:", e)
            continue
        log(sym, len(c), "Tage ab", c.index[0].date())
        px = c.values
        dr = np.r_[0.0, px[1:] / px[:-1] - 1]
        dates = c.index
        res = {}
        first = 260
        def stats(r):
            eq = np.cumprod(1 + r[first:])
            yrs = len(eq) / 252
            pk = np.maximum.accumulate(eq)
            return {"cagr": round(100 * (eq[-1] ** (1 / yrs) - 1), 1), "mdd": round(100 * float((eq / pk - 1).min()), 1)}
        res["Halten"] = stats(dr)
        crashes = {"1973–74": ("1973-01-01", "1974-12-31"), "1987": ("1987-08-01", "1987-12-31"),
                   "2000–02": ("2000-03-01", "2002-12-31"), "2008–09": ("2007-10-01", "2009-03-31"),
                   "2020": ("2020-02-01", "2020-04-30"), "2022": ("2022-01-01", "2022-12-31")}
        def crash_ret(r):
            o = {}
            for k, (a, b) in crashes.items():
                m = (dates >= a) & (dates <= b)
                if m.sum() > 10 and dates[first] <= pd.Timestamp(a):
                    o[k] = round(100 * (np.prod(1 + r[m]) - 1), 1)
            return o
        res["Halten"]["crash"] = crash_ret(dr)
        for L in (50, 100, 150, 200, 250):
            ma = pd.Series(px).rolling(L).mean().values
            on = np.r_[False, (px[:-1] > ma[:-1])]
            r = np.where(on, dr, 0.0)
            sw = int(np.sum(on[first + 1:] != on[first:-1]))
            st = stats(r)
            st["sw_yr"] = round(sw / ((len(px) - first) / 252), 1)
            st["crash"] = crash_ret(r)
            # Dekaden: Rendite Filter minus Halten
            dec = {}
            for d0 in range(1960, 2030, 10):
                m = (dates >= f"{d0}-01-01") & (dates < f"{d0 + 10}-01-01")
                m[:first] = False
                if m.sum() > 500:
                    yrs = m.sum() / 252
                    dec[f"{d0}er"] = round(100 * ((np.prod(1 + r[m])) ** (1 / yrs) - (np.prod(1 + dr[m])) ** (1 / yrs)), 1)
            st["dek"] = dec
            res[f"MA{L}"] = st
        out[sym] = res
    return out


# =============================================================================== Lauf
def run():
    t0 = time.time()
    edge.openinsider = lambda *a, **k: None      # Insider-Daten werden hier nicht gebraucht
    members, dates, P, by, ins, FH, RK = expand.prepare()
    G = lambda by_=by, **cfg: expand.gen(cfg, dates, P, by_, {}, FH, RK)
    base = G(single=100000)
    log("Signale:", len(base))
    R = {"asof": dates[-1], "stress": {}, "mc": {}, "long": {}}

    def row(name, res):
        R["stress"][name] = {"t": tstats(res), "cash": perf(sim(P, dates, res, "cash")), "ma": perf(sim(P, dates, res, "ma"))}
        log(name, R["stress"][name])

    b = outcomes(P, base)
    row("Basis", b)
    srt = sorted(b, key=lambda e: e["r"], reverse=True)
    for k in (5, 10):
        top = {(e["t"], e["i"]) for e in srt[:k]}
        row(f"ohne die {k} besten Trades", [e for e in b if (e["t"], e["i"]) not in top])
    for d in (1, 2, 3):
        row(f"Einstieg {d} Tag{'e' if d > 1 else ''} später", outcomes(P, base, delay=d))
    for c in (0.003, 0.01):
        row(f"Kosten {c * 100:.1f} % pro Trade", outcomes(P, base, cost=c))
    row("Stop erst am Folgetag", outcomes(P, base, stop_lag=1))
    noexec = {t: [r for r in arr if members[r["m"]].get("chamber") != "executive"] for t, arr in by.items()}
    row("ohne Regierung (Trump/OGE)", outcomes(P, G(by_=noexec, single=100000)))
    row("Alles zusammen: ohne Top 5, +1 Tag, 0,3 % Kosten, Stop Folgetag",
        [e for e in outcomes(P, base, delay=1, cost=0.003, stop_lag=1) if (e["t"], e["i"] - 1) not in {(x["t"], x["i"]) for x in srt[:5]}])

    # ---- Monte-Carlo
    r = np.array([e["r"] for e in b])
    ex = np.array([e["r"] - e["s"] for e in b])
    boots = RNG.integers(0, len(r), (10000, len(r)))
    R["mc"]["trades"] = {
        "win_p5_p95": [round(float(np.percentile((r[boots] > 0).mean(1) * 100, q)), 1) for q in (5, 95)],
        "avg_p5_p95": [round(float(np.percentile(r[boots].mean(1) * 100, q)), 2) for q in (5, 95)],
        "ex_p5_p95": [round(float(np.percentile(ex[boots].mean(1) * 100, q)), 2) for q in (5, 95)],
        "p_ex_pos": round(float((ex[boots].mean(1) > 0).mean() * 100), 1),
    }
    for mode in ("cash", "ma"):
        eq = sim(P, dates, b, mode)
        d = eq[1:] / eq[:-1] - 1
        n, blk = len(d), 21
        cg, md = [], []
        for _ in range(5000):
            starts = RNG.integers(0, n - blk, n // blk + 1)
            s = np.concatenate([d[a:a + blk] for a in starts])[:n]
            e = np.cumprod(1 + s)
            cg.append((e[-1] ** (252 / n) - 1) * 100)
            md.append(float((e / np.maximum.accumulate(e) - 1).min() * 100))
        R["mc"][mode] = {"cagr_p5_p50_p95": [round(float(np.percentile(cg, q)), 1) for q in (5, 50, 95)],
                         "mdd_p50_p95_p99": [round(float(np.percentile(md, q)), 1) for q in (50, 5, 1)]}
        log("MC", mode, R["mc"][mode])

    # ---- Langfrist
    R["long"] = long_trend()
    json.dump(R, open(os.path.join(OUT, "robust.json"), "w"), ensure_ascii=False, indent=1)
    md = summary(R)
    open(os.path.join(OUT, "robust.md"), "w").write(md)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md)
    print(md)
    log(f"fertig in {time.time() - t0:.0f}s")


def summary(R):
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    L = [f"# Robustheit (Kurse bis {R['asof']})", "", "## 1. Stresstest", "",
         "10 % je Trade, max. 8. **Cash** = freies Geld als Cash, **MA100** = freies Geld im S&P über 100-Tage-Schnitt.", "",
         "| Szenario | Trades | Treffer | schlägt S&P | Ø Trade | Ø vs S&P | RR | Cash p.a. | Cash Max-DD | MA100 p.a. | MA100 Max-DD |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in R["stress"].items():
        t = v["t"]
        L.append(f"| {k} | {t.get('n')} | {f(t.get('win'), ' %')} | {f(t.get('beat'), ' %')} | {f(t.get('avg'), ' %')} | {f(t.get('ex'), ' %')} | {f(t.get('rr'))} | "
                 f"{v['cash']['cagr']} % | {v['cash']['mdd']} % | {v['ma']['cagr']} % | {v['ma']['mdd']} % |")
    m = R["mc"]
    L += ["", "## 2. Monte-Carlo", "",
          f"Trades 10.000× neu gezogen: Trefferquote 5–95 %: {m['trades']['win_p5_p95']} %, Ø Trade {m['trades']['avg_p5_p95']} %, "
          f"Ø vs S&P {m['trades']['ex_p5_p95']} %, Anteil mit positivem Vorteil: {m['trades']['p_ex_pos']} %", "",
          "Tagesrenditen in Monatsblöcken 5.000× neu gemischt:", "",
          "| Freies Geld | Rendite p.a. 5 % / Median / 95 % | Max-DD Median / schlechteste 5 % / schlechteste 1 % |", "|---|---|---|"]
    for k in ("cash", "ma"):
        L.append(f"| {'Cash' if k == 'cash' else 'S&P über MA100'} | {m[k]['cagr_p5_p50_p95']} | {m[k]['mdd_p50_p95_p99']} |")
    L += ["", "## 3. S&P-Trendfilter über lange Historie", ""]
    for sym, res in R["long"].items():
        L += [f"### {sym}", "", "| | p.a. | Max-DD | Wechsel/Jahr | " + " | ".join(res["Halten"]["crash"].keys()) + " | Dekaden: Filter minus Halten (p.a.) |",
              "|---" * (5 + len(res["Halten"]["crash"])) + "|"]
        for k, v in res.items():
            L.append(f"| {k} | {v['cagr']} % | {v['mdd']} % | {v.get('sw_yr', '–')} | " + " | ".join(f"{v['crash'].get(c, '–')} %" for c in res["Halten"]["crash"]) +
                     " | " + (", ".join(f"{d}: {x:+}" for d, x in v.get("dek", {}).items()) or "–") + " |")
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run()
