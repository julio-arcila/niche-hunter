"""`nh cluster inspect` — making a relevance decision readable.

Production criterion 5: every displayed number reaches its input rows. For
`supply.*` that path now runs through a relevance decision, so the decision has to
be inspectable, not just stored.
"""

from __future__ import annotations

import sqlalchemy as sa

from nh.clustering.inspect import inspect_cluster
from nh.db.models import Cluster, ClusterMember, Video
from nh.db.session import session_scope
from nh.db.types import utcnow

CLUSTER = "aviation-disasters"


def _world(engine):
    with session_scope(engine) as s:
        s.add(Cluster(cluster_id=CLUSTER, label="Aviation", source="clustering", run_id="t"))
        rows = [
            ("keep_hi", "Plane crashed on the runway", 0.90, False),
            ("keep_lo", "Runway crash report", 0.56, False),
            ("band_hi", "A crash somewhere", 0.54, False),
            ("band_lo", "Something about a plane", 0.10, False),
            ("noise", "Maruti Vitara review", 0.0, True),
            ("unscorable", "क्या पंखा", None, False),
        ]
        for vid, title, relevance, noise in rows:
            s.add(
                Video(
                    video_id=vid,
                    channel_id="UCa",
                    title=title,
                    source="test",
                    run_id="t",
                    at=utcnow(),
                )
            )
            s.add(
                ClusterMember(
                    cluster_id=CLUSTER,
                    item_type="video",
                    item_id=vid,
                    relevance=relevance,
                    is_noise=noise,
                    detail={"matched": ["crash"]},
                    source="clustering",
                    run_id="t",
                )
            )


def test_it_returns_none_for_a_cluster_that_does_not_exist(engine):
    with session_scope(engine) as s:
        assert inspect_cluster(s, "no-such-cluster") is None


def test_the_bands_partition_the_cluster(engine):
    """Every video is in exactly one band, so the shares are readable as shares."""
    _world(engine)
    with session_scope(engine) as s:
        view = inspect_cluster(s, CLUSTER)
    assert view.total == 6
    assert sum(count for _, count in view.bands) == view.total
    assert dict(view.bands) == {"on-niche": 2, "undecided": 2, "noise": 1, "unscorable": 1}


def test_the_weakest_kept_comes_first(engine):
    """The point of the list: the rows nearest the threshold are where the rule is
    doing its least confident work."""
    _world(engine)
    with session_scope(engine) as s:
        view = inspect_cluster(s, CLUSTER)
    assert [row.relevance for row in view.weakest_kept] == [0.56, 0.90]


def test_the_strongest_dropped_comes_first(engine):
    _world(engine)
    with session_scope(engine) as s:
        view = inspect_cluster(s, CLUSTER)
    assert [row.relevance for row in view.strongest_dropped] == [0.54, 0.10]


def test_noise_and_unscorable_are_not_shown_as_dropped_near_the_edge(engine):
    """They are decided, not marginal — mixing them in would hide the actual edge."""
    _world(engine)
    with session_scope(engine) as s:
        view = inspect_cluster(s, CLUSTER)
    assert all(row.relevance > 0 for row in view.strongest_dropped)


def test_it_reports_retirement(engine):
    _world(engine)
    with session_scope(engine) as s:
        s.execute(sa.update(Cluster).where(Cluster.cluster_id == CLUSTER).values(active=False))
        s.commit()
        assert inspect_cluster(s, CLUSTER).active is False
