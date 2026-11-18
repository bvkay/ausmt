"""Network-type table prep pins (deploy/scripts/prep_nettype.py).

The prep script is the hand-run half of the network-type label: it reads the X4BNet datacenter
lists and, optionally, the iptoasn.com prefix table with a PeeringDB net table, and writes a compact
`start_ip,end_ip,type` table for the daily fold to bisect. It writes no AS number, organisation name
or domain, and it makes no network call.

Every address in this file and its fixtures is a documentation address (192.0.2.0/24,
198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32) and every AS number is reserved (64496 to 64511).
Pure stdlib python and committed fixtures, so the file runs everywhere.
"""
from __future__ import annotations

import importlib.util
import ipaddress
import re
import socket
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "prep_nettype.py"
_AGG_SCRIPT = _REPO / "deploy" / "scripts" / "aggregate_stats.py"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_V4 = _FIXTURES / "x4bnet-dc-v4.sample.txt"
_V6 = _FIXTURES / "x4bnet-dc-v6.sample.txt"
_LICENCE = _FIXTURES / "x4bnet-licence.sample.txt"
_ASN = _FIXTURES / "iptoasn.sample.tsv"
_PDB = _FIXTURES / "peeringdb-net.sample.json"
_TYPES = ("hosting", "education_research", "access_provider", "other")
_HEADER_RE = re.compile(r"^# ausmt-nettype v1 built=(\d{4}-\d{2}-\d{2}) "
                        r"oldest_source=(\d{4}-\d{2}-\d{2}) sources=([a-z0-9_,]+)$")
_ROW_RE = re.compile(r"^([0-9a-f.:]+),([0-9a-f.:]+),(%s)$" % "|".join(_TYPES))

_HOSTING_ONLY = [
    "192.0.2.0,192.0.2.255,hosting",
    "203.0.113.0,203.0.113.255,hosting",
    "2001:db8:a0::,2001:db8:a1:ffff:ffff:ffff:ffff:ffff,hosting",
    "2001:db8:180::,2001:db8:180:ffff:ffff:ffff:ffff:ffff,hosting",
]
_FULL = [
    "192.0.2.0,192.0.2.255,hosting",
    "198.51.100.0,198.51.100.255,education_research",
    "203.0.113.0,203.0.113.255,hosting",
    "2001:db8:a0::,2001:db8:a1:ffff:ffff:ffff:ffff:ffff,hosting",
    "2001:db8:100::,2001:db8:17f:ffff:ffff:ffff:ffff:ffff,access_provider",
    "2001:db8:180::,2001:db8:180:ffff:ffff:ffff:ffff:ffff,hosting",
    "2001:db8:181::,2001:db8:1ff:ffff:ffff:ffff:ffff:ffff,access_provider",
    "2001:db8:200::,2001:db8:2ff:ffff:ffff:ffff:ffff:ffff,other",
    "2001:db8:300::,2001:db8:3ff:ffff:ffff:ffff:ffff:ffff,education_research",
    "2001:db8:600::,2001:db8:6ff:ffff:ffff:ffff:ffff:ffff,hosting",
    "2001:db8:900::,2001:db8:900:ffff:ffff:ffff:ffff:ffff,other",
    "2001:db8:a00::,2001:db8:aff:ffff:ffff:ffff:ffff:ffff,other",
]

_CACHE: dict = {}


def _load(name: str, path: Path):
    if name not in _CACHE:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _CACHE[name] = mod
    return _CACHE[name]


def _prep():
    return _load("prep_nettype", _SCRIPT)


@pytest.fixture
def prep(monkeypatch):
    """The prep module with its X4BNet floor lowered to fit the small fixture. The floor itself is
    pinned by the refusal test, which leaves it at its default."""
    mod = _prep()
    monkeypatch.setattr(mod, "MIN_X4BNET_V4_CIDRS", 1)
    return mod


def _hosting_args(out: Path, *, v4=_V4, v6=_V6, date="2026-06-20") -> list[str]:
    return ["--x4bnet-v4", str(v4), "--x4bnet-v6", str(v6), "--x4bnet-date", date,
            "--x4bnet-licence", str(_LICENCE), "--out", str(out)]


def _full_args(out: Path, *, pdb=_PDB, min_records="1") -> list[str]:
    return _hosting_args(out) + ["--asn-table", str(_ASN), "--asn-date", "2026-06-05",
                                 "--peeringdb", str(pdb), "--peeringdb-date", "2026-06-28",
                                 "--min-peeringdb-records", min_records]


def _rows(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]


def _build(prep, tmp_path, args_fn=_full_args) -> str:
    out = tmp_path / "out" / "nettype.csv"
    assert prep.main(args_fn(out)) == 0
    return out.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# The emitted table.
# --------------------------------------------------------------------------------------------------
def test_hosting_only_mode_from_x4bnet(prep, tmp_path):
    """With X4BNet alone every row is hosting, narrower entries are widened, overlapping and adjacent
    entries merge, an entry of the wrong IP version for its file is skipped, and the header names
    x4bnet as the only source. Fails if a non-hosting type appears or a row is missing."""
    text = _build(prep, tmp_path, _hosting_args)
    assert _rows(text) == _HOSTING_ONLY
    assert _HEADER_RE.match(text.splitlines()[0]).group(3) == "x4bnet"
    assert "IPLocate.io" in text
    assert "PeeringDB" not in text and "iptoasn.com" not in text


def test_peeringdb_mapping_and_priority(prep, tmp_path):
    """Each ASN takes its PeeringDB type: Educational/Research is education_research, Cable/DSL/ISP is
    access_provider, Content is hosting, and Government, NSP (also under the single info_type key),
    Enterprise, Non-Profit and any other named type are other. Several types take the priority
    education_research, access_provider, hosting, other. Not Disclosed, an ASN absent from PeeringDB
    and AS 0 give no row. X4BNet hosting overlays every type."""
    text = _build(prep, tmp_path)
    assert _rows(text) == _FULL
    assert _HEADER_RE.match(text.splitlines()[0]).group(3) == "x4bnet,iptoasn,peeringdb"
    assert "# Network types from PeeringDB" in text
    assert "# Prefix to AS from iptoasn.com (PDDL)" in text


def _parsed(text: str):
    out = []
    for row in _rows(text):
        start, end, kind = _ROW_RE.match(row).groups()
        out.append((ipaddress.ip_address(start), ipaddress.ip_address(end), kind))
    return out


def test_output_ranges_sorted_disjoint_and_aligned(prep, tmp_path):
    """The fold bisects one candidate per lookup, so the rows must be sorted by start, pairwise
    disjoint, and aligned to /24 (IPv4) and /48 (IPv6). IPv4 rows come first."""
    rows = _parsed(_build(prep, tmp_path))
    versions = [s.version for s, _, _ in rows]
    assert versions == sorted(versions)
    prev = {4: -1, 6: -1}
    for start, end, _ in rows:
        host_bits = 8 if start.version == 4 else 80
        mask = (1 << host_bits) - 1
        assert int(start) & mask == 0, start
        assert int(end) & mask == mask, end
        assert int(start) <= int(end)
        assert int(start) > prev[start.version], start
        prev[start.version] = int(end)
    # Adjacent rows of one type are merged.
    for (s1, e1, k1), (s2, _e2, k2) in zip(rows, rows[1:]):
        if s1.version == s2.version and int(e1) + 1 == int(s2):
            assert k1 != k2, (s1, s2)


def _range_table(path: Path):
    agg = _load("aggregate_stats", _AGG_SCRIPT)

    class _Lower(agg._RangeTable):
        @staticmethod
        def _coerce_value(raw: str):
            v = raw.strip().lower()
            return v or None

    return _Lower.load(path)


def test_hosting_overlay_inside_wider_access_range_resolves(prep, tmp_path):
    """A hosting /48 inside a wider access range splits it into access, hosting, access, and the
    fold's bisect lookup reads hosting inside and access_provider on either side. A hosting /24
    over a narrower access range reads hosting throughout."""
    out = tmp_path / "out" / "nettype.csv"
    assert prep.main(_full_args(out)) == 0
    table = _range_table(out)
    assert table.lookup("2001:db8:180::") == "hosting"
    assert table.lookup("2001:db8:180:ffff::") == "hosting"
    assert table.lookup("2001:db8:17f:ffff::") == "access_provider"
    assert table.lookup("2001:db8:181::") == "access_provider"
    assert table.lookup("2001:db8:100::") == "access_provider"
    assert table.lookup("203.0.113.0") == "hosting"
    assert table.lookup("203.0.113.200") == "hosting"
    assert table.lookup("2001:db8:400::") is None
    assert table.lookup("2001:db8:500::") is None


def test_sub_slash24_hosting_widened(prep, tmp_path):
    """An X4BNet /25 is widened to its /24 and a /64 to its /48, and so is an iptoasn range that
    starts and ends inside a /48."""
    rows = _rows(_build(prep, tmp_path))
    assert "192.0.2.0,192.0.2.255,hosting" in rows
    assert "2001:db8:180::,2001:db8:180:ffff:ffff:ffff:ffff:ffff,hosting" in rows
    assert "2001:db8:900::,2001:db8:900:ffff:ffff:ffff:ffff:ffff,other" in rows


def test_output_has_only_ranges_and_closed_values(prep, tmp_path):
    """Every data row is two addresses and one of the four closed types: unknown is never written.
    No AS number and no organisation name from the sources reaches the file, and the header and
    notices are the only comment lines."""
    text = _build(prep, tmp_path)
    for row in _rows(text):
        assert _ROW_RE.match(row), row
    assert "unknown" not in text
    assert not re.search(r"(?i)\bAS\s?\d+", text)
    assert not re.search(r"\b(?:6449[6-9]|645[01]\d)\b", text)
    for line in _ASN.read_text(encoding="utf-8").splitlines():
        name = line.split("\t")[4]
        if name.startswith("Invented"):
            assert name not in text, name
    assert "Invented Novel Category" not in text and "Invented Category" not in text


def test_header_carries_oldest_source_date(prep, tmp_path):
    """The first line names the build date and the oldest of the given source dates, because the fold
    judges staleness by the oldest source and never by the build date."""
    full = _build(prep, tmp_path)
    built, oldest, _ = _HEADER_RE.match(full.splitlines()[0]).groups()
    assert oldest == "2026-06-05"
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", built)
    hosting_dir = tmp_path / "h"
    hosting_dir.mkdir()
    hosting = _build(prep, hosting_dir, _hosting_args)
    assert _HEADER_RE.match(hosting.splitlines()[0]).group(2) == "2026-06-20"


def test_x4bnet_licence_copied_into_header(prep, tmp_path):
    """The X4BNet MIT notice, copyright line included, is carried in the table's header from the
    licence file given, so the notice travels with the derived data."""
    text = _build(prep, tmp_path, _hosting_args)
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert "# Copyright (c) Invented Example Holder" in head
    assert any("Permission is hereby granted, free of charge" in ln for ln in head)


def test_makes_no_network_call(prep, tmp_path, monkeypatch):
    """A full build runs with every socket entry point raising, and the script imports no network
    module."""
    def refuse(*_a, **_k):
        raise AssertionError("network call attempted")

    for name in ("socket", "create_connection", "getaddrinfo"):
        monkeypatch.setattr(socket, name, refuse)
    assert _rows(_build(prep, tmp_path)) == _FULL
    src = _SCRIPT.read_text(encoding="utf-8")
    for mod in ("socket", "urllib", "http", "ssl", "ftplib", "requests"):
        assert not re.search(r"^\s*(?:import|from)\s+%s\b" % mod, src, re.M), mod


# --------------------------------------------------------------------------------------------------
# Refusals: non-zero, and nothing written.
# --------------------------------------------------------------------------------------------------
def _nothing_written(out: Path) -> None:
    assert not out.exists()
    if out.parent.exists():
        assert list(out.parent.iterdir()) == []


@pytest.mark.parametrize("case", ["short_x4bnet", "truncated_peeringdb", "missing_input",
                                  "unreadable_peeringdb", "licence_not_mit", "bad_date"])
def test_refuses_short_x4bnet_and_truncated_peeringdb_and_writes_nothing(tmp_path, monkeypatch,
                                                                        case):
    """The X4BNet floor (1000 valid IPv4 CIDRs) and the PeeringDB floor (5000 net records) refuse a
    truncated download, and an unreadable input, a licence file that is not the MIT grant or a
    malformed source date refuse too. Each exits non-zero and leaves no file behind."""
    prep = _prep()
    out = tmp_path / "out" / "nettype.csv"
    if case == "short_x4bnet":
        args = _hosting_args(out)
    elif case == "truncated_peeringdb":
        monkeypatch.setattr(prep, "MIN_X4BNET_V4_CIDRS", 1)
        args = [a for a in _full_args(out) if a not in ("--min-peeringdb-records", "1")]
    elif case == "missing_input":
        monkeypatch.setattr(prep, "MIN_X4BNET_V4_CIDRS", 1)
        args = _hosting_args(out, v6=tmp_path / "absent.txt")
    elif case == "unreadable_peeringdb":
        monkeypatch.setattr(prep, "MIN_X4BNET_V4_CIDRS", 1)
        bad = tmp_path / "pdb.json"
        bad.write_text('{"data": [', encoding="utf-8")
        args = _full_args(out, pdb=bad)
    elif case == "licence_not_mit":
        monkeypatch.setattr(prep, "MIN_X4BNET_V4_CIDRS", 1)
        args = _hosting_args(out)
        args[args.index("--x4bnet-licence") + 1] = str(_V4)
    else:
        monkeypatch.setattr(prep, "MIN_X4BNET_V4_CIDRS", 1)
        args = _hosting_args(out, date="2026-6-20")
    rc = prep.main(args)
    assert rc != 0
    _nothing_written(out)


def test_asn_table_and_peeringdb_must_come_together(prep, tmp_path):
    """The prefix table and the type table are one mode: either alone is refused, and each needs its
    own source date."""
    out = tmp_path / "out" / "nettype.csv"
    asn_only = _hosting_args(out) + ["--asn-table", str(_ASN), "--asn-date", "2026-06-05"]
    pdb_only = _hosting_args(out) + ["--peeringdb", str(_PDB), "--peeringdb-date", "2026-06-28",
                                     "--min-peeringdb-records", "1"]
    no_date = [a for a in _full_args(out) if a not in ("--asn-date", "2026-06-05")]
    for args in (asn_only, pdb_only, no_date):
        assert prep.main(args) != 0, args
        _nothing_written(out)


def test_refuses_inputs_in_output_directory(prep, tmp_path):
    """A download kept inside the directory the table is written to is refused, so the raw sources
    cannot linger beside the derived table."""
    out_dir = tmp_path / "geoip"
    out_dir.mkdir()
    for src in (_V4, _ASN):
        (out_dir / src.name).write_bytes(src.read_bytes())
    out = out_dir / "nettype.csv"
    inside_v4 = _hosting_args(out, v4=out_dir / _V4.name)
    assert prep.main(inside_v4) != 0
    full = _full_args(out)
    full[full.index("--asn-table") + 1] = str(out_dir / _ASN.name)
    assert prep.main(full) != 0
    assert sorted(p.name for p in out_dir.iterdir()) == sorted([_V4.name, _ASN.name])
