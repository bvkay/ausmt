"""The skip tripwire's own pins: the accounting must count SKIPS, not lines.

pytest -rs aggregates identical (location, reason) skips into ONE line carrying a multiplicity,
"SKIPPED [2] path:line: reason". Two tests skipping through one shared helper (the D3.1 validator
seam was the first) produce exactly that shape, and a parser that counts lines undercounts it -
the PR #164 red, caught by the tripwire's own cross-check against pytest's summary
total. These pins keep both halves honest: multiplicities are summed, and the cross-check still
fails loudly on formats the parser cannot see.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_check_skips as ccs  # noqa: E402

ALLOWED = "engine image build: gateway tree not shipped"


def _run(monkeypatch, report, allow=ALLOWED):
    monkeypatch.setattr(sys, "stdin", io.StringIO(report))
    return ccs.main(["--allow", allow])


def test_an_aggregated_multiplicity_counts_as_that_many_skips(monkeypatch):
    report = (f"SKIPPED [2] tests/test_validator_gate.py:66: {ALLOWED} (designed topology)\n"
              f"SKIPPED [1] tests/test_validator_gate.py:90: {ALLOWED} (designed topology)\n"
              "985 passed, 3 skipped, 1 xfailed in 1614.23s\n")
    assert _run(monkeypatch, report) == 0


def test_an_unaccounted_skip_still_fails_the_cross_check(monkeypatch):
    # summary says 3, the lines only carry 2: a skip printed in a format the parser cannot see
    report = (f"SKIPPED [2] tests/test_validator_gate.py:66: {ALLOWED}\n"
              "985 passed, 3 skipped in 100.00s\n")
    assert _run(monkeypatch, report) == 1


def test_a_reason_off_the_allow_list_fails_every_copy(monkeypatch):
    report = ("SKIPPED [2] tests/test_x.py:1: some new unvetted reason\n"
              "10 passed, 2 skipped in 1.00s\n")
    assert _run(monkeypatch, report) == 1


def test_input_that_is_not_a_pytest_report_fails(monkeypatch):
    assert _run(monkeypatch, "") == 1
