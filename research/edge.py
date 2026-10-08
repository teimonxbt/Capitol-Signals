"""
Capitol Signals – Edge-Forschung (läuft in GitHub Actions, wo Yahoo & SEC erreichbar sind).

Testet, ob sich aus Politiker-Käufen (+ Firmen-Insider-Käufen) ein Vorteil GEGEN DEN MARKT bauen lässt.
Gemessen wird immer gehedgt: Rendite der Aktie minus Rendite SPY im selben Zeitraum ("vs S&P").
Trefferquote = Anteil der Trades, die den S&P schlagen. Einstieg: Schlusskurs am ersten Handelstag
nach der Veröffentlichung. Alles getrennt nach 2020–2023 (IS) und 2024–2026 (OOS).

Ausgabe: research_out/research.json + Markdown-Zusammenfassung (GITHUB_STEP_SUMMARY).
"""
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import update  # noqa: E402

CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(ROOT, "research_out")
os.makedirs(OUT, exist_ok=True)
H = {"30": 21, "60": 42, "90": 63}
SPLIT = "2024-01-01"
UA = {"User-Agent": "CapitolSignals research teimonxbt@users.noreply.github.com", "Accept-Encoding": "gzip, deflate"}
NOISE = re.compile(r"reinvest|dividend", re.I)
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(time.strftime("%H:%M:%S"), s, flush=True)


# =============================================================================== Daten
def load_core():
    members, trades = update.load_trades()
    prices = pd.read_pickle(os.path.join(CACHE, "prices.pkl"))
    dates, px, rows = update.compute(members, trades, prices)
    return members, rows, dates, px


def sec_insider(px_cols, start_year=2020):
    """SEC 'Insider Transactions Data Sets' (Form 3/4/5, quartalsweise). Nur offene Marktkäufe (Code P)."""
    cache_file = os.path.join(CACHE, "insider_buys.pkl")
    have = pd.read_pickle(cache_file) if os.path.exists(cache_file) else pd.DataFrame()
    done = set(have["q"].unique()) if not have.empty else set()
    today = date.today()
    qs = [(y, q) for y in range(start_year, today.year + 1) for q in range(1, 5)
          if (y, q) <= (today.year, (today.month - 1) // 3 + 1)]
    parts = [have] if not have.empty else []
    for y, q in qs:
        tag = f"{y}q{q}"
        recent = (y, q) >= (today.year, (today.month - 1) // 3)   # letzte 2 Quartale immer neu laden
        if tag in done and not recent:
            continue
        url = f"https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{tag}_form345.zip"
        try:
            r = requests.get(url, headers=UA, timeout=120)
            if r.status_code != 200:
                log("SEC", tag, "HTTP", r.status_code)
                continue
            z = zipfile.ZipFile(io.BytesIO(r.content))
            names = {n.upper().split("/")[-1]: n for n in z.namelist()}
            rd = lambda n, cols: pd.read_csv(z.open(names[n]), sep="\t", dtype=str, usecols=lambda c: c.upper() in cols,
                                             quoting=3, on_bad_lines="skip", encoding_errors="replace")
            sub = rd("SUBMISSION.TSV", {"ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERTRADINGSYMBOL", "AFF10B5ONE"})
            own = rd("REPORTINGOWNER.TSV", {"ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP", "RPTOWNER_TITLE"})
            tr = rd("NONDERIV_TRANS.TSV", {"ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES",
                                           "TRANS_PRICEPERSHARE", "TRANS_ACQUIRED_DISP_CD", "SHRS_OWND_FOLWNG_TRANS"})
            for d in (sub, own, tr):
                d.columns = [c.upper() for c in d.columns]
            tr = tr[(tr["TRANS_CODE"] == "P") & (tr["TRANS_ACQUIRED_DISP_CD"].fillna("A") == "A")].copy()
            tr["sh"] = pd.to_numeric(tr["TRANS_SHARES"], errors="coerce")
            tr["pr"] = pd.to_numeric(tr["TRANS_PRICEPERSHARE"], errors="coerce")
            tr["after"] = pd.to_numeric(tr.get("SHRS_OWND_FOLWNG_TRANS"), errors="coerce")
            tr = tr[(tr["sh"] > 0) & (tr["pr"] > 0)]
            tr["v"] = tr["sh"] * tr["pr"]
            g = tr.groupby("ACCESSION_NUMBER").agg(val=("v", "sum"), sh=("sh", "sum"), after=("after", "max"), tx=("TRANS_DATE", "min"))
            sub = sub[sub["DOCUMENT_TYPE"].astype(str).str.startswith("4")]
            o1 = own.drop_duplicates("ACCESSION_NUMBER")
            m = g.join(sub.set_index("ACCESSION_NUMBER"), how="inner").join(o1.set_index("ACCESSION_NUMBER"), how="left")
            m["t"] = m["ISSUERTRADINGSYMBOL"].astype(str).str.upper().str.strip().str.replace(".", "-", regex=False)
            m["filed"] = pd.to_datetime(m["FILING_DATE"], format="mixed", dayfirst=False, errors="coerce").dt.strftime("%Y-%m-%d")
            m["tx"] = pd.to_datetime(m["tx"], format="mixed", errors="coerce").dt.strftime("%Y-%m-%d")
            rel = m["RPTOWNER_RELATIONSHIP"].fillna("").astype(str)
            title = m["RPTOWNER_TITLE"].fillna("").astype(str)
            out = pd.DataFrame({
                "q": tag, "t": m["t"], "filed": m["filed"], "tx": m["tx"], "cik": m["RPTOWNERCIK"],
                "val": m["val"], "sh": m["sh"], "after": m["after"],
                "officer": rel.str.contains("Officer", case=False),
                "director": rel.str.contains("Director", case=False),
                "ten": rel.str.contains("Ten|10", case=False),
                "ceo": title.str.contains(r"\bCEO\b|Chief Executive|President", case=False, regex=True),
                "cfo": title.str.contains(r"\bCFO\b|Chief Financial", case=False, regex=True),
                "plan": m.get("AFF10B5ONE", pd.Series(index=m.index, dtype=str)).fillna("").astype(str).str.upper().isin(["1", "TRUE", "Y"]),
            }).dropna(subset=["filed", "t"])
            parts = [p for p in parts if p.empty or tag not in set(p["q"])] + [out]
            log("SEC", tag, f"{len(out)} Kauf-Meldungen")
        except Exception as e:  # noqa
            log("SEC", tag, "Fehler", type(e).__name__, e)
        time.sleep(0.6)
    if not parts:
        return pd.DataFrame()
    ib = pd.concat(parts, ignore_index=True)
    ib.to_pickle(cache_file)
    log("SEC gesamt:", len(ib), "Kauf-Meldungen,", ib["t"].isin(px_cols).mean().round(3), "Anteil mit Kursdaten")
    return ib


# =============================================================================== Features & Outcomes
class Px:
    def __init__(self, px, dates):
        self.px = px
        self.dates = dates
        self.n = len(dates)
        self.spy = px["SPY"].values
        self.qqq = px["QQQ"].values if "QQQ" in px.columns else None
        self.cols = {c: px[c].values for c in px.columns}
        s = pd.Series(self.spy)
        self.spy_ma200 = s.rolling(200).mean().values
        self.spy_ma50 = s.rolling(50).mean().values
        self._ma = {}

    def idx_after(self, d):
        import bisect
        i = bisect.bisect_right(self.dates, d)
        return i if i < self.n else None

    def ma(self, t, k):
        key = (t, k)
        if key not in self._ma:
            self._ma[key] = pd.Series(self.cols[t]).rolling(k, min_periods=int(k * 0.8)).mean().values
        return self._ma[key]

    def feats(self, t, i):
        c = self.cols[t]
        p = c[i]
        f = {}
        if not (p > 0):
            return None
        def ret(a, j0, j1):
            if j0 < 0 or not (a[j0] > 0) or not (a[j1] > 0):
                return None
            return a[j1] / a[j0] - 1
        for k, lab in ((21, "m1"), (63, "m3"), (126, "m6")):
            r, s = ret(c, i - k, i), ret(self.spy, i - k, i)
            f["rs_" + lab] = None if r is None or s is None else r - s
            f["ret_" + lab] = r
        r12, r1 = ret(c, i - 252, i - 21), ret(c, i - 21, i)
        f["mom12_1"] = r12
        m50, m200 = self.ma(t, 50)[i], self.ma(t, 200)[i]
        f["above50"] = None if not (m50 > 0) else bool(p > m50)
        f["above200"] = None if not (m200 > 0) else bool(p > m200)
        lo = max(0, i - 252)
        w = c[lo:i + 1]
        w = w[w > 0]
        f["from_high"] = float(p / w.max() - 1) if len(w) > 50 else None
        d = c[max(0, i - 63):i + 1]
        d = d[d > 0]
        f["vol3m"] = float(np.std(np.diff(np.log(d))) * np.sqrt(252)) if len(d) > 40 else None
        f["spy_up"] = bool(self.spy[i] > self.spy_ma200[i]) if self.spy_ma200[i] > 0 else None
        f["price"] = float(p)
        return f

    def outcome(self, t, i, h, stop=None, tp=None):
        """Gehedgte Rendite (Aktie - SPY) über h Handelstage, optional Stop/Take-Profit auf die Aktie."""
        c = self.cols[t]
        if i is None or i + h > self.n - 1 or not (c[i] > 0) or not (self.spy[i] > 0):
            return None
        x = i + h
        if stop or tp:
            for j in range(i + 1, i + h + 1):
                if not (c[j] > 0):
                    continue
                r = c[j] / c[i] - 1
                if (stop and r <= -stop) or (tp and r >= tp):
                    x = j
                    break
        if not (c[x] > 0):
            return None
        r = c[x] / c[i] - 1
        s = self.spy[x] / self.spy[i] - 1
        return r, s, x


def summarize(evs, key="ex"):
    """evs: Liste dicts mit d (Datum), ex (gehedgt), r (absolut)."""
    def st(a):
        if len(a) < 10:
            return {"n": len(a)}
        x = np.array([e[key] for e in a])
        r = np.array([e["r"] for e in a])
        return {"n": len(a), "beat": round(float((x > 0).mean() * 100), 1), "win": round(float((r > 0).mean() * 100), 1),
                "ex": round(float(x.mean() * 100), 2), "med": round(float(np.median(x) * 100), 2),
                "t": round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 2) if x.std() > 0 else None}
    return {"all": st(evs), "is": st([e for e in evs if e["d"] < SPLIT]), "oos": st([e for e in evs if e["d"] >= SPLIT])}


def years(evs, key="ex"):
    o = {}
    for e in evs:
        o.setdefault(e["d"][:4], []).append(e[key])
    return {y: {"n": len(v), "beat": round(100 * float(np.mean(np.array(v) > 0)), 1), "ex": round(100 * float(np.mean(v)), 2)} for y, v in sorted(o.items())}


def attach(P, evs, h, stop=None, tp=None):
    out = []
    for e in evs:
        o = P.outcome(e["t"], e["i"], h, stop, tp)
        if o is None:
            continue
        r, s, x = o
        out.append({**e, "r": r, "s": s, "ex": r - s, "x": x})
    return out


# =============================================================================== Ereignisse
def congress_events(members, rows, P):
    buys = [r for r in rows if r["side"] == "P" and r["kind"] == "st" and r["t"] in P.cols and r["pi"] is not None
            and not NOISE.search(r.get("comment") or "")]
    seen, ev = set(), []
    for r in sorted(buys, key=lambda r: (r["filed"], r["tx"])):
        k = (r["m"], r["t"], r["filed"])
        if k in seen:
            continue
        seen.add(k)
        ev.append({"t": r["t"], "d": r["filed"], "i": r["pi"], "m": r["m"], "lo": r["lo"] or 0, "tx": r["tx"],
                   "lag": (date.fromisoformat(r["filed"]) - date.fromisoformat(r["tx"])).days,
                   "owner": r.get("owner"), "ch": members[r["m"]].get("chamber"), "party": members[r["m"]].get("party")})
    # ungewöhnlich: erster Kauf dieses Tickers durch diesen Politiker, Größe relativ zur eigenen Historie
    hist, sizes = {}, {}
    for e in ev:
        key = (e["m"], e["t"])
        e["first"] = key not in hist
        hist[key] = True
        prev = sizes.get(e["m"], [])
        e["size_rel"] = (e["lo"] / np.median(prev)) if len(prev) >= 5 and np.median(prev) > 0 else None
        sizes.setdefault(e["m"], []).append(max(e["lo"], 1))
    return ev


def option_events(rows, P):
    ev, seen = [], set()
    for r in rows:
        if r["kind"] != "opt" or r["t"] not in P.cols or r["pi"] is None:
            continue
        txt = ((r.get("asset") or "") + " " + (r.get("comment") or "")).lower()
        call = "call" in txt
        put = "put" in txt and not call
        if r["side"] == "P" and call:
            kind = "call_kauf"
        elif r["side"] == "P" and put:
            kind = "put_kauf"
        elif r["side"] == "S" and call:
            kind = "call_verkauf"
        else:
            continue
        k = (r["m"], r["t"], r["filed"], kind)
        if k in seen:
            continue
        seen.add(k)
        ev.append({"t": r["t"], "d": r["filed"], "i": r["pi"], "m": r["m"], "kind": kind, "lo": r["lo"] or 0})
    return ev


def clusters(ev, mn, win=30, cooldown=63):
    by = {}
    for e in ev:
        by.setdefault(e["t"], []).append(e)
    out = []
    for t, a in by.items():
        a.sort(key=lambda e: e["d"])
        last = -10 ** 9
        for j, e in enumerate(a):
            cut = (date.fromisoformat(e["d"]) - timedelta(days=win)).isoformat()
            w = [u for u in a[:j + 1] if u["d"] >= cut]
            ms = {u["m"] for u in w}
            if len(ms) < mn or e["i"] - last < cooldown:
                continue
            last = e["i"]
            out.append({"t": t, "d": e["d"], "i": e["i"], "n": len(ms), "vol": sum(u["lo"] for u in w), "mem": sorted(ms)})
    return out


def insider_events(ib, P):
    ib = ib[ib["t"].isin(P.cols.keys())].copy()
    ib = ib[ib["filed"] >= "2020-01-01"]
    ev = []
    for (t, f), g in ib.groupby(["t", "filed"]):
        i = P.idx_after(f)
        if i is None:
            continue
        val = float(g["val"].sum())
        own_inc = None
        if g["after"].notna().any() and g["sh"].notna().any():
            a, s = float(g["after"].max()), float(g["sh"].sum())
            own_inc = s / max(a - s, 1) if a > s else None
        ev.append({"t": t, "d": f, "i": i, "val": val, "n": int(g["cik"].nunique()), "ceo": bool(g["ceo"].any()),
                   "cfo": bool(g["cfo"].any()), "officer": bool(g["officer"].any()), "director_only": bool((g["director"] & ~g["officer"]).all()),
                   "ten": bool(g["ten"].all()), "plan": bool(g["plan"].any()), "own_inc": own_inc,
                   "lag": (date.fromisoformat(f) - date.fromisoformat(str(g["tx"].min()))).days if isinstance(g["tx"].min(), str) else None})
    ev.sort(key=lambda e: e["d"])
    # Insider-Cluster: mehrere verschiedene Insider innerhalb 30 Tagen
    by = {}
    for e in ev:
        by.setdefault(e["t"], []).append(e)
    for t, a in by.items():
        for j, e in enumerate(a):
            cut = (date.fromisoformat(e["d"]) - timedelta(days=30)).isoformat()
            w = [u for u in a[:j + 1] if u["d"] >= cut]
            e["n30"] = sum(u["n"] for u in w)
            e["val30"] = sum(u["val"] for u in w)
    return ev


# =============================================================================== Auswertung
def run():
    t0 = time.time()
    members, rows, dates, px = load_core()
    P = Px(px, dates)
    log("Kurse:", px.shape, "bis", dates[-1])
    R = {"asof": dates[-1], "split": SPLIT, "tables": {}, "years": {}, "notes": []}
    T = R["tables"]

    # SPY-Grundrate
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    for k, h in H.items():
        a = P.spy[i0:]
        R.setdefault("spy_up_rate", {})[k] = round(float(np.mean(a[h:] > a[:-h]) * 100), 1)

    CE = congress_events(members, rows, P)
    for e in CE:
        f = P.feats(e["t"], e["i"])
        e.update(f or {})
    CE = [e for e in CE if e.get("price")]
    log("Kongress-Käufe:", len(CE))

    def filt(name, evs, fn):
        return name, [e for e in evs if fn(e)]

    def feature_grid(prefix, evs, hs=("30", "60", "90")):
        F = [
            ("alle", lambda e: True),
            ("RS3M>0 (stärker als S&P, 3 Mon.)", lambda e: (e.get("rs_m3") or -9) > 0),
            ("RS3M<0", lambda e: e.get("rs_m3") is not None and e["rs_m3"] < 0),
            ("RS6M>0", lambda e: (e.get("rs_m6") or -9) > 0),
            ("über MA50", lambda e: e.get("above50") is True),
            ("unter MA50", lambda e: e.get("above50") is False),
            ("über MA200", lambda e: e.get("above200") is True),
            ("über MA50 & MA200", lambda e: e.get("above50") is True and e.get("above200") is True),
            ("Momentum 12-1 > 0", lambda e: (e.get("mom12_1") or -9) > 0),
            ("nahe 52W-Hoch (<10%)", lambda e: (e.get("from_high") or -9) > -0.10),
            ("weit unter 52W-Hoch (>30%)", lambda e: e.get("from_high") is not None and e["from_high"] < -0.30),
            ("Pullback: über MA200, unter MA50", lambda e: e.get("above200") is True and e.get("above50") is False),
            ("geringe Vola (<30%)", lambda e: e.get("vol3m") is not None and e["vol3m"] < 0.30),
            ("hohe Vola (>50%)", lambda e: (e.get("vol3m") or 0) > 0.50),
            ("SPY über MA200", lambda e: e.get("spy_up") is True),
            ("SPY unter MA200", lambda e: e.get("spy_up") is False),
            ("Kurs >= 10$", lambda e: e.get("price", 0) >= 10),
            ("RS3M>0 & über MA50 & SPY↑", lambda e: (e.get("rs_m3") or -9) > 0 and e.get("above50") is True and e.get("spy_up") is True),
        ]
        for h in hs:
            hh = H[h]
            base = attach(P, evs, hh)
            for name, fn in F:
                T[f"{prefix}|{h}|{name}"] = summarize([e for e in base if fn(e)])

    # ---- Punkt 1+2: einzelne Käufe & Cluster mit technischen Filtern
    feature_grid("Kongress-Kauf", CE)
    for mn in (2, 3):
        CL = clusters(CE, mn)
        for e in CL:
            e.update(P.feats(e["t"], e["i"]) or {})
        feature_grid(f"Cluster {mn}+", CL)
        log(f"Cluster {mn}+:", len(CL))

    # ---- Punkt 4: ungewöhnliche Käufe
    for h in ("30", "60", "90"):
        base = attach(P, [e for e in CE if e["d"] >= "2021-01-01"], H[h])
        U = [
            ("alle (ab 2021)", lambda e: True),
            ("Erstkauf dieses Tickers", lambda e: e["first"]),
            ("Wiederholungskauf", lambda e: not e["first"]),
            ("Größe >= 3x eigener Median", lambda e: (e.get("size_rel") or 0) >= 3),
            ("Größe >= 10x eigener Median", lambda e: (e.get("size_rel") or 0) >= 10),
            ("Betrag >= 50K", lambda e: e["lo"] >= 50000),
            ("Betrag >= 250K", lambda e: e["lo"] >= 250000),
            ("schnell gemeldet (<=10 T)", lambda e: e["lag"] <= 10),
            ("Erstkauf & >=15K", lambda e: e["first"] and e["lo"] >= 15000),
            ("Erstkauf & >=3x Median", lambda e: e["first"] and (e.get("size_rel") or 0) >= 3),
            ("Selbst (nicht Ehepartner)", lambda e: e.get("owner") == "Selbst"),
            ("Senat", lambda e: e.get("ch") == "senate"),
        ]
        for name, fn in U:
            T[f"Ungewöhnlich|{h}|{name}"] = summarize([e for e in base if fn(e)])
    OE = option_events(rows, P)
    log("Options-Ereignisse:", len(OE))
    for h in ("30", "60", "90"):
        base = attach(P, OE, H[h])
        for k in ("call_kauf", "put_kauf", "call_verkauf"):
            sel = [e for e in base if e["kind"] == k]
            if k == "put_kauf":   # Put = bärisch → Vorzeichen umdrehen
                sel = [{**e, "ex": -e["ex"], "r": -e["r"]} for e in sel]
            T[f"Optionen|{h}|{k}"] = summarize(sel)

    # ---- Punkt 3: Firmen-Insider
    IE = []
    try:
        ib = sec_insider(set(P.cols))
        if not ib.empty:
            IE = insider_events(ib, P)
            for e in IE:
                e.update(P.feats(e["t"], e["i"]) or {})
            IE = [e for e in IE if e.get("price")]
            log("Insider-Ereignisse:", len(IE))
    except Exception as ex:  # noqa
        log("Insider-Fehler:", type(ex).__name__, ex)
    if IE:
        # Politiker-Kauf derselben Aktie in den 60 Tagen vor/nach
        cong_by = {}
        for e in CE:
            cong_by.setdefault(e["t"], []).append(e["d"])
        for e in IE:
            ds = cong_by.get(e["t"], [])
            lo = (date.fromisoformat(e["d"]) - timedelta(days=60)).isoformat()
            e["congress60"] = any(lo <= d <= e["d"] for d in ds)
        ins_by = {}
        for e in IE:
            ins_by.setdefault(e["t"], []).append((e["d"], e["val"]))
        for e in CE:
            lo = (date.fromisoformat(e["d"]) - timedelta(days=60)).isoformat()
            e["insider60"] = any(lo <= d <= e["d"] and v >= 25000 for d, v in ins_by.get(e["t"], []))
        IF = [
            ("alle Insider-Käufe", lambda e: True),
            ("Wert >= 100K", lambda e: e["val"] >= 1e5),
            ("Wert >= 1 Mio", lambda e: e["val"] >= 1e6),
            ("CEO/CFO kauft", lambda e: e["ceo"] or e["cfo"]),
            ("CEO/CFO & >= 100K", lambda e: (e["ceo"] or e["cfo"]) and e["val"] >= 1e5),
            ("Officer (nicht nur Direktor)", lambda e: e["officer"]),
            ("nur Direktoren", lambda e: e["director_only"]),
            ("nur 10%-Eigner", lambda e: e["ten"]),
            ("Insider-Cluster >= 3 in 30 T", lambda e: e.get("n30", 0) >= 3),
            ("Bestand +20% oder mehr", lambda e: (e.get("own_inc") or 0) >= 0.2),
            ("kein 10b5-1-Plan", lambda e: not e["plan"]),
            ("unter MA50 (Dip-Kauf)", lambda e: e.get("above50") is False),
            ("über MA50", lambda e: e.get("above50") is True),
            ("weit unter 52W-Hoch (>30%)", lambda e: e.get("from_high") is not None and e["from_high"] < -0.30),
            ("Kurs >= 10$", lambda e: e.get("price", 0) >= 10),
            ("+ Politiker-Kauf in 60 T davor", lambda e: e.get("congress60")),
            ("Officer & >=100K & Kurs>=10$", lambda e: e["officer"] and e["val"] >= 1e5 and e.get("price", 0) >= 10),
            ("Cluster>=3 & >=100K & Kurs>=10$", lambda e: e.get("n30", 0) >= 3 and e["val"] >= 1e5 and e.get("price", 0) >= 10),
            ("CEO/CFO & >=100K & Kurs>=10$ & unter MA50", lambda e: (e["ceo"] or e["cfo"]) and e["val"] >= 1e5 and e.get("price", 0) >= 10 and e.get("above50") is False),
        ]
        for h in ("30", "60", "90"):
            base = attach(P, IE, H[h])
            for name, fn in IF:
                T[f"Insider|{h}|{name}"] = summarize([e for e in base if fn(e)])
            cb = attach(P, CE, H[h])
            T[f"Kombi|{h}|Politiker-Kauf + Insider-Kauf (>=25K) 60 T davor"] = summarize([e for e in cb if e.get("insider60")])
            T[f"Kombi|{h}|Politiker-Kauf ohne Insider"] = summarize([e for e in cb if not e.get("insider60")])

    # ---- Punkt 5: Exits auf die vielversprechendsten Mengen
    cands = {"Kongress-Kauf (alle)": CE, "Cluster 3+": [dict(e, **(P.feats(e["t"], e["i"]) or {})) for e in clusters(CE, 3)]}
    if IE:
        cands["Insider Officer >=100K Kurs>=10$"] = [e for e in IE if e["officer"] and e["val"] >= 1e5 and e.get("price", 0) >= 10]
        cands["Insider-Cluster>=3 >=100K"] = [e for e in IE if e.get("n30", 0) >= 3 and e["val"] >= 1e5 and e.get("price", 0) >= 10]
    for cname, evs in cands.items():
        for h in ("30", "60", "90"):
            for stop in (None, 0.08, 0.15):
                for tp in (None, 0.10, 0.20):
                    T[f"Exit {cname}|{h}|Stop {int(stop*100) if stop else '–'} / TP {int(tp*100) if tp else '–'}"] = summarize(attach(P, evs, H[h], stop, tp))

    # Jahresverläufe für die Hauptkandidaten
    for cname, evs in cands.items():
        R["years"][cname] = years(attach(P, evs, H["60"]))

    R["log"] = LOG[-60:]
    R["runtime_s"] = round(time.time() - t0)
    json.dump(R, open(os.path.join(OUT, "research.json"), "w"), ensure_ascii=False)
    write_summary(R)
    log("fertig in", R["runtime_s"], "s")


def write_summary(R):
    L = [f"# Edge-Forschung (Kurse bis {R['asof']})", "",
         f"SPY war nach 30/60/90 Tagen in {R['spy_up_rate']} % der Fälle im Plus (Grundrate für 'Trefferquote absolut').", "",
         "Spalten: n · schlägt S&P % · im Plus % · Ø vs S&P % · Median · t — jeweils IS (2020–23) | OOS (2024–26)", ""]
    def c(s):
        if not s or s.get("n", 0) < 10:
            return f"n={s.get('n', 0) if s else 0}"
        return f"{s['n']} · {s['beat']} · {s['win']} · {s['ex']:+.2f} · {s['med']:+.2f} · {s['t']}"
    cur = None
    for k, v in R["tables"].items():
        grp = k.split("|")[0]
        if grp != cur:
            L += ["", f"## {grp}", "", "| H | Filter | IS | OOS |", "|---|---|---|---|"]
            cur = grp
        _, h, name = k.split("|", 2)
        L.append(f"| {h} | {name} | {c(v['is'])} | {c(v['oos'])} |")
    L += ["", "## Jahre (60 T, gehedgt)", "", "```", json.dumps(R["years"], ensure_ascii=False), "```", "", "## Log", "", "```", *R["log"], "```"]
    md = "\n".join(L)
    open(os.path.join(OUT, "research.md"), "w").write(md)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md[:900000])


if __name__ == "__main__":
    run()
