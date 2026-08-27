"""
niche_hunter_kp.py — Google Ads Keyword Planner layer for the Niche Hunter.

pip install google-ads pandas

WHAT KEYWORD PLANNER ADDS THAT NOTHING ELSE FREE DOES:
  * Absolute monthly search volume        -> demand SCALE (Trends only gives shape)
  * Top-of-page bid low/high (+ avg CPC)  -> advertiser value = the best free RPM proxy
  * Competition index 0-100               -> how contested the ad inventory is
  * 12 months of monthly volumes          -> seasonality + trend in absolute units
  * Per-country runs                      -> CPC in tier-1 vs everywhere else

TWO ACCESS PATHS:
  A) Google Ads API (this module's default)
     - Needs: a Google Ads account (can be zero-spend), a Manager (MCC) account,
       a developer token. Test-account-only until "Basic access" is approved
       (free, application-gated, usually days). Basic access = 15,000 ops/day.
     - KeywordPlanIdeaService: generateKeywordIdeas (<=20 seeds/request, up to
       10k ideas back) and generateKeywordHistoricalMetrics (exact keywords, batches).
     - API returns numeric volumes; the UI shows ranges on zero-spend accounts.
  B) UI export (fallback, no API approval needed)
     - Keyword Planner -> "Get search volume and forecasts" -> paste up to 10k
       keywords -> Historical metrics -> download CSV -> parse_ui_csv() below.

CAVEATS:
  * This is Google SEARCH data. YouTube search behaves differently. Use CPC as
    an advertiser-value proxy, not as a YouTube RPM number.
  * Metrics are grouped by "close variants" — plurals/misspellings collapse.
  * Long-tail terms often have no bid data (zeros). Aggregate at niche level,
    not per keyword.
  * Bids are auction prices for text ads; YouTube CPMs track them loosely
    (same advertiser pool, different inventory). Calibrate; don't convert.

Usage:
  python niche_hunter_kp.py "aviation disasters" "plane crash investigation"
  python niche_hunter_kp.py --csv export.csv --niche "aviation disasters" --geo US
"""

import os
import sys
import json
import sqlite3
import argparse
import statistics
from datetime import datetime, timezone

import pandas as pd

DB_PATH = os.environ.get("NH_DB", "niche_hunter.db")
CUSTOMER_ID = os.environ.get("GADS_CUSTOMER_ID", "")  # digits only, no dashes
CONFIG_PATH = os.environ.get("GADS_CONFIG", "google-ads.yaml")

# geoTargetConstants ids (criteria ids). Language 1000 = English.
GEO = {
    "US": 2840,
    "GB": 2826,
    "CA": 2124,
    "AU": 2036,
    "DE": 2276,
    "IN": 2356,
    "BR": 2076,
    "MX": 2484,
    "PH": 2608,
    "ES": 2724,
    "FR": 2250,
    "WW": None,
}
LANG = {"en": 1000, "es": 1003, "de": 1001, "fr": 1002, "pt": 1014}
TIER1 = {"US", "GB", "CA", "AU", "DE"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS kp_keywords (
    keyword TEXT, geo TEXT, lang TEXT, avg_monthly_searches INTEGER, competition TEXT,
    competition_index INTEGER, bid_low REAL, bid_high REAL, avg_cpc REAL,
    monthly_volumes JSON, source TEXT, niche TEXT, at TEXT,
    PRIMARY KEY (keyword, geo, lang, at));
CREATE TABLE IF NOT EXISTS kp_features (
    niche TEXT, geo TEXT, data JSON, computed_at TEXT);
"""


def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.executescript(SCHEMA)
    return con


# ----------------------------------------------------------------------------
# A. Google Ads API
# ----------------------------------------------------------------------------


def gads_client():
    from google.ads.googleads.client import GoogleAdsClient

    return GoogleAdsClient.load_from_storage(CONFIG_PATH)


def _metrics_to_row(text, m, geo, lang, source, niche):
    micros = lambda x: round(x / 1_000_000, 2) if x else None
    monthly = [
        {"y": mv.year, "m": int(mv.month), "v": mv.monthly_searches}
        for mv in getattr(m, "monthly_search_volumes", [])
    ]
    return {
        "keyword": text,
        "geo": geo,
        "lang": lang,
        "avg_monthly_searches": int(m.avg_monthly_searches or 0),
        "competition": m.competition.name if hasattr(m.competition, "name") else str(m.competition),
        "competition_index": int(m.competition_index or 0),
        "bid_low": micros(m.low_top_of_page_bid_micros),
        "bid_high": micros(m.high_top_of_page_bid_micros),
        "avg_cpc": micros(getattr(m, "average_cpc_micros", 0)),  # present in newer API versions
        "monthly_volumes": json.dumps(monthly),
        "source": source,
        "niche": niche,
    }


def keyword_ideas(client, seeds, geo="US", lang="en", niche=None, page_size=1000, url_seed=None):
    """
    Expand <=20 seed terms into up to thousands of related keywords with metrics.
    url_seed: optionally seed from a page (e.g. a competitor's channel/about page).
    """
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = CUSTOMER_ID
    req.language = f"languageConstants/{LANG[lang]}"
    if GEO.get(geo):
        req.geo_target_constants.append(f"geoTargetConstants/{GEO[geo]}")
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    req.include_adult_keywords = False
    req.page_size = page_size
    try:
        req.historical_metrics_options.include_average_cpc = True
    except Exception:
        pass
    if url_seed and seeds:
        req.keyword_and_url_seed.url = url_seed
        req.keyword_and_url_seed.keywords.extend(seeds[:20])
    elif url_seed:
        req.url_seed.url = url_seed
    else:
        req.keyword_seed.keywords.extend(seeds[:20])
    rows = []
    for idea in svc.generate_keyword_ideas(request=req):
        rows.append(
            _metrics_to_row(idea.text, idea.keyword_idea_metrics, geo, lang, "ideas", niche)
        )
    return rows


def historical_metrics(client, keywords, geo="US", lang="en", niche=None, batch=1000):
    """Exact metrics for keywords you already have (e.g. n-grams from YouTube titles)."""
    svc = client.get_service("KeywordPlanIdeaService")
    rows = []
    for i in range(0, len(keywords), batch):
        req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        req.customer_id = CUSTOMER_ID
        req.language = f"languageConstants/{LANG[lang]}"
        if GEO.get(geo):
            req.geo_target_constants.append(f"geoTargetConstants/{GEO[geo]}")
        req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        req.keywords.extend(keywords[i : i + batch])
        try:
            req.historical_metrics_options.include_average_cpc = True
        except Exception:
            pass
        resp = svc.generate_keyword_historical_metrics(request=req)
        for r in resp.results:
            rows.append(_metrics_to_row(r.text, r.keyword_metrics, geo, lang, "historical", niche))
    return rows


# ----------------------------------------------------------------------------
# B. UI CSV fallback
# ----------------------------------------------------------------------------


def parse_ui_csv(path, geo, lang="en", niche=None):
    """Parses the 'Historical metrics' download. Column names vary by locale; matched loosely."""
    df = pd.read_csv(
        path,
        sep=None,
        engine="python",
        encoding="utf-16" if open(path, "rb").read(2) in (b"\xff\xfe", b"\xfe\xff") else "utf-8",
        skiprows=lambda i: i < 2 and False,
    )
    cols = {c.lower(): c for c in df.columns}
    pick = lambda *names: next((cols[c] for c in cols if any(n in c for n in names)), None)
    c_kw, c_vol = pick("keyword"), pick("avg. monthly", "avg monthly", "monthly searches")
    c_comp, c_ci = pick("competition)"), pick("indexed")
    c_lo, c_hi = pick("low range"), pick("high range")
    month_cols = [
        c
        for c in df.columns
        if any(
            m in c.lower()
            for m in (
                "searches: jan",
                "searches: feb",
                "searches: mar",
                "searches: apr",
                "searches: may",
                "searches: jun",
                "searches: jul",
                "searches: aug",
                "searches: sep",
                "searches: oct",
                "searches: nov",
                "searches: dec",
            )
        )
    ]
    num = lambda x: (
        float(str(x).replace(",", "").replace("$", "").strip() or 0) if pd.notna(x) else None
    )
    rows = []
    for _, r in df.iterrows():
        monthly = [{"label": c, "v": int(num(r[c]) or 0)} for c in month_cols]
        rows.append(
            {
                "keyword": r[c_kw],
                "geo": geo,
                "lang": lang,
                "avg_monthly_searches": int(num(r[c_vol]) or 0) if c_vol else 0,
                "competition": r[c_comp] if c_comp else None,
                "competition_index": int(num(r[c_ci]) or 0) if c_ci else None,
                "bid_low": num(r[c_lo]) if c_lo else None,
                "bid_high": num(r[c_hi]) if c_hi else None,
                "avg_cpc": None,
                "monthly_volumes": json.dumps(monthly),
                "source": "ui_csv",
                "niche": niche,
            }
        )
    return rows


# ----------------------------------------------------------------------------
# Niche-level features (this is what joins the niche table)
# ----------------------------------------------------------------------------


def niche_features(rows, min_volume=10):
    """
    Volume-weighted advertiser value + demand scale + competition + seasonality.
    Uses top-of-page bid midpoint when avg_cpc is unavailable.
    """
    rs = [r for r in rows if r["avg_monthly_searches"] >= min_volume]
    if not rs:
        return {"status": "insufficient", "n": len(rows)}

    def cpc(r):
        if r.get("avg_cpc"):
            return r["avg_cpc"]
        if r.get("bid_low") and r.get("bid_high"):
            return (r["bid_low"] + r["bid_high"]) / 2
        return None

    priced = [(r["avg_monthly_searches"], cpc(r)) for r in rs if cpc(r)]
    total_vol = sum(r["avg_monthly_searches"] for r in rs)
    vw_cpc = sum(v * c for v, c in priced) / sum(v for v, _ in priced) if priced else None
    # seasonality/trend from monthly volumes summed across keywords
    agg = {}
    for r in rs:
        for mv in json.loads(r["monthly_volumes"]):
            k = (mv.get("y"), mv.get("m")) if "y" in mv else mv["label"]
            agg[k] = agg.get(k, 0) + mv["v"]
    series = [agg[k] for k in sorted(agg, key=str)]
    trend_3v3 = (sum(series[-3:]) / max(sum(series[:3]), 1) - 1) if len(series) >= 6 else None
    season = (
        (statistics.pstdev(series) / statistics.mean(series))
        if len(series) >= 12 and statistics.mean(series) > 0
        else None
    )
    return {
        "status": "ok",
        "n_keywords": len(rs),
        "total_monthly_searches": total_vol,
        "priced_share": round(
            len(priced) / len(rs), 2
        ),  # how much of the niche advertisers bid on at all
        "vw_cpc": round(vw_cpc, 2) if vw_cpc else None,
        "median_bid_high": round(
            statistics.median(r["bid_high"] for r in rs if r.get("bid_high")), 2
        )
        if any(r.get("bid_high") for r in rs)
        else None,
        "competition_index_mean": round(
            statistics.mean(
                r["competition_index"] for r in rs if r.get("competition_index") is not None
            ),
            1,
        )
        if any(r.get("competition_index") is not None for r in rs)
        else None,
        "trend_last3_vs_first3": round(trend_3v3, 3) if trend_3v3 is not None else None,
        "season_strength": round(season, 3) if season is not None else None,
        "top_keywords": sorted(rs, key=lambda r: -r["avg_monthly_searches"])[:10]
        and [
            (r["keyword"], r["avg_monthly_searches"], cpc(r))
            for r in sorted(rs, key=lambda r: -r["avg_monthly_searches"])[:10]
        ],
    }


def cpc_geo_spread(client, seeds, niche, geos=("US", "GB", "CA", "AU", "DE", "IN", "BR", "PH")):
    """Same seeds, per country -> tier-1 vs rest CPC ratio. Direct input to the RPM geo term."""
    out = {}
    for g in geos:
        f = niche_features(keyword_ideas(client, seeds, geo=g, niche=niche))
        out[g] = {"vw_cpc": f.get("vw_cpc"), "volume": f.get("total_monthly_searches")}
    t1 = [v["vw_cpc"] for g, v in out.items() if g in TIER1 and v["vw_cpc"]]
    rest = [v["vw_cpc"] for g, v in out.items() if g not in TIER1 and v["vw_cpc"]]
    out["tier1_cpc_ratio"] = (
        round(statistics.mean(t1) / statistics.mean(rest), 2) if t1 and rest else None
    )
    return out


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


def store(con, rows, niche):
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        con.execute(
            "INSERT OR REPLACE INTO kp_keywords VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["keyword"],
                r["geo"],
                r["lang"],
                r["avg_monthly_searches"],
                r["competition"],
                r["competition_index"],
                r["bid_low"],
                r["bid_high"],
                r["avg_cpc"],
                r["monthly_volumes"],
                r["source"],
                niche,
                now,
            ),
        )
    con.commit()
    return now


def run_api(seeds, niche, geo="US", lang="en"):
    client, con = gads_client(), db()
    rows = keyword_ideas(client, seeds, geo=geo, lang=lang, niche=niche)
    now = store(con, rows, niche)
    f = niche_features(rows)
    con.execute("INSERT INTO kp_features VALUES (?,?,?,?)", (niche, geo, json.dumps(f), now))
    con.commit()
    print(json.dumps({k: v for k, v in f.items() if k != "top_keywords"}, indent=1))
    for kw, vol, c in f.get("top_keywords", []):
        print(f"  {vol:>8,}  ${c or 0:5.2f}  {kw}")


def run_csv(path, niche, geo="US", lang="en"):
    con = db()
    rows = parse_ui_csv(path, geo, lang, niche)
    now = store(con, rows, niche)
    f = niche_features(rows)
    con.execute("INSERT INTO kp_features VALUES (?,?,?,?)", (niche, geo, json.dumps(f), now))
    con.commit()
    print(json.dumps({k: v for k, v in f.items() if k != "top_keywords"}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("seeds", nargs="*")
    ap.add_argument("--csv")
    ap.add_argument("--niche")
    ap.add_argument("--geo", default="US")
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    if a.csv:
        run_csv(a.csv, a.niche or "unnamed", a.geo, a.lang)
    else:
        run_api(
            a.seeds or ["aviation disasters"],
            a.niche or (a.seeds[0] if a.seeds else "unnamed"),
            a.geo,
            a.lang,
        )
