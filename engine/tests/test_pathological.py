"""Pathological-input robustness on the mt_metadata engine (slice-#3d).

mt_metadata is stricter than the retired regex reader, so the guarantee moves from "the parser never
throws" to "the BUILD degrades gracefully": process_edis absorbs a per-file parse failure (skips it
with a diagnostic, never crashing the run), recovers what it can, and keeps the rows aligned.
"""
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import build_portal   # noqa: E402

BASE = (HERE.parent / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi").read_text(
    encoding="latin-1")


def strip_block(text, prefix):
    """Remove every >PREFIX... block (up to the next > line)."""
    return re.sub(rf"^>{prefix}[^\n]*\n(?:(?!^>).*\n)*", "", text, flags=re.MULTILINE)


def _degraded_dir(tmp_path):
    edi = tmp_path / "edi"; edi.mkdir()
    (edi / "good.edi").write_text(BASE, encoding="latin-1")
    (edi / "no_info.edi").write_text(strip_block(BASE, "INFO"), encoding="latin-1")
    txt = BASE
    for b in ("ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI", "RHOXY", "RHOYX"):
        txt = strip_block(txt, b)
    (edi / "no_z.edi").write_text(txt, encoding="latin-1")
    (edi / "trunc.edi").write_text(BASE[: len(BASE) // 3], encoding="latin-1")
    (edi / "empty.edi").write_text('>HEAD\nDATAID="E"\n>END\n', encoding="latin-1")
    return edi


def test_build_degrades_gracefully(tmp_path):
    """A directory of degraded EDIs builds WITHOUT crashing under mt_metadata: the good station
    survives with data, truly-unparseable files (truncated / empty) are skipped, survivors that share
    a DATAID become distinct processing-variant records, and the rows stay aligned."""
    edi = _degraded_dir(tmp_path)
    stations, tf_rows, sci_rows = build_portal.process_edis(
        sorted(edi.glob("*.edi")), "Pathological", "Test", "pathological", "mt_metadata")
    files = {r["file"] for _p, r in stations}
    assert "good.edi" in files                                 # the good station survived
    good = next(r for _p, r in stations if r["file"] == "good.edi")
    assert good["n_periods"] > 0 and good["id"].startswith("A1")
    assert good["ausmt_id"] == f"au.pathological.{good['id']}"
    assert "empty.edi" not in files and "trunc.edi" not in files   # truly-broken skipped, not crashed
    ids = [r["id"] for _p, r in stations]
    assert len(ids) == len(set(ids))                           # variant-tagged, no duplicate-id leak
    assert len(stations) == len(tf_rows) == len(sci_rows)      # rows aligned


def test_inf_error_values_do_not_drop_the_station(tmp_path):
    """FAILS IF: an EDI carrying a literal `inf` in an impedance-ERROR array (MTpy writes inf for
    dead/infinite-variance points) crashes TF assembly and drops the whole station. Pre-fix
    (2026-07-10): sig()'s log10(inf) -> int(inf) raised OverflowError, build_portal caught it as a
    station-level PARSE FAIL, and FOUR real stations (FR01, NF19, NF21, SA26W_2) were silently
    absent from the served corpus over single bad error points. Post-fix: the station SERVES and
    the non-finite error points render as null (the None path every consumer already tolerates) —
    never as a raw inf, which would poison tf.json (non-RFC `Infinity` rejected by JSON.parse)."""
    edi = tmp_path / "edi"; edi.mkdir()
    m = re.search(r"(^>ZXY\.VAR[^\n]*\n\s*)(-?\d+\.\d+(?:[eE][+-]?\d+)?)", BASE, flags=re.MULTILINE)
    assert m, "sample EDI lost its ZXY.VAR block (test set-up wrong)"
    (edi / "infvar.edi").write_text(BASE[: m.start(2)] + "inf" + BASE[m.end(2):], encoding="latin-1")
    stations, tf_rows, sci_rows = build_portal.process_edis(
        sorted(edi.glob("*.edi")), "InfVar", "Test", "infvar", "mt_metadata")
    files = {r["file"] for _p, r in stations}
    assert "infvar.edi" in files, \
        "a single inf error point dropped the whole station (the OverflowError PARSE-FAIL class)"
    row = next(r for _p, r in stations if r["file"] == "infvar.edi")
    assert row["n_periods"] > 0
    assert len(stations) == len(tf_rows) == len(sci_rows)
    # No raw non-finite value may reach the serialized row (JSON-poison guard).
    import json as _json
    import math as _math
    def _all_finite(o):
        if isinstance(o, float):
            return _math.isfinite(o)
        if isinstance(o, dict):
            return all(_all_finite(v) for v in o.values())
        if isinstance(o, (list, tuple)):
            return all(_all_finite(v) for v in o)
        return True
    assert _all_finite(_json.loads(_json.dumps(tf_rows))), "a non-finite value leaked into tf rows"


def test_missing_impedance_handled_without_crash(tmp_path):
    """An EDI with the impedance blocks stripped is handled WITHOUT a crash. (The graceful-degradation
    guarantee is build survival; the exact science of a degraded station is not asserted — mt_metadata
    and the retired regex reader legitimately differ on no-impedance edge cases.)"""
    edi = _degraded_dir(tmp_path)
    stations, tf_rows, sci_rows = build_portal.process_edis(
        [edi / "no_z.edi"], "P", "T", "p", "mt_metadata")
    assert isinstance(stations, list)                              # returned cleanly, no crash
    assert len(stations) == len(tf_rows) == len(sci_rows)         # rows aligned whatever survives
