#!/usr/bin/env python3
"""
Capitol Signals – Daten-Update

1. Lädt alle offengelegten Aktien-Trades von US-Kongressabgeordneten (House + Senate)
   aus dem offenen Datensatz von kadoa-org/congress-trading-monitor (MIT-Lizenz),
   der täglich aus den offiziellen Quellen (House Clerk, Senate eFD) gebaut wird.
2. Lädt Tageskurse (dividendenbereinigt) über yfinance, inkl. SPY als Benchmark.
3. Berechnet pro Trade die Rendite AB VERÖFFENTLICHUNG (Einstieg: Schlusskurs des
   ersten Handelstags NACH dem Meldedatum) und zum Vergleich ab Trade-Datum.
4. Schreibt alles nach web/data/ – das Dashboard liest nur diese Dateien.

Aufruf:  python3 update.py            (inkrementell, nutzt Cache)
         python3 update.py --full     (Kurse komplett neu laden)
"""
import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(ROOT, "web", "data")
SRC = "https://raw.githubusercontent.com/kadoa-org/congress-trading-monitor/main/public/data"

START = "2020-01-01"          # Trades ab diesem Meldedatum
PRICE_START = "2019-06-01"    # Kurse ab hier (Puffer für Trade-Datum vor Meldung)
HORIZONS = {"30": 21, "90": 63, "180": 126, "365": 252}   # Kalendertage -> Handelstage
BENCH = "SPY"

OWNER = {"SP": "Ehepartner", "Spouse": "Ehepartner", "JT": "Gemeinsam", "Joint": "Gemeinsam",
         "DC": "Kind", "Child": "Kind", "Self": "Selbst", None: "Selbst", "SA": "Selbst"}
OPTION_TYPES = {"OP", "Stock Option"}
NON_EQUITY = {"GS", "CS", "Corporate Bond", "AB", "CT", "PS", "OL", "OT", "Other", "Municipal Security"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# --------------------------------------------------------------------------- Trades
def fetch_json(url, tries=4):
    for i in range(tries):
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def yf_symbol(t):
    t = t.strip().upper().replace(".", "-").replace("/", "-").replace(" ", "")
    return t


def looks_like_stock_ticker(t):
    if not t or len(t) > 7:
        return False
    if re.fullmatch(r"[0-9A-Z]{9}", t):   # CUSIP (Anleihen)
        return False
    return re.fullmatch(r"[A-Z][A-Z0-9\-]{0,6}", t) is not None


def load_trades():
    log("Lade Abgeordneten-Liste …")
    filers = [f for f in fetch_json(f"{SRC}/filers.json") if f.get("branch") in ("congress", "executive")]
    log(f"{len(filers)} Politiker (Kongress + Regierung) – lade Trades …")

    def one(f):
        try:
            return f, fetch_json(f"{SRC}/filer/{f['id']}.json")["trades"]
        except Exception as e:  # noqa
            log("  WARN", f["id"], e)
            return f, []

    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(one, filers))

    members, trades = [], []
    for f, rows in results:
        mi = len(members)
        members.append({
            "id": f["id"], "name": f["full_name"],
            "chamber": f.get("chamber") or ("executive" if f.get("branch") == "executive" else None),
            "agency": f.get("agency"),
            "party": f.get("party"), "state": f.get("state"), "office": f.get("office"),
            "photo": f.get("photo_url"),
        })
        seen = set()
        for t in rows:
            filed, tx = t.get("filing_date"), t.get("transaction_date")
            if not filed or filed < START or not tx or tx > filed:
                continue
            tt = t.get("transaction_type") or ""
            if tt == "Purchase":
                side = "P"
            elif tt.startswith("Sale"):
                side = "S"
            else:
                continue
            raw = (t.get("ticker") or "").strip().upper()
            if not raw:
                continue
            at = t.get("asset_type")
            if at in OPTION_TYPES:
                kind = "opt"
            elif at in NON_EQUITY or not looks_like_stock_ticker(yf_symbol(raw)):
                continue
            else:
                kind = "st"
            key = t.get("id") or (raw, tx, filed, side, t.get("amount_range_low"))
            if key in seen:
                continue
            seen.add(key)
            trades.append({
                "m": mi, "t": yf_symbol(raw), "side": side, "partial": int("Partial" in tt),
                "kind": kind, "owner": OWNER.get(t.get("owner"), t.get("owner") or "Selbst"),
                "tx": tx, "filed": filed,
                "lo": t.get("amount_range_low") or 0, "hi": t.get("amount_range_high") or 0,
                "asset": (t.get("asset_name") or "")[:80], "doc": t.get("doc_url") or "",
                "comment": (t.get("comment") or "")[:160],
            })
    # nur Abgeordnete mit mindestens einem Trade behalten
    used = sorted({t["m"] for t in trades})
    remap = {old: new for new, old in enumerate(used)}
    members = [members[i] for i in used]
    for t in trades:
        t["m"] = remap[t["m"]]
    log(f"{len(trades)} Trades von {len(members)} Politikern seit {START}")
    return members, trades


# --------------------------------------------------------------------------- Kurse
RATE_HINTS = ("rate", "too many", "resolve host", "curl", "timed out", "timeout", "connection")


def download_batch(symbols, start):
    """Lädt Schlusskurse. Gibt (DataFrame, Menge der Ticker mit Rate-Limit/Netzfehler) zurück."""
    import yfinance as yf
    try:
        import yfinance.shared as yfs   # Fehlerliste (je nach yfinance-Version vorhanden)
        yfs._ERRORS.clear()
    except Exception:  # noqa
        yfs = None
    try:
        df = yf.download(symbols, start=start, auto_adjust=True, progress=False,
                         threads=2, group_by="column")
    except Exception as e:  # noqa
        log(f"  Fehler: {e.__class__.__name__}: {e}")
        return pd.DataFrame(), set(symbols)
    errs = dict(getattr(yfs, "_ERRORS", {}) or {}) if yfs is not None else {}
    limited = {t for t, msg in errs.items() if any(h in str(msg).lower() for h in RATE_HINTS)}
    if df is None or df.empty:
        return pd.DataFrame(), limited
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    if isinstance(close, pd.Series):
        close = close.to_frame(symbols[0])
    if list(close.columns) == ["Close"]:
        close.columns = [symbols[0]]
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.dropna(axis=1, how="all")
    return close, limited


def nasdaq_prices(symbols, start):
    """Ersatzquelle: Tagesschlusskurse von api.nasdaq.com (split-, aber nicht dividendenbereinigt)."""
    hdr = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}
    out = {}
    today = date.today().isoformat()
    for n, sym in enumerate(symbols):
        q = sym.replace("-", ".")
        for cls in ("stocks", "etf"):
            try:
                r = requests.get(f"https://api.nasdaq.com/api/quote/{q}/historical",
                                 params={"assetclass": cls, "fromdate": start, "todate": today, "limit": 9999},
                                 headers=hdr, timeout=20)
                rows = ((r.json().get("data") or {}).get("tradesTable") or {}).get("rows") or []
            except Exception:  # noqa
                rows = []
            if rows:
                ser = {}
                for row in rows:
                    try:
                        d = datetime.strptime(row["date"], "%m/%d/%Y")
                        ser[pd.Timestamp(d)] = float(str(row["close"]).replace("$", "").replace(",", ""))
                    except Exception:  # noqa
                        pass
                if len(ser) > 5:
                    out[sym] = pd.Series(ser).sort_index()
                break
        if (n + 1) % 25 == 0:
            log(f"  Nasdaq: {n + 1}/{len(symbols)} · {len(out)} gefunden")
            if not out:
                log("  Nasdaq liefert nichts – breche ab.")
                break
        time.sleep(0.4)
    log(f"  Nasdaq: {len(out)} von {len(symbols)} Tickern gefunden")
    return pd.DataFrame(out) if out else pd.DataFrame()


def load_prices(symbols, full=False, downloader=download_batch):
    os.makedirs(CACHE, exist_ok=True)
    cache_file = os.path.join(CACHE, "prices.pkl")
    failed_file = os.path.join(CACHE, "failed.json")
    prices = pd.DataFrame()
    seed_file = os.path.join(CACHE, "seed.pkl.gz")   # Start-Cache fürs Online-Repo
    if os.path.exists(cache_file) and not full:
        prices = pd.read_pickle(cache_file)
    elif os.path.exists(seed_file) and not full:
        log("Nutze mitgelieferten Start-Cache …")
        prices = pd.read_pickle(seed_file)
    # Ticker ohne Daten: erst nach 3 erfolglosen Versuchen (ohne Rate-Limit) endgültig überspringen
    tries = {}
    if os.path.exists(failed_file) and not full:
        raw = json.load(open(failed_file))
        tries = raw.get("tries", {}) if isinstance(raw, dict) and raw.get("v") == 2 else {}

    def merge(df):
        nonlocal prices
        if df is None or df.empty:
            return
        if prices.empty:
            prices = df.copy()
            return
        idx = prices.index.union(df.index)
        prices = prices.reindex(idx)
        dfr = df.reindex(idx)
        common = [c for c in dfr.columns if c in prices.columns]
        if common:
            prices[common] = dfr[common].combine_first(prices[common])
        newc = [c for c in dfr.columns if c not in prices.columns]
        if newc:
            prices = pd.concat([prices, dfr[newc]], axis=1)

    def persist():
        prices.sort_index().to_pickle(cache_file)
        json.dump({"v": 2, "tries": tries}, open(failed_file, "w"))

    state = {"streak": 0, "blocked": False}

    def run(syms, start, label, size=25):
        """Lädt in kleinen Paketen. Yahoo meldet Überlastung oft als "possibly delisted" –
        fehlt mehr als ein Drittel eines Pakets, gilt das Paket als gebremst: Pause, neuer Versuch."""
        missing = []
        for i in range(0, len(syms), size):
            batch = syms[i:i + size]
            if state["blocked"]:
                missing += [s for s in batch if s not in prices.columns]
                continue
            log(f"  {label}: {min(i + size, len(syms))}/{len(syms)}")
            todo = list(batch)
            any_got = False
            for attempt in range(4):
                # SPY läuft als Kontrolle mit: fehlt SPY, bremst Yahoo; sonst sind Lücken echte Delistings
                req = todo if BENCH in todo else todo + [BENCH]
                df, limited = downloader(req, start)
                if df is not None and not df.empty and BENCH not in todo and BENCH in df.columns:
                    df = df.drop(columns=[BENCH])
                    canary = True
                else:
                    canary = BENCH in todo and df is not None and BENCH in df.columns
                merge(df)
                got = set(df.columns) if df is not None and not df.empty else set()
                any_got = any_got or bool(got) or canary
                fails = [s for s in todo if s not in got]
                if fails and not canary:
                    limited = set(fails)
                todo = [s for s in fails if s in limited]
                if not todo:
                    break
                wait = 45 * (attempt + 1)
                log(f"  Yahoo bremst ({len(todo)} Ticker) – warte {wait}s …")
                time.sleep(wait)
            missing += [s for s in batch if s not in prices.columns]
            persist()
            state["streak"] = 0 if any_got else state["streak"] + 1
            if state["streak"] >= 2 and len(batch) > 1:
                state["blocked"] = True
                log("  Yahoo blockiert gerade komplett – überspringe den Rest und rechne mit den vorhandenen Kursen.")
            time.sleep(3)
        return missing

    # 1) Benchmark zuerst – ohne SPY geht nichts
    if BENCH not in prices.columns or full:
        log("Lade Benchmark SPY …")
        run([BENCH], PRICE_START, "SPY", size=1)
        if BENCH not in prices.columns:
            raise SystemExit("SPY konnte nicht geladen werden (Yahoo gesperrt?). Warte 15 Minuten und starte erneut.")

    # 2) Aktualisieren, was schon im Cache ist
    if not prices.empty and prices.index.max().date() < date.today():
        start = (prices.index.max() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        cols = list(prices.columns)
        log(f"Aktualisiere {len(cols)} Ticker ab {start} …")
        run(cols, start, "Update", size=80)

    # 3) Neue Ticker
    symbols = sorted(set(symbols))
    new = [s for s in symbols if s not in prices.columns and tries.get(s, 0) < 3]
    if new:
        log(f"Lade Kurshistorie für {len(new)} Ticker …")
        miss = run(new, PRICE_START, "Neu")
        if miss and not state["blocked"]:
            # Yahoo meldet bei Überlastung manchmal fälschlich "delisted" – ein zweiter, langsamer Durchgang
            log(f"{len(miss)} Ticker ohne Daten – zweiter Versuch in 60s …")
            time.sleep(60)
            miss = run(miss, PRICE_START, "Nachladen", size=20)
        if miss:
            log(f"{len(miss)} Ticker fehlen bei Yahoo – versuche Nasdaq.com …")
            got = nasdaq_prices(miss, PRICE_START)
            merge(got)
            miss = [s for s in miss if s not in prices.columns]
        for s in ([] if state["blocked"] else miss):
            tries[s] = tries.get(s, 0) + 1
    persist()

    prices = prices.sort_index()
    empty = [c for c in prices.columns if prices[c].notna().sum() < 5]
    prices = prices.drop(columns=empty)
    still = [s for s in symbols if s not in prices.columns]
    log(f"Kurse: {prices.shape[1]} Ticker, {prices.shape[0]} Tage · {len(still)} ohne Kurse "
        f"(meist delistet/übernommen; werden bei den nächsten Starts erneut versucht)")
    return prices


# --------------------------------------------------------------------------- Metriken
def r1(x):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(x * 100, 1)


def compute(members, trades, prices):
    if BENCH not in prices.columns:
        raise SystemExit("SPY fehlt in den Kursdaten.")
    cal = prices[BENCH].dropna().index
    px = prices.reindex(cal).ffill(limit=5).astype("float64")
    dates = [d.strftime("%Y-%m-%d") for d in cal]
    n = len(dates)
    spy = px[BENCH].values
    cols = {c: px[c].values for c in px.columns}
    import bisect

    def idx_on_or_after(d):
        return bisect.bisect_left(dates, d)

    def idx_after(d):
        return bisect.bisect_right(dates, d)

    def ret(arr, i, j):
        if i >= n or j >= n or i < 0:
            return None
        a, b = arr[i], arr[j]
        if a is None or b is None or not (a > 0) or not (b > 0):
            return None
        return b / a - 1

    last = n - 1
    rows = []
    for t in trades:
        arr = cols.get(t["t"])
        pub = idx_after(t["filed"])          # erster Handelstag NACH Meldung
        txi = idx_on_or_after(t["tx"])       # Handelstag des Trades
        rec = dict(t)
        rec["pi"] = pub if pub < n else None
        rec["ti"] = txi if txi < n else None
        has = arr is not None and t["kind"] == "st"
        rec["px"] = int(arr is not None)
        for k, h in HORIZONS.items():
            if has and pub + h <= last:
                r = ret(arr, pub, pub + h)
                s = ret(spy, pub, pub + h)
                rec["r" + k] = r1(r)
                rec["x" + k] = r1(None if r is None or s is None else r - s)
            else:
                rec["r" + k] = rec["x" + k] = None
            if has and txi + h <= last:
                r = ret(arr, txi, txi + h)
                s = ret(spy, txi, txi + h)
                rec["tx" + k] = r1(None if r is None or s is None else r - s)
            else:
                rec["tx" + k] = None
        if has and pub <= last:
            r, s = ret(arr, pub, last), ret(spy, pub, last)
            rec["rn"] = r1(r)
            rec["xn"] = r1(None if r is None or s is None else r - s)
        else:
            rec["rn"] = rec["xn"] = None
        if has and pub <= last:
            r, s = ret(arr, txi, pub), ret(spy, txi, pub)
            rec["lag"] = r1(r)
            rec["lagx"] = r1(None if r is None or s is None else r - s)
        else:
            rec["lag"] = rec["lagx"] = None
        rows.append(rec)
    return dates, px, rows


# --------------------------------------------------------------------------- Export
def sig(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if v == 0:
        return 0
    d = max(0, 4 - int(math.floor(math.log10(abs(v)))) - 1)
    return round(float(v), min(d, 6))


def export(members, rows, dates, px):
    os.makedirs(os.path.join(OUT, "prices"), exist_ok=True)
    for r in rows:
        d = r["doc"]
        m = re.match(r"https://disclosures-clerk\.house\.gov/public_disc/ptr-pdfs/(.+)\.pdf$", d)
        m2 = re.match(r"https://efdsearch\.senate\.gov/search/view/(.+?)/?$", d)
        r["doc"] = "h:" + m.group(1) if m else ("s:" + m2.group(1) if m2 else d)
    fields = ["m", "t", "side", "partial", "kind", "owner", "tx", "filed", "lo", "hi", "asset", "doc",
              "comment", "pi", "ti", "px", "r30", "r90", "r180", "r365", "x30", "x90", "x180", "x365",
              "tx30", "tx90", "tx180", "tx365", "rn", "xn", "lag", "lagx"]
    rows.sort(key=lambda r: (r["filed"], r["tx"]), reverse=True)
    json.dump({"fields": fields, "rows": [[r.get(f) for f in fields] for r in rows]},
              open(os.path.join(OUT, "trades.json"), "w"), separators=(",", ":"))
    json.dump(members, open(os.path.join(OUT, "members.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    json.dump({"dates": dates, "spy": [sig(v) for v in px[BENCH].values]},
              open(os.path.join(OUT, "calendar.json"), "w"), separators=(",", ":"))

    buckets = {}
    needed = {r["t"] for r in rows}
    first_need = {}
    for r in rows:
        i = r["ti"] if r["ti"] is not None else r["pi"]
        if i is not None:
            first_need[r["t"]] = min(first_need.get(r["t"], i), i)
    for c in px.columns:
        if c not in needed and c not in (BENCH, "QQQ"):
            continue
        s = px[c].values
        lo = 0 if c == BENCH else max(0, first_need.get(c, 0) - 130)   # ~6 Monate Chart-Vorlauf
        first = next((i for i in range(lo, len(s)) if s[i] == s[i] and s[i] is not None), None)
        if first is None:
            continue
        vals = [sig(v) for v in s[first:]]
        while vals and vals[-1] is None:
            vals.pop()
        b = bucket_of(c)
        buckets.setdefault(b, {})[c] = [first, vals]
    for f in os.listdir(os.path.join(OUT, "prices")):
        os.remove(os.path.join(OUT, "prices", f))
    for b, d in buckets.items():
        json.dump(d, open(os.path.join(OUT, "prices", f"{b}.json"), "w"), separators=(",", ":"))

    meta = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lastPrice": dates[-1], "firstPrice": dates[0], "start": START,
        "trades": len(rows), "members": len(members), "tickers": len(needed),
        "priced": sum(1 for r in rows if r["px"]), "horizons": HORIZONS,
        "buckets": sorted(buckets),
        "source": "kadoa-org/congress-trading-monitor (House Clerk + Senate eFD), Kurse: Yahoo Finance",
    }
    json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1)
    log(f"Fertig: {len(rows)} Trades, {len(buckets)} Kursdateien -> {OUT}")


def bucket_of(sym):
    c = sym[0]
    return c if c.isalpha() else "0"


def main(argv=None, downloader=download_batch):
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Kurscache verwerfen und alles neu laden")
    a = ap.parse_args(argv)
    members, trades = load_trades()
    prices = load_prices({t["t"] for t in trades} | {"QQQ"}, full=a.full, downloader=downloader)
    dates, px, rows = compute(members, trades, prices)
    export(members, rows, dates, px)
    import signals
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    site = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" if "/" in repo else ""
    sigs = signals.write_signals(OUT, CACHE, members, rows, dates, px, BENCH, site)
    log(f"Signale: {sum(s['active'] for s in sigs)} aktiv, {len(sigs)} gesamt")


if __name__ == "__main__":
    sys.exit(main())
