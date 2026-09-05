"""A half-coordinate station (latitude without longitude) must never abort the corpus build.

_mtm sets lat and lon independently, so a record with one and not the other is a legal parse
product. _group_collections once guarded only lat before appending BOTH accumulators, and
round(min(lon), 6) then raised TypeError at corpus level - after LAYER 2's per-survey withhold,
so one malformed station denied publication to the whole corpus. The three ingest guards are
pinned to require both coordinates, so the half-coordinate shape is dropped where it is born
(its siblings stations_geojson/mtcat_document/qc_pass always guarded both).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract"))
import build_portal as bp  # noqa: E402

SRC = (Path(__file__).resolve().parent.parent / "extract" / "build_portal.py").read_text(encoding="utf-8")


def _row(**kw):
    r = {"survey": "Alpha Survey", "lat": -30.0, "lon": 136.0}
    r.update(kw)
    return r


def test_group_collections_survives_a_half_coordinate_station():
    surveys_meta = {"Alpha Survey": {"slug": "alpha",
                                     "collection": {"id": "coll", "title": "Coll"}}}
    rows = [("a.edi", _row()), ("b.edi", _row(lon=None)), ("c.edi", _row(lat=None))]
    colls, _survey_coll = bp._group_collections(surveys_meta, rows)
    c = colls["coll"]
    assert c["n_stations"] == 3                       # membership counts every station
    assert c["bbox"] == {"west": 136.0, "south": -30.0, "east": 136.0, "north": -30.0}, (
        "the bbox derives from fully-located stations only, never a half coordinate: %r" % (c,))


def test_ingest_guards_require_both_coordinates():
    # The three parse arms share one graceful-degradation predicate. A lat-only record must fail
    # it (dropped at ingest, where the drop can be recorded), not flow on to crash a corpus-level
    # consumer or emit a half-null station the mtcat schema's paired rule rejects.
    guards = re.findall(r'if r\.get\("lat"\) is None[^\n]*', SRC)
    assert len(guards) >= 3, "the three ingest guards moved; re-anchor this pin: %r" % (guards,)
    for g in guards:
        assert 'r.get("lon") is None' in g, (
            "an ingest guard tests lat only; a lat-without-lon record flows through: %s" % g)
