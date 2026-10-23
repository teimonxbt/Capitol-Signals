"""
Capitol Signals – Wann stand jeder Trade zum ersten Mal in der Datenquelle?

Liest die Git-Historie von kadoa-org/congress-trading-monitor (ab 22.04.2026) und merkt sich für jeden Trade den Tag,
an dem er zum ersten Mal drinstand. Läuft inkrementell: im Cache (cache/pub_first.json) steht der zuletzt gelesene
Stand, beim nächsten Lauf werden nur neue Stände gelesen (flacher Clone). Fehlt der Cache, wird einmal alles gelesen.

avail(row) = Tag, ab dem man den Trade wirklich sehen konnte:
  - Meldung vor dem 22.04.2026 und schon im ersten Stand (bzw. in den ersten 3 Tagen) -> Meldedatum (unbekannt, pünktlich angenommen)
  - sonst: der spätere von Meldedatum und erstem Auftauchen
"""
import json
import os
import shutil
import subprocess
from datetime import date, timedelta

URL = "https://github.com/kadoa-org/congress-trading-monitor.git"
DIR = "public/data/filer"


def _lo(v):
    try:
        return str(int(float(v or 0)))
    except (TypeError, ValueError):
        return "0"


def _scan(repo, J, log):
    g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout
    commits = [l.split() for l in g("log", "--reverse", "--format=%H %ad", "--date=short", "--", DIR).splitlines()]
    hs = [c[0] for c in commits]
    head = J.get("head")
    if head and head not in hs:
        return False
    first = J.setdefault("first", {})
    k0 = hs.index(head) + 1 if head else 0
    prev = head
    for h, d in commits[k0:]:
        if prev is None:
            files = [l.split("\t")[1] for l in g("ls-tree", "-r", h, DIR + "/").splitlines()]
        else:
            files = [f for f in g("diff-tree", "--no-commit-id", "--name-only", "-r", prev, h, "--", DIR + "/").splitlines()]
        for f in files:
            if not f.endswith(".json"):
                continue
            try:
                data = json.loads(g("show", f"{h}:{f}"))
            except Exception:  # noqa – Datei gelöscht oder kaputt
                continue
            fid = f.rsplit("/", 1)[1][:-5]
            for t in data.get("trades", []):
                k = "|".join(str(x) for x in (fid, (t.get("ticker") or "").strip().upper(), t.get("filing_date"),
                                              t.get("transaction_date"), t.get("transaction_type"), _lo(t.get("amount_range_low"))))
                first.setdefault(k, d)
        prev = h
    if commits:
        J.setdefault("start", commits[0][1])
        J["head"], J["hdate"] = prev, commits[-1][1]
    log(f"Veröffentlichungs-Historie: {len(commits) - k0} neue Stände gelesen, {len(first)} Trades bekannt (bis {J.get('hdate')})")
    return True


def update(cache_dir, log=print):
    f = os.path.join(cache_dir, "pub_first.json")
    try:
        J = json.load(open(f))
    except Exception:  # noqa
        J = {}
    repo = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "kadoa_hist")
    try:
        for full in ((False, True) if J.get("hdate") else (True,)):
            if os.path.exists(repo):
                shutil.rmtree(repo)
            args = ["git", "clone", "-q", "--no-checkout", "--single-branch"]
            if not full:
                args += ["--shallow-since", (date.fromisoformat(J["hdate"]) - timedelta(days=4)).isoformat()]
            subprocess.run(args + [URL, repo], check=True, timeout=1200)
            if _scan(repo, J, log):
                break
            log("Veröffentlichungs-Historie: Lücke im flachen Clone – lese komplett neu")
            J = {}
        json.dump(J, open(f, "w"), separators=(",", ":"))
    except Exception as e:  # noqa – ohne Historie gilt alles als pünktlich
        log("Veröffentlichungs-Historie nicht aktualisiert:", type(e).__name__, str(e)[:200])
    finally:
        shutil.rmtree(repo, ignore_errors=True)
    return J


def avail_fn(J, members, yf_symbol):
    """Gibt avail(row) zurück: Tag, ab dem der Trade in den Daten stand (mindestens das Meldedatum)."""
    start, F = J.get("start"), J.get("first") or {}
    if not start:
        return lambda r: r["filed"]
    grace = (date.fromisoformat(start) + timedelta(days=3)).isoformat()
    idx = {}
    for k, d in F.items():
        fid, tk, filed, tx, tt, lo = k.split("|")
        side = "P" if tt == "Purchase" else "S" if tt.startswith("Sale") else None
        if not side:
            continue
        key = (fid, yf_symbol(tk), filed, tx, side, lo)
        if key not in idx or d < idx[key]:
            idx[key] = d

    def avail(r):
        d = idx.get((members[r["m"]].get("id"), r["t"], r["filed"], r["tx"], r["side"], _lo(r.get("lo"))))
        if d is None:
            return r["filed"]
        if r["filed"] < start:
            return d if d > grace else r["filed"]
        return max(d, r["filed"])
    return avail
