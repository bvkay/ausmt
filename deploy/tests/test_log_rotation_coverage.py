"""Rolled access logs must still reach the fold (the rotation blind spot).

ONE invariant, three config surfaces, so it gets one owner rather than a third of a pin in each of
three files: a log line that has ROLLED must still be readable by the daily C45 fold.

Caddy compresses a rolled log file by default, producing `access-<stamp>.json.gz`. Both consumers key
on the plain `.json` name: the aggregator's fold glob (deploy/scripts/aggregate_stats.py) and the
front-door ship filter (deploy/frontdoor/ship-frontdoor-logs.sh). A compressed roll is therefore
neither shipped nor folded, and because the fold advances its watermark past a day whether or not it
saw any lines for it, those requests are lost permanently rather than late.

The fix has two halves and this file pins both:
  * PREVENTION: both shipped Caddyfiles set `roll_uncompressed` inside their log output block, so a
    new roll stays plain JSON and both globs see it;
  * SALVAGE: the ship filter also carries the `.json.gz` family and the aggregator also reads
    `access*.json.gz` (pinned in test_aggregate_stats.py), which covers the transition window and any
    archive an operator places by hand.

Pure text assertions over the committed files plus a black-box shim run of the ship script: no caddy
binary, no network, so this runs everywhere and never trips the CI skip tripwire.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BOX_CADDY = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_FD_CADDY = _REPO / "deploy" / "frontdoor" / "Caddyfile"
_SHIP = _REPO / "deploy" / "frontdoor" / "ship-frontdoor-logs.sh"
_AGG = _REPO / "deploy" / "scripts" / "aggregate_stats.py"
_SH = shutil.which("sh") or shutil.which("bash")


def _log_output_block(path: Path) -> str:
    """The text of the `output file ... { ... }` block inside the top-level `log` block, brace-matched.
    Fails the test if the file has no such block (a restructure must not silently blank this pin)."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"output file \S+ \{", text)
    assert m is not None, f"{path.name} must declare an `output file <path> {{ ... }}` roll block"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
    raise AssertionError(f"unbalanced braces in {path.name}'s log output block")


@pytest.mark.parametrize("path", [_BOX_CADDY, _FD_CADDY], ids=["box", "frontdoor"])
def test_rolled_logs_stay_plain_json_in_both_caddyfiles(path):
    """ROLL-FORMAT PIN. Both shipped Caddyfiles must set `roll_uncompressed` INSIDE their log output
    block, so a rolled access log keeps the `.json` name the fold glob and the ship filter match on.
    Without it Caddy gzips the roll and every line that rolled before the daily ship is folded by
    nobody and then aged past by the watermark. FAILS IF either Caddyfile drops the directive, or
    carries it outside the roll block where Caddy would reject it."""
    block = _log_output_block(path)
    assert re.search(r"^\s*roll_uncompressed\s*$", block, re.MULTILINE), (
        f"{path.name}: the log output block must set `roll_uncompressed` so rolled files stay plain "
        f"JSON; block was:\n{block}")
    # The roll block is still the 7-day debugging tail it always was (this pin adds a format, not a
    # retention change).
    assert re.search(r"roll_keep_for\s+168h", block), f"{path.name}: the 7-day roll retention must stand"


def test_the_aggregator_glob_covers_both_the_plain_and_compressed_roll_families():
    """FOLD-GLOB PIN. The aggregator's log reader must glob the compressed family as well as the plain
    one, so a roll written before `roll_uncompressed` shipped is still salvageable. Behavioural proof
    lives in test_aggregate_stats.py; this is the source-level statement that the pattern exists at
    all. FAILS IF the .gz arm is dropped from the reader."""
    src = _AGG.read_text(encoding="utf-8")
    assert "access*.json.gz" in src, "read_log_lines must glob the compressed rolled family"
    assert "import gzip" in src, "the compressed arm must use the stdlib gzip reader"


@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run ship-frontdoor-logs.sh")
def test_ship_filter_carries_the_compressed_frontdoor_family(tmp_path):
    """SHIP-FILTER PIN. The front-door pull must include `access-frontdoor*.json.gz` as well as the
    plain family: a VPS roll written before `roll_uncompressed` shipped never leaves the VPS otherwise,
    and its 7-day retention then deletes it. Driven black-box with an rsync SHIM that records its argv.
    FAILS IF the compressed include is missing, or if the catch-all exclude is ordered before it (rsync
    filters are first-match-wins, so an exclude ahead of the include would silence it)."""
    import os
    marker = tmp_path / "rsync.argv"
    shim = tmp_path / "rsync.sh"
    shim.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"" + marker.as_posix() + "\"\n",
                    encoding="utf-8")
    shim.chmod(0o755)
    dest = tmp_path / "logs"
    env = {"PATH": os.environ["PATH"],
           "AUSMT_FRONTDOOR_LOG_REMOTE": "caddylog@ausmt-vps:/var/log/caddy",
           "AUSMT_FRONTDOOR_LOG_DEST": str(dest),
           "AUSMT_SHIP_RSYNC": f"sh {shim.as_posix()}",
           "AUSMT_SHIP_SSH": "ssh"}
    r = subprocess.run([_SH, str(_SHIP)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    argv = marker.read_text(encoding="utf-8")
    assert "access-frontdoor*.json.gz" in argv, (
        f"rsync must also pull the compressed rolled front-door family; argv={argv!r}")
    assert "access-frontdoor*.json" in argv, f"the plain family must still be pulled; argv={argv!r}"
    gz_at = argv.index("access-frontdoor*.json.gz")
    excl_at = argv.index("--exclude")
    assert gz_at < excl_at, (
        f"rsync filters are first-match-wins: the .gz include must precede the catch-all exclude; "
        f"argv={argv!r}")
