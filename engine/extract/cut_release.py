#!/usr/bin/env python3
"""cut_release - the quarterly citable corpus snapshot ("AusMT Data Portal, Release 2026-Q3").

WHAT THIS IS. A release is a FROZEN COPY of the current build's catalogue surface plus every
per-survey bundle it serves, cut into `<data-root>/releases/<tag>/`, with a `release.json`
provenance document and a pre-generated DataCite record beside it. It exists so a paper can cite a
specific state of the corpus: `builds/<ts>` dirs are pruned (deploy/Makefile rebuild-data keeps the
newest five) and `current` moves every rebuild, so neither is citable. `releases/` is a SIBLING of
`builds/` under the data root, exactly like the `cache/` tier, so it survives both the prune and
the atomic `current` symlink swap.

WHAT THIS IS NOT. This tool MINTS NOTHING. It has no network access, no DataCite credentials and no
git write path. It prepares the metadata so that the day AuScope's ARDC/DataCite access lands, the
emitted `datacite.json` can be submitted as-is, and `--doi` can be run again on the SAME tag to
stamp the minted DOI back into `release.json` + `datacite.json` (the post-minting backfill). The
corpus git tag is PRINTED for a person to run; this tool never invokes git.

USAGE (host, against a data root):

    python -m extract.cut_release --data <site-data root> --tag 2026-Q3 [--note "one line"]
    python -m extract.cut_release --data <site-data root> --tag 2026-Q3 --doi 10.xxxxx/yyyy

The production invocation runs INSIDE the build-runner container (site-data mounted at /out), the
same context rebuild-data builds in, so the release is written by the uid that owns site-data:

    make -C deploy cut-release TAG=2026-Q3 NOTE="first citable snapshot"

INTEGRITY. Every copied bundle is re-hashed from the bytes that landed in the release dir and
checked against the download manifest's own sha256 claim; ANY mismatch, and any repo-tier bundle the
manifest claims but the build does not have on disk, FAILS the cut and leaves no release behind. A
half-written release is worse than no release: a citation must resolve to bytes that match their
recorded digests.

IDEMPOTENCE. An existing tag is NEVER overwritten. Re-running a cut on a tag that exists is a hard
error; the only thing allowed to touch an existing tag is `--doi` (and `--note`, which rides along),
and that path rewrites only `release.json` + `datacite.json` and never re-copies data.

MTCAT TOLERANCE. mtcat.json is read TOLERANTLY: only `surveys[]`, `stations[]`, each survey's `doi`
and its `related_identifiers[]` rows are consulted, all guarded for absence and wrong types. No
derived or version-specific field is assumed, so a v1.1 and a v1.2 payload both cut cleanly.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from _contract import LICENSES  # noqa: E402  (sibling-import house pattern; deed URLs are single-sourced)

# --- layout constants: the one place the on-disk release shape is named ---------------------------
RELEASES_DIR = "releases"          # sibling of builds/ and cache/ under the data root
INDEX_NAME = "releases.json"       # releases/releases.json, the newest-first index
RELEASE_DOC = "release.json"       # releases/<tag>/release.json
DATACITE_DOC = "datacite.json"     # releases/<tag>/datacite.json
BUNDLES_DIR = "bundles"            # the per-survey artifact tree copied wholesale
CURRENT_LINK = "current"           # the symlink rebuild-data swaps atomically

# The catalogue surface a release freezes. All three are written to the BUILD ROOT by build_portal
# (the served copies, i.e. exactly what /data/ hands a reader), not the curator products/ mirror.
COPIED_DOCS = ("mtcat.json", "surveys.json", "manifest.json")

# A tag must be a safe single path component: it becomes a directory name and a git tag suffix.
_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# DataCite kernel-4 constants (the shape the REST API accepts under `attributes`).
_SCHEMA_VERSION = "http://datacite.org/schema/kernel-4"
_PUBLISHER = "AuScope"
_METADATA_LICENCE = "CC0-1.0"

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


class CutError(Exception):
    """A refusal or a failed integrity check. Carries the operator-facing message verbatim."""


# --- small pure helpers ---------------------------------------------------------------------------

def utc_now() -> str:
    """Wall-clock cut time, same ISO8601-Z shape every other AusMT build document uses."""
    return _dt.datetime.now(_dt.timezone.utc).strftime(_TS_FMT)


def sha256_of(path: Path) -> str:
    """Streamed sha256 of a file. Streamed, not read_bytes(): a survey MTH5 bundle can be large."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path, what: str) -> dict:
    """Read one build document, failing the cut with a path-naming message rather than a traceback."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise CutError(f"cannot read {what} at {path}: {type(e).__name__}: {e}") from e
    except ValueError as e:
        raise CutError(f"{what} at {path} is not valid JSON: {e}") from e


def write_json(path: Path, doc) -> None:
    """Indented JSON with a trailing newline, matching build.json / build_report.json house style."""
    path.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def normalise_doi(identifier) -> str:
    """Strip a leading doi.org resolver prefix so a bare DOI and a resolver URL dedupe to one part.
    Mirrors scripts/refresh_pid_status.normalise_doi (same job, no shared import: that script is not
    an installed module and this tool must stay importable inside the engine image)."""
    s = str(identifier or "").strip()
    for pfx in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
                "doi.org/", "dx.doi.org/"):
        if s.lower().startswith(pfx):
            return s[len(pfx):]
    return s


def is_doi(identifier) -> bool:
    """DOI-shaped: a '10.' prefix survives resolver-stripping. Deliberately the same loose test the
    PID sweep uses - a stricter regex would silently drop real corpus DOIs from the HasPart set."""
    return normalise_doi(identifier).startswith("10.")


def validate_tag(tag: str) -> str:
    """A tag is a directory name AND a git tag suffix, so it must be a safe single component."""
    t = (tag or "").strip()
    if not _TAG_RE.match(t):
        raise CutError(f"invalid --tag {tag!r}: expected a single path component matching "
                       f"[A-Za-z0-9][A-Za-z0-9._-]* (e.g. 2026-Q3)")
    return t


# --- reading the current build --------------------------------------------------------------------

def resolve_current(data_root: Path) -> Path:
    """Follow `<data-root>/current` to the build dir it names. This is the ONLY build a cut may
    freeze: it is by definition the one readers are being served, so the release and the live portal
    agree. A missing or dangling `current` is a hard error (a box with no successful build yet has
    nothing citable), never a silent fallback to the newest builds/ dir."""
    link = data_root / CURRENT_LINK
    if not link.exists():
        raise CutError(f"no current build: {link} is missing or dangling. Run `make rebuild-data` "
                       f"and cut the release after the symlink swap succeeds.")
    build = link.resolve()
    if not build.is_dir():
        raise CutError(f"no current build: {link} resolves to {build}, which is not a directory")
    return build


def build_identity(build: Path) -> dict:
    """The build.json identity block a release must carry. Absent build.json fails the cut: a
    snapshot whose commits cannot be named is not citable provenance, it is just a pile of files."""
    doc = read_json(build / "build.json", "build.json")
    if not isinstance(doc, dict) or not doc.get("build_id"):
        raise CutError(f"{build / 'build.json'} carries no build_id; refusing to cut an "
                       f"unidentifiable build")
    return {"build_id": doc.get("build_id"),
            "engine_commit": doc.get("engine_commit"),
            "source_commit": doc.get("source_commit"),
            "generated": doc.get("generated")}


def manifest_rows(manifest) -> tuple[list, list]:
    """(files, bundles) from the download manifest, each guarded to a list of mappings. Tolerant on
    purpose: the manifest is a schema-validated build product, but a release must not crash on a
    partially-written one, it must FAIL with a message."""
    if not isinstance(manifest, dict):
        raise CutError("manifest.json is not a JSON object")
    files = [r for r in (manifest.get("files") or []) if isinstance(r, dict)]
    bundles = [r for r in (manifest.get("bundles") or []) if isinstance(r, dict)]
    return files, bundles


def bundle_claims(manifest) -> dict:
    """Map `bundles/<name>` -> claimed sha256 for every REPO-tier bundle row in the manifest.

    Keyed on the path from `bundles/` onward so a non-empty manifest base_url (an absolutely-resolved
    url) still matches the on-disk layout. tier=nci rows are deliberately EXCLUDED: their bytes live
    at NCI, never in the build dir, so there is nothing local to verify or to copy."""
    _files, bundles = manifest_rows(manifest)
    claims: dict = {}
    for row in bundles:
        if row.get("tier") != "repo":
            continue
        url = str(row.get("url") or "")
        marker = BUNDLES_DIR + "/"
        idx = url.find(marker)
        if idx < 0:
            continue
        claims[url[idx:]] = row.get("sha256")
    return claims


def doi_parts(mtcat) -> list:
    """Every DOI-typed identifier the catalogue points at, deduped, in document order.

    Two sources per survey, both optional and both read tolerantly (v1.1 and v1.2 payloads alike):
      * the survey's own `doi` - the clearest "part of this release" there is;
      * each `related_identifiers[]` row whose `identifier_type` is DOI.
    NOTE FOR REVIEW: rolling the related-identifier rows in means a source archive a survey declares
    as IsDerivedFrom is emitted under HasPart, which overstates containment. The specification asks for
    HasPart over the DOI-typed related identifiers, so that is what ships; if the relation should
    instead be carried verbatim from each row, this is the ONE function to change."""
    out: list = []
    seen: set = set()

    def _add(value):
        if not is_doi(value):
            return
        key = normalise_doi(value)
        if key not in seen:
            seen.add(key)
            out.append(key)

    surveys = mtcat.get("surveys") if isinstance(mtcat, dict) else None
    for survey in (surveys or []):
        if not isinstance(survey, dict):
            continue
        _add(survey.get("doi"))
        rels = survey.get("related_identifiers")
        for row in (rels or []) if isinstance(rels, list) else []:
            if isinstance(row, dict) and str(row.get("identifier_type") or "").upper() == "DOI":
                _add(row.get("identifier"))
    return out


def corpus_counts(mtcat) -> tuple[int, int]:
    """(n_surveys, n_stations) straight off the copied catalogue, so the release document's counts
    can never disagree with the mtcat.json shipped beside it."""
    if not isinstance(mtcat, dict):
        return 0, 0
    surveys = mtcat.get("surveys")
    stations = mtcat.get("stations")
    return (len(surveys) if isinstance(surveys, list) else 0,
            len(stations) if isinstance(stations, list) else 0)


# --- the DataCite emitter -------------------------------------------------------------------------

def _rights_row(licence_id: str) -> dict:
    """One rightsList row for a corpus licence id. `rights` is the id VERBATIM and the SPDX
    identifier/scheme ride along only for ids the contract actually knows a deed URL for, so a
    non-SPDX corpus value (e.g. 'PUBLIC DOMAIN') is never dressed up as an SPDX id it is not."""
    row = {"rights": licence_id}
    url = (LICENSES.get("urls") or {}).get(licence_id)
    if url:
        row["rightsUri"] = url
        row["rightsIdentifier"] = licence_id
        row["rightsIdentifierScheme"] = "SPDX"
        row["schemeUri"] = "https://spdx.org/licenses/"
    return row


def _corpus_licences(manifest) -> list:
    """Distinct data licences actually present in the download manifest, canonicalised through the
    licence alias table and sorted. Derived, never asserted: the rightsList states what the corpus IS
    licensed under this quarter, not what it was licensed under when this file was written."""
    files, bundles = manifest_rows(manifest)
    aliases = LICENSES.get("aliases") or {}
    found = set()
    for row in files + bundles:
        raw = row.get("canon_license") or row.get("license")
        if raw:
            key = str(raw).strip()
            found.add(aliases.get(key, key))
    return sorted(found)


def _sizes_and_formats(manifest) -> tuple[list, list]:
    """DataCite `sizes` / `formats`, summarised from the manifest (every artifact it indexes, both
    tiers - the corpus is what it is regardless of which bytes AusMT happens to host)."""
    files, bundles = manifest_rows(manifest)
    rows = files + bundles
    total = sum(int(r.get("size") or 0) for r in rows)
    sizes = [f"{len(rows)} files", f"{total} bytes"]
    formats = sorted({str(r.get("format")) for r in rows if r.get("format")})
    return sizes, formats


def datacite_document(tag: str, release: dict, mtcat, manifest, previous_doi=None) -> dict:
    """The DataCite Metadata Schema 4 record for one release, ready to submit unchanged.

    The DOI is the only thing that arrives later. While `release["doi"]` is null the document
    carries NO `doi` and NO `identifiers` key at all - an empty or null identifier would be a
    rejected (and dishonest) submission. Once minted, `--doi` re-runs this function and both keys
    appear. Everything else is final on the day of the cut."""
    doi = release.get("doi")
    cut_at = (release.get("cut_at") or {}).get("cut") or ""
    year = cut_at[:4]
    licences = _corpus_licences(manifest)
    sizes, formats = _sizes_and_formats(manifest)

    rights = [_rights_row(lic) for lic in licences]
    if not any(r["rights"] == _METADATA_LICENCE for r in rights):
        rights.append(_rights_row(_METADATA_LICENCE))

    related = [{"relatedIdentifier": d, "relatedIdentifierType": "DOI", "relationType": "HasPart"}
               for d in doi_parts(mtcat)]
    # IsNewVersionOf is emitted ONLY against a real prior DOI. A prior release that has not been
    # minted yet contributes nothing: a null relatedIdentifier is invalid DataCite, and a placeholder
    # would be a claim about an identifier that does not exist.
    if previous_doi:
        related.append({"relatedIdentifier": normalise_doi(previous_doi),
                        "relatedIdentifierType": "DOI", "relationType": "IsNewVersionOf"})

    doc = {
        "schemaVersion": _SCHEMA_VERSION,
        "titles": [{"title": f"AusMT Data Portal, Release {tag}"}],
        "publisher": _PUBLISHER,
        "publicationYear": int(year) if year.isdigit() else None,
        "version": tag,
        "types": {"resourceTypeGeneral": "Dataset", "resourceType": "Catalogue snapshot"},
        # Portal-level attribution: a release is the aggregate work of the corpus, not of any one
        # survey's authors (each survey keeps its own creators[] in mtcat and its own DOI).
        "creators": [
            {"name": "AuScope", "nameType": "Organizational"},
            {"name": "AusMT contributors", "nameType": "Organizational"},
        ],
        "contributors": [
            {"name": "AusMT", "nameType": "Organizational", "contributorType": "HostingInstitution"},
        ],
        "dates": [{"date": cut_at, "dateType": "Created"}],
        "rightsList": rights,
        "sizes": sizes,
        "formats": formats,
        "relatedIdentifiers": related,
        "descriptions": [
            {"descriptionType": "Abstract",
             "description": (f"Quarterly citable snapshot of the AusMT data portal corpus, release "
                             f"{tag}: the MTCAT catalogue document, the survey metadata, the download "
                             f"manifest and every per-survey bundle as served by build "
                             f"{release.get('build_id')}. Covers {release.get('n_surveys')} surveys "
                             f"and {release.get('n_stations')} stations.")},
            {"descriptionType": "Other",
             "description": ("Licences vary by survey; CC-BY-4.0 is predominant. The per-survey "
                             "licence recorded in the download manifest, and the LICENSE.txt "
                             "travelling with each bundle, is authoritative for that survey's data. "
                             f"Catalogue metadata is {_METADATA_LICENCE}.")},
        ],
    }
    if release.get("note"):
        doc["descriptions"].append({"descriptionType": "TechnicalInfo",
                                    "description": str(release["note"])})
    if doi:
        doc["doi"] = normalise_doi(doi)
        doc["identifiers"] = [{"identifier": normalise_doi(doi), "identifierType": "DOI"}]
    return doc


# --- the releases index ---------------------------------------------------------------------------

def _index_path(data_root: Path) -> Path:
    return data_root / RELEASES_DIR / INDEX_NAME


def load_index(data_root: Path) -> dict:
    """The newest-first index, or a fresh empty one. A missing index is the first-ever cut, not an
    error; a CORRUPT index is an error (silently discarding the release history would lose the
    IsNewVersionOf chain, which is the one thing the index exists to carry)."""
    path = _index_path(data_root)
    if not path.exists():
        return {"schema": "ausmt-releases", "version": "1.0", "updated_at": None, "releases": []}
    doc = read_json(path, "releases.json index")
    if not isinstance(doc, dict) or not isinstance(doc.get("releases"), list):
        raise CutError(f"{path} is not a releases index (expected an object with a 'releases' list)")
    return doc


def index_entry(release: dict) -> dict:
    """The index row for one release. `cut` is the scalar wall-clock cut time (release.json's own
    cut_at is a two-timestamp object); keeping the names distinct means no consumer ever sees one
    key with two different types across the two files."""
    return {"tag": release["tag"],
            "cut": (release.get("cut_at") or {}).get("cut"),
            "doi": release.get("doi"),
            "note": release.get("note"),
            "build_id": release.get("build_id"),
            "n_surveys": release.get("n_surveys"),
            "n_stations": release.get("n_stations"),
            "path": f"{RELEASES_DIR}/{release['tag']}/"}


def upsert_index(index: dict, release: dict, now: str) -> dict:
    """Replace-or-insert this tag's row and re-sort NEWEST FIRST by cut time (tag as the tie-break,
    so two cuts inside the same second still order deterministically). Sorting rather than
    prepending keeps the ordering true even after a hand-edit or an out-of-order cut."""
    rows = [r for r in index.get("releases", []) if isinstance(r, dict) and r.get("tag") != release["tag"]]
    rows.append(index_entry(release))
    rows.sort(key=lambda r: (str(r.get("cut") or ""), str(r.get("tag") or "")), reverse=True)
    index["releases"] = rows
    index["updated_at"] = now
    return index


def previous_doi_for(index: dict, tag: str):
    """The DOI of the newest release OLDER than `tag` that actually has one, or None.

    Walks forward from this tag's position in the newest-first list, so it skips over any number of
    not-yet-minted intermediate releases and chains to the last real DOI. Returns None (and the
    emitter then omits IsNewVersionOf entirely) when nothing prior has been minted."""
    rows = index.get("releases") or []
    positions = [i for i, r in enumerate(rows) if isinstance(r, dict) and r.get("tag") == tag]
    start = positions[0] + 1 if positions else 0
    for row in rows[start:]:
        if isinstance(row, dict) and row.get("doi"):
            return row["doi"]
    return None


# --- the cut ---------------------------------------------------------------------------------------

def _copy_tree(build: Path, dest: Path) -> list:
    """Copy the catalogue documents and the whole bundles/ tree into the release dir. Returns the
    relative paths copied, sorted, so the release.json files[] order is stable across cuts."""
    copied = []
    for name in COPIED_DOCS:
        src = build / name
        if not src.is_file():
            raise CutError(f"current build is missing {name} ({src}); refusing to cut an incomplete "
                           f"catalogue surface")
        shutil.copy2(src, dest / name)
        copied.append(name)

    src_bundles = build / BUNDLES_DIR
    if src_bundles.is_dir():
        for src in sorted(p for p in src_bundles.rglob("*") if p.is_file()):
            rel = src.relative_to(build)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(rel.as_posix())
    return sorted(copied)


def _verify_bundles(dest: Path, copied: list, claims: dict) -> None:
    """Re-hash the bundle bytes that ACTUALLY landed in the release dir and check them against the
    manifest's own sha256 claims. Non-vacuous by construction: the digest is recomputed from the
    copied file, an observable independent of anything the manifest says, so a corrupted or
    tampered artifact cannot pass. Also fails when the manifest claims a repo-tier bundle the build
    does not have on disk - a release that silently ships fewer artifacts than its own manifest
    advertises would hand a citing reader a 404."""
    problems = []
    copied_set = set(copied)
    for rel in copied:
        claimed = claims.get(rel)
        if claimed is None:
            continue          # not a manifest-indexed artifact (e.g. a bundle LICENSE.txt sidecar)
        actual = sha256_of(dest / rel)
        if actual != claimed:
            problems.append(f"{rel}: manifest claims sha256 {claimed}, copied bytes hash {actual}")
    for rel in sorted(claims):
        if rel not in copied_set:
            problems.append(f"{rel}: listed in the download manifest but absent from the build")
    if problems:
        raise CutError("bundle integrity check FAILED, no release written:\n  "
                       + "\n  ".join(problems))


def _files_block(dest: Path, copied: list) -> list:
    """[{path, size, sha256}] for everything copied, in the same stable order."""
    return [{"path": rel,
             "size": (dest / rel).stat().st_size,
             "sha256": sha256_of(dest / rel)} for rel in copied]


def _print_tag_commands(tag: str, source_commit, surveys_live: str) -> None:
    """PRINT the corpus tag commands. This tool never runs git: tagging and pushing the surveys repo
    is a human action against an authenticated remote, and a build container has no business
    holding that credential."""
    print("")
    print("Tag the corpus for this release (run these yourself; cut_release never runs git):")
    if not source_commit:
        print(f"  (skipped: the build recorded no source_commit, so there is no corpus commit to "
              f"tag. This is a --raw or non-git build; tag ausmt-release-{tag} by hand.)")
        return
    print(f"  git -C {surveys_live} tag ausmt-release-{tag} {source_commit}")
    print(f"  git -C {surveys_live} push origin ausmt-release-{tag}")


def backfill_doi(data_root: Path, tag: str, doi: str, note=None, now=None) -> int:
    """The post-minting path: stamp a freshly minted DOI onto an EXISTING release and regenerate its
    DataCite record. Touches release.json, datacite.json and the index row only; the frozen data is
    never re-copied, so the files[] digests recorded at cut time stay exactly as cut.

    SCOPE LIMIT (deliberate): this rewrites THIS release's two documents, not any later release's.
    In the intended ritual (cut, mint, backfill, then cut the next quarter) that is exactly right,
    because the next cut reads the already-stamped index. Backfilling a DOI onto a release that
    ALREADY has a successor would leave that successor's IsNewVersionOf unset; re-running the
    backfill on the successor with its own --doi regenerates it."""
    now = now or utc_now()
    rel_dir = data_root / RELEASES_DIR / tag
    release = read_json(rel_dir / RELEASE_DOC, f"{RELEASE_DOC} for tag {tag}")
    if not isinstance(release, dict):
        raise CutError(f"{rel_dir / RELEASE_DOC} is not a JSON object")

    release["doi"] = normalise_doi(doi)
    if note is not None:
        release["note"] = note
    release["doi_stamped_at"] = now
    write_json(rel_dir / RELEASE_DOC, release)

    index = upsert_index(load_index(data_root), release, now)
    write_json(_index_path(data_root), index)

    mtcat = read_json(rel_dir / "mtcat.json", "the release's mtcat.json")
    manifest = read_json(rel_dir / "manifest.json", "the release's manifest.json")
    write_json(rel_dir / DATACITE_DOC,
               datacite_document(tag, release, mtcat, manifest,
                                 previous_doi=previous_doi_for(index, tag)))
    print(f"cut-release: stamped DOI {release['doi']} onto existing release {tag}")
    print(f"  {rel_dir / RELEASE_DOC}")
    print(f"  {rel_dir / DATACITE_DOC}")
    return 0


def cut(data_root: Path, tag: str, doi=None, note=None, surveys_live: str = "<surveys-live>",
        now=None) -> int:
    """Cut a fresh release from the current build. Returns a process exit code."""
    now = now or utc_now()
    rel_dir = data_root / RELEASES_DIR / tag
    if rel_dir.exists():
        raise CutError(f"release {tag} already exists at {rel_dir}. A cut release is immutable and "
                       f"is never overwritten. To stamp a minted DOI onto it, re-run with --doi; to "
                       f"cut a different snapshot, choose another --tag.")

    build = resolve_current(data_root)
    identity = build_identity(build)
    mtcat = read_json(build / "mtcat.json", "the build's mtcat.json")
    manifest = read_json(build / "manifest.json", "the build's manifest.json")
    n_surveys, n_stations = corpus_counts(mtcat)

    rel_dir.mkdir(parents=True, exist_ok=False)
    try:
        copied = _copy_tree(build, rel_dir)
        _verify_bundles(rel_dir, copied, bundle_claims(manifest))
        files = _files_block(rel_dir, copied)
    except (CutError, OSError):
        # Leave NOTHING half-cut behind: a partial releases/<tag>/ would both block the retry (the
        # idempotence guard fires on its existence) and look like a real, citable release.
        shutil.rmtree(rel_dir, ignore_errors=True)
        raise

    release = {
        "tag": tag,
        # Both clocks the snapshot depends on: WHEN THE BYTES WERE BUILT (build.json's generated
        # stamp) and WHEN THEY WERE FROZEN (this run's wall clock). They differ whenever a release is
        # cut some time after the rebuild, which is the normal case.
        "cut_at": {"build_generated": identity.get("generated"), "cut": now},
        "build_id": identity.get("build_id"),
        "engine_commit": identity.get("engine_commit"),
        "source_commit": identity.get("source_commit"),
        "n_surveys": n_surveys,
        "n_stations": n_stations,
        "files": files,
        "doi": normalise_doi(doi) if doi else None,
        "note": note,
    }
    write_json(rel_dir / RELEASE_DOC, release)

    index = upsert_index(load_index(data_root), release, now)
    write_json(_index_path(data_root), index)

    write_json(rel_dir / DATACITE_DOC,
               datacite_document(tag, release, mtcat, manifest,
                                 previous_doi=previous_doi_for(index, tag)))

    total = sum(f["size"] for f in files)
    print(f"cut-release: {tag} cut from {build}")
    print(f"  build_id      {identity.get('build_id')}")
    print(f"  corpus        {n_surveys} surveys, {n_stations} stations")
    print(f"  frozen        {len(files)} files, {total} bytes -> {rel_dir}")
    print(f"  doi           {release['doi'] or 'null (not minted yet; re-run with --doi to stamp it)'}")
    print(f"  index         {_index_path(data_root)}")
    _print_tag_commands(tag, identity.get("source_commit"), surveys_live)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m extract.cut_release",
        description="Cut a citable quarterly snapshot of the current build. Mints nothing.")
    ap.add_argument("--data", required=True,
                    help="site-data root (the dir holding current/, builds/ and releases/); /out in "
                         "the build-runner container")
    ap.add_argument("--tag", required=True, help="release tag, e.g. 2026-Q3")
    ap.add_argument("--doi", default=None,
                    help="the minted DOI. On a NEW tag it is recorded at cut time; on an EXISTING "
                         "tag it stamps release.json and regenerates datacite.json (the backfill).")
    ap.add_argument("--note", default=None, help="one-line note carried into release.json and DataCite")
    ap.add_argument("--surveys-live", default="<surveys-live>",
                    help="path to the surveys-live git checkout ON THE HOST, used only to print the "
                         "corpus tag commands, which are run by hand")
    a = ap.parse_args(argv)

    try:
        tag = validate_tag(a.tag)
        data_root = Path(a.data)
        if not data_root.is_dir():
            raise CutError(f"--data {data_root} is not a directory")
        rel_dir = data_root / RELEASES_DIR / tag
        if rel_dir.exists() and a.doi:
            return backfill_doi(data_root, tag, a.doi, note=a.note)
        return cut(data_root, tag, doi=a.doi, note=a.note, surveys_live=a.surveys_live)
    except CutError as e:
        print(f"cut-release: ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
