#!/usr/bin/env python3
"""Prepare the network-type table the usage-analytics fold bisects for the network-type label.

A hand-run, STDLIB-ONLY operator chore, run monthly in a scratch directory outside $AUSMT_DATA_DIR.
It reads the downloaded sources once and writes a compact `start_ip,end_ip,type` table, with type one
of hosting, education_research, access_provider or other. An address in no row is the fold's miss.

    python3 deploy/scripts/prep_nettype.py \\
        --x4bnet-v4 "$tmp/ipv4.txt" --x4bnet-v6 "$tmp/ipv6.txt" \\
        --x4bnet-licence "$tmp/LICENSE" --x4bnet-date YYYY-MM-DD \\
        --out "$AUSMT_DATA_DIR/geoip/nettype.csv"

SOURCES
  * X4BNet lists_vpn, output/datacenter ipv4.txt and ipv6.txt (MIT): one CIDR per line, every range
    hosting. Required, with the repository's LICENSE file, whose text is copied into the table header
    because the MIT terms require the notice to travel with the data.
  * Optional, both or neither: the iptoasn.com combined table (PDDL; range_start, range_end,
    AS_number, country_code, AS_description; tab separated, gzip accepted) with a PeeringDB net
    table (the whole `net` object as JSON). Each prefix takes its ASN's PeeringDB type.

THE TABLE
  * Every input range is widened outward to /24 (IPv4) or /48 (IPv6), the grain the fold's
    addresses are masked to, so a row never splits a masked network.
  * Where ranges overlap, the type is chosen in the order hosting, education_research,
    access_provider, other, and X4BNet hosting overlays everything. The rows are sorted, pairwise
    disjoint and aligned, because the fold's lookup tests a single bisect candidate.
  * No AS number, organisation name or domain from the sources is ever written; they exist only in
    memory while this runs.
  * The first line is the header the fold gates on:
      # ausmt-nettype v1 built=YYYY-MM-DD oldest_source=YYYY-MM-DD sources=x4bnet[,iptoasn,peeringdb]
    The fold judges staleness by oldest_source, the oldest of the given source dates.

TRUST CLASS. Like prep_au_states.py and unlike the timer-driven fold, this FAILS LOUDLY and NON-ZERO
and writes nothing on an unreadable input, a truncated download (fewer than MIN_X4BNET_V4_CIDRS valid
X4BNet IPv4 CIDRs, or fewer than --min-peeringdb-records PeeringDB net records), half of the optional
pair, or any input kept inside the output's directory. The output is written atomically.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import ipaddress
import json
import os
import re
import sys
from pathlib import Path

# The four types a row may carry, in the order that settles an overlap.
TYPE_ORDER = ("hosting", "education_research", "access_provider", "other")
_RANK = {t: i for i, t in enumerate(TYPE_ORDER)}

# The order that settles an ASN with several PeeringDB types.
_ASN_TYPE_ORDER = ("education_research", "access_provider", "hosting", "other")

# PeeringDB info_types to network type. Any other named type folds into other, so that no value
# points at a single kind of organisation; an undisclosed or empty type gives no row.
_PDB_TYPES = {
    "Educational/Research": "education_research",
    "Cable/DSL/ISP": "access_provider",
    "Content": "hosting",
    "NSP": "other",
    "Enterprise": "other",
    "Government": "other",
    "Non-Profit": "other",
    "Network Services": "other",
    "Route Server": "other",
    "Route Collector": "other",
}
_PDB_NO_TYPE = ("", "Not Disclosed")

# Floors that refuse a truncated download rather than write a misleading table.
MIN_X4BNET_V4_CIDRS = 1000
DEFAULT_MIN_PEERINGDB_RECORDS = 5000

# The masked grain of the fold's addresses: host bits below it are widened away.
_HOST_BITS = {4: 8, 6: 80}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MIT_GRANT = "Permission is hereby granted, free of charge"

_NOTICE_IPLOCATE = "Hosting ranges built in part from IPLocate.io data (CC BY-SA 4.0)"
_NOTICE_PEERINGDB = "Network types from PeeringDB"
_NOTICE_IPTOASN = "Prefix to AS from iptoasn.com (PDDL)"


class Refused(Exception):
    """An input this script will not build from. `code` is the exit status."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _widen(version: int, start: int, end: int) -> tuple[int, int]:
    mask = (1 << _HOST_BITS[version]) - 1
    return start & ~mask, end | mask


def _read_text(path: Path) -> str:
    try:
        raw = path.read_bytes()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8")
    except (OSError, EOFError, gzip.BadGzipFile, UnicodeDecodeError) as exc:
        raise Refused(f"could not read {path} ({type(exc).__name__})") from exc


def read_x4bnet(path: Path, version: int) -> list[tuple[int, int]]:
    """The valid CIDRs of one X4BNet list for `version`, widened, as (start, end) ints. Blank lines,
    comments, unparseable lines and entries of the other IP version are skipped."""
    out = []
    for line in _read_text(path).splitlines():
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        try:
            net = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if net.version != version:
            continue
        out.append(_widen(version, int(net.network_address), int(net.broadcast_address)))
    return out


def read_peeringdb(path: Path, min_records: int) -> dict[int, str]:
    """ASN to network type from a PeeringDB net table. Refuses a table with fewer than `min_records`
    net records, which is what a truncated or rate-limited download looks like."""
    try:
        doc = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise Refused(f"could not read {path} (not JSON)") from exc
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        raise Refused(f"could not read {path} (no net records)")
    records = [r for r in data if isinstance(r, dict) and isinstance(r.get("asn"), int)]
    if len(records) < min_records:
        raise Refused(f"{path} holds {len(records)} net records, fewer than {min_records}; "
                      "is the download truncated?", code=1)
    types: dict[int, str] = {}
    for rec in records:
        named = rec.get("info_types")
        named = list(named) if isinstance(named, list) else []
        if isinstance(rec.get("info_type"), str):
            named.append(rec["info_type"])
        found = set()
        for raw in named:
            if not isinstance(raw, str) or raw.strip() in _PDB_NO_TYPE:
                continue
            found.add(_PDB_TYPES.get(raw.strip(), "other"))
        for t in _ASN_TYPE_ORDER:
            if t in found:
                types[rec["asn"]] = t
                break
    return types


def read_iptoasn(path: Path, asn_types: dict[int, str]) -> dict[int, list[tuple[int, int, str]]]:
    """The iptoasn prefixes whose ASN has a type, widened, per IP version. AS 0 (not routed) and an
    ASN with no type give nothing. The description column is never read past the split."""
    out: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
    for line in _read_text(path).splitlines():
        cols = line.split("\t")
        if len(cols) < 3:
            continue
        try:
            start = ipaddress.ip_address(cols[0].strip())
            end = ipaddress.ip_address(cols[1].strip())
            asn = int(cols[2].strip())
        except ValueError:
            continue
        if start.version != end.version or int(end) < int(start):
            continue
        kind = asn_types.get(asn) if asn else None
        if kind is None:
            continue
        s, e = _widen(start.version, int(start), int(end))
        out[start.version].append((s, e, kind))
    return out


def resolve(ranges: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Disjoint pieces over sorted boundary points, each taking the first covering type in
    TYPE_ORDER, with adjacent pieces of one type merged."""
    events: dict[int, list[tuple[int, int]]] = {}
    for start, end, kind in ranges:
        events.setdefault(start, []).append((_RANK[kind], 1))
        events.setdefault(end + 1, []).append((_RANK[kind], -1))
    active = [0] * len(TYPE_ORDER)
    points = sorted(events)
    out: list[tuple[int, int, str]] = []
    for i, point in enumerate(points):
        for rank, delta in events[point]:
            active[rank] += delta
        if i + 1 == len(points):
            break
        best = next((r for r, n in enumerate(active) if n > 0), None)
        if best is None:
            continue
        kind, end = TYPE_ORDER[best], points[i + 1] - 1
        if out and out[-1][2] == kind and out[-1][1] + 1 == point:
            out[-1] = (out[-1][0], end, kind)
        else:
            out.append((point, end, kind))
    return out


def render(rows: dict[int, list[tuple[int, int, str]]], *, built: str, oldest: str,
           sources: list[str], licence: str) -> str:
    lines = [f"# ausmt-nettype v1 built={built} oldest_source={oldest} sources={','.join(sources)}",
             "# Columns: start_ip,end_ip,type (hosting, education_research, access_provider, other).",
             "# Hosting ranges from X4BNet lists_vpn, output/datacenter, under the MIT licence:"]
    lines += [f"# {ln}".rstrip() for ln in licence.strip().splitlines()]
    lines.append(f"# {_NOTICE_IPLOCATE}")
    if "peeringdb" in sources:
        lines += [f"# {_NOTICE_PEERINGDB}", f"# {_NOTICE_IPTOASN}"]
    for version, cls in ((4, ipaddress.IPv4Address), (6, ipaddress.IPv6Address)):
        for start, end, kind in rows[version]:
            lines.append(f"{cls(start)},{cls(end)},{kind}")
    return "\n".join(lines) + "\n"


def write_atomic(dest: Path, text: str) -> None:
    """tmp beside dest, then os.replace, so the fold never reads a half-written table."""
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


def _date(value: str, flag: str) -> str:
    if not _DATE_RE.match(value or ""):
        raise Refused(f"{flag} must be YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise Refused(f"{flag} must be a real date") from exc
    return value


def build(args) -> tuple[str, dict]:
    """The table text and the counts printed for the operator, or Refused."""
    with_asn = args.asn_table is not None
    if with_asn != (args.peeringdb is not None):
        raise Refused("--asn-table and --peeringdb go together: give both or neither")
    dates = {"x4bnet": _date(args.x4bnet_date, "--x4bnet-date")}
    inputs = [args.x4bnet_v4, args.x4bnet_v6, args.x4bnet_licence]
    if with_asn:
        if not args.asn_date or not args.peeringdb_date:
            raise Refused("--asn-table needs --asn-date and --peeringdb needs --peeringdb-date")
        dates["iptoasn"] = _date(args.asn_date, "--asn-date")
        dates["peeringdb"] = _date(args.peeringdb_date, "--peeringdb-date")
        inputs += [args.asn_table, args.peeringdb]
    out_dir = Path(args.out).resolve().parent
    for p in inputs:
        if out_dir in Path(p).resolve().parents:
            raise Refused(f"{p} is inside {out_dir}; keep the downloads in a scratch directory")
    licence = _read_text(Path(args.x4bnet_licence))
    if _MIT_GRANT not in licence:
        raise Refused(f"{args.x4bnet_licence} is not the MIT licence text")
    v4 = read_x4bnet(Path(args.x4bnet_v4), 4)
    if len(v4) < MIN_X4BNET_V4_CIDRS:
        raise Refused(f"{args.x4bnet_v4} holds {len(v4)} valid IPv4 CIDRs, fewer than "
                      f"{MIN_X4BNET_V4_CIDRS}; is the download truncated?", code=1)
    v6 = read_x4bnet(Path(args.x4bnet_v6), 6)
    ranges: dict[int, list[tuple[int, int, str]]] = {4: [], 6: []}
    if with_asn:
        asn_types = read_peeringdb(Path(args.peeringdb), args.min_peeringdb_records)
        ranges = read_iptoasn(Path(args.asn_table), asn_types)
    ranges[4] += [(s, e, "hosting") for s, e in v4]
    ranges[6] += [(s, e, "hosting") for s, e in v6]
    rows = {ver: resolve(ranges[ver]) for ver in (4, 6)}
    text = render(rows, built=dt.datetime.now(dt.timezone.utc).date().isoformat(),
                  oldest=min(dates.values()), sources=list(dates), licence=licence)
    return text, {"v4": len(rows[4]), "v6": len(rows[6]), "sources": ",".join(dates),
                  "oldest": min(dates.values())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit the network-type table for the AusMT usage-analytics fold. Hosting-only "
                    "from X4BNet by default; with iptoasn and PeeringDB, the full four types.")
    ap.add_argument("--x4bnet-v4", required=True, help="X4BNet output/datacenter/ipv4.txt")
    ap.add_argument("--x4bnet-v6", required=True, help="X4BNet output/datacenter/ipv6.txt")
    ap.add_argument("--x4bnet-licence", required=True, help="the X4BNet repository's LICENSE file")
    ap.add_argument("--x4bnet-date", required=True, help="the source's last commit date, YYYY-MM-DD")
    ap.add_argument("--asn-table", help="iptoasn.com combined TSV (.tsv or .tsv.gz)")
    ap.add_argument("--asn-date", help="the iptoasn download date, YYYY-MM-DD")
    ap.add_argument("--peeringdb", help="the PeeringDB net table as JSON")
    ap.add_argument("--peeringdb-date", help="the PeeringDB download date, YYYY-MM-DD")
    ap.add_argument("--min-peeringdb-records", type=int, default=DEFAULT_MIN_PEERINGDB_RECORDS,
                    help=f"refuse a PeeringDB table with fewer net records "
                         f"(default {DEFAULT_MIN_PEERINGDB_RECORDS})")
    ap.add_argument("--out", required=True, help="where to write the table")
    try:
        args = ap.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        text, counts = build(args)
        write_atomic(Path(args.out), text)
    except Refused as exc:
        print(f"prep_nettype: {exc}. Nothing written.", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"prep_nettype: could not write {args.out} ({type(exc).__name__}). Nothing written.",
              file=sys.stderr)
        return 2
    print(f"prep_nettype: {counts['v4']} IPv4 and {counts['v6']} IPv6 rows from "
          f"{counts['sources']}, oldest source {counts['oldest']} -> {args.out}", file=sys.stderr)
    print("prep_nettype: the downloads are not needed again; delete them.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
