"""Which served paths are forced to DOWNLOAD rather than render inline (the box Caddyfile).

The byte-payload families are served with `Content-Disposition: attachment` so a browser saves them
instead of rendering them (XML in particular renders inline otherwise). The matcher is evaluated AFTER
`handle_path /data/*` has stripped the prefix, so it is written against the path BELOW /data.

This is where the release tier was missed. `/data/releases/<tag>/bundles/<file>` presents to the
matcher as `/releases/<tag>/bundles/<file>`, which none of the four original patterns cover, so the
frozen citable copy of a bundle rendered inline while its mutable twin under `/data/bundles/`
downloaded. Same missing-prefix root cause as the analytics gap in the same tier, so it is fixed and
pinned in the same lane.

The two listeners (`:8080` tailnet reader, `:8081` public subset) carry the SAME matcher by design and
the second one's comment says so, so the pin holds them equal rather than checking one and trusting
the other. Pure text over the committed Caddyfile: no caddy binary, runs everywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BOX_CADDY = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"

# The families a browser must never render inline: original EDI, derived EMTF-XML, the packaged
# bundles, the latent /h5 path, and the frozen release bundles.
_REQUIRED_PATTERNS = ("/edi/*", "/xml/*", "/bundles/*", "/h5/*", "/releases/*/bundles/*")


def _download_matchers() -> list[list[str]]:
    """The path list of every `@download path ...` matcher in the Caddyfile, one entry per listener."""
    text = _BOX_CADDY.read_text(encoding="utf-8")
    found = re.findall(r"^\s*@download\s+path\s+(.+)$", text, re.MULTILINE)
    assert found, "the Caddyfile must declare an `@download path ...` matcher"
    return [line.split() for line in found]


def test_every_byte_payload_family_including_release_bundles_is_forced_to_download():
    """FORCE-DOWNLOAD PIN. Every byte-payload family must be matched for
    `Content-Disposition: attachment`, INCLUDING the release-tier bundles. The matcher runs after
    `handle_path /data/*` strips the prefix, so a release path arrives as /releases/<tag>/bundles/...
    and needs its own pattern; without it the citable frozen copy renders inline in the browser.
    FAILS IF any family is missing from any listener's matcher."""
    matchers = _download_matchers()
    for paths in matchers:
        for pattern in _REQUIRED_PATTERNS:
            assert pattern in paths, (
                f"the force-download matcher must cover {pattern}; it had {paths}")


def test_both_listeners_force_download_identically():
    """LISTENER PARITY PIN. The :8080 reader and the :8081 public subset serve the same /data tree and
    the second's comment states it is identical to the first, so their force-download matchers must
    agree exactly. FAILS IF one listener gains a family the other lacks, which would make a file
    download over the tailnet and render inline in public (or the reverse)."""
    matchers = _download_matchers()
    assert len(matchers) >= 2, f"both /data listeners must carry the matcher; found {len(matchers)}"
    first = matchers[0]
    for other in matchers[1:]:
        assert other == first, f"listener matchers diverged: {first} vs {other}"
