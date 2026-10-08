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
UA = {"User-Agent": "CapitolSignals/1.0 (research; teimonxbt@users.noreply.github.com)", "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"}
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
                log("SEC", tag, "HTTP", r.status_code, r.text[:160].replace("\n", " "))
                if r.status_code == 403:
                    log("SEC blockiert – nutze OpenInsider")
                    return pd.DataFrame()
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


def openinsider(start="2020-01-01"):
    """Ersatzquelle: OpenInsider-Screener (Form-4-Käufe, Code P), monatsweise."""
    cache_file = os.path.join(CACHE, "insider_oi.pkl")
    have = pd.read_pickle(cache_file) if os.path.exists(cache_file) else pd.DataFrame()
    done = set(have["mon"].unique()) if not have.empty else set()
    months = pd.date_range(start, date.today(), freq="MS")
    parts = [have] if not have.empty else []
    hdr = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
    fails = 0
    for k, m0 in enumerate(months):
        mon = m0.strftime("%Y-%m")
        recent = k >= len(months) - 2
        if mon in done and not recent:
            continue
        m1 = (m0 + pd.offsets.MonthEnd(0))
        rows = []
        for page in (1, 2, 3):
            url = ("http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=-1&fdr="
                   f"{m0:%m}%2F{m0:%d}%2F{m0:%Y}+-+{m1:%m}%2F{m1:%d}%2F{m1:%Y}"
                   "&td=0&tdr=&fdlyl=&fdlyh=&daysago=&xp=1&vl=&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0"
                   f"&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=5000&page={page}")
            try:
                r = requests.get(url, headers=hdr, timeout=90)
                tabs = pd.read_html(io.StringIO(r.text), attrs={"class": "tinytable"})
                t = tabs[0] if tabs else pd.DataFrame()
            except Exception as e:  # noqa
                log("OpenInsider", mon, page, type(e).__name__, str(e)[:100])
                t = pd.DataFrame()
                fails += 1
            if t.empty:
                break
            rows.append(t)
            if len(t) < 5000:
                break
            time.sleep(1.0)
        if not rows:
            if fails > 8:
                log("OpenInsider: zu viele Fehler, Abbruch")
                break
            continue
        t = pd.concat(rows, ignore_index=True)
        t.columns = [str(c).replace("\xa0", " ").strip() for c in t.columns]
        num = lambda x: pd.to_numeric(x.astype(str).str.replace(r"[+$,%]", "", regex=True), errors="coerce")
        title = t["Title"].fillna("").astype(str)
        d = pd.DataFrame({
            "mon": mon, "q": mon,
            "t": t["Ticker"].astype(str).str.upper().str.strip().str.replace(".", "-", regex=False),
            "filed": pd.to_datetime(t["Filing Date"], errors="coerce").dt.strftime("%Y-%m-%d"),
            "tx": pd.to_datetime(t["Trade Date"], errors="coerce").dt.strftime("%Y-%m-%d"),
            "cik": t["Insider Name"].astype(str),
            "val": num(t["Value"]).abs(), "sh": num(t["Qty"]).abs(), "after": num(t["Owned"]),
            "down": t["ΔOwn"].astype(str) if "ΔOwn" in t.columns else "",
            "officer": title.str.contains(r"CEO|CFO|COO|CTO|Pres|VP|GC|Officer|Chief|Treas|Sec", case=False, regex=True),
            "director": title.str.contains(r"Dir", case=False),
            "ten": title.str.contains("10%"),
            "ceo": title.str.contains(r"CEO|Pres", case=False, regex=True),
            "cfo": title.str.contains("CFO", case=False),
            "plan": False,   # OpenInsider zeigt keinen 10b5-1-Status
        }).dropna(subset=["filed", "t"])
        parts = [p for p in parts if p.empty or mon not in set(p["mon"])] + [d]
        if k % 6 == 0 or recent:
            log("OpenInsider", mon, len(d), "Käufe")
        time.sleep(1.0)
    if not parts:
        return pd.DataFrame()
    ib = pd.concat(parts, ignore_index=True)
    ib.to_pickle(cache_file)
    log("OpenInsider gesamt:", len(ib))
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
        self._dr = {}
        self.spy_dr = np.r_[np.nan, self.spy[1:] / self.spy[:-1] - 1]

    def beta(self, t, i):
        if t not in self._dr:
            c = self.cols[t]
            self._dr[t] = np.r_[np.nan, c[1:] / c[:-1] - 1]
        a, b = self._dr[t][max(1, i - 252):i], self.spy_dr[max(1, i - 252):i]
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 120:
            return 1.0
        a, b = a[ok], b[ok]
        v = np.var(b)
        return float(np.clip(np.cov(a, b)[0, 1] / v, 0.2, 3.0)) if v > 0 else 1.0

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
        f["beta"] = self.beta(t, i)
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
                "t": round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 2) if x.std() > 0 else None,
                **({"bbeat": round(float((np.array([e["exb"] for e in a]) > 0).mean() * 100), 1),
                    "bex": round(float(np.mean([e["exb"] for e in a]) * 100), 2),
                    "bt": round(float(np.mean([e["exb"] for e in a]) / (np.std([e["exb"] for e in a], ddof=1) / np.sqrt(len(a)))), 2)}
                   if "exb" in a[0] else {})}
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
        b = e.get("beta") or 1.0
        out.append({**e, "r": r, "s": s, "ex": r - s, "exb": r - b * s, "x": x})
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


# =============================================================================== Portfolio
def portfolio(P, evs, h, dates):
    """Alle offenen Positionen gleich gewichtet, täglich. 'long' = nur Aktien, 'hedged' = Aktie minus Beta*SPY."""
    n = P.n
    sl, sh, cnt = np.zeros(n), np.zeros(n), np.zeros(n)
    for e in evs:
        i = e["i"]
        if i is None or i >= n - 1:
            continue
        c = P.cols[e["t"]]
        x = min(i + h, n - 1)
        seg = c[i:x + 1]
        d = seg[1:] / seg[:-1] - 1
        d = np.where(np.isfinite(d), d, 0.0)
        sp = P.spy_dr[i + 1:x + 1]
        sp = np.where(np.isfinite(sp), sp, 0.0)
        sl[i + 1:x + 1] += d
        sh[i + 1:x + 1] += d - (e.get("beta") or 1.0) * sp
        cnt[i + 1:x + 1] += 1
    i0 = next(i for i, d in enumerate(dates) if d >= "2020-01-01")
    out = {}
    for k, s in (("long", sl), ("hedged", sh)):
        r = np.divide(s, cnt, out=np.zeros(n), where=cnt > 0)[i0:]
        eq = np.cumprod(1 + r)
        yrs = len(r) / 252
        peak = np.maximum.accumulate(eq)
        by = {}
        for j, d in enumerate(dates[i0:]):
            by.setdefault(d[:4], []).append(r[j])
        out[k] = {"cagr": round(float((eq[-1] ** (1 / yrs) - 1) * 100), 1), "mdd": round(float((eq / peak - 1).min() * 100), 1),
                  "sharpe": round(float(r.mean() / r.std() * np.sqrt(252)), 2) if r.std() > 0 else None,
                  "years": {y: round(float((np.prod(1 + np.array(v)) - 1) * 100), 1) for y, v in by.items()}}
    spy = P.spy_dr[i0:]
    spy = np.where(np.isfinite(spy), spy, 0)
    eqs = np.cumprod(1 + spy)
    out["spy_cagr"] = round(float((eqs[-1] ** (252 / len(spy)) - 1) * 100), 1)
    out["avg_pos"] = round(float(cnt[i0:].mean()), 1)
    out["invested"] = round(float((cnt[i0:] > 0).mean() * 100))
    return out


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
    CLS = {}
    feature_grid("Kongress-Kauf", CE)
    for mn in (2, 3):
        CL = clusters(CE, mn)
        for e in CL:
            e.update(P.feats(e["t"], e["i"]) or {})
        feature_grid(f"Cluster {mn}+", CL)
        log(f"Cluster {mn}+:", len(CL))
        CLS[mn] = CL

    # Dosis-Wirkung: Abstand zum 52-Wochen-Hoch (hält das Muster stufenweise?)
    BINS = [("0 bis -10%", -0.10, 9), ("-10 bis -20%", -0.20, -0.10), ("-20 bis -30%", -0.30, -0.20),
            ("-30 bis -40%", -0.40, -0.30), ("-40 bis -50%", -0.50, -0.40), ("mehr als -50%", -9, -0.50)]
    for lab, evs in (("Kongress-Kauf", CE), ("Cluster 2+", CLS[2]), ("Cluster 3+", CLS[3])):
        for h in ("30", "60", "90"):
            base = attach(P, evs, H[h])
            for bl, lo, hi in BINS:
                T[f"Abstand zum Hoch – {lab}|{h}|{bl}"] = summarize([e for e in base if e.get("from_high") is not None and lo < e["from_high"] <= hi])

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
        if ib.empty:
            ib = openinsider()
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
            for bl, lo, hi in BINS:
                T[f"Abstand zum Hoch – Insider >=100K|{h}|{bl}"] = summarize([e for e in base if e["val"] >= 1e5 and e.get("from_high") is not None and lo < e["from_high"] <= hi])
            cb = attach(P, CE, H[h])
            T[f"Kombi|{h}|Politiker-Kauf + Insider-Kauf (>=25K) 60 T davor"] = summarize([e for e in cb if e.get("insider60")])
            T[f"Kombi|{h}|Politiker-Kauf ohne Insider"] = summarize([e for e in cb if not e.get("insider60")])

    # ---- Punkt 5: Exits + Portfolio auf die Kandidaten
    far = lambda e: e.get("from_high") is not None and e["from_high"] < -0.30
    cands = {
        "Kongress-Kauf (alle)": CE,
        "Cluster 3+": CLS[3],
        "Kongress-Kauf >30% unter Hoch": [e for e in CE if far(e)],
        "Cluster 2+ >30% unter Hoch": [e for e in CLS[2] if far(e)],
        "Cluster 3+ >30% unter Hoch": [e for e in CLS[3] if far(e)],
    }
    if IE:
        cands["Insider >=100K"] = [e for e in IE if e["val"] >= 1e5 and e.get("price", 0) >= 5]
        cands["Insider Officer >=100K Kurs>=10$"] = [e for e in IE if e["officer"] and e["val"] >= 1e5 and e.get("price", 0) >= 10]
        cands["Insider-Cluster>=3 >=100K"] = [e for e in IE if e.get("n30", 0) >= 3 and e["val"] >= 1e5 and e.get("price", 0) >= 5]
        cands["Insider >=100K >30% unter Hoch"] = [e for e in IE if e["val"] >= 1e5 and e.get("price", 0) >= 5 and far(e)]
        cands["Politiker-Kauf + Insider 60T"] = [e for e in CE if e.get("insider60")]
    for cname, evs in cands.items():
        for h in ("30", "60", "90"):
            for stop in (None, 0.10):
                for tp in (None, 0.10, 0.20):
                    T[f"Exit {cname}|{h}|Stop {int(stop*100) if stop else '–'} / TP {int(tp*100) if tp else '–'}"] = summarize(attach(P, evs, H[h], stop, tp))
    R["portfolio"] = {}
    for cname, evs in cands.items():
        R["years"][cname] = years(attach(P, evs, H["60"]))
        for h in ("30", "60"):
            R["portfolio"][f"{cname} | {h} T"] = portfolio(P, evs, H[h], dates)

    # ---- Detailprüfung des besten Kandidaten: Politiker-Cluster in stark gefallenen Aktien
    R["detail"] = {}
    for thr in (-0.30, -0.35, -0.40, -0.45, -0.50):
        for mn in (2, 3):
            sel = [e for e in CLS[mn] if e.get("from_high") is not None and e["from_high"] <= thr]
            for h in ("30", "60"):
                T[f"Schwelle Cluster {mn}+|{h}|<= {int(thr*100)}% unter Hoch"] = summarize(attach(P, sel, H[h]))
        sel = [e for e in CE if e.get("from_high") is not None and e["from_high"] <= thr]
        T[f"Schwelle Einzelkauf|30|<= {int(thr*100)}% unter Hoch"] = summarize(attach(P, sel, H["30"]))
    deep = [e for e in CLS[2] if e.get("from_high") is not None and e["from_high"] <= -0.40]
    for h in ("30", "60"):
        R["portfolio"][f"Cluster 2+ >=40% unter Hoch | {h} T"] = portfolio(P, deep, H[h], dates)
        for stop in (None, 0.15):
            for tp in (None, 0.15, 0.25):
                T[f"Exit Cluster 2+ >=40% unter Hoch|{h}|Stop {int(stop*100) if stop else '–'} / TP {int(tp*100) if tp else '–'}"] = summarize(attach(P, deep, H[h], stop, tp))
    R["years"]["Cluster 2+ >=40% unter Hoch (30 T)"] = years(attach(P, deep, H["30"]))
    R["years"]["Einzelkauf >=40% unter Hoch (30 T)"] = years(attach(P, [e for e in CE if e.get("from_high") is not None and e["from_high"] <= -0.40], H["30"]))
    a30 = {(e["t"], e["d"]): e for e in attach(P, deep, H["30"])}
    a60 = {(e["t"], e["d"]): e for e in attach(P, deep, H["60"])}
    R["detail"]["Cluster 2+ >=40% unter Hoch"] = [
        [e["d"], e["t"], e["n"], round(e["from_high"] * 100), round(e.get("beta") or 1, 2),
         None if (e["t"], e["d"]) not in a30 else round(a30[(e["t"], e["d"])]["ex"] * 100, 1),
         None if (e["t"], e["d"]) not in a30 else round(a30[(e["t"], e["d"])]["exb"] * 100, 1),
         None if (e["t"], e["d"]) not in a60 else round(a60[(e["t"], e["d"])]["ex"] * 100, 1),
         round(e.get("price", 0), 2)]
        for e in sorted(deep, key=lambda e: e["d"])]

    R["log"] = LOG[-60:]
    R["runtime_s"] = round(time.time() - t0)
    json.dump(R, open(os.path.join(OUT, "research.json"), "w"), ensure_ascii=False)
    write_summary(R)
    log("fertig in", R["runtime_s"], "s")


def write_summary(R):
    L = [f"# Edge-Forschung (Kurse bis {R['asof']})", "",
         f"SPY war nach 30/60/90 Tagen in {R['spy_up_rate']} % der Fälle im Plus (Grundrate für 'Trefferquote absolut').", "",
         "Spalten: n · schlägt S&P % · im Plus % · Ø vs S&P % · Median · t ‖ β-bereinigt: schlägt % · Ø · t — jeweils IS (2020–23) | OOS (2024–26)", ""]
    def c(s):
        if not s or s.get("n", 0) < 10:
            return f"n={s.get('n', 0) if s else 0}"
        b = f" ‖ β {s['bbeat']} · {s['bex']:+.2f} · {s['bt']}" if "bex" in s else ""
        return f"{s['n']} · {s['beat']} · {s['win']} · {s['ex']:+.2f} · {s['med']:+.2f} · {s['t']}{b}"
    cur = None
    for k, v in R["tables"].items():
        grp = k.split("|")[0]
        if grp != cur:
            L += ["", f"## {grp}", "", "| H | Filter | IS | OOS |", "|---|---|---|---|"]
            cur = grp
        _, h, name = k.split("|", 2)
        L.append(f"| {h} | {name} | {c(v['is'])} | {c(v['oos'])} |")
    L += ["", "## Portfolio (gleichgewichtet, alle offenen Positionen)", "", "| Kandidat | long p.a. | long MaxDD | gehedgt p.a. | gehedgt MaxDD | Sharpe geh. | Ø Pos. | investiert % | gehedgt je Jahr |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in R.get("portfolio", {}).items():
        L.append(f"| {k} | {v['long']['cagr']} | {v['long']['mdd']} | {v['hedged']['cagr']} | {v['hedged']['mdd']} | {v['hedged']['sharpe']} | {v['avg_pos']} | {v['invested']} | {v['hedged']['years']} |")
    for k, rows_ in R.get("detail", {}).items():
        L += ["", f"## Einzelfälle: {k}", "", "Datum · Ticker · Käufer · % unter Hoch · Beta · vs S&P 30T · β-ber. 30T · vs S&P 60T · Kurs", "```"]
        L += [" · ".join(str(x) for x in r) for r in rows_]
        L += ["```"]
    L += ["", "## Jahre (gehedgt)", "", "```", json.dumps(R["years"], ensure_ascii=False), "```", "", "## Log", "", "```", *R["log"], "```"]
    md = "\n".join(L)
    open(os.path.join(OUT, "research.md"), "w").write(md)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        open(sp, "a").write(md[:900000])


if __name__ == "__main__":
    run()
