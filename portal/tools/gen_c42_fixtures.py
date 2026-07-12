#!/usr/bin/env python3
"""Regenerate the C42 coordinate-access portal fixtures from the REAL engine.

The portal coordinate-access test (tools/coord_access_test.js) loads engine-BUILT portal
artifacts — never hand-typed catalogue rows (the C42 house rule, D6). This script stages a survey
with one exact + one generalised + one withheld station (distinctive coordinates) and runs the real
extract.build_portal over it, then copies the portal-consumed artifacts into
tests/fixtures/c42/. Requires the mt_metadata/mth5 build stack (same as engine/tests/test_coord_access.py).

    python portal/tools/gen_c42_fixtures.py

The committed fixtures are the build's own output, so a reader can verify the exact masked shapes:
  * catalogue.json  — withheld => lat/lon null (cols 2/3); generalised => 0.1deg cell; exact verbatim.
  * mtcat.json      — station latitude/longitude same masking; a lone-withheld survey has bbox null.
  * products/sweep-survey/<ID>/station.json — location {lat,lon} masked; distribution.edi_available
    false for a byte-gated (non-exact) station.
NOTE (audited 2026-07-12): the engine emits NO explicit coordinate-access POLICY field on any
portal-consumed artifact. Withheld is detectable (null lat/lon); generalised is a silently-rounded
value with no marker — see the test header + the lane report for the record-vs-code discrepancy.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PORTAL = Path(__file__).resolve().parent.parent
ENGINE = PORTAL.parent / "engine"
SAMPLE = ENGINE / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
FIXTURES = PORTAL / "tests" / "fixtures" / "c42"

# distinctive coords per policy class (mirrors engine/tests/test_coord_access.py EXACT/GEN/HID)
EXACT = {"id": "EXACTONE", "lat": -31.234567, "lon": 135.234567, "elev": 111.61, "policy": "exact"}
GEN = {"id": "GENFIVE", "lat": -32.876543, "lon": 136.876543, "elev": 222.73, "policy": "generalised"}
HID = {"id": "HIDENINE", "file": "HIDEFILE.edi", "lat": -33.555551, "lon": 137.555559, "elev": 333.47,
       "policy": "withheld"}


def _rewrite(src, st):
    lat, lon, elev = st["lat"], st["lon"], st["elev"]
    t = src
    t = re.sub(r'DATAID="[^"]*"', f'DATAID="{st["id"]}"', t, count=1)
    t = re.sub(r"\nLAT=[^\n]*", f"\nLAT={lat:.6f}", t, count=1)
    t = re.sub(r"\nLONG=[^\n]*", f"\nLONG={lon:.6f}", t, count=1)
    t = re.sub(r"\nELEV=[^\n]*", f"\nELEV={elev:.2f}", t, count=1)
    t = re.sub(r"LATITUDE    :[^\n]*", f"LATITUDE    :   {lat:.6f}", t, count=1)
    t = re.sub(r"LONGITUDE   :[^\n]*", f"LONGITUDE   :   {lon:.6f}", t, count=1)
    t = re.sub(r"ELEVATION   :[^\n]*", f"ELEVATION   :   {elev:.4f}", t, count=1)
    t = re.sub(r"REFLAT=[^\n]*", f"REFLAT={lat:.6f}", t, count=1)
    t = re.sub(r"REFLONG=[^\n]*", f"REFLONG={lon:.6f}", t, count=1)
    t = re.sub(r"REFELEV=[^\n]*", f"REFELEV={elev:.2f}", t, count=1)
    return t


def main():
    work = PORTAL / "tools" / "_c42_build_tmp"
    if work.exists():
        shutil.rmtree(work)
    base = work / "surveys"
    edidir = base / "sweep-survey" / "transfer_functions" / "edi"
    edidir.mkdir(parents=True)
    src = SAMPLE.read_text(encoding="utf-8")
    for st in (EXACT, GEN, HID):
        (edidir / st.get("file", f"{st['id']}.edi")).write_text(_rewrite(src, st), encoding="utf-8")
    lines = ['schema_version: "0.1"', "slug: sweep-survey", 'name: "Coord Access Sweep Survey"',
             "country: Australia", 'organisation: "AusMT CI"', 'abstract: "C42 portal fixture"',
             'license: "CC-BY-4.0"', "data_type: BBMT",
             "geographic_extent: { west: 134.0, east: 139.0, south: -35.0, north: -30.0, datum: WGS84 }",
             "access:", "  level: open", "  coordinates: exact", "  coordinate_overrides:",
             "    GENFIVE: generalised", "    HIDENINE: withheld"]
    (base / "sweep-survey" / "survey.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = work / "out"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(base),
                        "--out", str(out), "--products", str(out / "products"), "--bundle-edi",
                        "--no-validate"], cwd=str(ENGINE), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("engine build failed:\n" + r.stderr)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for f in ("catalogue.json", "tf.json", "sci.json", "surveys.json", "collections.json",
              "mtcat.json", "qc_report.json"):
        shutil.copy(out / f, FIXTURES / f)
    for sid in (EXACT["id"], GEN["id"], HID["id"]):
        dst = FIXTURES / "products" / "sweep-survey" / sid
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(out / "products" / "sweep-survey" / sid / "station.json", dst / "station.json")
    shutil.rmtree(work)
    print("regenerated C42 fixtures under", FIXTURES)
    cat = json.loads((FIXTURES / "catalogue.json").read_text())
    for row in cat:
        print("  ", row[0], "lat/lon=", row[2], row[3])


if __name__ == "__main__":
    main()
