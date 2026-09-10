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
    """A on both, B on one -> two entries in first-appearance order. A: all 2.
    B: count 1, `stations=["S1"]`."""
    notes = {"S1": ["A", "B"], "S2": ["A"]}
    entries = bp.aggregate_conditioning(notes)
    assert [e["note"] for e in entries] == ["A", "B"]
    a, b = entries
    assert a["count"] == 2 and a["except"] is None
    assert b["count"] == 1 and b["stations"] == ["S1"] and b["except"] is None


def test_aggregate_ccmt_outlier_records_except_complement():
    """The ccmt-2017 shape: 28 stations, 27 share a note, and station CC07 lacks it. The small side is the
    single absentee, so the entry records except=['CC07'] (NOT stations=[27 ids]) and count=27."""
    ids = [f"CC{n:02d}" for n in range(1, 29)]  # the station ids CC01..CC28
    notes = {sid: (["shared"] if sid != "CC07" else ["outlier"]) for sid in ids}
    entries = bp.aggregate_conditioning(notes)
    shared = next(e for e in entries if e["note"] == "shared")
    assert shared["count"] == 27
    assert shared["except"] == ["CC07"], "the single absentee is the small side to enumerate"
    assert shared["stations"] is None, "27 carriers is too many to list - use the complement"
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
    panel view."""
    n = bp.CONDITIONING_ENUM_LIMIT + 2
    notes = {f"S{i}": ["A"] for i in range(n)}
    entries = bp.aggregate_conditioning(notes)
    assert len(entries) == 1
    e = entries[0]
    assert e["count"] == n
    assert e["stations"] is None, "carrier list must not be enumerated above the limit"
    assert e["except"] is None, "an all-carriers note must ship except=None, never []"


# --- the per-survey folds for the survey-level notice families -----------------------------------
# Each family folds to a bounded number of log lines and keeps its full membership in
# build_report.json, so nothing an operator could act on is lost by the fold.

def test_station_id_notes_are_class_stable_and_fold_to_one_line():
    """FAILS IF: the identity-rewrite notes embed the station's own value, which makes every station
    a DISTINCT note string and defeats the by-note aggregation (one line per station again)."""
    from ausmt_science.ingest import normalize as nz
    ids = [f"S{n:02d}" for n in range(1, 31)]
    notes = {sid: [nz.NOTE_STATION_ID_SET, nz.NOTE_SOURCE_ID_PRESERVED] for sid in ids}
    for note in (nz.NOTE_STATION_ID_SET, nz.NOTE_SOURCE_ID_PRESERVED, nz.NOTE_SOURCE_FILE_PRESERVED):
        assert "->" not in note and ":" not in note, f"{note!r} still embeds a per-station value"
    lines = bp.conditioning_log_lines("wide", notes)
    assert len(lines) == 2, f"30 stations sharing two notes must fold to two lines: {lines}"
    assert all(ln.endswith("all 30 stations") for ln in lines), lines


def test_station_id_ledger_carries_the_folded_per_station_mapping():
    """The mapping a class-stable note cannot carry in its text must be recoverable from
    build_report.json: served id, the sanitised EMTF-XML Site.id and the custodian source file,
    per rewritten station."""
    from ausmt_science.ingest import normalize as nz
    records = [
        {"id": "RD18-188e", "source_provenance": {"original_filename": "188_S__2.edi"}},
        {"id": "CLEAN01"},
        {"id": "NOTED99"},
    ]
    notes = {"RD18-188e": [nz.NOTE_STATION_ID_SET, nz.NOTE_SOURCE_FILE_PRESERVED],
             "CLEAN01": ["rotation: unknown"]}
    rows = bp.station_id_ledger(notes, records)
    assert rows == [{"station": "RD18-188e", "site_id": "RD18188e", "source_file": "188_S__2.edi"}], rows
    assert bp.station_id_ledger({}, records) == [], "no rewrite -> no ledger rows"


def test_product_failures_fold_per_producer_exception_and_message():
    """One line per (producer, exception, message prefix) with the count and ONE example file; the
    per-file rows survive in the ledger. FAILS IF: a 4,500-station build prints one line per file."""
    rows = [{"producer": "h5", "file": f"A{n:03d}.edi", "error": "ValueError",
             "message": "cannot broadcast the impedance array to the period grid",
             "context": "station product"} for n in range(40)]
    rows.append({"producer": "xml", "file": "B001.edi", "error": "KeyError",
                 "message": "'Site.id'", "context": "station product"})
    groups = bp.fold_product_failures(rows)
    lines = bp.product_failure_log_lines("wide", groups)
    assert lines == [
        "  [h5] WARN wide: ValueError: cannot broadcast the impedance array to the period "
        "grid - 40 file(s), e.g. A000.edi (station product)",
        "  [xml] WARN wide: KeyError: 'Site.id' - 1 file(s), e.g. B001.edi (station product)",
    ], lines
    led = bp.product_failures_report(rows)
    assert sorted(led) == ["h5", "xml"]
    assert len(led["h5"]) == 40 and led["h5"][0]["file"] == "A000.edi"
    assert led["h5"][0]["context"] == "station product"


def test_product_failures_message_prefix_groups_and_ledger_dedupes_the_replay():
    """Two faults whose messages differ only past the 60-char key are ONE group; and the survey
    bundle re-reading a file the station product already failed on adds no second ledger row and no
    second line (the pool replay must not duplicate)."""
    long_a = "x" * 60 + "station A"
    long_b = "x" * 60 + "station B"
    rows = [{"producer": "h5", "file": "A.edi", "error": "OSError", "message": long_a,
             "context": "station product"},
            {"producer": "h5", "file": "B.edi", "error": "OSError", "message": long_b,
             "context": "station product"}]
    assert len(bp.fold_product_failures(rows)) == 1, "same 60-char message prefix -> one group"
    replay = bp.dedupe_product_failures(rows + [
        {"producer": "h5", "file": "A.edi", "error": "OSError", "message": long_a,
         "context": "survey bundle"}])
    assert len(replay) == 2, replay
    assert replay[0]["context"] == "station product", "the FIRST occurrence context is kept"


def test_precedence_folds_to_one_line_per_survey():
    """FAILS IF: the EDI-wins precedence rule prints one line per skipped EMTF XML."""
    rows = [{"station": f"S{n:02d}", "file": f"S{n:02d}.xml"} for n in range(1, 13)]
    line = bp.precedence_log_line("mixed", rows)
    assert line == (
        "  [xml] PRECEDENCE mixed: 12 station(s) already ingested from transfer_functions/edi/ "
        "- the EDI is canonical, their EMTF XML is kept in the package but NOT ingested "
        "(S01, S02, S03, S04, S05, S06, S07, S08, +4 more)"), line
    assert bp.precedence_log_line("mixed", []) is None


def test_tipper_mask_folds_to_one_line_per_survey():
    """FAILS IF: the placeholder-tipper NOTICE prints one line per masked station. The ledger is the
    existing build_report `tipper_masked` list, so the fold adds no second record."""
    ids = [f"T{n:02d}" for n in range(1, 11)]
    line = bp.tipper_masked_log_line("phoenix", ids)
    assert line == (
        "  NOTICE phoenix: placeholder tipper (|T| flat at 1.0) masked - tipper withheld for "
        "10 station(s) (T01, T02, T03, T04, T05, T06, T07, T08, +2 more)"), line
    assert bp.tipper_masked_log_line("phoenix", []) is None


def test_coordinate_flag_notices_fold_per_survey_per_flag():
    """FAILS IF: the QC block prints one '[notice] coordinate flag ...' line per station. The full
    list stays in qc_report.json, so the folded line enumerates at most five examples."""
    flags = [{"flag": "dms_sign", "resolved": True, "file": f"a{n:02d}.edi",
              "ausmt_id": f"au.one.A{n:02d}"} for n in range(1, 9)]
    flags.append({"flag": "info_only", "resolved": False, "file": "b.edi", "ausmt_id": "au.two.B01"})
    lines = bp.coord_flag_log_lines(flags)
    assert lines == [
        "  [notice] coordinate flag 'dms_sign' (resolved) in one: 8 station(s), e.g. a01.edi "
        "(au.one.A01), a02.edi (au.one.A02), a03.edi (au.one.A03), a04.edi (au.one.A04), "
        "a05.edi (au.one.A05), +3 more",
        "  [notice] coordinate flag 'info_only' in two: 1 station(s), e.g. b.edi (au.two.B01)",
    ], lines
    assert bp.coord_flag_log_lines([]) == []


def test_station_id_ledger_covers_a_source_id_only_rewrite():
    """A station can be published under an id the EMTF-XML Site.id pattern rejects while the parsed
    Site.id already equals the sanitised form, so the only identity note it carries is the preserved
    source id. The rewrite happened all the same.

    FAILS IF: the ledger gate names only two of the three identity notes. The note text is
    class-stable, so a survey that rewrote every station would then have an EMPTY
    station_id_rewrites and the mapping would be recoverable from nowhere."""
    from ausmt_science.ingest import normalize as nz
    records = [{"id": "A-1"}, {"id": "A-2"}]
    notes = {sid: [nz.NOTE_SOURCE_ID_PRESERVED] for sid in ("A-1", "A-2")}
    rows = bp.station_id_ledger(notes, records)
    assert rows == [{"station": "A-1", "site_id": "A1"},
                    {"station": "A-2", "site_id": "A2"}], rows


def test_product_failure_count_names_distinct_files():
    """The folded line reads '<n> file(s)', so n is the count of DISTINCT files. FAILS IF: one file
    that fails twice with messages differing only past the group key is counted as two files."""
    head = "y" * bp.PRODUCT_FAILURE_KEY_CHARS
    rows = [{"producer": "h5", "file": "SAME.edi", "error": "OSError",
             "message": head + " first", "context": "station product"},
            {"producer": "h5", "file": "SAME.edi", "error": "OSError",
             "message": head + " second", "context": "station product"}]
    groups = bp.fold_product_failures(rows)
    assert len(groups) == 1, groups
    assert groups[0]["count"] == 1, groups
    assert bp.product_failure_log_lines("s", groups)[0].endswith(
        "1 file(s), e.g. SAME.edi (station product)"), groups


def test_merge_product_failures_reports_a_file_the_bundle_adds_to_a_known_group():
    """The deferred survey bundle failing on a file the station-product tier did NOT fail on is a new
    file even when its fault groups with one already printed. The merge reports the ADDED files, so
    every line accounts for a disjoint set and no printed count goes stale.

    FAILS IF: the merge reports only unseen group KEYS, which leaves the added file silent."""
    ledger = [{"producer": "h5", "file": "A.edi", "error": "ValueError", "message": "boom",
               "context": "station product"}]
    added = bp.merge_product_failures(ledger, [
        {"producer": "h5", "file": "A.edi", "error": "ValueError", "message": "boom",
         "context": "survey bundle"},
        {"producer": "h5", "file": "B.edi", "error": "ValueError", "message": "boom",
         "context": "survey bundle"}])
    assert bp.product_failure_log_lines("s", added) == [
        "  [h5] WARN s: ValueError: boom - 1 file(s), e.g. B.edi (survey bundle)"], added
    led = bp.product_failures_report(ledger)["h5"]
    assert [r["file"] for r in led] == ["A.edi", "B.edi"], led
    assert led[0]["context"] == "station product", "the first occurrence context is kept"
    assert bp.merge_product_failures(ledger, []) == [], "a drain with nothing new prints nothing"
