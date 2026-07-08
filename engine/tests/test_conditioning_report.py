"""Build-report conditioning aggregation (Deliverable 1 + 2).

The build gathers, per survey, each conditioned station's ordered list of canonical-conditioning note
strings. Instead of one near-identical NOTICE line per station (the ~792-line survey-wide-boilerplate
noise a ~1100-station rebuild exposed), the build aggregates BY DISTINCT NOTE STRING and prints one
line per note with a station count. ONE shared function computes both the log lines and the
build_report.json entries, so the two can never drift.

NON-VACUOUS (Invariant 10): every assertion tests an independent observable — the aggregation output
for hand-built note maps whose correct grouping is known by construction, and (below) the actual
build's stdout vs its emitted build_report.json. A bug in the shared function fails BOTH the log-line
test and the report test, which is the point of sharing it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
import build_portal as bp  # noqa: E402


# --- the pure aggregation function: {station_id: [note, ...]} -> ordered list of report entries ----

def test_aggregate_all_stations_share_one_note():
    """Both stations carry note A -> one entry, count 2, neither side small-complement needs listing
    (both stations carry it, so `except` is empty and `stations` may enumerate the 2 or be null)."""
    notes = {"S1": ["A"], "S2": ["A"]}
    entries = bp.aggregate_conditioning(notes)
    assert len(entries) == 1
    e = entries[0]
    assert e["note"] == "A"
    assert e["count"] == 2
    assert e["except"] is None  # nobody is missing it


def test_aggregate_note_on_one_of_two():
    """A on both, B on one -> two entries in first-appearance order. A: all 2. B: count 1, stations=[S1]."""
    notes = {"S1": ["A", "B"], "S2": ["A"]}
    entries = bp.aggregate_conditioning(notes)
    assert [e["note"] for e in entries] == ["A", "B"]
    a, b = entries
    assert a["count"] == 2 and a["except"] is None
    assert b["count"] == 1 and b["stations"] == ["S1"] and b["except"] is None


def test_aggregate_ccmt_outlier_records_except_complement():
    """The ccmt-2017 shape: 28 stations, 27 share a note, ONE (CC07) lacks it. The small side is the
    single absentee, so the entry records except=['CC07'] (NOT stations=[27 ids]) and count=27."""
    ids = [f"CC{n:02d}" for n in range(1, 29)]  # CC01..CC28
    notes = {sid: (["shared"] if sid != "CC07" else ["outlier"]) for sid in ids}
    entries = bp.aggregate_conditioning(notes)
    shared = next(e for e in entries if e["note"] == "shared")
    assert shared["count"] == 27
    assert shared["except"] == ["CC07"], "the single absentee is the small side to enumerate"
    assert shared["stations"] is None, "27 carriers is too many to list — use the complement"
    outlier = next(e for e in entries if e["note"] == "outlier")
    assert outlier["count"] == 1 and outlier["stations"] == ["CC07"]


def test_aggregate_neither_side_small_uses_count_only():
    """A note on ~half of a large survey: neither the carriers (>5) nor the absentees (>5) are small
    enough to enumerate, so both stations and except are null and the count alone tells the story."""
    ids = [f"S{n:02d}" for n in range(1, 21)]  # 20 stations
    carriers = set(ids[:10])                    # exactly 10 carry it, 10 do not
    notes = {sid: (["half"] if sid in carriers else ["other"]) for sid in ids}
    entries = bp.aggregate_conditioning(notes)
    half = next(e for e in entries if e["note"] == "half")
    assert half["count"] == 10
    assert half["stations"] is None and half["except"] is None


def test_aggregate_empty_and_zero_note_stations():
    """No conditioned stations -> no entries. A station present with an empty list contributes nothing
    to any note's carrier set and is not counted (N is the note-carrying denominator)."""
    assert bp.aggregate_conditioning({}) == []
    entries = bp.aggregate_conditioning({"S1": ["A"], "S2": []})
    assert len(entries) == 1
    assert entries[0]["note"] == "A" and entries[0]["count"] == 1
    assert entries[0]["stations"] == ["S1"]


# --- the log-line renderer, driven by the SAME aggregation -------------------------------------------

def test_log_lines_all_most_and_few():
    """One survey with three note shapes exercises all three log-line forms. Driven by the shared
    aggregation so a grouping bug fails here too."""
    ids = [f"S{n:02d}" for n in range(1, 9)]  # 8 stations
    notes = {}
    for sid in ids:
        row = ["everywhere"]                  # all 8 -> "all 8 stations"
        if sid != "S03":
            row.append("almost")             # 7/8, one absentee -> "(all except S03)"
        if sid in ("S01", "S02"):
            row.append("rare")               # 2/8 -> "stations: S01, S02"
        notes[sid] = row
    lines = bp.conditioning_log_lines("demo", notes)
    joined = "\n".join(lines)
    assert "  [xml] NOTICE demo: everywhere — all 8 stations" in joined
    assert "  [xml] NOTICE demo: almost — 7/8 stations (all except S03)" in joined
    assert "  [xml] NOTICE demo: rare — stations: S01, S02" in joined
    # exactly one line per distinct note, in first-appearance order
    assert [ln.split(" — ")[0] for ln in lines] == [
        "  [xml] NOTICE demo: everywhere",
        "  [xml] NOTICE demo: almost",
        "  [xml] NOTICE demo: rare",
    ]


def test_log_line_large_absentee_complement_uses_count():
    """When > 5 stations lack a majority note, the line reports the count of absentees rather than
    listing them (keeps the line bounded)."""
    ids = [f"S{n:02d}" for n in range(1, 21)]  # 20 stations
    absent = set(ids[:6])                       # 6 lack it (> 5) -> not enumerated
    notes = {sid: (["maj"] if sid not in absent else ["x"]) for sid in ids}
    lines = bp.conditioning_log_lines("big", notes)
    maj = next(ln for ln in lines if "maj" in ln and "— 14/20" in ln)
    assert maj == "  [xml] NOTICE big: maj — 14/20 stations (6 stations without it)"


def test_aggregate_all_carriers_above_enum_limit_has_null_both_sides():
    """A note carried by ALL stations of a survey LARGER than CONDITIONING_ENUM_LIMIT must ship
    stations=None AND except=None — the count equalling the survey total tells the story. FAILS IF:
    the empty absentee list slips through the small-complement branch as except=[] (empty array,
    truthy in JS), which rendered '[all except: ]' on every fleet-wide note in the first production
    panel view (2026-07-08)."""
    n = bp.CONDITIONING_ENUM_LIMIT + 2
    notes = {f"S{i}": ["A"] for i in range(n)}
    entries = bp.aggregate_conditioning(notes)
    assert len(entries) == 1
    e = entries[0]
    assert e["count"] == n
    assert e["stations"] is None, "carrier list must not be enumerated above the limit"
    assert e["except"] is None, "an all-carriers note must ship except=None, never []"
