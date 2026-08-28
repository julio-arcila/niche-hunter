"""Pick the event-stratum Wikipedia articles for each niche, reproducibly.

Run by hand; prints a Python literal to paste into `nh/seeds.py`. The *generator*
is a script because it touches the network; its *output* is hand curation and
belongs beside `SEEDS` and `TERMS`, which is where every other curated literal in
this project lives. Keeping it out of the nightly is the point — the pipeline must
not depend on a SPARQL endpoint being up.

    uv run python scripts/select_demand_articles.py [--k 20] [--seed 20260827]

**Why a fixed-K random sample and not "the biggest articles".** Ranking a pool by
pageviews and taking the top K selects for fame, which is exactly the bias that
made the hand-picked comparison in the Slice 5 planning notes untrustworthy —
Chernobyl and the Titanic would win every time and the niche's real distribution
would never show. A uniform sample is the only selector with no preference of its
own. Its error is sampling noise, which shrinks with K and can be quantified by
resampling; famous-bias cannot be quantified at all.

**Fixed K, not "everything in the pool".** `demand.wiki_weekly_views` sums over a
niche's articles and its confidence divides by article count, so a 3,202-article
niche and a 19-article one would not be comparable on either axis. Same K
everywhere makes them comparable and makes pool size a separate, visible fact.

**Two generators, and the heterogeneity is recorded rather than hidden.** Measured
2026-08-27, Wikidata class enumeration gives pools of 2,017 (aviation accident),
3,202 (US Supreme Court decision), 104 (shipwrecking) and 19 (criminal trial) — the
classes are unevenly populated, and two of six niches have no usable class at all.
Where the class pool is too thin, the script falls back to category membership, and
the generator used is emitted per niche so a later reader can see that court-cases
and maritime were not selected the same way. That difference is a confound; it is
not a reason to pretend one method fits all six.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.parse
import urllib.request

UA = "niche-hunter/0.1 (+contact@example.com) demand-article-selector"
SPARQL = "https://query.wikidata.org/sparql"
WIKI_API = "https://en.wikipedia.org/w/api.php"
#: Below this the class pool is too thin to sample from without the sample simply
#: being the pool, so the category generator is used instead.
MIN_POOL_MULTIPLE = 3

#: Per niche: Wikidata classes to try first, then categories as the fallback.
SOURCES: dict[str, dict[str, list[str]]] = {
    "aviation-disasters": {
        "classes": ["Q744913"],  # aviation accident
        "categories": ["Category:Aviation accidents and incidents by year"],
    },
    "maritime-disasters": {
        "classes": ["Q906512"],  # shipwrecking
        "categories": ["Category:Maritime incidents by year"],
    },
    "corporate-collapse": {
        "classes": ["Q4215744", "Q21996358"],  # accounting scandal, corporate scandal
        "categories": ["Category:Corporate scandals"],
    },
    "engineering-failures": {
        "classes": ["Q1309431", "Q68800046"],  # structural failure, industrial disaster
        "categories": ["Category:Building and structure collapses"],
    },
    "landmark-court-cases": {
        "classes": ["Q19692072"],  # decision of the US Supreme Court
        "categories": ["Category:United States Supreme Court cases"],
    },
    "true-crime-trials": {
        "classes": ["Q10855414"],  # criminal trial
        "categories": ["Category:Trials by country"],
    },
}


def _get(url: str, timeout: int, accept: str | None = None) -> dict:
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def _retry(fn, attempts: int = 3):
    """WDQS rate-limits and times out freely. A hand-run script can just wait."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts - 1:
                print(f"    gave up: {type(exc).__name__}", file=sys.stderr)
                return None
            time.sleep(5 * 2**attempt)
    return None


def from_classes(qids: list[str], limit: int = 4000) -> list[str] | None:
    """en.wikipedia article titles for every instance of these classes."""
    values = " ".join(f"wd:{qid}" for qid in qids)
    query = f"""SELECT DISTINCT ?name WHERE {{
      VALUES ?cls {{ {values} }} ?x wdt:P31/wdt:P279* ?cls .
      ?a schema:about ?x ; schema:isPartOf <https://en.wikipedia.org/> ;
         schema:name ?name . }} LIMIT {limit}"""
    url = f"{SPARQL}?format=json&query={urllib.parse.quote(query)}"
    payload = _retry(lambda: _get(url, 90, "application/sparql-results+json"))
    if payload is None:
        return None
    return sorted({b["name"]["value"].replace(" ", "_") for b in payload["results"]["bindings"]})


def _members(category: str, kind: str) -> list[str]:
    """One page of category members. `kind` is 'page' or 'subcat'."""
    url = (
        f"{WIKI_API}?action=query&list=categorymembers&cmtitle="
        f"{urllib.parse.quote(category)}&cmlimit=500&cmtype={kind}&format=json"
    )
    payload = _retry(lambda: _get(url, 30))
    time.sleep(0.3)
    if payload is None:
        return []
    return [m["title"] for m in payload["query"]["categorymembers"]]


def from_categories(categories: list[str], depth: int = 1) -> list[str]:
    """Article titles from these categories, walking `depth` levels of subcategories.

    Depth is capped hard and deliberately. The category graph has cycles and leaks
    upward — Aviation accidents reaches Aviation reaches Transport — so an uncapped
    walk ends up enumerating the encyclopedia. One level is enough to reach the
    by-year subcategories where the actual events live.
    """
    articles: set[str] = set()
    frontier = list(categories)
    for level in range(depth + 1):
        subcategories: list[str] = []
        for category in frontier:
            articles.update(title.replace(" ", "_") for title in _members(category, "page"))
            if level < depth:
                subcategories.extend(_members(category, "subcat"))
        frontier = subcategories
    return sorted(articles)


def pool_for(slug: str, k: int) -> tuple[list[str], str]:
    """`(candidates, generator)`. Classes when they are populated enough."""
    sources = SOURCES[slug]
    candidates = from_classes(sources["classes"]) if sources["classes"] else None
    if candidates and len(candidates) >= k * MIN_POOL_MULTIPLE:
        return candidates, "wikidata:" + ",".join(sources["classes"])
    found = len(candidates) if candidates is not None else "unavailable"
    print(f"    class pool {found} < {k * MIN_POOL_MULTIPLE}; falling back to categories")
    return from_categories(sources["categories"]), "category:" + ";".join(sources["categories"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--only", help="one slug, for iterating")
    args = parser.parse_args()

    print(f"# generated by scripts/select_demand_articles.py --k {args.k} --seed {args.seed}")
    print("# The sample is reproducible from that seed; the pool size is recorded per")
    print("# niche because it is not comparable across generators.")
    for slug in SOURCES:
        if args.only and slug != args.only:
            continue
        print(f"\n#   {slug}", file=sys.stderr)
        candidates, generator = pool_for(slug, args.k)
        if not candidates:
            print(f"    NO CANDIDATES for {slug}", file=sys.stderr)
            continue
        # Seeded per niche so adding a niche does not reshuffle the others.
        rng = random.Random(f"{args.seed}:{slug}")
        chosen = sorted(rng.sample(candidates, min(args.k, len(candidates))))
        print(f"    pool={len(candidates)} via {generator}", file=sys.stderr)
        print(f"    # {slug}: pool {len(candidates)} via {generator}")
        for title in chosen:
            print(
                f'    {{"slug": "{slug}", "source": "wikipedia", '
                f'"stratum": "event", "term": "{title}"}},'
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
