from __future__ import annotations

import pytest

from nh.collectors.registry import REGISTRY, iter_specs
from nh.jobs.nightly import plan


def test_every_prototype_has_a_port_target():
    """Wikipedia is excluded: it is new in Slice 3 with no legacy prototype behind
    it, which the spec records explicitly rather than leaving blank."""
    prototypes = {spec.prototype for spec in REGISTRY if "legacy/" in spec.prototype}
    assert prototypes == {
        "legacy/niche_hunter_rss.py",
        "legacy/niche_hunter_yt.py",
        "legacy/niche_hunter_trends.py",
        "legacy/niche_hunter_reddit.py",
        "legacy/niche_hunter_kp.py",
    }


def test_a_source_without_a_prototype_says_so():
    spec = next(s for s in REGISTRY if s.source == "wikipedia")
    assert "none" in spec.prototype.lower()


def test_discovery_runs_before_rss():
    """Only youtube_api can produce a channel list, so RSS-first would make day 1
    a no-op and delay every new channel's first velocity reading by a day (ADR-0007)."""
    order = [s.source for s in REGISTRY]
    assert order.index("youtube_api") < order.index("youtube_rss")


def test_only_filters_and_rejects_typos():
    assert [s.source for s in iter_specs(["trends"])] == ["trends"]
    with pytest.raises(KeyError, match="tredns"):
        list(iter_specs(["tredns"]))


def test_plan_explains_why_each_source_is_or_is_not_running(settings):
    items = {p.spec.source: p for p in plan(settings=settings)}
    assert not items["reddit"].will_run
    assert "not ported" in items["reddit"].reason
    # ported, and the settings fixture supplies a key
    assert items["youtube_api"].will_run
    assert items["youtube_rss"].will_run


def test_an_unconfigured_ported_source_is_reported_as_such(settings):
    settings.yt_api_key = None
    items = {p.spec.source: p for p in plan(settings=settings)}
    assert not items["youtube_api"].will_run
    assert "credentials" in items["youtube_api"].reason


def test_every_registered_metric_has_a_name_matching_what_it_emits():
    """`nh/jobs/niche.py` orders its output by `fn.__name__`, so a metric whose
    callable has no name — a `functools.partial`, say — breaks `nh niche show`
    while the features layer stays perfectly happy. That coupling is easy to
    re-introduce and invisible from where it is introduced."""
    from nh.features.run import METRICS

    for metric in METRICS:
        assert getattr(metric, "__name__", None), f"{metric!r} has no __name__"
    names = [m.__name__ for m in METRICS]
    assert len(names) == len(set(names)), "two metrics share a __name__"
