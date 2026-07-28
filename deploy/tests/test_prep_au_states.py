"""AU state-table prep pins (deploy/scripts/prep_au_states.py).

The prep script is the OPERATOR-side half of the Australian state breakdown: it ingests the db-ip
"IP to City Lite" CSV once a month and emits a COMPACT, AU-only `start_ip,end_ip,state_code` table for
the daily fold to bisect. The big city CSV is never kept and never enters the repo or the box's data
dir; only the small derived table does.

Different trust class from the aggregator on purpose: the aggregator is timer-driven and must NEVER
raise (it exits 0 and degrades a metric), while this script is run BY HAND and must fail LOUDLY on a
bad input rather than quietly write a table with no rows in it.

Each pin states its failure criterion (Invariant 10). Pure stdlib python + committed fixtures -- runs
everywhere (no network, no db-ip download), so it never trips the CI skip tripwire.
"""
from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "prep_au_states.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_CITY = _FIXTURES / "dbip-city-lite.sample.csv"
_EXPECTED_TABLE = _FIXTURES / "dbip-au-states.sample.csv"


def _load_prep():
    spec = importlib.util.spec_from_file_location("prep_au_states", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


PREP = _load_prep()


def _data_rows(text: str) -> list[str]:
    """The emitted table's DATA lines (comment/blank lines stripped)."""
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


# --------------------------------------------------------------------------------------------------
# The emitted table: AU only, state codes only, sorted, adjacency-merged.
# --------------------------------------------------------------------------------------------------
def test_prep_emits_au_only_state_ranges_sorted_and_merged(tmp_path):
    """PREP PIN. Over a fixture slice of the db-ip City Lite CSV the script must emit exactly the AU
    rows, mapped to the eight state/territory codes, sorted by range start (v4 then v6) and with
    ADJACENT ranges of the SAME state coalesced into one. FAILS IF a non-AU row survives, if an AU row
    is dropped, if two adjacent same-state ranges are not merged, if two adjacent DIFFERENT-state
    ranges are wrongly merged, or if the output is not sorted."""
    out = tmp_path / "dbip-au-states.csv"
    rc = PREP.main([str(_CITY), "--out", str(out)])
    assert rc == 0, "a well-formed City Lite slice must prep cleanly"
    rows = _data_rows(out.read_text(encoding="utf-8"))
    assert rows == [
        "1.0.0.0,1.0.0.255,QLD",
        "192.0.2.0,192.0.2.255,VIC",          # Melbourne + Geelong: adjacent, same state -> merged
        "203.0.113.0,203.0.113.255,NSW",      # Newcastle listed BEFORE Sydney in the source -> sorted
        "210.10.0.0,210.10.0.255,SA",         # adjacent to the WA range below and NOT merged with it
        "210.10.1.0,210.10.1.255,WA",
        "210.10.2.0,210.10.2.255,TAS",        # the 'AU-TAS' ISO-subdivision spelling normalises
        "2400:cb00::,2400:cb00:ffff:ffff:ffff:ffff:ffff:ffff,WA",
    ], rows
    # Non-AU rows (CN, US, DE) never appear, and neither does an AU row with no state at all.
    body = out.read_text(encoding="utf-8")
    for absent in ("Fuzhou", "San Jose", "Berlin", "100.64.0.0", "119.3061"):
        assert absent not in body, f"the compact table must not carry {absent!r}"


def test_prep_output_matches_the_committed_fold_fixture(tmp_path):
    """FIXTURE-AGREEMENT PIN. The table the fold's tests bisect must be exactly what this script
    produces from the committed City Lite slice -- otherwise the fold pins would be testing a shape the
    operator chore never emits. FAILS IF the two drift apart."""
    out = tmp_path / "t.csv"
    assert PREP.main([str(_CITY), "--out", str(out)]) == 0
    assert _data_rows(out.read_text(encoding="utf-8")) == \
        _data_rows(_EXPECTED_TABLE.read_text(encoding="utf-8"))


def test_prep_drops_labels_that_are_not_one_of_the_eight_states(tmp_path):
    """VOCABULARY PIN. Only the eight state/territory codes may reach the table. A stateprov label that
    is NOT one of them (an external territory, a db-ip oddity, an empty field) is DROPPED -- never
    guessed at, never passed through verbatim -- so it lands in the fold's honest 'unattributed' bucket
    instead of inventing a ninth state. FAILS IF an unknown label is emitted or coerced to a state."""
    assert PREP.au_state_code("New South Wales") == "NSW"
    assert PREP.au_state_code("  queensland ") == "QLD"
    assert PREP.au_state_code("AU-WA") == "WA"
    assert PREP.au_state_code("Australian Capital Territory") == "ACT"
    for junk in ("", "   ", "Jervis Bay Territory", "Antarctica", "Auckland", "Norfolk Island", None):
        assert PREP.au_state_code(junk) is None, f"{junk!r} must not resolve to a state"
    # And end to end: the fixture's Jervis Bay row must not appear in the emitted table.
    out = tmp_path / "t.csv"
    assert PREP.main([str(_CITY), "--out", str(out)]) == 0
    assert "210.10.3.0" not in out.read_text(encoding="utf-8")


def test_prep_reads_a_gzipped_city_csv(tmp_path):
    """GZIP PIN. db-ip ships the City Lite CSV gzipped and it is large; the operator must not have to
    decompress it first. FAILS IF a .csv.gz input is not read transparently."""
    gz = tmp_path / "dbip-city-lite.csv.gz"
    gz.write_bytes(gzip.compress(_CITY.read_bytes()))
    out = tmp_path / "t.csv"
    assert PREP.main([str(gz), "--out", str(out)]) == 0
    assert _data_rows(out.read_text(encoding="utf-8")) == \
        _data_rows(_EXPECTED_TABLE.read_text(encoding="utf-8"))


def test_prep_output_carries_the_ccby_attribution_header(tmp_path):
    """ATTRIBUTION PIN. db-ip Lite data is CC-BY-4.0, so the DERIVED table must carry the attribution
    with it -- the file outlives the terminal it was generated in. FAILS IF the header loses the
    db-ip credit, the licence, or the column contract."""
    out = tmp_path / "t.csv"
    assert PREP.main([str(_CITY), "--out", str(out)]) == 0
    head = out.read_text(encoding="utf-8")
    assert "DB-IP" in head or "db-ip" in head
    assert "CC-BY-4.0" in head and "https://db-ip.com" in head
    assert "start_ip,end_ip,state_code" in head
    assert "IP to City Lite" in head


def test_prep_fails_loudly_on_a_useless_input(tmp_path, capsys):
    """LOUD-FAILURE PIN. This is a hand-run operator chore, NOT the timer job: a missing file, or a CSV
    with no AU rows in it at all (the wrong dataset, or a column layout that moved), must exit NON-ZERO
    and write NO table, rather than silently leaving a zero-row file that would degrade the whole state
    breakdown to 'unattributed' with no explanation. FAILS IF either case returns 0 or writes a file."""
    out = tmp_path / "never.csv"
    assert PREP.main([str(tmp_path / "does-not-exist.csv"), "--out", str(out)]) != 0
    assert not out.exists(), "a failed prep must not leave a table behind"

    no_au = tmp_path / "no-au.csv"
    no_au.write_text("1.0.1.0,1.0.1.255,AS,CN,Fujian,Fuzhou,26.0614,119.3061\n", encoding="utf-8")
    assert PREP.main([str(no_au), "--out", str(out)]) != 0
    assert not out.exists()
    assert "AU" in capsys.readouterr().err, "the failure must name what it was looking for"


def test_prep_writes_atomically_and_leaves_no_tmp(tmp_path):
    """ATOMIC-WRITE PIN. The table is read by the daily fold; a half-written file must never be
    visible under its final name, and no .tmp debris may be left in the geoip dir. FAILS IF the
    write is not tmp->replace or a temp file survives."""
    out = tmp_path / "geo" / "dbip-au-states.csv"
    out.parent.mkdir()
    assert PREP.main([str(_CITY), "--out", str(out)]) == 0
    assert out.is_file()
    assert [p.name for p in out.parent.iterdir()] == [out.name], \
        "no temporary file may survive the prep"


def test_prep_is_deterministic(tmp_path):
    """DETERMINISM PIN. Two runs over the same input must produce the same DATA rows, so an operator can
    diff a refreshed table against the old one and see only real geolocation drift. FAILS IF row order
    or merging depends on dict/iteration order."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    assert PREP.main([str(_CITY), "--out", str(a)]) == 0
    assert PREP.main([str(_CITY), "--out", str(b)]) == 0
    assert _data_rows(a.read_text(encoding="utf-8")) == _data_rows(b.read_text(encoding="utf-8"))
