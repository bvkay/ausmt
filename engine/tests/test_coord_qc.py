"""Coordinate QC — the DMS sign-bug DETECTION + RESOLUTION that can REWRITE a published coordinate
(~32 km mislocation if it regresses). Built from the kept dependency-free helpers
(_edi_catalog.detect_coord_issue) + build_portal._apply_coord_resolution, so it runs in the core suite.

NON-VACUOUS: the repo's own sample Vulcan EDIs are LIVE dms_sign_ambiguous cases (HEAD lat vs the
decimal INFO lat differ by ~0.29 deg), so this both proves the flag fires on real fixtures and that the
resolution swap actually moves the coordinate (or, undeclared, leaves it on HEAD and flagged).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "extract"))
sys.path.insert(0, str(REPO))
import _edi_catalog as cat   # noqa: E402
import _ediparse as ep       # noqa: E402
import build_portal as bp    # noqa: E402

EDIS = sorted((REPO / "data" / "sample-survey" / "transfer_functions" / "edi").glob("*.edi"))


def _head_info(path):
    raw = ep.read_norm(path)
    hlat, hlon = cat.coords_of(path)       # HEAD-first (the EDI-standard authoritative field)
    ilat, ilon = cat.info_coords(raw)      # decimal INFO block
    return hlat, hlon, ilat, ilon


def test_sample_edis_are_dms_sign_ambiguous():
    assert EDIS, "sample EDIs missing"
    for p in EDIS:
        hlat, hlon, ilat, ilon = _head_info(p)
        flag, cand, _conflict = cat.detect_coord_issue(hlat, hlon, ilat, ilon, hlat, hlon)
        assert flag == "dms_sign_ambiguous", f"{p.name}: expected dms_sign_ambiguous, got {flag!r}"
        assert cand["head"][0] == hlat and cand["info"][0] == ilat
        assert abs(hlat - ilat) > 0.01, f"{p.name}: HEAD/INFO lat should genuinely differ"


def test_resolution_swaps_to_info_only_when_declared():
    p = EDIS[0]
    hlat, hlon, ilat, ilon = _head_info(p)
    flag, cand, conflict = cat.detect_coord_issue(hlat, hlon, ilat, ilon, hlat, hlon)
    assert flag == "dms_sign_ambiguous"

    def station():
        return [(p, {"id": "A", "lat": hlat, "lon": hlon, "coord_flag": flag,
                     "coord_candidates": cand, "coord_conflict_deg": conflict})]

    # no survey declaration -> coordinate STAYS on HEAD and remains flagged (treat-with-caution)
    s = station(); bp._apply_coord_resolution(s, None)
    assert s[0][1]["lat"] == hlat and s[0][1]["coord_flag"] == "dms_sign_ambiguous"

    # survey declares trust-INFO -> swap to the INFO candidate, mark resolved (coordinate MOVES)
    s = station(); bp._apply_coord_resolution(s, {"dms_sign": "info", "basis": "field GPS"})
    assert s[0][1]["lat"] == round(ilat, 6), "INFO resolution did not swap the latitude"
    assert s[0][1]["lat"] != hlat, "the published coordinate should have moved"
    assert s[0][1]["coord_flag"] == "dms_sign_resolved"

    # survey declares trust-HEAD -> keep HEAD value, mark resolved (no swap)
    s = station(); bp._apply_coord_resolution(s, {"dms_sign": "head"})
    assert s[0][1]["lat"] == hlat and s[0][1]["coord_flag"] == "dms_sign_resolved"


# ---- DMS-format INFO blocks (NSW re-export style) --------------------------------------------
# A decimal-only INFO regex truncated 'LATITUDE : -28:31:33.45' at the first colon (-> -28.0),
# manufacturing a whole-degree (~55 km) HEAD/INFO conflict at every station. The INFO parser must
# accept DMS and agree with HEAD to metres on files whose two blocks genuinely agree.

NSW_DMS_EDI = (
    '>HEAD\nDATAID="A23"\nLAT=-28:31:33.593\nLONG=+152:1:33.241\n\n'
    ">INFO\n  LATITUDE    :   -28:31:33.45\n  LONGITUDE   :   152:01:34.43\n\n"
    ">FREQ\n1 10 100\n>ZXYR\n1 2 3\n"
)


def test_info_coords_parses_dms(tmp_path):
    ilat, ilon = cat.info_coords(NSW_DMS_EDI)
    assert ilat is not None and abs(ilat - (-(28 + 31 / 60 + 33.45 / 3600))) < 1e-6
    assert ilon is not None and abs(ilon - (152 + 1 / 60 + 34.43 / 3600)) < 1e-6
    # decimal Geotools style still parses unchanged
    dlat, dlon = cat.info_coords("LATITUDE :  -29.3675\nLONGITUDE: 132.7536\n")
    assert dlat == -29.3675 and dlon == 132.7536


def test_dms_info_agreeing_head_raises_no_conflict():
    hlat = cat.parse_angle("-28:31:33.593")
    hlon = cat.parse_angle("+152:1:33.241")
    ilat, ilon = cat.info_coords(NSW_DMS_EDI)
    flag, cand, conflict = cat.detect_coord_issue(hlat, hlon, ilat, ilon, hlat, hlon)
    assert flag is None, f"agreeing DMS blocks must not flag, got {flag!r}"
    assert conflict is None, f"agreeing DMS blocks must not report a conflict, got {conflict!r}"
