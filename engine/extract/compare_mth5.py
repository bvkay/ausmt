#!/usr/bin/env python3
"""Compare EDI ingestion against MTH5 ingestion (Prototype 14, Priority 2).

Strategy (the one that worked for mt_metadata): take the existing path, build the new one beside
it, and compare. Here:

    EDI --(mt_metadata)--> products        [existing]
    EDI --> MTH5 --(mth5)--> products       [new ingestion]

Both feed the SAME downstream science (`_edi_tf.tf_from_components` /
`_edi_science.science_from_components`), so any difference is a storage round-trip difference.
Agreement is the evidence that AusMT can ingest MTH5 without changing the products.

Usage:
    python -m extract.compare_mth5 --edis <dir-of-edis> [--out report.json] [--limit N]
"""
import argparse
import json
import math
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _edi_tf as tfmod          # noqa: E402
import _edi_science as sci       # noqa: E402
import _mtm as mtm               # noqa: E402
import _mth5 as m5               # noqa: E402

# Read the tf/sci rows by NAME, not magic integer — single-sourced in contract/columns.json via
# _contract (mirrors build_portal.py's _SC map). APPEND, never reorder.
_T = {n: i for i, n in enumerate(tfmod.TF_COLUMNS)}
_SC = {n: i for i, n in enumerate(sci.SCI_COLUMNS)}


def _rms(a, b):
    pairs = [(x, y) for x, y in zip(a or [], b or []) if x is not None and y is not None]
    if not pairs:
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in pairs) / len(pairs))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--edis", required=True, help="directory of .edi files (searched recursively)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    if not (m5.available() and mtm.available()):
        sys.exit("mth5 + mt_metadata required (pip install -r environments/requirements-mtmetadata-lock.txt).")
    edis = sorted(Path(a.edis).rglob("*.edi"))
    if a.limit:
        edis = edis[:a.limit]
    if not edis:
        sys.exit(f"no EDIs under {a.edis}")

    # build MTH5 from the EDIs, then read TFs back keyed by station id
    with tempfile.TemporaryDirectory() as td:
        h5 = Path(td) / "roundtrip.h5"
        nw = m5.build_mth5_from_edis(edis, h5)
        mth5_by_station = {}
        for rec, per, comp in m5.records_and_components(h5):
            mth5_by_station[rec["id"]] = (rec, per, comp)

    rows, meta_ok, dim_ok, n = [], 0, 0, 0
    rho_rms_all, phs_rms_all, coord_max = [], [], 0.0
    for p in edis:
        er = mtm.parse_edi(p)
        ep, ec = mtm.components(p)
        mk = mth5_by_station.get(er["id"])
        if mk is None:
            rows.append({"file": p.name, "status": "missing_in_mth5"})
            continue
        mr, mp, mc = mk
        n += 1
        meta_match = (er["n_periods"] == mr["n_periods"] and er["type"] == mr["type"]
                      and er["components"] == mr["components"]
                      and abs((er["lat"] or 0) - (mr["lat"] or 0)) < 1e-4
                      and abs((er["lon"] or 0) - (mr["lon"] or 0)) < 1e-4)
        meta_ok += 1 if meta_match else 0
        coord_max = max(coord_max, abs((er["lat"] or 0) - (mr["lat"] or 0)),
                        abs((er["lon"] or 0) - (mr["lon"] or 0)))
        et = tfmod.tf_from_components(ep, ec); mt = tfmod.tf_from_components(mp, mc)
        rho_rms = _rms(et[_T["rho_xy"]], mt[_T["rho_xy"]]); phs_rms = _rms(et[_T["phs_xy"]], mt[_T["phs_xy"]])
        if rho_rms is not None:
            rho_rms_all.append(rho_rms)
        if phs_rms is not None:
            phs_rms_all.append(phs_rms)
        es = sci.science_from_components(ep, ec, mtm.proc_info(p))
        ms = sci.science_from_components(mp, mc, None)
        dim_ok += 1 if es[_SC["dim"]] == ms[_SC["dim"]] else 0
        rows.append({"file": p.name, "meta_match": meta_match, "dim_edi": es[_SC["dim"]], "dim_mth5": ms[_SC["dim"]],
                     "rho_rms": None if rho_rms is None else round(rho_rms, 4),
                     "phase_rms": None if phs_rms is None else round(phs_rms, 4)})

    summary = {
        "n_edis": len(edis), "tfs_written_to_mth5": nw, "compared": n,
        "metadata_agreement": f"{meta_ok}/{n}",
        "dimensionality_agreement": f"{dim_ok}/{n}",
        "coordinate_max_abs_diff_deg": round(coord_max, 7),
        "rho_xy_rms_median": round(sorted(rho_rms_all)[len(rho_rms_all) // 2], 6) if rho_rms_all else None,
        "phase_xy_rms_median_deg": round(sorted(phs_rms_all)[len(phs_rms_all) // 2], 6) if phs_rms_all else None,
    }
    print("=== EDI ingestion vs MTH5 ingestion (round-trip) ===")
    print(json.dumps(summary, indent=2))
    print("\nReading: agreement here is evidence that AusMT can ingest MTH5 and produce the same")
    print("products as the EDI path — the standards-aligned input is validated, not assumed.")
    if a.out:
        Path(a.out).write_text(json.dumps({"summary": summary, "per_file": rows}, indent=1, default=float))
        print(f"\nfull report -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
