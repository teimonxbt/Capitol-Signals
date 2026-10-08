"""
Ausschuss-Zuordnung: Welche Politiker sitzen in welchen Ausschüssen, und welche Branchen
beaufsichtigen diese Ausschüsse? Quellen (öffentlich, kostenlos):
- Ausschuss-Mitgliedschaften: github.com/unitedstates/congress-legislators (aktueller Kongress)
- Branchen je Ticker: github.com/rreichel3/US-Stock-Symbols (Nasdaq-Klassifikation)
Hinweis: Mitgliedschaften gibt es nur für den aktuellen Kongress (seit Jan. 2025).
"""
import json
import re

import requests
import yaml

CM_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committee-membership-current.yaml"
CO_URL = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/committees-current.yaml"
SYM_URLS = [f"https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/{x}/{x}_full_tickers.json" for x in ("nyse", "nasdaq", "amex")]

THEMES = {
    "def": "Verteidigung & Sicherheit",
    "fin": "Banken & Finanzen",
    "hea": "Gesundheit & Pharma",
    "ene": "Energie & Rohstoffe",
    "tec": "Tech & Telekom",
    "tra": "Verkehr & Infrastruktur",
    "agr": "Landwirtschaft & Lebensmittel",
}
# Branchen (Nasdaq "industry") -> Thema
IND = [
    ("def", r"^(Aerospace|Military/Government/Technical|Ordnance And Accessories)$"),
    ("fin", r"Bank|Savings Institutions|Investment Managers|Investment Bankers|Finance|Financial Services|Insurers|Life Insurance|Real Estate Investment Trusts|Homebuilding"),
    ("hea", r"Biotechnology|Medical|Pharmaceutical|Hospital|Health|Ophthalmic|Medicinal|Drug Stores|Accident &Health"),
    ("ene", r"Oil|Natural Gas|Electric Utilities|Power Generation|Coal|Metal Mining|Precious Metals|Steel|Metals and Minerals|Nonmetallic Minerals|Aluminum|Water Supply"),
    ("tec", r"Computer|EDP Services|Semiconductors|Telecommunications|Electronic Components|Broadcasting|Cable & Other Pay Television|Radio And Television"),
    ("tra", r"Railroads|Air Freight|Trucking|Marine Transportation|Transportation Services|Integrated Freight|Auto Manufacturing|Auto Parts|Motor Vehicles|Engineering & Construction|Other Transportation"),
    ("agr", r"Farming|Agricultural Chemicals|Meat/Poultry|Packaged Foods|Specialty Foods|Food Distributors|Tobacco|Beverages|Construction/Ag Equipment"),
]
# Große Rüstungs-/Sicherheitswerte, die die Nasdaq-Liste anders einordnet
AGR_EXTRA = {"DE", "CNH", "AGCO", "ADM", "BG", "CTVA", "FMC", "MOS", "NTR", "CF"}
DEF_EXTRA = {"LMT", "NOC", "RTX", "GD", "LHX", "BA", "HII", "LDOS", "BAH", "CACI", "SAIC", "PLTR", "KTOS", "AVAV", "TXT", "HEI", "TDG", "CW", "PSN", "MRCY", "BWXT", "AXON"}
# Ausschuss (thomas_id) -> Themen
COMMITTEE_THEMES = {
    "HSAS": ["def"], "SSAS": ["def"],
    "HLIG": ["def", "tec"], "SLIN": ["def", "tec"],
    "HSHM": ["def", "tec"], "SSGA": ["def", "tec"],
    "HSBA": ["fin"], "SSBK": ["fin"],
    "HSWM": ["fin", "hea"], "SSFI": ["fin", "hea"],
    "HSIF": ["hea", "ene", "tec"],
    "SSHR": ["hea"], "HSVR": ["hea"], "SSVA": ["hea"], "SPAG": ["hea"],
    "HSAG": ["agr"], "SSAF": ["agr"],
    "HSII": ["ene"], "SSEG": ["ene"], "SSEV": ["ene", "tra"],
    "HSPW": ["tra"], "SSCM": ["tra", "tec"],
    "HSSY": ["tec", "def"], "HSZS": ["tec", "def"],
    "HSJU": ["tec"], "SSJU": ["tec"],
}
# Regierung: Behörde -> Themen
AGENCY_THEMES = [
    (r"Defense|Army|Navy|Air Force|Intelligence|Homeland", ["def", "tec"]),
    (r"Treasury|Securities|Federal Reserve|Federal Deposit|Comptroller|Housing", ["fin"]),
    (r"Health|Food and Drug|Veterans|Social Security|Medicare", ["hea"]),
    (r"Energy|Interior|Nuclear|Environmental", ["ene"]),
    (r"Transportation", ["tra"]),
    (r"Agriculture", ["agr"]),
    (r"Commerce|Science and Technology|Communications", ["tec"]),
]


def ticker_themes(symbols_needed):
    ind = {}
    for u in SYM_URLS:
        try:
            for r in requests.get(u, timeout=60).json():
                ind[r["symbol"].replace("/", "-").replace("^", "-").upper()] = (r.get("industry") or "").strip()
        except Exception as e:  # noqa
            print("WARN Branchenliste", u, e)
    out, industries = {}, {}
    for s in symbols_needed:
        i = ind.get(s, "")
        industries[s] = i
        th = [k for k, rx in IND if i and re.search(rx, i, re.I)]
        if s in DEF_EXTRA and "def" not in th:
            th.append("def")
        if s in AGR_EXTRA and "agr" not in th:
            th.append("agr")
        if th:
            out[s] = th
    return out, industries


def member_committees(members):
    co = {c["thomas_id"]: c["name"] for c in yaml.safe_load(requests.get(CO_URL, timeout=60).text)}
    cm = yaml.safe_load(requests.get(CM_URL, timeout=60).text)
    by_bio = {}
    for cid, lst in cm.items():
        if cid not in COMMITTEE_THEMES:   # Unterausschüsse und allgemeine Ausschüsse überspringen
            continue
        for p in lst:
            by_bio.setdefault(p.get("bioguide"), []).append(cid)
    res = {}
    for i, m in enumerate(members):
        photo = m.get("photo") or ""
        mm = re.search(r"/([A-Z]\d{6})\.jpg", photo)
        cids = by_bio.get(mm.group(1), []) if mm else []
        th = sorted({t for c in cids for t in COMMITTEE_THEMES[c]})
        if m.get("chamber") == "executive":
            ag = (m.get("agency") or "") + " " + (m.get("office") or "")
            th = sorted({t for rx, ts in AGENCY_THEMES if re.search(rx, ag) for t in ts})
            cids = []
        if th:
            res[i] = {"c": [co.get(c, c) for c in cids], "th": th}
    return res
