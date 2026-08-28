"""The self-hosted basemap serving surface (/basemap/ pmtiles files).

The portal's basemap was its last runtime third party: CARTO's raster tiles, which the vendor now
watermarks without a key and is retiring. The self-hosted replacement serves two PMTiles files
(world at low zoom, the Australian region at full detail) as plain static files with HTTP range
requests, so the whole map rides our own edge, cache policy and privacy posture. These pins hold
the serving surface:

  * both box listeners serve /basemap/ from the mounted basemap volume with file_server (range
    requests are what the renderer lives on);
  * the basemap files carry a daily Cache-Control (max-age=86400): they change ~yearly by a
    deliberate re-extract, so daily revalidation is generous, and the no-cache default matcher
    must EXCLUDE /basemap or every range request would revalidate;
  * compose mounts the basemap directory read-only into the portal container;
  * the fetch script that produces the files pins its tooling by version + sha256 and writes
    atomically (tmp then mv), so a torn download can never serve;
  * runtime: the SHIPPED handle block, composed hermetically, answers a Range request with 206
    Partial Content and the pinned Cache-Control (content-agnostic: any bytes prove the wiring).
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BOX = _REPO / "deploy" / "docker" / "caddy" / "Caddyfile"
_COMPOSE = _REPO / "deploy" / "compose.yaml"
_FETCH = _REPO / "deploy" / "scripts" / "fetch-basemap.sh"
_DOCTOR = _REPO / "deploy" / "scripts" / "doctor-box.sh"

from test_frontdoor_bridge import _site_body  # noqa: E402  (house practice: shared harness helpers)

_CADDY = shutil.which("caddy")


def test_both_listeners_serve_basemap_with_daily_cache():
    """FAILS IF either box vhost loses the /basemap handle, its file_server, its daily
    Cache-Control, or lets the no-cache default swallow it (which would put an If-None-Match on
    every tile range request)."""
    text = _BOX.read_text(encoding="utf-8")
    for opener in (r"(?m)^:8080\s*\{", r"(?m)^:8081\s*\{"):
        body = _site_body(text, opener)
        m = re.search(r"handle_path\s+/basemap/\*\s*\{([\s\S]*?)\n\t\}", body)
        assert m, f"{opener}: no handle_path /basemap/* block"
        block = m.group(1)
        assert "/srv/basemap" in block, f"{opener}: /basemap must root at the mounted volume"
        assert "file_server" in block, f"{opener}: /basemap must be a plain file_server"
        assert re.search(r"Cache-Control\s+\"public,\s*max-age=86400\"", block), \
            f"{opener}: basemap files must carry the daily Cache-Control"
        nc = re.search(r"@revalidate\s*\{([^}]*)\}", body)
        assert nc and "/basemap" in nc.group(1), \
            f"{opener}: the no-cache default matcher must exclude /basemap"


def test_compose_mounts_basemap_read_only():
    """FAILS IF the portal container loses the read-only basemap mount the handle serves from."""
    text = _COMPOSE.read_text(encoding="utf-8")
    assert re.search(r"basemap:/srv/basemap:ro", text), \
        "compose.yaml must mount ${AUSMT_DATA_DIR}/basemap read-only at /srv/basemap"


def test_fetch_script_pins_tooling_and_writes_atomically():
    """FAILS IF fetch-basemap.sh stops pinning the pmtiles CLI (version + sha256: an unpinned
    binary download is a supply-chain hole), loses either extract, or writes the served filenames
    directly (a torn download would serve)."""
    text = _FETCH.read_text(encoding="utf-8")
    assert re.search(r"PMTILES_VERSION=", text), "the go-pmtiles version must be pinned"
    assert re.search(r"PMTILES_SHA256[A-Z0-9_]*=", text), "the go-pmtiles binary sha256 must be pinned"
    assert "sha256sum" in text or "shasum" in text, "the downloaded binary must be hash-verified"
    assert re.search(r"extract[\s\S]*maxzoom=6", text), "the world extract (maxzoom 6) is required"
    assert re.search(r"extract[\s\S]*bbox", text), "the region extract (bbox) is required"
    assert "world.pmtiles" in text and "region.pmtiles" in text, \
        "the two served filenames are the contract map.js's config defaults point at"
    assert re.search(r"\.tmp[\s\S]*mv ", text), "extracts must land via tmp then mv (atomic swap)"
    assert "AUSMT_DATA_DIR" in text, "the output root must be the deployment's data dir"


def test_doctor_box_has_the_basemap_leg():
    """FAILS IF doctor-box.sh loses the basemap probe. The leg is provider-aware: a deployment
    still on the carto fallback SKIPs (a missing file is not a fault there), and a pmtiles
    deployment must answer a Range request with 206 (the renderer's whole access pattern)."""
    text = _DOCTOR.read_text(encoding="utf-8")
    assert "check_basemap()" in text, "doctor-box.sh must define check_basemap"
    assert re.search(r"^check_basemap$", text, re.M), "check_basemap must run in the report"
    assert "206" in text, "the leg must demand 206 Partial Content on a Range probe"
    assert "Range" in text or "range" in text, "the probe must be a Range request"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.mark.skipif(_CADDY is None, reason="no caddy binary to run the hermetic serving pin")
def test_shipped_basemap_block_serves_ranges(tmp_path):
    """RUNTIME PIN over the SHIPPED directives: the reader's /basemap block, composed hermetically
    over a dummy file, must answer a Range request with 206, the requested slice, and the daily
    Cache-Control. FAILS IF file_server loses range support (a Caddy or config regression) or the
    header stops riding the response."""
    body = _site_body(_BOX.read_text(encoding="utf-8"), r"(?m)^:8081\s*\{")
    m = re.search(r"(@basemapAssets[\s\S]*?\n)?(\thandle_path\s+/basemap/\*\s*\{[\s\S]*?\n\t\})", body)
    assert m, "could not extract the shipped /basemap block"
    block = m.group(0).replace("/srv/basemap", str(tmp_path / "bm"))
    (tmp_path / "bm").mkdir()
    (tmp_path / "bm" / "region.pmtiles").write_bytes(b"0123456789" * 100)
    port = _free_port()
    cfg = ("{\n\tadmin off\n\tauto_https off\n}\n"
           + f":{port} {{\n" + block + "\n}\n")
    cfgpath = tmp_path / "bm.caddy"
    cfgpath.write_text(cfg, encoding="utf-8")
    v = subprocess.run([_CADDY, "validate", "--adapter", "caddyfile", "--config", str(cfgpath)],
                       capture_output=True, text=True)
    assert v.returncode == 0, f"composed basemap config invalid:\n{v.stdout}\n{v.stderr}\n---\n{cfg}"
    proc = subprocess.Popen([_CADDY, "run", "--adapter", "caddyfile", "--config", str(cfgpath)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        req = urllib.request.Request(f"http://127.0.0.1:{port}/basemap/region.pmtiles",
                                     headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 206, f"a Range request must answer 206, got {r.status}"
            payload = r.read()
            assert payload == b"0123456789", f"wrong slice: {payload!r}"
            cc = r.headers.get("Cache-Control", "")
            assert "max-age=86400" in cc, f"basemap response must carry the daily cache policy, got {cc!r}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
