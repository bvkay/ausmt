"""The projection seam, pinned: existence and route detail part ways, and level2 opens nothing.

These are the rules a leak or a wrong claim would have to get past, so every fixture is the
adversarial case, not the happy path.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "extract"))

from _tsproject import route_rows, station_flag, survey_counts  # noqa: E402


def _row(level="raw_packed", review="verified", **over):
    r = {"level": level, "review": review, "url_path": f"my80/x/{level}/S1.zip", "bytes": 42}
    r.update(over)
    return r


def test_the_flag_follows_the_register_for_a_withheld_station():
    rows = [_row()]
    assert station_flag(rows) is True
    # ...while the route detail is EMPTY for the same station: existence survives withholding,
    # the route does not (R13 vs R5, the sharpest seam in the lane)
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
    assert rows[0]["review"] == "verified"  # non-vacuity: the row would project but for D19
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
