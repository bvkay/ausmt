"""THE MTCAT SCHEMA VERSION HAS ONE SOURCE, AND THIS IS THE PIN THAT KEEPS IT THAT WAY.

The version used to be a literal, and a literal reproduces. Three consecutive review rounds each found
another hardcoded default: two in build_portal (the no-config/unreadable-config default in
load_portal_config and the emitter's own p.get fallback), a third in load_portal_config's parsed-config
branch, and a fourth in portal/tools/gen_config.py still defaulting to "1.0" two schema releases after
1.0 stopped being true. Patching them one at a time never converged, because nothing in the tree
asserted that the sites agreed, so each fix left the next one undiscovered until a human happened to
read it.

SINGLE SOURCE: engine/schema/mtcat.schema.json's own `title`. The schema is the artifact being
versioned, its `$id` is deliberately unversioned (docs/docs/reference/mtcat-schema.md), and the same
page already tells harvesters that a fetched schema identifies its version through the title. Every
other site derives from there: contract/generate.py:mtcat_schema_version() is the one parser, it emits
MTCAT_SCHEMA_VERSION into engine/extract/_contract.py (the same generated-constant mechanism the
positional column contract uses, gated by `generate.py --check` in both CI lanes), and the four former
default sites read that constant or call that parser.

THIS MODULE reads the version back off every surface that states one, INDEPENDENTLY of the shared
parser (it re-reads the title with its own regex, so the pin cannot agree with itself vacuously), and
asserts they are all the same string:

  1. the schema title                          (the authority)
  2. contract/generate.py:mtcat_schema_version()   (the one parser)
  3. engine/extract/_contract.py                (the generated engine constant)
  4. portal/portal.config.yaml                  (the human-editable portal config)
  5. portal/config.js                           (the generated browser reflection)
  6. portal/data/mtcat.json                     (the committed empty boot document)
  7. portal/tools/gen_config.py build_config()  (a config that OMITS the key: the re-used-portal path)
  8. a REAL BUILD's emitted mtcat.json portal block (the version a harvester is actually served)

plus a guard that forbids the CLASS itself: no MAJOR.MINOR literal may sit next to `schema_version` in
build_portal.py, gen_config.py or version.js ever again.

Two surfaces are pinned elsewhere and deliberately not repeated here: about.html's prose statement, in
portal/tests/test_mtcat_machine_contract.py (the lane that triggers on portal/** and engine/schema/**),
and the ENGINE's re-used-portal path (a real build against a config that omits the key), in
test_mtcat.py, which owns build-emission coverage.

TOPOLOGY (why the portal reads are guarded): surfaces 4-7 live in portal/, a tree the ENGINE IMAGE
deliberately does not ship. deploy/docker/engine.Dockerfile COPYs contract/ and engine/ plus the one
generated file portal/src/contract.js (so `generate.py --check` can verify it) and nothing else, and
deploy-images' engine-full-tests release gate runs THIS suite inside that image, where /app/portal/
holds that single file and none of the five pinned ones. Those reads therefore sit behind a
module-level topology check that skips them when no pinned portal file is present. That is the same
designed-topology skip test_validator_gate.py takes for the absent gateway tree, and its reason is
allow-listed in tests/ci_check_skips.py the same way. What still asserts IN the image: the schema-title
authority, the contract parser, the generated engine constant, the real build's emitted portal block,
and the builder's own literal guard. The image's internal coherence is exactly what the release gate
exists to prove, and none of that needs portal/. On a checkout all five files exist, so the guard is
inert and the pin is not one assertion weaker there; a checkout carrying SOME of them still FAILS on
the missing read, because a broken tree is not a topology. The portal surfaces are pinned from the
CHECKOUT lane:
build-products.yml runs this suite post-checkout and its path filter names all five files (and
engine/**, so this module's own edits trigger it), on push and on pull_request.

RED-proven: restoring the literal "1.0" default in gen_config.build_config fails
test_every_portal_surface_that_states_the_mtcat_version_agrees and
test_no_portal_site_carries_a_version_literal, and nothing else in either suite notices.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
REPO = ROOT.parent                                  # the ausmt monorepo root
SCHEMA_FILE = ROOT / "schema" / "mtcat.schema.json"
BUILDER = ROOT / "extract" / "build_portal.py"
GEN_CONFIG = REPO / "portal" / "tools" / "gen_config.py"
VERSION_JS = REPO / "portal" / "version.js"
PORTAL_CFG = REPO / "portal" / "portal.config.yaml"
CONFIG_JS = REPO / "portal" / "config.js"
PLACEHOLDER = REPO / "portal" / "data" / "mtcat.json"
SURVEYS = HERE / "fixtures"                         # vendored, self-contained (as in test_mtcat.py)

# ---------------------------------------------------------------- which tree is this? (topology)
# The five portal files this module reads. They all exist on any monorepo checkout and NONE of them
# exists in the engine image, whose Dockerfile COPYs contract/ + engine/ and exactly one portal file
# (portal/src/contract.js, the generated browser contract that `generate.py --check` verifies). So the
# presence of the SET is the topology probe, not the presence of portal/ (which the image does have,
# holding that single unrelated file), and not the presence of any one file (a checkout missing one is
# BROKEN, and must fail the read, not skip it).
PORTAL_SURFACES = (PORTAL_CFG, CONFIG_JS, PLACEHOLDER, GEN_CONFIG, VERSION_JS)

IMAGE_TOPOLOGY_SKIP_REASON = ("engine image build: portal tree not shipped "
                              "(designed topology; portal surfaces are pinned from checkout lanes)")

# Skip ONLY when NOT ONE of them is present: that is the image, where these surfaces do not exist to
# disagree. Any one of them present means a portal tree is meant to be here, so the guard opens and a
# missing sibling fails the read loudly (the arm test_validator_gate.py calls a broken checkout).
portal_surface = pytest.mark.skipif(not any(p.is_file() for p in PORTAL_SURFACES),
                                    reason=IMAGE_TOPOLOGY_SKIP_REASON)


# ---------------------------------------------------------------- the surfaces, read one by one

def _authority() -> str:
    """The version as the SCHEMA declares it, parsed here with this module's own regex.

    Deliberately not contract/generate.py's parser: if the pin asked the shared parser what the version
    is and then checked the shared parser's own output against itself, a parser that read the wrong
    field would still pass. This reads the raw title."""
    title = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["title"]
    m = re.match(r"^MTCAT v(\d+\.\d+):", title)
    assert m, f"the schema must declare its version in its title as 'MTCAT v<MAJOR>.<MINOR>: ...'; got {title!r}"
    return m.group(1)


def _shared_parser() -> str:
    sys.path.insert(0, str(REPO / "contract"))
    import generate                                  # the contract package's one MTCAT version parser
    return generate.mtcat_schema_version()


def _generated_engine_constant() -> str:
    sys.path.insert(0, str(ROOT / "extract"))
    import _contract                                 # generated; pure literals, so importing it is cheap
    return _contract.MTCAT_SCHEMA_VERSION


def _portal_config_yaml() -> str:
    m = re.search(r"^\s*schema_version:\s*\"([^\"]+)\"", PORTAL_CFG.read_text(encoding="utf-8"), flags=re.M)
    assert m, f"could not read portal.schema_version from {PORTAL_CFG}"
    return m.group(1)


def _generated_config_js() -> str:
    m = re.search(r"window\.AUSMT_CONFIG\s*=\s*(\{.*\});", CONFIG_JS.read_text(encoding="utf-8"), flags=re.S)
    assert m, f"could not find the AUSMT_CONFIG object in {CONFIG_JS}"
    return json.loads(m.group(1))["schema_version"]


def _placeholder_document() -> str:
    return json.loads(PLACEHOLDER.read_text(encoding="utf-8"))["portal"]["version"]


def _gen_config_default() -> str:
    """gen_config's answer for a portal config that OMITS portal.schema_version: the re-used-portal
    path (NZMT, CanadaMT, ...), and the one this repo's own config never exercises because it declares
    the key. This was the fourth literal, and it rendered the footer chip as MTCAT 1.0."""
    sys.path.insert(0, str(GEN_CONFIG.parent))
    import gen_config
    conf = gen_config.build_config({"portal": {"id": "nzmt", "name": "NZMT", "short_name": "NZMT"}})
    assert conf["name"] == "NZMT", "the config was not read, so this is not the omitted-key path"
    return conf["schema_version"]


# ---------------------------------------------------------------- the pin

def _assert_agrees(want: str, stated: dict):
    """Fail naming every surface that states something other than the authority's value, so a future
    bump cannot half-land and the diagnostic says exactly where it half-landed."""
    disagree = {k: v for k, v in stated.items() if v != want}
    assert not disagree, (
        f"the MTCAT schema version is {want} per engine/schema/mtcat.schema.json's title, but these "
        f"surfaces state something else: {disagree}. Bump the schema title, run "
        f"`python contract/generate.py --write` and `python portal/tools/gen_config.py`, and update "
        f"portal.config.yaml + the committed portal/data/mtcat.json placeholder.")


def test_every_engine_surface_that_states_the_mtcat_version_agrees():
    """Statements 1-3: the authority, the one parser, the generated constant. All three ship in the
    engine image, so this runs there too and the release gate proves the image's own coherence: the
    _contract.py constant baked into it really is what the schema baked in beside it declares."""
    want = _authority()
    _assert_agrees(want, {
        "engine/schema/mtcat.schema.json (title)": want,
        "contract/generate.py mtcat_schema_version()": _shared_parser(),
        "engine/extract/_contract.py MTCAT_SCHEMA_VERSION": _generated_engine_constant(),
    })


@portal_surface
def test_every_portal_surface_that_states_the_mtcat_version_agrees():
    """Statements 4-7, checked against the same authority (the schema title, read here even in the
    image lane's absence of these files, because the authority is an ENGINE file). Skipped where the
    portal tree is not shipped; asserted on every checkout lane, which is where these files change."""
    want = _authority()
    _assert_agrees(want, {
        "portal/portal.config.yaml portal.schema_version": _portal_config_yaml(),
        "portal/config.js AUSMT_CONFIG.schema_version": _generated_config_js(),
        "portal/data/mtcat.json portal.version": _placeholder_document(),
        "portal/tools/gen_config.py build_config() on an omitted key": _gen_config_default(),
    })


def test_the_schema_id_stays_unversioned_so_it_cannot_become_another_surface():
    """The $id is the one place a version could plausibly be reintroduced without anyone calling it a
    duplicate. It is unversioned on purpose (a versioned identifier nobody serves is worse than none),
    and keeping it that way is what leaves the title as the single declaration."""
    schema_id = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["$id"]
    assert not re.search(r"\d+\.\d+", schema_id.rsplit("/", 1)[-1]), (
        f"the schema $id filename must stay unversioned so the title is the only version declaration; "
        f"got {schema_id}")


def _assert_no_version_literal(files):
    """The CLASS guard, applied to whichever of the three sites this topology ships. Every one of the
    four defects was the same shape: a MAJOR.MINOR literal parked beside the word schema_version.
    Forbidding the shape is what stops the fifth one, because the four were not found by reading
    carefully, they were found one per review round."""
    offenders = {}
    for f in files:
        hits = re.findall(r"schema_version[^\n]{0,60}?[\"']\d+\.\d+[\"']", f.read_text(encoding="utf-8"))
        if hits:
            offenders[str(f.relative_to(REPO))] = hits
    assert not offenders, (
        "an MTCAT schema-version literal was reintroduced next to a schema_version default: "
        f"{offenders}. Read it from the single source instead (MTCAT_SCHEMA_VERSION from _contract, "
        "or contract/generate.py's mtcat_schema_version()); version.js, which cannot read the schema "
        "from a browser, must state no version at all rather than a stale one.")


def test_the_builder_carries_no_version_literal():
    """build_portal.py is engine code and ships in the image, so the site that held TWO of the four
    literals is guarded in the release gate as well as on every checkout."""
    _assert_no_version_literal((BUILDER,))


@portal_surface
def test_no_portal_site_carries_a_version_literal():
    """The other two sites of the same class (gen_config.py held the fourth literal, version.js is the
    one that cannot derive the value at all), guarded wherever the portal tree is shipped."""
    _assert_no_version_literal((GEN_CONFIG, VERSION_JS))


@portal_surface
def test_version_js_sentinel_states_no_version_rather_than_a_stale_one():
    """version.js is the one surface that CANNOT derive the version (no build step, no way to read the
    schema at render time), so its config-missing sentinel is honest instead: an explicit null, and a
    label that stops after the schema name. The jsdom driver asserts the rendered chip; this asserts the
    source, so the sentinel cannot quietly grow a number back in a lane that skips when Node is absent."""
    src = VERSION_JS.read_text(encoding="utf-8")
    m = re.search(r"window\.AUSMT_CONFIG\s*\|\|\s*\{([^}]*)\}", src)
    assert m, "version.js must keep a config-missing sentinel object"
    assert re.search(r"schema_version:\s*null", m.group(1)), (
        f"the config-missing sentinel must set schema_version null, not a version; got {{{m.group(1)}}}")


# ---------------------------------------------------------------- the emitted document

def _build(tmp_path):
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(SURVEYS),
                        "--out", str(out), "--no-validate"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads((out / "mtcat.json").read_text(encoding="utf-8"))


def test_a_real_build_stamps_the_schemas_own_version(tmp_path):
    """The surface that actually reaches a harvester. Run the real pipeline and read the version back
    out of the document it wrote, so the pin covers what is PUBLISHED and not merely what is declared."""
    pytest.importorskip("mt_metadata")
    doc = _build(tmp_path)
    assert doc["portal"]["version"] == _authority(), (
        f"a real build stamped MTCAT {doc['portal']['version']!r} into mtcat.json, but the schema it "
        f"serves beside it declares {_authority()!r}")
    served = json.loads((tmp_path / "data" / "mtcat.schema.json").read_text(encoding="utf-8"))
    assert served["title"] == json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))["title"], (
        "the build serves the schema beside the document, so the copy a harvester validates against "
        "must be the one whose title this pin read")
