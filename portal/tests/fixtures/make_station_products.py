#!/usr/bin/env python3
"""Regenerate portal/tests/fixtures/station-products/ by RUNNING the real emitter.

The three documents under station-products/ are emitted output, not hand-written JSON: the portal
lane installs no engine stack, so its tests cannot run the emitter and instead read a committed tree
the emitter really wrote. That only works while the tree is refreshed whenever the emitter changes
what it writes, and until this script existed there was no way to refresh it - the tree went two
behaviour changes stale with nothing red to say so.

    /path/to/sm/.venv/bin/python portal/tests/fixtures/make_station_products.py

Needs the LOCKED engine venv (mt_metadata + mth5); rewrites the tree in place and prints the commit
it stamped into each record's provenance. Run it, then commit the tree in the SAME commit as the
emitter change that moved it.

The corpus is three stations over one sample EDI, chosen so the tree covers every branch the portal
pages describe: SPEXACT is open and exact (full record, runs[], resources[], a dimensionality
sidecar), SPGENERAL is open with a generalised position (the coordinate_policy key, and no served
bytes, so no resources), SPHELD is embargoed (the withheld stub, and no sidecar at all).
"""
import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]                       # the ausmt monorepo root
ENGINE = REPO / "engine"
SAMPLE = ENGINE / "data" / "sample-survey" / "transfer_functions" / "edi" / "Vulcan_A1.edi"
DEST = HERE / "station-products"

# Positions distinctive enough that a leak sweep can attribute a hit to one station.
STATIONS = {
    "open-survey": [("SPEXACT", -31.234567, 135.234567, 111.61),
                    ("SPGENERAL", -32.876543, 136.876543, 222.73)],
    "withheld-survey": [("SPHELD", -33.555551, 137.555559, 333.47)],
}


def rewrite(src: str, sid: str, lat: float, lon: float, elev: float) -> str:
    """One sample EDI restamped as `sid` at a given position. Every coordinate bearer in the file is
    rewritten, not just HEAD: DEFINEMEAS and the >INFO sheet carry them too."""
    out = re.sub(r'DATAID="[^"]*"', f'DATAID="{sid}"', src, count=1)
    for pattern, value in ((r"\nLAT=[^\n]*", f"\nLAT={lat:.6f}"),
                           (r"\nLONG=[^\n]*", f"\nLONG={lon:.6f}"),
                           (r"\nELEV=[^\n]*", f"\nELEV={elev:.2f}"),
                           (r"LATITUDE    :[^\n]*", f"LATITUDE    :   {lat:.6f}"),
                           (r"LONGITUDE   :[^\n]*", f"LONGITUDE   :   {lon:.6f}"),
                           (r"ELEVATION   :[^\n]*", f"ELEVATION   :   {elev:.4f}"),
                           (r"REFLAT=[^\n]*", f"REFLAT={lat:.6f}"),
                           (r"REFLONG=[^\n]*", f"REFLONG={lon:.6f}"),
                           (r"REFELEV=[^\n]*", f"REFELEV={elev:.2f}")):
        out = re.sub(pattern, value, out, count=1)
    return out


def stage(root: Path, slug: str, name: str, access_lines: list) -> None:
    edidir = root / slug / "transfer_functions" / "edi"
    edidir.mkdir(parents=True)
    src = SAMPLE.read_text(encoding="utf-8")
    for sid, lat, lon, elev in STATIONS[slug]:
        (edidir / f"{sid}.edi").write_text(rewrite(src, sid, lat, lon, elev), encoding="utf-8")
    lines = ['schema_version: "0.1"', f"slug: {slug}", f'name: "{name}"', "country: Australia",
             'organisation: "AusMT CI"', 'abstract: "emitted-products documentation fixture"',
             'license: "CC-BY-4.0"', "data_type: BBMT",
             "geographic_extent: { west: 134.0, east: 139.0, south: -35.0, north: -30.0, "
             "datum: WGS84 }"] + access_lines
    (root / slug / "survey.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The run-id store, without which a station asserting an acquisition fact publishes no runs[]
    # (D2: the id comes from the store and from nowhere else). The sample EDI states a rate, so
    # these rows are what make the fixture carry the block the portal pages describe.
    rows = "\n".join(f"  {sid}: [{sid}-r01]" for sid, *_ in STATIONS[slug])
    (root / slug / "run-ids.yaml").write_text(f"run_ids:\n{rows}\n", encoding="utf-8")


def main() -> int:
    if not SAMPLE.is_file():
        print(f"the sample EDI is missing: {SAMPLE}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        surveys = work / "surveys"
        surveys.mkdir()
        stage(surveys, "open-survey", "Station Products Open Survey",
              ["access:", "  level: open", "  coordinates: exact",
               "  coordinate_overrides:", "    SPGENERAL: generalised"])
        # A date far enough out that the fixture does not expire; the schema requires a real one
        # under an embargoed level (D6).
        embargo = (dt.date.today() + dt.timedelta(days=400)).isoformat()
        stage(surveys, "withheld-survey", "Station Products Withheld Survey",
              ["access:", "  level: embargoed", f"  embargo_until: {embargo}"])
        out = work / "data"
        # --bundle-edi so the tree carries the archive rows a served station really publishes.
        run = subprocess.run(
            [sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
             "--out", str(out), "--products", str(out / "products"), "--bundle-edi",
             "--no-validate"],
            cwd=str(ENGINE), capture_output=True, text=True)
        if run.returncode:
            print(run.stdout[-4000:], run.stderr[-4000:], file=sys.stderr)
            return 1
        shutil.rmtree(DEST, ignore_errors=True)
        # The per-station products only. survey-metadata.json is a different contract with no reader
        # here, and a second document nothing checks is a second document that can go stale unnoticed.
        for slug, stations in STATIONS.items():
            for sid, *_ in stations:
                shutil.copytree(out / "products" / slug / sid, DEST / slug / sid)
    for path in sorted(DEST.rglob("*")):
        print(path.relative_to(REPO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
