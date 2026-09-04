"""Characterization test for _edi_catalog.state_of — the coarse AU-state facet used (only) to seed
the AusLAMP raw/bulk-mode per-state survey split. The function is a crude lon/lat ladder; this test
PINS its current behaviour at representative points so it can be cleaned up later without silently
moving the AusLAMP grouping. (The catalogue region facet r[9] comes from survey.yaml, not this.)"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import _edi_catalog as cat   # noqa: E402

# (label, lat, lon) -> expected state_of() output (captured from the current implementation)
CASES = [
    ("Perth",       -31.95, 115.86, "WA"),
    ("Darwin",      -12.46, 130.84, "NT"),
    ("Adelaide",    -34.93, 138.60, "SA"),
    ("Hobart",      -42.88, 147.33, "TAS"),
    ("Brisbane",    -27.47, 153.03, "QLD"),
    ("Sydney",      -33.87, 151.21, "NSW"),
    ("Melbourne",   -37.81, 144.96, "VIC"),
    ("Broken Hill", -31.95, 141.47, "NSW"),
    ("US Alabama",   34.68, -87.00, ""),    # non-AU -> region guard returns ""
    ("null island",   0.00,   0.00, ""),    # outside the AU bbox
]


def test_state_of_representative_points():
    for label, lat, lon, expected in CASES:
        assert cat.state_of(lat, lon) == expected, f"{label}: {lat},{lon}"


def test_state_of_missing_coords():
    assert cat.state_of(None, None) == "?"
    assert cat.state_of(-30.0, None) == "?"
