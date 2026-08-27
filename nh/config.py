"""Settings, loaded from the environment / .env.

Every credential is Optional on purpose. Importing a collector module must never
raise just because its source has not been provisioned yet — the nightly job
skips unconfigured sources and records that in `job_runs` (see
.claude/rules/data.md). This is the fix for the prototypes' module-scope
``KEY = os.environ["YT_API_KEY"]``, which made them unimportable and untestable.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_prefix="NH_",
        extra="ignore",
    )

    # --- database ----------------------------------------------------------
    database_url: str = f"sqlite:///{REPO_ROOT / 'data' / 'niche_hunter.db'}"
    sql_echo: bool = False

    # --- operations --------------------------------------------------------
    #: healthchecks.io ping URL. The job pings on success; the service alerts when
    #: a ping fails to arrive, which is the only way to detect a run that never
    #: started (machine off, stale cron line).
    healthcheck_url: str | None = None
    #: ntfy.sh topic for push alerts the job raises itself.
    ntfy_topic: str | None = None
    #: Days of bulk raw payloads (feed XML) to keep. Long enough to replay a bad
    #: parse across two weeks; short enough that storage stays bounded as the
    #: channel set grows. Snapshots are never pruned (ADR-0010).
    raw_retention_days: int = 14

    # --- youtube data api v3 ----------------------------------------------
    yt_api_key: str | None = None
    yt_quota_budget: int = 9_500  # of 10,000; 500 held back for retries
    #: search.list pages per query per sort order. This is the quota lever:
    #: cost is seeds x keywords x 2 orders x pages x 100 units. Start at 1
    #: (~3,000 units for 5 seeds x 3 keywords), raise only after measuring.
    yt_search_pages: int = 1
    #: Discovery window. Matches the prototype's days_back.
    yt_discover_days: int = 90
    #: Ceiling on the RSS-discovered videos enriched per night. At 1 unit per
    #: 50 ids, 25,000 is 500 units — enough to clear the initial backlog in one
    #: night while capping the worst case if discovery ever floods the queue.
    yt_backfill_max_ids: int = 25_000

    # --- youtube rss -------------------------------------------------------
    rss_user_agent: str = "niche-hunter-rss/0.1 (+contact@example.com)"
    rss_workers: int = 8
    rss_jitter_s: tuple[float, float] = (0.2, 0.8)

    # --- google trends -----------------------------------------------------
    trends_anchor: str = "documentary"
    trends_min_gap_s: float = 2.5
    trends_cache_ttl_h: int = 24
    trends_proxy: str | None = None

    # --- reddit ------------------------------------------------------------
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str | None = None

    # --- google ads keyword planner ---------------------------------------
    gads_customer_id: str | None = None
    gads_config: Path = Field(default=REPO_ROOT / "google-ads.yaml")
    gads_cache_days: int = 7

    def configured(self, source: str) -> bool:
        """Whether `source` has the credentials it needs to run at all."""
        required: dict[str, tuple[object, ...]] = {
            "youtube_api": (self.yt_api_key,),
            "youtube_rss": (),  # no auth
            "trends": (),  # no auth
            "reddit": (self.reddit_client_id, self.reddit_client_secret, self.reddit_user_agent),
            "keyword_planner": (self.gads_customer_id,),
        }
        return all(required.get(source, ())) if source in required else True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
