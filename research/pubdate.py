"""
Capitol Signals – Backtest mit dem ECHTEN Veröffentlichungsdatum (wann stand die Meldung in der Datenquelle?)

Grundlage: Git-Historie von kadoa-org/congress-trading-monitor (ab 22.04.2026). Für jeden Trade: Tag, an dem er
zum ersten Mal in den Daten stand. Meldungen von vor dem 22.04.2026, die schon im ersten Stand enthalten waren,
gelten als pünktlich (unbekannt – günstige Annahme). Später nachgelieferte alte Meldungen gelten ab ihrem Liefertag.
Ein Signal ist bekannt, sobald genug Käufe davon in den Daten stehen (2. Käufer bzw. der 100k-Kauf).
Aufruf: python research/pubdate.py [first_seen.json]   (ohne Datei: Historie wird per git clone selbst gelesen)
"""
import bisect
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import edge  # noqa: E402
import expand  # noqa: E402
import robust  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import update  # noqa: E402

log = edge.log


def build_first_seen(out_path):
    """Liest die Git-Historie der Datenquelle und merkt sich für jeden Trade den ersten Tag, an dem er drinstand."""
    import subprocess
    repo = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "kadoa")
    if not os.path.exists(repo):
        subprocess.run(["git", "clone", "--no-checkout", "--single-branch",
                        "https://github.com/kadoa-org/congress-trading-monitor.git", repo], check=True)
    g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout
    commits = [l.split() for l in g("log", "--reverse", "--format=%H %ad", "--date=short", "--", "public/data/filer").splitlines()]
    first, prev = {}, None
    for h, d in commits:
        files = ([l.split("\t")[1] for l in g("ls-tree", "-r", h, "public/data/filer/").splitlines()] if prev is None else
                 [f for f in g("diff-tree", "--no-commit-id", "--name-only", "-r", prev, h, "--", "public/data/filer/").splitlines() if f.endswith(".json")])
        for f in files:
            try:
                data = json.loads(g("show", f"{h}:{f}"))
            except Exception:  # noqa
                continue
            fid = f.rsplit("/", 1)[1][:-5]
            for t in data.get("trades", []):
                k = "|".join(str(x) for x in (fid, (t.get("ticker") or "").strip().upper(), t.get("filing_date"),
                                              t.get("transaction_date"), t.get("transaction_type"), t.get("amount_range_low")))
                first.setdefault(k, d)
        prev = h
    json.dump({"start": commits[0][1], "first": first}, open(out_path, "w"))
    log("Historie gelesen:", len(commits), "Stände,", len(first), "Trades")


def main(fs_path=None):
    if not fs_path:
        fs_path = os.path.join(edge.OUT, "first_seen.json")
        build_first_seen(fs_path)
    J = json.load(open(fs_path))
    start, F = J["start"], J["first"]
    grace = (date.fromisoformat(start) + timedelta(days=3)).isoformat()
    idx = {}
    for k, d in F.items():
        fid, tk, filed, tx, tt, lo = k.split("|")
        side = "P" if tt == "Purchase" else "S" if tt.startswith("Sale") else None
        if not side:
            continue
        key = (fid, update.yf_symbol(tk), filed, tx, side, lo)
        if key not in idx or d < idx[key]:
            idx[key] = d
    edge.openinsider = lambda *a, **k: None
    members, dates, P, by, _, FH, RK = expand.prepare()
    n = len(dates)
    miss = [0, 0]

    def avail(r):
        k = (members[r["m"]]["id"], r["t"], r["filed"], r["tx"], r["side"], str(r["lo"] or 0))
        d = idx.get(k)
        if d is None:   # Schlüssel nicht gefunden (z. B. Betrag anders gespeichert) -> nur über Datum suchen
            miss[0] += 1
            return r["filed"]
        miss[1] += 1
        if r["filed"] < start:
            return d if d > grace else r["filed"]
        return max(d, r["filed"])

    base_ev = expand.gen({"single": 100000}, dates, P, by, {}, FH, RK)
    real = []
    for e in base_ev:
        arr = by[e["t"]]
        cut = (date.fromisoformat(e["d"]) - timedelta(days=30)).isoformat()
        w = [u for u in arr if cut <= u["filed"] <= e["d"] and u["side"] == "P"]
        first_by = {}
        for u in w:
            a = avail(u)
            first_by[u["m"]] = min(first_by.get(u["m"], "9999"), a)
        av = sorted(first_by.values())
        cands = []
        if len(av) >= 2:
            cands.append(av[1])
        big = [avail(u) for u in w if (u["lo"] or 0) >= 100000]
        if big:
            cands.append(min(big))
        known = max(min(cands) if cands else e["d"], e["d"])
        k2 = bisect.bisect_right(dates, known)
        lag = (k2 - e["i"]) if k2 < n else None
        real.append({**e, "known": known, "lag": lag, "i_real": k2 if k2 < n else None})
    log("Schlüssel gefunden:", miss[1], "nicht gefunden:", miss[0])
    lags = [x["lag"] for x in real if x["lag"] is not None]
    json.dump([[x["t"], x["d"], x["i_real"]] for x in real if x["lag"] is not None and x["lag"] <= 5],
              open(os.path.join(edge.OUT, "tradable.json"), "w"))   # für research/sector.py
    late = [x for x in real if x["lag"] is None or x["lag"] > 5]
    R = {}

    def row(name, evs):
        res = robust.outcomes(P, evs)
        R[name] = {"t": robust.tstats(res), "is": robust.tstats([x for x in res if x["d"] < "2024-01-01"]),
                   "oos": robust.tstats([x for x in res if x["d"] >= "2024-01-01"]),
                   "cash": robust.perf(robust.sim(P, dates, res, "cash"))}
        log(name, R[name])

    row("Backtest bisher (Meldedatum)", base_ev)
    row("Echt: Einstieg nach Erscheinen in den Daten", [{**x, "i": x["i_real"]} for x in real if x["i_real"] is not None])
    row("Echt, aber zu spät (> 5 Handelstage) auslassen", [{**x, "i": x["i_real"]} for x in real if x["lag"] is not None and x["lag"] <= 5])
    row("nur pünktliche Signale (Verzögerung <= 1 Tag)", [x for x in real if x["lag"] is not None and x["lag"] <= 1])
    row("nur verspätete Signale (> 5 Tage), zum Meldedatum", [x for x in real if x["lag"] is None or x["lag"] > 5])
    yr = {}
    for x in real:
        y = x["d"][:4]
        yr.setdefault(y, [0, 0])
        yr[y][0] += 1
        if x["lag"] is None or x["lag"] > 5:
            yr[y][1] += 1
    out = {"lags": {"n": len(lags), "0-1": sum(l <= 1 for l in lags), "2-5": sum(1 < l <= 5 for l in lags),
                    "6-20": sum(5 < l <= 20 for l in lags), ">20": sum(l > 20 for l in lags)},
           "late_per_year": yr, "rows": R}
    json.dump(out, open(os.path.join(edge.OUT, "pubdate.json"), "w"), indent=1, ensure_ascii=False, default=str)
    f = lambda v, s="": "–" if v is None else f"{v}{s}"
    L = [f"# Backtest mit echtem Veröffentlichungsdatum (Datenquelle ab {start}, Kurse bis {dates[-1]})", "",
         f"Verzögerung Meldedatum → in den Daten (Signale, Handelstage): 0–1: {out['lags']['0-1']}, 2–5: {out['lags']['2-5']}, "
         f"6–20: {out['lags']['6-20']}, über 20: {out['lags']['>20']}", "",
         "Signale je Jahr (gesamt / davon mehr als 5 Tage zu spät): " + ", ".join(f"{y}: {a}/{b}" for y, (a, b) in sorted(yr.items())), "",
         "| Variante | Trades | Treffer | schlägt S&P | Ø Trade | Ø vs S&P | RR | 2020–23 | 2024–26 | Nur Trades p.a. / DD |", "|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in R.items():
        a, i, o = v["t"], v["is"], v["oos"]
        L.append(f"| {k} | {a.get('n')} | {f(a.get('win'), ' %')} | {f(a.get('beat'), ' %')} | {f(a.get('avg'), ' %')} | {f(a.get('ex'), ' %')} | {f(a.get('rr'))} | "
                 f"{i.get('n')} · {f(i.get('win'))} · {f(i.get('beat'))} | {o.get('n')} · {f(o.get('win'))} · {f(o.get('beat'))} | {v['cash']['cagr']} % / {v['cash']['mdd']} % |")
    md = "\n".join(L) + "\n"
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md)
    print(md)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
