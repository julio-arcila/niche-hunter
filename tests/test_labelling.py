"""The blind sample and the labels it produces."""

from __future__ import annotations

import json

import sqlalchemy as sa

from nh.db.models import RelevanceLabel
from nh.db.session import session_scope
from nh.jobs.labelling import export_sample, import_labels, stratified_sample
from tests.conftest_features import CLUSTER, add_channel, make_cluster


def _world(engine):
    make_cluster(engine)
    add_channel(engine, "UCa", videos=8)
    add_channel(engine, "UCb", videos=8)


def test_the_sample_never_carries_a_score(engine):
    """Thresholds are chosen against these labels, so seeing the scorer's opinion
    first would make the measurement circular."""
    _world(engine)
    rows = stratified_sample(engine, 5, seed=1)
    assert rows
    for row in rows:
        assert "relevance" not in row and "score" not in row
        assert row["label"] is None


def test_the_niche_is_shown_because_the_question_needs_it(engine):
    """ "Is this about the niche" is unanswerable with the niche hidden. What is
    blind here is the scorer's output, not the question."""
    _world(engine)
    assert all(row["niche"] for row in stratified_sample(engine, 5, seed=1))


def test_the_same_seed_reproduces_the_same_sample(engine):
    _world(engine)
    assert stratified_sample(engine, 5, seed=7) == stratified_sample(engine, 5, seed=7)


def test_a_different_seed_gives_a_different_sample(engine):
    _world(engine)
    assert stratified_sample(engine, 5, seed=7) != stratified_sample(engine, 5, seed=8)


def test_it_never_asks_for_more_than_the_cluster_holds(engine):
    _world(engine)
    assert len(stratified_sample(engine, 500, seed=1)) == 16


def test_export_then_import_round_trips(engine, tmp_path):
    _world(engine)
    path = tmp_path / "sample.jsonl"
    export_sample(path, engine, per_cluster=4, seed=1)

    labelled = []
    for i, line in enumerate(path.read_text().splitlines()):
        record = json.loads(line)
        record["label"] = i % 2 == 0
        labelled.append(json.dumps(record))
    path.write_text("\n".join(labelled))

    assert import_labels(path, engine, labeller="tester") == 4
    with session_scope(engine) as s:
        rows = s.execute(sa.select(RelevanceLabel.label, RelevanceLabel.cluster_id)).all()
    assert len(rows) == 4
    assert {r.cluster_id for r in rows} == {CLUSTER}
    assert sum(1 for r in rows if r.label) == 2


def test_a_null_label_is_a_skip_not_a_false(engine, tmp_path):
    """No third state is stored: a judgement that cannot be made is left unwritten
    rather than recorded as something every later calculation must interpret."""
    _world(engine)
    path = tmp_path / "sample.jsonl"
    export_sample(path, engine, per_cluster=4, seed=1)

    assert import_labels(path, engine, labeller="tester") == 0
    with session_scope(engine) as s:
        assert s.scalar(sa.select(sa.func.count()).select_from(RelevanceLabel)) == 0


def test_reimporting_a_correction_overwrites(engine, tmp_path):
    _world(engine)
    path = tmp_path / "sample.jsonl"
    export_sample(path, engine, per_cluster=1, seed=1)
    record = json.loads(path.read_text().splitlines()[0])

    path.write_text(json.dumps(record | {"label": True}))
    import_labels(path, engine, labeller="first")
    path.write_text(json.dumps(record | {"label": False}))
    import_labels(path, engine, labeller="second")

    with session_scope(engine) as s:
        row = s.execute(sa.select(RelevanceLabel.label, RelevanceLabel.labeller)).one()
    assert row == (False, "second")
