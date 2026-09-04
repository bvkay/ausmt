"""The projection seam, pinned: existence and route detail part ways, and level2 opens nothing.

These are the rules a leak or a wrong claim has to get past, so every fixture is the
adversarial case, not the happy path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract"))

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _tsproject import NEVER_PROJECTS, route_rows, station_flag, survey_counts  # noqa: E402


def _row(level="raw_packed", review="verified", **over):
    r = {"level": level, "review": review, "url_path": f"my80/x/{level}/S1.zip", "bytes": 42}
    r.update(over)
    return r


def test_the_flag_follows_the_register_for_a_withheld_station():
    rows = [_row()]
    assert station_flag(rows) is True
    # ...while the route detail is EMPTY for the same station: existence survives withholding,
    # the route does not (the sharpest seam in the workflow)
    assert route_rows(rows, station_open=False) == {}


def test_pending_and_retired_rows_project_nothing():
    assert station_flag([_row(review="pending")]) is False
    assert station_flag([_row(review="retired")]) is False
    assert route_rows([_row(review="pending"), _row(review="retired", level="level0")],
                      station_open=True) == {}


def test_retiring_the_last_verified_row_takes_the_flag_down():
    live = [_row()]
    assert station_flag(live)
    assert not station_flag([_row(review="retired")])  # the one lawful way down


def test_a_verified_level2_row_is_evidence_but_never_a_claim():
    rows = [_row(level="level2")]
    assert rows[0]["review"] == "verified"  # non-vacuity: only the LEVEL keeps this row out
    assert station_flag(rows) is False
    assert route_rows(rows, station_open=True) == {}


def test_route_rows_carry_url_path_and_bytes_per_live_level():
    rows = [_row(), _row(level="level1_mth5", bytes=None), _row(level="level2")]
    out = route_rows(rows, station_open=True)
    assert set(out) == {"raw_packed", "level1_mth5"}
    assert out["raw_packed"] == {"url_path": "my80/x/raw_packed/S1.zip", "bytes": 42}
    assert out["level1_mth5"] == {"url_path": "my80/x/level1_mth5/S1.zip"}  # no null bytes member


def test_survey_counts_omit_zero_and_are_access_blind():
    flags = {"a": [True, False, True], "b": [False], "c": []}
    assert survey_counts(flags) == {"a": 2}  # b and c ABSENT, never 0


def test_route_rows_and_the_resource_table_admit_THE_SAME_LEVELS():
    """The two renderings of the register must not part company over vocabulary. `route_rows` names
    what NEVER projects and the resource table names what DOES, so a token added to the register's
    closed set would otherwise become a route with no resource row beside it: the emitter iterates
    its own table and would skip it, while this predicate would let it through. Pinned across all
    three, from the register's vocabulary outwards, so a sixth token fails HERE and not in the
    key-set parity a deploy runs."""
    import _tsindex  # noqa: PLC0415
    import build_portal as bp  # noqa: PLC0415
    routable = set(_tsindex.LEVELS) - set(NEVER_PROJECTS)
    assert routable == set(bp._TS_LEVEL_ROUTE), sorted(routable ^ set(bp._TS_LEVEL_ROUTE))
    # THE FOURTH RENDERING, and the one Python cannot reach: the portal's chooser, drawer rows and
    # hand-off pointer file all map over state.js TS_LEVELS. It re-DECLARES this vocabulary rather
    # than deriving it, so a sixth token would publish in ts_access.json, route at the front door,
    # and be silently invisible in the UI. The shared vector file is where the two sides meet - the
    # same file that holds the encoder mirror, because the level IS a segment of the same address -
    # and portal/tests/ts_url_vectors.test.js reds on the JS side of the same line.
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    shared = json.loads((Path(__file__).resolve().parent / "fixtures" / "ts_url_vectors.json")
                        .read_text(encoding="utf-8"))["routable_levels"]
    assert set(shared) == routable, sorted(set(shared) ^ routable)
    assert list(shared) == [lvl for lvl in bp._TS_LEVEL_ROUTE if lvl in set(shared)], (
        "the shared file is IN RENDER ORDER and the emitter iterates its own table in that order; "
        "a reordering that touches only one of them reds here")


def _emitter_row():
    return {"level": "raw_packed", "url_path": "my80/x/raw_packed/S1.zip", "bytes": 42,
            "verified": "2026-08-24", "review": "verified"}


def test_the_resource_emitter_ASKS_the_projection_rather_than_restating_it(monkeypatch):
    """ONE implementation, not two that happen to agree.

    The vocabulary pin above forbids the LEVEL SETS from diverging; it cannot see the other half,
    which is the publication predicate itself. While the emitter restated `review == verified`, a
    change to which review states publish had to be made in two places, and a workflow that made it in
    one would still pass every vocabulary check in this file. So the emitter is driven here by
    REPLACING the projection's answer: a row the projection declines emits nothing, however the
    register reads.

    The control above the patch is what makes this non-vacuous: with the real predicate the SAME row
    does emit, so an empty result cannot come from an empty fixture."""
    import _tsproject as tsproject  # noqa: PLC0415
    import build_portal as bp  # noqa: PLC0415
    rows = [_emitter_row()]
    assert [r["id"] for r in bp.station_time_series_resources(rows, [])] == ["ts-raw_packed"]
    monkeypatch.setattr(tsproject, "projects", lambda row: False)
    assert bp.station_time_series_resources(rows, []) == []


def test_the_resource_row_ASKS_the_one_encoder_rather_than_restating_it(monkeypatch):
    """The same rule for the other half of a published route. Three surfaces render an NCI address
    from one `url_path` and only one of them may be the implementation: `_stationcheck` holds it, the
    front-door generator calls it, and the JS mirror is held to its bytes by a shared vector file.
    A second `quote` in the emitter is what would let station.json publish a working route beside
    a dead one in the redirect table."""
    import _stationcheck as stcheck  # noqa: PLC0415
    import build_portal as bp  # noqa: PLC0415
    rows = [_emitter_row()]
    real = bp.station_time_series_resources(rows, [])[0]["access_url"]
    assert real == stcheck.ts_access_url(rows[0]["url_path"])   # control: it agrees today
    monkeypatch.setattr(stcheck, "ts_access_url", lambda p: "https://example.invalid/SENTINEL",
                        raising=False)
    assert bp.station_time_series_resources(rows, [])[0]["access_url"] == \
        "https://example.invalid/SENTINEL"
