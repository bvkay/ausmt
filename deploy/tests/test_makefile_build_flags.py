"""The flags that actually reach a production build.

THE FLAG-REACHES-PRODUCTION TRAP, which this repository has now walked into twice. A distribution
producer is gated two ways: `flags:` in `portal/portal.config.yaml`, and a CLI flag on the engine.
Only one of those two reaches a box.

`deploy/docker/engine.Dockerfile` copies `contract/`, `engine/` and exactly one portal file
(`portal/src/contract.js`). `portal/portal.config.yaml` is NOT in the image, so `load_flags()` inside
the build container reads a path that does not exist, returns its OFF defaults, and every flag set in
that YAML is a production no-op. The enable that works is the CLI flag on `deploy/Makefile`'s
`rebuild-data` recipe, which is where `--survey-h5` lives and why the Makefile comment above it calls
that line its single source of truth.

The failure mode is silent in the worst way: the config says the feature is on, the portal's generated
`config.js` says it is on, the engine's own default is off, the box quietly serves nothing, and no test
anywhere is red. So the wiring is pinned here rather than reviewed.

Two directions, because either alone can pass over a broken lane:

  * every producer flag named below must appear on the rebuild-data invocation, or the producer never
    runs in production;
  * every producer flag named below must be a real option of the engine CLI, or the Makefile is
    passing an argument argparse will reject and the nightly rebuild fails outright.

Plus the premise itself: the Dockerfile must still be excluding portal.config.yaml from the image. If
a future change starts baking it in, the reasoning above stops holding and this module should be
rewritten rather than quietly kept passing.

Pure stdlib, reads committed files only. Runs everywhere.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_MAKEFILE = _REPO / "deploy" / "Makefile"
_DOCKERFILE = _REPO / "deploy" / "docker" / "engine.Dockerfile"
_BUILDER = _REPO / "engine" / "extract" / "build_portal.py"

# The flags that gate a DISTRIBUTION PRODUCER: each one decides whether bytes exist for users to
# download. A flag that only changes build mechanics (--incremental, --cache-mode) is deliberately not
# in this list; its absence costs speed, not products.
_PRODUCER_FLAGS = ("--bundle-edi", "--survey-h5", "--station-h5")


def _rebuild_data_recipe() -> str:
    """The body of the `rebuild-data:` target: every line from the target through the last of its
    tab-indented / backslash-continued recipe lines. Parsed rather than string-searched over the whole
    file so a flag mentioned only in a comment somewhere else in the Makefile cannot satisfy the pin."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    m = re.search(r"^rebuild-data:.*?$(?P<body>(?:\n(?:\t.*|)$)*)", text, flags=re.M | re.S)
    assert m, "deploy/Makefile no longer defines a rebuild-data target"
    body = m.group("body")
    assert "build-runner" in body, "the rebuild-data recipe no longer invokes the build-runner"
    return body


def _engine_cli_options() -> set[str]:
    """Every long option engine/extract/build_portal.py's argparse defines."""
    src = _BUILDER.read_text(encoding="utf-8")
    opts = set(re.findall(r'ap\.add_argument\(\s*"(--[a-z0-9-]+)"', src))
    assert opts, "no argparse options parsed out of build_portal.py; the parse has drifted"
    return opts


def test_every_producer_flag_is_wired_into_rebuild_data():
    """FAILS IF a distribution producer is enabled only in portal.config.yaml. That YAML never enters
    the engine image, so the box would build without the producer, serve nothing for it, and look
    exactly like a healthy build while doing so."""
    recipe = _rebuild_data_recipe()
    missing = [f for f in _PRODUCER_FLAGS if f not in recipe]
    assert not missing, (
        f"deploy/Makefile's rebuild-data does not pass {missing}. The portal.config.yaml flag alone is "
        f"a production no-op: engine.Dockerfile does not copy that file, so load_flags() falls back to "
        f"its OFF defaults inside the build container.")


def test_every_wired_flag_is_a_real_engine_option():
    """The other direction. FAILS IF the Makefile passes an option argparse does not define, which
    aborts the nightly rebuild with a usage error instead of producing a build."""
    opts = _engine_cli_options()
    unknown = [f for f in _PRODUCER_FLAGS if f not in opts]
    assert not unknown, (
        f"deploy/Makefile passes {unknown}, which build_portal.py's CLI does not define; the build "
        f"would exit on a usage error")


def test_the_engine_image_still_excludes_the_portal_config():
    """The PREMISE of the two pins above. The engine image copies contract/, engine/ and one generated
    portal file; portal.config.yaml is not among them, which is exactly why the CLI flag is the
    production enable. FAILS IF the image starts baking the config in, at which point the reasoning
    changes and this module needs rewriting rather than relaxing."""
    copied = re.findall(r"^COPY\s+(.+)$", _DOCKERFILE.read_text(encoding="utf-8"), flags=re.M)
    assert copied, "no COPY lines parsed out of engine.Dockerfile"
    assert not any("portal.config.yaml" in line for line in copied), (
        "engine.Dockerfile now copies portal.config.yaml into the engine image. If the config really "
        "does reach a box build, rewrite this module; do not delete the flag pins.")
