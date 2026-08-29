"""Check that google-ads.yaml works, and what access level it actually has.

    uv run python scripts/gads_check.py

Prints diagnosis only, never a credential. It answers three questions in order, and
stops at the first failure, because each one makes the next meaningless:

  1. Do the four credentials authenticate at all?
  2. Does the developer token reach a PLANNING service? A freshly issued token has
     Explorer access, which explicitly excludes Keyword Planner -- so this can fail
     even when authentication succeeds, and that failure is the expected one until
     Basic access is granted.
  3. Do volumes come back NUMERIC or as power-of-ten buckets? This is the open
     question from reports/source_audit_2026-08-28.md: practitioner reports disagree
     about whether a zero-spend account still gets ranges, and it decides whether
     the API upgrade delivers one benefit or four.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "google-ads.yaml"
#: Three keywords whose US volumes we already hold from the CSV export, so a
#: mismatch is visible immediately. Their stored values are bucket MIDPOINTS
#: (500000, 50000, 5000) -- if the API returns those exact numbers it is bucketing
#: too; anything else is a real count.
PROBES = ("inflation", "day trading", "biohacking")


def main() -> int:
    if not CONFIG.exists():
        print(f"missing {CONFIG.name}")
        return 1
    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    missing = [
        k
        for k in (
            "developer_token",
            "client_id",
            "client_secret",
            "refresh_token",
            "login_customer_id",
        )
        if not str(cfg.get(k) or "").strip()
    ]
    if missing:
        print("google-ads.yaml is missing:", ", ".join(missing))
        return 1
    print("all five fields present (values not read)\n")

    import pkgutil

    import google.ads.googleads as _pkg
    from google.ads.googleads.client import GoogleAdsClient
    from google.ads.googleads.errors import GoogleAdsException

    # Newest bundled version, not a hardcoded one. v21 was pinned first and returned
    # 501 "GRPC target method can't be resolved" -- the method exists in the library
    # but the version is sunset server-side, and Google retires roughly one version a
    # quarter. Picking the newest at runtime makes that a non-event.
    versions = sorted(
        (m.name for m in pkgutil.iter_modules(_pkg.__path__) if m.name.startswith("v")),
        key=lambda v: int(v[1:]),
    )
    api_version = versions[-1]
    print(f"   using API {api_version} (bundled: {', '.join(versions)})")

    try:
        client = GoogleAdsClient.load_from_storage(str(CONFIG), version=api_version)
    except Exception as exc:  # a config boundary: report, never raise into the CLI
        print(f"1. authenticate: FAILED — {type(exc).__name__}: {str(exc)[:200]}")
        return 1
    print("1. authenticate: client built")

    customer_id = str(cfg["login_customer_id"]).replace("-", "")
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = customer_id
    req.keywords.extend(PROBES)
    req.geo_target_constants.append("geoTargetConstants/2840")  # United States
    req.language = "languageConstants/1000"  # English

    try:
        resp = svc.generate_keyword_historical_metrics(request=req)
    except GoogleAdsException as exc:
        errs = "; ".join(e.message for e in exc.failure.errors)[:300]
        print(f"2. planning service: DENIED — {errs}")
        print("\n   If this says the developer token has insufficient access, that is")
        print("   the EXPECTED state before Basic access is granted. Explorer access")
        print("   excludes every planning service, Keyword Planner included.")
        return 1
    except Exception as exc:  # same boundary
        print(f"2. planning service: FAILED — {type(exc).__name__}: {str(exc)[:200]}")
        return 1
    print("2. planning service: reachable\n")

    print("3. volumes returned:")
    buckets = {50, 500, 5000, 50000, 500000, 5000000}
    seen = []
    for r in resp.results:
        vol = r.keyword_metrics.avg_monthly_searches
        seen.append(vol)
        flag = "bucket midpoint" if vol in buckets else "NUMERIC"
        print(f"     {r.text:20} {vol:>12,}   {flag}")
    if seen and all(v in buckets for v in seen):
        print("\n   Every value is a power-of-ten midpoint: the API is bucketing too,")
        print("   so the upgrade buys the monthly columns and multi-geo, not precision.")
    elif seen:
        print("\n   Numeric volumes: the bucketing was a CSV-export artifact, and the")
        print("   ranking instability traced to it in reports/geo_value_2026-08-28.md")
        print("   can be re-measured on real numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
