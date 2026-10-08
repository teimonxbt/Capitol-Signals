"""
Capitol Signals – Dashboard-Daten (Cluster, Ausschuss-Insider, Top-Politiker) + Benachrichtigungen

Alle Renditen werden ab VERÖFFENTLICHUNG gemessen: Einstieg zum Schlusskurs des ersten Handelstags
nach der Meldung, Ausstieg nach 30 / 60 / 90 Kalendertagen (21 / 42 / 63 Handelstage). Nur Käufe (Long).

1. Cluster: mindestens N verschiedene Politiker kaufen dieselbe Aktie innerhalb von 30 Tagen
   (nach Meldedatum), mehr Käufer als Verkäufer. Pro Aktie höchstens ein Signal je 63 Handelstage.
2. Ausschuss-Insider: Kauf einer Aktie aus der Branche, die ein Ausschuss des Politikers beaufsichtigt.
   Mitgliedschaften gibt es nur für den aktuellen Kongress → Backtest ab 2025.
3. Top-Politiker: Bilanz der Käufe je Haltedauer. Der Backtest „Top 10 folgen" nutzt zu jedem Zeitpunkt
   nur Käufe, die damals schon abgeschlossen waren (kein Blick in die Zukunft).
Dividenden-Reinvestitionen werden ignoriert.
"""
import json
import os
import re
from datetime import date, timedelta

import numpy as np

HOLDS = {"30": 21, "60": 42, "90": 63}
WIN = 30
MIN_NS = (2, 3, 4)
COOLDOWN = 63
COMMITTEE_START = "2025-01-03"      # Beginn des 119. Kongresses
TOP_N = 10
TOP_MIN = 5
SHRINK = 10
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


def _rets(col, spy, qqq, i, last):
    """Renditen (in %) je Haltedauer, nur wenn abgeschlossen; plus Stand heute."""
    o = {}
    if i is None:
        return o
    for k, h in HOLDS.items():
        if i + h <= last:
            o["r" + k] = _p(_r(col, i, i + h))
            o["s" + k] = _p(_r(spy, i, i + h))
            if qqq is not None:
                o["q" + k] = _p(_r(qqq, i, i + h))
    if i + max(HOLDS.values()) > last:
        o["rn"] = _p(_r(col, i, last))
        o["sn"] = _p(_r(spy, i, last))
    return o


def _curve(positions, cols, n, i0):
    """Gleichgewichtetes Portfolio aller offenen Positionen, täglich; Cash (0 %) wenn nichts offen ist."""
    s = np.zeros(n)
    c = np.zeros(n)
    for t, i, x in positions:
        col = cols[t]
        if i is None or x <= i:
            continue
        seg = col[i:x + 1]
        d = seg[1:] / seg[:-1] - 1
        d = np.where(np.isfinite(d), d, 0.0)
        s[i + 1:x + 1] += d
        c[i + 1:x + 1] += 1
    daily = np.divide(s, c, out=np.zeros(n), where=c > 0)
    eq = np.cumprod(1 + daily[i0:])
    eq = eq / eq[0]
    v = [round(float(e), 4) for e in eq[::STEP]]
    if (len(eq) - 1) % STEP:
        v.append(round(float(eq[-1]), 4))
    return v


def build(members, rows, dates, px, bench="SPY", tth=None, sectors=None):
    tth = tth or {}
    n = len(dates)
    last = n - 1
    cols = {c: px[c].values for c in px.columns}
    spy = cols[bench]
    qqq = cols.get("QQQ")
    i0 = next(i for i, d in enumerate(dates) if d >= CURVE_START)
    mth = [set(m.get("th") or []) for m in members]

    st = [r for r in rows if r["kind"] == "st" and r["t"] in cols and r["side"] in ("P", "S")
          and not (r["side"] == "P" and NOISE.search(r.get("comment") or ""))]
    # gleiche Person / Aktie / Meldetag / Richtung = ein Trade (mehrere Teilkäufe zusammenfassen)
    seen, trades = set(), []
    for r in sorted(st, key=lambda r: (r["filed"], r["tx"])):
        k = (r["m"], r["t"], r["filed"], r["side"])
        if k in seen:
            continue
        seen.add(k)
        trades.append(r)
    buys = [r for r in trades if r["side"] == "P"]
    cm = lambda r: bool(mth[r["m"]] & set(tth.get(r["t"], [])))

    by = {}
    for r in trades:
        by.setdefault(r["t"], []).append(r)

    # ------------------------------------------------------------------ 1) Cluster
    clusters = {}
    for mn in MIN_NS:
        out = []
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
                if len(b) < mn or len(s) >= len(b):
                    continue
                pos = r["pi"] if r["pi"] is not None else n
                if pos - last_sig < COOLDOWN:
                    continue
                last_sig = pos
                bw = [u for u in w if u["side"] == "P"]
                rec = {"t": tk, "d": r["filed"], "i": r["pi"], "n": len(b), "o": len(s), "m": sorted(b),
                       "cm": sorted({u["m"] for u in bw if cm(u)}),
                       "vol": round(sum(((u["lo"] or 0) + (u["hi"] or u["lo"] or 0)) / 2 for u in bw))}
                rec.update(_rets(col, spy, qqq, r["pi"], last))
                out.append(rec)
        out.sort(key=lambda s: (s["d"], s["n"]), reverse=True)
        curves = {}
        for k, h in HOLDS.items():
            for flag, sel in (("", out), ("c", [s for s in out if s["cm"]])):
                curves[k + flag] = _curve([(s["t"], s["i"], min(s["i"] + h, last)) for s in sel if s["i"] is not None], cols, n, i0)
        clusters[str(mn)] = {"signals": out, "curves": curves}

    # ------------------------------------------------------------------ 2) Ausschuss-Insider
    comm = []
    for r in buys:
        if r["filed"] < COMMITTEE_START or not cm(r):
            continue
        rec = {"m": r["m"], "t": r["t"], "d": r["filed"], "tx": r["tx"], "i": r["pi"], "lo": r["lo"], "hi": r["hi"],
               "th": sorted(mth[r["m"]] & set(tth.get(r["t"], [])))}
        rec.update(_rets(cols[r["t"]], spy, qqq, r["pi"], last))
        comm.append(rec)
    comm.sort(key=lambda s: s["d"], reverse=True)
    ci0 = next(i for i, d in enumerate(dates) if d >= COMMITTEE_START)
    comm_curves = {k: _curve([(s["t"], s["i"], min(s["i"] + h, last)) for s in comm if s["i"] is not None], cols, n, i0)
                   for k, h in HOLDS.items()}

    # ------------------------------------------------------------------ 3) Top-Politiker
    top = {}
    for k, h in HOLDS.items():
        # a) Rangliste nach heutigem Stand
        acc = {}
        for r in buys:
            i = r["pi"]
            if i is None or i + h > last:
                continue
            rr, rs = _r(cols[r["t"]], i, i + h), _r(spy, i, i + h)
            if rr is None or rs is None:
                continue
            a = acc.setdefault(r["m"], [0, 0.0, 0, 0.0])
            a[0] += 1
            a[1] += rr - rs
            a[2] += rr > rs
            a[3] += rr
        rank = []
        for m, (cnt, sx, hit, sr) in acc.items():
            if cnt < TOP_MIN:
                continue
            rank.append({"m": m, "n": cnt, "ex": _p(sx / cnt), "r": _p(sr / cnt), "hit": round(hit / cnt * 100),
                         "score": _p(sx / (cnt + SHRINK))})
        rank.sort(key=lambda x: x["score"], reverse=True)
        rank = rank[:25]

        # b) Backtest „Top 10 folgen" ohne Blick in die Zukunft
        events = sorted(((r["pi"] + h, r) for r in buys if r["pi"] is not None and r["pi"] + h <= last), key=lambda e: e[0])
        run, ei, follow = {}, 0, []
        for r in sorted((r for r in buys if r["pi"] is not None), key=lambda r: r["pi"]):
            while ei < len(events) and events[ei][0] < r["pi"]:
                u = events[ei][1]
                rr, rs = _r(cols[u["t"]], u["pi"], u["pi"] + h), _r(spy, u["pi"], u["pi"] + h)
                if rr is not None and rs is not None:
                    a = run.setdefault(u["m"], [0, 0.0])
                    a[0] += 1
                    a[1] += rr - rs
                ei += 1
            elig = sorted(((a[1] / (a[0] + SHRINK), m) for m, a in run.items() if a[0] >= TOP_MIN), reverse=True)[:TOP_N]
            if r["m"] in {m for _, m in elig} and elig[0][0] > 0:
                follow.append(r)
        fl = []
        for r in follow:
            rec = {"m": r["m"], "t": r["t"], "d": r["filed"], "i": r["pi"]}
            rec.update(_rets(cols[r["t"]], spy, qqq, r["pi"], last))
            fl.append(rec)
        fl.sort(key=lambda s: s["d"], reverse=True)
        curve = _curve([(s["t"], s["i"], min(s["i"] + h, last)) for s in fl], cols, n, i0)
        top[k] = {"rank": rank, "follow": fl, "curve": curve}

    # neueste Käufe aller Politiker in den Ranglisten (für „Neue Käufe der Top-Politiker")
    ranked = {x["m"] for t in top.values() for x in t["rank"]}
    recent_cut = (date.fromisoformat(dates[-1]) - timedelta(days=120)).isoformat()
    tb = []
    for r in buys:
        if r["m"] in ranked and r["filed"] >= recent_cut:
            rec = {"m": r["m"], "t": r["t"], "d": r["filed"], "tx": r["tx"], "i": r["pi"], "lo": r["lo"], "hi": r["hi"]}
            rec.update(_rets(cols[r["t"]], spy, qqq, r["pi"], last))
            tb.append(rec)
    tb.sort(key=lambda s: s["d"], reverse=True)

    # Benchmarks
    def bcurve(col):
        e = col[i0:] / col[i0]
        v = [round(float(x), 4) for x in e[::STEP]]
        if (len(e) - 1) % STEP:
            v.append(round(float(e[-1]), 4))
        return v

    # Mitglieder & Aktien, die vorkommen
    used_m, used_t = set(), set()
    for c in clusters.values():
        for s in c["signals"]:
            used_m |= set(s["m"])
            used_t.add(s["t"])
    for lst in [comm, tb] + [t["follow"] for t in top.values()]:
        for s in lst:
            used_m.add(s["m"])
            used_t.add(s["t"])
    for t in top.values():
        used_m |= {x["m"] for x in t["rank"]}
    asset = {}
    for r in rows:
        if r["t"] in used_t and r["t"] not in asset and r.get("asset"):
            asset[r["t"]] = r["asset"]
    sectors = sectors or {}
    mem = {}
    for i in sorted(used_m):
        m = members[i]
        mem[i] = {k: m.get(k) for k in ("name", "chamber", "party", "state", "office", "agency", "photo", "c", "th") if m.get(k)}
    tks = {t: {"a": asset.get(t, ""), "th": tth.get(t, []), "ind": sectors.get(t, "")} for t in sorted(used_t)}

    i_last_dates = dates[i0::STEP]
    if (n - 1 - i0) % STEP:
        i_last_dates = i_last_dates + [dates[-1]]
    return {
        "asof": dates[-1], "dates": dates, "curveStart": i0, "step": STEP, "curveDates": i_last_dates,
        "holds": HOLDS, "win": WIN, "cooldown": COOLDOWN, "committeeStart": COMMITTEE_START, "committeeIdx": ci0,
        "topN": TOP_N, "topMin": TOP_MIN,
        "bench": {"SPY": bcurve(spy), "QQQ": bcurve(qqq) if qqq is not None else None},
        "clusters": clusters, "committee": {"buys": comm, "curves": comm_curves},
        "top": top, "topBuys": tb, "members": mem, "tickers": tks,
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


def write_signals(out_dir, cache_dir, members, rows, dates, px, bench="SPY", site_url="", tth=None, sectors=None):
    D = build(members, rows, dates, px, bench, tth, sectors)
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
    M = D["members"]
    nm = lambda i: M.get(i, {}).get("name", "?")

    cl = D["clusters"]["3"]["signals"]
    ck = lambda s: f'{s["t"]}|L|{s["d"]}'
    new_c = [s for s in cl if ck(s) not in seen and s["d"] >= recent]
    seen |= {ck(s) for s in cl}

    cb = D["committee"]["buys"]
    kk = lambda r: f'C|{r["m"]}|{r["t"]}|{r["d"]}'
    new_k = [r for r in cb if kk(r) not in seen and r["d"] >= recent]
    seen |= {kk(r) for r in cb}

    top_now = {x["m"] for x in D["top"]["60"]["rank"][:TOP_N]}
    tk = lambda r: f'T|{r["m"]}|{r["t"]}|{r["d"]}'
    new_t = [r for r in D["topBuys"] if r["m"] in top_now and tk(r) not in seen and r["d"] >= recent]
    seen |= {tk(r) for r in D["topBuys"]}
    json.dump(sorted(seen), open(seen_file, "w"))

    if new_c or new_k or new_t:
        parts = [f'{s["t"]} Cluster' for s in new_c[:4]] + [f'{r["t"]} Ausschuss' for r in new_k[:3]] + [f'{r["t"]} Top' for r in new_t[:3]]
        title = "Capitol Signals: " + ", ".join(parts) + (" …" if len(new_c) + len(new_k) + len(new_t) > len(parts) else "")
        L = [title, "", f"Kursstand {dates[-1]}. Einstieg zum nächsten Schlusskurs, Haltedauer 30 bis 90 Tage.", ""]
        if new_c:
            L += ["**Neue Cluster** (mindestens 3 Politiker kaufen dieselbe Aktie):", "", "| Aktie | Käufer | Ausschuss-Bonus | gemeldet |", "|---|---|---|---|"]
            for s in new_c:
                L.append(f'| {s["t"]} | {s["n"]}: {", ".join(nm(i) for i in s["m"][:6])} | {"ja" if s["cm"] else "–"} | {s["d"]} |')
            L.append("")
        if new_k:
            L += ["**Neue Ausschuss-Käufe** (Kauf in der Branche des eigenen Ausschusses):", "", "| Aktie | Politiker | Ausschuss | Betrag | gemeldet |", "|---|---|---|---|---|"]
            for r in new_k[:25]:
                m = members[r["m"]]
                L.append(f'| {r["t"]} | {m["name"]} | {", ".join((m.get("c") or [m.get("agency") or ""])[:2])} | ${r["lo"] or 0:,}–${r["hi"] or 0:,} | {r["d"]} |')
            L.append("")
        if new_t:
            L += ["**Neue Käufe der Top-10-Politiker:**", "", "| Aktie | Politiker | Betrag | gemeldet |", "|---|---|---|---|"]
            for r in new_t[:25]:
                L.append(f'| {r["t"]} | {nm(r["m"])} | ${r["lo"] or 0:,}–${r["hi"] or 0:,} | {r["d"]} |')
            L.append("")
        if site_url:
            L += [f"Details: {site_url}"]
        L += ["", "Keine Anlageberatung. Signale beruhen auf historischen Mustern."]
        open(alert_file, "w").write("\n".join(L) + "\n")
    return D
