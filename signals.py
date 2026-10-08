"""
Capitol Signals – Cluster-Signale

LONG:  mindestens 3 verschiedene Politiker kaufen dieselbe Aktie innerhalb von 30 Tagen
       (nach Meldedatum) und es gibt mehr Käufer als Verkäufer. Haltedauer 21 Handelstage.
SHORT: mindestens 4 verschiedene Politiker verkaufen innerhalb von 60 Tagen und es gibt
       mehr Verkäufer als Käufer. Haltedauer 63 Handelstage (relativ zum S&P 500 gedacht).
Einstieg immer zum Schlusskurs des ersten Handelstags NACH der auslösenden Meldung.
Pro Aktie und Richtung höchstens ein Signal je 63 Handelstage. Gab es in den 63 Handelstagen davor
ein Gegensignal, wird das neue Signal als widersprüchlich verworfen.
Die Regeln stammen aus einem Test auf den Daten 2020–2026 (siehe Webseite → Signale).
"""
import json
import os
from datetime import date, timedelta

RULES = {
    "L": {"side": "P", "min_n": 3, "win": 30, "hold": 21, "label": "LONG"},
    "S": {"side": "S", "min_n": 4, "win": 60, "hold": 63, "label": "SHORT"},
}
COOLDOWN = 63


def _ret(col, i, j):
    if i is None or j is None:
        return None
    a, b = col[i], col[j]
    if not (a > 0) or not (b > 0):
        return None
    return float(b / a - 1)


def build_signals(members, rows, dates, px, bench="SPY"):
    n = len(dates)
    last = n - 1
    spy = px[bench].values
    qqq = px["QQQ"].values if "QQQ" in px.columns else None
    by = {}
    for r in rows:
        if r["kind"] != "st" or r["t"] not in px.columns:
            continue
        by.setdefault(r["t"], []).append(r)
    out = []
    for tk, arr in by.items():
        arr.sort(key=lambda r: r["filed"])
        col = px[tk].values
        found = {"L": [], "S": []}
        for code, p in RULES.items():
            last_sig = -10 ** 9
            for r in arr:
                if r["side"] != p["side"]:
                    continue
                cut = (date.fromisoformat(r["filed"]) - timedelta(days=p["win"])).isoformat()
                w = [u for u in arr if cut <= u["filed"] <= r["filed"]]
                same = {u["m"] for u in w if u["side"] == p["side"]}
                other = {u["m"] for u in w if u["side"] != p["side"]}
                if len(same) < p["min_n"] or len(other) >= len(same):
                    continue
                i = r["pi"]
                pos = i if i is not None else n
                if pos - last_sig < COOLDOWN:
                    continue
                last_sig = pos
                found[code].append((pos, r, same, other, w))
        for code, p in RULES.items():
            opp = found["S" if code == "L" else "L"]
            for pos, r, same, other, w in found[code]:
                # Gegensignal in den letzten 63 Handelstagen → widersprüchlich, kein Signal (nur Vergangenheit, kein Blick nach vorn)
                if any(op <= pos and pos - op < COOLDOWN for op, *_ in opp):
                    continue
                i = r["pi"]
                x = min(i + p["hold"], last) if i is not None else None
                active = i is None or i + p["hold"] > last
                sgn = 1 if code == "L" else -1
                rr = _ret(col, i, x)
                rs = _ret(spy, i, x)
                rq = _ret(qqq, i, x) if qqq is not None else None
                later_opp = sorted({u["m"] for u in arr if u["side"] != p["side"] and u["filed"] > r["filed"]}) if active else []
                vol = sum(((u["lo"] or 0) + (u["hi"] or u["lo"] or 0)) / 2 for u in w if u["side"] == p["side"])
                out.append({
                    "t": tk, "s": code, "d": r["filed"], "i": i, "x": x, "n": len(same), "o": len(other),
                    "m": sorted(same), "vol": round(vol), "asset": r.get("asset", ""), "active": bool(active),
                    "r": None if rr is None else round(sgn * rr * 100, 2),
                    "ex": None if rr is None or rs is None else round(sgn * (rr - rs) * 100, 2),
                    "exq": None if rr is None or rq is None else round(sgn * (rr - rq) * 100, 2),
                    "warn": later_opp,
                })
    out.sort(key=lambda s: (s["d"], s["n"]), reverse=True)
    return out


def write_signals(out_dir, cache_dir, members, rows, dates, px, bench="SPY", site_url=""):
    sigs = build_signals(members, rows, dates, px, bench)
    json.dump({"rules": RULES, "cooldown": COOLDOWN, "signals": sigs},
              open(os.path.join(out_dir, "signals.json"), "w"), separators=(",", ":"), ensure_ascii=False)

    # Benachrichtigung: neue Signale der letzten 7 Tage, die noch nicht gemeldet wurden
    root = os.path.dirname(os.path.abspath(cache_dir))
    alert_file = os.path.join(root, "alerts.md")
    if os.path.exists(alert_file):
        os.remove(alert_file)
    seen_file = os.path.join(cache_dir, "alerts_seen.json")
    seen = set(json.load(open(seen_file))) if os.path.exists(seen_file) else set()
    key = lambda s: f'{s["t"]}|{s["s"]}|{s["d"]}'
    recent = (date.fromisoformat(dates[-1]) - timedelta(days=7)).isoformat()
    new = [s for s in sigs if key(s) not in seen and s["d"] >= recent]
    seen |= {key(s) for s in sigs}
    json.dump(sorted(seen), open(seen_file, "w"))
    if new:
        names = lambda s: ", ".join(members[i]["name"] for i in s["m"][:6]) + (" …" if len(s["m"]) > 6 else "")
        title = "Capitol Signals: " + ", ".join(f'{s["t"]} {RULES[s["s"]]["label"]}' for s in new[:6]) + (" …" if len(new) > 6 else "")
        lines = [title, "", f"{len(new)} neue{'s' if len(new) == 1 else ''} Signal{'e' if len(new) != 1 else ''} (Stand Kurse {dates[-1]}):", "",
                 "| Ticker | Richtung | Politiker | gemeldet | Haltedauer |", "|---|---|---|---|---|"]
        for s in new:
            lines.append(f'| {s["t"]} | {RULES[s["s"]]["label"]} | {s["n"]}: {names(s)} | {s["d"]} | {RULES[s["s"]]["hold"]} Handelstage |')
        if site_url:
            lines += ["", f"Details: {site_url}#sig"]
        lines += ["", "Keine Anlageberatung. Signale beruhen auf historischen Mustern."]
        open(alert_file, "w").write("\n".join(lines) + "\n")
    return sigs
