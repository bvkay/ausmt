#!/usr/bin/env python3
"""Prepare the COMPACT Australian state table the usage-analytics fold bisects.

A hand-run, STDLIB-ONLY operator chore. It ingests the db-ip "IP to City Lite" CSV once (db-ip
refreshes it monthly) and emits a small `start_ip,end_ip,state_code` table covering AUSTRALIA ONLY.
The big city CSV is read and thrown away: it is never copied into the data dir, never committed, and
nothing downstream ever reads it again.

    python3 deploy/scripts/prep_au_states.py ~/Downloads/dbip-city-lite-2026-07.csv.gz
    python3 deploy/scripts/prep_au_states.py <city-csv> --out /srv/ausmt/geoip/dbip-au-states.csv

WHY STATE, AND WHY NOT CITY  (a design decision -- do NOT "improve" this to cities later):
  * the address this table is looked up with was ALREADY TRUNCATED at the edge: IPv4 to a /24, IPv6 to
    a /48. A /24 prefix does not place a request in a city reliably -- mobile carrier and CGNAT pools
    routinely serve a whole state from one prefix -- so a city column would be confidently wrong;
  * the Australian magnetotelluric research community is small. A city-level cell is
    QUASI-IDENTIFYING: "3 downloads from Hobart" names a research group as surely as a name would. A
    state-level cell is not.
State is the finest grain that is BOTH defensible from a /24 and non-identifying at this community's
scale. The city and coordinate columns of the source CSV are read only to be discarded.

TRUST CLASS -- deliberately the OPPOSITE of aggregate_stats.py. That script is timer-driven and must
never raise (it exits 0 and degrades a metric). This one is run BY HAND by an operator who is watching,
so it FAILS LOUDLY and NON-ZERO on a useless input rather than quietly leaving an empty table that
would silently degrade every Australian request to "unattributed" with no explanation.

INPUT FORMAT. db-ip's Lite CSVs are headerless, one range per line. The City edition is:
    start_ip,end_ip,continent,country_code,stateprov,city,latitude,longitude
Only fields 0, 1, 3 and 4 are used. A `.gz` input is decompressed transparently (db-ip ships gzip and
the file is large). Rows that are not AU, carry no recognised state, or do not parse are skipped.

OUTPUT. `start_ip,end_ip,STATE` sorted by range start (IPv4 block first, then IPv6), with ADJACENT
ranges of the SAME state coalesced -- which is what keeps the emitted table to a few MB rather than
the source's hundreds. A comment header carries the CC-BY-4.0 attribution with the file, because the
file outlives the terminal it was made in. Written atomically (tmp -> rename), so the daily fold can
never read a half-written table.

ATTRIBUTION. db-ip Lite data is CC-BY-4.0 and the credit is REQUIRED. It is carried in three places:
the header of every table this writes, docs/docs/introduction/usage-analytics.md, and deploy/README.md.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import ipaddress
import os
import sys
from pathlib import Path

# The eight Australian states and territories, in the conventional listing order. This tuple is the
# WHOLE vocabulary: a source label that does not normalise into it is DROPPED rather than guessed at,
# so the fold's "unattributed" bucket carries the honest residue instead of a ninth invented state.
AU_STATE_CODES = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT")

# Source `stateprov` spellings -> code. db-ip writes the full English name; the ISO 3166-2 `AU-XXX`
# form and a bare code are both tolerated because the Lite datasets have shipped all three over time.
# NOT mapped, on purpose:
#   * "Jervis Bay Territory" -- a separate territory, not part of any state (the ABS files it under
#     "Other Territories"). Folding it into ACT would be a guess; it lands in `unattributed` instead.
#   * Norfolk Island, Christmas Island, Cocos (Keeling) Islands, Heard & McDonald -- these carry their
#     OWN ISO country codes (NF, CX, CC, HM), so they never appear under AU in the first place.
_STATE_ALIASES = {
    "new south wales": "NSW",
    "victoria": "VIC",
    "queensland": "QLD",
    "south australia": "SA",
    "western australia": "WA",
    "tasmania": "TAS",
    "northern territory": "NT",
    "australian capital territory": "ACT",
    "capital territory": "ACT",
}

# The db-ip City Lite column positions actually read. Everything else (continent, city, lat, lon) is
# read only to be discarded -- see the state-not-city rationale above.
_COL_START, _COL_END, _COL_COUNTRY, _COL_STATE = 0, 1, 3, 4
_MIN_COLS = 5

_ATTRIBUTION = (
    "This product includes IP to City Lite data created by DB-IP.com, available from "
    "https://db-ip.com, licensed under CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/)."
)


def au_state_code(raw) -> str | None:
    """The state/territory CODE for a db-ip `stateprov` label, or None when it is not one of the eight.

    Tolerant of case, surrounding whitespace, an `AU-` ISO prefix and an already-coded value; NEVER a
    guess. An unrecognised label (an external territory, a db-ip oddity, an empty field) returns None
    so the range is dropped and the traffic lands in the fold's honest unattributed-state bucket."""
    if not isinstance(raw, str):
        return None
    s = " ".join(raw.split()).strip().lower()
    if not s:
        return None
    if s.startswith("au-"):
        s = s[3:]
    if s.upper() in AU_STATE_CODES:
        return s.upper()
    return _STATE_ALIASES.get(s)


def parse_city_row(row) -> tuple[int, int, int, str] | None:
    """One db-ip City Lite row -> (ip_version, start_int, end_int, state_code), or None to skip it.

    Skipped: a short row, a comment, a non-AU country, a mixed-version or unparseable range, and any
    row whose state label is not one of the eight (see au_state_code)."""
    if not row or len(row) < _MIN_COLS:
        return None
    if row[0].lstrip().startswith("#"):
        return None
    if row[_COL_COUNTRY].strip().upper() != "AU":
        return None
    code = au_state_code(row[_COL_STATE])
    if code is None:
        return None
    try:
        start = ipaddress.ip_address(row[_COL_START].strip())
        end = ipaddress.ip_address(row[_COL_END].strip())
    except ValueError:
        return None
    if start.version != end.version or int(end) < int(start):
        return None
    return start.version, int(start), int(end), code


def merge_ranges(rows: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Sort `(start, end, code)` ranges and coalesce ADJACENT-OR-OVERLAPPING ones carrying the SAME
    code. Two consecutive city ranges inside one state become a single row; two adjacent ranges in
    DIFFERENT states stay separate. This is the whole reason the emitted table is small."""
    out: list[tuple[int, int, str]] = []
    for start, end, code in sorted(rows, key=lambda r: (r[0], r[1])):
        if out and out[-1][2] == code and start <= out[-1][1] + 1:
            prev_start, prev_end, prev_code = out[-1]
            out[-1] = (prev_start, max(prev_end, end), prev_code)
        else:
            out.append((start, end, code))
    return out


def build_table(handle) -> tuple[list[tuple[int, int, str]], list[tuple[int, int, str]], dict]:
    """Read a db-ip City Lite CSV stream -> (merged IPv4 ranges, merged IPv6 ranges, counters).

    Only AU rows are kept in memory; the rest of the (very large) file streams past. `counters` is for
    the operator's own eyes -- how many rows were read, how many were Australian, how many survived."""
    raw4: list[tuple[int, int, str]] = []
    raw6: list[tuple[int, int, str]] = []
    counters = {"rows": 0, "au_rows": 0, "au_no_state": 0}
    for row in csv.reader(handle):
        counters["rows"] += 1
        is_au = len(row) >= _MIN_COLS and row[_COL_COUNTRY].strip().upper() == "AU"
        counters["au_rows"] += 1 if is_au else 0
        parsed = parse_city_row(row)
        if parsed is None:
            # An AU row the eight-code vocabulary did not recognise (an external territory, an empty
            # stateprov). Counted so the operator can see the residue that will fold as unattributed.
            counters["au_no_state"] += 1 if is_au else 0
            continue
        version, start, end, code = parsed
        (raw4 if version == 4 else raw6).append((start, end, code))
    return merge_ranges(raw4), merge_ranges(raw6), counters


def render_table(ranges4, ranges6, *, source: str, generated: str) -> str:
    """The emitted file: a provenance + attribution header (comment lines the fold's loader skips),
    then `start_ip,end_ip,STATE` rows, IPv4 first then IPv6."""
    lines = [
        "# AusMT compact Australian state table for the usage-analytics fold.",
        f"# Generated {generated} by deploy/scripts/prep_au_states.py from {source}",
        f"# {_ATTRIBUTION}",
        "# Columns: start_ip,end_ip,state_code   (AU only; codes: " + " ".join(AU_STATE_CODES) + ")",
        "# STATE, NOT CITY, on purpose: the addresses looked up here are masked to a /24 (v4) or /48",
        "# (v6) at the edge, which does not place a request in a city, and a city-level count in a",
        "# research community this small would identify a single group. Do not add cities.",
        "# Refresh monthly by re-running the script over a fresh db-ip City Lite CSV; staleness is",
        "# tolerable (networks move between states rarely) and an absent file is simply country-only.",
    ]
    for cls, ranges in ((ipaddress.IPv4Address, ranges4), (ipaddress.IPv6Address, ranges6)):
        for start, end, code in ranges:
            lines.append(f"{cls(start)},{cls(end)},{code}")
    return "\n".join(lines) + "\n"


def write_atomic(dest: Path, text: str) -> None:
    """tmp under the dest dir -> chmod 0644 -> os.replace, the same posture aggregate_stats.py uses to
    write stats.json: the daily fold must never observe a half-written table under its final name."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        try:
            os.chmod(tmp, 0o644)
        except OSError:
            pass
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _open_city_csv(path: Path):
    """The source CSV as a text stream, decompressing a `.gz` transparently (db-ip ships gzip and the
    file is far too large to expect an operator to expand it by hand first)."""
    if path.suffix.lower() == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline="")
    return open(path, encoding="utf-8", errors="replace", newline="")


def _default_out() -> str:
    """Where the fold looks by default: AUSMT_STATS_AU_STATES_CSV, else beside the country CSV under
    AUSMT_DATA_DIR, else a file in the working directory (so the script is usable off-box)."""
    env = os.environ.get("AUSMT_STATS_AU_STATES_CSV", "").strip()
    if env:
        return env
    data_dir = os.environ.get("AUSMT_DATA_DIR", "").strip()
    if data_dir:
        return str(Path(data_dir) / "geoip" / "dbip-au-states.csv")
    return "dbip-au-states.csv"


def main(argv=None) -> int:
    """Read the City Lite CSV, emit the compact AU state table, and report what happened. Returns 0 on
    success and NON-ZERO on a useless input -- an unreadable file, or a CSV that yielded no Australian
    state ranges at all (the wrong dataset, or a column layout that moved). A loud failure with no file
    written is the honest outcome: an empty table would degrade every Australian request to
    "unattributed" and look like a geolocation problem rather than an operator one."""
    ap = argparse.ArgumentParser(
        description="Emit the compact AU state table for the AusMT usage-analytics fold, from the "
                    "db-ip IP to City Lite CSV (CC-BY-4.0). AU only; state, never city.")
    ap.add_argument("city_csv", help="the db-ip 'IP to City Lite' CSV (.csv or .csv.gz)")
    ap.add_argument("--out", default=None,
                    help="where to write the compact table (default: $AUSMT_STATS_AU_STATES_CSV, "
                         "else $AUSMT_DATA_DIR/geoip/dbip-au-states.csv)")
    args = ap.parse_args(list(argv) if argv is not None else None)

    src = Path(args.city_csv)
    dest = Path(args.out or _default_out())
    if not src.is_file():
        print(f"prep_au_states: no such file: {src}", file=sys.stderr)
        return 2
    try:
        with _open_city_csv(src) as fh:
            ranges4, ranges6, counters = build_table(fh)
    except (OSError, gzip.BadGzipFile, UnicodeError) as exc:
        print(f"prep_au_states: could not read {src} ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2

    total = len(ranges4) + len(ranges6)
    if total == 0:
        print(f"prep_au_states: {src} yielded NO Australian (AU) state ranges from "
              f"{counters['rows']} row(s) -- is this the db-ip 'IP to City Lite' CSV? Nothing written.",
              file=sys.stderr)
        return 1

    text = render_table(ranges4, ranges6, source=src.name,
                        generated=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        write_atomic(dest, text)
    except OSError as exc:
        print(f"prep_au_states: could not write {dest} ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 2
    print(f"prep_au_states: {counters['rows']} source row(s), {counters['au_rows']} Australian, "
          f"{counters['au_no_state']} with no recognised state (they fold as unattributed) -> "
          f"{total} merged range(s) ({len(ranges4)} v4, {len(ranges6)} v6), "
          f"{len(text.encode('utf-8')) / 1024:.0f} KiB -> {dest}", file=sys.stderr)
    print("prep_au_states: the source City Lite CSV is not needed again -- delete it.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
