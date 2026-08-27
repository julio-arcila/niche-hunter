"""
niche_hunter_trends.py — Google Trends (trendspy) demand-side layer for the Niche Hunter.

pip install trendspy pandas numpy

Google Trends is a DEMAND signal (what people search) while the YouTube API/RSS
layers are SUPPLY signals (what creators publish). The niche score lives in the gap.

What this module extracts per niche cluster:
  1. Anchor-scaled interest over time  -> comparable across keywords & batches
  2. Trend features                     -> slope, YoY, recent momentum, seasonality, breakout
  3. Seed expansion                     -> rising/breakout related queries + topics (mids)
  4. Geo tier-1 share                   -> RPM model input
  5. Trending-now matches               -> early-velocity feed filtered to your niches

Hard constraints of the source (design around them, don't fight them):
  * Values are normalized 0-100 PER REQUEST. Never compare numbers from two
    different requests unless both contain the same anchor keyword.
  * Max 5 terms per request -> 1 anchor + 4 targets per batch.
  * No absolute volumes. Use Keyword Planner for scale; Trends for shape.
  * Sampled: re-running gives +/-5 point jitter. Smooth, don't overfit.
  * Low-volume terms return all zeros. Prefer TOPICS (Freebase mids like /m/0abc)
    from related_topics() over raw strings — they aggregate spellings/languages.
  * Unofficial endpoint: expect 429s. Cache everything, pace requests, use a proxy
    pool if you go above a few hundred calls/day.

Usage:
  python niche_hunter_trends.py "aviation disasters" "plane crash investigation"
"""

import os
import sys
import json
import time
import random
import sqlite3
import hashlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from trendspy import Trends

DB_PATH = os.environ.get("NH_DB", "niche_hunter.db")
ANCHOR = os.environ.get("NH_TRENDS_ANCHOR", "documentary")  # stable, mid-volume, niche-agnostic
TIER1 = {"US", "GB", "CA", "AU", "DE", "CH", "NO", "SE", "DK", "NL", "IE", "NZ", "AT"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS trends_cache (k TEXT PRIMARY KEY, payload TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS trends_features (
    keyword TEXT, geo TEXT, timeframe TEXT, data JSON, computed_at TEXT);
CREATE TABLE IF NOT EXISTS trends_seeds (
    parent TEXT, kind TEXT, value TEXT, growth TEXT, at TEXT);
"""


# ----------------------------------------------------------------------------
# Client with cache + backoff
# ----------------------------------------------------------------------------


class TrendsClient:
    def __init__(self, proxy=None, min_gap_s=2.5, cache_ttl_h=24):
        self.tr = Trends(proxy=proxy) if proxy else Trends()
        self.min_gap, self.ttl = min_gap_s, cache_ttl_h * 3600
        self._last = 0.0
        self.con = sqlite3.connect(DB_PATH, timeout=30)
        self.con.executescript(SCHEMA)

    def _key(self, name, *args, **kw):
        return hashlib.sha1(
            json.dumps([name, args, kw], sort_keys=True, default=str).encode()
        ).hexdigest()

    def _cached(self, k):
        row = self.con.execute("SELECT payload, at FROM trends_cache WHERE k=?", (k,)).fetchone()
        if row and (time.time() - datetime.fromisoformat(row[1]).timestamp()) < self.ttl:
            return json.loads(row[0])
        return None

    def _store(self, k, payload):
        self.con.execute(
            "INSERT OR REPLACE INTO trends_cache VALUES (?,?,?)",
            (k, json.dumps(payload, default=str), datetime.now(timezone.utc).isoformat()),
        )
        self.con.commit()

    def _call(self, name, *args, **kw):
        k = self._key(name, *args, **kw)
        hit = self._cached(k)
        if hit is not None:
            return hit, True
        for attempt in range(5):
            wait = max(0, self.min_gap - (time.time() - self._last)) + random.uniform(0, 0.8)
            time.sleep(wait)
            try:
                self._last = time.time()
                res = getattr(self.tr, name)(*args, **kw)
                payload = res.to_dict(orient="split") if isinstance(res, pd.DataFrame) else res
                self._store(k, payload)
                return payload, False
            except Exception as e:  # 429 / parse errors surface here
                msg = str(e)
                if "429" in msg or "Too Many" in msg or attempt < 4:
                    time.sleep(min(120, 10 * 2**attempt))
                    continue
                raise
        raise RuntimeError(f"trends call failed: {name} {args}")

    @staticmethod
    def _df(payload):
        if isinstance(payload, dict) and "columns" in payload:
            df = pd.DataFrame(payload["data"], columns=payload["columns"], index=payload["index"])
            df.index = pd.to_datetime(df.index)
            return df
        return payload

    # --- thin wrappers -------------------------------------------------------
    def interest_over_time(self, keywords, timeframe="today 5-y", geo="", cat=None, gprop=None):
        kw = dict(timeframe=timeframe, geo=geo)
        if cat:
            kw["cat"] = cat
        if gprop:  # 'youtube' restricts to YouTube search if your trendspy version supports it
            kw["gprop"] = gprop
        p, _ = self._call("interest_over_time", keywords, **kw)
        return self._df(p)

    def interest_by_region(self, keyword, timeframe="today 12-m", resolution="COUNTRY"):
        p, _ = self._call("interest_by_region", keyword, timeframe=timeframe, resolution=resolution)
        return self._df(p)

    def related_queries(self, keyword, timeframe="today 12-m", geo=""):
        p, _ = self._call("related_queries", keyword, timeframe=timeframe, geo=geo)
        return p

    def related_topics(self, keyword, timeframe="today 12-m", geo=""):
        p, _ = self._call("related_topics", keyword, timeframe=timeframe, geo=geo)
        return p

    def trending_now(self, geo="US"):
        p, _ = self._call("trending_now", geo=geo)
        return p


# ----------------------------------------------------------------------------
# 1. Anchor scaling — make interest comparable across batches
# ----------------------------------------------------------------------------


def anchor_scaled_interest(client, keywords, anchor=ANCHOR, timeframe="today 5-y", geo="", **kw):
    """
    Every batch includes the anchor. Each target series is rescaled so the anchor's
    mean == 100 across batches, giving a common unit ('anchor-relative interest').
    Returns a DataFrame with one column per keyword (+ anchor).
    """
    frames = []
    targets = [k for k in keywords if k != anchor]
    for i in range(0, len(targets), 4):
        batch = [anchor] + targets[i : i + 4]
        df = client.interest_over_time(batch, timeframe=timeframe, geo=geo, **kw)
        df = df[[c for c in df.columns if c in batch]]
        a_mean = df[anchor].replace(0, np.nan).mean()
        if not a_mean or np.isnan(a_mean):
            raise ValueError(
                f"anchor '{anchor}' has no volume in batch {batch}; pick a bigger anchor"
            )
        scale = 100.0 / a_mean
        frames.append(df.drop(columns=[anchor]) * scale)
        anchor_series = df[anchor] * scale
    out = pd.concat(frames, axis=1)
    out[anchor] = anchor_series
    return out


# ----------------------------------------------------------------------------
# 2. Trend features per keyword series
# ----------------------------------------------------------------------------


def trend_features(s: pd.Series):
    """s: weekly (5y) or daily (12m) interest, already anchor-scaled."""
    s = s.astype(float).replace(0, np.nan).interpolate(limit_direction="both").fillna(0)
    n = len(s)
    if n < 20 or s.sum() == 0:
        return {"status": "insufficient"}
    t = np.arange(n)
    # log-linear slope over the whole window (growth rate per period)
    y = np.log1p(s.values)
    slope = np.polyfit(t, y, 1)[0]
    # recent momentum: last 13 periods vs previous 13
    rec, prev = s.iloc[-13:].mean(), s.iloc[-26:-13].mean() if n >= 26 else np.nan
    momentum = (rec / prev - 1) if prev and not np.isnan(prev) and prev > 0 else None
    # YoY: last 52 vs prior 52 (weekly) — fall back to halves if shorter
    if n >= 104:
        yoy = s.iloc[-52:].mean() / max(s.iloc[-104:-52].mean(), 1e-6) - 1
    else:
        h = n // 2
        yoy = s.iloc[h:].mean() / max(s.iloc[:h].mean(), 1e-6) - 1
    # seasonality: month index normalized to 1.0, plus concentration
    by_month = s.groupby(s.index.month).mean()
    season_idx = (by_month / by_month.mean()).round(2).to_dict() if by_month.mean() > 0 else {}
    season_strength = float(by_month.std() / by_month.mean()) if by_month.mean() > 0 else None
    # breakout: last 4 periods vs trailing-52 median, z-scored
    trail = s.iloc[-56:-4] if n >= 56 else s.iloc[:-4]
    z = (s.iloc[-4:].mean() - trail.median()) / max(trail.std(), 1e-6)
    return {
        "status": "ok",
        "level": round(float(s.iloc[-13:].mean()), 2),  # anchor-relative
        "slope_log_per_period": round(float(slope), 5),
        "momentum_13p": None if momentum is None else round(float(momentum), 3),
        "yoy": round(float(yoy), 3),
        "season_strength": None if season_strength is None else round(season_strength, 3),
        "season_index": season_idx,
        "peak_month": int(by_month.idxmax()) if len(by_month) else None,
        "breakout_z": round(float(z), 2),
        "breakout": bool(z > 2.5),
        "volatility": round(float(s.pct_change().std()), 3),
        "n_periods": n,
    }


# ----------------------------------------------------------------------------
# 3. Seed expansion — feed search.list and discover sub-niches
# ----------------------------------------------------------------------------


def expand_seeds(client, keyword, timeframe="today 12-m", geo=""):
    """
    Returns rising related queries/topics. 'Breakout' (>5000%) entries are the
    ones to route straight into YouTube discovery; they're sub-niches forming NOW.
    trendspy returns dict-like {'top': df, 'rising': df}; structure may vary by version.
    """
    seeds = []
    for kind, fn in (("query", client.related_queries), ("topic", client.related_topics)):
        res = fn(keyword, timeframe=timeframe, geo=geo)
        rising = res.get("rising") if isinstance(res, dict) else None
        if rising is None:
            continue
        rows = (
            rising
            if isinstance(rising, list)
            else pd.DataFrame(rising.get("data", []), columns=rising.get("columns", [])).to_dict(
                "records"
            )
        )
        for r in rows:
            val = r.get("query") or r.get("topic_title") or r.get("title") or r.get("value")
            growth = str(r.get("value") or r.get("formattedValue") or "")
            mid = r.get("topic_mid") or r.get("mid")
            seeds.append(
                {
                    "parent": keyword,
                    "kind": kind,
                    "value": val,
                    "mid": mid,
                    "growth": growth,
                    "breakout": "Breakout" in growth
                    or growth.replace("%", "").replace("+", "").isdigit()
                    and int(growth.replace("%", "").replace("+", "")) >= 5000,
                }
            )
    return seeds


# ----------------------------------------------------------------------------
# 4. Geo tier-1 share (RPM input)
# ----------------------------------------------------------------------------


def geo_tier1_share(client, keyword, timeframe="today 12-m"):
    """
    interest_by_region is normalized per-region (100 = region's own peak), NOT
    volume-weighted. Weight by internet-population to approximate share of demand.
    """
    df = client.interest_by_region(keyword, timeframe=timeframe, resolution="COUNTRY")
    col = keyword if keyword in df.columns else df.columns[0]
    s = df[col].astype(float)
    # crude internet-user weights (millions); refine with real data if you care about precision
    w = {
        "US": 310,
        "GB": 66,
        "CA": 36,
        "AU": 24,
        "DE": 78,
        "IN": 900,
        "BR": 180,
        "ID": 210,
        "MX": 100,
        "PH": 85,
        "NG": 100,
        "PK": 110,
        "JP": 105,
        "FR": 60,
        "RU": 130,
        "TR": 70,
        "VN": 80,
        "EG": 80,
        "BD": 65,
        "ES": 45,
        "IT": 50,
        "NL": 17,
        "SE": 10,
        "NO": 5,
        "CH": 8,
        "IE": 5,
        "NZ": 5,
        "DK": 6,
        "AT": 8,
    }
    idx = [i for i in s.index if i in w]
    if not idx:
        return None
    weighted = {c: s[c] * w[c] for c in idx}
    total = sum(weighted.values()) or 1
    tier1 = sum(v for c, v in weighted.items() if c in TIER1) / total
    top = sorted(weighted.items(), key=lambda x: -x[1])[:5]
    return {"tier1_share": round(tier1, 3), "top_countries": [c for c, _ in top]}


# ----------------------------------------------------------------------------
# 5. Trending-now matches
# ----------------------------------------------------------------------------


def trending_matches(client, niche_terms, geo="US", matcher=None):
    """
    Pull realtime trending searches and keep the ones that belong to your niches.
    Default matcher is token overlap; plug in your embedding similarity instead.
    """
    trends = client.trending_now(geo=geo)
    items = trends if isinstance(trends, list) else []

    def default_match(text):
        toks = set(text.lower().split())
        return any(len(toks & set(t.lower().split())) >= 1 for t in niche_terms)

    match = matcher or default_match
    out = []
    for t in items:
        text = t.get("keyword") or t.get("title") or str(t)
        if match(text):
            out.append(
                {
                    "keyword": text,
                    "volume": t.get("volume") or t.get("traffic"),
                    "started": t.get("started") or t.get("startTimestamp"),
                    "related": t.get("trend_keywords") or t.get("relatedQueries"),
                }
            )
    return out


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


def run(keywords, geo="", timeframe="today 5-y", gprop=None):
    client = TrendsClient()
    now = datetime.now(timezone.utc).isoformat()

    df = anchor_scaled_interest(client, keywords, timeframe=timeframe, geo=geo, gprop=gprop)
    for k in keywords:
        f = trend_features(df[k])
        g = geo_tier1_share(client, k)
        f["geo"] = g
        client.con.execute(
            "INSERT INTO trends_features VALUES (?,?,?,?,?)",
            (k, geo or "WW", timeframe, json.dumps(f), now),
        )
        print(
            f"{k:40s} level={f.get('level')} yoy={f.get('yoy')} mom={f.get('momentum_13p')} "
            f"season={f.get('season_strength')} breakout_z={f.get('breakout_z')} tier1={g and g['tier1_share']}"
        )
        for s in expand_seeds(client, k, geo=geo):
            client.con.execute(
                "INSERT INTO trends_seeds VALUES (?,?,?,?,?)",
                (s["parent"], s["kind"], s["value"], s["growth"], now),
            )
            if s["breakout"]:
                print(f"   BREAKOUT {s['kind']}: {s['value']} ({s['growth']})")
    client.con.commit()

    hits = trending_matches(client, keywords, geo=geo or "US")
    if hits:
        print("trending now in-niche:", [h["keyword"] for h in hits])


if __name__ == "__main__":
    run(sys.argv[1:] or ["aviation disasters", "plane crash investigation"])
