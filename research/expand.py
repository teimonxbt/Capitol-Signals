"""
Capitol Signals – Mehr Trades in gleicher Qualität? (läuft in GitHub Actions)

Basis = Dip-Cluster wie auf der Seite: 2+ Politiker kaufen innerhalb von 30 Tagen, mehr Käufer als Verkäufer,
Aktie >= 40 % unter 52-Wochen-Hoch, Einstieg Schlusskurs am ersten Handelstag nach der Meldung,
Verkauf nach 21 Handelstagen oder Stop -25 % (Schlusskurs), 63 Handelstage Sperre je Aktie.

Getestete Erweiterungen:
  1. relativer Dip  (Aktie gehört an dem Tag zu den x % am stärksten gefallenen Aktien)
  2. gelockerte Dip-Schwelle (-35 / -30 / -25 %)
  3. ein Käufer reicht bei großem Kauf (>= 50k / 100k / 250k $)
  4. Firmen-Insider-Kauf zählt als zweiter Käufer
  5. Zeitfenster 60 Tage, Sperre 21 Tage
  + Kombinationen.

Für jede Variante: Trades pro Jahr, Trefferquote (absolut im Plus), Ø Gewinn/Verlust, RR, Profit-Faktor,
Anteil schlägt S&P, getrennt 2020–23 / 2024–26, und eine Konto-Simulation (10 % je Trade, max. 15, Rest Cash).
Wichtig ist auch die Spalte "nur neue Trades": Qualität der Trades, die die Basis NICHT hatte.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge  # noqa: E402

HOLD, STOP, SPLIT = 21, 0.25, "2024-01-01"
OUT = edge.OUT
log = edge.log


# =============================================================================== Daten
def prepare():
    members, rows, dates, px = edge.load_core()
    P = edge.Px(px, dates)
    log("Kurse:", px.shape, "bis", dates[-1])
    # Abstand zum 52-Wochen-Hoch für alle Aktien und jeden Tag + Rang im Markt
    a = px.where(px > 0)
    hi = a.rolling(253, min_periods=60).max()
    fh = (a / hi - 1)
    etf = {c for c in px.columns if c in ("SPY", "QQQ", "IWM", "DIA", "TLT", "GLD")}
    fh_u = fh.drop(columns=[c for c in etf if c in fh.columns])
    # nur Aktien mit Kurs >= 3 $ für den Markt-Rang (sonst verzerren Pennystocks)
    fh_u = fh_u.where(a.drop(columns=[c for c in etf if c in a.columns]) >= 3)
    rank = fh_u.rank(axis=1, pct=True)
    FH = {c: fh[c].values for c in fh.columns}
    RK = {c: rank[c].values for c in rank.columns}
    log("Markt-Rang berechnet, Aktien pro Tag Ø", int(fh_u.notna().sum(axis=1).iloc[-500:].mean()))

    st = [r for r in rows if r["kind"] == "st" and r["t"] in P.cols and r["side"] in ("P", "S")
          and not (r["side"] == "P" and edge.NOISE.search(r.get("comment") or ""))]
    seen, trades = set(), []
    for r in sorted(st, key=lambda r: (r["filed"], r["tx"])):
        k = (r["m"], r["t"], r["filed"], r["side"])
        if k not in seen:
            seen.add(k)
            trades.append(r)
    by = {}
    for r in trades:
        by.setdefault(r["t"], []).append(r)

    ins = {}
    try:
        ib = edge.openinsider()
        if ib is not None and not ib.empty:
            ib = ib[(ib["filed"] >= "2019-12-01") & ib["t"].isin(P.cols.keys())]
            ib = ib[ib["val"].fillna(0) >= 10000]
            for t, g in ib.groupby("t"):
                ins[t] = sorted(set(zip(g["filed"], g["cik"])))
        log("Insider-Käufe (>=10k $) in", len(ins), "Aktien")
    except Exception as e:  # noqa
        log("Insider-Daten nicht verfügbar:", type(e).__name__, str(e)[:120])
    return members, dates, P, by, ins, FH, RK


# =============================================================================== Signale
def gen(cfg, dates, P, by, ins, FH, RK):
    """cfg: win, min_n, dip=('abs', -0.40) | ('rel', 0.15), single (Mindestbetrag oder None), ins (bool), cd"""
    win, mn, cd = cfg.get("win", 30), cfg.get("min_n", 2), cfg.get("cd", 63)
    kind, thr = cfg.get("dip", ("abs", -0.40))
    single, use_ins = cfg.get("single"), cfg.get("ins", False)
    out = []
    for t, arr in by.items():
        if t not in FH:
            continue
        evd = [(r["filed"], r["pi"]) for r in arr if r["side"] == "P"]
        if use_ins and t in ins:
            evd += [(f, P.idx_after(f)) for f, _ in ins[t]]
        evd = sorted({e for e in evd if e[1] is not None})
        last = -10 ** 9
        for d, i in evd:
            if i - last < cd:
                continue
            cut = (date.fromisoformat(d) - timedelta(days=win)).isoformat()
            w = [u for u in arr if cut <= u["filed"] <= d]
            b = {u["m"] for u in w if u["side"] == "P"}
            s = {u["m"] for u in w if u["side"] == "S"}
            if not b:
                continue
            ni = 1 if use_ins and t in ins and any(cut <= f <= d for f, _ in ins[t]) else 0
            big = max(((u["lo"] or 0) for u in w if u["side"] == "P"), default=0)
            ok = (len(b) + ni >= mn and len(s) < len(b) + ni) or (single and big >= single and len(s) < len(b))
            if not ok:
                continue
            f = FH[t][i]
            if not np.isfinite(f):
                continue
            if kind == "abs" and f > thr:
                continue
            if kind == "rel":
                rk = RK.get(t)
                if rk is None or not np.isfinite(rk[i]) or rk[i] > thr:
                    continue
            last = i
            out.append({"t": t, "d": d, "i": i, "n": len(b), "ni": ni, "big": big, "fh": float(f)})
    return out


def union(*lists, cd=63):
    a = sorted([e for L in lists for e in L], key=lambda e: (e["i"], -e["n"]))
    last, out = {}, []
    for e in a:
        if e["i"] - last.get(e["t"], -10 ** 9) < cd:
            continue
        last[e["t"]] = e["i"]
        out.append(e)
    return out


def outcome(P, evs):
    res = []
    for e in evs:
        c, i = P.cols[e["t"]], e["i"]
        if i + HOLD > P.n - 1 or not (c[i] > 0) or not (P.spy[i] > 0):
            continue
        x, path = i + HOLD, []
        lv = 1.0
        for j in range(i, i + HOLD + 1):
            if c[j] > 0:
                lv = c[j] / c[i]
            path.append(lv)
            if j > i and lv <= 1 - STOP:
                x = j
                break
        r = path[-1] - 1
        s = P.spy[x] / P.spy[i] - 1 if P.spy[x] > 0 else 0.0
        res.append({**e, "r": r, "s": s, "x": x, "path": path, "stop": x < i + HOLD})
    return res


# =============================================================================== Kennzahlen
def stats(a):
    if len(a) < 5:
        return {"n": len(a)}
    r = np.array([e["r"] for e in a])
    ex = np.array([e["r"] - e["s"] for e in a])
    w, l = r[r > 0], r[r <= 0]
    aw, al = (w.mean() if len(w) else 0), (l.mean() if len(l) else 0)
    return {"n": len(a), "win": round(100 * len(w) / len(r), 1), "beat": round(100 * float((ex > 0).mean()), 1),
            "avg": round(100 * r.mean(), 2), "aw": round(100 * aw, 1), "al": round(100 * al, 1),
            "rr": round(aw / -al, 2) if al < 0 else None,
            "pf": round(w.sum() / -l.sum(), 2) if l.sum() < 0 else None,
            "ex": round(100 * ex.mean(), 2), "stops": int(sum(e["stop"] for e in a))}


def sim(P, dates, res, pp=0.10, mx=15):
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    by = {}
    for e in sorted(res, key=lambda e: (e["i"], -e["n"])):
        by.setdefault(e["i"], []).append(e)
    cash, opn, eq = 1.0, [], []
    for k in range(i0, P.n):
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
    eq = np.array(eq)
    yrs = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[i0])).days / 365.25
    peak = np.maximum.accumulate(eq)
    return {"cagr": round(100 * (eq[-1] ** (1 / yrs) - 1), 1), "mdd": round(100 * float((eq / peak - 1).min()), 1)}


def per_year(a):
    o = {str(y): 0 for y in range(2020, int(a[-1]["d"][:4]) + 1)} if a else {}
    for e in a:
        o[e["d"][:4]] = o.get(e["d"][:4], 0) + 1
    return o


def is_new(e, base):
    return not any(b["t"] == e["t"] and abs(b["i"] - e["i"]) <= 10 for b in base)


# =============================================================================== Lauf
def run():
    t0 = time.time()
    members, dates, P, by, ins, FH, RK = prepare()
    G = lambda **cfg: gen(cfg, dates, P, by, ins, FH, RK)
    A40 = ("abs", -0.40)
    V = {}
    V["Basis (Seite)"] = G()
    for x in (0.35, 0.30, 0.25):
        V[f"Dip -{int(x * 100)} %"] = G(dip=("abs", -x))
    for q in (0.05, 0.10, 0.15, 0.20):
        V[f"Rel. Dip: schlechteste {int(q * 100)} %"] = G(dip=("rel", q))
    for amt in (50000, 100000, 250000):
        V[f"1 Käufer ab {amt // 1000}k $ (Dip -40)"] = G(single=amt)
    V["1 Käufer ab 100k $ (Dip -30)"] = G(single=100000, dip=("abs", -0.30))
    V["1 Käufer ab 100k $ (Rel. 15 %)"] = G(single=100000, dip=("rel", 0.15))
    if ins:
        V["Insider zählt als Käufer (Dip -40)"] = G(ins=True)
        V["Insider zählt als Käufer (Dip -30)"] = G(ins=True, dip=("abs", -0.30))
        V["Insider zählt als Käufer (Rel. 15 %)"] = G(ins=True, dip=("rel", 0.15))
    V["Fenster 60 Tage"] = G(win=60)
    V["Sperre 21 Tage"] = G(cd=21)
    V["Fenster 60 + Sperre 21"] = G(win=60, cd=21)
    V["Rel. 15 % + Fenster 60"] = G(dip=("rel", 0.15), win=60)
    V["Kombi: Basis + Rel. 15 %"] = union(V["Basis (Seite)"], V["Rel. Dip: schlechteste 15 %"])
    V["Kombi: Basis + 1 Käufer 100k"] = union(V["Basis (Seite)"], V["1 Käufer ab 100k $ (Dip -40)"])
    k = [V["Basis (Seite)"], V["Rel. Dip: schlechteste 15 %"], V["1 Käufer ab 100k $ (Dip -40)"], V["Fenster 60 Tage"]]
    if ins:
        V["Kombi: Basis + Insider"] = union(V["Basis (Seite)"], V["Insider zählt als Käufer (Dip -40)"])
        k.append(V["Insider zählt als Käufer (Dip -40)"])
    V["Kombi: alles (Basis, Rel.15, 100k, Insider, 60 T)"] = union(*k)

    base = outcome(P, V["Basis (Seite)"])
    R = {"asof": dates[-1], "variants": {}}
    for name, evs in V.items():
        res = outcome(P, evs)
        new = [e for e in res if is_new(e, base)]
        py = per_year(sorted(evs, key=lambda e: e["d"]))
        R["variants"][name] = {
            "all": stats(res), "is": stats([e for e in res if e["d"] < SPLIT]), "oos": stats([e for e in res if e["d"] >= SPLIT]),
            "new": stats(new), "years": py, "sim": sim(P, dates, res),
            "sim15": sim(P, dates, res, 0.15, 15),
        }
        log(name, len(evs), R["variants"][name]["all"].get("win"), R["variants"][name]["sim"])
    R["insider"] = bool(ins)
    json.dump(R, open(os.path.join(OUT, "expand.json"), "w"), ensure_ascii=False, indent=1)
    md = summary(R)
    open(os.path.join(OUT, "expand.md"), "w").write(md)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md)
    print(md)
    log(f"fertig in {time.time() - t0:.0f}s")


def summary(R):
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    L = [f"# Mehr Trades in gleicher Qualität? (Kurse bis {R['asof']})", "",
         "Halten 21 Handelstage, Stop -25 % (Schlusskurs). **Treffer** = Trade im Plus. **schlägt S&P** = besser als SPY im selben Zeitraum. "
         "**Konto** = 10 % je Trade, max. 15 gleichzeitig, Rest Cash (in Klammern 15 % je Trade). "
         "**Neu** = nur Trades, die die Basis nicht hatte. Firmen-Insider-Daten: " + ("ja" if R["insider"] else "NICHT verfügbar"), "",
         "| Variante | Trades | pro Jahr | Treffer | Ø Gew. / Verl. | RR | PF | schlägt S&P | Treffer 20–23 / 24–26 | S&P 20–23 / 24–26 | Konto p.a. | Max. Rückgang | Neu: n · Treffer · S&P |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, v in R["variants"].items():
        a, i, o, n = v["all"], v["is"], v["oos"], v["new"]
        yrs = " ".join(f"{y[2:]}:{c}" for y, c in v["years"].items())
        L.append(f"| {name} | {a.get('n')} | {yrs} | {f(a.get('win'), ' %')} | {f(a.get('aw'))} / {f(a.get('al'))} | {f(a.get('rr'))} | {f(a.get('pf'))} | "
                 f"{f(a.get('beat'), ' %')} | {f(i.get('win'))} / {f(o.get('win'))} | {f(i.get('beat'))} / {f(o.get('beat'))} | "
                 f"{f(v['sim']['cagr'], ' %')} ({f(v['sim15']['cagr'], ' %')}) | {f(v['sim']['mdd'], ' %')} ({f(v['sim15']['mdd'], ' %')}) | "
                 f"{n.get('n')} · {f(n.get('win'), ' %')} · {f(n.get('beat'), ' %')} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run()
