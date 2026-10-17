"""
Capitol Signals – Dip-Cluster

Signal: mindestens 2 verschiedene Politiker kaufen innerhalb von 30 Tagen dieselbe Aktie, mehr Käufer als Verkäufer,
und die Aktie notiert 40 % oder mehr unter ihrem 52-Wochen-Hoch. Ein einzelner Politiker reicht, wenn er mindestens
100.000 $ kauft (research/expand.py: hält die Qualität der Basis; Firmen-Insider als zweiter Käufer dagegen nicht).
Einstieg zum Schlusskurs des ersten Handelstags nach der auslösenden Meldung, Verkauf nach 30 Tagen
(21 Handelstage). Pro Aktie höchstens ein Signal je 63 Handelstage. Dividenden-Reinvestitionen zählen nicht.

Warum nur das: In der Forschung (research/edge.py) war das der einzige Bereich, der in beiden
Testzeiträumen (2020–23 und 2024–26) verlässlich den S&P 500 geschlagen hat. Alles andere (normale
Cluster, Ausschuss-Käufe, Top-Politiker, Firmen-Insider, technische Filter) brachte keinen Vorteil.
"""
import bisect
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
BIG = 100000       # ein Politiker reicht ab diesem Betrag (Untergrenze der Meldespanne)
LIVE_START = "2026-10-16"   # ab hier zählt die Live-Bilanz (alles davor ist Backtest)


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


def build(members, rows, dates, px, bench="SPY", ins=None):
    ins = ins or {}
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
        last_sig = last_all = -10 ** 9
        evd = {(r["filed"], r["pi"]) for r in arr if r["side"] == "P"}
        for f in ins.get(tk, []):
            k = bisect.bisect_right(dates, f)
            evd.add((f, k if k < n else None))
        for d, i in sorted(evd, key=lambda e: (e[0], n if e[1] is None else e[1])):
            cut = (date.fromisoformat(d) - timedelta(days=WIN)).isoformat()
            w = [u for u in arr if cut <= u["filed"] <= d]
            b = {u["m"] for u in w if u["side"] == "P"}
            s = {u["m"] for u in w if u["side"] == "S"}
            if not b:
                continue
            ni = 1 if any(cut <= f <= d for f in ins.get(tk, [])) else 0
            big = max(((u["lo"] or 0) for u in w if u["side"] == "P"), default=0)
            if not ((len(b) + ni >= MIN_N and len(s) < len(b) + ni) or (big >= BIG and len(s) < len(b))):
                continue
            pos = i if i is not None else n
            fh = _from_high(col, i if i is not None else last)
            dip_ok = fh is not None and fh <= DIP and pos - last_sig >= COOLDOWN
            all_ok = pos - last_all >= COOLDOWN       # Vergleichsgruppe: alle Cluster ohne Dip-Filter
            if not (dip_ok or all_ok):
                continue
            if all_ok:
                last_all = pos
            if dip_ok:
                last_sig = pos
            rec = {"t": tk, "d": d, "i": i, "n": len(b), "o": len(s), "m": sorted(b), "fh": fh,
                   "vol": round(sum(((u["lo"] or 0) + (u["hi"] or u["lo"] or 0)) / 2 for u in w if u["side"] == "P"))}
            if ni:
                rec["ins"] = 1
            if big >= BIG and len(b) + ni < MIN_N:
                rec["big"] = big
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
            if all_ok:
                allc.append(rec)
            if dip_ok:
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
                  "stop": STOP, "target": TARGET, "size": SIZE, "big": BIG, "live": LIVE_START},
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


# ====================================================================== Vor-Check (Ampel) für offene Signale
def _exit_date(dates, i):
    """Datum des Verkaufstags (Einstieg + HOLD Handelstage); in der Zukunft grob über Werktage geschätzt."""
    last = len(dates) - 1
    k = (i if i is not None else last + 1) + HOLD
    if k <= last:
        return dates[k]
    d, rest = date.fromisoformat(dates[last]), k - last
    while rest > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            rest -= 1
    return d.isoformat()


def vorcheck(sigs, dates):
    """Holt Börsenwert, Handelsvolumen und Termin der Quartalszahlen (Yahoo) und bewertet jedes offene Signal:
    grün = ok, gelb = genauer hinschauen, rot = eher auslassen. Die Schwellen sind Vorsichts-Regeln, nicht getestet."""
    try:
        import yfinance as yf
    except Exception:  # noqa
        yf = None
    for s in sigs:
        info, earn = {}, None
        if yf is not None:
            try:
                tk = yf.Ticker(s["t"])
                info = tk.get_info() or {}
                cal = tk.calendar or {}
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if ed:
                    earn = str(ed[0])[:10]
            except Exception as e:  # noqa
                print("Vor-Check", s["t"], type(e).__name__, str(e)[:80], flush=True)
        cap = info.get("marketCap")
        vol = info.get("averageDailyVolume10Day") or info.get("averageVolume")
        lp = s.get("lp")
        adv = vol * lp if vol and lp else None
        ex = _exit_date(dates, s.get("i"))
        red, yel = [], []
        if lp is not None and lp < 5:
            red.append(f"Kurs unter 5 $ ({lp:.2f} $)")
        if cap is None:
            yel.append("keine Firmendaten gefunden")
        elif cap < 3e8:
            red.append(f"sehr klein: Börsenwert {cap / 1e6:.0f} Mio. $")
        elif cap < 2e9:
            yel.append(f"klein: Börsenwert {cap / 1e9:.1f} Mrd. $")
        if adv is not None:
            if adv < 2e6:
                red.append(f"wenig Handel: ~{adv / 1e6:.1f} Mio. $ pro Tag")
            elif adv < 1e7:
                yel.append(f"mäßiger Handel: ~{adv / 1e6:.0f} Mio. $ pro Tag")
        today = dates[-1]
        if earn and today <= earn <= ex:
            yel.append(f"Quartalszahlen am {earn[8:10]}.{earn[5:7]}. (vor dem Verkauf, Kurssprung möglich)")
        fresh = s.get("i") is None or len(dates) - 1 - s["i"] <= 3      # nur für einen frischen Einstieg relevant
        run = (s["lp"] / s["ep"] - 1) * 100 if fresh and s.get("ep") and s.get("lp") else None
        if run is not None and run > 15:
            red.append(f"seit Einstieg schon +{run:.0f} %")
        elif run is not None and run > 10:
            yel.append(f"seit Einstieg schon +{run:.0f} %")
        s["chk"] = {"lvl": "r" if red else "y" if yel else "g", "why": red + yel, "cap": cap, "adv": round(adv) if adv else None,
                    "earn": earn, "exit": ex, "name": info.get("shortName")}


# ====================================================================== Discord
def discord(webhook, payloads):
    import requests
    import time as _t
    for p in payloads:
        try:
            r = requests.post(webhook, json=p, timeout=20)
            if r.status_code == 429:
                _t.sleep(2)
                requests.post(webhook, json=p, timeout=20)
            elif r.status_code >= 300:
                print("Discord:", r.status_code, r.text[:200], flush=True)
            _t.sleep(1)
        except Exception as e:  # noqa
            print("Discord-Fehler:", type(e).__name__, str(e)[:120], flush=True)


AMP = {"g": ("GRÜN", 0x2EA043), "y": ("GELB", 0xD29922), "r": ("ROT", 0xDA3633)}


def _embed_signal(s, nm, site_url):
    c = s.get("chk") or {}
    lvl = c.get("lvl", "y")
    lp = s.get("lp")
    stop = round(lp * (1 + STOP / 100), 2) if lp else None
    who = f'{s["n"]} Politiker' + (f" (Kauf ab {s['big'] // 1000}k $)" if s.get("big") else "")
    f = [{"name": "Käufer", "value": f'{who}: {", ".join(nm(i) for i in s["m"][:5])}', "inline": False},
         {"name": "Unter 52W-Hoch", "value": f'{s["fh"]:.0f} %', "inline": True},
         {"name": "Letzter Kurs", "value": f"{lp} $" if lp else "–", "inline": True},
         {"name": f"Stop ({STOP} %)", "value": f"{stop} $" if stop else "–", "inline": True},
         {"name": "Kauf", "value": "zum nächsten Schlusskurs" if s.get("i") is None else f'Schluss {s.get("ep")} $', "inline": True},
         {"name": "Verkauf ca.", "value": c.get("exit", "–"), "inline": True},
         {"name": f"Vor-Check: {AMP[lvl][0]}", "value": "\n".join("• " + w for w in c.get("why", [])) or "• alles ok", "inline": False}]
    e = {"title": f'Neues Dip-Signal: {s["t"]}' + (f' ({c["name"]})' if c.get("name") else ""),
         "color": AMP[lvl][1], "fields": f,
         "footer": {"text": f'Gemeldet {s["d"]} · Positionsgröße laut Journal · keine Anlageberatung'}}
    if site_url:
        e["url"] = f"{site_url}#t.{s['t']}"
    return e


def write_signals(out_dir, cache_dir, members, rows, dates, px, bench="SPY", site_url="", *_, **__):
    D = build(members, rows, dates, px, bench)
    extra = write_ticker_trades(out_dir, members, rows, set(D["tickers"]))
    for i, v in extra.items():
        D["members"].setdefault(i, v)
    last = len(dates) - 1
    open_sigs = [s for s in D["signals"] if s.get("i") is None or s["i"] + HOLD > last]
    vorcheck(open_sigs, dates)
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

    # Discord: neue Signale, Verkaufstag, Stop – nur wenn das Secret DISCORD_WEBHOOK gesetzt ist
    hook = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if hook:
        msgs = []
        if "discord_ok" not in seen:
            op = ", ".join(f'{s["t"]} ({s.get("chk", {}).get("lvl", "?").upper()})' for s in open_sigs) or "keine"
            msgs.append({"content": f"**Capitol Signals ist verbunden.** Neue Dip-Signale, Verkaufstage und Stops kommen ab jetzt hier rein.\nGerade offen: {op}\n{site_url}"})
            seen.add("discord_ok")
        for k in range(0, len(new), 10):
            msgs.append({"embeds": [_embed_signal(s, nm, site_url) for s in new[k:k + 10]]})
        for s in open_sigs:
            if s.get("i") is None or not s.get("ep") or not s.get("lp"):
                continue
            r = (s["lp"] / s["ep"] - 1) * 100
            if s["lp"] <= s["ep"] * (1 + STOP / 100) and f'S|{s["t"]}|{s["d"]}' not in seen:
                msgs.append({"content": f'**Stop erreicht: {s["t"]}** – Schlusskurs {s["lp"]} $ ({r:+.1f} % seit Einstieg {s["ep"]} $). Laut Regel verkaufen.'})
                seen.add(f'S|{s["t"]}|{s["d"]}')
        for s in D["signals"]:
            if s.get("i") is not None and s["i"] + HOLD - 1 == last and f'X|{s["t"]}|{s["d"]}' not in seen:
                r = (s["lp"] / s["ep"] - 1) * 100 if s.get("ep") and s.get("lp") else None
                msgs.append({"content": f'**Morgen verkaufen: {s["t"]}** – 30 Tage sind morgen voll (Verkauf zum Schlusskurs). '
                                        f'Stand: {"%+.1f %%" % r if r is not None else "–"} seit Einstieg.'})
                seen.add(f'X|{s["t"]}|{s["d"]}')
        discord(hook, msgs)
        print(f"Discord: {len(msgs)} Nachricht(en)", flush=True)
    json.dump(sorted(seen), open(seen_file, "w"))
    if new:
        title = "Dip-Cluster: " + ", ".join(s["t"] for s in new[:6]) + (" …" if len(new) > 6 else "")
        L = [title, "", f"Kursstand {dates[-1]}. Regeln: am nächsten Handelstag zum Schlusskurs kaufen, "
             f"Positionsgröße wie im Journal eingestellt, Notfall-Stop {STOP} %, nach 30 Tagen verkaufen.", "",
             "| Aktie | Käufer | unter 52W-Hoch | letzter Kurs | Stop | gemeldet |", "|---|---|---|---|---|---|"]
        for s in new:
            lp = s.get("lp")
            extra = f" (Kauf ab {s['big'] // 1000}k $)" if s.get("big") else ""
            L.append(f'| {s["t"]} | {s["n"]}: {", ".join(nm(i) for i in s["m"][:6])}{extra} | {s["fh"]:.0f} % | '
                     f'{lp if lp else "–"} | {round(lp * (1 + STOP / 100), 2) if lp else "–"} | {s["d"]} |')
        L += ["", "Vor dem Kauf kurz prüfen: Warum ist die Aktie gefallen? Bei Betrugsverdacht, Insolvenzgefahr oder Delisting nicht kaufen."]
        if site_url:
            L += ["", f"Details: {site_url}"]
        L += ["", "Keine Anlageberatung. Signale beruhen auf historischen Mustern mit wenigen Fällen."]
        open(alert_file, "w").write("\n".join(L) + "\n")
    return D
