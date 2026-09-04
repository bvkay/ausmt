"""cut_release: the quarterly citable snapshot tool (engine/extract/cut_release.py).

These tests are PURE (no mt_metadata, no mth5, no network): they build a fixture site-data root by
hand, which is exactly the shape rebuild-data leaves behind (builds/<ts>/ + a `current` symlink), and
drive the CLI entry point against it.

NON-VACUOUS (Invariant 10) where it matters. The two RED-proven gates below are checked against an
INDEPENDENT observable, not against a value the tool wrote:
  * the sha256 gate re-hashes the bytes that actually landed in the release dir and compares them to
    the manifest's own claim, so a doctored manifest (or corrupted bytes) cannot pass;
  * the duplicate-tag guard is checked by the release dir EXISTING on disk before the second cut.
Both were confirmed RED by neutering the guard in the implementation and watching these fail.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import cut_release as cr   # noqa: E402

_BUILD_TS = "20260728T010203Z"
_BUNDLE_BYTES = b"PK\x03\x04 pretend this is a survey edi zip"
_H5_BYTES = b"\x89HDF\r\n\x1a\n pretend this is a survey mth5"


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _mtcat_v11():
    """A v1.1-shaped payload: two surveys, one with its own DOI plus a DOI-typed related identifier,
    one with neither (no related_identifiers key at all, the byte-identical posture the build uses
    for a survey that declares no relations)."""
    return {
        "portal": {"portal_id": "ausmt", "portal_name": "AusMT", "schema": "mtcat",
                   "version": "1.1", "generated_at": "2026-07-28T01:02:03Z"},
        "surveys": [
            {"survey_id": "demo", "title": "Demo Survey", "organisation": "AuScope",
             "country": "Australia", "doi": "10.5555/demo-survey", "license": "CC-BY-4.0",
             "related_identifiers": [
                 {"identifier": "https://doi.org/10.25914/sv5r-zw68", "identifier_type": "DOI",
                  "relation": "IsDerivedFrom", "custodian": "NCI"},
                 {"identifier": "https://example.org/not-a-doi", "identifier_type": "URL",
                  "relation": "IsDocumentedBy", "custodian": None}]},
            {"survey_id": "plain", "title": "Plain Survey", "organisation": "AuScope",
             "country": "Australia", "doi": None, "license": "CC0-1.0"},
        ],
        "stations": [
            {"station_id": "au.demo.A1", "survey_id": "demo", "latitude": -30.1,
             "longitude": 137.0, "data_type": "BBMT"},
            {"station_id": "au.demo.A2", "survey_id": "demo", "latitude": -30.2,
             "longitude": 137.1, "data_type": "BBMT"},
            {"station_id": "au.plain.B1", "survey_id": "plain", "latitude": -31.0,
             "longitude": 138.0, "data_type": "LPMT"},
        ],
        "collections": [],
    }


def _manifest(bundle_sha, h5_sha):
    return {
        "generated_count": 3,
        "base_url": "",
        "files": [
            {"ausmt_id": "au.demo.A1", "survey": "Demo Survey", "station": "A1", "format": "edi",
             "url": "edi/demo/A1.edi", "size": 120, "sha256": "a" * 64, "tier": "repo",
             "license": "CC-BY-4.0", "canon_license": "CC-BY-4.0", "custodian": "AuScope"},
        ],
        "bundles": [
            {"survey": "Demo Survey", "slug": "demo", "format": "edi-zip",
             "url": "bundles/demo-edi.zip", "size": len(_BUNDLE_BYTES), "sha256": bundle_sha,
             "tier": "repo", "license": "CC-BY-4.0", "canon_license": "CC-BY-4.0",
             "custodian": "AuScope", "n_stations": 2},
            {"survey": "Plain Survey", "slug": "plain", "format": "mth5",
             "url": "bundles/plain-tf.h5", "size": len(_H5_BYTES), "sha256": h5_sha,
             "tier": "repo", "license": "CC0-1.0", "canon_license": "CC0-1.0",
             "custodian": "AuScope", "n_stations": 1},
        ],
    }


def _data_root(tmp_path, mtcat=None, manifest=None, source_commit="cafed00d"):
    """A fixture site-data root in the exact shape rebuild-data leaves: builds/<ts>/ holding the
    served catalogue surface + bundles/, and a RELATIVE `current` symlink pointing at it."""
    root = tmp_path / "site-data"
    build = root / "builds" / _BUILD_TS
    (build / "bundles").mkdir(parents=True)
    (build / "bundles" / "demo-edi.zip").write_bytes(_BUNDLE_BYTES)
    (build / "bundles" / "plain-tf.h5").write_bytes(_H5_BYTES)
    # A sidecar the build emits beside a bundle but does NOT index in the manifest; it must be copied
    # and hashed into files[] without the verifier demanding a claim for it.
    (build / "bundles" / "plain-tf.LICENSE.txt").write_text("CC0-1.0\n", encoding="utf-8")

    mtcat = _mtcat_v11() if mtcat is None else mtcat
    manifest = _manifest(_sha(_BUNDLE_BYTES), _sha(_H5_BYTES)) if manifest is None else manifest
    (build / "mtcat.json").write_text(json.dumps(mtcat), encoding="utf-8")
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (build / "surveys.json").write_text(json.dumps({"Demo Survey": {"org": "AuScope"}}),
                                        encoding="utf-8")
    (build / "build.json").write_text(json.dumps(
        {"build_id": f"eng123-{source_commit}-2026-07-28T01:02:03Z", "engine_commit": "eng123",
         "source_commit": source_commit, "generated": "2026-07-28T01:02:03Z"}), encoding="utf-8")
    (root / "current").symlink_to(Path("builds") / _BUILD_TS)
    return root


def _cut(root, tag="2026-Q3", *extra):
    return cr.main(["--data", str(root), "--tag", tag, *extra])


def _release(root, tag="2026-Q3"):
    return json.loads((root / "releases" / tag / "release.json").read_text(encoding="utf-8"))


def _datacite(root, tag="2026-Q3"):
    return json.loads((root / "releases" / tag / "datacite.json").read_text(encoding="utf-8"))


def _index(root):
    return json.loads((root / "releases" / "releases.json").read_text(encoding="utf-8"))


# --- the happy cut ---------------------------------------------------------------------------------

def test_cut_writes_the_release_dir(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    rel = root / "releases" / "2026-Q3"
    for name in ("mtcat.json", "surveys.json", "manifest.json", "release.json", "datacite.json"):
        assert (rel / name).is_file(), name
    assert (rel / "bundles" / "demo-edi.zip").read_bytes() == _BUNDLE_BYTES
    assert (rel / "bundles" / "plain-tf.h5").read_bytes() == _H5_BYTES
    assert (rel / "bundles" / "plain-tf.LICENSE.txt").is_file()


def test_release_json_carries_identity_counts_and_digests(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q3", "--note", "first citable snapshot") == 0
    doc = _release(root)
    assert doc["tag"] == "2026-Q3"
    assert doc["build_id"] == "eng123-cafed00d-2026-07-28T01:02:03Z"
    assert doc["engine_commit"] == "eng123"
    assert doc["source_commit"] == "cafed00d"
    assert doc["n_surveys"] == 2 and doc["n_stations"] == 3
    assert doc["doi"] is None
    assert doc["note"] == "first citable snapshot"
    # cut_at carries BOTH clocks: when the bytes were built and when they were frozen.
    assert doc["cut_at"]["build_generated"] == "2026-07-28T01:02:03Z"
    assert doc["cut_at"]["cut"].endswith("Z")
    by_path = {f["path"]: f for f in doc["files"]}
    assert set(by_path) == {"mtcat.json", "surveys.json", "manifest.json",
                            "bundles/demo-edi.zip", "bundles/plain-tf.h5",
                            "bundles/plain-tf.LICENSE.txt"}
    assert by_path["bundles/demo-edi.zip"]["sha256"] == _sha(_BUNDLE_BYTES)
    assert by_path["bundles/demo-edi.zip"]["size"] == len(_BUNDLE_BYTES)
    assert doc["files"] == sorted(doc["files"], key=lambda f: f["path"]), "stable files[] order"


def test_index_is_newest_first(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q2") == 0
    assert _cut(root, "2026-Q3") == 0
    rows = _index(root)["releases"]
    assert [r["tag"] for r in rows] == ["2026-Q3", "2026-Q2"], rows
    assert rows[0]["path"] == "releases/2026-Q3/"
    assert rows[0]["doi"] is None


def test_cut_prints_the_corpus_tag_commands_and_never_runs_git(tmp_path, capsys):
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q3", "--surveys-live", "/srv/ausmt/surveys-live") == 0
    out = capsys.readouterr().out
    assert "git -C /srv/ausmt/surveys-live tag ausmt-release-2026-Q3 cafed00d" in out
    assert "git -C /srv/ausmt/surveys-live push origin ausmt-release-2026-Q3" in out
    # The corpus is untouched: the tool has no git write path at all.
    assert not (root / ".git").exists()


def test_cut_without_source_commit_says_so_instead_of_printing_a_broken_tag(tmp_path, capsys):
    root = _data_root(tmp_path, source_commit=None)
    assert _cut(root) == 0
    out = capsys.readouterr().out
    assert "no source_commit" in out
    assert "git -C" not in out.split("Tag the corpus")[1]


# --- RED-proven gate 1: the sha256 verification blocks the cut --------------------------------------

def test_sha256_mismatch_blocks_the_cut(tmp_path, capsys):
    """RED-PROVEN. Doctor ONE bundle's recorded sha256 so the manifest disagrees with the bytes on
    disk (the corrupted/tampered-artifact shape). The cut must FAIL and leave NO release behind: a
    half-cut release would both look citable and block the retry via the idempotence guard."""
    root = _data_root(tmp_path, manifest=_manifest("0" * 64, _sha(_H5_BYTES)))
    rc = _cut(root)
    assert rc != 0
    err = capsys.readouterr().err
    assert "integrity check FAILED" in err
    assert "bundles/demo-edi.zip" in err
    assert not (root / "releases" / "2026-Q3").exists(), "a failed cut must leave nothing behind"


def test_corrupted_bytes_block_the_cut(tmp_path, capsys):
    """The same gate from the other side: the manifest is honest and the BYTES are wrong. Proves the
    check is a real recomputation over the copied file, not a manifest-internal comparison."""
    root = _data_root(tmp_path)
    (root / "builds" / _BUILD_TS / "bundles" / "plain-tf.h5").write_bytes(b"corrupted")
    assert _cut(root) != 0
    assert "bundles/plain-tf.h5" in capsys.readouterr().err
    assert not (root / "releases" / "2026-Q3").exists()


def test_manifest_bundle_missing_from_the_build_blocks_the_cut(tmp_path, capsys):
    """A repo-tier bundle the manifest advertises but the build never wrote: shipping the release
    anyway would hand a citing reader a 404 from a document that claims the file exists."""
    root = _data_root(tmp_path)
    (root / "builds" / _BUILD_TS / "bundles" / "plain-tf.h5").unlink()
    assert _cut(root) != 0
    err = capsys.readouterr().err
    assert "bundles/plain-tf.h5" in err and "absent from the build" in err
    assert not (root / "releases" / "2026-Q3").exists()


def test_nci_tier_bundles_are_not_demanded_locally(tmp_path):
    """A tier=nci bundle's bytes live at NCI, never in the build dir, so it is neither copied nor
    verified. Without the tier filter this cut would fail on a perfectly healthy build."""
    man = _manifest(_sha(_BUNDLE_BYTES), _sha(_H5_BYTES))
    man["bundles"].append({"survey": "Remote", "slug": "remote", "format": "edi-zip",
                           "url": "https://thredds.nci.org.au/x/bundles/remote-edi.zip",
                           "size": 10, "sha256": "b" * 64, "tier": "nci", "license": "CC-BY-4.0",
                           "n_stations": 1})
    root = _data_root(tmp_path, manifest=man)
    assert _cut(root) == 0


# --- RED-proven gate 2: duplicate-tag refusal -------------------------------------------------------

def test_duplicate_tag_is_refused(tmp_path, capsys):
    """RED-PROVEN. The second cut of a tag that ALREADY EXISTS ON DISK must fail loudly and leave the
    first release byte-identical. A cut release is immutable: something may already cite it."""
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    before = (root / "releases" / "2026-Q3" / "release.json").read_bytes()
    capsys.readouterr()

    assert (root / "releases" / "2026-Q3").is_dir()      # the independent observable
    assert _cut(root) != 0
    err = capsys.readouterr().err
    assert "already exists" in err and "2026-Q3" in err
    assert (root / "releases" / "2026-Q3" / "release.json").read_bytes() == before


def test_a_different_tag_from_the_same_build_is_allowed(tmp_path):
    """The guard is per-tag, not per-build: re-cutting the same build under a new tag is legitimate."""
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q3") == 0
    assert _cut(root, "2026-Q4") == 0


# --- refusals that are not about tags ---------------------------------------------------------------

def test_missing_current_build_is_refused(tmp_path, capsys):
    root = _data_root(tmp_path)
    (root / "current").unlink()
    assert _cut(root) != 0
    assert "no current build" in capsys.readouterr().err


def test_build_without_build_json_is_refused(tmp_path, capsys):
    root = _data_root(tmp_path)
    (root / "builds" / _BUILD_TS / "build.json").unlink()
    assert _cut(root) != 0
    assert "build.json" in capsys.readouterr().err


def test_unsafe_tag_is_refused(tmp_path, capsys):
    root = _data_root(tmp_path)
    assert _cut(root, "../escape") != 0
    assert "invalid --tag" in capsys.readouterr().err
    assert not (tmp_path / "escape").exists()


# --- the DataCite emitter ----------------------------------------------------------------------------

def test_datacite_carries_the_required_kernel4_fields(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    dc = _datacite(root)
    assert dc["schemaVersion"] == "http://datacite.org/schema/kernel-4"
    assert dc["titles"] == [{"title": "AusMT Data Portal, Release 2026-Q3"}]
    assert dc["publisher"] == "AuScope"
    assert isinstance(dc["publicationYear"], int) and dc["publicationYear"] >= 2026
    assert dc["version"] == "2026-Q3"
    assert dc["types"]["resourceTypeGeneral"] == "Dataset"
    assert {c["name"] for c in dc["creators"]} == {"AuScope", "AusMT contributors"}
    assert dc["dates"][0]["dateType"] == "Created"


def test_datacite_contributors_include_ausmt_as_hosting_institution(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    hosts = [c for c in _datacite(root)["contributors"]
             if c.get("contributorType") == "HostingInstitution"]
    assert [h["name"] for h in hosts] == ["AusMT"]


def test_datacite_rights_are_derived_from_the_manifest_plus_metadata_cc0(tmp_path):
    """rightsList states what the corpus IS licensed under this quarter (read off the manifest rows),
    with the catalogue-metadata row always present."""
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    dc = _datacite(root)
    ids = [r["rights"] for r in dc["rightsList"]]
    assert "CC-BY-4.0" in ids and "CC0-1.0" in ids
    cc_by = next(r for r in dc["rightsList"] if r["rights"] == "CC-BY-4.0")
    assert cc_by["rightsIdentifierScheme"] == "SPDX"
    assert cc_by["rightsUri"].startswith("https://creativecommons.org/licenses/by/4.0")
    blurb = " ".join(d["description"] for d in dc["descriptions"])
    assert "Licences vary by survey" in blurb and "CC-BY-4.0 is predominant" in blurb


def test_datacite_sizes_and_formats_are_summarised_from_the_manifest(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    dc = _datacite(root)
    assert dc["sizes"] == ["3 files", f"{120 + len(_BUNDLE_BYTES) + len(_H5_BYTES)} bytes"]
    assert dc["formats"] == ["edi", "edi-zip", "mth5"]


def test_datacite_haspart_rows_come_from_the_mtcat_dois(tmp_path):
    """Every DOI-typed identifier the catalogue points at becomes a HasPart row, resolver prefixes
    normalised away; a URL-typed related identifier is NOT a DOI and must not appear."""
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    parts = [r["relatedIdentifier"] for r in _datacite(root)["relatedIdentifiers"]
             if r["relationType"] == "HasPart"]
    assert parts == ["10.5555/demo-survey", "10.25914/sv5r-zw68"], parts
    assert all(r["relatedIdentifierType"] == "DOI"
               for r in _datacite(root)["relatedIdentifiers"])


def test_datacite_omits_the_identifier_while_the_doi_is_null(tmp_path):
    """Nothing is minted yet, so the record must carry NO doi and NO identifiers key. An empty or
    null identifier would be a rejected submission and a claim about a DOI that does not exist."""
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    dc = _datacite(root)
    assert "doi" not in dc and "identifiers" not in dc
    assert all(r["relatedIdentifier"] for r in dc["relatedIdentifiers"])


def test_datacite_has_no_isnewversionof_without_a_prior_minted_release(tmp_path):
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q2") == 0
    assert _cut(root, "2026-Q3") == 0
    rels = {r["relationType"] for r in _datacite(root, "2026-Q3")["relatedIdentifiers"]}
    assert "IsNewVersionOf" not in rels, "a prior release with doi=null must contribute nothing"


def test_datacite_chains_isnewversionof_to_the_last_minted_release(tmp_path):
    """The first quarter is minted and the second is not; the third must chain past the un-minted
    second to the first quarter's real DOI."""
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q1") == 0
    assert cr.main(["--data", str(root), "--tag", "2026-Q1", "--doi", "10.5555/rel-q1"]) == 0
    assert _cut(root, "2026-Q2") == 0
    assert _cut(root, "2026-Q3") == 0
    rows = [r for r in _datacite(root, "2026-Q3")["relatedIdentifiers"]
            if r["relationType"] == "IsNewVersionOf"]
    assert [r["relatedIdentifier"] for r in rows] == ["10.5555/rel-q1"], rows


# --- the --doi backfill --------------------------------------------------------------------------

def test_doi_backfill_updates_release_and_datacite(tmp_path):
    """The post-minting path: --doi on an EXISTING tag stamps release.json, regenerates datacite.json
    with the identifier, and updates the index row, WITHOUT re-copying or re-digesting the data."""
    root = _data_root(tmp_path)
    assert _cut(root) == 0
    files_before = _release(root)["files"]
    assert "doi" not in _datacite(root)

    assert cr.main(["--data", str(root), "--tag", "2026-Q3",
                    "--doi", "https://doi.org/10.5555/rel-q3"]) == 0

    rel = _release(root)
    assert rel["doi"] == "10.5555/rel-q3", "the resolver prefix is normalised away"
    assert rel["doi_stamped_at"].endswith("Z")
    assert rel["files"] == files_before, "frozen data is never re-cut by a backfill"

    dc = _datacite(root)
    assert dc["doi"] == "10.5555/rel-q3"
    assert dc["identifiers"] == [{"identifier": "10.5555/rel-q3", "identifierType": "DOI"}]
    assert _index(root)["releases"][0]["doi"] == "10.5555/rel-q3"


def test_doi_at_cut_time_is_recorded_immediately(tmp_path):
    """A tag minted BEFORE the cut (the happy future case) needs no backfill."""
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q3", "--doi", "10.5555/rel-q3") == 0
    assert _release(root)["doi"] == "10.5555/rel-q3"
    assert _datacite(root)["doi"] == "10.5555/rel-q3"


def test_doi_on_an_unknown_tag_cuts_a_new_release_rather_than_erroring(tmp_path):
    """PINS THE TRADE-OFF, so a future change to it is a deliberate one. --doi selects the backfill
    path ONLY when the tag already exists; on an unknown tag it is an ordinary cut that happens to
    know its DOI up front (the steady state once minting is routine). The cost is that a typo'd
    --tag cuts a new release instead of erroring; the idempotence guard cannot help there, because a
    tag that does not exist is exactly what a first cut looks like."""
    root = _data_root(tmp_path)
    assert _cut(root, "2026-Q3") == 0
    assert cr.main(["--data", str(root), "--tag", "2026-Q9", "--doi", "10.5555/x"]) == 0
    assert _release(root, "2026-Q9")["doi"] == "10.5555/x"
    assert [r["tag"] for r in _index(root)["releases"]] == ["2026-Q9", "2026-Q3"]


# --- mtcat version tolerance -------------------------------------------------------------------------

def test_mtcat_v12_shaped_payload_cuts_identically(tmp_path):
    """The v1.2 branch adds derived fields; this tool must never assume them AND never trip over
    them. Same DOI set out of a payload carrying extra keys the tool has never heard of."""
    mtcat = _mtcat_v11()
    mtcat["portal"]["version"] = "1.2"
    mtcat["portal"]["derived_stats"] = {"n_dois": 2}
    for s in mtcat["surveys"]:
        s["derived_period_band"] = {"min_s": 0.01, "max_s": 1000.0}
        s["quality_rollup"] = None
    root = _data_root(tmp_path, mtcat=mtcat)
    assert _cut(root) == 0
    parts = [r["relatedIdentifier"] for r in _datacite(root)["relatedIdentifiers"]]
    assert parts == ["10.5555/demo-survey", "10.25914/sv5r-zw68"]
    assert _release(root)["n_surveys"] == 2


def test_mtcat_without_related_identifiers_still_cuts(tmp_path):
    """The whole pre-migration corpus shape: surveys carry a doi and no related_identifiers key."""
    mtcat = _mtcat_v11()
    for s in mtcat["surveys"]:
        s.pop("related_identifiers", None)
    root = _data_root(tmp_path, mtcat=mtcat)
    assert _cut(root) == 0
    parts = [r["relatedIdentifier"] for r in _datacite(root)["relatedIdentifiers"]]
    assert parts == ["10.5555/demo-survey"]


def test_doi_parts_tolerates_junk_shapes():
    """Defensive, mirroring build_portal's _related_identifiers_of tolerance: bare strings, wrong
    types and a non-list surveys value are skipped, never crash."""
    assert cr.doi_parts({}) == []
    assert cr.doi_parts({"surveys": None}) == []
    assert cr.doi_parts({"surveys": "not-a-list"}) == []
    assert cr.doi_parts({"surveys": ["nope", 42, {"doi": None},
                                     {"doi": "not-a-doi"},
                                     {"related_identifiers": "not-a-list"},
                                     {"related_identifiers": ["bare", 7]},
                                     {"doi": "10.1/x", "related_identifiers": [
                                         {"identifier": "10.1/x", "identifier_type": "doi"}]}]}) == ["10.1/x"]
