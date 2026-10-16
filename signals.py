"""
Capitol Signals – Dip-Cluster

Signal: mindestens 2 verschiedene Politiker melden innerhalb von 30 Tagen einen Kauf derselben Aktie,
es gibt mehr Käufer als Verkäufer, und die Aktie notiert 40 % oder mehr unter ihrem 52-Wochen-Hoch.
Einstieg zum Schlusskurs des ersten Handelstags nach der auslösenden Meldung, Verkauf nach 30 Tagen
(21 Handelstage). Pro Aktie höchstens ein Signal je 63 Handelstage. Dividenden-Reinvestitionen zählen nicht.

Warum nur das: In der Forschung (research/edge.py) war das der einzige Bereich, der in beiden
Testzeiträumen (2020–23 und 2024–26) verlässlich den S&P 500 geschlagen hat. Alles andere (normale
Cluster, Ausschuss-Käufe, Top-Politiker, Firmen-Insider, technische Filter) brachte keinen Vorteil.
"""
import json
import os
import re
from datetime import date, timedelta

import numpy as np

HOLD = 21          # 30 Kalendertage
WIN = 30           # Zeitfenster für mehrere Käufer (Kalendertage)
MIN_N = 2
DIP = -40          # mindestens 40 % unter dem 52-Wochen-Hoch
COOLDOWN = 63
STOP = -25         # Notfall-Stop (Schlusskurs)
TARGET = 15        # optionales Kursziel
SIZE = 4           # Positionsgröße in % des Depots
CURVE_START = "2020-01-01"
STEP = 5
NOISE = re.compile(r"reinvest|dividend", re.I)


def _r(col, i, j):
    if i is None or j is None:
        return None
    a, b = col[i], col[j]
    if not (a > 0) or not (b > 0):
        return None
    return float(b / a - 1)


def _p(x):
    return None if x is None else round(x * 100, 2)


def _from_high(col, i):
    w = col[max(0, i - 252):i + 1]
    w = w[w > 0]
    if len(w) < 60 or not (col[i] > 0):
        return None
    return round(float(col[i] / w.max() - 1) * 100, 1)


def _curve(positions, cols, spy, n, i0):
    """Depot nach den Regeln: je Trade SIZE % des Depots, höchstens 5 gleichzeitig, Notfall-Stop auf
    Schlusskurs-Basis, Verkauf nach HOLD Tagen. Das restliche Geld liegt im S&P 500 (SPY)."""
    w = np.zeros(n)          # Summe der Gewichte offener Trades
    rs = np.zeros(n)         # Summe gewichteter Tagesrenditen
    cnt = np.zeros(n)
    for t, i, x in sorted(positions, key=lambda p: p[1]):
        col = cols[t]
        if i is None or x <= i or not (col[i] > 0):
            continue
        if cnt[i + 1] >= 5:
            continue
        for j in range(i + 1, x + 1):     # Notfall-Stop
            if col[j] > 0 and col[j] / col[i] - 1 <= STOP / 100:
                x = j
                break
        seg = col[i:x + 1]
        d = seg[1:] / seg[:-1] - 1
        d = np.where(np.isfinite(d), np.clip(d, -0.5, 1.0), 0.0)
        rs[i + 1:x + 1] += SIZE / 100 * d
        w[i + 1:x + 1] += SIZE / 100
        cnt[i + 1:x + 1] += 1
    sd = np.r_[0.0, spy[1:] / spy[:-1] - 1]
    sd = np.where(np.isfinite(sd), sd, 0.0)
    daily = rs + (1 - w) * sd
    eq = np.cumprod(1 + daily[i0:])
    v = [round(float(e), 4) for e in eq[::STEP]]
    if (len(eq) - 1) % STEP:
        v.append(round(float(eq[-1]), 4))
    return v


def _bcurve(col, i0):
    e = col[i0:] / col[i0]
    v = [round(float(x), 4) for x in e[::STEP]]
    if (len(e) - 1) % STEP:
        v.append(round(float(e[-1]), 4))
    return v


def build(members, rows, dates, px, bench="SPY"):
    n = len(dates)
    last = n - 1
    cols = {c: px[c].values for c in px.columns}
    spy = cols[bench]
    qqq = cols.get("QQQ")
    i0 = next(i for i, d in enumerate(dates) if d >= CURVE_START)

    st = [r for r in rows if r["kind"] == "st" and r["t"] in cols and r["side"] in ("P", "S")
          and not (r["side"] == "P" and NOISE.search(r.get("comment") or ""))]
    seen, trades = set(), []
    for r in sorted(st, key=lambda r: (r["filed"], r["tx"])):
        k = (r["m"], r["t"], r["filed"], r["side"])
        if k not in seen:
            seen.add(k)
            trades.append(r)
    by = {}
    for r in trades:
        by.setdefault(r["t"], []).append(r)

    allc, sig = [], []
    for tk, arr in by.items():
        col = cols[tk]
        last_sig = -10 ** 9
        for r in arr:
            if r["side"] != "P":
                continue
            cut = (date.fromisoformat(r["filed"]) - timedelta(days=WIN)).isoformat()
            w = [u for u in arr if cut <= u["filed"] <= r["filed"]]
            b = {u["m"] for u in w if u["side"] == "P"}
            s = {u["m"] for u in w if u["side"] == "S"}
            if len(b) < MIN_N or len(s) >= len(b):
                continue
            i = r["pi"]
            pos = i if i is not None else n
            if pos - last_sig < COOLDOWN:
                continue
            last_sig = pos
            fh = _from_high(col, i if i is not None else last)
            rec = {"t": tk, "d": r["filed"], "i": i, "n": len(b), "o": len(s), "m": sorted(b), "fh": fh,
                   "vol": round(sum(((u["lo"] or 0) + (u["hi"] or u["lo"] or 0)) / 2 for u in w if u["side"] == "P"))}
            if i is not None and i + HOLD <= last:
                rec["r"] = _p(_r(col, i, i + HOLD))
                rec["s"] = _p(_r(spy, i, i + HOLD))
                if qqq is not None:
                    rec["q"] = _p(_r(qqq, i, i + HOLD))
            elif i is not None:
                rec["rn"] = _p(_r(col, i, last))
                rec["sn"] = _p(_r(spy, i, last))
            if i is not None and col[i] > 0:
                rec["ep"] = round(float(col[i]), 2)
            if col[last] > 0:
                rec["lp"] = round(float(col[last]), 2)
            allc.append(rec)
            if fh is not None and fh <= DIP:
                if i is not None and col[i] > 0:
                    seg = col[i:min(i + HOLD, last) + 1]
                    rec["path"] = [round(float(v / col[i]), 4) if v > 0 else None for v in seg]
                sig.append(rec)
    sig.sort(key=lambda s: (s["d"], s["n"]), reverse=True)

    def stats(a):
        d = [x for x in a if x.get("r") is not None and x.get("s") is not None]
        if not d:
            return {"n": 0}
        e = sorted(x["r"] - x["s"] for x in d)
        return {"n": len(d), "beat": round(100 * sum(v > 0 for v in e) / len(e)), "ex": round(sum(e) / len(e), 2),
                "med": round(e[len(e) // 2], 2)}

    curve = _curve([(s["t"], s["i"], min(s["i"] + HOLD, last)) for s in sig if s["i"] is not None], cols, spy, n, i0)
    used_m = {m for s in sig for m in s["m"]}
    used_t = {s["t"] for s in sig}
    asset = {}
    for r in rows:
        if r["t"] in used_t and r["t"] not in asset and r.get("asset"):
            asset[r["t"]] = r["asset"]
    mem = {i: {k: members[i].get(k) for k in ("name", "chamber", "party", "state", "office") if members[i].get(k)}
           for i in sorted(used_m)}
    cd = dates[i0::STEP]
    if (n - 1 - i0) % STEP:
        cd = cd + [dates[-1]]
    return {
        "asof": dates[-1], "dates": dates, "curveDates": cd,
        "rules": {"hold": HOLD, "days": 30, "win": WIN, "min_n": MIN_N, "dip": DIP, "cooldown": COOLDOWN,
                  "stop": STOP, "target": TARGET, "size": SIZE},
        "signals": sig, "curve": curve,
        "bench": {"SPY": _bcurve(spy, i0), "QQQ": _bcurve(qqq, i0) if qqq is not None else None},
        "compare": {"dip": stats(sig), "alle": stats(allc), "ohne_dip": stats([x for x in allc if x not in sig])},
        "members": mem, "tickers": {t: {"a": asset.get(t, "")} for t in sorted(used_t)},
    }


def write_ticker_trades(out_dir, members, rows, used):
    """Trades je Aktie für die Detailansicht, in Dateien nach Anfangsbuchstabe."""
    d = os.path.join(out_dir, "tr")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    bk = {}
    for r in rows:
        if r["t"] in used and r["kind"] == "st" and r["side"] in ("P", "S"):
            c = r["t"][0] if r["t"][0].isalpha() else "0"
            bk.setdefault(c, {}).setdefault(r["t"], []).append(
                [r["m"], r["side"], r["tx"], r["filed"], r["lo"], r["hi"], 1 if NOISE.search(r.get("comment") or "") else 0])
    for c, v in bk.items():
        json.dump(v, open(os.path.join(d, c + ".json"), "w"), separators=(",", ":"))
    return {i: {k: members[i].get(k) for k in ("name", "party", "chamber") if members[i].get(k)}
            for v in bk.values() for arr in v.values() for i in {x[0] for x in arr}}


def write_signals(out_dir, cache_dir, members, rows, dates, px, bench="SPY", site_url="", *_, **__):
    D = build(members, rows, dates, px, bench)
    extra = write_ticker_trades(out_dir, members, rows, set(D["tickers"]))
    for i, v in extra.items():
        D["members"].setdefault(i, v)
    json.dump(D, open(os.path.join(out_dir, "dash.json"), "w"), separators=(",", ":"), ensure_ascii=False)

    # ------------------------------------------------------------------ Benachrichtigung (GitHub Issue → E-Mail)
    root = os.path.dirname(os.path.abspath(cache_dir))
    alert_file = os.path.join(root, "alerts.md")
    if os.path.exists(alert_file):
        os.remove(alert_file)
    seen_file = os.path.join(cache_dir, "alerts_seen.json")
    seen = set(json.load(open(seen_file))) if os.path.exists(seen_file) else set()
    recent = (date.fromisoformat(dates[-1]) - timedelta(days=7)).isoformat()
    nm = lambda i: D["members"].get(i, {}).get("name", "?")
    key = lambda s: f'D|{s["t"]}|{s["d"]}'
    new = [s for s in D["signals"] if key(s) not in seen and s["d"] >= recent]
    seen |= {key(s) for s in D["signals"]}
    json.dump(sorted(seen), open(seen_file, "w"))
    if new:
        title = "Dip-Cluster: " + ", ".join(s["t"] for s in new[:6]) + (" …" if len(new) > 6 else "")
        L = [title, "", f"Kursstand {dates[-1]}. Regeln: am nächsten Handelstag zum Schlusskurs kaufen, "
             f"{SIZE} % Positionsgröße, Notfall-Stop {STOP} %, optional Ziel +{TARGET} %, nach 30 Tagen verkaufen.", "",
             "| Aktie | Käufer | unter 52W-Hoch | letzter Kurs | Stop | gemeldet |", "|---|---|---|---|---|---|"]
        for s in new:
            lp = s.get("lp")
            L.append(f'| {s["t"]} | {s["n"]}: {", ".join(nm(i) for i in s["m"][:6])} | {s["fh"]:.0f} % | '
                     f'{lp if lp else "–"} | {round(lp * (1 + STOP / 100), 2) if lp else "–"} | {s["d"]} |')
        L += ["", "Vor dem Kauf kurz prüfen: Warum ist die Aktie gefallen? Bei Betrugsverdacht, Insolvenzgefahr oder Delisting nicht kaufen."]
        if site_url:
            L += ["", f"Details: {site_url}"]
        L += ["", "Keine Anlageberatung. Signale beruhen auf historischen Mustern mit wenigen Fällen."]
        open(alert_file, "w").write("\n".join(L) + "\n")
    return D
