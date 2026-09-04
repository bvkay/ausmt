"""Station.json emission semantics, pinned against the real emitter over BUILT output.

PERMANENT TEST STAGE (the MTCAT 2.0 rule, inherited by the third public contract): this suite runs on
every later emitter change, so a future feature can never silently move a frozen key, widen a branch,
split the dimensionality call across two surfaces or let a masked position reach a published note.

What this module pins, all of it read off documents a REAL build wrote:

  * THE KEY SETS, on both branches (workflow contract section 2). The full record carries the fourteen
    frozen keys, exactly three promotion markers, the new canonical model where the source supports it
    and the one conditional coordinate key; the withheld stub carries the nine frozen keys plus exactly
    three markers and nothing else. These are the pins that make byte-stability enforceable: before the
    promotion nothing forbade a fifteenth key on either branch.
  * the markers themselves: `schema` names the contract, `version` is the generated constant, and
    `survey_id` is the SLUG, which is what mtcat and survey-metadata.json key on.
  * the dimensionality fold: `diagnostics` and the sidecar state ONE call, from one computation,
    and the withheld branch gains no `diagnostics` at all, which is what keeps the interpretation
    product out of a record whose science is withheld.
  * the NEW blocks carry no null and no empty container. This is scoped to runs[] and resources[] on
    purpose: the frozen keys carry legitimate nulls (remote_site, coordinate_qc, the frame rotation
    sources), so the survey-metadata document's corpus-wide rule cannot be imported here.
  * the leak rejections and, applied to BUILT withheld stubs rather than to a
    hand-written fixture, so what is proven closed is the document the corpus actually publishes.
  * No non-exact station's true position reaches any published free text. The per-station mask
    withholds a masked station's OWN note; nothing stops ANOTHER station's note naming it, and the
    corpus already publishes remote-station coordinates in notes (WG-1-1, where both stations are
    open, so it is not a leak). This is fail-closed protection ahead of the first survey where it
    would be, and it is mutation-proven so it cannot pass by looking in the wrong place.
"""
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                                  # engine/
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(HERE))

from _contract import STATION_SCHEMA_VERSION  # noqa: E402
from test_run_facts import qualify_lemimt  # noqa: E402
from test_station_schema_v01 import validator as schema_validator  # noqa: E402

import _stationcheck as stcheck  # noqa: E402

# The station.json KEY SET on each branch. Frozen = emitted before the promotion and byte-stable
# through 1.x; markers = the three additions; new model = the canonical blocks, which are
# CONDITIONAL because a source that asserts no acquisition fact publishes no runs[]; conditional =
# coordinate_policy, present only for a non-exact station.
FROZEN_FULL_KEYS = ("ausmt_id", "station", "survey", "country", "organisation", "location", "data",
                    "diagnostics", "processing", "distribution", "provenance", "coordinate_qc",
                    "canonical_conditioning", "frame")
FROZEN_WITHHELD_KEYS = ("ausmt_id", "station", "survey", "country", "organisation", "access",
                        "distribution", "withheld", "note")
PROMOTION_MARKERS = ("schema", "version", "survey_id")
NEW_MODEL_KEYS = ("runs", "resources")
CONDITIONAL_FULL_KEYS = ("coordinate_policy",)
# The five members the dimensionality call is made of. `screening_diagnostic` stays sidecar-only: where
# the numbers now sit, the caveat sentence carries that meaning.
FOLDED_DIMENSIONALITY = ("classification", "skew_beta_median_deg", "pct_periods_3d", "method", "note")

_FUT = "2099-01-01"
_ACCESS_CORPUS = {"open-s": "  level: open",
                  "embargo-s": f"  level: embargoed\n  embargo_until: \"{_FUT}\"",
                  "metaonly-s": "  level: metadata_only"}


def _survey_yaml(slug, access_block):
    return (f'schema_version: "0.1"\n'
            f"slug: {slug}\n"
            f'name: "{slug} survey"\n'
            f"country: Australia\n"
            f'organisation: "Example Organisation"\n'
            f'abstract: "engine-produced station-emission fixture"\n'
            f'license: "CC-BY-4.0"\n'
            f"data_type: BBMT\n"
            f"access:\n{access_block}\n")


def _build(surveys: Path, out: Path, *extra):
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
                        "--out", str(out), "--products", str(out / "products"), "--bundle-edi",
                        "--no-validate", *extra], cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _docs(out: Path) -> dict:
    """Every published station record, keyed '<slug>/<station>' - the served path components."""
    return {f"{p.parent.parent.name}/{p.parent.name}": json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((out / "products").glob("*/*/station.json"))}


@pytest.fixture(scope="module")
def built_open(tmp_path_factory):
    """The two vendored packages with DISTINCT slugs (fixtures/filled-survey declares example-survey's
    slug, which collides in the manifest). Both open, so this is the full-branch arm.

    The staged copies gain the LEMIMT logger line: the shipped bytes state only the DECLINED band
    token, so without it no station would publish runs[] and the pins below would go vacuous."""
    pytest.importorskip("mt_metadata")
    root = tmp_path_factory.mktemp("station-emission-open")
    surveys = root / "surveys"
    surveys.mkdir()
    for pkg in ("example-survey", "pid-survey"):
        shutil.copytree(FIXTURES / pkg, surveys / pkg)
        qualify_lemimt(surveys / pkg)
    return _build(surveys, root / "data")


@pytest.fixture(scope="module")
def built_access(tmp_path_factory):
    """One survey per access state, each over the same EDIs: the open control plus the two states that
    emit a withheld stub. Two withheld surveys rather than one because the embargo date is CONDITIONAL
    and metadata_only is the branch that carries a null one."""
    pytest.importorskip("mt_metadata")
    root = tmp_path_factory.mktemp("station-emission-access")
    surveys = root / "surveys"
    surveys.mkdir()
    for slug, access in _ACCESS_CORPUS.items():
        shutil.copytree(FIXTURES / "example-survey", surveys / slug)
        (surveys / slug / "survey.yaml").write_text(_survey_yaml(slug, access), encoding="utf-8")
    return _build(surveys, root / "data")


def _split(out):
    docs = _docs(out)
    full = {k: d for k, d in docs.items() if not d.get("withheld")}
    withheld = {k: d for k, d in docs.items() if d.get("withheld")}
    return full, withheld


# ---------------------------------------------------------------- the key sets (section 2)

def test_the_full_branch_carries_the_frozen_fourteen_the_markers_and_nothing_unaccounted(built_open):
    full, withheld = _split(built_open)
    assert full and not withheld, "fixture sanity: this arm's corpus is all open"
    allowed = set(FROZEN_FULL_KEYS) | set(PROMOTION_MARKERS) | set(NEW_MODEL_KEYS) | set(CONDITIONAL_FULL_KEYS)
    for key, doc in full.items():
        assert set(FROZEN_FULL_KEYS) | set(PROMOTION_MARKERS) <= set(doc), (
            f"{key}: a frozen key or a promotion marker went missing; emitted {sorted(doc)}")
        assert set(doc) <= allowed, (
            f"{key}: an unaccounted top-level key reached the full record: {sorted(set(doc) - allowed)}")
        assert "withheld" not in doc, f"{key}: the withheld marker is schema-forbidden on a full record"


def test_the_withheld_branch_carries_the_frozen_nine_plus_exactly_three_markers(built_access):
    full, withheld = _split(built_access)
    assert len(withheld) == 4 and full, (
        f"fixture sanity: two withheld surveys of two stations plus an open control; got "
        f"{sorted(withheld)} withheld and {sorted(full)} full")
    for key, doc in withheld.items():
        assert set(doc) == set(FROZEN_WITHHELD_KEYS) | set(PROMOTION_MARKERS), (
            f"{key}: the stub carries the nine frozen keys plus the three markers and nothing else; "
            f"emitted {sorted(doc)}")
        assert doc["access"]["served"] is False and doc["distribution"]["edi_available"] is False
        assert doc["distribution"]["edi_path"] is None


def test_the_stub_key_set_is_exactly_what_the_semantic_layer_closes_over():
    """One definition, not two: the emitted stub's key set and the layer's closed world are the same
    twelve names, so a widening of either surfaces here rather than at a deployment gate."""
    assert set(FROZEN_WITHHELD_KEYS) | set(PROMOTION_MARKERS) == set(stcheck.WITHHELD_KEYS)


def test_every_record_opens_with_the_markers_and_survey_id_is_the_slug(built_access):
    docs = _docs(built_access)
    assert docs
    for key, doc in docs.items():
        slug = key.split("/")[0]
        assert doc["schema"] == "ausmt-station"
        assert doc["version"] == STATION_SCHEMA_VERSION, "version is the generated constant, not a literal"
        assert doc["survey_id"] == slug, "survey_id is the slug (D4); a display title is not an identifier"
        assert doc["survey"] != doc["survey_id"], "the display title stays a separate, legacy surface"


# --------------------------------------------------------------- One call, two surfaces

def test_the_fold_and_the_sidecar_state_one_dimensionality_call(built_open):
    """`diagnostics` gains the call, the method string and the caveat, from the SAME computation the
    sidecar reads. The sidecar keeps being written byte-unchanged through 1.x, so the two must
    never be able to disagree.

    what the fold carries is bound to the sidecar; what the sidecar states as null is ABSENT
    here, never copied across."""
    full, _ = _split(built_open)
    for key, doc in full.items():
        slug, station = key.split("/")
        sidecar = json.loads((built_open / "products" / slug / station / "dimensionality.json")
                             .read_text(encoding="utf-8"))
        diagnostics = doc["diagnostics"]
        for member in FOLDED_DIMENSIONALITY:
            if sidecar[member] is None:
                assert member not in diagnostics, f"{key}: {member} is undetermined and must be omitted"
                continue
            assert member in diagnostics, f"{key}: the fold is missing {member}"
            assert diagnostics[member] == sidecar[member], f"{key}: {member} differs between the two surfaces"
        assert "screening_diagnostic" not in diagnostics, (
            "the marker stays sidecar-only; the caveat text carries that meaning where the numbers sit")
        assert sidecar["screening_diagnostic"] is True
        assert not [m for m in FOLDED_DIMENSIONALITY if diagnostics.get(m, "") is None], (
            f"{key}: the fold states absence by omission, so no member of it is ever null")


def test_a_withheld_record_gains_no_diagnostics_and_no_sidecar(built_access):
    """The asymmetry the fold could have collapsed: a withheld station has no dimensionality.json, and
    folding the call in gives it one under another name."""
    _, withheld = _split(built_access)
    for key, doc in withheld.items():
        assert "diagnostics" not in doc, f"{key}: the interpretation product must stay out of a stub"
        slug, station = key.split("/")
        assert not (built_access / "products" / slug / station / "dimensionality.json").exists()


# ---------------------------------------------------------------- the new blocks

def test_the_new_blocks_carry_no_null_and_no_empty_container(built_open):
    for key, doc in _docs(built_open).items():
        assert stcheck._new_block_violations(doc) == [], key


def test_the_open_control_really_publishes_runs_and_resources(built_open):
    """Non-vacuity for every pin above: a corpus whose stations published neither block would satisfy
    the key-set and scan tests without exercising them."""
    full, _ = _split(built_open)
    assert any(d.get("runs") for d in full.values()), "the staged sources state an acquisition fact"
    assert all(d.get("resources") for d in full.values()), "every open station serves an EDI"


def test_a_withheld_record_publishes_neither_block(built_access):
    _, withheld = _split(built_access)
    for key, doc in withheld.items():
        assert not set(NEW_MODEL_KEYS) & set(doc), f"{key}: the stub carries {sorted(set(NEW_MODEL_KEYS) & set(doc))}"


# ---------------------------------------------------------------- the leak rejections

def _leaks():
    """The emission vectors, as mutations of a BUILT stub. Each differs from the emitted document by
    exactly the field under test."""
    return [
        ("T13 injected runs[]", lambda d: d.update({"runs": [{"id": "001"}]})),
        ("T14 injected coordinates", lambda d: d.update({"location": {"lat": -31.0, "lon": 140.0}})),
        ("T28a bare latitude/longitude", lambda d: d.update({"latitude": -31.0, "longitude": 140.0})),
        ("T28b coordinates nested in access", lambda d: d["access"].update({"coords": [-31.0, 140.0]})),
        ("T28c runs under a renamed key", lambda d: d.update({"acquisitions": [{"id": "001"}]})),
        ("T28d a live edi_path", lambda d: d["distribution"].update({"edi_path": "edi/x/y.edi"})),
    ]


def test_a_built_withheld_stub_validates_as_emitted(built_access):
    """The non-vacuity control for the rejections below: the unmutated document must PASS, or every
    mutation would be rejected for a reason that has nothing to do with the leak."""
    _, withheld = _split(built_access)
    v = schema_validator()
    for key, doc in withheld.items():
        assert [e.message for e in v.iter_errors(doc)] == [], key
        assert stcheck.violations(doc) == [], key


@pytest.mark.parametrize("why,mutate", _leaks(), ids=[w for w, _ in _leaks()])
def test_built_withheld_stubs_reject_the_ratified_leaks(built_access, why, mutate):
    _, withheld = _split(built_access)
    assert withheld, "fixture sanity: nothing to mutate"
    v = schema_validator()
    for key, doc in withheld.items():
        leaked = copy.deepcopy(doc)
        mutate(leaked)
        assert list(v.iter_errors(leaked)), f"{key}: the schema accepted {why}"
        assert stcheck.violations(leaked), f"{key}: the semantic layer accepted {why}"


# --------------------------------------------------------------- No masked position in a note

def _coord_fixtures():
    """The coordinate fixtures and their leak-string generator, reused rather than restated."""
    import test_coord_access as c42  # noqa: PLC0415
    return c42


@pytest.fixture(scope="module")
def built_masked(tmp_path_factory):
    """One exact, one generalised and one withheld station in one survey, built stager so
    the positions are distinctive enough to attribute a hit to a policy class."""
    pytest.importorskip("mt_metadata")
    c42 = _coord_fixtures()
    root = tmp_path_factory.mktemp("station-emission-masked")
    surveys = root / "surveys"
    surveys.mkdir()
    c42._stage_survey(surveys, [c42.EXACT, c42.GEN, c42.HID])
    return _build(surveys, root / "data")


def _note_hits(out: Path, values):
    """Every (document, string) where a published free-text member carries one of `values` in any of
    its string forms. Free text is where a coordinate hides: `processing.note` is the >INFO block
    verbatim, `canonical_conditioning` is generated prose, and the two NEW blocks carry token
    extractions out of that same >INFO (a resistance source_value, an instrument model string), so
    they are swept as text too rather than trusted to be numeric."""
    c42 = _coord_fixtures()
    variants = set()
    for value in values:
        variants |= c42._true_value_string_variants(value)
    hits = []
    for key, doc in _docs(out).items():
        texts = [(doc.get("processing") or {}).get("note") or "",
                 json.dumps(doc.get("canonical_conditioning") or []),
                 json.dumps(doc.get("runs") or []),
                 json.dumps(doc.get("resources") or []),
                 (doc.get("note") or "")]
        for text in texts:
            hits += [(key, v) for v in variants if v in text]
    return hits


def test_no_non_exact_position_reaches_any_published_note(built_masked):
    """The coordinate mask is PER STATION: it withholds a masked station's own note, and nothing
    stops a different station's note from naming it (the corpus already publishes a remote station's
    gps_lat/gps_lon that way, in a pair where both stations are open). Fail-closed, ahead of the first
    survey where that pair is not both-open."""
    c42 = _coord_fixtures()
    masked = [c42.GEN["lat"], c42.GEN["lon"], c42.HID["lat"], c42.HID["lon"]]
    hits = _note_hits(built_masked, masked)
    assert not hits, "a masked station's true position reached published free text:\n" + "\n".join(
        f"  {k}: {v}" for k, v in hits)


def test_the_note_sweep_catches_a_planted_position(built_masked, tmp_path):
    """MUTATION PROOF: plant the withheld station's latitude in the EXACT station's note, in a copy of
    the built tree, and the same sweep must find it. Without this the test above passes by reading the
    wrong member as easily as by holding."""
    c42 = _coord_fixtures()
    tree = tmp_path / "planted"
    shutil.copytree(built_masked, tree)
    victim = next(p for p in sorted((tree / "products").glob("*/*/station.json"))
                  if json.loads(p.read_text(encoding="utf-8"))["station"] == c42.EXACT["id"])
    doc = json.loads(victim.read_text(encoding="utf-8"))
    doc["processing"]["note"] = f"remote reference at gps_lat={c42.HID['lat']:.6f}"
    victim.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    assert _note_hits(tree, [c42.HID["lat"]]), "the sweep is blind to a planted position"


def test_the_masked_stations_still_publish_a_record(built_masked):
    """Non-vacuity: the sweep must run over documents that exist, and a masked station's record is
    published with its position masked rather than withheld altogether."""
    docs = _docs(built_masked)
    c42 = _coord_fixtures()
    by_station = {d["station"]: d for d in docs.values()}
    assert set(by_station) == {c42.EXACT["id"], c42.GEN["id"], c42.HID["id"]}, sorted(by_station)
    assert by_station[c42.GEN["id"]]["coordinate_policy"] == "generalised"
    assert by_station[c42.HID["id"]]["coordinate_policy"] == "withheld"
    assert by_station[c42.HID["id"]]["location"] == {"lat": None, "lon": None}


# --------------------------------------------------------------- X archives are containment

def test_a_masked_station_advertises_no_archive_it_put_no_bytes_into(built_masked):
    """An `archive` row is a CONTAINMENT claim, and the byte gate decides containment per station: a
    generalised or withheld station's EDI and EMTF XML are withheld, so its bytes are in neither
    survey zip even though its survey publishes both.

    FAILS against the pre-fix emitter, which merged the survey's bundle rows into every station of a
    served survey: the two masked stations published `edi-zip` and `xml-zip` while the manifest
    recorded n_stations 1 for each, counting the exact station alone."""
    c42 = _coord_fixtures()
    by_station = {d["station"]: d for d in _docs(built_masked).values()}
    assert [r["id"] for r in by_station[c42.EXACT["id"]]["resources"]] == \
        ["edi", "emtfxml", "edi-zip", "xml-zip"], "non-vacuity: the served station is in both zips"
    for station in (c42.GEN["id"], c42.HID["id"]):
        assert by_station[station].get("resources", []) == [], (
            f"{station} serves no bytes, so it is in no bundle and has nothing to describe: "
            f"{by_station[station].get('resources')}")


def test_every_archive_row_is_counted_by_the_bundle_it_names(built_masked):
    """The manifest's `n_stations` is the bundle's own count of what went into it, so it is the
    independent arithmetic: exactly that many records may advertise the bundle. Reads the manifest
    rather than the emitter's constants, so an emitter that over-advertises cannot also move the
    number it is checked against."""
    man = json.loads((built_masked / "manifest.json").read_text(encoding="utf-8"))
    docs = _docs(built_masked)
    assert man["bundles"], "non-vacuity: this arm builds bundles"
    for bundle in man["bundles"]:
        row_id = {"mth5": "survey-mth5"}.get(bundle["format"], bundle["format"])
        advertisers = [key for key, doc in docs.items()
                       if key.split("/")[0] == bundle["slug"]
                       and row_id in {r["id"] for r in doc.get("resources", [])}]
        assert len(advertisers) == bundle["n_stations"], (
            f"{bundle['slug']} {row_id}: {len(advertisers)} record(s) claim to be in a bundle "
            f"holding {bundle['n_stations']} station(s): {sorted(advertisers)}")


# ---------------------------------------------------------------- the shipped schema, over built output

@pytest.mark.parametrize("arm", ["built_open", "built_access", "built_masked"])
def test_every_built_document_validates_with_format_checking(arm, request):
    out = request.getfixturevalue(arm)
    v = schema_validator()
    for key, doc in _docs(out).items():
        errs = [f"{list(e.path)}: {e.message}" for e in v.iter_errors(doc)]
        assert not errs, f"{key}: {errs}"
