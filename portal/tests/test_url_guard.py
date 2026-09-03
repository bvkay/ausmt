"""Section 4 - the client's two URL/HTML allowlist edges, via their node driver
(tools/url_guard_test.js, the fetch_bounded/coord_access driver pattern).

Both surfaces are decisions rather than renders, so the driver runs them over a vector table against
the SHIPPED src/security.js and src/map.js: escUrl is called directly, and userLayer is extracted by
name and driven with hostile GeoJSON through a stub Leaflet.

It FAILS if:
- an allowlisted form stops working: an absolute http(s)/mailto target, a fragment, the site root, or
  a same-origin path such as /data/catalogue.json or a /go/ts/... hand-off route;
- an off-allowlist form stops collapsing to "#": javascript: (including the leading-whitespace and
  upper-case variants), data:, vbscript:, a protocol-relative //host, or the backslash authority
  /\\host that an http(s) URL parser folds to the same off-site host;
- the map layer attribution reaches Leaflet's addAttribution unescaped. That path is DORMANT (the
  layer control is not mounted), so the pin exists to hold the guard until a revisit.

Skips if Node is unavailable (CI installs Node - see .github/workflows/portal-ci.yml)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent                 # portal/
DRIVER = ROOT / "tools" / "url_guard_test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_url_guard_vectors():
    assert DRIVER.exists(), "tools/url_guard_test.js missing"
    r = subprocess.run(["node", str(DRIVER)], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    out = r.stdout + r.stderr
    assert r.returncode == 0, f"url-guard driver failed:\n{out}"
    assert "URL GUARD OK" in r.stdout, out
