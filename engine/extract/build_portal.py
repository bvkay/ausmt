#!/usr/bin/env python3
"""build_portal — the one reproducible pipeline that wires the three repos together.

  ausmt-surveys (survey.yaml + EDIs)
        -> validate -> extract (mt_metadata) -> science diagnostics
        -> products/<survey>/<station>/{station,dimensionality}.json
        -> products/{catalogue,surveys,manifest}.json          (the boring contract)
        -> portal/data/{catalogue,tf,sci,surveys}.json         (the portal projection)

The portal consumes ONLY generated JSON. There is no hard-coded survey metadata anywhere:
survey metadata comes from each package's survey.yaml (or, for the bulk seed, from a
seed-metadata JSON in the surveys repo).

NOTE ON THE EXTRACTOR: mt_metadata (the USGS community library) is the SOLE parsing engine.
The dependency-free regex extractor + _spectra reader were retired in 2026-06; the shared TF/science math in
`_edi_tf`/`_edi_science`/`_ediparse` and the coord/DATAID helpers in `_edi_catalog` are kept and
fed by mt_metadata. The canonical persisted form is EMTF XML via `ausmt_science/ingest`.

Usage
  # survey-package mode (the real loop; the architecture proof) — run from ausmt/engine/:
  python -m extract.build_portal --surveys ../../ausmt-surveys/surveys \
         --out ../portal/data --products products

  # raw-EDI bulk mode (regenerate the large seed demo without packaging 1,454 files):
  python -m extract.build_portal --raw <edi_root> --collections <map.json> \
         --seed-meta <seed_survey_meta.json> --out ../portal/data --products products
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _edi_catalog as cat          # noqa: E402  (coords/QC + DATAID/proc-note helpers)
import _edi_tf as tfmod             # noqa: E402  (tf_from_components — shared TF math)
import _mtm as mtm                  # noqa: E402  (mt_metadata extractor — the sole parse engine)
import _edi_science as sci          # noqa: E402  (science_from_components, proc_info)
import _mth5 as m5                   # noqa: E402  (MTH5 reader; optional, needs mth5+mt_metadata)
import _ediparse as ep              # noqa: E402  (shared math: read_norm/pt_params/drho/dphase/EMPTY_TF)
import _conventions as conv         # noqa: E402  (C25 convention gates: frame guard + quadrant check)
import _coordaccess as coordacc     # noqa: E402  (C42 coordinate-access mask seam + byte gate)
import _stationids as stnids        # noqa: E402  (survey.yaml station-id override for third-party data)
import _presence as presence        # noqa: E402  (the presence rule: mt_metadata defaults are never assertions)
import _runfacts as rfacts          # noqa: E402  (the six >INFO dialect extractors for run acquisition facts)
import _runids as runids            # noqa: E402  (the persistent per-survey run-id store)
import _tsindex as tsindex          # noqa: E402  (the per-survey verified-resource register, read offline)
import _tsproject as tsproject      # noqa: E402  (the ONE projection: flag/count/route from the register)
import _stationcheck as stcheck     # noqa: E402  (station semantics beyond JSON Schema; shared with scripts/verify.py)
import cache as cache_mod           # noqa: E402  (C18 content-addressed per-station build cache)
from _contract import CATALOGUE_COLUMNS, MTCAT_SCHEMA_VERSION, STATION_SCHEMA_VERSION, SURVEY_METADATA_SCHEMA_VERSION  # noqa: E402  (single-source positional column contract + the three public-contract schema versions)

# Named sci-column access for the consumer side (mirrors the portal's contract.js SC map) so the product
# writers below read sci fields BY NAME, not raw integer index. Built from the same generated SCI_COLUMNS,
# so a reorder of contract/columns.json moves these in lockstep too.
_SC = {_n: _i for _i, _n in enumerate(sci.SCI_COLUMNS)}

# Authoritative catalogue.json column order (r[0..15]) — now SINGLE-SOURCED in contract/columns.json
# and imported above as CATALOGUE_COLUMNS (regenerate with `python contract/generate.py`). The portal
# reads these BY POSITION via portal/src/contract.js (the C.* index map), as do engine scripts/verify.py
# and the separate ausmt-surveys/_validation/contribute.py. APPEND, never reorder; the build asserts
# each emitted row matches this width (and SCI_COLUMNS / TF_COLUMNS).

# Validator lives in the SEPARATE ausmt-surveys repo (ADR-001). AUSMT_VALIDATOR_PATH (a directory
# containing validate_survey.py, or the file itself) is consulted FIRST -- an explicit pin for CI/
# non-sibling layouts; if set but unresolvable that is a HARD error (never fall through to the walk,
# or a typo'd path would silently re-adopt whatever the bounded walk happens to find). Otherwise
# search upward from this file for a sibling `ausmt-surveys/_validation`, so it resolves whether the
# engine is the monorepo `ausmt/engine/` (surveys at <root>/ausmt-surveys) or a standalone checkout
# placed next to ausmt-surveys.
def _load_validator():
    env = os.environ.get("AUSMT_VALIDATOR_PATH")
    if env:
        p = Path(env)
        f = p if p.name == "validate_survey.py" else (p / "validate_survey.py")
        if not f.exists():
            sys.exit(f"ERROR: AUSMT_VALIDATOR_PATH={env!r} does not resolve to validate_survey.py "
                      f"(looked for {f}) -- fix the path or unset it; never falling through silently.")
        sys.path.insert(0, str(f.parent))
        import validate_survey  # noqa: PLC0415
        print(f"survey validator: {f} (via AUSMT_VALIDATOR_PATH)", file=sys.stderr)
        return validate_survey
    # BOUND the upward walk to a few levels (the real ausmt-surveys is a sibling of the monorepo, within
    # ~3 levels) so a stray ausmt-surveys far up the filesystem can't be silently adopted, and LOG the
    # resolved path so a wrong/foreign validator is visible, not silently trusted.
    for base in (HERE, *list(HERE.parents)[:5]):
        c = base / "ausmt-surveys" / "_validation"
        if (c / "validate_survey.py").exists():
            sys.path.insert(0, str(c))
            import validate_survey  # noqa: PLC0415
            print(f"survey validator: {c / 'validate_survey.py'}", file=sys.stderr)
            return validate_survey
    return None


_SHA_CACHE: dict = {}


def _dist_version(default="0.2.1"):
    """Single source of truth for the version is pyproject's [project].version. Read it from the
    installed distribution metadata when available; fall back to `default` when running from source
    without `pip install -e .`. Keep `default` in step with pyproject.toml."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version("ausmt")
        except PackageNotFoundError:
            return default
    except Exception:  # noqa: BLE001
        return default


def peak_rss_mib():
    """The build process's memory high-water mark in MiB, from resource.getrusage (a cheap kernel
    counter, no sampling): what build_report.json records as `peak_rss_mib` so every real build carries
    its own peak and an operator can see the trend BEFORE the box runs out (the 2026-08-15 P350 OOM
    kills were the first anyone heard of 13.7 GB). ru_maxrss is KiB on Linux and bytes on macOS; both
    are normalised here. None where the counter is unavailable (Windows), never a guess.

    SCOPE (for the survey-parallel build lane, which composes with this): RUSAGE_SELF is THIS process
    only, and RUSAGE_CHILDREN reports the largest single waited-for descendant, never the sum over
    concurrent workers. With N worker processes the box-level footprint is about N times what either
    counter reports. That lane must report max(RUSAGE_SELF, RUSAGE_CHILDREN) together with the worker
    count (or per-worker peaks) in build_report, and restate tests/test_build_memory.py's pin as a
    per-worker bound times workers, so the field keeps meaning "what the box needed"."""
    try:
        import resource  # noqa: PLC0415  (POSIX only)
        v = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:  # noqa: BLE001  (no resource module, or a platform without ru_maxrss)
        return None
    if v <= 0:
        return None
    nbytes = v if sys.platform == "darwin" else v * 1024
    return round(nbytes / (1024 * 1024), 1)


def lib_versions() -> dict:
    """C32 §2: the ONE source of truth for the mt_metadata / mth5 library versions the build ran
    against. Returns {"mt_metadata": <ver>, "mth5": <ver>} with a key present only when that library
    is importable (a source checkout without the optional stack, or a --raw build, may have neither).
    Both the C18 cache salt (which keys cached XML against the exact library versions that produced
    it) and the C32 served-version keys (build.json / build_provenance.json / mtcat) read THIS helper,
    so the two can never drift to different versions of the same fact."""
    out: dict = {}
    try:
        import mt_metadata as _mtm_pkg  # noqa: PLC0415
        out["mt_metadata"] = _mtm_pkg.__version__
    except Exception:  # noqa: BLE001  (absent/broken optional dep -> key simply omitted)
        pass
    try:
        import mth5 as _mth5_pkg  # noqa: PLC0415
        out["mth5"] = _mth5_pkg.__version__
    except Exception:  # noqa: BLE001
        pass
    return out


def _json_default(obj):
    """json.dumps `default=` hook for EVERY product emit (surveys.json, mtcat, catalogue, products,
    ...). A survey.yaml that carries an UNQUOTED ISO date (e.g. `attribution.declared_date: 2026-07-25`)
    is implicit-typed by PyYAML safe_load into a datetime.date, which survey_meta_from_yaml threads
    VERBATIM into SMETA — plain json.dumps could not serialise it and the whole build CRASHED at the
    first emit site (Object of type date is not JSON serializable), quarantining every survey with it.
    Here any date/datetime/time is ISO-formatted (datetime subclasses date, so the one isinstance covers
    both) and a Decimal is stringified to preserve exact precision. This MIRRORS the gateway's
    gateway/jobs.py:_json_default so the two dumpers agree. Anything else is a genuine programming error,
    so we RAISE TypeError (json's own behaviour) rather than blind-str() a truly unexpected object into a
    served product — LAYER 2 (main()'s per-survey dry-run) then withholds just that survey."""
    import datetime  # noqa: PLC0415 (house style: local import where used)
    from decimal import Decimal  # noqa: PLC0415
    if isinstance(obj, (datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _jdump(obj, **kw) -> str:
    # ensure_ascii=False: catalogue text (survey/custodian names, the mtcat portal_name em-dash)
    # is emitted as real UTF-8, not \uXXXX escapes — byte-identical semantics for every JSON
    # parser, readable for humans. REQUIRES the paired write_text(..., encoding="utf-8") at
    # every product-emit site below: pathlib defaults to the locale encoding, which is cp1252
    # on the Windows dev box and unpinned in slim containers.
    # default=_json_default: an unquoted-ISO-date a survey.yaml carried into SMETA (date/datetime/time)
    # is ISO-formatted rather than crashing the build (mirrors gateway/jobs.py); a genuinely alien type
    # still raises TypeError, which LAYER 2's per-survey dry-run turns into a single-survey withhold.
    return json.dumps(obj, ensure_ascii=False, default=_json_default, **kw)


def _copy_source_bytes(src: Path, dest: Path) -> None:
    """Copy a custodian source file into the served tree, byte for byte. A named seam rather than an
    inline write_bytes so the integrity gate at the call site has something INDEPENDENT to check: the
    gate re-hashes what landed on disk, and a test can substitute a faulty copier without touching
    the gate itself. Never transforms; never re-encodes; the source is the citable record (D1)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())


def sha256(p: Path) -> str:
    # Cached per build: the same file is referenced for the per-station provenance, the
    # manifest and the catalogue's r[14]; without this it would be read and hashed three times.
    k = str(p)
    h = _SHA_CACHE.get(k)
    if h is None:
        h = _SHA_CACHE[k] = hashlib.sha256(p.read_bytes()).hexdigest()
    return h


# C6/C34-D2: the licence primitives (canonicalisation, the redistribution allow-list gate, and the
# deterministic LICENSE.txt/LICENSE.md rights text) live in the STDLIB-ONLY leaf `_license_text`, so
# the gw-runner can share the EXACT same rights text (LICENSE.md at intake) without importing this
# heavy build module. redistributable() (the served-EDI gate) and license_instrument_text() (the
# bundle LICENSE.txt) are re-imported here under their historical names so build_portal's own call
# sites and the tests that reference bp.redistributable / bp.license_instrument_text keep resolving
# unchanged, and the LICENSE.txt output stays byte-identical (pinned by test_license_gate /
# test_manifest).
from _license_text import canon_license, license_instrument_text, redistributable  # noqa: E402


# --- C1 access gate: access.level (open|metadata_only|embargoed) + embargo_until gate BYTE DISTRIBUTION,
# ORTHOGONAL to the licence gate above (a survey must be BOTH openly licensed AND access=open+un-embargoed
# to be served). Discovery is universal — a withheld survey still appears fully in catalogue/tf/sci/mtcat;
# only the bytes (manifest rows, edi/xml/bundle emission, edi_available) are withheld. The pure logic lives
# here so it is unit-testable without the mt_metadata stack. -----------------------------------------------

ACCESS_LEVELS = ("open", "metadata_only", "embargoed")   # the survey.yaml access.level enum (validator-enforced)


def normalise_access_level(raw) -> str:
    """Trim+lowercase the declared access.level. Absent/None/blank -> 'open' (legacy-friendly: the current
    corpus predates the field and is all-open). An UNRECOGNISED value passes through normalised, NOT coerced
    to 'open' — the validator FAILs a bad enum, and here anything != 'open' fails closed at serve time."""
    s = str(raw).strip().lower() if raw not in (None, "") else "open"
    return s or "open"


def access_serve_state(level, embargo_until, today=None) -> dict:
    """Whether a survey's ACCESS state permits byte distribution, plus curator-facing warnings.

    Returns {served, embargo_active, warnings}. served == access permits distribution (the licence gate is
    applied SEPARATELY by the caller). Only access.level == 'open' with no active embargo serves. Decisions
    (recorded per the C1 contract):
      (a) embargoed + UNPARSEABLE embargo_until  -> embargoed (FAIL CLOSED) + loud warning.
      (b) embargoed + NO embargo_until           -> embargoed INDEFINITELY + warning.
          embargoed + FUTURE date                -> embargoed (normal; no warning).
          embargoed + PAST date                  -> STILL embargoed + STALE-embargo warning. The level is the
              state of record; auto-un-embargoing on a lapsed date would be a SILENT publication. A curator
              flips level->open deliberately (Invariant 10: no state changes itself behind the curator's back).
      metadata_only -> never served (embargo_until irrelevant).
      open          -> served; embargo_until (if any) is ignored for serving — the level is authoritative.
    """
    from datetime import date, datetime, timezone   # noqa: PLC0415 (house style: local import where used)
    if today is None:
        today = datetime.now(timezone.utc).date()  # embargo is a calendar boundary; compare in UTC
    lvl = normalise_access_level(level)
    warnings: list = []
    if lvl == "open":
        return {"served": True, "embargo_active": False, "warnings": warnings}
    if lvl == "metadata_only":
        return {"served": False, "embargo_active": False, "warnings": warnings}
    if lvl == "embargoed":
        raw = str(embargo_until).strip() if embargo_until not in (None, "") else ""
        if not raw:                                                        # (b) no date => indefinite
            warnings.append("access.level=embargoed with no embargo_until — treated as embargoed INDEFINITELY "
                            "(set embargo_until, or flip level to open when the embargo lifts).")
            return {"served": False, "embargo_active": True, "warnings": warnings}
        try:
            end = date.fromisoformat(raw)
        except ValueError:                                                 # (a) unparseable => fail closed
            warnings.append(f"access.embargo_until {raw!r} is not an ISO YYYY-MM-DD date — treating the survey "
                            f"as EMBARGOED (fail closed). Fix the date or flip level to open.")
            return {"served": False, "embargo_active": True, "warnings": warnings}
        if end < today:                                                    # lapsed => still withheld + warn
            warnings.append(f"access.level=embargoed but embargo_until {raw} is in the PAST — the survey is "
                            f"STILL withheld (the level is the state of record; a lapsed date does not auto-"
                            f"publish). Flip level to open to release it.")
        return {"served": False, "embargo_active": True, "warnings": warnings}
    # unrecognised level (validator FAILs this; here it must fail closed — not-open never serves).
    warnings.append(f"access.level {lvl!r} is not one of {ACCESS_LEVELS} — treating as NOT servable (fail closed).")
    return {"served": False, "embargo_active": False, "warnings": warnings}


# --- C1b display-product withholding: the derived DISPLAY data the portal plots for a station. When a
# survey's ACCESS state is not served, the byte gate (C1) already withholds manifest/edi/xml/bundles; C1b
# additionally empties the derived display products at EMISSION so nothing is hidden only client-side — the
# withheld content simply is not in the served tf.json/sci.json. Width + station alignment are preserved
# (an empty [] per series / a nulled scalar per science field), so the positional contract and the build's
# _validate_products/width guard still hold. ------------------------------------------------------------

def withhold_tf_row(_tf_row=None):
    """The withheld tf.json row for a non-served survey's station: every SERIES column (periods, rho_xy,
    rho_yx, phs_xy, phs_yx_adj, tip_mag, pt_min, pt_max, pt_az, pt_beta) an EMPTY ARRAY. Row WIDTH and
    station alignment are kept — the period RANGE stays public via the catalogue columns (period_min_s/
    max_s/n_periods), the CURVES are not. This is exactly ep.EMPTY_TF's shape (one [] per TF_COLUMN); build
    a fresh list per call (never share the module-level EMPTY_TF list, whose inner []s would alias)."""
    return [[] for _ in tfmod.TF_COLUMNS]


# The sci columns split into science-DERIVED values (WITHHELD for a non-served survey — these are the
# embargoed diagnostics) and processing-METADATA (KEPT — rr/sw/alg describe HOW the data were processed,
# they are metadata, not the data). Per-column null convention MATCHES _edi_science's own no-periods row:
#   q->None qb->'s' dim->None p3d->None gd->0 ellip->None skew->None mre->None decades->0  (science, nulled)
#   rr / sw / alg                                                                          (metadata, kept)
_SCI_WITHHELD_SCIENCE = {"q": None, "qb": "s", "dim": None, "p3d": None, "gd": 0,
                         "ellip": None, "skew": None, "mre": None, "decades": 0}


def withhold_sci_row(sci_row):
    """The withheld sci.json row for a non-served survey's station: science-derived fields nulled per
    _SCI_WITHHELD_SCIENCE (matching the existing no-periods null convention), processing-metadata fields
    (rr/sw/alg) preserved verbatim from the real row. Built BY NAME then projected through SCI_COLUMNS, so
    a reorder of contract/columns.json moves these in lockstep with the emitters (self-following)."""
    _sc = {n: i for i, n in enumerate(sci.SCI_COLUMNS)}
    return [(_SCI_WITHHELD_SCIENCE[c] if c in _SCI_WITHHELD_SCIENCE else sci_row[_sc[c]])
            for c in sci.SCI_COLUMNS]


# C6/C34-D2: license_instrument_text now lives in the stdlib-only leaf `_license_text` (imported near
# the top of this module) so the bundle LICENSE.txt and the gw-runner's intake LICENSE.md share ONE
# implementation and can never drift. The output is unchanged (byte-identical, pinned by the license
# gate + manifest tests). The bundle call site below (build of the served-EDI zip) is untouched.


# ---- download manifest helpers (slice #4: the distribution backbone) --------------------------
# The manifest is the single key-based index of every DOWNLOADABLE artifact — per-station (EDI,
# EMTF XML) and per-survey bundles (EDI zip, survey MTH5) — each carrying size + sha256 for integrity
# and a tier-resolved URL. It rides BESIDE the positional catalogue (never as new r[] columns), so
# adding download metadata costs the index-read consumers nothing.
#   tier=repo : a portal-relative URL the portal joins onto its data_base_url (or base_url, if set).
#   tier=nci  : an ABSOLUTE NCI THREDDS fileServer URL. A survey may declare a single `nci_base`
#               (survey.yaml) — the fileServer directory its files sit flat under — and the build
#               then emits <nci_base>/<filename> for that survey's artifacts (the NCI storage tier).
# The sha256 is ALWAYS computed from the LOCAL bytes the build has at hand: the integrity ledger the
# git manifest keeps even for an NCI-hosted copy (a consumer can verify the NCI download against it).
_TIERS = ("repo", "nci")


def url_for(rel_path: str, tier: str = "repo", base_url: str = ""):
    """Resolve a served artifact's portal-relative path (e.g. 'edi/A1.edi') to a tier=repo download
    URL. base_url default '' => a relative URL the portal joins onto its data_base_url. tier=nci is
    NOT resolved here (it needs the survey's nci_base + the filename — see _resolve_artifact); a bare
    tier=nci with no base yields None, defensively. Forward-slash normalised for web URLs on Windows."""
    rel = str(rel_path).replace("\\", "/").lstrip("/")
    if tier == "nci":
        return None
    return (base_url.rstrip("/") + "/" + rel) if base_url else rel


def _resolve_artifact(rel: str, served: Path, nci_base, base_url):
    """(tier, url) for one served artifact. A survey with an nci_base hosts its files flat under that
    NCI fileServer directory, so the artifact resolves to <nci_base>/<filename> (tier=nci); otherwise
    it is served from the repo/Pages and resolves portal-relative (tier=repo, via url_for)."""
    base = str(nci_base).strip() if nci_base else ""
    if base:                              # a whitespace-only nci_base must NOT flip the tier
        return "nci", base.rstrip("/") + "/" + served.name
    return "repo", url_for(rel, "repo", base_url)


def _artifact_integrity(p: Path):
    """(size_bytes, sha256_hex) of a served artifact; reuses the cached sha256 (one read)."""
    return p.stat().st_size, sha256(p)


def _file_row(ausmt_id, survey, station, fmt, served: Path, rel, license_str, nci_base=None,
              base_url="", custodian=None):
    """One per-station downloadable-artifact manifest row, with the integrity of the SERVED bytes.
    C46-W3a: the raw `license` field is KEPT for compatibility; `canon_license` adds the canonical id
    (the de-aliased/normalised form) and `custodian` the rights-holder of record (attribution.custodian,
    else the organisation) so a manifest consumer can resolve rights without re-parsing the raw string."""
    size, digest = _artifact_integrity(served)
    tier, url = _resolve_artifact(rel, served, nci_base, base_url)
    return {"ausmt_id": ausmt_id, "survey": survey, "station": station, "format": fmt,
            "url": url, "size": size, "sha256": digest,
            "tier": tier, "license": license_str, "canon_license": canon_license(license_str),
            "custodian": custodian}


def _bundle_row(survey, slug, fmt, served: Path, rel, license_str, n_stations, nci_base=None,
                base_url="", custodian=None):
    """One per-survey bundle manifest row (EDI zip / survey MTH5). C46-W3a: canonical licence id +
    custodian added alongside the retained raw `license` (see _file_row)."""
    size, digest = _artifact_integrity(served)
    tier, url = _resolve_artifact(rel, served, nci_base, base_url)
    return {"survey": survey, "slug": slug, "format": fmt,
            "url": url, "size": size, "sha256": digest,
            "tier": tier, "license": license_str, "canon_license": canon_license(license_str),
            "custodian": custodian, "n_stations": n_stations}


def slugify(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


import re as _re  # noqa: E402

_UNSAFE_ID = _re.compile(r"[^A-Za-z0-9._-]")


def safe_component(s, fallback: str = "x") -> str:
    """Sanitise a station id (DATAID) or slug for safe use in ausmt_id, on-disk product paths
    and portal URLs/markup. Submitted survey packages are UNTRUSTED (staged before review), so a
    crafted DATAID like '../../etc/x' or '<img onerror=...>' must not be able to escape the
    products tree (path traversal / arbitrary write) or reach the DOM unescaped (stored XSS).
    Keep only [A-Za-z0-9._-]; neutralise '..'; strip leading dots/dashes; never return empty."""
    s = _UNSAFE_ID.sub("-", str(s if s is not None else "").strip())
    while ".." in s:
        s = s.replace("..", "-")
    s = s.lstrip(".-")
    return s or fallback


def _variant_tag(path, station_id, idx, used):
    """A short, stable tag distinguishing same-station re-processings: prefer the part of the
    filename beyond the station id (MBV20_LemiGraph -> 'lemigraph'), else a positional index.
    Sanitised and made unique within the colliding group."""
    stem = getattr(path, "stem", str(path))
    leftover = _re.sub(_re.escape(station_id), "", stem, count=1).strip(" _-.")
    tag = safe_component(leftover).lower() if leftover else f"v{idx + 1}"
    base, k = tag, 2
    while tag in used:
        tag = f"{base}-{k}"
        k += 1
    used.add(tag)
    return tag


def _disambiguate(stations, slug):
    """Keep BOTH records when two transfer functions in one survey share a station id (the same
    site processed by two codes, e.g. MBV20 from LemiGraph and Ohmega). A single id per station
    would collide on ausmt_id / product path / portal route, so append a processing-variant tag:
    au.<slug>.<station>.<variant>. Unique stations are left untouched. Mutates records in place."""
    from collections import defaultdict
    groups = defaultdict(list)
    for (p, r) in stations:
        groups[r.get("id")].append((p, r))
    for sid, members in groups.items():
        if len(members) < 2:
            continue
        used = set()
        for idx, (p, r) in enumerate(members):
            var = _variant_tag(p, sid, idx, used)
            r["variant"] = var
            r["id"] = f"{sid}.{var}"
            r["ausmt_id"] = f"au.{safe_component(slug)}.{safe_component(r['id'])}"
    return stations


def _group_collections(surveys_meta: dict, all_stations: list):
    """Group surveys into optional collections/programmes (e.g. AusLAMP): rollup of member surveys,
    station counts and extent. Rollup ONLY — collections hold no transfer functions; all scientific
    provenance stays with the child surveys. Returns (collections_by_id, survey->collection_id)."""
    survey_coll, colls = {}, {}
    _STATUS = {"active", "completed", "archived"}
    for label, m in surveys_meta.items():
        c = (m or {}).get("collection")
        if c and c.get("id"):
            cid = c["id"]; survey_coll[label] = cid
            e = colls.setdefault(cid, {"id": cid, "title": c.get("title") or cid,
                                       "type": c.get("type"), "surveys": [], "n_stations": 0,
                                       "start_year": None, "status": None, "last_updated": None,
                                       "description": None, "_lat": [], "_lon": []})
            # programme-level fields are consistent across members; take the first declared value
            for fld in ("title", "type", "start_year", "status", "last_updated", "description"):
                if e.get(fld) in (None, "") and c.get(fld) not in (None, ""):
                    e[fld] = c.get(fld)
            if e["status"] and e["status"] not in _STATUS:
                e["status"] = None      # ignore out-of-vocabulary status (validator warns separately)
            if label not in e["surveys"]:
                e["surveys"].append(label)
    for (_p, r) in all_stations:
        cid = survey_coll.get(r.get("survey"))
        if cid:
            colls[cid]["n_stations"] += 1
            if r.get("lat") is not None and r.get("lon") is not None:
                colls[cid]["_lat"].append(r["lat"]); colls[cid]["_lon"].append(r["lon"])
    out = {}
    for cid, c in colls.items():
        lat, lon = c.pop("_lat"), c.pop("_lon")
        c["surveys"] = sorted(c["surveys"])
        c["n_surveys"] = len(c["surveys"])
        if lat:
            c["bbox"] = {"west": round(min(lon), 6), "south": round(min(lat), 6),
                         "east": round(max(lon), 6), "north": round(max(lat), 6)}
            c["centroid"] = {"latitude": round(sum(lat) / len(lat), 6),
                             "longitude": round(sum(lon) / len(lon), 6)}
        else:
            c["bbox"] = c["centroid"] = None
        out[cid] = c
    return out, survey_coll


def _near_duplicate_collection_ids(cids):
    """Collection ids that differ only by case or surrounding whitespace — a likely typo that splits one
    programme into SEPARATE collections (grouping is an EXACT id match). Returns the colliding groups (each a
    sorted list of >1 ids) so the build can warn. The add-survey datalist prevents this in the UI, but a
    hand-edited survey.yaml can still introduce it."""
    seen = {}
    for cid in cids:
        seen.setdefault(str(cid).strip().lower(), []).append(cid)
    return [sorted(g) for g in seen.values() if len(g) > 1]


def _survey_latest_date(meta: dict):
    """S3: the single 'best' date for a survey, as (date_str YYYY-MM-DD, is_exact) — used for BOTH
    the Atom feed <updated> and the portal's recently-added sort, so the two never disagree.

    PINNED CROSS-LANE DATE RULE (LOCKSTEP with portal/src/main.js surveyLatestDate, the two MUST
    implement this identically so the feed and the portal strip can never show a different "latest"
    survey): the latest date = the MAX well-formed YYYY-MM-DD among ALL release_notes[].date PLUS
    attribution.declared_date when present (each a real dated event, day-precision) -> else Dec 31 of
    year_end||year_start (a bare year, so falls back to Dec 31 / midnight UTC per RFC3339 when only a
    year is known) -> else None (no date at all -> excluded from feed/recently-added, per the "dated
    data" comment on the year filter above). NOTE: the 30-day window / item limit on "recently added"
    is a PORTAL-ONLY display rule; feed.xml keeps EVERY dated survey."""
    # Candidate day-precision dates: every release_notes entry's date + the C46 attribution.declared_date
    # (stored on SMETA as a string by _survey_smeta; verified corpus key path attribution.declared_date).
    cands = []
    rn = meta.get("release_notes")
    if isinstance(rn, list):
        cands.extend(e.get("date") for e in rn if isinstance(e, dict))
    attr = meta.get("attribution")
    if isinstance(attr, dict):
        cands.append(attr.get("declared_date"))
    best = None
    for c in cands:
        d = str(c or "").strip()[:10]
        if len(d) == 10 and d[4] == "-" and d[7] == "-" and (best is None or d > best):
            best = d
    if best:
        return best, True
    yr = meta.get("year_end") or meta.get("year_start")
    if yr:
        return f"{yr:04d}-12-31", False
    return None, False


def feed_entries(surveys_meta: dict) -> list:
    """S3: surveys with a resolvable date (see _survey_latest_date), sorted NEWEST first — the
    shared ordering for BOTH feed.xml and the portal's 'recently added' strip. Each entry:
    {survey, slug, date} (date = 'YYYY-MM-DD'). Surveys with no date at all are OMITTED (not
    sorted-last with a fake date), since neither the feed nor 'recently added' should imply a date
    for data that declares none."""
    out = []
    for label, meta in surveys_meta.items():
        m = meta or {}   # PLW2901: don't reassign the loop variable
        date, _exact = _survey_latest_date(m)
        if date and m.get("slug"):
            out.append({"survey": label, "slug": m["slug"], "date": date})
    out.sort(key=lambda e: (e["date"], e["survey"]), reverse=True)
    return out


def build_feed_xml(surveys_meta: dict, base_url: str = None):
    """S3: a minimal valid Atom 1.0 feed of surveys, sorted by feed_entries() (latest release_notes
    date, falling back to the dates.end/start year). Returns the XML text, or None when NO survey
    has a resolvable date (empty builds, or a corpus with zero dated surveys, emit no feed file at
    all — an Atom feed with no dated content is not a meaningful product). Deterministic: the ONLY
    "build time" value is <feed><updated>, set to the MAX entry date (not wall-clock time), so two
    builds of the same surveys_meta are byte-identical regardless of when they run.
    `base_url`: passed a's --sitemap-base (rstrip("/") + "/") when set; entry <link> is that base +
    'surveys/<slug>' (the PATH-URL contract form, owner ruling 2026-08-18: the path shape is the
    published URL and the front door maps it into the SPA), or OMITTED (no <link> element) when
    base_url is None (the feed is still valid Atom without it, just not clickable outside the
    portal's own context)."""
    from xml.sax.saxutils import escape as _xesc
    entries = feed_entries(surveys_meta)
    if not entries:
        return None
    base = (base_url.rstrip("/") + "/") if base_url else None
    feed_updated = f"{entries[0]['date']}T00:00:00Z"   # newest entry's date = the whole feed's <updated>
    items = []
    for e in entries:
        link = f'\n    <link href="{_xesc(base + "surveys/" + e["slug"])}"/>' if base else ""
        items.append(
            "  <entry>\n"
            f'    <id>tag:ausmt:{_xesc(e["slug"])}</id>\n'
            f'    <title>{_xesc(e["survey"])}</title>\n'
            f'    <updated>{e["date"]}T00:00:00Z</updated>{link}\n'
            "  </entry>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        "  <id>tag:ausmt:feed</id>\n"
        "  <title>AusMT — recently added/updated surveys</title>\n"
        f"  <updated>{feed_updated}</updated>\n" +
        "\n".join(items) + "\n"
        "</feed>\n")


def collections_document(surveys_meta: dict, all_stations: list, coll_by_id: dict = None) -> dict:
    """Portal collections.json: {collection_id: {id, title, type, surveys[], n_surveys, n_stations,
    bbox, centroid}}. Empty when no survey declares collection membership (backwards compatible).
    `coll_by_id` may be passed in so the (single) grouping is shared with mtcat_document."""
    if coll_by_id is None:
        coll_by_id, _ = _group_collections(surveys_meta, all_stations)
    return coll_by_id


def stations_geojson(all_stations: list, surveys_meta: dict) -> dict:
    """The served stations GeoJSON (RFC 7946 FeatureCollection, one Point per station) so a GIS can add
    AusMT as a vector layer straight from the URL instead of scripting against the positional catalogue.

    COORDINATE POSTURE (C42, the only thing that makes this product safe). It is derived from the SAME
    policy-applied station records the catalogue is projected from (call it AFTER the mask seam), so it
    cannot disclose a position the catalogue withholds. A generalised station's geometry is its served
    0.1 degree cell VERBATIM: nothing is re-derived or re-rounded here, because a second rounding site is
    a second thing that can round differently.

    A WITHHELD station is EXCLUDED, not emitted with a null geometry. RFC 7946 permits a null-geometry
    feature, but no GIS draws one: QGIS keeps it as an invisible attribute row a user can neither see nor
    select, so it helps nobody and it would be a second surface describing a station whose position the
    custodian withheld. Absence is the honest answer; coord_policy.json remains the record that the
    station exists with its position withheld, and the station keeps its catalogue row, its mtcat entry
    and its station.json. There is no other exclusion: an EMBARGOED or metadata-only survey keeps
    DISCOVERY (the access gate withholds BYTES), and this document carries no bytes, so its stations
    appear here exactly as the catalogue serves them.

    Properties are lean and FLAT. A GIS attribute table has no useful nesting, and credit/licence are
    survey-level facts that already have one owner each (surveys.json, mtcat.json, and the record link in
    the docs); a copy of the licence string on every one of ~1400 features is bloat, not provenance."""
    feats = []
    for (_p, r) in all_stations:
        lat, lon = r.get("lat"), r.get("lon")
        if lat is None or lon is None:
            continue   # withheld position => no usable geometry => no feature (see the docstring)
        feats.append({
            "type": "Feature",
            # RFC 7946 positions are [longitude, latitude], the opposite order to every AusMT surface
            # that says "lat, lon". Getting this backwards still parses and still draws, in the Indian
            # Ocean, so the order is pinned by test_stations_geojson.
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "ausmt_id": r["ausmt_id"],
                "station": r["id"],
                "survey": r["survey"],                                    # display label
                "survey_id": (surveys_meta.get(r["survey"]) or {}).get("slug"),   # slug, never re-derived
                "data_type": r.get("type"),
                "period_min_s": r.get("period_min_s"),
                "period_max_s": r.get("period_max_s"),
            },
        })
    return {"type": "FeatureCollection", "features": feats}


# MTCAT 1.2: the canonical band order the survey-level data_types map is emitted in (the SAME order the
# portal presents bands in, so the served key order and the rendered order can never disagree). A band the
# classifier produces but this tuple does not name (only "unknown" today) is appended, sorted, after these:
# the map NEVER silently drops a station's band.
_MTCAT_TYPE_ORDER = ("BBMT", "LPMT", "AMT", "GDS")


def _type_mix(counts: dict) -> dict:
    """{data_type: n_stations} in _MTCAT_TYPE_ORDER, then any unnamed band sorted. {} when no stations."""
    named = [t for t in _MTCAT_TYPE_ORDER if t in (counts or {})]
    rest = sorted(t for t in (counts or {}) if t not in _MTCAT_TYPE_ORDER)
    return {t: counts[t] for t in named + rest}


def _formats_by_survey(manifest_doc):
    """MTCAT 1.2: {survey label: sorted[format]} from the build's download manifest, or None when no
    manifest was supplied. The manifest is the ONE authority on what is actually distributed, and its rows
    are written only for a survey whose bytes the access/licence gate lets through, so a withheld
    (embargoed or metadata-only) survey derives an EMPTY format list here automatically, with no separate
    withholding rule to keep in step. None (no manifest at all) is distinct from {} and makes the caller
    OMIT the key: "not known" must not be served as "nothing distributed"."""
    if not isinstance(manifest_doc, dict):
        return None
    out = {}
    for row in list(manifest_doc.get("files") or []) + list(manifest_doc.get("bundles") or []):
        if isinstance(row, dict) and row.get("survey") and row.get("format"):
            out.setdefault(row["survey"], set()).add(str(row["format"]))
    return {k: sorted(v) for k, v in out.items()}


def _canonical_sample_rates(values) -> list:
    """The ONE sample-rate canonicaliser (ratified, deterministic, RED-proven against a
    float-artefact fixture): round each explicit rate to 6 SIGNIFICANT figures, dedupe, sort
    ascending. Integral canonical values are emitted as integers (the spec example's [10, 150,
    24000] shape); binary-float noise on the same physical rate (149.99999999999997 vs
    150.00000000000003) collapses to one mode. Non-positive/unparseable inputs are dropped - a
    rate is EXPLICIT acquisition metadata or it is nothing."""
    out = set()
    for v in values or ():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not f > 0:
            continue
        c = float(f"{f:.6g}")
        out.add(int(c) if c.is_integer() and abs(c) < 1e15 else c)
    return sorted(out)


def _omit_none(node):
    """MTCAT 2.0 omit-when-undeclared: recursively drop every None-valued dict key (the exact
    clean() of the ratified migrate_12_to_20 transform). List elements are cleaned in place-order;
    scalars pass through. Callers apply this to surveys[]/collections[]/portal - NEVER to
    stations[], whose paired latitude/longitude nulls are the one defined null."""
    if isinstance(node, dict):
        return {k: _omit_none(v) for k, v in node.items() if v is not None}
    if isinstance(node, list):
        return [_omit_none(v) for v in node]
    return node


def _coordinates_state(policies, declared_default):
    """The ratified aggregation rule over a survey's per-station effective coordinate policies:
    all exact => exact; all withheld => withheld; any other mixture => generalised (the
    conservative reading). A survey with no stations falls back to its DECLARED survey default
    (today's survey-level policy makes every case trivial; the rule is implemented anyway)."""
    states = set(policies or ())
    if not states:
        return declared_default or "exact"
    if states == {"exact"}:
        return "exact"
    if states == {"withheld"}:
        return "withheld"
    return "generalised"


def mtcat_document(surveys_meta: dict, all_stations: list, generated_at: str = None,
                   portal: dict = None, coll_by_id: dict = None,
                   manifest_doc: dict = None) -> dict:
    """Build an MTCAT discovery/federation document (see docs/docs/reference/mtcat-schema.md and
    schema/mtcat.schema.json).
    Portal owns its data; MTCAT is the shared, minimal metadata other
    portals could harvest. Derived purely from already-computed catalogue data — no new science.
    `coll_by_id` may be passed in so the (single) collection grouping is shared with
    collections_document instead of being recomputed here.

    MTCAT 2.0 (the ratified migrate_12_to_20 transform implemented AT THE SOURCE):

      * omit-when-undeclared everywhere (see _omit_none); the paired station position nulls are
        the one defined null.
      * formats emitted only when at least one format is distributed - an embargoed/withheld
        survey OMITS the key (owner finding 62), and no manifest at all omits it corpus-wide
        ("not known" is never served as "nothing distributed"; see _formats_by_survey).
      * sources[]/changes are NEVER emitted: sources rows map to related_identifiers rows; a row
        carrying rights content (statement/licence/retrieved/profile) HARD-STOPS the build so the
        content is captured in survey-metadata rather than silently deleted.
      * the top-level mt_metadata_version/mth5_version keys are gone (legacy 1.x, removed in 2.0).
      * NEW: description (discovery_description, else the abstract when already <= 1200 - never
        truncated by the engine), subjects[] verbatim, sample_rates_hz[] from explicit run
        metadata only (canonicalised, see _canonical_sample_rates), coordinates_state projected
        from the survey's DECLARED access.coordinates policy (see _coordinates_state).
      * stations[].has_time_series / surveys[].n_stations_time_series_verified are schema-defined
        for the later projection lane and emitted NOWHERE here.

    `manifest_doc` is the manifest built earlier in the same run."""
    from datetime import datetime, timezone
    slug_of, bbox_of = {}, {}
    n_of, types_of, per_of, tip_of = {}, {}, {}, {}
    rates_of, pol_of, ts_n_of = {}, {}, {}
    fmt_of = _formats_by_survey(manifest_doc)
    for (_p, r) in all_stations:
        lbl, aid, sid = r["survey"], r["ausmt_id"], r["id"]
        slug = aid[3:]                                   # strip "au."
        if slug.endswith("." + sid):
            slug = slug[:-(len(sid) + 1)]                # strip ".<station>"
        slug_of[lbl] = slug
        if r["lat"] is not None and r["lon"] is not None:
            b = bbox_of.setdefault(lbl, [r["lon"], r["lat"], r["lon"], r["lat"]])  # w,s,e,n
            b[0] = min(b[0], r["lon"]); b[1] = min(b[1], r["lat"])
            b[2] = max(b[2], r["lon"]); b[3] = max(b[3], r["lat"])
        # Derived facets, accumulated in the walk that was already happening (no second pass and
        # no new upstream computation): station count, band mix, period range and tipper count.
        n_of[lbl] = n_of.get(lbl, 0) + 1
        _t = r.get("type")
        if _t:
            _c = types_of.setdefault(lbl, {})
            _c[_t] = _c.get(_t, 0) + 1
        if "T" in (r.get("comps") or ""):     # the tipper component, exactly as the catalogue records it
            tip_of[lbl] = tip_of.get(lbl, 0) + 1
        _pr = per_of.setdefault(lbl, [None, None])
        for _i, _v in ((0, r.get("period_min_s")), (1, r.get("period_max_s"))):
            if _v is not None:                # each bound guarded separately: a half-populated row still counts
                _pr[_i] = _v if _pr[_i] is None else (min(_pr[_i], _v) if _i == 0 else max(_pr[_i], _v))
        # MTCAT 2.0: the survey's explicit sample-rate modes (record_from_tf attaches the key ONLY
        # when a run declared a rate) and the per-station effective coordinate policy (stamped on
        # non-exact records by the one mask seam; an unstamped record is exact by construction).
        if r.get("sample_rates_hz"):
            rates_of.setdefault(lbl, set()).update(r["sample_rates_hz"])
        pol_of.setdefault(lbl, set()).add(r.get("coord_policy") or "exact")
        if r.get("has_ts"):
            ts_n_of[lbl] = ts_n_of.get(lbl, 0) + 1
    surveys = []
    for lbl, meta in sorted(surveys_meta.items()):
        bb = bbox_of.get(lbl)
        m = meta or {}
        entry = {
            "survey_id": slug_of.get(lbl, slugify(lbl)), "title": lbl,
            "organisation": m.get("org", "unknown"),
            # C7: additive optional federation fields - the organisation's ROR and the project's
            # RAiD, when the survey declares them; None here is DROPPED by the _omit_none pass.
            "organisation_ror": m.get("org_ror"),
            "raid": m.get("raid"),
            "country": m.get("country", "Australia"),
            "version": m.get("version"),
            "collection_id": (m.get("collection") or {}).get("id"),
            "doi": m.get("doi"), "license": m.get("lic"),
            # C1: emit the NORMALISED access level. SMETA already normalises it; normalise again so
            # a raw-mode seed value stays a clean scalar.
            "access": normalise_access_level(m.get("access", "open")),
            "bbox": ({"west": round(bb[0], 6), "south": round(bb[1], 6),
                      "east": round(bb[2], 6), "north": round(bb[3], 6)} if bb else None),
            "centroid": ({"latitude": round((bb[1] + bb[3]) / 2, 6),
                          "longitude": round((bb[0] + bb[2]) / 2, 6)} if bb else None),
            # The DERIVED discovery facets. Counts are emitted for every survey (0 is a real count);
            # the band mix and period bounds are emitted only when there is something to state
            # (2.0 forbids the empty-object/null states). n_stations is a convenience over
            # stations[], which stays authoritative; the schema says so.
            "n_stations": n_of.get(lbl, 0),
            "data_types": _type_mix(types_of.get(lbl)) or None,
            "period_min_s": per_of.get(lbl, [None, None])[0],
            "period_max_s": per_of.get(lbl, [None, None])[1],
            "n_stations_tipper": tip_of.get(lbl, 0),
            # The declared acquisition year range, a verbatim SMETA pass-through (never inferred
            # from file timestamps); undeclared drops out in the _omit_none pass.
            "year_start": m.get("year_start"),
            "year_end": m.get("year_end")}
        # MTCAT 2.0: the concise discovery text. The explicit survey.yaml discovery_description
        # wins; else the UNCAPPED abstract rides through only when it is already within the
        # ratified 1200-char discovery budget. The engine NEVER truncates: an over-long abstract
        # with no discovery text is a surveys-side validation failure, not an engine edit.
        _desc = m.get("discovery_description")
        if not _desc:
            _blurb = m.get("blurb")
            if isinstance(_blurb, str) and _blurb and len(_blurb) <= 1200:
                _desc = _blurb
        if _desc:
            entry["description"] = _desc
        # MTCAT 2.0: subjects[] VERBATIM from survey.yaml (curation asserts, the engine never
        # invents); absent means no assertion.
        if m.get("subjects"):
            entry["subjects"] = m["subjects"]
        # MTCAT 2.0: the explicit acquisition sample-rate modes across this survey's stations,
        # canonicalised (6 significant figures, deduped, ascending). Emitted only when at least one
        # run DECLARED a rate; never inferred from instrument model or period coverage.
        _rates = _canonical_sample_rates(rates_of.get(lbl))
        if _rates:
            entry["sample_rates_hz"] = _rates
        # MTCAT 2.0: coordinates_state, projected ONLY when the survey DECLARES an
        # access.coordinates policy (the state is public, the reason stays private; absence makes
        # no assertion). Aggregated over the per-station effective policies; a withheld state
        # forbids bbox/centroid (already absent by construction - a withheld survey's stations
        # carry no published positions - and asserted by the invariant suite + schema).
        if m.get("coord_policy_declared"):
            _state = _coordinates_state(pol_of.get(lbl), m.get("coord_policy_default"))
            entry["coordinates_state"] = _state
            if _state == "withheld":
                entry["bbox"] = None
                entry["centroid"] = None
        # C46-W3a: the attribution rights block, PRESENT ONLY when the survey declares it, emitted
        # verbatim from SMETA. MTCAT 2.0 REMOVED the sources/changes blocks: a sources row maps to
        # a related_identifiers row below, and the changes facts already live inside attribution
        # (SMETA's changes descriptor is derived FROM attribution, so nothing is lost).
        if m.get("attribution") is not None:
            entry["attribution"] = m["attribution"]
        # §2a: the typed provenance relations, PRESENT ONLY when the survey declares any. SMETA
        # carries this as always-a-list ([] when absent); emit only the non-empty list (2.0 forbids
        # empty arrays). A legacy sources[] row is MAPPED here (spec 6.9, the ratified transform):
        # its identifier keys become a relationship row; rights content in a row is a HARD STOP
        # because it must be captured in survey-metadata, never silently deleted.
        _rel = list(m.get("related_identifiers") or [])
        for _row in (m.get("sources") or []):
            if any(_row.get(k) for k in ("statement", "licence", "retrieved", "profile")):
                raise NotImplementedError(
                    f"survey '{lbl}': a sources[] row carries statement/licence/retrieved/profile "
                    f"content; capture it in survey-metadata before this survey can emit under "
                    f"MTCAT 2.0 (the transform hard-stops rather than silently deleting rights text)")
            _mapped = {k: _row[k] for k in ("identifier", "identifier_type", "relation",
                                            "identifies", "custodian") if _row.get(k) is not None}
            if _mapped.get("identifier"):
                _rel.append(_mapped)
        if _rel:
            entry["related_identifiers"] = _rel
        # CONTRIBUTOR-CREDIT-SPEC C1/§4: the credit surface for the DataCite/federation export.
        # creators[] rides through verbatim when the survey declares it. contributors[] is the
        # EXPORT form: the survey's own contributors PLUS AusMT as the HostingInstitution, added
        # automatically on export only (never a curator field, never in survey.yaml).
        if m.get("creators"):
            entry["creators"] = m["creators"]
        entry["contributors"] = _export_contributors_of(m)
        # MTCAT 2.0 formats: what is ACTUALLY distributed, off the download manifest (the one
        # authority) - emitted ONLY when at least one format is distributed. An embargoed/withheld
        # survey OMITS the key (owner finding 62: under represented-holdings semantics, [] would
        # falsely assert that no formats are KNOWN when the holdings exist and are merely
        # withheld). No manifest at all also omits it: "not known" is never served as "nothing
        # distributed".
        if fmt_of is not None and fmt_of.get(lbl):
            entry["formats"] = fmt_of[lbl]
        # The embargo end date, present ONLY when the survey declares one (absent means "no
        # declared end date", NOT "not embargoed" - `access` above is the state of record).
        if m.get("embargo_until"):
            entry["embargo_until"] = m["embargo_until"]
        # THREDDS A4: the tally of this survey's true flags - present iff POSITIVE (spec 245-250:
        # existence semantics make it stable across access transitions and never derivable by
        # subtraction; an absent count asserts nothing, a zero would).
        if ts_n_of.get(lbl):
            entry["n_stations_time_series_verified"] = ts_n_of[lbl]
        # MTCAT 2.0 omit-when-undeclared: drop every remaining None-valued key, at every depth
        # (relationship rows included - the 110-error class). The stations[] rows below are NOT
        # cleaned: their paired latitude/longitude nulls are the one defined null.
        surveys.append(_omit_none(entry))
    stations = [{"station_id": r["ausmt_id"], "survey_id": slug_of.get(r["survey"], slugify(r["survey"])),
                 "latitude": r["lat"], "longitude": r["lon"], "data_type": r["type"],
                 # THREDDS A4: true-or-absent, never false (spec 373-383, existence semantics).
                 **({"has_time_series": True} if r.get("has_ts") else {})}
                for (_p, r) in all_stations]
    if coll_by_id is None:
        coll_by_id, _ = _group_collections(surveys_meta, all_stations)
    collections = [_omit_none({"collection_id": c["id"], "title": c["title"], "type": c["type"],
                               "status": c.get("status"), "start_year": c.get("start_year"),
                               "last_updated": c.get("last_updated"), "description": c.get("description"),
                               "n_surveys": c["n_surveys"], "n_stations": c["n_stations"],
                               "bbox": c["bbox"], "centroid": c["centroid"]})
                   for c in sorted(coll_by_id.values(), key=lambda x: x["id"])]
    p = portal or {}
    doc = {
        "portal": _omit_none(
                  {"portal_id": p.get("portal_id", "ausmt"),
                   "portal_name": p.get("portal_name", "AusMT — Australia's Magnetotelluric Data Portal"),
                   # The version is NEVER a literal here: MTCAT_SCHEMA_VERSION is generated from the
                   # single-source MTCAT_VERSION constant (contract/generate.py), so this document
                   # cannot claim a version the schema served beside it does not display.
                   "schema": "mtcat", "version": str(p.get("schema_version", MTCAT_SCHEMA_VERSION)),
                   # FAIR-I: point harvesters at the schema served BESIDE this document (relative to the
                   # data dir — the build copies schema/mtcat.schema.json to out/mtcat.schema.json), so a
                   # second implementation can validate mtcat.json without resolving the canonical $id.
                   "schema_url": p.get("schema_url", "mtcat.schema.json"),
                   # FAIR-R: the licence of the CATALOGUE METADATA itself (distinct from per-survey data
                   # licences). CC0 by recommendation; overridable via portal.config.yaml pending owner
                   # sign-off on the catalogue-metadata licence.
                   "metadata_license": p.get("metadata_license", "CC0-1.0"),
                   "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}),
        "surveys": surveys, "stations": stations}
    # collections joins the document only when at least one exists (2.0 forbids the empty-array
    # state; schema minItems 1). The 1.2 always-present-empty-list shape is gone with the version.
    if collections:
        doc["collections"] = collections
    # MTCAT 2.0 removed the top-level mt_metadata_version/mth5_version keys (legacy 1.x, SHOULD NOT
    # be newly adopted): build.json / build_provenance.json / manifest.json remain the homes of the
    # served-tool versions.
    return doc


# --- survey-metadata.json: the SECOND public contract (AusMT_2026/AUSMT-SURVEY-METADATA-SCOPE.md,
# AUSMT-METADATA-INTERFACE-CONTRACT.md, schema/ausmt-survey-metadata.schema.json 0.1). One document per
# survey at out/products/<survey_id>/survey-metadata.json (the served root, never the --products dir):
# the canonical public metadata of one survey dataset/release, generated from the RAW survey.yaml
# (a discovery side channel; SMETA and surveys.json are untouched, D18). The emitter never invents a
# curated fact: every class is verbatim from survey.yaml when present and ABSENT otherwise (open-world;
# no nulls, no empty containers, no library defaults as assertions). Discovery is universal, so a
# non-served (embargoed / metadata_only) survey emits every curated class exactly as mtcat does (D8);
# the only policy seam is the coordinate policy (a withheld state omits the curated extent, D7). ----------

# The identifies -> DataCite relation derivation (owner ruling D-L2): the SAME table the surveys
# validator (validate_survey.IDENTIFIES_RELATION) and the gateway editor (gateway/editor_form.py) carry.
# A related_identifiers row states the data level it points at and the relation follows; an explicit
# relation on the row stands when present.
_IDENTIFIES_RELATION = {
    "collection": "IsPartOf",       # the parent record (e.g. an NCI parent collection)
    "raw_packed": "IsDerivedFrom",  # raw/packed time series
    "level0": "IsDerivedFrom",      # edited time series
    "level1": "IsDerivedFrom",      # transformed time series
    "level2": "IsVariantFormOf",    # derived frequency-domain processed data (EDI/TF)
    "level3": "IsSourceOf",         # models (the model derives FROM this dataset)
    "entire": "IsVariantFormOf",    # a single record covering all levels (a GA eCAT / state landing page)
}
# The validator's placeholder semantics (validate_survey._has_real_value): None, "", TBD, TODO and the
# survey.yaml template's REPLACE sentinel are "no value" and never become a public assertion.
_SM_PLACEHOLDER_MARK = "« REPLACE »"
# A DOI resolver prefix on a curated DOI is stripped at emission (the schema wants bare DOIs); the
# DOI's own case is kept (DOIs are case-insensitive, and a Record DOI's curated form is the form cited).
_SM_DOI_RESOLVER_RE = _re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", _re.IGNORECASE)
# A DOI in the bare canonical form the station schema wants (scope 4.2), after the resolver prefix
# above is stripped. Anything else is not placeable as a DOI and is reported for curation.
_BARE_DOI_RE = _re.compile(r"^10\.\d{4,9}/\S+$")
# extent is emitted ONLY from a curated WGS 84 geographic_extent (D7: never station-derived; the
# schema's CRS rule). GDA94/GDA2020 extents wait on an owner ruling and are omitted meanwhile.
_SM_WGS84_DATUMS = {"WGS84", "EPSG:4326", "WGS-84"}


def _sm_real(v) -> bool:
    """True when a curated value is a real assertion: not None, not a blank/TBD/TODO/REPLACE string.
    Booleans and numbers are always real (False is an assertion, 0 is a value)."""
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        return s not in ("", "TBD", "TODO") and _SM_PLACEHOLDER_MARK not in s
    return True


def _sm_plain(node):
    """Prune a curated block for public emission: drop every placeholder scalar at every depth, then
    every container that emptied; date/time values become ISO strings so the in-memory document is
    plain JSON. Returns None when nothing real is left (the caller omits the key)."""
    import datetime as _dt  # noqa: PLC0415 (house style: local import where used)
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            pv = _sm_plain(v)
            if pv is not None:
                out[k] = pv
        return out or None
    if isinstance(node, list):
        out = [pv for pv in (_sm_plain(v) for v in node) if pv is not None]
        return out or None
    if isinstance(node, (_dt.date, _dt.time)):   # datetime subclasses date
        return node.isoformat()
    return node if _sm_real(node) else None


def _sm_bare_identifier(scheme, identifier) -> str:
    """The identifier in the form the schema wants: a DOI loses a resolver prefix (https://doi.org/,
    http://dx.doi.org/), every other scheme is verbatim; surrounding whitespace is trimmed; case kept."""
    s = str(identifier).strip()
    if str(scheme or "").strip().upper() == "DOI":
        s = _SM_DOI_RESOLVER_RE.sub("", s)
    return s


def _sm_pair(entry):
    """A complete curated {scheme, identifier} pair in emission form, or None (half pairs and
    placeholders are no assertion; the validator FAILs them at the entry gates anyway)."""
    if not isinstance(entry, dict) or not (_sm_real(entry.get("scheme")) and _sm_real(entry.get("identifier"))):
        return None
    return {"scheme": str(entry["scheme"]).strip(),
            "identifier": _sm_bare_identifier(entry["scheme"], entry["identifier"])}


def _sm_designated_identifiers(y: dict) -> list:
    """identifiers[] (the identifiers OF this dataset/release, D12): the identity_classification
    MAPPING designates them - represents[] for case_a (the source identifiers this record is the SAME
    dataset/release as), own_identifiers[] for case_b (the distinct AusMT release's own). Curated order,
    exact duplicates dropped. An absent classification, or the legacy scalar form (unreachable in a
    validated build since S1), designates nothing: identifiers[] is absent and every related row is a
    relationship."""
    ic = y.get("identity_classification")
    if not isinstance(ic, dict):
        return []
    case = str(ic.get("case") or "").strip()
    rows = ic.get("represents") if case == "case_a" else (ic.get("own_identifiers") if case == "case_b" else None)
    out = []
    for r in (rows or []) if isinstance(rows, list) else []:
        pair = _sm_pair(r)
        if pair is not None and pair not in out:
            out.append(pair)
    return out


def _sm_relationships(y: dict, designated: list) -> list:
    """relationships[]: every related_identifiers row that is NOT a designated identifier of this
    dataset, reduced to the shared clean core {identifier, identifier_type, relation} (MTCAT's legacy
    row extensions custodian/identifies/resolution are deliberately not inherited). relation is the
    row's explicit relation, else the one its identifies level derives to, else absent; the resolver
    prefix is stripped, case kept, exact duplicates dropped."""
    # Scheme comparison is CASE-FOLDED (the same normalisation _sm_bare_identifier applies for its
    # own DOI test): a curated scheme "doi" beside identifier_type "DOI" used to miss the dedup and
    # publish the dataset IsIdenticalTo itself - the self-reference the D12 partition exists to
    # prevent. The published rows keep their curated spelling; only the KEY folds.
    keys = {(str(d["scheme"]).upper(), d["identifier"]) for d in designated}
    out = []
    for r in (y.get("related_identifiers") or []):
        if not isinstance(r, dict) or not _sm_real(r.get("identifier")):
            continue
        itype = str(r["identifier_type"]).strip() if _sm_real(r.get("identifier_type")) else None
        ident = _sm_bare_identifier(itype, r["identifier"])
        if itype is not None and (itype.upper(), ident) in keys:
            continue
        row = {"identifier": ident}
        if itype is not None:
            row["identifier_type"] = itype
        rel = (str(r["relation"]).strip() if _sm_real(r.get("relation"))
               else _IDENTIFIES_RELATION.get(str(r.get("identifies") or "").strip()))
        if rel:
            row["relation"] = rel
        if row not in out:
            out.append(row)
    return out


def _sm_rows(seq, required: tuple) -> list:
    """Curated rows (creators, contributors, subjects, organisations, acknowledgements) VERBATIM after
    the placeholder prune; a row missing a schema-required member is no assertion and is dropped (the
    same tolerance _credit_rows applies; the validator WARNs on such rows at the entry gates)."""
    out = []
    for r in (seq or []) if isinstance(seq, list) else []:
        if not isinstance(r, dict):
            continue
        pr = _sm_plain(r)
        if not pr or any(k not in pr for k in required):
            continue
        out.append(pr)
    return out


def _sm_funders(y: dict) -> list:
    """funders[] per D6 (DataCite-aligned): organisation -> name, organisation_ror -> ror, grant_id ->
    award_number, grant_title -> award_title, funding_doi -> award_uri (https://doi.org/<bare>, ratified
    at GO). A name-only row is valid; a row without a funder name is not a funder. The legacy
    name/pid/id spellings _funders_of tolerates are read the same way."""
    out = []
    for f in (y.get("funding") or y.get("funders") or []):
        if not isinstance(f, dict):
            continue
        name = f.get("organisation") if _sm_real(f.get("organisation")) else f.get("name")
        if not _sm_real(name):
            continue
        row = {"name": name if isinstance(name, str) else str(name)}
        ror = f.get("organisation_ror") if _sm_real(f.get("organisation_ror")) else f.get("pid")
        if _sm_real(ror):
            row["ror"] = ror if isinstance(ror, str) else str(ror)
        gid = f.get("grant_id") if _sm_real(f.get("grant_id")) else f.get("id")
        if _sm_real(gid):
            row["award_number"] = gid if isinstance(gid, str) else str(gid)
        if _sm_real(f.get("grant_title")):
            row["award_title"] = f["grant_title"] if isinstance(f["grant_title"], str) else str(f["grant_title"])
        if _sm_real(f.get("funding_doi")):
            row["award_uri"] = "https://doi.org/" + _sm_bare_identifier("DOI", f["funding_doi"])
        out.append(row)
    return out


def _sm_citation(y: dict):
    """The citation block verbatim: preferred_identifier {scheme, identifier} (resolver prefix stripped
    like every identifier, so T25 compares like with like), preferred_text, text_source, additional[]
    rows {identifier?, preferred_text?, reason} (a row without a reason is no assertion)."""
    cit = y.get("citation")
    if not isinstance(cit, dict):
        return None
    out = {}
    pref = _sm_pair(cit.get("preferred_identifier"))
    if pref is not None:
        out["preferred_identifier"] = pref
    if _sm_real(cit.get("preferred_text")):
        out["preferred_text"] = cit["preferred_text"]
    if _sm_real(cit.get("text_source")):
        out["text_source"] = str(cit["text_source"]).strip()
    add = []
    for row in (cit.get("additional") or []) if isinstance(cit.get("additional"), list) else []:
        if not isinstance(row, dict) or not _sm_real(row.get("reason")):
            continue
        a = {}
        ident = _sm_pair(row.get("identifier"))
        if ident is not None:
            a["identifier"] = ident
        if _sm_real(row.get("preferred_text")):
            a["preferred_text"] = row["preferred_text"]
        a["reason"] = row["reason"] if isinstance(row["reason"], str) else str(row["reason"])
        add.append(a)
    if add:
        out["additional"] = add
    return out or None


def _sm_extent(y: dict, coord_state):
    """extent {bbox} from the curated geographic_extent ONLY (D7): emitted when the datum is WGS 84, the
    four bounds are numbers and not the template's all-zero placeholder, and the survey's coordinate
    state is not withheld (a withheld survey publishes no footprint, the mtcat rule)."""
    if coord_state == "withheld":
        return None
    ext = y.get("geographic_extent")
    if not isinstance(ext, dict):
        return None
    datum = str(ext.get("datum") or "").strip().upper().replace(" ", "")
    if datum not in _SM_WGS84_DATUMS:
        return None
    try:
        bbox = {k: float(ext.get(k)) for k in ("west", "south", "east", "north")}
    except (TypeError, ValueError):
        return None
    if all(v == 0 for v in bbox.values()):
        return None
    return {"bbox": bbox}


def _sm_dates(y: dict):
    """dates: coverage {year_start, year_end} through the SAME year-range helper the portal filter and
    mtcat use (_year_range_of; an unparseable year is simply absent), and issued VERBATIM as an ISO date
    string (never derived from acquisition; unknown = absent)."""
    import datetime as _dt  # noqa: PLC0415 (house style: local import where used)
    ys, ye = _year_range_of(y)
    out = {}
    cov = {k: v for k, v in (("year_start", ys), ("year_end", ye)) if v is not None}
    if cov:
        out["coverage"] = cov
    d = y.get("dates")
    issued = d.get("issued") if isinstance(d, dict) else None
    if isinstance(issued, _dt.datetime):
        out["issued"] = issued.date().isoformat()
    elif isinstance(issued, _dt.date):
        out["issued"] = issued.isoformat()
    elif _sm_real(issued):
        out["issued"] = str(issued).strip()
    return out or None


def survey_metadata_document(label, y: dict, smeta: dict, served: bool, coord_state: str,
                             prov: dict = None, generated_at: str = None) -> dict:
    """Build one survey's survey-metadata.json (schema/ausmt-survey-metadata.schema.json 0.1, the
    second public contract) from the RAW survey.yaml mapping `y` plus the SMETA entry (for the
    authoritative slug and the normalised access state the byte gate used). Returns a plain-JSON dict
    in the schema's property order; the caller serialises with _jdump(doc, indent=1).

    `served` is the survey's access_serve_state["served"], captured at the emit site. Under D8 (no new
    withholding: discovery is universal and this document carries no distribution facts) it gates NO
    class - the argument is the policy-before-emission seam a per-class refinement for embargoed
    surveys would plug into, never an invention of this emitter. `coord_state` is the aggregated
    post-mask coordinate state (exact / generalised / withheld): a withheld survey emits no extent (D7).

    The mapping (LANE-CONTRACT-SURVEY-METADATA D5-D13):
      * title = project_name, else name (never the directory name); survey_id = the slug.
      * abstract, subjects, creators, contributors, organisations, citation, acknowledgements,
        dates.issued and attribution VERBATIM when present (placeholders pruned); no HostingInstitution
        append (D9) and no engine-authored acknowledgement (D10); funders per D6.
      * dates.coverage via _year_range_of; rights {license raw, access normalised, embargo_until}.
      * extent from the curated WGS 84 geographic_extent only (D7); identifiers[] from the
        identity_classification mapping and every other related_identifiers row to relationships[]
        (D12); activities[] from identifiers.project_raid only (D13); dataset_version omitted (D5).
      * provenance {generated, generator}; no nulls, no empty containers, ever."""
    import datetime as _dt  # noqa: PLC0415 (house style: local import where used)
    del label  # the display label is never a source of the title (it falls back to the directory name)
    del served  # D8: nothing class-wise is withheld here (see the docstring)
    prov = prov or {}
    sm = smeta or {}
    title = next((v for v in (y.get("project_name"), y.get("name")) if _sm_real(v)), None)
    designated = _sm_designated_identifiers(y)
    raid = _raid_of(y)
    rights = {}
    if _sm_real(y.get("license")):
        rights["license"] = y["license"] if isinstance(y["license"], str) else str(y["license"])
    rights["access"] = normalise_access_level(sm.get("access", "open"))
    if _sm_real(sm.get("embargo_until")):
        rights["embargo_until"] = str(sm["embargo_until"]).strip()
    generator = " ".join(str(x) for x in (prov.get("pipeline"), prov.get("pipeline_version")) if x)
    doc = {
        "schema": "ausmt-survey-metadata",
        # NEVER a literal: SURVEY_METADATA_SCHEMA_VERSION is generated from the single-source constant
        # (contract/generate.py), so the document cannot claim a version the schema beside it does not.
        "version": SURVEY_METADATA_SCHEMA_VERSION,
        "survey_id": sm.get("slug") or safe_component(y.get("slug", "")),
        "title": (title if isinstance(title, str) else (str(title) if title is not None else None)),
        "dates": _sm_dates(y),
        "identifiers": designated or None,
        "activities": [{"identifier": raid, "scheme": "RAiD"}] if raid else None,
        "abstract": (y["abstract"] if isinstance(y.get("abstract"), str) else str(y["abstract"]))
        if _sm_real(y.get("abstract")) else None,
        "subjects": _sm_rows(y.get("subjects"), ("code", "scheme")) or None,
        "creators": _sm_rows(y.get("creators"), ("name",)) or None,
        "contributors": _sm_rows(y.get("contributors"), ("name",)) or None,
        "organisations": None,
        "funders": _sm_funders(y) or None,
        "citation": _sm_citation(y),
        "acknowledgements": _sm_rows(y.get("acknowledgements"), ("text",)) or None,
        "rights": rights,
        "extent": _sm_extent(y, coord_state),
        "relationships": _sm_relationships(y, designated) or None,
        "attribution": _sm_plain(y.get("attribution")) if isinstance(y.get("attribution"), dict) else None,
        "provenance": {"generated": generated_at or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "generator": generator or None},
    }
    # organisations[]: verbatim role-typed rows {name, ror?, roles[], primary_custodian?}; the
    # primary_custodian flag is emitted ONLY as the schema's present-true marker (a curated false is the
    # absence of the marker, never a false assertion).
    orgs = []
    for o in _sm_rows(y.get("organisations"), ("name", "roles")):
        if o.get("primary_custodian") is not True:
            o.pop("primary_custodian", None)
        orgs.append(o)
    doc["organisations"] = orgs or None
    return _sm_plain(doc) or {}


def _sm_scan_nulls_and_empties(doc):
    """The zero-null / zero-empty scan over one survey-metadata document (every null at any depth,
    every empty array/object at any depth; this document defines no null at all)."""
    nulls, empties = [], []

    def walk(node, path):
        if isinstance(node, dict):
            if not node:
                empties.append(path)
            for k, v in node.items():
                if v is None:
                    nulls.append(f"{path}.{k}")
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            if not node:
                empties.append(path)
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(doc, "$")
    return nulls, empties


# --- survey.yaml -> SMETA: per-facet mappers (each small + independently testable; the assembler
# below just composes them). Both the Prototype-20 structured schema and the older flat schema. ----

def _org_of(y: dict):
    """(name, ror) from organisation: a {name, ror} map, or a bare string (then ror=None)."""
    org = y.get("organisation")
    if isinstance(org, dict):
        return org.get("name"), org.get("ror")
    return org or "unknown", None


# A1 (CONTRIBUTOR-CREDIT-SPEC C3, reader retirement): the back-compat 'who' facet that folded the two
# retired flat credit keys into a served SMETA list is GONE, and with it the reader that built it. The
# corpus migration seeded creators[]/contributors[] from those keys and deleted them, so nothing reads
# them anywhere in the engine; a survey that still carries them (a pre-migration corpus) is simply
# ignored, never served. creators[]/contributors[] are the credit surface (_creators_of/_contributors_of).


# CONTRIBUTOR-CREDIT-SPEC C1/C2: the two typed credit lists passed through to SMETA VERBATIM from
# survey.yaml (after validation). creators[] is the ORDERED citation-author list; contributors[] is the
# roled who-did-what list. Only the validated keys ride through, in canonical order; a key is OMITTED
# when the source row omits it (an ORCID-less row serves no orcid key, not a null), so a survey without
# these lists serves no such key (the pinned drawer/engine seam: absent -> absent). Non-mapping rows and
# rows without a real name are dropped (mirrors _funders_of / _related_identifiers_of tolerance).
_CREATOR_KEYS = ("name", "name_type", "orcid", "ror")
_CONTRIBUTOR_KEYS = ("name", "name_type", "role", "orcid", "ror")


def _credit_rows(seq, keys) -> list:
    out = []
    for c in (seq or []):
        if not isinstance(c, dict) or c.get("name") in (None, ""):
            continue
        out.append({k: c[k] for k in keys if c.get(k) not in (None, "")})
    return out


def _creators_of(y: dict) -> list:
    """The ORDERED creators[] list, verbatim (order IS the citation author order); [] when absent."""
    return _credit_rows(y.get("creators"), _CREATOR_KEYS)


def _contributors_of(y: dict) -> list:
    """The contributors[] list (each carries a fail-closed role), verbatim; [] when absent."""
    return _credit_rows(y.get("contributors"), _CONTRIBUTOR_KEYS)


def _citation_authors_of(y: dict):
    """CONTRIBUTOR-CREDIT-SPEC §2.1 citation-author assembly for the cite.au line: the creators[] names
    in order (joined '; ' so a 'Last, First' name stays unambiguous) when creators are present; else a
    hand-authored verbatim cite.au string when the survey carries a cite block with one; else None so the
    caller keeps the org-year synthesis (the existing default). No field suppresses another and the
    retired flat credit keys are NOT read here (nor anywhere else in the engine) - the citation reads
    creators, never the retired fields (C3)."""
    creators = _creators_of(y)
    if creators:
        return "; ".join(c["name"] for c in creators)
    cite = y.get("cite")
    if isinstance(cite, dict):
        au = str(cite.get("au") or "").strip()
        if au:
            return au
    return None


def _funders_of(y: dict) -> list:
    """[{name, pid, grant_id?}] from funding/funders; tolerates odd shapes (non-dicts dropped), never
    crashes. grant_id rides through ONLY when the survey funding row declares a real one (the corpus
    carries grant_id: null, so it stays omitted - the mth5 producer emits no placeholder grant id)."""
    out = []
    for f in (y.get("funding") or y.get("funders") or []):
        if not isinstance(f, dict):
            continue
        row = {"name": f.get("organisation") or f.get("name"),
               "pid": f.get("organisation_ror") or f.get("pid")}
        gid = f.get("grant_id") or f.get("id")
        if gid not in (None, ""):
            row["grant_id"] = gid
        out.append(row)
    return out


# CONTRIBUTOR-CREDIT-SPEC §4: AusMT is added as the DataCite HostingInstitution on EXPORT ONLY (the
# mtcat federation document) - it is never a curator field and is never written into survey.yaml.
_AUSMT_HOSTING_CONTRIBUTOR = {"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"}


def _export_contributors_of(smeta: dict) -> list:
    """The DataCite-export contributor list for one survey (mtcat, §4): the survey's own contributors[]
    verbatim, with AusMT appended as the HostingInstitution. AusMT is added AUTOMATICALLY for every
    exported record (AusMT hosts them all) and appears ONLY here, never in survey.yaml and never in the
    surveys.json seam (which stays the verbatim curator surface)."""
    rows = [dict(c) for c in (smeta.get("contributors") or []) if isinstance(c, dict)]
    rows.append(dict(_AUSMT_HOSTING_CONTRIBUTOR))
    return rows


_ORCID_URL_RE = _re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$", _re.IGNORECASE)


def _orcid_url(orcid):
    """A full https://orcid.org/<id> URL from a bare id or an already-URL ORCID, or None when the value
    is absent or not ORCID-shaped. Never fabricates: an unparseable value yields no URL. The checksum is
    not re-verified here (the surveys validator already warns on a bad ORCID); this only canonicalises
    the shape the mth5 project_lead.url field wants."""
    m = _ORCID_URL_RE.match(str(orcid or "").strip())
    return "https://orcid.org/" + m.group(1).upper() if m else None


def _instrument_model_of(y: dict):
    """'manufacturer model; ...' joined across the instruments list, or None."""
    instruments = [i for i in (y.get("instruments") or []) if isinstance(i, dict)]
    return "; ".join(
        " ".join(x for x in [i.get("manufacturer"), i.get("model")] if x) for i in instruments) or None


def _instruments_of(y: dict):
    """PID-schema: the structured instruments list [{manufacturer, model, pid}, ...] — used ONLY to
    carry a per-instrument-system persistent identifier (the AuScope Instrument Registry URL/handle)
    through to the portal drawer, where it renders as a link. Returns None (key omitted from SMETA)
    UNLESS at least one instrument actually declares a `pid`: the display string `instrument_model`
    already carries manufacturer/model for every survey, so emitting this richer list only when a PID
    is present keeps surveys.json byte-identical for the whole existing corpus (an ADDITIVE change must
    change nothing when the new field is absent). `pid` is a curator-asserted metadata string, verbatim;
    the portal applies the same escUrl/URL-shape guard used for the other PID links before linking it."""
    instruments = [i for i in (y.get("instruments") or []) if isinstance(i, dict)]
    if not any((i.get("pid") not in (None, "")) for i in instruments):
        return None
    out = []
    for i in instruments:
        pid = i.get("pid")
        out.append({"manufacturer": i.get("manufacturer"), "model": i.get("model"),
                    "pid": (str(pid).strip() or None) if pid not in (None, "") else None})
    return out


def _collection_of(y: dict):
    """The collection facet {id, title, type, status, start_year, last_updated, description}, or None."""
    coll = y.get("collection")
    if not (isinstance(coll, dict) and (coll.get("id") or coll.get("title"))):
        return None
    lu = coll.get("last_updated")
    return {"id": coll.get("id"), "title": coll.get("title"), "type": coll.get("type"),
            "status": coll.get("status"), "start_year": coll.get("start_year"),
            "last_updated": str(lu) if lu is not None else None,
            "description": coll.get("description")}


def _date_range_of(y: dict):
    """'YYYY–YYYY' from a {start, end} dates map. str()-coerces each year so an unquoted YAML int
    (e.g. start: 2009) or a present-but-null year no longer raises TypeError; a non-dict dates value
    passes through unchanged (so an existing string date is byte-identical)."""
    d = y.get("dates")
    if not isinstance(d, dict):
        return d
    s, e = str(d.get("start") or "")[:4], str(d.get("end") or "")[:4]
    return f"{s}–{e}".strip("–")


def _year_range_of(y: dict):
    """S3: (year_start, year_end) as ints|None, parsed from the SAME dates map as _date_range_of —
    reuses its str()-coercion (an unquoted YAML int or a present-but-null year must not raise/crash)
    instead of re-parsing the display string portal-side, so the modeller year filter and the
    'YYYY-YYYY' display can never drift apart. A non-dict/absent dates value -> (None, None): the
    filter/feed callers treat unknown years as "pass when unset, fail when a range is given" (a
    modeller filtering by year wants DATED data, not a false match on undated stations)."""
    d = y.get("dates")
    if not isinstance(d, dict):
        return None, None
    def _yr(v):
        s = str(v or "")[:4]
        return int(s) if s.isdigit() else None
    return _yr(d.get("start")), _yr(d.get("end"))


def _citation_year_of(y: dict) -> str:
    """C7: the citation year — the 4-digit year of the dates.end, else dates.start, else '' (genuinely
    no date declared, in which case the citation honestly renders '(n.d.)'). Independent of
    _date_range_of's display string so a malformed/partial dates map still yields a usable year."""
    d = y.get("dates")
    if not isinstance(d, dict):
        return ""
    return str(d.get("end") or d.get("start") or "")[:4]


def _raid_of(y: dict):
    """identifiers.project_raid verbatim (a RAiD URL/handle, e.g. https://raid.org/10.12345/AB1234),
    or None. C7: previously parsed by nothing — SMETA had no 'raid' key at all."""
    ids = y.get("identifiers", {}) or {}
    v = ids.get("project_raid") if isinstance(ids, dict) else None
    return (str(v).strip() or None) if v not in (None, "") else None


def _ts_pid_of(y: dict):
    """time_series.collection_pid verbatim (a survey-specific raw-TS collection DOI/handle), or None
    when the survey does not declare one (the caller falls back to the deployment-wide TS_COLLECTION
    default ONLY for the AusLAMP/NCI collection case — see drawer.js/exports.js). C7: previously read
    by nothing; the engine only checked levels_available for the ts:'ok'/'unk' badge."""
    ts = y.get("time_series", {}) or {}
    v = ts.get("collection_pid") if isinstance(ts, dict) else None
    return (str(v).strip() or None) if v not in (None, "") else None


def _publications_of(y: dict) -> list:
    """Publications: the structured {author,year,title,journal,doi} dict, or a bare string the
    _template invites — kept as a DOI when it looks like one (starts '10.'), else as a title."""
    out = []
    for p in (y.get("publications") or []):
        if isinstance(p, dict):
            out.append({"a": p.get("author"), "y": p.get("year"), "t": p.get("title"),
                        "j": p.get("journal"), "doi": p.get("doi")})
        else:
            is_doi = str(p).startswith("10.")
            out.append({"a": None, "y": None, "t": None if is_doi else str(p),
                        "j": None, "doi": str(p) if is_doi else None})
    return out


def _related_identifiers_of(y: dict) -> list:
    """§2a (identifiers design — the related-identifiers model): the top-level related_identifiers list,
    passed through carrying the typed-core keys the drawer renders — identifier, identifier_type,
    relation, custodian — plus D-L1's `identifies` (WHAT the identifier points at, in NCI Table 1 data-level
    terms). The stored entry may hold the wider SOURCE_KEYS allow-list (it TYPES the C46 sources[] object);
    the portal only needs the level-labelled, typed link, so the acquisition keys are dropped here rather
    than shipped to surveys.json. `identifies` is emitted VERBATIM when present and OMITTED per-entry when
    absent, so a legacy row yields the byte-identical four-key dict (back-compat). Non-mapping entries are
    skipped (never crash) — mirroring _funders_of's tolerance. Always a list (possibly empty): an absent
    list yields [], which the drawer treats as 'render nothing' (identifiersHtml checks emptiness)."""
    out = []
    for r in (y.get("related_identifiers") or []):
        if not isinstance(r, dict):
            continue
        entry = {"identifier": r.get("identifier"), "identifier_type": r.get("identifier_type"),
                 "relation": r.get("relation"), "custodian": r.get("custodian")}
        if r.get("identifies") not in (None, ""):
            entry["identifies"] = r.get("identifies")   # D-L1: level label the drawer/files-tab key off
        out.append(entry)
    return out


def _instrument_pid_of(y: dict):
    """§2b (identifiers design): identifiers.instrument_pid — the ONE survey/platform-level instrument
    PID (the PIDINST platform DOI), verbatim or None. Distinct from the per-instrument `pid`s carried by
    _instruments_of; this is the survey-wide platform identifier the editor added in wave 1."""
    ids = y.get("identifiers", {}) or {}
    v = ids.get("instrument_pid") if isinstance(ids, dict) else None
    return (str(v).strip() or None) if v not in (None, "") else None


# IDCONS D4 (SPEC §5.3): map a pid_status.json cache status to the served `resolution` facet. The cache
# (written by scripts/refresh_pid_status.py, NEVER by the build) holds {identifier: {status, checked}} with
# status resolved|unregistered|error. A DOI the cache says is `resolved` -> "ok"; `unregistered` (doi.org's
# own 404 — reserved-but-not-yet-active) -> "reserved"; `error` OR no cache entry -> "unknown" (the portal
# links it as today). We only ATTACH a facet for the ok/reserved cases: a survey whose identifiers have no
# cache entry (the whole existing corpus when no cache is present) gets a byte-identical surveys.json entry.
_RESOLUTION_BY_STATUS = {"resolved": "ok", "unregistered": "reserved"}


def _resolution_of(identifier, status_map: dict | None):
    """The resolution facet for one identifier, or None to attach nothing (unknown = link as today).
    None/blank identifier or an absent/`error` cache entry -> None."""
    if not status_map or identifier in (None, ""):
        return None
    entry = status_map.get(str(identifier).strip())
    if not isinstance(entry, dict):
        return None
    return _RESOLUTION_BY_STATUS.get(entry.get("status"))


def apply_pid_resolution(sm: dict, status_map: dict | None) -> dict:
    """IDCONS D4 (SPEC §5.3): annotate a SMETA entry with resolution facets from the pid_status.json cache,
    IN PLACE, and return it. Attaches `doi_resolution` / `ts_pid_resolution` (for the flat dataset DOI and
    collection PID still read during migration) and a per-entry `resolution` on each related_identifiers
    row — but ONLY when the cache actually knows the identifier (ok/reserved). No cache, or no entry, adds
    nothing, so an un-cached corpus serves byte-identical bytes (the fully-backward-compatible contract).
    Tolerant of a missing/None sm (the raw seed path may carry None)."""
    if not isinstance(sm, dict) or not status_map:
        return sm
    doi_res = _resolution_of(sm.get("doi"), status_map)
    if doi_res is not None:
        sm["doi_resolution"] = doi_res
    ts_res = _resolution_of(sm.get("ts_pid"), status_map)
    if ts_res is not None:
        sm["ts_pid_resolution"] = ts_res
    for entry in (sm.get("related_identifiers") or []):
        if isinstance(entry, dict):
            res = _resolution_of(entry.get("identifier"), status_map)
            if res is not None:
                entry["resolution"] = res
    return sm


def load_pid_status(path) -> dict:
    """Read a pid_status.json cache if it exists, returning {identifier: {status, checked}} (or {} when
    absent/unreadable). The build NEVER writes or refreshes this — it only CONSUMES it (SPEC §5.2); a
    missing or malformed file is silently treated as 'no cache' so the build stays offline and robust."""
    if not path:
        return {}
    try:
        p = Path(path)
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def survey_meta_from_yaml(y: dict) -> dict:
    """Map a survey.yaml into the portal's surveys.json entry shape (SMETA), composing the per-facet
    mappers above. Tolerant of both the Prototype-20 structured schema and the older flat schema."""
    ids = y.get("identifiers", {}) or {}
    acc_raw = y.get("access", {})
    # C1: carry BOTH the normalised access level and embargo_until into SMETA. The level gates byte
    # distribution (see access_serve_state); the portal reads both (surveys.json) to badge withholding
    # honestly. embargo_until is only meaningful under level=embargoed but is preserved verbatim regardless.
    acc = normalise_access_level(acc_raw.get("level") if isinstance(acc_raw, dict) else acc_raw)
    embargo_until = acc_raw.get("embargo_until") if isinstance(acc_raw, dict) else None
    embargo_until = str(embargo_until).strip() if embargo_until not in (None, "") else None
    org_name, org_ror = _org_of(y)
    name = y.get("project_name") or y.get("name", "")
    proc = y.get("processing") if isinstance(y.get("processing"), dict) else {}
    release_notes = y.get("release_notes") if isinstance(y.get("release_notes"), list) else None
    coord_resolution = y.get("coordinate_resolution") if isinstance(y.get("coordinate_resolution"), dict) else None
    year_start, year_end = _year_range_of(y)
    sm = {
        "country": y.get("country", "Australia"),
        "region": y.get("region"),   # optional finer geographic facet (e.g. "South Australia"); survey-driven
        "nci_base": y.get("nci_base"),   # optional NCI THREDDS fileServer dir; set => this survey's downloads are tier=nci
        "org": org_name,
        "org_ror": org_ror,
        "version": y.get("version"),
        "collection": _collection_of(y),
        "software": proc.get("software"),
        "release_notes": release_notes,
        "coord_resolution": coord_resolution,
        "lic": y.get("license", "TBD by uploader"),
        "doi": ids.get("dataset_doi"),
        "pid": ids.get("survey_pid"),
        "raid": _raid_of(y),                  # C7: identifiers.project_raid -> a RAiD link in identifiersHtml
        "related_identifiers": _related_identifiers_of(y),  # §2a: typed provenance relations (always a list; [] => drawer renders nothing)
        "instrument_pid": _instrument_pid_of(y),  # §2b: survey/platform-level instrument PID (PIDINST DOI) or None
        "instrument_model": _instrument_model_of(y),
        "dates": _date_range_of(y),
        "year_start": year_start, "year_end": year_end,   # S3: modeller year-range filter (ints|null)
        "funders": _funders_of(y),
        "pubs": _publications_of(y),
        "blurb": y.get("abstract"),
        "ts": "ok" if (y.get("time_series", {}) or {}).get("levels_available") else "unk",
        "ts_pid": _ts_pid_of(y),              # C7: survey-specific raw-TS collection PID (None => deployment default)
        "edi": "ok",
        "mth5": "unk",
        "access": acc,                       # SMETA key; normalised ACCESS_LEVELS: open|metadata_only|embargoed
        "embargo_until": embargo_until,       # C1: ISO date or None; the portal badges withholding from these
        # C7: yr/ve were always '' (every citation rendered "(n.d.)" regardless of a declared date/version);
        # yr = year of dates.end, else dates.start, else '' (genuinely no date -> honest "(n.d.)"); ve = the
        # declared survey version, else '' (no version -> the apa()/bibtex()/ris() helpers already omit it).
        # au: CONTRIBUTOR-CREDIT-SPEC §2.1 - the creators[] names in order when present, else a hand-authored
        # verbatim cite.au, else the org-year synthesis (org_name, the unchanged default for the whole
        # existing corpus). The retired lead/PI keys never drive the citation line (C3, no suppression).
        "cite": {"au": _citation_authors_of(y) or org_name, "yr": _citation_year_of(y),
                 "ti": name, "ve": (y.get("version") or ""), "pb": org_name},
    }
    # PID-schema (ADDITIVE, optional): only attach the structured instruments list when a survey actually
    # declares a per-instrument `pid`. Appended LAST so every other key's order/value is untouched — a
    # survey without any instrument PID gets a byte-identical surveys.json entry (the whole existing corpus
    # is unchanged). `instrument_model` (above) still carries the display string for every survey.
    instruments = _instruments_of(y)
    if instruments is not None:
        sm["instruments"] = instruments
    # C46-W3a: thread the schema-0.3 attribution/sources blocks (design §2.1) into SMETA when present,
    # ABSENT -> ABSENT (no empty placeholders), so a survey WITHOUT them yields a byte-identical entry.
    # This LIGHTS UP the W2 build-side instrument threading (which reads SMETA.attribution/.sources) and
    # feeds the render/export surfaces (mtcat/manifest/LICENSE.txt). `changes` is a normalised {made,
    # summary} descriptor of the survey's DECLARED changes (from attribution.changes_made/summary) — a
    # metadata fact carried in the discovery document, independent of which derived products THIS build
    # happened to emit (that build-time gating lives in instrument_params_from_survey at the zip seam).
    attribution = y.get("attribution")
    sources = y.get("sources")
    if isinstance(attribution, dict) and attribution:
        sm["attribution"] = attribution
    if isinstance(sources, list) and sources:
        sm["sources"] = sources
    if isinstance(attribution, dict) and attribution.get("changes_made") is not None:
        sm["changes"] = {"made": bool(attribution.get("changes_made")),
                         "summary": str(attribution.get("changes_summary") or "").strip()}
    # NCI data-level standard: the ORDERED list of time-series levels this survey declares
    # (time_series.levels_available; vocab raw_packed/level0/level1 per gateway/editor_form.py). The `ts`
    # flag above only says ok/unk; the portal Files tab renders per-level availability off THIS list.
    # ADDITIVE + absent -> absent: a survey without a levels list yields a byte-identical surveys.json entry.
    levels = (y.get("time_series", {}) or {}).get("levels_available")
    if isinstance(levels, list) and levels:
        sm["ts_levels"] = [str(x) for x in levels]
    # CONTRIBUTOR-CREDIT-SPEC C1/C2: the typed credit lists, served VERBATIM per the pinned drawer/engine
    # seam (order preserved, keys omitted when absent). ADDITIVE + absent -> absent: a survey without them
    # yields a byte-identical surveys.json entry (the whole pre-migration corpus). creators[] is the
    # citation-author order; contributors[] carries the fail-closed roles the drawer renders.
    creators = _creators_of(y)
    if creators:
        sm["creators"] = creators
    contributors = _contributors_of(y)
    if contributors:
        sm["contributors"] = contributors
    # MTCAT 2.0 curation fields, each ADDITIVE and absent-to-absent (default stability: a survey
    # that declares none of them yields a byte-identical SMETA entry, i.e. the whole pre-2.0 corpus).
    #   * discovery_description: the explicit <= 1200-char discovery text (the abstract stays
    #     UNCAPPED in `blurb`; the emitter prefers this key and never truncates either).
    #   * subjects[]: the controlled thematic classification rows, passed through VERBATIM.
    #   * coord_policy_declared/_default: whether the survey DECLARES an access.coordinates policy
    #     (including override-only declarations) and its survey default - the mtcat emitter projects
    #     coordinates_state from these plus the per-station post-mask stamps. Parse errors are left
    #     to the discovery phase's fail-closed parse (discover_work raises CoordinatePolicyError);
    #     here an unparseable block simply declares nothing.
    dd = y.get("discovery_description")
    if isinstance(dd, str) and dd.strip():
        sm["discovery_description"] = dd
    subjects = y.get("subjects")
    if isinstance(subjects, list) and subjects:
        sm["subjects"] = subjects
    if isinstance(acc_raw, dict) and (acc_raw.get("coordinates") not in (None, "")
                                      or acc_raw.get("coordinate_overrides") not in (None, "", {})):
        try:
            _cp_default, _ = coordacc.parse_coordinate_policy(acc_raw)
        except coordacc.CoordinatePolicyError:
            pass   # invalid policy: discover_work fails the survey loudly; SMETA asserts nothing
        else:
            sm["coord_policy_declared"] = True
            sm["coord_policy_default"] = _cp_default
    return sm


# A TOP-LEVEL `station_ids:` key in survey.yaml source text. Used only to decide whether the
# no-PyYAML fallback is allowed to read this document at all (see _read_yaml); a text scan is
# deliberate, because the parser being gated is the one that cannot be trusted to see the key.
_STATION_IDS_KEY = _re.compile(r"(?m)^station_ids[ \t]*:")


def _read_yaml(path: Path, raw: bytes | None = None):
    """Parse a survey.yaml. `raw`, when given, is the file's ALREADY-READ bytes and is parsed instead
    of re-reading the path — so a caller that also derives a content digest from those same bytes gets
    parse+digest coherence from ONE read (C18 Amendment A4: the 2026-07-07 incident was a build whose
    metadata and cache-key digest came from two reads of the same file, minutes apart, straddling an
    edit). YAML mandates a UTF family, so the bytes decode as UTF-8 (replace-on-error: a bad byte
    degrades one field's text, never the parse+digest pairing)."""
    text = raw.decode("utf-8", errors="replace") if raw is not None else None
    try:
        import yaml  # noqa: PLC0415
    except ModuleNotFoundError:
        # tolerant stdlib fallback (top-level scalars + simple nested maps)
        src = text if text is not None else path.read_text()
        # ...tolerant EXCEPT for `station_ids`, which it does not get to read at all. The fallback is
        # reduced-fidelity in two ways that both END in a PARTIAL map, and a partial map is a LEGAL
        # shape, so nothing fails: the unread stations publish under the raw contractor DATAID with
        # no warning anywhere, which is the exact mis-identification the block exists to prevent.
        #   (1) it matches a mapping key as bare-word or QUOTED, while YAML's plain scalar keys are
        #       wider, so `49R stage 1.edi:` and `53(RR).edi:` are read by PyYAML and dropped here;
        #   (2) PRE-EXISTING, unrelated to this block: a top-level block SEQUENCE whose key line
        #       carries a TRAILING COMMENT takes the comment as its value, orphans the list items,
        #       and drops every later top-level key. That is the shipped template's own shape
        #       (`data_types:  # select all that apply`), so on the ausmt-surveys example package
        #       this fallback returns 11 of 21 top-level keys -- station_ids among the 10 missing.
        # (2) is why this gate reads the SOURCE TEXT rather than the parsed document: asking the
        # parser whether the block is present is asking the very thing that cannot see it.
        if _STATION_IDS_KEY.search(src):
            print(f"SKIP {path.parent.name}: {path.name} declares station_ids, which requires PyYAML "
                  f"(the stdlib fallback parser cannot read this block faithfully and would build "
                  f"the survey from a PARTIAL map, publishing raw contractor DATAIDs silently). "
                  f"Install PyYAML (pip install PyYAML) -- survey dropped from the build",
                  file=sys.stderr)
            return None
        return _mini_yaml(src)
    try:
        return yaml.safe_load(text if text is not None else path.read_text()) or {}
    except yaml.YAMLError as e:
        # one malformed contributor survey.yaml must NOT crash the whole build with a raw traceback and deny
        # publication to every other survey -- warn loudly and drop just this package (the caller skips a non-dict).
        print(f"SKIP {path.parent.name}: {path.name} is not valid YAML ({e}) -- survey dropped from the build",
              file=sys.stderr)
        return None


def _mini_yaml(text: str) -> dict:
    """Small YAML-subset parser used only when PyYAML is unavailable, sufficient for AusMT
    `survey.yaml`. Handles nested maps, block sequences (of scalars and of maps), inline ``[]`` /
    ``{}`` and simple flow collections, block scalars (``>`` / ``|`` collapsed to one line), quotes,
    booleans/numbers, and ``#`` comments. It is NOT a general YAML parser; the build also accepts
    PyYAML and the two agree on the AusMT schema (guarded by ``tests/test_mini_yaml_parity.py``).
    Keep it in step with the survey.yaml schema."""
    import re

    def _strip_comment(v: str) -> str:
        v = v.strip()
        if not v:
            return v
        if v[0] == "#":
            # The whole value is a comment ('data_types:  # pick one'). YAML forbids an unquoted
            # scalar starting with '#' after a space, so this is always a comment, never data.
            # Before 2026-08-25 this case leaked through (the mid-string scan below needs ' #'),
            # so a commented key line swallowed its nested block and truncated the document.
            return ""
        if v[0] in "\"'":
            # A quoted scalar may carry a trailing comment AFTER its closing quote
            # ('name: "Stephan Thiel"  # note'). Walk to the closing quote (honouring
            # backslash escapes inside double quotes) and drop a trailing comment; a hash
            # INSIDE the quotes is data and survives. Found live 2026-07-25: the credit
            # migration's inline review note read as part of the value on the no-PyYAML path.
            q, i = v[0], 1
            while i < len(v):
                if q == '"' and v[i] == "\\":
                    i += 2
                    continue
                if v[i] == q:
                    break
                i += 1
            rest = v[i + 1:].lstrip()
            if rest == "" or rest.startswith("#"):
                return v[:i + 1]
            return v
        i = v.find(" #")
        return (v[:i] if i >= 0 else v).strip()

    def _flow_split(s: str):
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch in "[{":
                depth += 1; cur += ch
            elif ch in "]}":
                depth -= 1; cur += ch
            elif ch == "," and depth == 0:
                out.append(cur); cur = ""
            else:
                cur += ch
        if cur.strip():
            out.append(cur)
        return [x.strip() for x in out]

    def _scalar(v):
        v = _strip_comment(v)
        if v == "":
            return None
        if (v[0] == '"' and v[-1:] == '"') or (v[0] == "'" and v[-1:] == "'"):
            return v[1:-1]
        if v == "[]":
            return []
        if v == "{}":
            return {}
        if v[0] == "[" and v[-1:] == "]":
            inner = v[1:-1].strip()
            return [_scalar(x) for x in _flow_split(inner)] if inner else []
        if v[0] == "{" and v[-1:] == "}":
            d = {}
            for part in _flow_split(v[1:-1]):
                if ":" in part:
                    kk, _, vv = part.partition(":")
                    d[kk.strip()] = _scalar(vv)
            return d
        low = v.lower()
        if low in ("true", "false"):
            return low == "true"
        if low in ("null", "~"):
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    toks = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        toks.append((len(ln) - len(ln.lstrip(" ")), ln.strip()))
    n = len(toks)
    pos = [0]
    # A mapping key: bare, or QUOTED. The quoted form is not a nicety: the `station_ids.map` keys are
    # source FILENAMES, and real ones carry spaces and parentheses ("49R stage 1.edi", "53(RR).edi"),
    # which YAML can express only quoted. Before this alternation the fallback matched neither and
    # silently dropped the whole map, so a no-PyYAML build published the raw contractor DATAIDs.
    # The closing quote must be followed IMMEDIATELY by ':', so a quoted list-item SCALAR that happens
    # to contain a colon (- "a: b") is still a scalar, not a one-key map (pinned by test).
    key_re = re.compile(r"""^("[^"]+"|'[^']+'|[\w.\-]+):\s*(.*)$""")

    def _key(k: str) -> str:
        """Unquote a matched mapping key; a bare key passes through unchanged."""
        return k[1:-1] if (len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'") else k

    def _block_scalar(min_indent, style=">"):
        buf = []
        while pos[0] < n and toks[pos[0]][0] >= min_indent:
            buf.append(toks[pos[0]][1]); pos[0] += 1
        joiner = "\n" if style[0] == "|" else " "       # | literal keeps newlines; > folds to spaces
        text_out = joiner.join(buf)
        if not style.endswith("-") and text_out:        # clip (default) keeps one trailing newline
            text_out += "\n"
        return text_out

    def parse(min_indent):
        node = None
        while pos[0] < n:
            indent, content = toks[pos[0]]
            if indent < min_indent:
                break
            if content.startswith("- "):
                if node is None:
                    node = []
                if not isinstance(node, list):
                    break
                item = content[2:].strip()
                m = key_re.match(item)
                if m:
                    sub = {}
                    # _strip_comment BEFORE the structural tests: a trailing comment must not stop
                    # 'val' reading as empty (nested block follows) or as a block-scalar header.
                    k, val = _key(m.group(1)), _strip_comment(m.group(2))
                    if val in (">", "|", ">-", "|-"):
                        pos[0] += 1; sub[k] = _block_scalar(indent + 2, val)
                    elif val == "":
                        pos[0] += 1
                        sub[k] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 1) else None
                    else:
                        sub[k] = _scalar(val); pos[0] += 1
                    while pos[0] < n:                       # sibling keys of the same list item
                        i2, c2 = toks[pos[0]]
                        if i2 == indent + 2 and not c2.startswith("- "):
                            m2 = key_re.match(c2)
                            if m2:
                                k2, v2 = _key(m2.group(1)), _strip_comment(m2.group(2))
                                if v2 in (">", "|", ">-", "|-"):
                                    pos[0] += 1; sub[k2] = _block_scalar(indent + 4, v2)
                                elif v2 == "":
                                    pos[0] += 1
                                    sub[k2] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 2) else None
                                else:
                                    sub[k2] = _scalar(v2); pos[0] += 1
                                continue
                        break
                    node.append(sub)
                else:
                    node.append(_scalar(item)); pos[0] += 1
                continue
            m = key_re.match(content)
            if not m:
                pos[0] += 1; continue
            if node is None:
                node = {}
            if not isinstance(node, dict):
                break
            k, val = _key(m.group(1)), _strip_comment(m.group(2))
            if val in (">", "|", ">-", "|-"):
                pos[0] += 1; node[k] = _block_scalar(indent + 1, val)
            elif val == "":
                pos[0] += 1
                node[k] = parse(indent + 1) if (pos[0] < n and toks[pos[0]][0] > indent) else None
            else:
                node[k] = _scalar(val); pos[0] += 1
        return node if node is not None else {}

    result = parse(0)
    return result if isinstance(result, dict) else {}


def _parse_one_edi(p):
    """The expensive per-EDI compute: the mt_metadata parse + C25 convention gates + coord-QC +
    shared TF/science math. Returns a plain JSON-serializable dict {record, tf, sci, email_flag,
    coord_warn, frame, frame_notes} — or {"skip": {station, gate, reason}} when a convention gate
    FAILS the station (fail-closed; the caller logs it loudly and records the structured drop).
    This is the C18-cacheable unit. Kept side-effect-free (no stderr, no survey/org finalisation)
    so a cache HIT reproduces the identical value a MISS computes; the caller applies the
    survey-scoped finalisation and emits the warnings. `record`/`tf`/`sci` round-trip through JSON
    byte-identically into the positional products (numpy float64 serialises as a float; verified
    by test).

    C25 frame POLICY v3 (owner ruling 2026-07-11): Gate 1 NEVER rotates served data — it PASSES the
    station (served AS STORED, the declared frame recorded in `frame`) or FAILS it (per-period frame
    mixing V3-C, or an unknowable frame). Because a station's disposition no longer depends on its
    siblings' angles (every uniform declaration serves as-stored regardless of the survey), this
    parse is survey-context-INDEPENDENT again — no policy mode is threaded and the C18 cache key
    carries no policy context. The V3-B survey-level "mixed declared frames" note is applied by the
    caller (process_edis), not here. Gate 2's quadrant check sees the SERVED (as-stored) frame. The
    source file bytes are never touched (D1)."""
    # parse ONCE, reuse below. `_parse_fallback` is the reason string when mt_metadata could only
    # read this file from a NORMALISED TEMPORARY COPY (its >INFO JSON trailing-delimiter defect; see
    # _mtm). Parse-only: that copy is destroyed inside the read, so `p` -- the custodian's file --
    # remains the ONLY path this build ever copies to the served tree or hands to sha256().
    tfobj, _parse_fallback = mtm.read_with_fallback(p)
    _raw = ep.read_norm(p)   # raw EDI text: frame evidence + coord-QC + processing-metadata scrape
    _did = cat.grab(_raw, "DATAID")

    # ---- C25 Gate 1: rotation/frame guard (full design in extract/_conventions.py). Evidence =
    # the raw text (ZROT/TROT/ROTSPEC/HMEAS — load-bearing for spectra files, which mt_metadata
    # reads with NO rotation metadata at all) cross-checked against the TF's own _rotation_angle.
    # v3: PASS -> served AS STORED (declared frame recorded); FAIL -> the station is skipped (never
    # serve a per-period-mixed or unresolvable frame; C8 posture). The engine does NOT de-rotate —
    # the de-rotation math in _conventions is diagnostic-only and no serve-path caller invokes it.
    _ev = conv.parse_frame_evidence(_raw)
    _n_per = int(tfobj.period.size) if tfobj.period is not None else 0
    _disp = conv.frame_disposition(_ev, getattr(tfobj, "_rotation_angle", None),
                                   conv.z_present_mask(tfobj), bool(tfobj.has_tipper()), _n_per)
    if _disp.action == "fail":
        try:
            _sid, _ = cat.parse_dataid(_did)
        except Exception:  # noqa: BLE001
            _sid = None
        return {"skip": {"station": _sid or p.stem, "gate": "rotation-frame",
                         "reason": _disp.fail_reason}}
    _frame_notes = list(_disp.notes)

    r = mtm.record_from_tf(tfobj, p.name)
    # mt_metadata reads only the HEAD coordinate, so run the INFO-vs-HEAD DMS-bug detection +
    # the processing-metadata scrape on the raw EDI text (kept helpers; not a TF re-parse).
    # Curator signal only (C3): the SOURCE EDI (as submitted/served) still carries whatever the
    # custodian wrote; we never mutate it (D1). proc_note() redacts its own returned note; this is
    # purely a flag for the caller's loud per-survey WARNING.
    _im = cat._INFO_BLOCK.search(_raw)
    email_flag = bool(_im and cat._EMAIL.search(_im.group(1)))
    coord_warn = None
    try:
        # The DATAID (HEAD) is authoritative for the station id. parse_dataid also unpacks the
        # Phoenix remote-reference compound id 'P=<station> R=<remote> (H)' -> the real station.
        _station, _ = cat.parse_dataid(_did)
        # R4 site_name: r["id"] here still holds the ORIGINAL tf station/site name (record_from_tf ->
        # tf.station). The next line overwrites it with the parsed DATAID that becomes the DISPLAYED id.
        # Capture the pre-overwrite name (the same value the source_id_preserved_in_site_name notice tracks)
        # and carry it as site_name ONLY when the overwrite actually changes it (a sanitised id such as
        # SA28_2B -> SA282B); identical -> absent, so the catalogue keeps its zero-change convention.
        _orig_site_name = r.get("id")
        if _station:
            r["id"] = _station
        if _orig_site_name and _orig_site_name != r["id"]:
            r["site_name"] = _orig_site_name
        _ila, _ilo = cat.info_coords(_raw)
        r["coord_flag"], r["coord_candidates"], r["coord_conflict_deg"] = \
            cat.detect_coord_issue(r.get("lat"), r.get("lon"), _ila, _ilo,
                                   r.get("lat"), r.get("lon"))
        r["info_lat"], r["info_lon"] = _ila, _ilo
    except Exception as _e:  # noqa: BLE001
        # Coord QC must NEVER silently no-op: a failure here would reopen the DMS sign-bug
        # (~140 km mislocation). Surface the warning to the caller (not stderr here,
        # so a cache hit and a miss emit the SAME diagnostics); do not crash for one station.
        coord_warn = f"{type(_e).__name__}: {_e}"
    r["state"] = cat.state_of(r["lat"], r["lon"])
    # Processing note + remote-reference SITE (best-effort; rich for Phoenix INFO blocks).
    r["processing_note"], r["remote_site"] = cat.proc_note(_raw, _did)
    # Processing metadata (sw/alg/remote-ref): mt_metadata leaves these EMPTY for many EDI dialects,
    # so supplement with the kept text scrape so this best-effort facet survives.
    _pm, _pt = mtm.proc_info_from_tf(tfobj, with_writer=True), sci.proc_info(_raw)
    # LINEAGE: the program that WROTE the file and the program that PROCESSED the TF are two facts,
    # and `sw` is the second one. It used to fall back to the HEAD's PROGVERS, which published the
    # WRITER as the processor across most of the corpus ("Geotools 4.0.5.12583", "WINGLINK EDI
    # 1.0.22", "MTpy") while the real processor sat unread in the >INFO free text. PROGVERS is now
    # carried as file_written_by instead, and the processor is MINED from the note, with the
    # writer's identity passed in so a hit that merely echoes it is not mistaken for evidence.
    # The miner also returns the source LINE it matched; it is not carried into the product because
    # the line is already published verbatim inside processing.note (the whole >INFO block), so the
    # mined claim is auditable against the served document without a second key stating it twice.
    _writer = _pm[3] if _pm[3].get("name") else cat.writer_from_text(_raw)
    _mined = cat.mine_processor(r.get("processing_note") or "", _writer.get("name"))[0]
    # Fallback order, strongest evidence first: the mined >INFO phrase; the explicit
    # "Processing code:" declaration; and finally a stated writer that is NOT a known exporter (an
    # EDI written directly by its processor, e.g. LEMIMT or Phoenix EMpower). A known writer never
    # becomes the processor, and nothing is invented — no evidence leaves sw None.
    _sw_writer = _writer.get("name") if not cat.is_known_writer(_writer.get("name")) else None
    proc = (_mined or _pt[0] or _pm[0] or _sw_writer,           # sw: THE PROCESSOR
            _pm[1] or _pt[1],                                  # alg: scrape
            _pm[2] or _pt[2] or (1 if r.get("remote_site") else 0))  # rr: ...or remote_site found
    r["file_written_by"] = _writer
    _tnotes = []
    per, comp = mtm.components_from_tf(tfobj, notes=_tnotes)
    if _tnotes:
        r["tipper_masked"] = True   # rides the cached parse product; the caller emits on hit AND miss
    tf = tfmod.tf_from_components(per, comp) if per else ep.EMPTY_TF
    srow = sci.science_from_components(per, comp, proc) if per \
        else sci.science_from_components(None, {}, None)

    # ---- C25 Gate 2: sign-convention quadrant check, on the SERVED (post-derotation) components.
    # BOTH off-diagonal medians coherently out of quadrant -> FAIL (a pure convention flip: the
    # station is skipped, never served under the wrong e^{±iωt} sense). ONE out -> honesty WARN
    # (3D/distortion does that legitimately). Too little data -> explicit insufficient note.
    _ck = conv.convention_check(comp)
    if _ck["verdict"] == "fail":
        return {"skip": {"station": r["id"], "gate": "sign-convention", "reason": _ck["detail"]}}
    if _ck["verdict"] in ("warn_xy", "warn_yx"):
        _frame_notes.append(f"convention: {_ck['detail']}")
    elif _ck["verdict"] == "insufficient":
        _frame_notes.append(f"convention: {_ck['detail']}")
    _frame = dict(_disp.facts)
    _frame["convention_check"] = _ck
    return {"record": r, "tf": tf, "sci": srow, "email_flag": email_flag, "coord_warn": coord_warn,
            "frame": _frame, "frame_notes": _frame_notes, "parse_fallback": _parse_fallback,
            # The presence rule (gate 15): what THIS parse carried as an mt_metadata default rather
            # than a source assertion. Derived here, where the parsed model is, so a warm rebuild
            # reports it identically to a cold one.
            "presence": presence.run_default_notes(tfobj),
            # The acquisition facts the >INFO block itself asserts, per dialect (extract/_runfacts).
            # mt_metadata reads none of them, so they are recovered from the raw text the reader
            # already has; runs[] is emitted from these and from nothing else.
            "run_facts": rfacts.run_facts(_im.group(1) if _im else "")}


def process_edis(edi_paths, survey_label, org, slug, extractor="mt_metadata",
                 cache=None, survey_digest="", report=None, station_ids=None):
    """Run the mt_metadata extractor + shared science over a list of EDIs; return aligned rows.

    mt_metadata is the SOLE engine (the dependency-free regex extractor + _spectra were retired in
    slice #3d). The TF object is read ONCE and reused for the record, components and processing info;
    the raw EDI text is read once more for the kept coord-QC + processing-metadata helpers. The
    `extractor` param is retained for call-site compatibility and is ignored (mt_metadata is the sole
    engine).

    C25: the per-EDI parse runs the convention gates (extract/_conventions.py). A gate FAIL skips
    the station LOUDLY (stderr + a structured drop record); a derotation/warn is carried as
    conditioning-style frame notes. `report`, when given, is a dict the caller owns that collects
    the survey-scoped gate output: {"stations_dropped": [{station, reason}],
    "frame_notes": {station_id: [note, ...]}} — the main loop feeds these into build_report.json
    (stations_dropped + warnings) and the survey-level NOTICE log. Optional so existing callers
    (tests) are unchanged.

    C18: when `cache` is an ENABLED BuildCache, the per-EDI parse result (_parse_one_edi's plain-dict
    output) is content-addressed by the source EDI sha + salt, so an unchanged EDI on a warm rebuild
    reads the parse from cache instead of re-invoking mt_metadata. The restored value feeds the SAME
    survey-scoped finalisation below, so the emitted rows are byte-identical to a fresh parse (a
    cached gate-skip replays identically too).

    `station_ids` is the survey's {source filename: published station id} override map (see
    extract/_stationids.py; empty/None for every survey that declares no `station_ids` block, which
    is the whole existing corpus). It is applied AFTER the DATAID parse and BEFORE _disambiguate, so
    the disambiguator sees already-unique ids and cannot invent a processing-variant tag for two
    genuinely different physical sites that the custodian numbered alike. NOT part of the C18 cache
    key namespace and deliberately applied OUTSIDE _parse_one_edi: the cached unit stays the pure
    per-file parse, and the map lives in survey.yaml, whose digest already keys every entry, so a map
    edit re-derives the survey either way."""
    stations, tf_rows, sci_rows = [], [], []
    _email_hits = []   # curator signal (C3): source filenames whose raw >INFO block carries an email
    if not mtm.available():
        sys.exit("ERROR: the mt_metadata stack is required for the build "
                 "(pip install -r environments/requirements-mtmetadata-lock.txt).")
    _use_cache = cache is not None and getattr(cache, "enabled", False)
    # ---- C25 POLICY v3 survey-scope pre-scan (cheap lexical pass; read_norm is cached so the text
    # is read once and reused by the per-station parse below). Under v3 a station's disposition is
    # survey-context-INDEPENDENT (every uniform declaration serves as-stored; every per-period
    # declaration refuses), so this scan NO LONGER changes any per-station parse and no policy
    # context enters the C18 cache key (kind="parse"). It exists ONLY to detect the V3-B
    # survey-inconsistency and surface the "mixed declared frames" note — applied per station below.
    _angles = []
    for p in sorted(edi_paths):
        try:
            _angles.append(conv.declared_uniform_angle(conv.parse_frame_evidence(ep.read_norm(p))))
        except Exception:  # noqa: BLE001  (unreadable file -> the per-station loop reports it)
            continue
    _survey_frame_note = conv.classify_survey_frame(_angles)   # V3-B note string, or None
    for p in sorted(edi_paths):
        _ck = cache.key(edi_sha=sha256(p), survey_digest=survey_digest, kind="parse") if _use_cache else None
        parsed = cache.get_json(_ck) if _ck else None
        if parsed is None:
            try:
                parsed = _parse_one_edi(p)
            except Exception as e:  # noqa: BLE001
                print(f"  PARSE FAIL {p.name}: {e}", file=sys.stderr)
                continue
            if _ck:
                cache.put_json(_ck, parsed)   # populate for the next warm build
        # C25 gate FAIL (fresh or cache-replayed): the station is skipped LOUDLY — stderr names the
        # gate, the angles and the fix; the structured drop rides into build_report.json via
        # `report` so the skip is machine-visible, never a silent absence.
        if parsed.get("skip"):
            _sk = parsed["skip"]
            print(f"  GATE FAIL {p.name} [{_sk['gate']}]: {_sk['reason']}", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": _sk.get("station") or p.stem,
                     "reason": f"[{_sk['gate']}] {_sk['reason']}"})
            continue
        r, tf, srow = parsed["record"], parsed["tf"], parsed["sci"]
        # Emit the deferred per-EDI diagnostics identically whether parsed from source or cache.
        if r.get("tipper_masked"):
            print(f"  NOTICE {r.get('id') or p.stem}: placeholder tipper (|T| flat at 1.0) masked "
                  f"- tipper withheld", file=sys.stderr)
            if report is not None:
                report.setdefault("tipper_masked", []).append(str(r.get("id") or p.stem))
        if parsed.get("email_flag"):
            _email_hits.append(p.name)
        if parsed.get("coord_warn"):
            print(f"  WARNING: coord-QC failed for {p.name}: {parsed['coord_warn']} "
                  f"(DMS sign-bug detection SKIPPED for this station)", file=sys.stderr)
        # Graceful degradation: a record with no coordinates or no periods is unusable (a malformed
        # header, or an EDI mt_metadata cannot turn into a transfer function). Skip it rather than
        # emit a junk station.
        if r.get("lat") is None or r.get("lon") is None or not r.get("n_periods"):
            print(f"  SKIP {p.name}: no coordinates/periods recovered by mt_metadata "
                  f"(malformed header or unreadable transfer function)", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": r.get("id") or p.stem,
                     "reason": "no coordinates/periods recovered by mt_metadata"})
            continue
        r["survey"] = survey_label
        r["org"] = org
        # STATION-ID OVERRIDE (owner ruling 2026-08-08): for a third-party release the contractor's
        # DATAID is not a usable public identifier, and the EDI must be served byte-identical, so the
        # published id is declared per SOURCE FILE in survey.yaml instead. Applied HERE - after the
        # DATAID parse, before safe_component and before _disambiguate below - so the disambiguator
        # sees already-unique ids (Roxby Downs 2018: 56 reused numbers whose furthest colliding pair
        # is 58.5 km apart, which a `.v1`/`.s1` variant tag would misreport as one re-processed site).
        # A file with no map entry is untouched and keeps DATAID behaviour (partial maps are legal).
        # apply_override retains the EDI's own DATAID as site_name via the SAME mechanism the DATAID
        # overwrite in _parse_one_edi uses, so the catalogue keeps one convention for a displayed id
        # that differs from the source's. The same call stamps any declared SOURCE PROVENANCE
        # (original filename, the custodian's opaque record id, the acquisition-stage label) onto
        # r["source_provenance"], to travel in AusMT's own records only.
        stnids.apply(r, p, station_ids)
        r["id"] = safe_component(r.get("id"))          # untrusted DATAID/override -> no traversal / XSS
        r["ausmt_id"] = f"au.{safe_component(slug)}.{r['id']}"
        r["comps"] = "".join(r.get("components") or [])
        r["frame"] = parsed.get("frame")               # C25 frame facts -> station.json
        # C25 V3-B: a survey with inconsistent per-station declared frames carries the survey-level
        # "mixed declared frames" note. Stamp it here (AFTER the context-free per-station parse, so
        # it never enters the C18 cache) into BOTH the station's frame facts (-> station.json, so the
        # portal drawer can surface it) and its frame notes (-> build_report `frame` array + the
        # [frame] NOTICE log, one aggregated line per survey). Every station is still served AS
        # STORED — nothing is de-rotated; the note is reporting, not correction.
        _fn = list(parsed.get("frame_notes") or [])
        if _survey_frame_note:
            _fn.append(_survey_frame_note)
            if isinstance(r.get("frame"), dict):
                r["frame"]["survey_frame_note"] = _survey_frame_note
        if _fn:
            r["_frame_notes"] = _fn                     # keyed by FINAL id below (post-disambiguate)
        # A file mt_metadata could only read from a normalised temporary copy is RECORDED, never
        # silently repaired: a curator must be able to see which stations needed it. Rides the C18
        # cache with the rest of the parse, so a warm rebuild reports it identically to a cold one.
        if parsed.get("parse_fallback"):
            r["_parse_fallback"] = parsed["parse_fallback"]   # keyed by FINAL id below, as above
        if parsed.get("presence"):
            r["_presence"] = list(parsed["presence"])         # keyed by FINAL id below, as above
        if parsed.get("run_facts"):
            r["_run_facts"] = parsed["run_facts"]             # keyed by FINAL id below, as above
        stations.append((p, r))
        tf_rows.append(tf)
        sci_rows.append(srow)
    _disambiguate(stations, slug)   # keep same-station re-processings as distinct variant records
    # C25: hand the frame notes to the caller keyed by the FINAL (post-disambiguation) station id —
    # the same key discipline the canonical-conditioning notes use.
    if report is not None:
        for (_p, _r) in stations:
            if _r.get("_frame_notes"):
                report.setdefault("frame_notes", {})[_r["id"]] = _r.pop("_frame_notes")
            if _r.get("_presence"):
                report.setdefault("presence_notes", {})[_r["id"]] = _r.pop("_presence")
            if _r.get("_run_facts"):
                report.setdefault("run_facts", {})[_r["id"]] = _r.pop("_run_facts")
            _fb = _r.pop("_parse_fallback", None)
            if _fb:
                report.setdefault("parse_fallbacks", []).append(
                    {"station": _r["id"], "file": _p.name, "defect": _fb})
    else:
        for (_p, _r) in stations:
            _r.pop("_frame_notes", None)
            _r.pop("_parse_fallback", None)
            _r.pop("_presence", None)
            _r.pop("_run_facts", None)
    if _email_hits:
        # Loud, ONCE per survey (not per file — a survey can have hundreds of EDIs from the same
        # custodian). This is a curator flag, not a mutation: the served original .edi bytes are the
        # custodian's published record and are never rewritten; only the DERIVED processing_note
        # (proc_note(), above) is scrubbed before it reaches station.json.
        print(f"  WARNING: survey '{survey_label}' has an email address in the raw >INFO block of "
              f"{len(_email_hits)} source EDI(s): {', '.join(_email_hits)} (derived processing_note "
              f"is redacted; the served original .edi bytes are NOT modified -- flagged for curator "
              f"review, not auto-fixed).", file=sys.stderr)
    return stations, tf_rows, sci_rows


def process_mth5(h5_paths, survey_label, org, slug, report=None):
    """Read transfer functions from MTH5 file(s) and run the SAME shared science as the EDI path.
    Different input format, identical downstream: records_and_components yields (record, periods,
    components) that feed the very same tf_from_components / science_from_components used for EDI, so
    catalogues, derived products and diagnostics are identical where equivalent information exists.
    AusMT reads only transfer-function products + metadata from MTH5 — never raw time series."""
    if not m5.available():
        sys.exit("ERROR: MTH5 input requested but mth5/mt_metadata are not installed "
                 "(pip install mth5 mt_metadata).")
    stations, tf_rows, sci_rows = [], [], []
    for h5 in sorted(h5_paths):
        try:
            for r, per, comp in m5.records_and_components(h5):
                r["state"] = cat.state_of(r.get("lat"), r.get("lon"))
                tf = tfmod.tf_from_components(per, comp) if per else ep.EMPTY_TF
                srow = sci.science_from_components(per, comp, None) if per \
                    else sci.science_from_components(None, {}, None)
                if r.get("lat") is None or r.get("lon") is None or not r.get("n_periods"):
                    print(f"  SKIP {r.get('id')} in {h5.name}: no coordinates/periods in MTH5", file=sys.stderr)
                    if report is not None:
                        report.setdefault("stations_dropped", []).append(
                            {"station": str(r.get("id") or h5.stem),
                             "reason": "no coordinates/periods in MTH5"})
                    continue
                r["survey"] = survey_label
                r["org"] = org
                r["id"] = safe_component(r.get("id"))          # untrusted id -> no traversal / XSS
                r["ausmt_id"] = f"au.{safe_component(slug)}.{r['id']}"
                r["comps"] = "".join(r.get("components") or [])
                stations.append((h5, r))
                tf_rows.append(tf)
                sci_rows.append(srow)
        except Exception as e:  # noqa: BLE001
            print(f"  MTH5 READ FAIL {h5.name}: {e}", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": h5.stem, "reason": f"MTH5 read failed: {type(e).__name__}"})
            continue
    _disambiguate(stations, slug)   # keep same-station re-processings as distinct variant records
    return stations, tf_rows, sci_rows


# The ingest source recorded per station, keyed by the SUFFIX of the file the record was parsed from.
# One derivation for the whole build: build_provenance's input_formats set and build_report's
# per-station ingest_sources both read it, so the two can never disagree about where a station came
# from. A suffix outside this table cannot reach a station record (discovery globs only these).
_INGEST_SOURCE_BY_SUFFIX = {".edi": "edi", ".xml": "emtfxml", ".h5": "mth5", ".mth5": "mth5"}


def _emtfxml_frame(tfobj, n_periods):
    """C25 frame facts for an EMTF-XML source, and the POLICY v3 verdict taken off the file's own
    declaration. Returns (facts, fail_reason); fail_reason is None to serve.

    Gate 1's EDI leg scrapes the RAW EDI text (ZROT/TROT/ROTSPEC/HMEAS) because an EDI states its
    frame only in prose-ish header records. EMTF XML states it MACHINE-READABLY, in
    <Site><Orientation angle_to_geographic_north=...>, which mt_metadata surfaces as
    station_metadata.orientation -- so that block, not a text scrape, is the evidence here. v3 is
    then applied unchanged: a declaration of ANY magnitude serves AS STORED with the angle recorded,
    and an ABSENT declaration is recorded as not-asserted rather than silently reported as 0 degrees.
    Nothing is ever rotated (v3), so `derotated` is always False.

    The TF's own `_rotation_angle` is deliberately NOT read as the declared angle: mt_metadata 1.0.9's
    EMTF-XML reader does not populate it from the file at all (it hands back a bare int 0 even for a
    file declaring 30 degrees -- measured), so reporting it would assert a library default as a
    station fact, exactly what normalize()'s Issue #4/#7 notes exist to prevent. It is consulted for
    one thing only: should a reader ever surface a PER-PERIOD array there, V3-C refuses the station
    rather than pick one of the angles. On the pinned mt_metadata no real EMTF XML reaches that
    branch, so it is a fail-closed guard, exercised at the unit seam rather than by a fixture file."""
    import numpy as np  # noqa: PLC0415

    rot = getattr(tfobj, "_rotation_angle", None)
    rot_vals = []
    if rot is not None:
        try:
            rot_vals = sorted({round(float(v), 4)
                               for v in np.atleast_1d(np.asarray(rot, dtype=float)).ravel()
                               if np.isfinite(v)})
        except (TypeError, ValueError):
            rot_vals = []
    ori = getattr(getattr(tfobj, "station_metadata", None), "orientation", None)
    declared = getattr(ori, "angle_to_geographic_north", None) if ori is not None else None
    try:
        declared = float(declared) if declared is not None else None
    except (TypeError, ValueError):
        declared = None
    facts: dict = {
        "evidence": {
            "branch": "emtfxml",
            "orientation_angle_to_geographic_north_deg": declared,
            "orientation_reference_frame": (getattr(ori, "reference_frame", None)
                                            if ori is not None else None),
            "n_periods": int(n_periods),
        },
        # Kept for station.json shape stability with the EDI path: v3 never rotates, so the
        # rotation SOURCE fields are always None and `derotated` is always False.
        "impedance_rotation_deg_source": None,
        "tipper_rotation_deg_source": None,
        "derotated": False,
    }
    if len(rot_vals) > 1:
        return facts, (f"the EMTF XML resolves to PER-PERIOD rotation angles "
                       f"({min(rot_vals):g}..{max(rot_vals):g}, {len(rot_vals)} distinct); AusMT "
                       f"serves data as stored and never serves a per-period-mixed frame. Re-export "
                       f"this station in one frame.")
    if declared is None:
        facts["frame_served"] = "not-asserted"
        facts["declared_azimuth_deg"] = None
    elif abs(conv._norm_angle(declared)) > conv.ROT_ZERO_EPS_DEG:
        facts["frame_served"] = "declared-azimuth"
        facts["declared_azimuth_deg"] = round(conv._norm_angle(declared), 4)
    else:
        facts["frame_served"] = "declared-zero"
        facts["declared_azimuth_deg"] = 0.0
    return facts, None


def process_emtfxml(xml_paths, survey_label, org, slug, *, exclude_ids=(), report=None):
    """Read transfer functions from EMTF XML file(s) and run the SAME shared science as the EDI
    path. Different input format, identical downstream: `_mtm.record_from_tf` /
    `_mtm.components_from_tf` yield the very same (record, periods, components) the EDI path feeds
    into tf_from_components / science_from_components, so the catalogue row, the derived products
    and the diagnostics are identical where equivalent information exists (the same contract the
    MTH5 input path holds).

    `exclude_ids` carries the OWNER PRECEDENCE RULING (2026-08-03): where a station has both an EDI
    and an EMTF XML, the EDI is the canonical source and the XML is NOT ingested. The caller passes
    the base station ids the EDI pass already produced; a matching XML is skipped with a NOTICE and
    the file stays in the package, untouched. `report`, when given, collects the same survey-scoped
    gate output process_edis collects ({"stations_dropped": [...], "frame_notes": {...}}).

    NOT cached (like the MTH5 input path): the C18 cache stores the EDI parse and the EDI-sourced
    served XML, and the XML path's served bytes include a normalize()-generated EDI that the cache
    does not carry. See _emit_served_xml's derived_edi_dir."""
    if not mtm.available():
        sys.exit("ERROR: the mt_metadata stack is required for the build "
                 "(pip install -r environments/requirements-mtmetadata-lock.txt).")
    exclude = {str(x) for x in (exclude_ids or ())}
    stations, tf_rows, sci_rows = [], [], []
    for p in sorted(xml_paths):
        try:
            tfobj = mtm.read(p)
        except Exception as e:  # noqa: BLE001
            print(f"  PARSE FAIL {p.name}: {e}", file=sys.stderr)
            continue
        r = mtm.record_from_tf(tfobj, p.name, extractor="emtfxml")
        # An EMTF XML sanitises the station id on write (Site.id is ^[a-zA-Z0-9]*$), so recover the
        # UNSANITISED source id the emitter preserved in the Site <Name> when one is present -- the
        # same token normalize() embeds, read back with its own public helper rather than re-derived.
        # The import is a HARD dependency of this arm (a broken environment should fail loud, not
        # silently downgrade identity); only the token parse is guarded, and its failure mode is
        # named for what it is - not a dropped station but a PUBLISHED identifier: the station
        # ships under its sanitised id while the custodian's true id sat unread.
        from ausmt_science.ingest.normalize import (  # noqa: PLC0415
            source_station_id_from_geographic_name as _src_id)
        try:
            _true = _src_id(getattr(tfobj.station_metadata, "geographic_name", None))
        except Exception as _ie:  # noqa: BLE001
            _true = None
            print(f"  WARNING {p.name}: source-id recovery failed ({type(_ie).__name__}); "
                  f"station publishes under its sanitised id", file=sys.stderr)
        if _true and _true != r.get("id"):
            r["site_name"] = r.get("id")
            r["id"] = _true
        r["state"] = cat.state_of(r.get("lat"), r.get("lon"))
        if r.get("lat") is None or r.get("lon") is None or not r.get("n_periods"):
            print(f"  SKIP {p.name}: no coordinates/periods recovered by mt_metadata "
                  f"(malformed EMTF XML or unreadable transfer function)", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": r.get("id") or p.stem,
                     "reason": "no coordinates/periods recovered from EMTF XML"})
            continue
        r["survey"] = survey_label
        r["org"] = org
        r["id"] = safe_component(r.get("id"))          # untrusted Site id -> no traversal / XSS
        if r["id"] in exclude:
            # OWNER PRECEDENCE RULING: this station's EDI already won. The XML is not ingested and
            # not re-emitted from here; it stays in the submitted package as a custodian artifact.
            print(f"  PRECEDENCE {p.name}: station {r['id']} is already ingested from "
                  f"transfer_functions/edi/ -- the EDI is canonical, this EMTF XML is kept in the "
                  f"package but NOT ingested.", file=sys.stderr)
            continue
        r["ausmt_id"] = f"au.{safe_component(slug)}.{r['id']}"
        r["comps"] = "".join(r.get("components") or [])
        _tnotes = []
        per, comp = mtm.components_from_tf(tfobj, notes=_tnotes)
        if _tnotes:
            r["tipper_masked"] = True
            print(f"  NOTICE {r.get('id') or p.stem}: placeholder tipper (|T| flat at 1.0) masked "
                  f"- tipper withheld", file=sys.stderr)
            if report is not None:
                report.setdefault("tipper_masked", []).append(str(r.get("id") or p.stem))
        # Processing metadata comes from the TF's own structured fields: an EMTF XML has no EDI
        # >INFO block, so neither the EDI text scrape nor the processor evidence miner has anything
        # to read here and neither is run. proc_info_from_tf still splits WRITER from PROCESSOR, so
        # a file stamped by a known exporter yields file_written_by and a null processor rather
        # than naming the exporter as one.
        _pm = mtm.proc_info_from_tf(tfobj, with_writer=True)
        proc = (_pm[0], _pm[1], _pm[2])
        r["file_written_by"] = _pm[3]
        tf = tfmod.tf_from_components(per, comp) if per else ep.EMPTY_TF
        srow = sci.science_from_components(per, comp, proc) if per \
            else sci.science_from_components(None, {}, None)
        # C25 Gate 1 (frame), from the file's own machine-readable rotation -- see _emtfxml_frame.
        _frame, _fail = _emtfxml_frame(tfobj, r.get("n_periods") or 0)
        if _fail:
            print(f"  GATE FAIL {p.name} [rotation-frame]: {_fail}", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": r["id"], "reason": f"[rotation-frame] {_fail}"})
            continue
        # C25 Gate 2 (sign convention) is format-agnostic -- it reads the SERVED components, so the
        # EMTF-XML path runs the identical check the EDI path does. A coherent quadrant flip FAILs
        # the station (never serve data under the wrong e^{+/-iwt} sense); one side out is a WARN.
        _ck = conv.convention_check(comp)
        if _ck["verdict"] == "fail":
            print(f"  GATE FAIL {p.name} [sign-convention]: {_ck['detail']}", file=sys.stderr)
            if report is not None:
                report.setdefault("stations_dropped", []).append(
                    {"station": r["id"], "reason": f"[sign-convention] {_ck['detail']}"})
            continue
        _frame["convention_check"] = _ck
        r["frame"] = _frame
        _fn = []
        if _ck["verdict"] in ("warn_xy", "warn_yx", "insufficient"):
            _fn.append(f"convention: {_ck['detail']}")
        if _fn:
            r["_frame_notes"] = _fn                    # keyed by FINAL id below (post-disambiguate)
        stations.append((p, r))
        tf_rows.append(tf)
        sci_rows.append(srow)
    _disambiguate(stations, slug)   # keep same-station re-processings as distinct variant records
    # C25: hand the frame notes to the caller keyed by the FINAL (post-disambiguation) station id --
    # the same key discipline process_edis uses.
    for (_p, _r) in stations:
        _notes = _r.pop("_frame_notes", None)
        if _notes and report is not None:
            report.setdefault("frame_notes", {})[_r["id"]] = _notes
    return stations, tf_rows, sci_rows


def load_portal_config(path) -> dict:
    """Read the portal's branding/version config (portal.config.yaml) for the MTCAT portal block, so a
    re-used portal (NZMT, CanadaMT, …) is configured in one place. Falls back to AusMT defaults when no
    config is given or it cannot be read. Uses PyYAML if present, else the stdlib mini-parser.

    The branding defaults are AusMT literals because AusMT is what this repo brands. The schema version
    is NOT: it comes from MTCAT_SCHEMA_VERSION, generated from the schema's own title, so a re-used
    portal that ships no config (or an unreadable one, or one omitting the key) publishes the version
    the schema in this tree actually declares instead of whatever was last typed here."""
    default = {"portal_id": "ausmt",
               "portal_name": "AusMT — Australia's Magnetotelluric Data Portal",
               "schema_version": MTCAT_SCHEMA_VERSION}
    if not path:
        return default
    try:
        text = Path(path).read_text()
    except OSError:
        return default
    try:
        import yaml  # type: ignore  # noqa: PLC0415
    except ModuleNotFoundError:
        cfg = _mini_yaml(text)  # stdlib-only fallback when PyYAML is absent
    else:
        # PyYAML present: a malformed config must fail loudly, not silently fall through to the
        # mini-parser (which would parse some fields and drop others with no diagnostic).
        try:
            cfg = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            sys.exit(f"ERROR: portal config {path} is not valid YAML: {e}")
    p = (cfg or {}).get("portal", {}) if isinstance(cfg, dict) else {}
    if not isinstance(p, dict):
        p = {}   # a non-mapping portal: block (e.g. `portal: true`) must not crash p.get below
    name = p.get("name") or default["portal_name"]
    portal_name = name
    return {"portal_id": p.get("id", "ausmt"),
            "portal_name": portal_name,
            "schema_version": str(p.get("schema_version", MTCAT_SCHEMA_VERSION))}


def _extent_of(y: dict):
    """(west, east, south, north) from a survey.yaml geographic_extent, or None if not declared
    (the mini-yaml fallback can leave an inline {…} unparsed, in which case we treat it as absent)."""
    ext = y.get("geographic_extent")
    if not isinstance(ext, dict):
        return None
    try:
        return (float(ext.get("west")), float(ext.get("east")),
                float(ext.get("south")), float(ext.get("north")))
    except (TypeError, ValueError):
        return None   # missing/quoted/garbage bound -> treat as undeclared so qc_pass never compares str to float


def _apply_coord_resolution(stations, cr):
    """Apply a survey-declared resolution of the DMS sign-bug ambiguity (data-driven; replaces the
    old hard-coded per-survey rule). survey.yaml may declare:

        coordinate_resolution: { dms_sign: info|head, basis: "<ground truth>" }

    When a station is flagged 'dms_sign_ambiguous' and the survey says to trust INFO (the decimal
    block — correct for LEMI/Geotools exports whose negative HEAD DMS was floored), swap in the
    INFO coordinate and record the resolution + its basis. With no
    declaration the coordinate stays as HEAD (the EDI-standard field) and remains flagged so the
    portal can badge it 'treat with caution'."""
    if not isinstance(cr, dict):
        return
    choose = str(cr.get("dms_sign") or cr.get("chosen") or "").lower()
    if choose not in ("info", "head"):
        return
    for (_p, r) in stations:
        if r.get("coord_flag") != "dms_sign_ambiguous":
            continue
        if choose == "info":
            cand = (r.get("coord_candidates") or {}).get("info")
            if not (cand and cand[0] is not None and cand[1] is not None):
                # Fail LOUD, never open: the survey declared a resolution this station cannot take
                # (no usable INFO pair - _edi_catalog.info_coords can return (value, None)). Stamping
                # it resolved would erase the outstanding conflict and publish a coord_resolution
                # that never happened - the DMS sign-bug class (~140 km) the flag exists to catch.
                print(f"  WARNING {r.get('id')}: declared dms_sign resolution 'info' cannot be "
                      f"applied (no usable INFO coordinate pair); station stays flagged",
                      file=sys.stderr)
                continue
            r["lat"], r["lon"] = round(cand[0], 6), round(cand[1], 6)
        r["coord_flag"] = "dms_sign_resolved"
        r["coord_conflict_deg"] = None   # the HEAD/INFO conflict is now resolved, not outstanding
        r["coord_resolution"] = {"chosen": choose, "basis": cr.get("basis"), "source": "survey.yaml"}


def _station_identity(r, label, slug) -> dict:
    """The identity block every station.json opens with, on BOTH branches, in the schema's own order.

    `survey` is the display label (the legacy surface, frozen); `survey_id` is the slug, the identifier
    the machine surfaces key on - mtcat's surveys[].survey_id and survey-metadata.json's are the same
    slug, and a display label is not an identifier. STATION_SCHEMA_VERSION is the generated mirror of
    the single-source constant, never a literal, so a document cannot claim a version the schema served
    beside it does not."""
    return {"schema": "ausmt-station", "version": STATION_SCHEMA_VERSION,
            "ausmt_id": r["ausmt_id"], "station": r["id"], "survey": label, "survey_id": slug}


def _folded_dimensionality(srow) -> dict:
    """D1: the dimensionality members station.json's `diagnostics` carries, read off the sidecar
    document itself so the two surfaces cannot state different calls. `screening_diagnostic` stays
    sidecar-only: where the numbers now sit, the caveat text carries that meaning.

    A member the call leaves UNDETERMINED is omitted rather than copied. The sidecar states it as
    null and keeps doing so (D14), but a null here would be a value where the promoted document says
    absence: an `indeterminate` classification has no skew statistic to state."""
    return {k: v for k, v in _dimensionality_document(srow).items()
            if k != "screening_diagnostic" and v is not None}


# resources[] (D3): one row per SERVED, ADDRESSABLE thing, keyed by the manifest format it is
# emitted under. `id` is stable within the document and is never an array index or a path.
#
# D19 role axes, emitted ONLY where they are mechanically certain: the served EDI is the custodian's
# never-edited source in its original form (rule 11), while the EMTF XML and the MTH5 are this
# engine's conversions of it. The bundle archives carry NEITHER axis in 0.1: whether a zip of source
# EDIs is source or derived is a semantics call this lane must not improvise.
_RESOURCE_BY_FORMAT = {
    "edi":         {"id": "edi", "kind": "transfer_function", "format": "edi",
                    "provenance_role": "source", "representation_role": "original"},
    "emtfxml":     {"id": "emtfxml", "kind": "transfer_function", "format": "emtfxml",
                    "provenance_role": "derived", "representation_role": "alternate"},
    "mth5":        {"id": "mth5", "kind": "transfer_function", "format": "mth5",
                    "provenance_role": "derived", "representation_role": "alternate"},
    "edi-zip":     {"id": "edi-zip", "kind": "archive", "format": "zip"},
    "xml-zip":     {"id": "xml-zip", "kind": "archive", "format": "zip"},
    "survey-mth5": {"id": "survey-mth5", "kind": "archive", "format": "mth5"},
}
# GATE 12 (D16). The clean station vocabularies (scope 4.4) crosswalked OUT to NCI's level names and
# to MTCAT's legacy `identifies` values. Direction of dependency, stated because it is the whole
# point: the station concepts are the SOURCE of this mapping and the legacy values are the target,
# so MTCAT's heterogeneous vocabulary is mapped FROM, never inherited. The time-series route table
# below is this table's first consumer: a `time_series` row's processing_level and packaging come
# from these keys, and its containing-collection identifier is matched on the `mtcat_identifies`
# value, which covers 20 of the 42 related_identifiers rows in the survey packages.
STATION_VOCABULARY_CROSSWALK = {
    ("raw", "packed_archive"): {"nci": "the survey's packed raw time series (NCI numbers no level "
                                       "for it)", "mtcat_identifies": "raw_packed"},
    ("level0", None): {"nci": "level_0", "mtcat_identifies": "level0"},
    ("level1", None): {"nci": "level_1", "mtcat_identifies": "level1"},
    ("level2", None): {"nci": "level_2", "mtcat_identifies": "level2"},
    ("level3", None): {"nci": "level_3", "mtcat_identifies": "level3"},
}
# The legacy identifies values that are SCOPE, not processing level. Mapping them onto a station
# processing_level is precisely the identifies debt the separated vocabularies exist to refuse.
STATION_VOCABULARY_UNMAPPED = ("collection", "entire")
# What a curated `identifies` must name before a row can be PLACED as a containing collection: a
# collection, or a product level. Derived from the crosswalk above so a level added there cannot be
# silently unplaceable here. `entire` is the one legacy value that is neither - MTCAT defines it as
# one record covering all levels, which states the scope of a RECORD and asserts no containment.
_PLACEABLE_SCOPES = frozenset({"collection"} | {v["mtcat_identifies"]
                                                for v in STATION_VOCABULARY_CROSSWALK.values()})
# D2: the repository that holds the bytes a `time_series` row routes to. The schema's deferral
# trigger (:327) has fired; the crawler knows the host with certainty, NCI is the ratified token, and
# a controlled string is additively replaceable by a richer object when one exists.
TS_REPOSITORY = "NCI"
# {register level token: what a `time_series` row for it states}. `vocab` is a crosswalk KEY, so a
# level added to the crosswalk cannot be silently unroutable here; `format` is the domain token for
# what the archive serves; `roles` are the D19 axes.
#
# level2 IS ABSENT BY RULING (D19, 2026-08-24), not by omission: NCI's level_2 tree holds transfer
# functions, and projecting 1,197 of them as kind=time_series would assert a verified TIME SERIES for
# 88 stations that have none. The token stays in the register's vocabulary for hand-curated rows;
# nothing here routes it, and _stationcheck rejects one that reaches a document by another path.
#
# ORDER IS THE EMITTED ORDER: the emitter iterates this table rather than the register file, so two
# registers listing one station's levels differently produce identical documents.
_TS_LEVEL_ROUTE = {
    "raw_packed":    {"vocab": ("raw", "packed_archive"), "format": "zip",
                      "roles": ("source", "original")},
    "level0":        {"vocab": ("level0", None), "format": "mth5",
                      "roles": ("derived", "alternate")},
    "level1_mth5":   {"vocab": ("level1", None), "format": "mth5",
                      "roles": ("derived", "alternate")},
    "level1_netcdf": {"vocab": ("level1", None), "format": "netcdf",
                      "roles": ("derived", "alternate")},
}


def station_time_series_resources(rows, collection_identifiers, run_ids=()) -> list:
    """The `kind: time_series` rows for ONE station, from its register rows.

    A row describes bytes on ANOTHER host: it carries a route and no `path`, no checksum and no
    `service_urls` (this archive answers 500 on OPeNDAP, so no service is advertised at all). AusMT
    hands the reader off; it never proxies, re-hosts or re-zips.

    THREE THINGS DECIDE WHETHER A ROW EXISTS, and this renders rather than decides any of them.
    `_tsproject.projects` answers the first two - `review: verified` (a pending row is an
    adjudication-queue entry and a retired one is evidence of a resource that ceased to exist, so
    neither publishes) and a routable level (D19 excludes level2) - and it is IMPORTED rather than
    restated, because that rule also decides the flag, the boot artifact and the front door's route
    table, and four surfaces cannot be allowed four opinions. The third is the access gate, applied
    at the capture site so this renders what it is handed. A level with nothing verified produces NO
    row, never a row with a null route.

    `related_collection_identifiers` rides the level whose PRODUCT the curated DOI names, matched on
    the crosswalk's own `mtcat_identifies` value. A survey-scope collection DOI is not projected
    here: it identifies the collection rather than this product, and a row that IS a download route
    is the last place a reader should have to work out which."""
    out = []
    by_level = {row["level"]: row for row in rows if tsproject.projects(row)}
    for level, route in _TS_LEVEL_ROUTE.items():
        row = by_level.get(level)
        if row is None:
            continue
        processing_level, packaging = route["vocab"]
        provenance, representation = route["roles"]
        res = {"id": f"ts-{level}", "kind": "time_series", "format": route["format"],
               "provenance_role": provenance, "representation_role": representation,
               "access_url": stcheck.ts_access_url(row["url_path"]), "repository": TS_REPOSITORY,
               "processing_level": processing_level}
        if packaging:
            res["packaging"] = packaging
        if row.get("bytes"):
            res["bytes"] = row["bytes"]
        if provenance == "derived" and run_ids:
            # SCOPE:337-339's case: a concatenated/resampled/rotated product IS derived from the
            # acquisition this record publishes, so the link holds wherever the run id exists.
            res["derived_from_runs"] = sorted(run_ids)
        scope = STATION_VOCABULARY_CROSSWALK[route["vocab"]]["mtcat_identifies"]
        placed = [dict(e) for e in collection_identifiers if e.get("identifies") == scope]
        if placed:
            res["related_collection_identifiers"] = placed
        # R9 as amended by D18: rule 14 forbids a network call inside the build, so the build
        # verifies nothing. The date is the crawler's, carried through unchanged.
        res["note"] = f"verified against NCI THREDDS on {row['verified']}"
        out.append(res)
    return out


def station_collection_identifiers(meta):
    """(related_collection_identifiers[], declined notes) for one survey's curated rows.

    SCOPE:173-179 makes placement verification mandatory and this lane resolves no DOIs, so a row is
    projected only where the CURATION states its entity scope: a bare canonical DOI whose
    `identifies` names a collection or product level. The scope travels with the row, so a
    collection DOI can never read as an identifier of the file it sits beside.

    Everything else is REFUSED and reported for curation, because an unplaceable row would publish a
    wrong citation claim: a row with no `identifies` (nothing states what it names), a row whose
    `identifies` names neither a collection nor a product level, a row that is not a DOI, and a DOI
    one survey declares at two different levels (the curated scope contradicts itself, so neither row
    is placeable)."""
    rows, declined = [], []
    curated = [r for r in ((meta or {}).get("related_identifiers") or []) if isinstance(r, dict)]
    levels: dict = {}
    for row in curated:
        levels.setdefault(str(row.get("identifier") or ""), set()).add(row.get("identifies"))
    for row in curated:
        raw = str(row.get("identifier") or "")
        scope = row.get("identifies")
        if str(row.get("identifier_type") or "").upper() != "DOI":
            declined.append(f"{raw}: identifier_type is {row.get('identifier_type')!r}, not DOI")
            continue
        if not scope:
            declined.append(f"{raw}: `identifies` is absent, so nothing states what this DOI names")
            continue
        if scope not in _PLACEABLE_SCOPES:
            declined.append(f"{raw}: `identifies` is {scope!r}, which names neither a collection nor "
                            f"a product level, so it asserts no containment")
            continue
        doi = _SM_DOI_RESOLVER_RE.sub("", raw).strip()
        if not _BARE_DOI_RE.match(doi):
            declined.append(f"{raw}: not a bare canonical DOI")
            continue
        if len(levels.get(raw, set())) > 1:
            declined.append(f"{raw}: declared at two levels ({', '.join(sorted(str(s) for s in levels[raw]))}), "
                            f"so its curated scope contradicts itself")
            continue
        entry = {"scheme": "DOI", "identifier": doi, "identifies": scope}
        if entry not in rows:
            rows.append(entry)
    return rows, declined


def station_resources(served_formats, collection_identifiers, ts_rows=(), run_ids=()) -> list:
    """resources[] for one open station. `served_formats` is {manifest format: served path} for the
    station's own renditions AND the survey bundles it put bytes into, captured at the emit sites so
    the path here is the one the manifest records for the same bytes and never a second derivation
    of it. The caller does the bundle-membership filtering; this renders what it is handed.

    `ts_rows` are this station's verified-resource register rows, APPENDED after the served rows so
    no existing row moves: what AusMT serves is described first, what it hands off to comes after.

    No row carries `identifiers[]`: no DOI identifies any exact file AusMT serves today (D3), and a
    collection DOI presenting as a file DOI is the failure the identity contract names. The
    containing-collection hook is `related_collection_identifiers`, projected by
    station_collection_identifiers() and identical for every resource of one survey, since each
    curated row names a collection whose scope covers this survey's holdings, not one file."""
    out = []
    for fmt, template in _RESOURCE_BY_FORMAT.items():
        path = served_formats.get(fmt)
        if not path:
            continue
        row = dict(template)
        row["path"] = path
        if collection_identifiers:
            row["related_collection_identifiers"] = [dict(e) for e in collection_identifiers]
        out.append(row)
    return out + station_time_series_resources(ts_rows or [], collection_identifiers, run_ids)


# The published channel order: the acquisition families in the order every dialect writes them,
# then anything else alphabetically, so two builds of one station order its channels identically.
_CHANNEL_ORDER = ("ex", "ey", "hx", "hy", "hz")
# What the schema lets each channel family carry. The guards are also IN the schema (an electric
# channel may not carry `sensor`, a magnetic one may not carry the electrode-circuit fields); they
# are applied here first so a future extractor cannot produce a document only the validator catches.
_ELECTRIC_CHANNEL_KEYS = ("measurement_azimuth_deg", "sample_rate_hz", "dipole_length_m",
                          "contact_resistance", "positive", "negative")
_MAGNETIC_CHANNEL_KEYS = ("measurement_azimuth_deg", "sample_rate_hz", "sensor")


def _measured_components(comps) -> set:
    """The channels the SERVED transfer function was measured from. An impedance is estimated from
    the two electric and the two horizontal magnetic channels; a tipper adds the vertical magnetic.
    This is the corroboration D9 accepts alongside the >INFO naming a channel; DEFINEMEAS is not
    consulted at all, because a declaration there is what D9 rules insufficient."""
    out = set()
    if "Z" in (comps or ""):
        out |= {"ex", "ey", "hx", "hy"}
    if "T" in (comps or ""):
        out |= {"hx", "hy", "hz"}
    return out


def station_runs(run_facts, run_ids, station_id, comps):
    """(runs[], curation notes) for one station. `run_facts` is the >INFO extraction
    (extract/_runfacts), `run_ids` this survey's persistent store (extract/_runids).

    D2: a run is published only where the source asserts a run id or a real acquisition fact; the
    placeholder run mt_metadata instantiates for every file it reads is never published, so most of
    the corpus correctly gets no runs[] at all. The id comes from the store and from nowhere else
    (scope section 9: assigned once, never regenerated), so a qualifying station with no stored row
    publishes nothing and the gap is REPORTED instead.

    ONE run per station: no corpus source describes two acquisitions for one station, and splitting
    one source record across two stored ids would be inventing which facts belong to which run. A
    longer stored row is a curation signal and rides the notes."""
    facts = list((run_facts or {}).get("facts") or [])
    if not facts:
        return [], []
    ids = list((run_ids or {}).get(station_id) or [])
    notes = []
    if not ids:
        return [], [f"curation: {station_id} asserts acquisition facts ({', '.join(facts)}) but the "
                    f"run-id store has no row for it, so no runs[] is published; assign one with "
                    f"_tools/assign_run_ids.py"]
    if len(ids) > 1:
        notes.append(f"curation: the run-id store gives {station_id} {len(ids)} run ids "
                     f"({', '.join(ids)}) while its source describes one acquisition; only "
                     f"{ids[0]} is published")
    src = dict((run_facts or {}).get("run") or {})
    run = {"id": ids[0]}
    period = dict(src.get("time_period") or {})
    if period.get("start"):
        # `end` is ABSENT when unknown, never null: absence is the open-world statement that the
        # source did not say when the acquisition stopped.
        run["time_period"] = {k: period[k] for k in ("start", "end") if period.get(k)}
    if src.get("sample_rate_hz"):
        run["sample_rate_hz"] = src["sample_rate_hz"]
    if src.get("data_logger"):
        run["data_logger"] = src["data_logger"]

    named = {c.lower() for c in ((run_facts or {}).get("named_components") or [])}
    excluded = {c.lower() for c in ((run_facts or {}).get("excluded_components") or [])}
    # D9: corroborated beyond DEFINEMEAS alone, minus anything a source assertion contradicts, minus
    # the rr* pair, which the PRESENCE rule governs rather than corroboration (they are mt_metadata
    # run defaults; over the corpus EDIs the CHTYPE census carries no RRHX at all).
    components = {c for c in (named | _measured_components(comps))
                  if c not in excluded and not presence.is_run_default_component(c)}
    channels = []
    for component in sorted(components, key=lambda c: (_CHANNEL_ORDER.index(c)
                                                       if c in _CHANNEL_ORDER else len(_CHANNEL_ORDER), c)):
        allowed = (_ELECTRIC_CHANNEL_KEYS if component.startswith("e") else _MAGNETIC_CHANNEL_KEYS)
        source = ((run_facts or {}).get("channels") or {}).get(component) or {}
        channel = {"component": component}
        channel.update({k: source[k] for k in allowed if source.get(k) is not None})
        if channel.get("sample_rate_hz") and not run.get("sample_rate_hz"):
            # schema: a run whose channels declare a rate MUST declare its own nominal rate, so the
            # survey rate rollup cannot silently lose one. With no nominal rate to state, the
            # channel rate is dropped rather than published outside the relationship that types it.
            channel.pop("sample_rate_hz")
            notes.append(f"curation: {station_id} channel {component} declares a rate while its run "
                         f"declares no nominal rate; the channel rate is withheld")
        channels.append(channel)
    if channels:
        run["channels"] = channels
    return [run], notes


def station_document(r, srow, label, org, meta, lic, slug, p, edi_rel, conditioning_notes, served,
                     prov, runs=None, resources=None) -> dict:
    """Build one station's station.json (schema/ausmt-station.schema.json 0.1, the third public
    contract) from the station record `r`, its science row `srow` and the survey context. Returns a
    plain-JSON dict in the schema's property order; the caller serialises with _jdump(doc, indent=1)
    and is the only thing that touches the filesystem. Nothing here reads a published file back.

    `r` is the SHARED station record, masked in place at the single coordinate seam, which is why the
    caller runs deferred (C42): `location` carries the post-mask value every other emitter reads, with
    no per-emitter mask logic. `edi_rel` is the portal-relative path of the EDI this station ACTUALLY
    serves, or None when it serves none. It is a path rather than a bool because the served EDI is not
    always named after the input: an EMTF-XML-sourced station serves the normalize()-generated
    <station>.edi, while its `input_file` provenance stays the submitted .xml it was built from.

    C1c: products/ IS a served surface in deployment (deploy/Makefile writes it INSIDE the served build
    dir), so it rides the SAME C1 access gate as tf.json/sci.json. For a NON-SERVED survey (embargoed
    with an active embargo, or metadata_only) the derived TF science IS the embargoed data: emitting
    median_relative_error, the completeness diagnostic or the frame phase medians here would publish
    exactly what the byte gate (C1) and the display gate (C1b) withhold. `served` is the survey's
    access_serve_state["served"] captured at the emit site, never re-derived."""
    edi_served = edi_rel is not None
    if not served:
        # The withheld record carries ONLY the discovery-safe identity the public catalogue already
        # exposes: no TF-derived science, no exact source position, no input_sha256.
        return {
            **_station_identity(r, label, slug),
            "country": (meta or {}).get("country", "Australia"), "organisation": org,
            "access": {"level": normalise_access_level((meta or {}).get("access", "open")),
                       "embargo_until": (meta or {}).get("embargo_until"), "served": False},
            "distribution": {"edi_available": False, "license": lic, "edi_path": None},
            # discovery-universal flag: the survey is fully in the catalogue/surveys/mtcat; only the derived
            # science products are withheld here (same posture as the withheld tf.json/sci.json rows).
            "withheld": True,
            "note": "This survey's access state withholds its derived science products (embargoed or "
                    "metadata_only). Discovery metadata remains in the catalogue; the science is released "
                    "when the survey's access.level is opened.",
        }
    doc = {
        **_station_identity(r, label, slug),
        "country": (meta or {}).get("country", "Australia"), "organisation": org,
        # C42: post-mask coordinates, exact / generalised (0.1deg) / withheld (null) per the custodian
        # policy, read from the single-seam-masked record.
        "location": {"lat": r["lat"], "lon": r["lon"]},
        "data": {"type": r.get("type"), "n_periods": r.get("n_periods"),
                 "period_min_s": r.get("period_min_s"), "period_max_s": r.get("period_max_s")},
        # D1: the dimensionality call is FOLDED IN here, and the method string and the screening caveat
        # come with it, from the SAME computed values _dimensionality_document() reads. The earlier
        # removal was aimed at a copy that travelled WITHOUT the caveat; folding the caveat in is what
        # answers that, and it puts the qualification beside the numbers instead of one file away. The
        # sidecar keeps being written byte-unchanged through 1.x (D14): deleting a served file is a
        # deprecation. This block sits INSIDE the C1 access gate above, so a withheld record gains no
        # diagnostics at all and the interpretation product stays out of it.
        "diagnostics": {"median_relative_error": srow[_SC["mre"]], "remote_reference": bool(srow[_SC["rr"]]),
                        "tipper_available": "T" in (r.get("comps") or ""),
                        "completeness_smoothness_diagnostic": {
                            "value": srow[_SC["q"]], "basis": srow[_SC["qb"]],
                            "note": "not a quality or geological-value judgement"},
                        **_folded_dimensionality(srow)},
        # Processing metadata is all BEST-EFFORT (scraped from the EDI; mt_metadata's structured fields
        # are empty for most dialects). LINEAGE: `software` is the program that PROCESSED the transfer
        # function, `file_written_by` the program that SERIALISED the file; they are usually different
        # programs and were once conflated. A null software means the file states no processor, NOT that
        # none was used. The remote-reference arrangement detail lives in `note` (the EDI INFO block);
        # remote_site is the named reference station where derivable (Phoenix 'P=x R=y' DATAID).
        "processing": {"software": srow[_SC["sw"]], "algorithm": srow[_SC["alg"]],
                       "remote_reference": bool(srow[_SC["rr"]]),
                       "remote_site": r.get("remote_site"),
                       "file_written_by": r.get("file_written_by") or {"name": None, "version": None},
                       "note": r.get("processing_note")},
        # C42: edi_served folds in the per-station coordinate byte-gate. A non-exact station is NOT
        # distributed even inside a served survey, so its distribution must not advertise an EDI.
        "distribution": {"edi_available": edi_served, "license": lic,
                         "edi_path": edi_rel},
        # provenance: input -> software/params -> output (traceable, per Egbert). `source` is the
        # THIRD-PARTY ingest provenance the custodian declared in survey.yaml's station_ids block. It
        # rides AusMT's record because the source EDI is served byte-identical and is never rewritten.
        # ADDITIVE + absent-means-absent: a survey that declares none gains no key at all.
        "provenance": {**prov, "input_file": p.name, "input_sha256": sha256(p),
                       **({"source": r["source_provenance"]} if r.get("source_provenance") else {})},
        # coordinate QC: present only when the parse flagged something, so consumers can surface
        # "treat with caution" without implying anything about unflagged stations.
        "coordinate_qc": ({"flag": r.get("coord_flag"),
                           "head_info_conflict_deg": r.get("coord_conflict_deg"),
                           "resolution": r.get("coord_resolution")}
                          if (r.get("coord_flag") or r.get("coord_conflict_deg")) else None),
        # canonical_conditioning: what normalize() had to change to make this station's canonical EMTF
        # XML schema-valid and round-trippable. Present only when the station was actually conditioned,
        # so an unconditioned station is not implied to be.
        "canonical_conditioning": (conditioning_notes.get(r["id"]) or None),
        # frame (C25): the measured frame facts and the sign-convention verdict for THIS station. None
        # only for inputs the gates do not cover (the flag-gated MTH5 path).
        "frame": r.get("frame"),
    }
    # C42 A1: the coordinate policy rides station.json too (secondary to the boot-loaded
    # coord_policy.json the portal drawer reads, but consistent for a curator reading the product).
    # Added ONLY for a non-exact station; an exact record gains no key.
    cp = r.get("coord_policy")
    if cp and cp != "exact":
        doc["coordinate_policy"] = cp
    # runs[] (D2), APPENDED so no existing key moves. Absent where the source asserts no acquisition
    # fact, which is most of the corpus and is the correct open-world statement: run metadata not
    # asserted, never "no runs occurred". Assembled by station_runs() from the >INFO extraction and
    # the persistent run-id store; the withheld branch above returns before this and gains none.
    if runs:
        doc["runs"] = runs
    # resources[] (D3), appended for the same reason. Absent where the station serves no bytes at
    # all, which is the honest statement: a station whose EDI the coordinate gate withholds has no
    # served rendition to describe.
    if resources:
        doc["resources"] = resources
    return doc


def _dimensionality_document(srow) -> dict:
    """The phase-tensor screening result served beside station.json. Served-survey stations only: it is
    a pure interpretation product, so a non-served survey gets none at all."""
    return {"classification": srow[_SC["dim"]], "skew_beta_median_deg": srow[_SC["skew"]],
            "pct_periods_3d": srow[_SC["p3d"]], "method": "phase-tensor (Caldwell 2004)",
            "screening_diagnostic": True,
            "note": "screening diagnostic, not an interpretation product"}


def _write_station_products(job, prov, served_root, products_dir, served_formats=None,
                            bundle_formats=None, collection_ids=None, ts_rows=None):
    """Write one station's per-station products. `job` is the tuple captured in main()'s per-survey
    loop and drained after the coordinate mask; `prov` is the build PROV block. The rendering lives in
    station_document() / _dimensionality_document(); this is the write path alone.

    `served_formats` / `bundle_formats` / `collection_ids` / `ts_rows` are the resources[] inputs,
    captured at the manifest emit sites. They arrive HERE rather than in the job because a survey's
    bundles are emitted after its station loop, so the per-survey archive rows do not exist yet when
    the job is queued. `ts_rows` is {ausmt_id: [register row]}, captured behind the SAME access gate
    the byte-gated renditions are: a station absent from it publishes no route.

    Returns (served path, document) so main() can run the station self-check over the bytes it just
    published without reading a served file back (SCOPE:289-290).

    D7: station.json is published under `served_root` (out/products) UNCONDITIONALLY, because it is a
    public contract and a build run without --products would otherwise ship a data tree with a
    documented contract missing from it. It is ALSO published under `products_dir` where that is a
    different directory, which is not redundancy: five test files build with a --products dir outside
    --out and read station.json back out of it, and deploy/Makefile makes the two coincide in
    deployment, so the served path is the same either way. dimensionality.json is not a contract and
    keeps its single --products home."""
    (r, srow, label, org, meta, lic, slug, p, edi_rel, conditioning_notes, served, runs) = job
    _own = dict((served_formats or {}).get(r["ausmt_id"]) or {})
    # A bundle row is a containment claim, so it rides only a station whose bytes are actually in that
    # bundle: the C42 byte gate withholds a non-exact station's EDI and EMTF XML, so it is in neither
    # zip its survey publishes. stcheck.ARCHIVE_MEMBER_FORMAT names the rendition that proves it, and
    # the semantic layer re-checks the same rule over the emitted document.
    _formats = {fmt: path for fmt, path in ((bundle_formats or {}).get(slug) or {}).items()
                if stcheck.ARCHIVE_MEMBER_FORMAT.get(fmt) in _own}
    _formats.update(_own)
    doc = station_document(r, srow, label, org, meta, lic, slug, p, edi_rel, conditioning_notes,
                           served, prov, runs,
                           station_resources(_formats, (collection_ids or {}).get(slug) or [],
                                             (ts_rows or {}).get(r["ausmt_id"]) or [],
                                             [run["id"] for run in (runs or [])]))
    payload = _jdump(doc, indent=1)
    served_dir = served_root / slug / r["id"]
    curated_dir = (products_dir / slug / r["id"]) if products_dir is not None else None
    dirs = [served_dir]
    if curated_dir is not None and curated_dir.resolve() != served_dir.resolve():
        dirs.append(curated_dir)
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / "station.json").write_text(payload, encoding="utf-8")
    written = (f"products/{slug}/{r['id']}/station.json", doc)
    if not served or curated_dir is None:
        return written   # no dimensionality.json for a non-served survey (interpretation product = withheld science)
    curated_dir.mkdir(parents=True, exist_ok=True)
    (curated_dir / "dimensionality.json").write_text(_jdump(_dimensionality_document(srow), indent=1),
                                                     encoding="utf-8")
    return written


def qc_pass(all_stations, survey_extent):
    """Build-time QC over the assembled catalogue. Returns a findings dict; the caller decides what
    blocks. The only HARD failure is duplicate ausmt_ids — non-unique ids corrupt the URL/export/r[12]
    contract and cannot be valid. Everything else is advisory:
      * near_duplicate_locations  — re-occupation across surveys/years is legitimate for MT (notice).
      * coord_flags / coord_conflicts — per-station coordinate-parse signals (also badged in the portal).
      * outside_declared_extent   — a station outside its OWN survey's declared extent (FYI). This is
        NOT an Australia bounding-box test: ocean-bottom, overseas and Antarctic sites are expected, so
        a site is only noted when it falls outside the extent that survey itself declares. Surveys with
        no declared extent are counted quietly (stations_without_survey_extent), never listed.
    """
    def fid(p, r):
        # Delegates to the mask module's single derivation, so the qc keys and the policy resolver
        # are the same function by construction (never a second, divergent fallback here).
        return coordacc.fid(p, r)

    seen, dups = {}, []
    for (p, r) in all_stations:
        aid = r.get("ausmt_id")
        if aid in seen:
            dups.append({"ausmt_id": aid, "files": [seen[aid], fid(p, r)]})
        else:
            seen[aid] = fid(p, r)

    grid, near = {}, []
    for (p, r) in all_stations:
        if r.get("lat") is None or r.get("lon") is None:
            continue
        k = (round(r["lat"], 3), round(r["lon"], 3))  # ~100 m bins
        f = fid(p, r)
        if k in grid and grid[k] != f:
            near.append({"a": grid[k], "b": f, "at_deg": [k[0], k[1]]})
        else:
            grid.setdefault(k, f)

    coord_flags = [{"file": fid(p, r), "ausmt_id": r.get("ausmt_id"), "flag": r.get("coord_flag"),
                    "resolved": bool(r.get("coord_resolution"))}
                   for (p, r) in all_stations if r.get("coord_flag")]
    coord_conflicts = [{"file": fid(p, r), "ausmt_id": r.get("ausmt_id"), "delta_deg": r.get("coord_conflict_deg")}
                       for (p, r) in all_stations if r.get("coord_conflict_deg")]

    outside, no_extent = [], 0
    for (p, r) in all_stations:
        if r.get("lat") is None or r.get("lon") is None:
            continue
        ext = survey_extent.get(r.get("survey"))
        if not ext:
            no_extent += 1
            continue
        w, e, s, n = ext
        if not (s <= r["lat"] <= n and w <= r["lon"] <= e):
            outside.append({"file": fid(p, r), "ausmt_id": r.get("ausmt_id"),
                            "lat": r["lat"], "lon": r["lon"], "survey": r.get("survey")})

    return {"n_stations": len(all_stations),
            "duplicate_ausmt_ids": dups,
            "near_duplicate_locations": near,
            "coord_flags": coord_flags,
            "coord_conflicts": coord_conflicts,
            "outside_declared_extent": outside,
            "stations_without_survey_extent": no_extent}


_GIT_COMMIT_MEMO: dict = {}   # str(cwd) -> short sha; SUCCESSES only (A4 salt-stability hardening)


def _git_commit_at(cwd):
    """Short git HEAD commit of the repo containing `cwd`, or None when `cwd` doesn't sit inside a git
    work tree (not installed / not a repo / detached bare checkout) -- graceful, never raises. Shared by
    _build_prov (engine_commit, resolved at HERE = engine/extract/) and build.json's source_commit
    (resolved at the --surveys root, a SEPARATE repo per ADR-001 -- ausmt-surveys, not ausmt).

    Memoised PER PROCESS on success (A4, the C18c-flake hardening): the resolved commit feeds the C18
    cache salt, so two builds in one interpreter (tests; any future in-process rebuild loop) must key
    identically even if HEAD moves or a transient rev-parse failure lands between them — a mid-suite
    salt flip is exactly the nondeterministic full-miss the 2026-07-07 verification runs hit. A FAILED
    resolution is never memoised (a later build in this process may still resolve); tests that need a
    different commit monkeypatch this NAME, which bypasses the memo entirely."""
    key = str(cwd)
    if key in _GIT_COMMIT_MEMO:
        return _GIT_COMMIT_MEMO[key]
    import subprocess as _sp
    try:
        got = _sp.check_output(["git", "rev-parse", "--short", "HEAD"],
                               cwd=key, stderr=_sp.DEVNULL).decode().strip() or None
    except Exception:  # noqa: BLE001
        return None
    if got is not None:
        _GIT_COMMIT_MEMO[key] = got
    return got


def _build_prov(extractor):
    """The provenance/reproducibility block emitted with every product (Egbert/Heinson/Kelbert: an
    output must trace to its inputs, software and parameters). Captures the pipeline + version +
    extractor + python + git commit + the ACTUAL dimensionality decision-boundary parameters."""
    import datetime as _dt
    import platform as _pf

    def _git_commit():
        # U2: the engine image COPYs engine/ WITHOUT .git (deploy/docker/engine.Dockerfile), so
        # _git_commit_at(HERE) is ALWAYS None in a container -- fall back to AUSMT_ENGINE_COMMIT, the
        # real commit CI bakes in at image-build time (deploy-images.yml's GIT_SHA build-arg -> ENV;
        # the SAME env build_identity() consumes). Provenance stays HONEST where build_identity()'s
        # opaque build_id renders "unknown": the Dockerfile's ARG default "unknown" (a bare `docker
        # build` with no --build-arg) AND an empty env var both resolve to None ("unavailable"), never
        # a fabricated commit string. So a real container build records the real commit; a local bare
        # build records null, not a made-up "unknown".
        got = _git_commit_at(HERE)
        if got:
            return got
        env = (os.environ.get("AUSMT_ENGINE_COMMIT") or "").strip()
        return env if env and env != "unknown" else None

    # The dimensionality decision boundary actually used in science_from_components. These values are
    # READ from the single source of truth (_edi_science constants + _ediparse.PT_MIN_REZ_ROW_SINE),
    # NOT re-typed here, so the recorded provenance cannot drift from the thresholds the science
    # actually applied:
    #   * skip periods whose Re(Z) rows are near-collinear (|det| < min_rez_row_sine*||r1||*||r2||);
    #   * if fewer than min_usable_period_frac of periods survive -> "indeterminate";
    #   * else 3-D if MEDIAN|beta| > skew_3d_deg OR > pct_periods_3d_threshold% have |beta| >
    #     beta_per_period_deg; else 2-D if median ellipticity > ellip_2d_deg; else 1-D.
    params = {"dimensionality": {"beta_per_period_deg": sci.BETA_PER_PERIOD_DEG,
                                 "skew_3d_deg": sci.SKEW_3D_DEG,
                                 "pct_periods_3d_threshold": sci.PCT_PERIODS_3D_THRESHOLD,
                                 "ellip_2d_deg": sci.ELLIP_2D_DEG,
                                 "min_rez_row_sine": ep.PT_MIN_REZ_ROW_SINE,
                                 "beta_physical_cap_deg": sci.BETA_PHYSICAL_CAP_DEG,
                                 "min_usable_period_frac": sci.MIN_USABLE_PERIOD_FRAC,
                                 "skew_aggregation": sci.SKEW_AGGREGATION},
              "diagnostic": "completeness/smoothness (median rel error + coverage + smoothness)"}
    return {"pipeline": "ausmt/extract.build_portal", "pipeline_version": _dist_version(),
            "extractor": "mt_metadata (community canonical)",  # the sole engine since the regex retirement
            # Named software carries its version (the mt_metadata Provenance rule: software.version
            # is required). lib_versions() is the C32 single source, so this can never drift from
            # the versions mtcat.json / build_provenance.json declare.
            "software": {"python": _pf.python_version(), **lib_versions()},
            "git_commit": _git_commit(),
            "parameters": params,
            "generated": _dt.datetime.now(_dt.timezone.utc).isoformat()}


# Small enough to enumerate in a log line / report entry. A distinct note carried by <= this many
# stations lists those stations; a note MISSING from <= this many (the outlier/CC07 case) lists the
# absentee complement instead. Above it on both sides, the count alone tells the story.
CONDITIONING_ENUM_LIMIT = 5


def aggregate_conditioning(notes_by_station: dict) -> list:
    """The SINGLE source of truth for both the survey-level conditioning NOTICE log (Deliverable 1) and
    build_report.json's `conditioning` field (Deliverable 2) — so the log an operator reads and the
    machine-readable report can never disagree.

    Input: {station_id: [ordered conditioning-note string, ...]} for the survey's CONDITIONED stations
    (a station absent from the map, or present with an empty list, carries no notes and is not counted).
    Output: one entry per DISTINCT note string, ordered by the note's FIRST appearance across stations
    (stations iterated in insertion order — the build inserts them in station order), each:

        {"note": <str>, "count": <int carriers>, "stations": [ids]|None, "except": [absentees]|None}

    where N = the number of note-carrying stations (the denominator). At most one of stations/except is
    non-null, and only when that side is small (<= CONDITIONING_ENUM_LIMIT):
      * carriers <= limit  -> stations = sorted carrier ids (the "few" case);
      * else absentees <= limit AND < carriers -> except = sorted absentee ids (the "all except X" case);
      * else both None -> the count alone (neither side is short enough to enumerate honestly).
    This is the design the ccmt-2017 outlier drove: a note on 27 of 28 stations records except=['CC07'],
    NOT a 27-id list, so the one meaningful curatorial signal is surfaced without the 27-line noise."""
    # carriers per distinct note, in first-appearance order; the full carrier universe = every station
    # that carried >= 1 note (the denominator N — a zero-note station never enters here).
    order: list = []
    carriers: dict = {}
    universe: list = []  # note-carrying station ids, in insertion order (for stable complements)
    for sid, notes in notes_by_station.items():
        if not notes:
            continue
        universe.append(sid)
        for n in notes:
            if n not in carriers:
                carriers[n] = []
                order.append(n)
            # a station may repeat a note within its own list; count it once per station
            if sid not in carriers[n]:
                carriers[n].append(sid)
    n_total = len(universe)
    entries = []
    for note in order:
        carrier_ids = carriers[note]
        count = len(carrier_ids)
        absentees = [s for s in universe if s not in set(carrier_ids)]
        stations = ex = None
        if count <= CONDITIONING_ENUM_LIMIT:
            stations = sorted(carrier_ids)
        elif absentees and len(absentees) <= CONDITIONING_ENUM_LIMIT and len(absentees) < count:
            # `absentees and`: a note carried by ALL stations has an EMPTY absentee list, which
            # passed the small-complement check and shipped except=[] — truthy in JS, so the first
            # production panel render (2026-07-08) showed "[all except: ]" on every fleet-wide note.
            # All-carriers => both sides None; count == the survey total tells the story.
            ex = sorted(absentees)
        entries.append({"note": note, "count": count,
                        "stations": stations, "except": ex,
                        # carried privately for the log renderer (dropped from the report), so the
                        # renderer never re-derives N: keep the two views bit-for-bit consistent.
                        "_n_total": n_total, "_n_absent": len(absentees)})
    return entries


def conditioning_log_lines(slug: str, notes_by_station: dict, prefix: str = "[xml]") -> list:
    """Render the per-survey conditioning NOTICE lines from the SHARED aggregation. One line per
    distinct note (never per station — that was the ~792-line noise), ordered by first appearance:

        all N     -> `  [xml] NOTICE <slug>: <note> — all <N> stations`
        most,      few absentees -> `... — <k>/<N> stations (all except <ids>)`
        most,      many absentees -> `... — <k>/<N> stations (<N-k> stations without it)`
        few/half  -> `... — <note> — stations: <ids>`  (the enumerated-carriers case)

    `prefix` tags the note family: "[xml]" (canonical conditioning, the default — existing tests
    pin that exact text) or "[frame]" (C25 frame/convention notes). Returns the lines (the caller
    prints them to stderr, where the old per-station NOTICEs went), so a test can assert the exact
    text. Empty input -> no lines."""
    lines = []
    for e in aggregate_conditioning(notes_by_station):
        n = e["_n_total"]
        count = e["count"]
        head = f"  {prefix} NOTICE {slug}: {e['note']}"
        if count == n:
            lines.append(f"{head} — all {n} stations")
        elif e["except"] is not None:  # small absentee complement enumerated by the shared fn
            lines.append(f"{head} — {count}/{n} stations (all except {', '.join(e['except'])})")
        elif e["stations"] is not None:  # small carrier set enumerated by the shared fn
            lines.append(f"{head} — stations: {', '.join(e['stations'])}")
        else:  # neither side short enough to list — report the majority/minority by count
            n_absent = e["_n_absent"]
            if count * 2 > n:  # a clear majority: frame it as "k/N (M without it)"
                lines.append(f"{head} — {count}/{n} stations ({n_absent} stations without it)")
            else:
                lines.append(f"{head} — {count}/{n} stations")
    return lines


def conditioning_report(notes_by_station: dict) -> list:
    """build_report.json's `conditioning` field: the SHARED aggregation with the private renderer hints
    (`_n_total` / `_n_absent`) dropped, so the report carries exactly {note, count, stations, except}."""
    return [{"note": e["note"], "count": e["count"],
             "stations": e["stations"], "except": e["except"]}
            for e in aggregate_conditioning(notes_by_station)]


def run_extraction_report(run_facts_by_station: dict) -> dict:
    """build_report.json's `run_extraction`: which >INFO dialect produced each station's acquisition
    values, and the extraction-confidence class behind every one of them.

    SCOPE:254-258 asks the curation layer to KEEP that provenance even where the public document does
    not display it, and station.json publishes the value alone, so this is where the class lives. A
    curator reading a rate cannot otherwise tell a structured_dialect value from one pattern-matched
    out of free text. Stations whose >INFO asserted nothing are omitted, so the map names exactly the
    records there is something to question."""
    return {sid: {"dialects": list(facts.get("dialects") or []),
                  "confidence": dict(sorted((facts.get("confidence") or {}).items()))}
            for sid, facts in sorted((run_facts_by_station or {}).items())
            if isinstance(facts, dict) and facts.get("confidence")}


def build_identity(surveys_root) -> dict:
    """C12: build.json — the build<->data handshake a served portal needs to trace itself back to the
    exact engine + surveys commits that produced it (flagged missing in the review). Deterministic
    aside from `generated` (an ISO UTC timestamp), so two builds of identical inputs differ only there.

    engine_commit  : short HEAD of THIS repo (ausmt/), via the same _git_commit_at helper _build_prov
                     uses (HERE = engine/extract/). U2: the engine image COPYs engine/ WITHOUT .git,
                     so git resolution ALWAYS yields None in a container build -- when that happens,
                     fall back to the AUSMT_ENGINE_COMMIT env var (baked in at image-build time by
                     deploy-images.yml's build-arg; see engine.Dockerfile). Precedence: real git
                     result first, env var second, the literal string "unknown" last (a genuinely
                     unresolvable build identity, e.g. a bare pip install with no .git and no env var --
                     still a valid string, never Python's None).
    source_commit  : short HEAD of the ausmt-surveys checkout at `surveys_root`, when that directory
                     sits inside a git work tree; None for --raw builds or a non-git --surveys dir (a
                     plain directory copy, or CI's PR-diff checkout of just a subtree) -- graceful, not
                     a hard error, since building without a resolvable surveys commit is legitimate.
                     (No env fallback for this one -- there is exactly one source repo per deployment
                     and it is always bind-mounted with its .git intact; see engine.Dockerfile.)
    build_id       : "<engine_commit>-<source_commit>-<generated>" — plain concatenation, opaque to
                     the portal (displayed verbatim, never parsed). U2: source_commit's None (the
                     legitimate no-surveys-commit case) renders as "unknown" IN THE JOIN ONLY, never
                     the Python str(None) "None" -- the live footer showed the literal
                     "None - None - <date>" on the first container deployment because the old
                     f-string folded None straight into the join.
    """
    import datetime as _dt
    engine_commit = _git_commit_at(HERE) or os.environ.get("AUSMT_ENGINE_COMMIT") or "unknown"
    source_commit = _git_commit_at(surveys_root) if surveys_root else None
    generated = _dt.datetime.now(_dt.timezone.utc).isoformat()
    # source_commit legitimately stays None (see docstring) -- render it "unknown" for the joined
    # opaque id ONLY, so a consumer checking `if doc["source_commit"]` still sees real None/falsy,
    # while build_id never carries the literal word "None".
    src_for_id = source_commit or "unknown"
    return {"build_id": f"{engine_commit}-{src_for_id}-{generated}",
            "engine_commit": engine_commit, "source_commit": source_commit, "generated": generated}


def emit_canonical_store(stations, slug, cdir, survey_meta=None):
    """ADDITIVE: write the canonical EMTF XML + a derived EDI for each station via the mt_metadata-backed
    `ausmt_science.ingest.normalize` (impedance round-trip verified). Returns (n_ok, n_fail, versions, notes)
    where notes is {station_id: [conditioning-note, ...]} for the stations that were conditioned (rotation
    unknown, source-id preservation, citation provenance) — the caller persists it (provenance.json map +
    stderr NOTICE). `survey_meta` (the survey SMETA) sources an HONEST citation (custodian org, not the
    portal). A per-station failure is logged and SKIPPED — this store is additive and must never break the
    product build. Keyed by the FINAL (post-disambiguation) station id `r["id"]` — the same key
    `_emit_served_xml` uses — so two EDIs that share a DATAID (the same-site-two-codes case `_disambiguate`
    exists for) write DISTINCT XML files instead of overwriting one, and `n_ok` cannot exceed the files
    actually written. The source EDI is read but never modified (it remains the citable artifact)."""
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415  (installed pkg; C37/F8)
    out = cdir / slug
    n_ok = n_fail = 0
    versions: dict = {}
    notes: dict = {}
    for (p, r) in stations:
        try:
            res = normalize(p, out, survey_id=slug, station_id=r["id"], survey_meta=survey_meta,
                            source_provenance=r.get("source_provenance"))
            versions = res.versions or versions
            if res.conditioned:
                notes[r["id"]] = res.conditioned
                # NOTE: the per-station NOTICE print was retired — the survey-level aggregation in
                # main() (aggregate_conditioning) now emits ONE line per distinct note instead of one
                # near-identical line per station (the ~792-line survey-boilerplate noise). The notes
                # are still returned here and persisted per-station (provenance.json + station.json).
            n_ok += 1
        except Exception as ex:  # noqa: BLE001
            n_fail += 1
            print(f"  [canonical] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
    return n_ok, n_fail, versions, notes


def _derived_edi_filename(station_id, taken):
    """The filename a GENERATED EDI is served under inside a survey's out/edi/<slug>/ directory.

    That one directory carries TWO naming schemes at once: a custodian EDI keeps its own submitted
    filename (it is the citable artifact, so it is copied byte for byte under the name it arrived
    with), and an EMTF-XML-sourced station has no custodian file, so its generated EDI is named for
    the station. The two schemes are NOT disjoint. An EDI's filename need not equal its DATAID -- the
    build derives the station id from DATAID, not from the name -- so a custodian file called B.edi
    can carry station A while station B arrives as EMTF XML and generates its own B.edi. Left
    unhandled that is a silent swap, not a crash: one file on disk, two manifest rows naming it, both
    sha256 columns verifying against the same bytes, and station B's advertised download handing back
    station A's transfer function.

    `taken` is the case-folded set of names already spoken for (custodian filenames first, then each
    generated name as it is allocated); the served tree is read from case-insensitive filesystems too,
    so the fold is part of the guarantee. The generated file steps aside rather than overwrite or be
    overwritten. Deterministic: the suffix is a function of the survey's own input file set alone, so
    the same package always produces the same served filename."""
    cand = f"{station_id}.edi"
    n = 0
    while cand.lower() in taken:
        n += 1
        cand = f"{station_id}.generated.edi" if n == 1 else f"{station_id}.generated-{n}.edi"
    return cand


# mt_metadata's own "no date asserted" header value; it omits the INFO original_file.date line for it.
_EDI_NULL_DATE = b"1980-01-01T00:00:00+00:00"
_EDI_FILEDATE_RE = _re.compile(rb"(?m)^([ \t]*FILEDATE[ \t]*=[ \t]*).*$")
_EDI_SOURCE_DATE_RES = (_re.compile(rb"(?m)^[ \t]*original_file\.date[ \t]*=[ \t]*(\S.*?)[ \t]*$"),
                        _re.compile(rb"(?m)^[ \t]*provenance\.creation_time[ \t]*=[ \t]*(\S.*?)[ \t]*$"))


def _reproducible_derived_edi(raw: bytes) -> bytes:
    """The bytes a GENERATED EDI is SERVED as: mt_metadata's output with its one wall-clock field
    carrying the date the source document declared instead of the minute this build ran.

    The download manifest's reference states that the served EDI and the per-survey EDI zip are
    byte-reproducible across builds, so their SHA-256 is a stable cross-build invariant, unlike the
    EMTF XML and the MTH5 which embed timestamps and UUIDs. A custodian EDI satisfies that for free
    because it is copied. A generated EDI is WRITTEN, and mt_metadata's header writer assigns
    FILEDATE = now at write time with no knob to pass it (Header.write_header), so an untouched
    generated file would publish a new digest for its station AND for its survey's whole EDI zip on
    every rebuild of an unchanged package. That is the same class of build-clock leak the zip writers
    already spend effort on (a pinned member timestamp) and _license_text avoids (no timestamp in the
    instrument text), for the same reason: a citable download whose digest churns cannot be checked
    against a previously published one.

    The value stamped in is not invented. It is the filedate mt_metadata itself carried in from the
    source, which it writes into the INFO block as original_file.date BEFORE the header writer
    overwrites it, and which for an EMTF-XML source is that document's own CreateTime. So the served
    file dates the transfer function it renders, and re-reading it yields the same
    provenance.creation_time the source asserts rather than a build clock. Falls back to the INFO
    provenance.creation_time, then to mt_metadata's null date (the value whose presence makes it drop
    original_file.date altogether); every branch is a function of the source bytes alone.

    Byte-level on purpose: this runs on a file the round-trip gate has already passed, so it must not
    re-serialise anything. A file with no FILEDATE line is returned unchanged (nothing to pin)."""
    src_date = None
    for rx in _EDI_SOURCE_DATE_RES:
        m = rx.search(raw)
        if m:
            src_date = m.group(1)
            break
    if src_date is None:
        src_date = _EDI_NULL_DATE
    return _EDI_FILEDATE_RE.sub(lambda mm: mm.group(1) + src_date, raw, count=1)


def _claim_served_artifact(claims, collisions, served: Path, ausmt_id, fmt):
    """Register ONE station's claim on ONE served file, and record a collision if the file was already
    claimed. `claims` maps a resolved served path to the row that owns it; `collisions` collects the
    contradictions for the build gate.

    Two manifest rows describing the same bytes as two different stations' downloads is an integrity
    contradiction that the sha256 columns cannot surface -- BOTH rows verify, because both really do
    hash the file they name. The gate is the only place it can be caught, so it is a corpus-wide
    invariant checked over every per-station artifact (EDI, EMTF XML and MTH5 alike) rather than a
    guard bolted onto the one naming scheme that broke it."""
    key = str(Path(served).resolve())
    prev = claims.get(key)
    if prev is not None:
        collisions.append({"path": key, "first": prev,
                           "second": {"ausmt_id": ausmt_id, "format": fmt}})
        return
    claims[key] = {"ausmt_id": ausmt_id, "format": fmt}


def _emit_served_xml(stations, slug, xmldir, survey_meta=None, cache=None, survey_digest="",
                     coord_default="exact", coord_overrides=None, derived_edi_dir=None,
                     reserved_edi_names=()):
    """Write the canonical EMTF XML for each station into the PORTAL data dir (xmldir = out/xml/<slug>)
    so EMTF XML is a downloadable format alongside the bundled EDI. Same normalize() path + impedance
    round-trip gate as the canonical store; a per-station failure is logged and SKIPPED, and what that
    station still serves afterwards depends on its SOURCE format (see `derived_edi_dir` below and the
    except arm, which is where that consequence is stated). Keyed by the station's FINAL r["id"]
    (post-disambiguation) so the XML filename matches the manifest/catalogue id. `survey_meta` (the
    survey SMETA) sources an HONEST citation (custodian org, not the portal brand). Engine-guarded by
    the caller (mt_metadata is a core build dep). Returns (written, notes, stamped, failures,
    derived_edis): written={station_id: xml_path},
    notes={station_id:[note,...]} for conditioned stations (rotation unknown / source-id preserved /
    citation provenance) — the caller persists notes into that station's station.json
    (canonical_conditioning) and emits a NOTICE; failures={station_id: exception-class-name} for every
    station whose XML emission RAISED (logged and skipped), so the caller can surface the gap in
    build_report.json instead of it vanishing into a printed WARN; derived_edis={station_id: generated-EDI
    path} for the XML-sourced stations whose served EDI this call produced (empty unless
    `derived_edi_dir` is given); and stamped={station_id: survey_digest} recording,
    per served station, the survey.yaml digest the served XML was KEYED/PRODUCED under (C18b,
    Amendment A3). On the FRESH path that is the digest this call was invoked with; on a cache HIT it is
    the digest carried in the entry's own meta blob (a stale entry surfaces its stale digest here). The
    caller writes stamped into the out/products/survey_digests.json sidecar the verify.py consistency
    gate compares against the LIVE survey.yaml, so a product served under a stale digest is caught.

    C18 (~27% of a cold build - the 2026-08-27 full-corpus profile corrected the old '~84%' claim,
    which described a build without --station-h5/--survey-h5; the MTH5 writers dominate the
    production shape at ~68%, and a warm rebuild is ~99% MTH5 precisely because THIS cache
    covers parse+XML and not MTH5. See AusMT_2026/BUILD-PERF-PROFILE-2026-08-27.md):
    when `cache` is an ENABLED BuildCache, the normalize()
    round-trip is cached per station by source-EDI sha + salt. A HIT writes the cached XML BYTES
    verbatim to <xmldir>/<station>.xml (the exact bytes normalize() produced on the miss build) and
    returns the cached conditioning notes — skipping the round-trip entirely. The served XML a hit
    writes is byte-identical to what a fresh normalize() writes (the round-trip QC gate already ran on
    the miss build that populated it); verify.py re-hashes these bytes cache-blind regardless.

    `derived_edi_dir` (the EMTF-XML ingest path, owner ruling 2026-08-03): normalize() always writes a
    round-trip-verified derived EDI beside the canonical XML. For an EDI-sourced station that file is
    redundant (the custodian's own EDI is served) and is deleted, exactly as before. For a station
    whose SOURCE is an EMTF XML there is no custodian EDI, so (when this dir is given) the derived
    EDI is KEPT and moved into <derived_edi_dir> under a name allocated by _derived_edi_filename, and
    returned in `derived_edis`; that is the "generated EDI where mt_metadata supports the write" half
    of serving the full product set from an XML-only station. `reserved_edi_names` is every custodian
    EDI basename this survey could serve, so a generated file never lands on one (see
    _derived_edi_filename for why that is a silent swap rather than a crash). The cache is BYPASSED for
    those stations (a hit would restore the XML bytes but not the generated EDI, silently serving one
    format instead of two), so the XML ingest path is always a fresh, gated normalize(), the same
    posture the MTH5 input path takes."""
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415  (installed pkg; C37/F8)
    written = {}
    notes = {}
    stamped = {}   # C18b (A3): {station_id: survey_digest the served XML was keyed/produced under}
    failures = {}  # {station_id: exception-class-name} for stations whose XML emission RAISED (skipped)
    derived_edis = {}  # {station_id: generated-EDI path} for XML-sourced stations (see derived_edi_dir)
    # The served-EDI filename namespace for THIS survey: custodian basenames reserved up front, then
    # each generated name as it is allocated. Case-folded (the served tree is read from
    # case-insensitive filesystems too).
    _taken_edi_names = {str(_n).lower() for _n in (reserved_edi_names or ())}
    _use_cache = cache is not None and getattr(cache, "enabled", False)
    for (p, r) in stations:
        # C42 byte gate: a non-exact (generalised/withheld) station's EMTF-XML — a full elevation +
        # coordinate bearer (HEAD/INFO/DEFINEMEAS carried through by normalize()) — is NOT served. Skip
        # it here so it is absent from out/xml, the xml zip and the manifest (all derive from `written`).
        # r.get("variant") rides along (fix round 2): a variant record inherits its BASE id's policy.
        if not coordacc.coordinates_served(
                coordacc.station_policy(coord_default, coord_overrides, r.get("id"), r.get("variant"))):
            continue
        xml_target = Path(xmldir) / f"{r['id']}.xml"
        # The XML content AND filename are a function of the FINAL (post-_disambiguate) station id —
        # normalize() writes station_id into the Site.id / geographic-name and the <stem>.xml path. The
        # disambiguated id depends on the survey's EDI SET (two EDIs sharing a DATAID -> X.a / X.b),
        # which is NOT captured by the survey.yaml digest, so BIND r["id"] into the key namespace.
        # Otherwise removing a colliding sibling EDI could serve a hit whose internal id is stale.
        # A station whose source is NOT an EDI must ALSO emit a generated EDI (derived_edi_dir), and
        # the cache carries only the XML blob + meta, so bypass it there rather than serve a
        # half-product set off a hit. EDI-sourced stations keep the C18 behaviour byte-for-byte.
        _src_is_edi = Path(p).suffix.lower() == ".edi"
        _keep_derived = (derived_edi_dir is not None) and not _src_is_edi
        _ck = cache.key(edi_sha=sha256(p), survey_digest=survey_digest,
                        kind=f"xml:{r['id']}") if (_use_cache and not _keep_derived) else None
        if _ck:
            _cached_xml = cache.get_bytes(_ck, "xml")
            if _cached_xml is not None:
                _cached_meta = cache.get_json(_ck, "meta")
                if _cached_meta is None:
                    # TORN pair (A1b/c): the xml blob hit its checksum but the meta sibling is
                    # absent/corrupt, so the pair produced NOTHING usable — revoke the phantom xml
                    # hit (get_json already tallied its own miss/corrupt) and fall through to a
                    # fresh normalize, which re-puts BOTH blobs. Without the revoke, a torn pair
                    # over-counted hits (the review's phantom-hit finding).
                    cache.revoke_hit()
                else:
                    xml_target.parent.mkdir(parents=True, exist_ok=True)
                    xml_target.write_bytes(_cached_xml)
                    written[r["id"]] = xml_target
                    # C18b (A3): stamp the digest the CACHED entry was written under. The v3 meta blob
                    # always carries survey_digest; an entry WITHOUT one reads as a SENTINEL that can
                    # never equal a live digest, so the verify gate goes RED — never as this call's
                    # digest, which would bless exactly the unprovable state the gate exists to catch.
                    stamped[r["id"]] = _cached_meta.get("survey_digest") or "unstamped-cache-entry"
                    _cnotes = _cached_meta.get("conditioned") or []
                    if _cnotes:
                        notes[r["id"]] = _cnotes
                        # per-station NOTICE retired: the survey-level aggregation in main() emits one
                        # line per distinct note (see aggregate_conditioning). Notes still returned +
                        # persisted per-station; a warm (cache-hit) build reports identically to a cold one.
                    continue
        try:
            res = normalize(p, xmldir, survey_id=slug, station_id=r["id"], survey_meta=survey_meta,
                            source_provenance=r.get("source_provenance"))
            written[r["id"]] = res.canonical_xml
            # C18b (A3): the FRESH path is keyed under THIS call's survey_digest — stamp it directly.
            stamped[r["id"]] = survey_digest
            if res.conditioned:
                notes[r["id"]] = res.conditioned
                # per-station NOTICE retired -> survey-level aggregation in main() (aggregate_conditioning).
            # normalize() also writes a round-trip derived .edi beside the .xml. For an EDI-sourced
            # station the custodian's own EDI is what gets served, so the derived copy is dropped to
            # keep out/xml/ to manifested artifacts. For an EMTF-XML-sourced station it IS the served
            # EDI (there is no custodian EDI), so it is moved into the survey's edi/ dir instead.
            if _keep_derived:
                try:
                    # Named against the survey's WHOLE served-EDI namespace, custodian filenames
                    # included, so a generated file can never overwrite (or be overwritten by) the
                    # custodian bytes of a different station -- see _derived_edi_filename.
                    _dname = _derived_edi_filename(r["id"], _taken_edi_names)
                    _taken_edi_names.add(_dname.lower())
                    _dest = Path(derived_edi_dir) / _dname
                    _dest.parent.mkdir(parents=True, exist_ok=True)
                    # Served through _reproducible_derived_edi: mt_metadata stamps FILEDATE with the
                    # write-time clock, and a served EDI (and the survey EDI zip it lands in) is
                    # documented as byte-reproducible across builds.
                    _dest.write_bytes(_reproducible_derived_edi(Path(res.derived_edi).read_bytes()))
                    Path(res.derived_edi).unlink(missing_ok=True)
                    derived_edis[r["id"]] = _dest
                except OSError as _de:
                    # The XML still serves; only the generated-EDI convenience rendition is missing.
                    print(f"  [edi] WARN {p.name}: generated EDI not written ({type(_de).__name__}: "
                          f"{str(_de)[:80]}); this station serves EMTF XML only", file=sys.stderr)
            else:
                try:
                    Path(res.derived_edi).unlink(missing_ok=True)
                except OSError:
                    pass
            if _ck:   # populate the cache with the EXACT served bytes + notes for the next warm build.
                # C18b (A3): the meta blob carries survey_digest (the digest this entry was keyed under)
                # so a future cache HIT can propagate it to the sidecar — surfacing a stale entry's
                # digest to the verify.py consistency gate. The v3 tag bump keys this new-shape meta.
                cache.put_bytes(_ck, "xml", Path(res.canonical_xml).read_bytes())
                cache.put_json(_ck, {"conditioned": res.conditioned, "survey_digest": survey_digest},
                               ext="meta")
        except Exception as ex:  # noqa: BLE001
            # Record the failure (station id + exception class) so the caller can COUNT it into
            # build_report.json; a per-station XML gap must never again be invisible in a green build,
            # only a printed WARN. What the station still serves depends on its SOURCE (see the
            # _keep_derived branch below), so this arm states no consequence of its own.
            failures[r["id"]] = type(ex).__name__
            print(f"  [xml] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
            # normalize() writes the canonical XML and the derived EDI BEFORE its round-trip gate
            # runs, so a gate FAILURE leaves both of them sitting in xmldir -- inside the served data
            # tree, which the file server hands out by path with no manifest row required to reach it
            # (deploy's Caddyfile serves the whole tree, and api-reference documents
            # /data/xml/<slug>/<station>.xml as the public URL). An unverified rendition must not be
            # fetchable at the URL this build reports as NOT served, so remove both. Best effort: a
            # file that will not delete is named loudly rather than left silently reachable.
            for _stale in (xml_target, Path(xmldir) / f"{r['id']}.edi"):
                try:
                    _stale.unlink(missing_ok=True)
                except OSError as _ue:
                    print(f"  [xml] WARN {r['id']}: could NOT remove the unverified {_stale.name} "
                          f"({type(_ue).__name__}); it is unmanifested but still on disk",
                          file=sys.stderr)
            if _keep_derived:
                # An XML-sourced station whose canonical emission RAISED (the round-trip gate, or a
                # write mt_metadata refuses) has NO custodian EDI to fall back on, so it serves NO
                # bytes at all. Say so loudly here as well as in build_report's xml_failures: the
                # EDI-sourced wording ("served as EDI-only") would be false for this station.
                print(f"  [xml] {r['id']}: EMTF-XML-sourced station FAILED the canonical round-trip "
                      f"gate; NO bytes are served for it (no XML, no generated EDI).", file=sys.stderr)
    return written, notes, stamped, failures, derived_edis


def _emit_survey_edi_zip(served_edis, slug, out, license_txt=None):
    """Pre-build a per-survey EDI zip (out/bundles/<slug>-edi.zip) from the already-served EDI copies, so
    'download the whole survey' is one cacheable static file instead of on-the-fly browser zipping.
    Reproducible bytes => stable sha256: sorted entries + fixed mtime + fixed mode + fixed compression
    AND a pinned create_system (Python's ZipInfo otherwise stamps the host OS byte — 0 on Windows, 3 on
    Unix — so an identical survey would hash differently across a Windows build vs Linux CI). Cross-build
    reproducibility additionally assumes a fixed zlib build (DEFLATE output can vary across zlib versions).
    C6: `license_txt` (a deterministic string from license_instrument_text) is written as LICENSE.txt so the
    rights travel INSIDE the archive; it uses the SAME fixed ZipInfo convention (no timestamp in the text
    either), so the zip stays byte-reproducible. LICENSE.txt is written first at a fixed name so entry order
    is deterministic regardless of EDI basenames.
    Returns (rel_url, zip_path) or (None, None) when there is nothing to bundle."""
    import zipfile  # noqa: PLC0415
    paths = sorted({Path(p) for p in served_edis}, key=lambda p: p.name)
    if not paths:
        return None, None
    bdir = out / "bundles"; bdir.mkdir(parents=True, exist_ok=True)
    zpath = bdir / f"{slug}-edi.zip"

    def _zi(name):
        zi = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))  # fixed => reproducible
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        zi.create_system = 3  # pin to Unix so the OS byte is identical on Windows and Linux builds
        return zi

    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if license_txt:  # rights travel with the bytes (C6) — deterministic content + fixed ZipInfo
            z.writestr(_zi("LICENSE.txt"), license_txt.encode("utf-8"))
        for p in paths:
            z.writestr(_zi(p.name), p.read_bytes())
    return f"bundles/{slug}-edi.zip", zpath


def _emit_survey_xml_zip(xml_paths, slug, out, license_txt=None):
    """C32 §1.1: pre-build a per-survey EMTF-XML zip (out/bundles/<slug>-xml.zip) from the survey's
    already-emitted canonical EMTF-XMLs — the exact byte-reproducible convention as _emit_survey_edi_zip
    (sorted entries + fixed date_time/mode + pinned create_system + LICENSE.txt first). Those XMLs exist
    ONLY for round-trip-verified stations by construction (_emit_served_xml skips any that fail), so this
    bundles precisely the served XML set and nothing else. Same C6 LICENSE.txt travels inside the archive.
    Returns (rel_url, zip_path) or (None, None) when there is nothing to bundle (no served XML)."""
    import zipfile  # noqa: PLC0415
    paths = sorted({Path(p) for p in xml_paths if Path(p).exists()}, key=lambda p: p.name)
    if not paths:
        return None, None
    bdir = out / "bundles"; bdir.mkdir(parents=True, exist_ok=True)
    zpath = bdir / f"{slug}-xml.zip"

    def _zi(name):
        zi = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))  # fixed => reproducible
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        zi.create_system = 3  # pin to Unix so the OS byte is identical on Windows and Linux builds
        return zi

    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        if license_txt:  # rights travel with the bytes (C6) — same treatment as the EDI zip
            z.writestr(_zi("LICENSE.txt"), license_txt.encode("utf-8"))
        for p in paths:
            z.writestr(_zi(p.name), p.read_bytes())
    return f"bundles/{slug}-xml.zip", zpath


def _sanitise_station_id(raw_id: str) -> str:
    """mt_metadata's Site.id is alphanumeric-only; a disambiguated id like 'MBV20.lemigraph' would be
    rejected and the station silently dropped (SPEC §3.2 / caveat 5). Strip to alnum so it is kept. The
    survey and collection producers MUST share this one rule so their station ids never diverge."""
    return _re.sub(r"[^A-Za-z0-9]", "", str(raw_id)) or str(raw_id)


def _mth5_doi_url(d):
    """Normalise a DOI to the https://doi.org/… URL mt_metadata's citation_*.doi (a pydantic HttpUrl)
    accepts. A bare '10.1234/x' would be REJECTED and the injection silently lost, so bare/doi:-prefixed
    forms are lifted to a resolvable URL; an already-http value passes through; junk returns None."""
    if not d:
        return None
    s = str(d).strip()
    if s.lower().startswith(("http://", "https://")):
        return s
    if s.lower().startswith("doi:"):
        s = s[4:].strip()
    if s.startswith("10."):
        return "https://doi.org/" + s
    return None


def _mth5_project_lead(smeta: dict):
    """The lead-most credited party for mth5 survey_metadata.project_lead (CONTRIBUTOR-CREDIT-SPEC): the
    first contributor whose role is ProjectLeader, else the lead-most creator (creators[0], the citation
    lead). Returns {name, orcid} or None. A1 retires the third rung: the back-compat facet built from the
    retired flat credit keys no longer exists, so a survey with neither a ProjectLeader nor creators has
    no project_lead rather than one recovered from a retired key. A project_lead may be a person or an
    organisation (name_type is not consulted); only a person carries an ORCID, so an org lead yields no
    url downstream."""
    for c in (smeta.get("contributors") or []):
        if isinstance(c, dict) and c.get("name") and str(c.get("role") or "").strip() == "ProjectLeader":
            return {"name": c["name"], "orcid": c.get("orcid")}
    for c in (smeta.get("creators") or []):
        if isinstance(c, dict) and c.get("name"):
            return {"name": c["name"], "orcid": c.get("orcid")}
    return None


def _apply_mth5_survey_metadata(sm, smeta, slug, label):
    """Map survey.yaml/SMETA scholarly + identifier fields onto an mth5 TF's survey_metadata at write
    time (SPEC §3.3 mapping table, A5 ruling). The grouping key id=slug ALWAYS overrides the raw EDI
    '0' so stations do not collapse into one survey group. The DATASET DOI is INJECTED because it is the
    one scholarly field genuinely absent from every EDI (raw AND enriched read citation_dataset.doi=None,
    SPEC §9.1); the journal citation is single-sourced from SMETA too (belt-and-braces, it also survives
    the enriched-EDI round-trip). Every set is best-effort: mt_metadata 1.0.9 rejects some hand-authored
    values (unit strings, unknown attributes — SPEC caveat 7), so a field that will not coerce is skipped
    with NO effect on the TF payload (the §6 round-trip stays lossless). smeta None => only the slug is
    seeded (raw/CSV-only surveys build metadata-thin but valid, SPEC caveat 2)."""
    def _set(path, value):
        if value in (None, "", []):
            return
        try:
            obj = sm
            *parents, leaf = path.split(".")
            for pnm in parents:
                obj = getattr(obj, pnm)
            setattr(obj, leaf, value)
        except Exception as ex:  # noqa: BLE001  (a rejected hand-authored value must not touch the payload)
            print(f"  [h5] note {slug} survey_metadata.{path}: {type(ex).__name__}: {str(ex)[:80]}",
                  file=sys.stderr)
    sm.id = slug   # the grouping key — always seeded, even without SMETA
    if not smeta:
        return
    _cite = smeta.get("cite") or {}
    _name = _cite.get("ti") or label
    _set("name", _name)
    _set("project", _name)
    _set("summary", smeta.get("blurb"))
    # A5: the one genuinely-absent scholarly field. Inject the dataset DOI from SMETA (survey.yaml).
    _set("citation_dataset.doi", _mth5_doi_url(smeta.get("doi")))
    # Journal citation: single-source from the first publication (SMETA), best-effort.
    _pubs = smeta.get("pubs") or []
    if _pubs:
        _p0 = _pubs[0] or {}
        _set("citation_journal.doi", _mth5_doi_url(_p0.get("doi")))
        _set("citation_journal.title", _p0.get("t"))
        _set("citation_journal.journal", _p0.get("j"))
        _set("citation_journal.year", str(_p0.get("y")) if _p0.get("y") not in (None, "") else None)
    _set("acquired_by.organization", smeta.get("org"))
    _set("release_license", smeta.get("lic"))
    # CONTRIBUTOR-CREDIT-SPEC: project_lead is the lead-most credited party (a ProjectLeader contributor,
    # else the lead creator, else the legacy investigator). Its ORCID goes into project_lead.url as a full
    # https://orcid.org/<id> URL - the AuthorPerson model has no serialised `id` field, so the URL is the
    # field that actually survives the write; a non-person/ORCID-less lead simply gets no url (no fabrication).
    _lead = _mth5_project_lead(smeta)
    if _lead:
        _set("project_lead.author", _lead.get("name"))
        _set("project_lead.url", _orcid_url(_lead.get("orcid")))
    _fund = smeta.get("funders") or []
    if _fund:
        _f0 = _fund[0] or {}
        _set("funding_source.organization", _f0.get("name") if isinstance(_f0, dict) else _f0)
        if isinstance(_f0, dict):
            _set("funding_source.grant_id", _f0.get("grant_id") or _f0.get("id"))


def _tensor_max_abs_diff(a, b):
    """Max absolute element diff between two impedance/tipper tensors (xarray DataArrays or arrays),
    NaN-aware. Returns None on a SHAPE mismatch and inf on a NaN-pattern mismatch (both hard fails for
    the §6 gate); a 0.0 means the storage round-trip was lossless (the measured Tumby result)."""
    import numpy as np  # noqa: PLC0415
    av = np.asarray(getattr(a, "values", a))
    bv = np.asarray(getattr(b, "values", b))
    if av.shape != bv.shape:
        return None
    if not np.array_equal(np.isnan(av), np.isnan(bv)):
        return float("inf")   # a value present in one and NaN in the other is a mismatch, not 0
    diff = np.abs(av - bv)
    return float(np.nanmax(diff)) if diff.size else 0.0


def _release_mth5_metadata_classes() -> None:
    """Emit-and-release for the MTH5 arm. Called after EVERY station-sized unit of MTH5 work (each
    add_transfer_function in the writers, each get_transfer_function in the round-trip gate).

    WHY (measured, 2026-08-15, the P350 OOM incident: 5 kernel kills at anon-rss 13.7 GB on a 14 GB box
    at ~2,580 stations). The build was not holding the corpus. On the pinned stack every mth5 0.6.8
    group/dataset instantiation calls add_attributes_to_metadata_class_pydantic, which builds a FRESH
    pydantic model class via create_model (about 75 classes per served station across the tier-1
    file, the tier-2 bundle and the gate's reopen), and mt_metadata 1.0.9's to_dict then memoises each
    class's field tree in the module-global, class-KEYED dict
    mt_metadata.base.pydantic_helpers._FIELDS_TREE_CACHE. A class-keyed memo of classes that are never
    reused can never hit; it only pins every class, its ~300 KB json tree and its pydantic-core
    validator/serializer for the life of the process. Profiled at 7.6 MiB per served station, linear
    and unbounded, 78% of the peak footprint, all of it inside _write_tf_mth5; parsing, the C18 cache,
    the XML arm, the zips and the corpus-wide emissions are flat.

    The library's own clear_field_caches() empties that memo; the classes then have no owner and the
    ordinary cyclic GC frees them. Cost: the next lookup of a STATIC class re-reads its tree from
    mt_metadata's on-disk cache (the same source the memo was filled from), so the served bytes cannot
    change; measured full-corpus build time did not rise. Guarded so a future mt_metadata without the
    helper degrades to the old behaviour rather than failing the build (the memory regression pin in
    tests/test_build_memory.py would then go RED, which is the right way to learn about it).

    CONCURRENCY (for the survey-parallel build lane): this clears a PROCESS-GLOBAL memo. On the pinned
    mt_metadata 1.0.9 its RLock is held from the cycle-breaking sentinel write through the final store
    (get_all_fields_serializable's whole body is one `with _CACHE_LOCK`), so a clear from another
    thread cannot split a computation; but with THREAD workers one worker's release evicts what
    another is about to look up again, and the per-unit bound this gives is per process, not per
    thread. Worker PROCESSES each own their memo and keep the bound; that lane should use processes."""
    try:
        from mt_metadata.base.pydantic_helpers import clear_field_caches  # noqa: PLC0415
    except Exception:  # noqa: BLE001  (a different mt_metadata layout: no memo to release)
        return
    clear_field_caches()


def mth5_survey_roundtrip_ok(hpath, stations, *, z_tol=1e-6, coord_tol=1e-6):
    """SPEC §6 BLOCKING gate. Reopen a built survey MTH5 and compare every stored TF's impedance tensor
    (and tipper) + coordinates to a FRESH parse of its source EDI, exact-or-tolerance. Also asserts the
    payload is TF-ONLY (transfer-function groups present, no time-series samples — a TF's placeholder
    channels carry n_samples<=1; real time series would be far larger). Returns (ok: bool, report: dict).
    The caller WITHHOLDS the survey h5 on ok=False (the survey, not the corpus — the CP3B21-at-survey
    -scope pattern), so a silently-wrong TF is never shipped. Never raises: an unexpected failure returns
    ok=False with the reason recorded, matching the producer's withhold-not-crash contract."""
    from mth5.mth5 import MTH5  # noqa: PLC0415
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    # Key each source EDI by (survey, sanitised-station-id). A collection file holds the SAME station id
    # under different survey groups (that non-collision is the whole point of tier 3), so a survey-agnostic
    # key would compare a station against the wrong survey's EDI. `_survey` is tagged by the collection
    # producer; the survey producer omits it and matches via the (None, sid) fallback below.
    by_key = {}
    for (p, r) in stations:
        sid = _sanitise_station_id(r["id"])
        by_key[(r.get("_survey"), sid)] = p
        by_key.setdefault((None, sid), p)   # survey-agnostic fallback (single-survey files, unique sids)
    report = {"checked": 0, "z_max_abs_diff": 0.0, "coord_max_abs_diff": 0.0,
              "tf_only": True, "mismatches": []}
    try:
        m = MTH5()
        m.open_mth5(str(hpath), mode="r")
    except Exception as ex:  # noqa: BLE001
        report["mismatches"].append({"station": "*", "reason": f"reopen failed: {type(ex).__name__}"})
        try:
            m.close_mth5()
        except Exception:  # noqa: BLE001, S110  (best-effort on a handle that may never have opened)
            pass
        return False, report
    try:
        tfs = m.tf_summary.to_dataframe()
        # TF-only payload gate (SPEC §6): a TF write leaves placeholder channels (n_samples==1); any
        # channel carrying real samples means the file is not TF-only and the honest label is falsified.
        try:
            cs = m.channel_summary.to_dataframe()
            _max_samples = int(cs["n_samples"].max()) if len(cs) and "n_samples" in cs.columns else 0
        except Exception:  # noqa: BLE001
            _max_samples = 0
        if _max_samples > 1:
            report["tf_only"] = False
            report["mismatches"].append({"station": "*",
                                         "reason": f"time-series samples present (n_samples={_max_samples})"})
        for _, row in tfs.iterrows():
            # Release the PREVIOUS station's dynamically created metadata classes before reading the
            # next one, so a 764-station bundle's gate runs flat instead of holding every reopened TF's
            # class tree until the file closes (see _release_mth5_metadata_classes).
            _release_mth5_metadata_classes()
            sid = row["station"]
            src = by_key.get((row.get("survey"), sid)) or by_key.get((None, sid))
            if src is None:
                report["mismatches"].append({"station": sid, "reason": "no source EDI mapped"})
                continue
            tf_h5 = m.get_transfer_function(sid, row.get("tf_id", sid), survey=row.get("survey"))
            tf_ed = TF(fn=str(src)); tf_ed.read()
            report["checked"] += 1
            for a, b in ((tf_ed.latitude, tf_h5.latitude), (tf_ed.longitude, tf_h5.longitude),
                         (tf_ed.elevation, tf_h5.elevation)):
                if a is None or b is None:
                    if (a is None) != (b is None):
                        report["mismatches"].append({"station": sid, "reason": "coordinate presence differs"})
                    continue
                d = abs(float(a) - float(b))
                report["coord_max_abs_diff"] = max(report["coord_max_abs_diff"], d)
                if d > coord_tol:
                    report["mismatches"].append({"station": sid, "reason": f"coord diff {d:.3g} > {coord_tol}"})
            for kind, present, ea, ha in (("impedance", tf_ed.has_impedance(),
                                           lambda: tf_ed.impedance, lambda: tf_h5.impedance),
                                          ("tipper", tf_ed.has_tipper(),
                                           lambda: tf_ed.tipper, lambda: tf_h5.tipper)):
                h5_present = tf_h5.has_impedance() if kind == "impedance" else tf_h5.has_tipper()
                if bool(present) != bool(h5_present):
                    report["mismatches"].append({"station": sid, "reason": f"{kind} presence differs"})
                    continue
                if not present:
                    continue
                d = _tensor_max_abs_diff(ea(), ha())
                if d is None:
                    report["mismatches"].append({"station": sid, "reason": f"{kind} shape differs"})
                elif kind == "impedance":
                    report["z_max_abs_diff"] = max(report["z_max_abs_diff"], d)
                    if d > z_tol:
                        report["mismatches"].append({"station": sid, "reason": f"impedance diff {d:.3g} > {z_tol}"})
                elif d > z_tol:
                    report["mismatches"].append({"station": sid, "reason": f"tipper diff {d:.3g} > {z_tol}"})
    except Exception as ex:  # noqa: BLE001  (gate never crashes the build; a failure withholds the survey)
        report["mismatches"].append({"station": "*", "reason": f"{type(ex).__name__}: {str(ex)[:80]}"})
    finally:
        # Guarded: this function promises never-raises, and an HDF5 close failure escaping a finally
        # would abort the whole corpus build from inside the withhold-not-crash gate.
        try:
            m.close_mth5()
        except Exception as ex:  # noqa: BLE001
            report["mismatches"].append({"station": "*", "reason": f"close failed: {type(ex).__name__}"})
        _release_mth5_metadata_classes()   # the last station's classes + the reopen's own group classes
    ok = report["tf_only"] and not report["mismatches"]
    return ok, report


def _write_tf_mth5(stations, slug, label, hpath, smeta=None):
    """THE MTH5 writer. Both served tiers go through this one function: the tier-2 survey bundle
    (emit_survey_mth5, every station in one file) and the tier-1 per-station files (emit_station_mth5,
    one station per file). Sharing it is the design, not a tidy-up: the station-id sanitisation, the
    survey.yaml -> survey_metadata mapping with the injected dataset DOI (SPEC §3.3 / A5), the
    withhold-not-crash posture and the SPEC §6 round-trip gate are then INHERITED by tier 1 rather than
    written a second time, so there is no second place for any of them to be got wrong. The two
    remaining differences are the caller's business: which stations it hands over, and where the file
    goes.

    Every station is grouped under one named survey (survey_metadata.id = slug) so a station never
    collapses into the raw EDI's survey '0'. A per-station TF write failure is logged (WARN) and
    SKIPPED, never a build failure. Before returning, the file passes the SPEC §6 round-trip gate
    (reopen, compare each stored TF's impedance/tipper + coordinates to a fresh parse of its source EDI,
    assert the payload is TF-only); a file that FAILS the gate is WITHHELD (deleted) rather than shipping
    a silently-wrong TF. Returns n_written, and 0 means nothing shipped and the path does not exist.

    NOTE: HDF5 embeds creation timestamps/uuids, so these files are NOT byte-reproducible across builds;
    a manifest sha256 over one is a download-integrity hash for THIS build's bytes, not a cross-build
    invariant."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    from mth5.mth5 import MTH5  # noqa: PLC0415
    hpath = Path(hpath)
    hpath.parent.mkdir(parents=True, exist_ok=True)
    if hpath.exists():
        hpath.unlink()
    # Opening the h5 can itself fail (file lock, HDF5 driver). Keep it best-effort like the per-station
    # loop: one h5 failure must NOT abort the whole portal build (catalogue/tf/sci/manifest are written
    # after the survey loop), so swallow it and report "nothing written".
    try:
        m = MTH5()
        m.open_mth5(str(hpath), mode="w")
    except Exception as ex:  # noqa: BLE001
        print(f"  [h5] WARN open {hpath.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
        hpath.unlink(missing_ok=True)
        return 0
    n = 0
    try:
        for (p, r) in stations:
            try:
                tf = TF(fn=str(p))
                tf.read()
                _apply_mth5_survey_metadata(tf.survey_metadata, smeta, slug, label)
                tf.station_metadata.id = _sanitise_station_id(r["id"])
                _stamp_mth5_source_provenance(tf.station_metadata, r)
                m.add_transfer_function(tf)
                n += 1
            except Exception as ex:  # noqa: BLE001
                print(f"  [h5] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
            finally:
                # Emit-and-release, per station, INSIDE the open file: the memory bound is then one
                # station's transient, not one bundle's (a 764-station survey stays flat). See
                # _release_mth5_metadata_classes for the measured why.
                _release_mth5_metadata_classes()
    finally:
        # Guarded: one h5 close failure must NOT abort the whole portal build; the round-trip gate
        # below withholds this file if the close left it unreadable.
        try:
            m.close_mth5()
        except Exception as _cx:  # noqa: BLE001
            print(f"  [h5] WARN {hpath.name}: close failed: {type(_cx).__name__}", file=sys.stderr)
    if not n:
        hpath.unlink(missing_ok=True)
        return 0
    # SPEC §6 blocking round-trip gate: withhold this file (never the corpus) on any mismatch.
    ok, rep = mth5_survey_roundtrip_ok(hpath, stations)
    if not ok:
        print(f"  [h5] WITHHOLD {hpath.name}: round-trip gate FAILED "
              f"(checked={rep['checked']}, z_maxdiff={rep['z_max_abs_diff']:.3g}, "
              f"coord_maxdiff={rep['coord_max_abs_diff']:.3g}, tf_only={rep['tf_only']}); "
              f"first: {rep['mismatches'][0] if rep['mismatches'] else 'n/a'}", file=sys.stderr)
        hpath.unlink(missing_ok=True)
        return 0
    return n


# ---- The MTH5 worker pool (the build-parallelism seam) -------------------------------------------
# The 2026-08-27 profile (AusMT_2026/BUILD-PERF-PROFILE-2026-08-27.md) attributed ~68% of a cold
# build and ~99% of a warm rebuild to _write_tf_mth5, which is self-contained by construction: it
# re-reads its source EDIs from disk, carries its own SPEC §6 gate, owns a unique output path per
# call and returns 0 instead of raising. The pool parallelises exactly that unit and NOTHING else:
# parse, XML, the C18 cache and all manifest bookkeeping stay in the main process, and every
# station id is final (_disambiguate has run) before the first task is submitted, so worker
# scheduling can never reach an identity or ordering decision. Workers are spawned, not forked
# (h5py and forked HDF5 state do not mix, and spawn behaves identically on the Linux box and a
# macOS dev machine).
_MTH5_POOL = None


def _mth5_write_task(stations, slug, label, hpath, smeta):
    """The one function a pool worker runs: a single _write_tf_mth5 call with its stderr captured
    and RETURNED rather than written, so the main process can replay every worker's WARN lines in
    input order and the build log stays deterministic under parallelism. (C-level HDF5 error spew
    still reaches fd 2 directly and may interleave; it does serially too.) Paths travel as strings
    because the task must pickle across a spawn boundary."""
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        n = _write_tf_mth5([(Path(p), r) for (p, r) in stations], slug, label, Path(hpath),
                           smeta=smeta)
    return n, buf.getvalue()


def _workers_arg(v):
    """argparse type for --workers: an integer >= 0 or 'auto'. Rejecting a malformed CLI value
    here (unlike the env var, which WARNS and builds serial) is deliberate: a typed flag is an
    operator at a keyboard who can fix it; the env var is an unattended box rebuild."""
    s = str(v).strip().lower()
    if s == "auto":
        return s
    try:
        if int(s) < 0:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(f"--workers must be an integer >= 0 or 'auto', got {v!r}")
    return s


def _resolve_workers(cli_value):
    """Effective MTH5 worker count: CLI --workers beats the AUSMT_BUILD_WORKERS env var beats 1
    (serial, the exact pre-pool build). 'auto' or 0 means min(6, cpus): ~400 MB peak per worker
    (profile: 383 MB flat), so 6 fits the box's 14 GiB with a wide margin while saturating the
    seam. A malformed env value WARNS and builds serial rather than killing an unattended box
    rebuild; a malformed CLI value is rejected by argparse before reaching here."""
    raw = cli_value if cli_value is not None else os.environ.get("AUSMT_BUILD_WORKERS")
    if raw is None:
        return 1
    s = str(raw).strip().lower()
    if s in ("auto", "0"):
        return max(1, min(6, os.cpu_count() or 1))
    try:
        return max(1, int(s))
    except ValueError:
        print(f"  [parallel] WARN AUSMT_BUILD_WORKERS={raw!r} is not an integer or 'auto'; "
              "building serial.", file=sys.stderr)
        return 1


def _pool_worker_ready():
    """Warmup no-op: submitting it launches the worker process (which pays its build_portal import
    right there) and the returned result proves that import succeeded."""
    return True


def _mth5_pool_start(workers):
    """Create the spawn-context pool. Returns the EFFECTIVE worker count: `workers` when the pool
    came up, 1 when it could not (WARN + serial fallback; the equivalence contract means the
    products are identical either way, and an unattended box rebuild should degrade, not die, on
    a spawn-capability problem).

    A spawned child must be able to import build_portal by name when the parent itself imported
    it as a module (pytest, or an embedding caller), so PYTHONPATH gains the extract/ dir for
    EXACTLY the warmup window: every worker is launched eagerly inside it, then the variable is
    restored before returning. The restore is load-bearing, not tidiness: a leaked PYTHONPATH
    reaches every subprocess the build (or a later test in the same process) shells, and
    test_proc_info_survives_a_missing_writer_vocabulary failed on exactly that contamination
    before the restore existed. Workers never respawn after a death (a dead worker breaks the
    whole pool), so no child ever launches outside the window."""
    global _MTH5_POOL  # noqa: PLW0603  (deliberate: main()'s finally must reach the pool from outside _main_build)
    if workers <= 1:
        return 1
    if _MTH5_POOL is not None:
        return workers
    import concurrent.futures  # noqa: PLC0415
    import multiprocessing  # noqa: PLC0415
    ext = str(Path(__file__).resolve().parent)
    old_pp = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = ext + (os.pathsep + old_pp if old_pp else "")
    try:
        _MTH5_POOL = concurrent.futures.ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
        for fut in [_MTH5_POOL.submit(_pool_worker_ready) for _ in range(workers)]:
            fut.result()
        return workers
    except Exception as ex:  # noqa: BLE001  (degrade to the identical-product serial path)
        print(f"  [parallel] WARN MTH5 pool failed to start ({type(ex).__name__}: {str(ex)[:120]});"
              " building serial.", file=sys.stderr)
        _mth5_pool_stop()
        return 1
    finally:
        if old_pp is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pp


def _mth5_pool_stop():
    """Shut the pool down (idempotent). main() guarantees this on every exit path: a leaked pool
    would make the NEXT main() call in the same process silently parallel, which is exactly the
    ambient state the serial default exists to forbid."""
    global _MTH5_POOL  # noqa: PLW0603  (deliberate: same slot; see _mth5_pool_start)
    if _MTH5_POOL is not None:
        # cancel_futures: an ABORTED build must not sit through its queued writes before dying (a
        # completed build has already drained every future it submitted, so this cancels nothing).
        _MTH5_POOL.shutdown(wait=True, cancel_futures=True)
        _MTH5_POOL = None


def emit_survey_mth5(stations, slug, label, out, smeta=None):
    """C32 §1.2 (tier 2): write ONE survey-aggregated MTH5 (out/bundles/<slug>-tf.h5) holding every
    served station's TRANSFER FUNCTION via mth5.add_transfer_function, the idiomatic MTCollection
    working unit for mtpy-v2/ModEM. It contains transfer functions ONLY (never time series); the -tf
    filename says so. FLAG-GATED by the caller (survey_h5_enabled). The write, the metadata mapping and
    the SPEC §6 withhold gate are _write_tf_mth5's; n_written is the ACTUAL count included, so the
    manifest row's n_stations reflects reality (design §1.4). A survey that fails the gate is withheld,
    not the corpus. Returns (rel_url, h5_path, n_written) or (None, None, 0)."""
    hpath = out / "bundles" / f"{slug}-tf.h5"
    n = _write_tf_mth5(stations, slug, label, hpath, smeta=smeta)
    if not n:
        return None, None, 0
    return f"bundles/{slug}-tf.h5", hpath, n


def _stamp_mth5_source_provenance(station_metadata, record) -> None:
    """Carry a third-party ingest's declared source provenance into an MTH5's station metadata.

    `station_metadata.comments` is the one station-level free-text slot MEASURED to survive the mth5
    write/read round trip on the pinned stack: provenance.comments and provenance.log are both
    dropped, and geographic_name survives but is a place name, not a record slot. Written as
    machine-readable `ausmt_*=value` lines and APPENDED, so the source EDI's own >INFO text is kept
    rather than displaced. No-op when the survey declared no provenance, so every existing file is
    byte-unchanged. Best-effort: the comments model varies across mt_metadata versions and a failure
    here must never lose the station."""
    prov = (record or {}).get("source_provenance")
    if not prov:
        return
    lines = [f"ausmt_source_file={prov['original_filename']}"] if prov.get("original_filename") else []
    if prov.get("source_record_id"):
        lines.append(f"ausmt_source_record_id={prov['source_record_id']}")
    if prov.get("acquisition_stage"):
        lines.append(f"ausmt_acquisition_stage={prov['acquisition_stage']}")
    if not lines:
        return
    try:
        existing = str(station_metadata.comments.value or "")
        station_metadata.comments.value = (existing + "\n" + "\n".join(lines)).strip()
    except Exception as ex:  # noqa: BLE001  (comments model varies; never lose a station over a note)
        print(f"  [h5] note source provenance not stamped for {record.get('id')}: "
              f"{type(ex).__name__}: {str(ex)[:80]}", file=sys.stderr)


def emit_station_mth5(stations, slug, label, h5dir, smeta=None):
    """Tier 1 (owner ruling 2026-08-02, which OVERRIDES the earlier skip-tier-1 ruling): one
    <station>.h5 per served station, written into h5dir = out/h5/<slug>/ so the per-station MTH5 sits
    beside the edi/ and xml/ families the manifest already keys. deploy/docker/caddy/Caddyfile has
    force-downloaded /h5/* since before there was a producer; this is the producer.

    Written by the SAME writer the tier-2 bundle uses (one station handed over instead of the survey),
    so the round-trip gate, the metadata mapping and the withhold-not-crash posture are inherited. The
    CALLER owns both gates: it is invoked only inside the served-survey branch (an embargoed or
    non-served survey emits nothing, identically to its EDI), and it is handed only the stations that
    pass the C42 per-station byte gate (an MTH5 carries the true latitude/longitude/elevation in its
    own station metadata, so a generalised or withheld station is withheld here exactly as its EDI and
    its EMTF-XML are).

    NO LICENCE SIDECAR is written beside these files, unlike the survey bundle's
    bundles/<slug>-tf.LICENSE.txt. It is not needed and it would be harmful: the licence already
    travels INSIDE each file (survey_metadata.release_license, set by _apply_mth5_survey_metadata), and
    a sidecar per station would put ~1400 unmanifested files into a served download family, every one
    of which would land in the analytics `unattributed` bucket that exists to detect build/serve skew.

    A station whose write fails is simply absent from the returned map (the WARN is printed by the
    writer); the caller emits a manifest row only for what came back, so the manifest can never
    advertise a file that was withheld. Returns {station_id: h5_path}.

    When the MTH5 pool is up, the stations fan out as one worker task each and the results are
    drained IN INPUT ORDER, each task's captured stderr replayed before the next, so the log and
    the returned map are indistinguishable from the serial loop's. The map is consumed by keyed
    lookup, but input order is still the contract: it is what makes the two paths comparable
    line-for-line."""
    written = {}
    if _MTH5_POOL is not None and len(stations) > 1:
        futs = []
        for (p, r) in stations:
            hpath = Path(h5dir) / f"{r['id']}.h5"
            futs.append((r["id"], hpath, _MTH5_POOL.submit(
                _mth5_write_task, [(str(p), r)], slug, label, str(hpath), smeta)))
        for sid, hpath, fut in futs:
            n, err = fut.result()
            if err:
                sys.stderr.write(err)
            if n:
                written[sid] = hpath
        return written
    for (p, r) in stations:
        hpath = Path(h5dir) / f"{r['id']}.h5"
        if _write_tf_mth5([(p, r)], slug, label, hpath, smeta=smeta):
            written[r["id"]] = hpath
    return written


# ---- Tier 3 (collection): DESIGNED, DISABLED BY CONSTRUCTION (SPEC §2.3 / A4). The producer exists so
# the code path is present and unit-testable, but no live build calls it unless collection_h5_enabled is
# flipped AND the station count clears max_collection_stations (default ~600) — SPEC §7.2 shows a single
# AusLAMP-national file peaks ~6 GiB of build RAM and would OOM a small runner, so the guard is mandatory.
def collection_h5_allowed(flags, n_stations):
    """Tier-3 producer guard (SPEC A4). True only when collection_h5_enabled is ON and n_stations does
    not exceed max_collection_stations (the RAM ceiling — a naive single-file build holds every TF
    resident at ~4.2 MB/station, SPEC §7.2). Returns (allowed: bool, reason: str)."""
    if not flags.get("collection_h5_enabled", False):
        return False, "collection_h5_enabled OFF (designed-but-disabled, SPEC A4)"
    cap = int(flags.get("max_collection_stations", 600) or 600)
    if n_stations > cap:
        return False, f"n_stations {n_stations} exceeds max_collection_stations {cap} (RAM gate, SPEC §7.2)"
    return True, "ok"


def emit_collection_mth5(members, collection_id, out, *, smeta_by_slug=None):
    """Tier 3 (SPEC §2.3): write ONE MTH5 concatenating several surveys, EACH under its own survey group
    keyed by its slug so cross-survey duplicate station ids never collide. `members` is an ordered list of
    (slug, label, stations) where stations is the same [(edi_path, record)] list tier 2 takes. Reuses the
    tier-2 station-id sanitisation and metadata mapping so a station's id/metadata are identical whether it
    rides a survey or a collection file. Best-effort per station (WARN + skip); the whole file passes the
    §6 round-trip + grouping gate (each member under a DISTINCT survey_metadata.id) before it is returned,
    else the collection is WITHHELD. Returns (rel_url, h5_path, n_written) or (None, None, 0).
    DISABLED BY CONSTRUCTION: gate callers on collection_h5_allowed(flags, n_stations) first."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    from mth5.mth5 import MTH5  # noqa: PLC0415
    smeta_by_slug = smeta_by_slug or {}
    hdir = out / "bundles"; hdir.mkdir(parents=True, exist_ok=True)
    hpath = hdir / f"{collection_id}-tf.h5"
    if hpath.exists():
        hpath.unlink()
    try:
        m = MTH5()
        m.open_mth5(str(hpath), mode="w")
    except Exception as ex:  # noqa: BLE001
        print(f"  [h5] WARN open {hpath.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
        hpath.unlink(missing_ok=True)
        return None, None, 0
    n = 0
    all_stations = []
    try:
        for (slug, label, stations) in members:
            for (p, r) in stations:
                try:
                    tf = TF(fn=str(p))
                    tf.read()
                    _apply_mth5_survey_metadata(tf.survey_metadata, smeta_by_slug.get(slug), slug, label)
                    tf.station_metadata.id = _sanitise_station_id(r["id"])
                    _stamp_mth5_source_provenance(tf.station_metadata, r)
                    m.add_transfer_function(tf)
                    n += 1
                    # tag the survey so the round-trip gate keys (survey, sid) — cross-survey duplicate
                    # station ids must compare against the RIGHT member EDI, not the first one seen.
                    all_stations.append((p, {**r, "_survey": slug}))
                except Exception as ex:  # noqa: BLE001
                    print(f"  [h5] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
                finally:
                    _release_mth5_metadata_classes()   # per station, same bound as _write_tf_mth5
    finally:
        # Guarded like the survey writer above: withhold-not-crash at the file, never the corpus.
        try:
            m.close_mth5()
        except Exception as _cx:  # noqa: BLE001
            print(f"  [h5] WARN {hpath.name}: close failed: {type(_cx).__name__}", file=sys.stderr)
    if not n:
        hpath.unlink(missing_ok=True)
        return None, None, 0
    ok, rep = mth5_survey_roundtrip_ok(hpath, all_stations)
    # Grouping gate (SPEC §6, tier 3): every member slug must land as a DISTINCT survey group.
    grouping_ok, groups = True, set()
    try:
        _m = MTH5(); _m.open_mth5(str(hpath), mode="r")
        try:
            groups = set(_m.tf_summary.to_dataframe()["survey"].unique())
        finally:
            _m.close_mth5()
        want = {s for (s, _l, st) in members if st}
        grouping_ok = want.issubset(groups)
    except Exception as ex:  # noqa: BLE001
        grouping_ok = False
        rep["mismatches"].append({"station": "*", "reason": f"grouping check: {type(ex).__name__}"})
    if not ok or not grouping_ok:
        print(f"  [h5] WITHHOLD {hpath.name}: collection gate FAILED "
              f"(roundtrip_ok={ok}, grouping_ok={grouping_ok}, groups={sorted(groups)})", file=sys.stderr)
        hpath.unlink(missing_ok=True)
        return None, None, 0
    return f"bundles/{collection_id}-tf.h5", hpath, n


def load_flags(path) -> dict:
    """Distribution feature flags from the portal.config.yaml `flags:` block (default OFF). The single
    config seam, mirrored to the portal via tools/gen_config.py -> config.js. survey_h5_enabled gates the
    tier-2 survey-aggregated MTH5 producer; station_h5_enabled gates the tier-1 per-station MTH5 producer
    (owner ruling 2026-08-02); collection_download_enabled reserves the future collection-level bundle.
    CLI --survey-h5 / --station-h5 / --collection-download OR on top.

    NOTE FOR ANYONE FLIPPING A FLAG HERE: this YAML lives under portal/ and the engine image does NOT
    copy it (deploy/docker/engine.Dockerfile takes contract/, engine/ and portal/src/contract.js only),
    so inside a production build container this function reads a path that does not exist and every flag
    falls back to the OFF default below. The enable that reaches a box is the CLI flag on
    deploy/Makefile's rebuild-data recipe. Setting a flag here ALONE is a production no-op, which has
    caught this repository twice; deploy/tests/test_makefile_build_flags.py now pins the wiring."""
    # Boolean distribution flags default OFF. collection_h5_enabled gates the tier-3 collection PRODUCER
    # (SPEC A4, designed-but-disabled); collection_download_enabled reserves the portal-side download.
    flags = {"survey_h5_enabled": False, "station_h5_enabled": False,
             "collection_download_enabled": False, "collection_h5_enabled": False}
    # max_collection_stations is the tier-3 RAM ceiling (SPEC §7.2): an INT, not a bool — kept out of the
    # bool-coercion loop below. Default ~600 (A4) so an AusLAMP-national-sized build cannot OOM the host.
    flags["max_collection_stations"] = 600
    if not path:
        return flags
    try:
        text = Path(path).read_text()
    except OSError:
        return flags
    try:
        import yaml  # type: ignore  # noqa: PLC0415
    except ModuleNotFoundError:
        cfg = _mini_yaml(text)  # stdlib-only fallback when PyYAML is absent
    else:
        # flags gate distribution behaviour (the deliberately-OFF D4 MTH5 producer); a config typo must
        # crash, not silently flip a flag via the mini-parser.
        try:
            cfg = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            sys.exit(f"ERROR: portal config {path} (flags block) is not valid YAML: {e}")
    f = (cfg or {}).get("flags", {}) if isinstance(cfg, dict) else {}
    if not isinstance(f, dict):
        f = {}   # a non-mapping flags: block must not crash f.get below
    for k in ("survey_h5_enabled", "station_h5_enabled", "collection_download_enabled",
              "collection_h5_enabled"):
        flags[k] = bool(f.get(k, flags[k]))
    _cap = f.get("max_collection_stations", flags["max_collection_stations"])
    try:
        flags["max_collection_stations"] = int(_cap)
    except (TypeError, ValueError):
        pass   # a non-integer cap in config is ignored; the ~600 default stands (fail-safe, not fail-open)
    return flags


def _validate_products(mtcat_doc, manifest_doc, build_report_doc=None):
    """Validate the emitted MTCAT + download-manifest (+ optional build_report) docs against
    schema/{mtcat,manifest,build_report}.schema.json. Returns a list of human-readable violations
    (empty = OK). jsonschema is optional: absent => [] + a note. A missing/broken schema file is
    noted, not fatal: only an actual schema VIOLATION fails.

    Each document is validated through _jdump + json.loads first, i.e. against THE BYTES THAT SHIP, not
    against the in-memory object. The two are not the same object graph: _jdump's default= hook ISO-
    formats a date/datetime/time an unquoted survey.yaml scalar carried into SMETA (attribution.
    declared_date is the live case), so the in-memory doc holds a datetime.date exactly where the served
    JSON holds a string. Validating the object would therefore report a violation the shipped file does
    not have, and would equally miss one the serialiser introduces. This gate exists to answer "does what
    we publish conform", so it must read what we publish. A doc that cannot be serialised at all is a
    genuine emit failure and is reported as a violation rather than crashing the build."""
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        print("note: jsonschema not installed — product schema self-check skipped", file=sys.stderr)
        return []
    errs = []
    _docs = [("mtcat", mtcat_doc), ("manifest", manifest_doc)]
    if build_report_doc is not None:
        _docs.append(("build_report", build_report_doc))
    for name, doc in _docs:
        schema_path = HERE.parent / "schema" / f"{name}.schema.json"
        try:
            served = json.loads(_jdump(doc))
        except (TypeError, ValueError) as e:
            errs.append(f"{name}.json: cannot be serialised for validation ({type(e).__name__}: {e})")
            continue
        try:
            jsonschema.validate(served, json.loads(schema_path.read_text()))
        except jsonschema.ValidationError as e:  # noqa: PERF203
            errs.append(f"{name}.json: {e.message} (at /{'/'.join(str(x) for x in e.absolute_path)})")
        except Exception as e:  # noqa: BLE001  (missing/unreadable schema must not crash the build)
            print(f"note: {name} schema self-check skipped ({type(e).__name__}: {e})", file=sys.stderr)
    return errs


def _validate_survey_metadata(docs_by_slug: dict) -> list:
    """The survey-metadata.json self-check, the emitter's own last line (beside _validate_products):
    every document {slug: doc} is validated against schema/ausmt-survey-metadata.schema.json WITH
    FORMAT CHECKING (date / date-time; jsonschema optional => noted, not fatal, like the other
    self-checks), scanned for nulls and empty containers (the document defines no null at all), and
    checked for the citation invariant (T25): a citation.preferred_identifier with no EQUAL {scheme,
    identifier} row in identifiers[] is a HARD STOP that RAISES naming the survey (the mtcat
    sources[]-rights precedent), because a document whose preferred citation identifier is not one of
    the dataset's own identifiers must never be published. In normal operation the surveys validator
    FAILs such a survey at the entry gates and the build's loud skip (D20) records it; this raise is
    reachable only in builds that run without a validator (--no-validate). Returns the list of
    human-readable violations (empty = OK); validation reads the bytes that ship (_jdump round-trip)."""
    for slug, doc in sorted(docs_by_slug.items()):
        pref = (doc.get("citation") or {}).get("preferred_identifier")
        if isinstance(pref, dict) and not any(
                i.get("scheme") == pref.get("scheme") and i.get("identifier") == pref.get("identifier")
                for i in (doc.get("identifiers") or [])):
            raise ValueError(
                f"survey-metadata: survey '{slug}' declares citation.preferred_identifier "
                f"{pref.get('scheme')}:{pref.get('identifier')} but no equal {{scheme, identifier}} row is "
                f"designated in identifiers[] (identity_classification.represents for case_a, "
                f"own_identifiers for case_b); the preferred citation identifier must be one of the "
                f"dataset's own identifiers (T25). Fix the designation in survey.yaml; the build refuses "
                f"to publish this document.")
    errs = []
    validator = None
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        print("note: jsonschema not installed - survey-metadata schema self-check skipped", file=sys.stderr)
    else:
        try:
            schema = json.loads((HERE.parent / "schema" / "ausmt-survey-metadata.schema.json").read_text())
            validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
        except Exception as e:  # noqa: BLE001  (missing/unreadable schema must not crash the build)
            print(f"note: survey-metadata schema self-check skipped ({type(e).__name__}: {e})", file=sys.stderr)
    for slug, doc in sorted(docs_by_slug.items()):
        name = f"products/{slug}/survey-metadata.json"
        try:
            served = json.loads(_jdump(doc))
        except (TypeError, ValueError) as e:
            errs.append(f"{name}: cannot be serialised for validation ({type(e).__name__}: {e})")
            continue
        nulls, empties = _sm_scan_nulls_and_empties(served)
        errs.extend(f"{name}: null value at {p} (this document defines no null)" for p in nulls)
        errs.extend(f"{name}: empty container at {p} (absence is the only no-assertion state)" for p in empties)
        if validator is not None:
            errs.extend(f"{name}: {e.message} (at /{'/'.join(str(x) for x in e.absolute_path)})"
                        for e in validator.iter_errors(served))
    return errs


def _validate_station_metadata(docs_by_path: dict) -> list:
    """The station.json self-check, the emitter's own last line (beside _validate_survey_metadata):
    every document {served path: doc} is validated against schema/ausmt-station.schema.json WITH
    FORMAT CHECKING (the run time_period date-times; jsonschema optional => noted, not fatal, as in
    the other self-checks) and against the SEMANTIC layer JSON Schema cannot state (_stationcheck:
    run reference integrity, unique run and resource ids, time_period ordering, channel shape per
    component family, withheld-branch closure, DOI syntax, the 1.x distribution.edi_path equivalence
    pin). Returns the list of human-readable violations (empty = OK); validation reads the bytes that
    ship (_jdump round-trip). scripts/verify.py runs the same layer over the BUILT tree, so a corpus
    reaching a deployment gate is checked twice, from the emitter's state and from the served one."""
    errs = []
    validator = None
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:
        print("note: jsonschema not installed - station schema self-check skipped", file=sys.stderr)
    else:
        try:
            schema = json.loads((HERE.parent / "schema" / "ausmt-station.schema.json").read_text())
            validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
        except Exception as e:  # noqa: BLE001  (missing/unreadable schema must not crash the build)
            print(f"note: station schema self-check skipped ({type(e).__name__}: {e})", file=sys.stderr)
    for name, doc in sorted(docs_by_path.items()):
        try:
            served = json.loads(_jdump(doc))
        except (TypeError, ValueError) as e:
            errs.append(f"{name}: cannot be serialised for validation ({type(e).__name__}: {e})")
            continue
        errs.extend(f"{name}: {v}" for v in stcheck.violations(served))
        if validator is not None:
            errs.extend(f"{name}: {e.message} (at /{'/'.join(str(x) for x in e.absolute_path)})"
                        for e in validator.iter_errors(served))
    return errs


def discover_work(a, ap, validator):
    """One work entry per survey, from --surveys packages or --raw EDI folders. Returns
    (work, survey_extent): work = [(label, org, inputs, kind, meta-or-None, pkgdir-or-None, slug,
    yaml_digest)]; survey_extent maps a survey label to its declared geographic_extent (for the
    out-of-extent QC). A pure discovery phase -- it reads the filesystem + validator and produces the
    work list; the per-survey extract/science/products happen in main()'s loop over what this returns.
    yaml_digest is the sha256 of the SAME survey.yaml bytes the meta was parsed from (Amendment A4:
    one read feeds both, so an edit landing mid-build can never split them; "" for --raw entries).

    C42: also returns coord_policy = {label: (default, overrides)} — the coordinate-access policy per
    survey (D2). Carried in a SIDE CHANNEL (not on SMETA, which is emitted to surveys.json — putting
    the always-'exact' default there would break the default-stability pin). Absent field => ('exact',
    {}); --raw entries have no survey.yaml so are always 'exact'. An UNKNOWN enum value raises
    CoordinatePolicyError from parse_coordinate_policy — the survey-level build fails LOUDLY (fail
    closed). Override IDS are deliberately NOT validated here (fix round 2): any discovery-time scrape
    is a SECOND id derivation and hence a divergence risk (the probe-e hole: a stem∪DATAID∪prefix
    candidate set validated keys the mask never applied). They are validated in main()'s build loop at
    the point the REAL parsed station ids exist — for both EDI and MTH5 inputs, before any of that
    survey's bytes are emitted, with the SAME matcher station_policy applies with.

    Station-id override (owner ruling 2026-08-08): also returns station_ids = {label: {source
    filename: published station id}}, the survey.yaml `station_ids` block parsed by
    extract/_stationids.py. Same SIDE-CHANNEL discipline as coord_policy (it is an ingest instruction,
    not survey metadata, so it never reaches surveys.json) and the same validation SPLIT: the block's
    SHAPE is checked here, where a bad enum or a traversal-shaped key drops just this survey loudly;
    the keys are checked against the package's REAL files in the build loop, before any of that
    survey's bytes are emitted. A survey with no block yields {} and takes no override path at all.

    Survey metadata (the second public contract): also returns survey_yaml_by_label = {label: the RAW
    parsed survey.yaml mapping}, the side channel survey_metadata_document reads (D18: SMETA and
    surveys.json stay byte-identical; the emitter never widens the portal seam). --raw entries have no
    survey.yaml and so no entry (a raw build emits no survey-metadata documents).

    The loud skip (D20): also returns surveys_skipped_validation = [package directory name, ...] for
    every package the validator FAILed and the build SKIPPED. The skip itself is unchanged (the rest of
    the corpus builds, exit 0), but it is no longer silent: main() writes the list into
    build_report.json and scripts/verify.py FAILs on a non-empty list, so `make rebuild-data` leaves
    `current` untouched rather than letting a survey vanish from every public surface."""
    work, survey_extent, coord_policy, station_ids = [], {}, {}, {}
    survey_yaml_by_label, surveys_skipped_validation = {}, []
    # Every survey-granularity drop below is RECORDED, not just printed: build_report.json carries
    # the list and scripts/verify.py FAILs on any entry, so `make rebuild-data` can never swap in a
    # build that silently lost a survey (D20's rule, extended to the whole drop class).
    surveys_dropped = []
    if a.surveys:
        for d in sorted(Path(a.surveys).iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            sy = d / "survey.yaml"
            if not sy.exists():
                continue
            if validator:
                rep = validator.validate(d)
                if rep.worst() == 2:
                    print(f"SKIP {d.name}: validation FAILED ({rep.counts()['FAIL']} fails)", file=sys.stderr)
                    # D20: record the skip so build_report.json / verify.py make it LOUD. The package
                    # directory name is the slug in every validated corpus (the validator FAILs a slug
                    # that differs from its folder); the yaml is not parsed here because it just FAILed.
                    surveys_skipped_validation.append(d.name)
                    continue
            # C18 Amendment A4 (single-read coherence): read survey.yaml's bytes ONCE and derive BOTH
            # the parsed metadata and the cache-key digest from them. The 2026-07-07 incident was a
            # build that read this file twice (meta here, digest at its per-survey loop iteration,
            # minutes later on a full corpus): an edit landing between the reads wrote served XML
            # embedding the PRE-edit metadata KEYED under the POST-edit digest — poisoning the cache
            # so the NEXT build warm-served stale citations at hits=N/misses=0, invisible to the C18b
            # gate (the poisoned stamp equals the live digest). One read = nothing to straddle.
            try:
                sy_raw = sy.read_bytes()
            except OSError as e:
                print(f"SKIP {d.name}: could not read survey.yaml ({type(e).__name__}: {e}) "
                      f"-- survey dropped", file=sys.stderr)
                surveys_dropped.append((d.name, f"survey.yaml could not be read ({type(e).__name__})"))
                continue
            y = _read_yaml(sy, raw=sy_raw)
            if not isinstance(y, dict):
                if y is not None:  # valid YAML but not a mapping (list/scalar); None was already warned in _read_yaml
                    print(f"SKIP {d.name}: survey.yaml is not a YAML mapping -- survey dropped", file=sys.stderr)
                surveys_dropped.append((d.name, "survey.yaml is not a YAML mapping"
                                                if y is not None else "survey.yaml did not parse"))
                continue
            sy_digest = hashlib.sha256(sy_raw).hexdigest()   # the ONE digest this survey builds under
            label = y.get("name", d.name)
            slug = safe_component(y.get("slug", d.name))   # untrusted slug -> safe paths/ids
            edis = sorted((d / "transfer_functions" / "edi").glob("*.edi"))
            mh = sorted((d / "transfer_functions" / "mth5").glob("*.h5")) \
                + sorted((d / "transfer_functions" / "mth5").glob("*.mth5"))
            # EMTF XML is a FIRST-CLASS submission input (owner ruling 2026-08-03), alongside EDI and
            # MTH5. transfer_functions/emtfxml/ in a SUBMITTED package is therefore an ingest folder;
            # the build's own canonical re-emission still lands in the served tree (out/xml/<slug>/),
            # never back into the package, so the two never collide.
            xmls = sorted((d / "transfer_functions" / "emtfxml").glob("*.xml"))
            fmt = a.input_format
            if fmt == "edi":
                inputs, kind = edis, "edi"
            elif fmt == "mth5":
                inputs, kind = mh, "mth5"
            elif fmt == "emtfxml":
                inputs, kind = xmls, "emtfxml"
            # auto: the file-based TF inputs (EDI and/or EMTF XML) together, otherwise MTH5. EDI+XML
            # are ingested as ONE set because precedence is PER STATION (the ruling: a station present
            # in edi/ wins; its same-station XML stays in the package as an untouched artifact and is
            # not ingested). main() applies that precedence after the parse, where the real station ids
            # exist. `kind` names the PRIMARY file format so the pre-parse dispatch below stays a
            # two-way choice; the honest per-station source is recorded from each input's own suffix.
            elif edis or xmls:
                inputs, kind = edis + xmls, ("edi" if edis else "emtfxml")
            else:
                inputs, kind = ((mh, "mth5") if mh else (edis, "edi"))
            # Use the extracted org NAME (string), never the raw `organisation` mapping — under the
            # structured schema that mapping would otherwise land in station.json as a dict.
            smeta = survey_meta_from_yaml(y)
            survey_extent[label] = _extent_of(y)  # for the build-time out-of-extent QC FYI
            # C42: parse the coordinate-access policy from THIS survey's access block. An unknown enum
            # value is a SURVEY-level build failure (fail-closed, D2): the survey is DROPPED loudly,
            # NOTHING is served for it, and the REST of the corpus builds — never a silent fallback to
            # exact. Override IDS are NOT validated here (fix round 2): a discovery-time scrape is a
            # second id derivation and hence a divergence risk (probe-e); they are validated in the
            # build loop against the REAL parsed station records, before any bytes are emitted.
            try:
                coord_policy[label] = coordacc.parse_coordinate_policy(y.get("access"))
            except coordacc.CoordinatePolicyError as _cpe:
                print(f"SKIP {d.name}: coordinate-access policy INVALID — {_cpe}", file=sys.stderr)
                survey_extent.pop(label, None)
                surveys_dropped.append((d.name, "coordinate-access policy invalid"))
                continue
            # Station-id override: parse the block's SHAPE now (unknown key, bad `source`, a key that
            # is not a bare filename, a value the sanitiser would mangle, colliding values). Same
            # fail-closed, survey-granularity posture as the coordinate policy above: this package is
            # dropped loudly and the rest of the corpus builds. Key EXISTENCE is checked in the build
            # loop against the survey's real EDI files.
            try:
                station_ids[label] = stnids.parse_station_ids(y.get("station_ids"))
            except stnids.StationIdError as _sie:
                print(f"SKIP {d.name}: station_ids block INVALID: {_sie}", file=sys.stderr)
                survey_extent.pop(label, None)
                coord_policy.pop(label, None)
                station_ids.pop(label, None)
                surveys_dropped.append((d.name, "station_ids block invalid"))
                continue
            work.append((label, smeta["org"], inputs, kind, smeta, d, slug, sy_digest))
            survey_yaml_by_label[label] = y   # the raw mapping, for survey-metadata.json (D18 side channel)
    elif a.raw:
        coll = json.loads(Path(a.collections).read_text()) if a.collections else \
            {p.name: [p.name, "unknown"] for p in sorted(Path(a.raw).iterdir()) if p.is_dir()}
        seed = json.loads(Path(a.seed_meta).read_text()) if a.seed_meta else {}
        for folder, (label, org) in coll.items():
            edis = sorted((Path(a.raw) / folder).glob("*.edi"))
            # AusLAMP splits into per-state surveys by station prefix/location (matches portal)
            if label == "AusLAMP":
                buckets = {}
                for p in edis:
                    # Bucket by state via a LIGHT coord read (kept coord helpers, not the retiring
                    # regex component parser). The per-EDI TF is parsed once later in process_edis.
                    lat, lon = cat.coords_of(p)
                    st = cat.state_of(lat, lon)
                    lab = f"AusLAMP {st}" if st != "?" else "AusLAMP"
                    buckets.setdefault(lab, []).append(p)
                for lab, ps in buckets.items():
                    # raw mode: no survey.yaml -> the stable empty digest marker (matches Amendment A1a:
                    # raw builds are cache-excluded anyway; the field just keeps the tuple shape uniform)
                    work.append((lab, seed.get(lab, {}).get("org", org), ps, "edi", seed.get(lab), None, slugify(lab), ""))
            else:
                work.append((label, seed.get(label, {}).get("org", org), edis, "edi", seed.get(label), None, slugify(label), ""))
    else:
        ap.error("pass --surveys or --raw")
    return work, survey_extent, coord_policy, station_ids, survey_yaml_by_label, surveys_skipped_validation, surveys_dropped


def main(argv=None):
    """The build entry point. The wrapper exists for exactly one constraint: the MTH5 pool must be
    gone by the time main() returns on EVERY path (success, sys.exit, exception), because a leaked
    pool would make a later main() call in the same process silently parallel and would strand
    spawned workers on an aborted build."""
    try:
        return _main_build(argv)
    finally:
        _mth5_pool_stop()


def _main_build(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surveys", help="root of survey packages (<slug>/survey.yaml + "
                                      "transfer_functions/{edi,emtfxml,mth5}/)")
    ap.add_argument("--raw", help="root of raw EDI folders (bulk seed mode)")
    ap.add_argument("--collections", help="JSON {folder:[survey_label,org]} for --raw mode")
    ap.add_argument("--seed-meta", help="JSON of survey metadata (SMETA) for --raw mode -> surveys.json")
    ap.add_argument("--out", required=True, help="portal data dir to write {catalogue,tf,sci,surveys}.json")
    ap.add_argument("--products", default=None, help="optional dir for the product-contract JSON")
    ap.add_argument("--ts-index", default=None,
                    help="root of the per-survey verified-resource registers (<slug>/ts-index.yaml, "
                         "written out of band by the ausmt-surveys crawler). Read OFFLINE as files "
                         "(rule 14: the build never reaches the archive), validated against the same "
                         "closed vocabularies the surveys validator applies, and projected as "
                         "kind=time_series resource rows. Absent => no register is read and the build "
                         "is byte-identical to one built before the flag existed.")
    ap.add_argument("--pid-status", default=None,
                    help="IDCONS D4: optional path to a pid_status.json cache (written by "
                         "scripts/refresh_pid_status.py). When present, each served DOI-typed identifier "
                         "gains a resolution facet (ok|reserved) so the portal renders a reserved-but-404 "
                         "DOI as plain text, not a dead link. The build NEVER hits the network; absent => "
                         "every identifier is 'unknown' (linked as today), byte-identical output.")
    ap.add_argument("--no-validate", action="store_true",
                    help="skip the survey validator gate. Since C8 this is the ONLY way to build "
                         "--surveys without a resolved validator (an unresolvable validator is "
                         "otherwise a hard error, not a warning) -- pass this to explicitly "
                         "acknowledge building unvalidated.")
    ap.add_argument("--bundle-edi", action="store_true",
                    help="copy EDIs of redistributably-licensed surveys into <out>/edi/ and mark them "
                         "downloadable (the interim static distribution model). License-gated.")
    ap.add_argument("--extractor", choices=["mt_metadata"], default="mt_metadata",
                    help="EDI parser. Only 'mt_metadata' (the USGS community library) remains; the "
                         "dependency-free regex extractor was retired (see "
                         "the 2026-06 regex-parser retirement). Kept as an explicit flag so "
                         "provenance records the engine and call sites stay stable.")
    ap.add_argument("--input-format", choices=["auto", "edi", "mth5", "emtfxml"], default="auto",
                    help="transfer-function input for --surveys packages: 'edi', 'mth5', 'emtfxml', "
                         "or 'auto' (the file-based inputs EDI+EMTF XML together where either is "
                         "present, otherwise MTH5). One science seam for all three. Under 'auto' a "
                         "station present in edi/ wins over a same-station file in emtfxml/.")
    ap.add_argument("--portal-config", default=None,
                    help="path to portal.config.yaml — sets the MTCAT portal_id/name (for re-used portals). "
                         "Defaults to AusMT when omitted.")
    ap.add_argument("--allow-empty", action="store_true",
                    help="permit a build with zero surveys/stations to succeed, writing valid EMPTY "
                         "default product files (for fresh-start deployments and international reuse). "
                         "Without this flag an empty build fails loudly (the trust invariant).")
    ap.add_argument("--sitemap-base", default=None,
                    help="if set (e.g. https://org.github.io/ausmt/), write <out>/sitemap.xml "
                         "with per-survey and per-station deep links")
    ap.add_argument("--canonical-dir", default=None,
                    help="ADDITIVE: emit the canonical EMTF XML store (D6) — for each EDI write "
                         "<dir>/<slug>/<station>.xml + a derived .edi via mt_metadata's normalize(), "
                         "round-trip verified. Does NOT change the portal products (a separate "
                         "canonical artifact alongside them); requires the mt_metadata stack "
                         "(pip install -r environments/requirements-mtmetadata-lock.txt).")
    ap.add_argument("--base-url", default="",
                    help="optional URL prefix for download-manifest artifact URLs. Default: relative "
                         "URLs (e.g. edi/<file>) the portal joins onto its data_base_url. Set this for an "
                         "absolute artifact host.")
    ap.add_argument("--survey-h5", action="store_true",
                    help="produce a survey-aggregated transfer-function MTH5 per served survey "
                         "(out/bundles/<slug>-tf.h5) and list it in the manifest. OFF by default (D4: "
                         "MTH5 gated pending storage/management sign-off). ORs with portal.config "
                         "flags.survey_h5_enabled.")
    ap.add_argument("--station-h5", action="store_true",
                    help="produce ONE transfer-function MTH5 per served station "
                         "(out/h5/<slug>/<station>.h5) and list each in the manifest's files[]. Rides "
                         "the same access + coordinate gates as the station's EDI. OFF by default; "
                         "ORs with portal.config flags.station_h5_enabled. Wired into deploy/Makefile's "
                         "rebuild-data, which is the ONLY enable that reaches a production build.")
    ap.add_argument("--workers", default=None, metavar="N|auto", type=_workers_arg,
                    help="MTH5 writer processes (the ~68%%-cold / ~99%%-warm seam the 2026-08-27 "
                         "profile attributed). Default 1: byte-for-byte the pre-pool serial build. "
                         "'auto' (or 0) = min(6, cpus). Overrides the AUSMT_BUILD_WORKERS env var; "
                         "only the MTH5 writes parallelise (parse, XML, cache and manifest stay in "
                         "the main process), and test_build_parallel pins serial==parallel "
                         "product equivalence.")
    ap.add_argument("--collection-download", action="store_true",
                    help="set the collection-level download capability flag (reserved; no producer yet).")
    # C18 incremental build cache (default OFF; a no-op without --cache-dir). See
    # maintainer/C18-BuildCacheDesign.md. The cache may only change build SPEED, never output bytes —
    # verify.py stays full/byte-re-hashing/cache-blind, and a warm build is byte-identical to a
    # --cache-mode refresh build. Switched ON in exactly one place: deploy/Makefile's rebuild-data.
    ap.add_argument("--incremental", action="store_true",
                    help="C18: consult + populate a content-addressed cache of per-station products "
                         "(the mt_metadata parse + the served-XML round-trip) so unchanged stations "
                         "skip both. OFF by default; a NO-OP without --cache-dir. A degenerate salt "
                         "(unknown engine commit, or a dirty engine checkout) silently disables it.")
    ap.add_argument("--cache-dir", default=None,
                    help="C18: cache root (required for --incremental to do anything). Unset => "
                         "--incremental is a no-op.")
    ap.add_argument("--cache-mode", choices=list(cache_mod.CACHE_MODES), default="rw",
                    help="C18: rw (consult+populate) / ro (consult only, CI reproducibility) / "
                         "refresh (ignore hits, forced full rebuild that still repopulates).")
    a = ap.parse_args(argv)
    # IDCONS D4 (SPEC §5.3): load the pid_status.json cache ONCE per build (or {} when absent). The build
    # never refreshes it — it only annotates each served identifier's resolution facet from it.
    pid_status = load_pid_status(a.pid_status)
    if pid_status:
        print(f"note: IDCONS resolve-gate active ({len(pid_status)} cached identifier statuses from "
              f"{a.pid_status}).", file=sys.stderr)
    # sha256() memoises per PATH in the module-global _SHA_CACHE ("cached per build"). Reset it at the
    # start of every build so a rebuild in a REUSED process (tests, the C18 warm-vs-refresh harness)
    # re-hashes each file's CURRENT bytes — otherwise a stale memoised sha would HIDE an edited EDI
    # from the content-addressed cache key (the exact spurious-hit the design's content-sha key exists
    # to prevent). Production runs one build per subprocess, where this is already empty; this makes
    # the "per build" contract hold in-process too.
    _SHA_CACHE.clear()
    # Same contract for the raw-EDI-text memo (_ediparse.read_norm, @lru_cache): it feeds coord-QC +
    # processing-metadata scrapes, so a rebuild in a reused process must re-read an edited EDI's
    # CURRENT text there too — a latent sibling of the _SHA_CACHE hazard above (A4 hardening; no
    # observed incident, closed on principle: one reset point per per-build memo).
    ep.read_norm.cache_clear()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    edidir = out / "edi"
    prod = Path(a.products) if a.products else None
    if prod:
        prod.mkdir(parents=True, exist_ok=True)
    validator = None if a.no_validate else _load_validator()
    if validator is None and not a.no_validate and a.surveys:
        # Fail-CLOSED (C8): the sibling ausmt-surveys pytest suite never ran in CI and validate.yml is
        # path-scoped to surveys/**, so an unresolved validator used to only WARN and proceed — a build
        # that quietly skipped validation looked identical to a validated one. Now that
        # silently-unvalidated state is a hard error; --no-validate is the only sanctioned opt-out.
        print("ERROR: survey validator not found (ausmt-surveys/_validation/validate_survey.py is not "
              "beside this repo, and AUSMT_VALIDATOR_PATH is unset) — refusing to ingest survey packages "
              "UNVALIDATED. Check out ausmt-surveys next to the ausmt monorepo, set AUSMT_VALIDATOR_PATH, "
              "or pass --no-validate to explicitly acknowledge building without the gate.",
              file=sys.stderr)
        return 2

    cdir = Path(a.canonical_dir) if a.canonical_dir else None
    if cdir is not None:
        if not mtm.available():
            sys.exit("ERROR: --canonical-dir requires the mt_metadata stack "
                     "(pip install -r environments/requirements-mtmetadata-lock.txt).")
        cdir.mkdir(parents=True, exist_ok=True)
    canonical_ok = canonical_fail = 0
    canonical_versions: dict = {}
    all_canonical_notes: dict = {}   # {slug: {station_id: [conditioning-note, ...]}} -> provenance.json

    # Distribution feature flags (config OR CLI): D4 keeps survey MTH5 OFF by default.
    flags = load_flags(a.portal_config)
    flags["survey_h5_enabled"] = flags["survey_h5_enabled"] or a.survey_h5
    flags["station_h5_enabled"] = flags["station_h5_enabled"] or a.station_h5
    flags["collection_download_enabled"] = flags["collection_download_enabled"] or a.collection_download
    base_url = a.base_url
    if (flags["survey_h5_enabled"] or flags["station_h5_enabled"]) and not mtm.available():
        sys.exit("ERROR: --survey-h5 / --station-h5 (and their portal.config flags) require the "
                 "mt_metadata stack (pip install -r environments/requirements-mtmetadata-lock.txt).")
    # The MTH5 worker pool: started only when a build both asked for workers AND emits MTH5 (the
    # only seam the pool serves); every other build records workers=1 and runs the untouched serial
    # code path. The wrapper around _main_build guarantees the stop on every exit.
    workers = _resolve_workers(a.workers)
    if workers > 1 and (flags["survey_h5_enabled"] or flags["station_h5_enabled"]):
        workers = _mth5_pool_start(workers)
        if workers > 1:
            print(f"[parallel] MTH5 pool: {workers} workers (spawn)", file=sys.stderr)
    else:
        workers = 1
    # Survey-MTH5 bundles submitted to the pool: each entry holds the future, its reserved (empty)
    # manifest row to fill in place, and the row/sidecar ingredients captured at submit time. The
    # worker pickled its (path, record) payload at submit, so the C42 mask seam mutating records
    # later cannot reach a write; resolution happens at the survey loop's exit, before the first
    # bookkeeping consumer.
    _deferred_bundles: list = []

    all_stations, all_tf, all_sci = [], [], []
    # manifest: per-station artifacts (files) + per-survey bundles (bundles). Key-based, NOT positional.
    surveys_meta, manifest = {}, {"files": [], "bundles": []}
    dropped_surveys = []   # (label, n_inputs, reason|None): a survey that validated but yielded 0
                           # stations (reason None), or LAYER 2 dropped for an unserialisable SMETA
                           # (reason set) — either way it never silently vanishes from the build log.
    # build_report.json accumulator: {slug: {stations_built, stations_dropped, warnings, conditioning,
    # cache, duration_seconds}}. Populated per survey in the loop; assembled + written alongside
    # build_provenance.json below. Public build metadata for the (planned) curator serve-state UI.
    build_report_surveys: dict = {}
    (work, survey_extent, coord_policy, station_ids_by_survey,
     survey_yaml_by_label, surveys_skipped_validation, _disc_dropped) = discover_work(a, ap, validator)
    # Discovery-phase drops fold into the SAME recorder as the loop's own, so build_report's
    # surveys_dropped is the one list verify.py gates on.
    dropped_surveys.extend((name, None, reason) for name, reason in _disc_dropped)

    # === provenance block (traceability: input -> software/params -> output) ===
    PROV = _build_prov(a.extractor)
    # === build identity (C12): engine_commit + source_commit + generated -> build.json, the
    # build<->data handshake a served portal needs to trace itself to its inputs. a.surveys is None
    # in --raw mode (no ausmt-surveys checkout involved) -> source_commit stays None, gracefully. ===
    BUILD_ID = build_identity(a.surveys)
    # C32 §2: resolve the served-tool versions ONCE (the single source of truth) — reused by the C18
    # cache salt below and folded into build.json / build_provenance.json / mtcat as additive keys.
    LIB_VERSIONS = lib_versions()

    # === C18 incremental build cache ===
    # OFF by default; a no-op without --cache-dir. Keyed by source-EDI content sha + the COARSE
    # engine-commit salt (BUILD_ID["engine_commit"]) + mt_metadata/mth5 versions + the positional/
    # schema contract + each survey's whole-yaml digest (cache.py derives the key). A degenerate salt
    # (unknown engine commit, or a DIRTY engine checkout where a checkout exists) yields an INERT
    # cache: cache.enabled is False, so get() always misses and put() no-ops, and the build runs
    # full. The cache may only change build SPEED — the products below are byte-identical whether
    # they came from a hit or a fresh compute (proven by the §4.5 equivalence test).
    build_cache = None
    if a.incremental and a.cache_dir:
        build_cache = cache_mod.BuildCache(
            Path(a.cache_dir),
            engine_commit=BUILD_ID["engine_commit"],
            lib_versions=LIB_VERSIONS,   # C32 §2: same single-source helper the served version keys read
            contract_digest=cache_mod.contract_schema_digest(HERE.parent),
            mode=a.cache_mode,
            checkout_dir=HERE,   # the engine checkout; dirty-here disables the cache (integrity §2.2)
            # Amendment A1a: --raw builds are EXCLUDED from caching entirely. Raw-mode survey
            # metadata comes from --seed-meta JSON, which feeds the served XML's citation
            # (DOI/authors/title) but is covered by NO key component (survey_meta_digest is empty
            # without a survey.yaml) — a warm raw rebuild would serve the PREVIOUS seed's citation
            # while the same build's surveys.json showed the new values. Raw is the rare
            # seed-regeneration path, not the hot path: over-invalidate (inert, like a degenerate salt).
            disabled_reason=("--raw build: --seed-meta metadata feeds served citations but is not a "
                             "cache-key component; raw mode is excluded from caching (Amendment A1a)"
                             if a.raw else ""))
        if build_cache.degenerate:
            print(f"note: C18 cache DISABLED for this build — {build_cache.degenerate_reason}. "
                  f"Building full (no cache reads or writes).", file=sys.stderr)
        else:
            print(f"note: C18 incremental cache active (dir={a.cache_dir}, mode={a.cache_mode}).",
                  file=sys.stderr)
    elif a.incremental and not a.cache_dir:
        print("note: --incremental with no --cache-dir is a no-op (safe default); building full.",
              file=sys.stderr)

    # === per-survey processing: extract + science + per-station products ===
    available_ids = set()
    # ONE served file, ONE owning manifest row. {resolved served path: {ausmt_id, format}} plus the
    # contradictions found, gated hard after the loop (see _claim_served_artifact): two rows over the
    # same bytes is the one integrity failure the manifest's own sha256 column cannot expose, because
    # both rows hash the file they name and both verify.
    _artifact_claims: dict = {}
    _artifact_collisions: list = []
    # C42: --products station.json carries a `location` (r[lat/lon]) and IS a served surface in
    # deployment (deploy/Makefile writes products/ INSIDE the served build dir; D1/D3). Its coordinates
    # must therefore be the POST-MASK values from the single seam — but the mask runs after the corpus-
    # wide qc_pass, which is after this per-survey loop. So the per-station product emission is DEFERRED:
    # each iteration appends a job here capturing its (shared, in-place-masked) station record; the jobs
    # run AFTER apply_coordinate_policy, so station.json reads the same masked record every other emitter
    # reads (D3: "no per-emitter logic"). Nothing else in station.json depends on the mask, so deferral is
    # value-preserving for exact stations (proven by the default-stability pin).
    _station_product_jobs: list = []
    # resources[] inputs, captured at the emit sites so a resource path is the SAME string the
    # manifest row is built from and never a second derivation of it: {ausmt_id: {format: path}}
    # for the per-station renditions, {slug: {format: path}} for the per-survey bundles (which are
    # emitted after the station loop), and {slug: [row]} for the placeable collection identifiers.
    _served_formats: dict = {}
    _bundle_formats: dict = {}
    _collection_ids: dict = {}
    # {ausmt_id: [register row]} for the hand-off rows, captured at the same gate as the renditions
    # above so a station the access gate excludes is simply absent rather than filtered later.
    _ts_rows: dict = {}
    # survey-metadata.json (the second public contract): ONE job per survey, keyed by label like
    # surveys_meta (so the document set equals mtcat's surveys[] by construction), capturing the raw
    # survey.yaml side channel, the SMETA entry and the survey's serve state (D8 seam). Emitted after
    # the coordinate mask seam and the deferred station jobs, because the extent follows the post-mask
    # coordinate state (D7), into out/products/<slug>/ (the served root, D2).
    _survey_metadata_jobs: dict = {}
    # C1b: ausmt_ids whose survey is NOT served (embargoed/metadata_only/unrecognised level). The C1 gate
    # withholds the BYTES; C1b additionally withholds the DERIVED DISPLAY products (the thinned tf.json
    # curves + the science-derived sci.json fields) at EMISSION, because for an embargoed dataset the
    # response curves ARE the data — a portal that plots them has published what the byte gate withheld.
    # Populated from the SAME access_serve_state result the byte gate uses (never re-derived), then applied
    # in the portal-projection loop below so a station's catalogue row (locations/band/nper/sha256) stays
    # public while its tf series go empty and its science sci fields are nulled.
    withheld_ids = set()
    input_formats = set()
    # C18b (A3, as amended by A4): the digest-stamp sidecar (out/products/survey_digests.json). Per
    # served survey it records the digest of the survey.yaml bytes THIS BUILD'S METADATA CAME FROM
    # (yaml_digest_current — the discovery-time single read, A4) and, per served station, the digest
    # its served XML was KEYED/PRODUCED under (xml_digest_stamped). verify.py's --surveys consistency
    # gate compares BOTH against the LIVE survey.yaml, catching (a) a product served under a stale
    # (pre-edit) digest and (b) a STRADDLED build whose yaml changed underneath it mid-build — the
    # 2026-07-07 incident's two faces. Cache-INDEPENDENT: built from the served products + the source
    # yaml, never from cache state.
    survey_digests_sidecar: dict = {}
    import time as _time  # noqa: PLC0415 (house style: local import where used — per-survey wall time)
    for label, org, inputs, kind, meta, pkgdir, slug, _survey_digest in work:
        _survey_t0 = _time.perf_counter()   # build_report.json duration_seconds (wall time for this survey)
        _survey_warnings: list = []         # structured survey-scoped warnings for build_report.json
        # C42 coordinate-access policy for THIS survey (side-channel from discover_work; ('exact', {})
        # for a survey with no policy field and for every --raw entry). Drives the per-station byte gate
        # at the copy/emit sites below AND the post-QC mask seam. ONE source for both.
        _coord_default, _coord_overrides = coord_policy.get(label, ("exact", {}))
        # Station-id override map for THIS survey (side-channel from discover_work; {} for a survey
        # with no `station_ids` block and for every --raw entry, which is the whole existing corpus).
        _station_ids = station_ids_by_survey.get(label) or stnids.StationIds("filename", {}, {})
        # C18 cache key component: this survey's WHOLE survey.yaml digest (§2.5, provably
        # over-invalidating — any yaml edit re-derives just this survey; "" for --raw entries, which
        # are cache-excluded anyway). Amendment A4: the digest is CARRIED from discover_work, computed
        # there from the SAME bytes the survey meta was parsed from — never re-read here. A loop-time
        # re-read is exactly the 2026-07-07 incident window: an edit landing between discovery and
        # this iteration used to key PRE-edit products under the POST-edit digest, poisoning the
        # cache invisibly to the C18b gate (test_straddled_build_cannot_poison_the_cache pins this).
        # C18b (A3): snapshot the cumulative cache counters so this survey's PER-SURVEY delta can be
        # logged after its products are emitted (all of a survey's cache reads/writes happen within
        # this one iteration — the parse gets in process_edis and the xml gets in _emit_served_xml).
        _c0 = (build_cache.hits, build_cache.misses, build_cache.writes) \
            if (build_cache is not None and build_cache.enabled) else None
        # C25: survey-scoped gate output (structured drops + per-station frame notes) — collected
        # by process_edis, fed into build_report.json + the NOTICE log below.
        _gate_report: dict = {}
        # `station_ids` keys are EDI source FILENAMES, and both the key check and the application
        # live in the EDI arm below. On the MTH5 arm the block can never be honoured, so a package
        # carrying one there was a silent WHOLE-BLOCK no-op with no diagnostic: the stations publish
        # under their raw identifiers while the custodian believes they were renamed. Reachable via
        # `--input-format mth5` (which forces this arm even on a package that DOES contain EDIs) and
        # via any MTH5-only package built with --no-validate. Fail closed, survey granularity, like
        # every other invalid shape of the block. The emtfxml arm needs no guard: it falls through to
        # the else, where validate_station_ids sees an EMPTY EDI set and fails on the first key.
        if kind == "mth5" and (_station_ids.ids or _station_ids.provenance):
            print(f"SKIP {slug}: station_ids block INVALID: this survey is ingested as MTH5, and "
                  f"station_ids map keys are EDI source filenames inside transfer_functions/edi/, "
                  f"so the block cannot be honoured on this path (fail closed rather than publish "
                  f"the raw identifiers while the block silently does nothing).", file=sys.stderr)
            dropped_surveys.append((label, len(inputs), "station_ids block cannot be honoured on the MTH5 path"))
            continue
        if kind == "mth5":
            stations, tf_rows, sci_rows = process_mth5(inputs, label, org, slug, report=_gate_report)   # MTH5 path not cached
        else:
            # The file-based TF inputs, split by their OWN suffix -- the single derivation of a
            # station's ingest source in this build (never a second guess from `kind`).
            _edi_in = [_p for _p in inputs if Path(_p).suffix.lower() == ".edi"]
            _xml_in = [_p for _p in inputs if Path(_p).suffix.lower() == ".xml"]
            # Station-id override KEY validation, at the point the survey's real EDI set is known and
            # BEFORE a single byte of it is parsed or emitted. A key naming no file in the package is
            # fail-closed: ignoring it would publish that station under its raw DATAID while the
            # custodian believed it renamed, which is precisely the mis-identification the block
            # exists to prevent. THIS survey alone is dropped loudly (rc stays 0, per the C42
            # survey-granularity precedent) and the rest of the corpus builds.
            try:
                stnids.validate_station_ids(_station_ids, _edi_in)
            except stnids.StationIdError as _sie:
                print(f"SKIP {slug}: station_ids block INVALID: {_sie}", file=sys.stderr)
                dropped_surveys.append((label, len(inputs), "station_ids block invalid"))
                continue
            stations, tf_rows, sci_rows = process_edis(_edi_in, label, org, slug, a.extractor,
                                                       cache=build_cache, survey_digest=_survey_digest,
                                                       report=_gate_report, station_ids=_station_ids) \
                if _edi_in else ([], [], [])
            if _xml_in:
                # OWNER PRECEDENCE RULING (2026-08-03): EDI wins per station. The exclusion set is the
                # BASE station ids the EDI pass produced (a disambiguated variant A.lemi still occupies
                # station A), computed with the SAME shared matcher the coordinate policy uses, so the
                # precedence key and the policy key cannot diverge.
                _edi_base = {coordacc.base_station_id(_r.get("id"), _r.get("variant"))
                             for (_p, _r) in stations}
                _xs, _xt, _xsci = process_emtfxml(_xml_in, label, org, slug,
                                                  exclude_ids=_edi_base, report=_gate_report)
                stations += _xs
                tf_rows += _xt
                sci_rows += _xsci
        for _d in _gate_report.get("stations_dropped", []):
            _survey_warnings.append(f"station {_d['station']} SKIPPED by convention gate: {_d['reason']}")
        if not stations:
            n_in = len(inputs)
            print(f"  WARNING: survey '{label}' produced 0 stations from {n_in} input file(s) and "
                  f"was DROPPED from the portal. (Check that mt_metadata could read these EDIs — "
                  f"malformed headers or missing coordinates yield no usable station.)",
                  file=sys.stderr)
            dropped_surveys.append((label, n_in, None))
            continue
        # C42 (fix round 2): validate override ids NOW — at the exact point the REAL station ids
        # exist (the parsed, disambiguated records above, EDI and MTH5 inputs alike) and BEFORE any
        # of this survey's bytes/products are emitted (the canonical store, served XML/EDI copies,
        # bundles, station.json jobs, and the corpus aggregation all come after this line). The
        # validator is the SAME shared matcher station_policy applies with (validate_overrides /
        # base_station_id), so validation and application cannot diverge by construction — the
        # probe-e hole (a stem∪prefix candidate set validating keys the mask never applied) is
        # structurally closed. On failure: THIS survey alone is dropped loudly (rc stays 0), the
        # rest of the corpus builds, and the message lists the survey's real station ids.
        if _coord_overrides:
            try:
                coordacc.validate_overrides(_coord_overrides, stations)
            except coordacc.CoordinatePolicyError as _cpe:
                print(f"SKIP {slug}: coordinate-access policy INVALID — {_cpe}", file=sys.stderr)
                dropped_surveys.append((label, len(stations), "coordinate-access override ids invalid"))
                continue
        _apply_coord_resolution(stations, (meta or {}).get("coord_resolution"))
        # Per-station canonical-conditioning notes (rotation-unknown, source-id preservation, citation
        # provenance). Populated by whichever normalize() pass runs below (canonical store and/or served
        # XML — both take the SAME survey SMETA `meta`, so their notes agree); station.json reads it so
        # the conditioning is persisted even for surveys whose bytes are withheld (no served XML). The
        # canonical store's provenance.json also records this per-station map (not just counts).
        conditioning_notes: dict = {}
        # The canonical store runs over every FILE-based TF input (EDI and EMTF XML alike): normalize()
        # reads both into the same TF object and applies the same round-trip gate. `kind != "mth5"` is
        # the same set `kind == "edi"` selected before EMTF XML became an ingest format.
        if cdir is not None and kind != "mth5":
            n_ok, n_fail, _cver, _cnotes = emit_canonical_store(stations, slug, cdir, survey_meta=meta)
            canonical_ok += n_ok
            canonical_fail += n_fail
            if _cver:
                canonical_versions = _cver
            conditioning_notes.update(_cnotes)
            all_canonical_notes[slug] = _cnotes   # aggregated into the canonical store provenance.json
        # Survey-driven region facet (catalogue r[9]): the survey's declared region, else its country.
        # Replaces the old AU-only state_of() point-in-box, which mislabelled non-AU data; the live
        # Country->Org->Survey tree already groups by survey.yaml country. state_of() now only seeds
        # the AusLAMP raw-mode per-state split, as a last-resort fallback here.
        _region = (meta or {}).get("region") or (meta or {}).get("country") or ""
        for (_p, _r) in stations:
            _r["region"] = _region or _r.get("state", "")
        # Assemble this survey's SMETA entry (the surveys.json/mtcat payload) BEFORE aggregating any of
        # its data into the corpus, so LAYER 2's dry-run can withhold the WHOLE survey cleanly on failure.
        smeta_entry = meta or {"country": "Australia", "org": org, "edi": "ok",
                               "lic": "unknown", "cite": {"au": org, "ti": label, "yr": "", "ve": "", "pb": org}}
        smeta_entry["slug"] = slug  # authoritative survey slug; the portal reads this (no re-derivation)
        # IDCONS D4: annotate the resolution facets from the pid_status cache (no-op when no cache).
        apply_pid_resolution(smeta_entry, pid_status)
        # LAYER 2 (withhold-not-crash at survey granularity): dry-run the EXACT dump the surveys.json /
        # mtcat / collections emit sites do (LAYER 1's _jdump ISO-formats dates, so only a genuinely alien
        # SMETA value reaches this raise). A single survey's un-serialisable metadata must NEVER abort the
        # whole corpus build (the C42 CP3B21 per-station drop precedent, lifted to survey scope): drop
        # THIS survey loudly + record it, and keep building the rest. Done here — before all_stations/tf/sci
        # and surveys_meta gain this survey — so a dropped survey leaves no half-served trace (its catalogue
        # rows never ship without a surveys.json entry, and its per-station station.json jobs are never queued).
        try:
            _jdump(smeta_entry)
        except TypeError as _smeta_exc:
            print(f"SKIP {slug}: survey metadata is not JSON-serializable ({_smeta_exc}) -- survey DROPPED "
                  f"from the portal so the rest of the corpus still builds", file=sys.stderr)
            build_report_surveys[slug] = {
                "stations_built": 0,
                "stations_dropped": [],
                "warnings": [f"survey DROPPED: metadata is not JSON-serializable ({_smeta_exc})"],
                "conditioning": [],
                "frame": [],
                "presence": [],
                "cache": {"digest": (_survey_digest or "")[:12], "hits": 0, "misses": 0, "writes": 0},
                "duration_seconds": round(_time.perf_counter() - _survey_t0, 3),
            }
            dropped_surveys.append((label, len(inputs), f"metadata not JSON-serializable ({_smeta_exc})"))
            continue
        # The ingest source PER STATION, derived from the input file this record was actually parsed
        # from: the one derivation in the build (never re-guessed from `kind`, which names only the
        # survey's primary format and would mislabel a mixed EDI+EMTF-XML survey). Feeds both the
        # build_provenance input_formats set and build_report's per-station ingest_sources.
        _ingest_sources = {r["id"]: _INGEST_SOURCE_BY_SUFFIX.get(Path(p).suffix.lower(), "unknown")
                           for (p, r) in stations}
        input_formats.update(_ingest_sources.values())
        all_stations += stations; all_tf += tf_rows; all_sci += sci_rows
        surveys_meta[label] = smeta_entry
        lic = (meta or {}).get("lic", "unknown")
        # NCI storage tier (optional, per-survey): if the survey declares nci_base, its downloadable
        # artifacts resolve to that NCI THREDDS fileServer dir (tier=nci) instead of the repo. The
        # local copies are still written (integrity source + git fallback); only the manifest URL
        # changes. Default (no nci_base) = git/Pages, exactly as before.
        nci_base = (meta or {}).get("nci_base")
        if nci_base and not str(nci_base).strip().startswith(("http://", "https://")):
            # Defence-in-depth (the surveys validator FAILs this first): never concatenate an
            # arbitrary-scheme value into a published manifest URL. Drop a non-http(s) nci_base to the
            # repo tier, loudly, rather than emitting e.g. a file:/javascript: download link.
            print(f"WARNING: survey '{label}' nci_base is not an http(s) URL ({nci_base!r}); ignoring it "
                  f"-- this survey's downloads stay on the repo tier.", file=sys.stderr)
            _survey_warnings.append(f"nci_base is not an http(s) URL ({nci_base!r}); downloads stay on "
                                    f"the repo tier")
            nci_base = None
        # C1 access gate (ORTHOGONAL to the licence gate): a survey must be access.level=open AND not under
        # an active embargo to have its bytes distributed. metadata_only/embargoed surveys stay fully in the
        # discovery surfaces (catalogue/tf/sci/surveys/mtcat) below — only the bytes are withheld here. The
        # canonical store (--canonical-dir) is a curator-only artifact (not written into the served build) and
        # is emitted regardless. The --products tree, HOWEVER, IS a distribution surface: deploy/Makefile
        # writes products/ INSIDE the served build dir (D1), so its per-station station.json/dimensionality.json
        # ride this SAME gate — C1c withholds the derived TF science for a non-served survey (see
        # _write_station_products). meta is SMETA (access + embargo_until).
        _acc = access_serve_state((meta or {}).get("access", "open"), (meta or {}).get("embargo_until"))
        for _w in _acc["warnings"]:
            print(f"WARNING: survey '{label}': {_w}", file=sys.stderr)
            _survey_warnings.append(_w)   # structured access-gate warnings -> build_report.json
        # survey-metadata.json: capture this survey's emission job (raw yaml side channel + SMETA + the
        # SAME serve state the byte gate uses, never re-derived). A --raw entry has no yaml and no job.
        if label in survey_yaml_by_label:
            _survey_metadata_jobs[label] = (slug, survey_yaml_by_label[label], smeta_entry, bool(_acc["served"]))
        # C1b: the DISPLAY-product gate keys on the ACCESS state ALONE (not can_serve). A survey may be
        # access=open yet non-redistributably licensed (or built with --no-bundle-edi): that survey's bytes
        # are withheld by the licence/flag gate but its curves SHOULD still plot (open-access preview). Only
        # a NON-OPEN ACCESS state (embargoed/metadata_only/unrecognised) withholds the derived display data.
        if not _acc["served"]:
            withheld_ids.update(r["ausmt_id"] for (_p, r) in stations)
        # Only the FILE-based TF inputs are byte-copied. `kind != "mth5"` is the same set `kind ==
        # "edi"` selected before EMTF XML became an ingest format; it now also admits the XML path,
        # whose served EDI is normalize()-generated rather than copied (see _derived_edis below).
        can_serve = a.bundle_edi and redistributable(lic) and kind != "mth5" and _acc["served"]
        xml_written = {}
        h5_written = {}      # tier 1: {station_id: h5_path} for the per-station MTH5 (flag-gated)
        _xml_failures = {}   # {station_id: exception-class} per-station EMTF-XML emission failures (report)
        _derived_edis = {}   # {station_id: generated-EDI path} for EMTF-XML-sourced stations
        # Per-survey EDI dir, NAMESPACED by slug (like out/xml/<slug>/ and out/bundles/) so two surveys
        # that reuse an EDI basename (e.g. both ship 01.edi) cannot overwrite each other in a flat tree —
        # which would also corrupt the path-keyed sha256 cache. ausmt_id is unique but basenames are not.
        sedir = edidir / slug
        if can_serve:
            sedir.mkdir(parents=True, exist_ok=True)
            # Derived EMTF XML is the SAME redistribution as the EDI (same TF data), so it rides the
            # same license gate; served into out/xml/<slug>/ as a downloadable format.
            # Every custodian EDI basename this survey could serve, reserved BEFORE a single generated
            # EDI is named, so a generated file cannot land on one. Reserved unconditionally, including
            # for stations the coordinate gate will withhold: a generated filename must not depend on
            # access policy, or editing an override would silently rename a published download.
            _reserved_edi_names = {Path(_p).name for (_p, _r) in stations
                                   if Path(_p).suffix.lower() == ".edi"}
            xml_written, _xnotes, _xstamped, _xml_failures, _derived_edis = _emit_served_xml(
                stations, slug, out / "xml" / slug, survey_meta=meta,
                cache=build_cache, survey_digest=_survey_digest,
                coord_default=_coord_default, coord_overrides=_coord_overrides,
                derived_edi_dir=sedir, reserved_edi_names=_reserved_edi_names)
            # If the canonical-store pass did not run (no --canonical-dir) these are the only notes; merge
            # (both passes agree, so update is idempotent) so station.json carries conditioning either way.
            for _sid, _nl in _xnotes.items():
                conditioning_notes.setdefault(_sid, _nl)
            # C18b (A3/A4): record this served survey's digest stamps. yaml_digest_current is the
            # digest of the bytes this build's metadata was parsed from (the discovery single read);
            # xml_digest_stamped is per-station the digest each served XML was keyed/produced under
            # (fresh => this build's digest; cache hit => the entry's stored digest). A survey served
            # under a stale cache entry surfaces the stale digest here — and a STRADDLED build (yaml
            # edited mid-build) surfaces as yaml_digest_current != live — where verify.py catches both.
            survey_digests_sidecar[slug] = {
                "yaml_digest_current": _survey_digest,
                "xml_digest_stamped": _xstamped,
            }
            # ---- tier 1: one <station>.h5 per served station (owner ruling 2026-08-02) ----
            # Inside `can_serve`, so an embargoed or non-served survey emits nothing, identically to
            # its EDI. The station list is filtered by the SAME per-station coordinate byte gate the
            # EDI copy loop and the tier-2 bundle apply (C42 F1: an MTH5 rebuilt from the RAW source
            # carries the true lat/lon/elev in its own metadata, which is exactly how the survey
            # bundle leaked one before it was gated), so a generalised or withheld station gets no
            # file, no manifest row and no bytes. NOT cached: the C18 cache stores the pre-mask parse
            # and the served XML only, and an HDF5 file is not byte-reproducible anyway.
            if flags["station_h5_enabled"]:
                h5_written = emit_station_mth5(
                    [(_p, _r) for (_p, _r) in stations
                     if coordacc.coordinates_served(coordacc.station_policy(
                         _coord_default, _coord_overrides, _r.get("id"), _r.get("variant")))],
                    slug, label, out / "h5" / slug, smeta=meta)
        # C18b (A3): one per-survey instrumentation line (the delta of this survey's cache activity vs
        # the snapshot at the top of the iteration). digest=<first12> ties the log to the sidecar so an
        # operator reading the build log sees, per survey, which digest keyed it and how it hit/missed.
        # The corpus-total "C18 cache [...]" line below is UNCHANGED (tests pin it).
        if _c0 is not None:
            _dh = build_cache.hits - _c0[0]
            _dm = build_cache.misses - _c0[1]
            _dw = build_cache.writes - _c0[2]
            print(f"C18 survey {slug}: digest={(_survey_digest or '<none>')[:12]} "
                  f"hits={_dh} misses={_dm} writes={_dw}", file=sys.stderr)
        served_edis = []
        # Source-bytes integrity ledger for THIS survey (build_report.source_integrity). `checked`
        # counts the EDI-sourced stations whose bytes were actually copied into the served tree;
        # `verified` counts those whose served copy re-hashed equal to the supplied file. A build
        # where checked == verified and mismatches == [] is the machine-readable form of the promise
        # AusMT makes to a third-party custodian.
        _integrity: dict = {"checked": 0, "verified": 0, "mismatches": []}
        # C46-W3a: the survey's custodian of record for manifest rows — the declared attribution.custodian
        # (rights-holder, may differ from the acquiring organisation), else the organisation. Computed once.
        _custodian = (((meta or {}).get("attribution") or {}).get("custodian") or org)
        # runs[] inputs: this survey's >INFO extraction (per station, off the cached parse) and its
        # persistent run-id store. The assembly runs HERE rather than at the deferred write, so its
        # curation notes can reach this survey's build_report entry; the coordinate mask that runs
        # between touches nothing a run carries.
        _run_facts_by_station = _gate_report.get("run_facts", {})
        # Read from the PACKAGE, not from a label-keyed side channel: two packages may legitimately
        # publish under one display label, and the store belongs to the directory it sits in.
        try:
            _survey_run_ids = runids.load(pkgdir) if pkgdir else {}
        except runids.RunIdError as _rie:
            print(f"  {slug}: run-id store IGNORED ({_rie}); this survey publishes no runs[]",
                  file=sys.stderr)
            _survey_warnings.append(f"run-id store IGNORED ({_rie}); no runs[] published")
            _survey_run_ids = {}
        _run_notes: list = []
        # The verified-resource register (--ts-index), read OFFLINE from a ROOT of per-survey files
        # (rule 14). UNLIKE the run-id store this is HARD: the store is a nice-to-have whose absence
        # costs a station its runs[], while a register row is a ROUTE to bytes on another host, so a
        # register the build cannot read whole stops the build instead of publishing the part of it
        # that happened to parse. Read by PACKAGE DIRECTORY NAME for the run-id store's reason (two
        # packages may declare one slug), against this package's own published station ids, which is
        # what makes an unmatched row loud rather than silently dropped.
        _pkgname = Path(pkgdir).name if pkgdir else ""
        try:
            _ts_index = (tsindex.load(a.ts_index, _pkgname, {r["id"] for (_p, r) in stations})
                         if (a.ts_index and _pkgname) else {})
        except tsindex.TsIndexError as _tie:
            print(f"ERROR: {_pkgname}: {_tie}", file=sys.stderr)
            print("Fix the register (or drop --ts-index) and re-run.", file=sys.stderr)
            return 2
        if _ts_index:
            _ts_all = [row for rows in _ts_index.values() for row in rows]
            print(f"  {_pkgname}: ts-index register: {len(_ts_index)} station(s), {len(_ts_all)} "
                  f"row(s), {len([row for row in _ts_all if row['review'] == 'verified'])} verified",
                  file=sys.stderr)
        # The A4 stamp: EXISTENCE follows the register for EVERY station, withheld included (R13);
        # route detail is a different assertion class answered per surface from _tsproject, so the
        # stamp carries no url_path, no bytes, nothing an access gate would need to strip.
        for (_p2, _r2) in stations:
            if tsproject.station_flag(_ts_index.get(_r2["id"])):
                _r2["has_ts"] = True
        # resources[]: the survey's placeable containing-collection identifiers, and the rows this
        # lane REFUSES to place. A refusal is reported, never silently dropped: an unplaceable row
        # would publish a wrong citation claim, and a curator is the only one who can fix it.
        _collection_ids[slug], _collection_declined = station_collection_identifiers(meta)
        if _collection_declined:
            _survey_warnings.append(
                f"{len(_collection_declined)} related_identifiers row(s) are NOT placeable as "
                f"containing-collection identifiers and are omitted from resources[] "
                f"[{'; '.join(_collection_declined)}]")
        # product contract per station + manifest + (optional, license-gated) EDI/XML copies
        for (p, r), srow in zip(stations, sci_rows):
            # C42 per-station byte gate: a non-exact (generalised/withheld) station's SOURCE bytes are
            # NEVER served — the EDI + EMTF-XML carry the true position in too many corners to redact
            # trustworthily (D3), so the file is withheld, not rewritten. `can_serve` is the survey-scoped
            # scalar (license/access/flag); this ANDs in the per-station coordinate policy. A withheld EDI
            # cascades: no served copy, no manifest row, no zip entry, no available_id (the derived-EDI/XML
            # zips + manifest all build from these copy/emit sites).
            _cserved = coordacc.coordinates_served(
                coordacc.station_policy(_coord_default, _coord_overrides, r.get("id"), r.get("variant")))
            # Where THIS station's served EDI comes from depends on its OWN source format:
            #  - EDI source: the custodian's file, copied byte-for-byte (it is the citable record).
            #  - EMTF-XML source: no custodian EDI exists, so the served EDI is the one normalize()
            #    generated and round-trip verified while writing the canonical XML. A station whose
            #    canonical emission FAILED has neither (the failure is already recorded in
            #    build_report's xml_failures), so it serves NO bytes, never a quietly-unverified
            #    copy of the submitted XML under an .edi name.
            served_edi = None
            if can_serve and _cserved:
                if Path(p).suffix.lower() == ".edi":
                    served_edi = sedir / p.name
                    _copy_source_bytes(Path(p), served_edi)
                    # SOURCE-BYTES INTEGRITY GATE. AusMT's whole no-editing posture for third-party
                    # data is one claim: what we serve for an EDI-sourced station is byte-for-byte
                    # what the custodian supplied. Assert it here, over the bytes ACTUALLY on disk in
                    # the served tree, rather than trusting the copy. On a mismatch the station
                    # serves NOTHING: the file is removed (the served tree is handed out by path, so
                    # leaving it would publish bytes we have just declared unverified), no manifest
                    # row is emitted, and the failure is recorded in build_report.source_integrity.
                    _src_digest = sha256(Path(p))
                    _served_digest = hashlib.sha256(served_edi.read_bytes()).hexdigest()
                    _integrity["checked"] += 1
                    if _served_digest == _src_digest:
                        _integrity["verified"] += 1
                    else:
                        _integrity["mismatches"].append(
                            {"station": r["id"], "file": Path(p).name,
                             "source_sha256": _src_digest, "served_sha256": _served_digest})
                        print(f"  INTEGRITY FAIL {Path(p).name} [{r['id']}]: the served copy is NOT "
                              f"byte-identical to the supplied file (source {_src_digest[:12]}, "
                              f"served {_served_digest[:12]}); serving NOTHING for this station.",
                              file=sys.stderr)
                        try:
                            served_edi.unlink(missing_ok=True)
                        except OSError as _ue:
                            print(f"  INTEGRITY FAIL {r['id']}: could NOT remove the non-identical "
                                  f"{served_edi.name} ({type(_ue).__name__}); it is unmanifested but "
                                  f"still on disk", file=sys.stderr)
                        served_edi = None
                else:
                    _gen = _derived_edis.get(r["id"])
                    served_edi = Path(_gen) if (_gen and Path(_gen).exists()) else None
            if served_edi is not None:
                available_ids.add(r["ausmt_id"])
                served_edis.append(served_edi)
                # One file, one owner (see _claim_served_artifact): the served-EDI directory is the
                # one place two naming schemes meet, but the invariant is checked over every
                # per-station artifact so no future emitter can reintroduce the class.
                _claim_served_artifact(_artifact_claims, _artifact_collisions,
                                       served_edi, r["ausmt_id"], "edi")
                _edi_rel = f"edi/{slug}/{served_edi.name}"
                manifest["files"].append(_file_row(r["ausmt_id"], label, r["id"], "edi",
                                                    served_edi, _edi_rel, lic,
                                                    nci_base=nci_base, base_url=base_url,
                                                    custodian=_custodian))
                _served_formats.setdefault(r["ausmt_id"], {})["edi"] = _edi_rel
            if can_serve and _cserved:
                _xmlp = xml_written.get(r["id"])
                if _xmlp and Path(_xmlp).exists():
                    _claim_served_artifact(_artifact_claims, _artifact_collisions,
                                           Path(_xmlp), r["ausmt_id"], "emtfxml")
                    _xml_rel = f"xml/{slug}/{Path(_xmlp).name}"
                    manifest["files"].append(_file_row(r["ausmt_id"], label, r["id"], "emtfxml",
                                                        Path(_xmlp), _xml_rel,
                                                        lic, nci_base=nci_base, base_url=base_url,
                                                        custodian=_custodian))
                    _served_formats.setdefault(r["ausmt_id"], {})["emtfxml"] = _xml_rel
                # Tier 1: the row exists only for a station the writer actually shipped, so a station
                # whose h5 was withheld by the round-trip gate is absent from the manifest rather than
                # advertised as a 404 (the same rule the EMTF-XML row above follows).
                _h5p = h5_written.get(r["id"])
                if _h5p and Path(_h5p).exists():
                    _claim_served_artifact(_artifact_claims, _artifact_collisions,
                                           Path(_h5p), r["ausmt_id"], "mth5")
                    _h5_rel = f"h5/{slug}/{Path(_h5p).name}"
                    manifest["files"].append(_file_row(r["ausmt_id"], label, r["id"], "mth5",
                                                        Path(_h5p), _h5_rel,
                                                        lic, nci_base=nci_base, base_url=base_url,
                                                        custodian=_custodian))
                    _served_formats.setdefault(r["ausmt_id"], {})["mth5"] = _h5_rel
            # THE HAND-OFF GATE, on the SAME two already-computed scalars the byte gate ANDs and never
            # a second derivation of either: the survey's access-serve state and this station's
            # coordinate policy. NOT `can_serve`, which also carries the licence and --bundle-edi
            # gates: those govern bytes AUSMT redistributes, and these bytes are the archive's, served
            # under its own terms. The coordinate arm is what matters here - a raw time series carries
            # the true position in every corner the C42 mask exists to withhold, so a generalised or
            # position-withheld station hands off nothing even though its survey is open.
            if _acc["served"] and _cserved and _ts_index.get(r["id"]):
                _ts_rows[r["ausmt_id"]] = _ts_index[r["id"]]
            # C42: DEFER station.json/dimensionality.json to after the mask (see _station_product_jobs
            # above). The job captures this station's SHARED record `r` (masked in place downstream), its
            # science row, and the survey context needed to render - nothing here depends on cross-survey
            # state that changes after this iteration (conditioning_notes is this survey's own dict). The
            # per-station coordinate byte-gate (_cserved) is captured too: even inside a served survey, a
            # non-exact station's EDI is withheld, so station.json's distribution must not advertise it.
            # C1c: the SURVEY access-serve state (_acc["served"], the SAME result the byte gate and the
            # C1b tf/sci withholding use, never re-derived) is captured so the deferred emitter withholds
            # the derived science products for a non-served survey, exactly as tf.json/sci.json are.
            # edi_served is the ACTUAL served-EDI outcome for this station, not the gate alone:
            # an EMTF-XML-sourced station whose canonical emission failed passes both gates yet
            # has no EDI to advertise, and station.json's distribution must not claim one.
            # D7: the job is queued for EVERY station, not only under --products; station.json is a
            # public contract and the write path below publishes it at the served root regardless.
            _runs, _rnotes = station_runs(_run_facts_by_station.get(r["id"]), _survey_run_ids,
                                          r["id"], r.get("comps"))
            _run_notes += _rnotes
            _station_product_jobs.append(
                (r, srow, label, org, meta, lic, slug, p,
                 (f"edi/{slug}/{served_edi.name}" if served_edi is not None else None),
                 conditioning_notes, bool(_acc["served"]), _runs))
        # ---- per-survey bundles (served surveys only): pre-zipped EDIs + optional survey MTH5 ----
        if can_serve and served_edis:
            # C6: rights travel with the bytes — build a deterministic LICENSE.txt for the zip. Licensor =
            # the survey custodian org; year = the survey's date range (drop the license year to a single
            # 4-digit token so a "2009–2011" range prints "2011"); attribution from the SMETA cite block.
            _dates = (meta or {}).get("dates") or ""
            _yr = "".join(ch for ch in _dates if ch.isdigit())[-4:] if _dates else ""
            _cite = (meta or {}).get("cite") or {}
            _attn = " ".join(x for x in [_cite.get("au") or org, f"({_yr})" if _yr else "",
                                         _cite.get("ti") or label] if x).strip() or None
            # C46: thread the survey's attribution/sources blocks + a changes descriptor into the
            # instrument. `derived_products` keys on THIS survey's ACTUAL derived-rendition emission
            # (served EMTF XML and/or the MTH5 bundle) — not a hardcode: when the build emits neither,
            # changes.made defaults off. The attribution/sources blocks ride on SMETA (dormant until a
            # survey carries them); the gw-runner reads the SAME blocks from the raw survey.yaml, and both
            # go through instrument_params_from_survey so the two instruments state identical rights.
            from _license_text import instrument_params_from_survey  # stdlib leaf (imported at module load)
            _derived = (bool(xml_written) or bool(flags.get("survey_h5_enabled"))
                        or bool(h5_written))
            _p = instrument_params_from_survey(
                attribution_block=(meta or {}).get("attribution"),
                sources_block=(meta or {}).get("sources"),
                derived_products=_derived, synthesized_attribution=_attn)
            _lic_txt = license_instrument_text(lic, org, _yr, **_p)
            _zrel, _zpath = _emit_survey_edi_zip(served_edis, slug, out, license_txt=_lic_txt)
            if _zpath:
                manifest["bundles"].append(_bundle_row(label, slug, "edi-zip", _zpath, _zrel,
                                                        lic, len(served_edis),
                                                        nci_base=nci_base, base_url=base_url,
                                                        custodian=_custodian))
                _bundle_formats.setdefault(slug, {})["edi-zip"] = _zrel
            # C32 §1.1: per-survey EMTF-XML zip — unconditional (like the EDI zip) whenever served XML
            # exists. n_stations = the number of XMLs bundled (the round-trip-verified set), not the
            # station count, so it stays honest if a station had no servable XML.
            _xsrc = [xml_written[r["id"]] for (_pp, r) in stations if xml_written.get(r["id"])]
            _xrel, _xpath = _emit_survey_xml_zip(_xsrc, slug, out, license_txt=_lic_txt)
            if _xpath:
                manifest["bundles"].append(_bundle_row(label, slug, "xml-zip", _xpath, _xrel,
                                                        lic, len(_xsrc),
                                                        nci_base=nci_base, base_url=base_url,
                                                        custodian=_custodian))
                _bundle_formats.setdefault(slug, {})["xml-zip"] = _xrel
            if flags["survey_h5_enabled"]:
                # C42 (F1): emit_survey_mth5 rebuilds the bundle by RE-READING the RAW source files
                # (TF(fn=...)), bypassing the masked record entirely — an unfiltered station list served
                # a withheld station's exact lat/lon/elev inside the h5 while every JSON surface was
                # correctly null (the leak-sweep's HDF5 leg pins this). Filter to the byte-gated
                # exact-only set (the same per-station predicate as the EDI copy loop above): the
                # non-exact contribution is WITHHELD from the bundle — never rewritten (D3 posture).
                _h5_stations = [(p, r) for (p, r) in stations
                                if coordacc.coordinates_served(coordacc.station_policy(
                                    _coord_default, _coord_overrides, r.get("id"), r.get("variant")))]
                if _MTH5_POOL is not None:
                    # Pool build: submit the bundle write and move on, so it overlaps the NEXT
                    # survey's station fan-out. An EMPTY row is reserved here so the manifest keeps
                    # the serial build's exact row order; the resolver after the loop fills it (or
                    # leaves it empty for the withheld filter) and writes the LICENSE sidecar then.
                    _hpath = out / "bundles" / f"{slug}-tf.h5"
                    _row: dict = {}
                    manifest["bundles"].append(_row)
                    _deferred_bundles.append({
                        "fut": _MTH5_POOL.submit(
                            _mth5_write_task, [(str(p), r) for (p, r) in _h5_stations],
                            slug, label, str(_hpath), meta),
                        "row": _row, "slug": slug, "label": label, "lic": lic,
                        "lic_txt": _lic_txt, "hpath": _hpath, "custodian": _custodian,
                        "nci_base": nci_base})
                else:
                    _hrel, _hpath, _hn = emit_survey_mth5(_h5_stations, slug, label, out, smeta=meta)
                    if _hpath:
                        manifest["bundles"].append(_bundle_row(label, slug, "mth5", _hpath, _hrel,
                                                               lic, _hn, nci_base=nci_base, base_url=base_url,
                                                               custodian=_custodian))
                        _bundle_formats.setdefault(slug, {})["survey-mth5"] = _hrel
                        # C46-W3a: rights must travel with the MTH5 bytes too. The survey MTH5 ships as a bare
                        # file (bundles/<slug>-tf.h5, NOT a zip - HDF5 embeds timestamps so it is not
                        # byte-reproducible), so the SAME LICENSE.txt instrument is written BESIDE it as a
                        # sidecar (bundles/<slug>-tf.LICENSE.txt). Identical bytes to the zip-internal LICENSE.txt.
                        (_hpath.parent / f"{slug}-tf.LICENSE.txt").write_text(_lic_txt, encoding="utf-8")

        # ---- survey-level conditioning NOTICE (Deliverable 1) + build_report entry (Deliverable 2) ----
        # ONE line per DISTINCT conditioning note (not one near-identical line per station — the
        # ~792-line survey-boilerplate noise a ~1100-station rebuild exposed), from the SHARED
        # aggregation that also drives the report below, so the log and the report can never disagree.
        for _cline in conditioning_log_lines(slug, conditioning_notes):
            print(_cline, file=sys.stderr)
        # C25 frame/convention NOTICE lines: same one-line-per-distinct-note discipline, separate
        # prefix and a separate build_report field — frame facts must never masquerade as
        # canonical-XML conditioning (station.json keeps them apart the same way).
        _frame_notes_by_station = _gate_report.get("frame_notes", {})
        for _fline in conditioning_log_lines(slug, _frame_notes_by_station, prefix="[frame]"):
            print(_fline, file=sys.stderr)
        # Presence rule (gate 15), the same discipline again: what the parse carried as an
        # mt_metadata default rather than a source assertion. Its own prefix and its own report
        # field, because a library default is not a conditioning decision AusMT made.
        _presence_notes_by_station = _gate_report.get("presence_notes", {})
        for _pline in conditioning_log_lines(slug, _presence_notes_by_station, prefix="[presence]"):
            print(_pline, file=sys.stderr)
        # Convention WARNs (one off-diagonal out of quadrant) are survey-level warnings in the
        # report — the honest "look at this" surface. Derotation/insufficient/unverifiable notes
        # stay in `frame` (they are recorded facts, not warnings).
        for _fe in conditioning_report(_frame_notes_by_station):
            if _fe["note"].startswith("convention:") and "outside its expected quadrant" in _fe["note"]:
                _survey_warnings.append(f"{_fe['note']} — {_fe['count']} station(s): "
                                        f"{_fe['stations'] or _fe['except'] or _fe['count']}")
        # Per-station EMTF-XML emission failures. What such a station still serves depends on its ingest
        # source, so that is stated once where it is computed (see _consequence below) rather than here.
        # A structured xml_failures list (station + exception class) PLUS a counted survey warning, so an
        # otherwise green build can never hide this class of gap (the 8-survey/~380-station regression that shipped
        # 1182 EDI rows but only 732 EMTF-XML rows, invisible behind a printed '[xml] WARN'). Aggregated
        # by exception class for the warning; the full station->class map rides the xml_failures field.
        _xml_fail_rows = [{"station": _sid, "error": _cls} for _sid, _cls in sorted(_xml_failures.items())]
        if _xml_fail_rows:
            _fail_by_cls: dict = {}
            for _row in _xml_fail_rows:
                _fail_by_cls.setdefault(_row["error"], []).append(_row["station"])
            _cls_summary = ", ".join(f"{_c} x{len(_ids)}" for _c, _ids in sorted(_fail_by_cls.items()))
            # The CONSEQUENCE differs by ingest source, so the warning must not state one for both: an
            # EDI-sourced station falls back to serving its custodian EDI, but an EMTF-XML-sourced one
            # has no EDI behind it and serves NOTHING. Saying "served as EDI-only" for the latter would
            # advertise a file that does not exist.
            _fail_xml_src = [_row["station"] for _row in _xml_fail_rows
                             if _ingest_sources.get(_row["station"]) == "emtfxml"]
            _consequence = "served as EDI-only (no XML download)"
            if _fail_xml_src:
                _consequence = (f"{len(_xml_fail_rows) - len(_fail_xml_src)} served as EDI-only; "
                                f"{len(_fail_xml_src)} were EMTF-XML-sourced and serve NO bytes at all "
                                f"({', '.join(_fail_xml_src)})")
            _survey_warnings.append(f"EMTF-XML emission failed for {len(_xml_fail_rows)} station(s) "
                                    f"[{_cls_summary}]; {_consequence}")
        # >INFO JSON delimiter fallback: a counted survey WARNING as well as the structured ledger,
        # same discipline as xml_failures and the integrity gate. These stations parsed only from a
        # normalised TEMPORARY copy, so a curator should know the custodian's file trips a reader
        # defect -- while the bytes AusMT serves for them are still the custodian's, unmodified.
        _parse_fallback_rows = list(_gate_report.get("parse_fallbacks", []))
        if _parse_fallback_rows:
            _survey_warnings.append(
                f"mt_metadata could not read {len(_parse_fallback_rows)} source file(s) directly "
                f"(>INFO JSON trailing-delimiter defect); each was reparsed from a normalised "
                f"TEMPORARY copy and its unmodified source bytes are what is served "
                f"[{', '.join(_row['file'] for _row in _parse_fallback_rows[:8])}"
                f"{', ...' if len(_parse_fallback_rows) > 8 else ''}]")
        # runs[] curation gaps: a station whose source asserts an acquisition fact but whose run id
        # the store does not carry publishes NO runs, and that silence must not hide behind a green
        # build. Same counted-warning shape as the fallbacks above, worst case first.
        if _run_notes:
            _survey_warnings.append(
                f"{len(_run_notes)} run-metadata curation note(s) for this survey "
                f"[{'; '.join(_run_notes[:8])}{'; ...' if len(_run_notes) > 8 else ''}]")
        # Source-bytes integrity: a counted survey WARNING as well as the structured ledger, so a
        # mismatch can never hide behind an otherwise-green build (the xml_failures lesson).
        if _integrity["mismatches"]:
            _survey_warnings.append(
                f"served EDI bytes were NOT identical to the supplied file for "
                f"{len(_integrity['mismatches'])} station(s) "
                f"[{', '.join(m['station'] for m in _integrity['mismatches'])}]; each serves no "
                f"bytes at all")
        build_report_surveys[slug] = {
            "stations_built": len(stations),
            # C25: convention-gate skips are STRUCTURED drops ({station, reason}); the legacy
            # unusable-EDI print+continue path still records nothing here (per the original brief).
            "stations_dropped": list(_gate_report.get("stations_dropped", [])),
            "tipper_masked": list(_gate_report.get("tipper_masked", [])),
            "warnings": list(_survey_warnings),
            # Per-station EMTF-XML emission failures (empty when every served station's XML emitted).
            "xml_failures": _xml_fail_rows,
            # Per-station record of the >INFO JSON delimiter fallback (empty for every survey whose
            # files mt_metadata reads directly, which is the whole existing corpus). A PROVENANCE
            # fact, not a repair log: the parse came from a normalised temporary copy that no longer
            # exists, while the served bytes and the sha256 columns are the custodian's source file.
            "source_parse_fallbacks": _parse_fallback_rows,
            # The INGEST SOURCE per station (owner ruling 2026-08-03): {station_id: edi|mth5|emtfxml}.
            # A provenance fact, not a summary: for a mixed survey it is the only place that says
            # which stations the EDI precedence rule resolved to EDI and which came from EMTF XML.
            "ingest_sources": dict(sorted(_ingest_sources.items())),
            # The served-bytes integrity gate for EDI-sourced stations (see _integrity above). A
            # GATE, not a comment: a mismatch withholds that station's bytes entirely.
            "source_integrity": {"checked": _integrity["checked"],
                                 "verified": _integrity["verified"],
                                 "mismatches": list(_integrity["mismatches"])},
            # Same shared aggregation as the log lines above: [{note,count,stations|null,except|null}].
            "conditioning": conditioning_report(conditioning_notes),
            # C25: frame/convention notes, same aggregation shape as `conditioning`.
            "frame": conditioning_report(_frame_notes_by_station),
            # The presence rule (gate 15), same aggregation shape again: the mt_metadata defaults
            # this survey's parses carried, which the emitter never publishes as source assertions.
            "presence": conditioning_report(_presence_notes_by_station),
            # The other half of the same provenance question: not what was a library default, but
            # which dialect asserted each real value and how confidently it was read (SCOPE:254-258).
            "run_extraction": run_extraction_report(_run_facts_by_station),
            "cache": ({"digest": (_survey_digest or "")[:12], "hits": _dh, "misses": _dm, "writes": _dw}
                      if _c0 is not None else {"digest": (_survey_digest or "")[:12],
                                              "hits": 0, "misses": 0, "writes": 0}),
            "duration_seconds": round(_time.perf_counter() - _survey_t0, 3),
        }

    # ---- deferred survey-MTH5 bundles (pool builds only): drain in submit order, replaying each
    # task's captured stderr, and fill each reserved manifest row IN PLACE so row order is the
    # serial build's. A bundle the writer withheld (n=0) leaves its row empty; the filter drops the
    # empties so the manifest can never advertise a withheld file (the emit_station_mth5 rule).
    # Ordered strictly BEFORE the QC/mask seam and every manifest/_bundle_formats consumer.
    for _d in _deferred_bundles:
        _n, _err = _d["fut"].result()
        if _err:
            sys.stderr.write(_err)
        if not _n:
            continue
        _dslug, _dhp = _d["slug"], _d["hpath"]
        _drel = f"bundles/{_dslug}-tf.h5"
        _d["row"].update(_bundle_row(_d["label"], _dslug, "mth5", _dhp, _drel,
                                     _d["lic"], _n, nci_base=_d["nci_base"], base_url=base_url,
                                     custodian=_d["custodian"]))
        _bundle_formats.setdefault(_dslug, {})["survey-mth5"] = _drel
        # C46-W3a sidecar, identical to the serial path's (see the in-loop branch).
        (_dhp.parent / f"{_dslug}-tf.LICENSE.txt").write_text(_d["lic_txt"], encoding="utf-8")
    if _deferred_bundles:
        manifest["bundles"] = [_r for _r in manifest["bundles"] if _r]

    # ---- build-time QC over the assembled catalogue (curator-facing) ----
    # Duplicate ausmt_ids are a HARD failure (they break the URL/export/r[12] contract and make
    # station.json files overwrite each other). Everything else is advisory and never blocks —
    # re-occupied sites and ocean-bottom/overseas/Antarctic sites are all legitimate, so the
    # out-of-extent check is per the survey's OWN declared extent, not a national bounding box.
    qc = qc_pass(all_stations, survey_extent)
    # ---- C42 coordinate-access mask seam (D3): the ONE choke point. Ordered strictly AFTER qc_pass
    # (which computed extent/duplicate checks on the TRUE coordinates) and BEFORE any emission below.
    # Masks the SHARED station records in place — withheld => lat/lon/elev null, generalised => 0.1deg
    # cell + elev null — so every downstream emitter (catalogue, mtcat, collections, the deferred
    # station.json jobs) reads the masked value with no per-emitter logic; and rewrites the coordinate-
    # bearing qc_report fields (outside_declared_extent lat/lon, near_duplicate at_deg) so the served
    # qc_report carries no true-position bits of a non-exact station. The mask output is NEVER cached
    # (the C18 cache stores the pre-mask parse; this runs after every cache read — cache-boundary
    # invariant). A survey with no policy field is all-exact => this is a value-preserving no-op
    # (default-stability pin). An override naming no station raises here (fail-closed).
    _masked_ausmt_ids = coordacc.apply_coordinate_policy_corpus(
        all_stations, lambda lbl: coord_policy.get(lbl, ("exact", {})), qc=qc)
    if _masked_ausmt_ids:
        print(f"C42 coordinate access: {len(_masked_ausmt_ids)} station(s) masked "
              f"(generalised or withheld); their EDI/XML are byte-gated out and positions "
              f"masked in all served surfaces.", file=sys.stderr)
    # ---- deferred per-station station.json/dimensionality.json: run NOW, after the mask, so each
    # station.json `location` carries the post-mask coordinate (D3: products/ is a served surface in
    # deployment). The jobs read the same shared records the mask mutated. D7: station.json lands under
    # out/products unconditionally and under --products as well where that is a different directory.
    # The documents are kept for the self-check below (_validate_station_metadata), which reads the
    # bytes that ship rather than the served file (SCOPE:289-290: no read-back of the public file).
    _station_docs: dict = {}
    for _job in _station_product_jobs:
        _st_name, _st_doc = _write_station_products(_job, PROV, out / "products", prod,
                                                    _served_formats, _bundle_formats, _collection_ids,
                                                    _ts_rows)
        _station_docs[_st_name] = _st_doc
    # ---- survey-metadata.json (the second public contract): one document per survey, AFTER the mask
    # seam (the extent follows the aggregated post-mask coordinate state, D7) and after the station jobs,
    # into out/products/<slug>/ UNCONDITIONALLY (the served root in deployment, independent of
    # --products, D2). The survey's coordinate state is aggregated over its post-mask station records
    # with the SAME rule mtcat projects coordinates_state from (_coordinates_state). The documents are
    # kept in memory for the self-check below (_validate_survey_metadata), which reads the bytes that
    # ship and refuses to publish a non-conforming document.
    _sm_policies: dict = {}
    for (_p, _r) in all_stations:
        _sm_policies.setdefault(_r["survey"], set()).add(_r.get("coord_policy") or "exact")
    _survey_metadata_docs: dict = {}
    for _lbl, (_slug, _y_raw, _smeta, _served) in _survey_metadata_jobs.items():
        _state = _coordinates_state(_sm_policies.get(_lbl), coord_policy.get(_lbl, ("exact", {}))[0])
        _sm_doc = survey_metadata_document(_lbl, _y_raw, _smeta, _served, _state, prov=PROV)
        _sm_dir = out / "products" / _slug
        _sm_dir.mkdir(parents=True, exist_ok=True)
        (_sm_dir / "survey-metadata.json").write_text(_jdump(_sm_doc, indent=1), encoding="utf-8")
        _survey_metadata_docs[_slug] = _sm_doc
    print("QC: "
          f"duplicate-ids {len(qc['duplicate_ausmt_ids'])} | coord-flagged {len(qc['coord_flags'])} | "
          f"coord-conflicts {len(qc['coord_conflicts'])} | near-duplicate-locations {len(qc['near_duplicate_locations'])} | "
          f"outside-declared-extent {len(qc['outside_declared_extent'])} | "
          f"no-declared-extent {qc['stations_without_survey_extent']}")
    for d in qc["near_duplicate_locations"]:
        _at = d["at_deg"] if d.get("at_deg") is not None else "(masked)"  # C42: at_deg nulled for a withheld pair
        print(f"  [notice] near-duplicate location ~{_at}: {d['a']} <-> {d['b']}")
    for c in qc["coord_conflicts"]:
        print(f"  [notice] coordinate HEAD/INFO conflict {c['delta_deg']}° in {c['file']} ({c['ausmt_id']})")
    for fl in qc["coord_flags"]:
        print(f"  [notice] coordinate flag '{fl['flag']}'{' (resolved)' if fl['resolved'] else ''} "
              f"in {fl['file']} ({fl['ausmt_id']})")
    for o in qc["outside_declared_extent"]:
        print(f"  [FYI] {o['ausmt_id']} at {o['lat']},{o['lon']} is outside survey '{o['survey']}' declared extent")
    (out / "qc_report.json").write_text(_jdump(qc, indent=1), encoding="utf-8")
    if prod:
        (prod / "qc_report.json").write_text(_jdump(qc, indent=1), encoding="utf-8")
    if qc["duplicate_ausmt_ids"]:
        print(f"ERROR: {len(qc['duplicate_ausmt_ids'])} duplicate ausmt_id(s) — station ids must be "
              f"unique (they key URLs, exports and the catalogue r[12] contract). Offenders:", file=sys.stderr)
        for d in qc["duplicate_ausmt_ids"]:
            print(f"  {d['ausmt_id']}: {d['files'][0]} <-> {d['files'][1]}", file=sys.stderr)
        print("Fix the colliding station ids (or survey slugs) and re-run.", file=sys.stderr)
        return 2
    # A served file claimed by two manifest rows is the same class of failure and is equally HARD:
    # the download contract says a row's sha256 is the integrity of THAT station's artifact, and a
    # shared file makes both rows verify while one station serves the other's transfer function. The
    # sha256 columns cannot catch it, so the build refuses to publish rather than emit it.
    if _artifact_collisions:
        print(f"ERROR: {len(_artifact_collisions)} served artifact(s) claimed by more than one manifest "
              f"row: one file cannot be two stations' download (both rows would carry the same, "
              f"VERIFYING sha256 while one station serves the other's transfer function). Offenders:",
              file=sys.stderr)
        for _col in _artifact_collisions:
            print(f"  {_col['path']}: {_col['first']['ausmt_id']} ({_col['first']['format']}) <-> "
                  f"{_col['second']['ausmt_id']} ({_col['second']['format']})", file=sys.stderr)
        print("Fix the colliding served filenames and re-run.", file=sys.stderr)
        return 2

    # ---- portal projection (compact arrays the portal reads); r[13]=edi_available, r[14]=sha256 ----
    compact, tf_out, sci_out = [], [], []
    for ((p, r), tf, srow) in zip(all_stations, all_tf, all_sci):
        # Build the row keyed by NAME, then PROJECT it in CATALOGUE_COLUMNS order, so the emit order IS
        # the contract: a reorder of contract/columns.json moves the emitted columns in lockstep with the
        # portal's generated C map (no silent producer/consumer divergence). A missing key here is a loud
        # KeyError — i.e. adding a column to the contract without supplying its value fails the build.
        _vals = {"id": r["id"], "survey": r["survey"], "lat": r["lat"], "lon": r["lon"],
                 "period_min_s": r.get("period_min_s"), "period_max_s": r.get("period_max_s"),
                 "n_periods": r.get("n_periods"), "comps": r.get("comps", ""), "type": r.get("type"),
                 "region": (r.get("region") or r.get("state") or "?"),   # survey-driven region facet
                 "file": p.name, "coord_flag": bool(r.get("coord_flag")), "ausmt_id": r["ausmt_id"],
                 "edi_available": 1 if r["ausmt_id"] in available_ids else 0, "sha256": sha256(p),
                 # R4: original pre-sanitisation station/site name, present only when it differs from id.
                 "site_name": r.get("site_name")}
        compact.append([_vals[c] for c in CATALOGUE_COLUMNS])
        # Catalogue row is UNCHANGED for a withheld survey — locations/band/nper/sha256 stay public because
        # DISCOVERY IS UNIVERSAL. Only the DERIVED DISPLAY products (tf curves + science sci fields) are
        # emptied here for a non-served survey (C1b); the withholding is at emission, not client-side.
        if r["ausmt_id"] in withheld_ids:
            tf_out.append(withhold_tf_row(tf)); sci_out.append(withhold_sci_row(srow))
        else:
            tf_out.append(tf); sci_out.append(srow)
    # Contract guard (see docs/docs/developer/data-files.md): these rows are read BY POSITION
    # by the portal, verify.py and contribute.py, so a drifted row width is silent data corruption.
    # Fail the build loudly instead. Update the *_COLUMNS lists + the doc + consumers together.
    # Use an explicit raise, NOT a bare assert: assert is stripped under `python -O`, which would remove
    # the last guard against shipping width-mismatched positional JSON (silent corruption).
    for _label, _rows, _cols in (("catalogue", compact, CATALOGUE_COLUMNS),
                                 ("sci", sci_out, sci.SCI_COLUMNS), ("tf", tf_out, tfmod.TF_COLUMNS)):
        if not all(len(row) == len(_cols) for row in _rows):
            raise ValueError(f"{_label} row width != {len(_cols)} (the positional contract) — regenerate "
                             f"from contract/columns.json; APPEND, never reorder")
    (out / "catalogue.json").write_text(_jdump(compact, separators=(",", ":")), encoding="utf-8")
    # ---- C42 Amendment A1: the coordinate-policy MARKER boot artifact ----
    # The drawer renders from the in-memory catalogue loaded at boot (station.json is never fetched on
    # navigation), so a generalised station's "position generalised" badge needs a boot-loaded signal.
    # Rather than append a positional catalogue COLUMN — which would add a trailing element to EVERY row of
    # EVERY survey and break the zero-change default the record promises for all-exact corpora — emit a
    # SEPARATE optional artifact (the record's A1 sanctions "an equivalent boot artifact"): a compact map
    # ausmt_id -> policy for NON-EXACT stations ONLY. It reuses the policy the mask seam stamped on each
    # record (r["coord_policy"]) — never re-derived from coordinate values — and carries NO coordinate, only
    # the policy string, so the leak-sweep cannot trip on it. Emitted ONLY when at least one station is
    # non-exact, so an all-exact corpus is byte-identical (no new file) — the zero-change default preserved.
    _coord_policy_map = {r["ausmt_id"]: r["coord_policy"]
                         for (p, r) in all_stations
                         if r.get("coord_policy") and r["coord_policy"] != "exact"}
    if _coord_policy_map:
        (out / "coord_policy.json").write_text(
            _jdump(_coord_policy_map, separators=(",", ":")), encoding="utf-8")
        if prod:
            (prod / "coord_policy.json").write_text(
                _jdump(_coord_policy_map, separators=(",", ":")), encoding="utf-8")
    # ---- THREDDS A5: ts_access.json, the ROUTE-DETAIL boot artifact ----
    # {ausmt_id: {level token: {bytes, url_path}}}, beside coord_policy.json and for its stated
    # reason (:5368-5380): the drawer and the exports render from the boot-loaded catalogue, and
    # station.json is never fetched on navigation, so a per-level size and route cannot reach the
    # portal any other way. That is what D3 rules and what makes the pointer file portal-generated.
    #
    # THE GUARANTEE IS MEMBERSHIP, NOT SHAPE, and the trade is deliberate: _ts_rows holds only
    # stations that passed the SAME access gate the hand-off rows did, captured at :5187 and never
    # re-derived here, and route_rows() is the ONE predicate every route surface renders from
    # (ts_access, the resource rows, the front-door table), so R5 suppression is one answer rather
    # than three opinions. Every string this adds for an open station is already published in that
    # station's own access_url; a withheld or coordinate-gated station is ABSENT, and the root-level
    # leak sweep is what holds that.
    #
    # Keys sorted at both levels: the register's row order is a curator's habit, and these bytes are
    # not. Emitted ONLY when non-empty, so a corpus with no verified routes stays byte-identical to
    # one built before this artifact existed.
    _ts_access = {}
    for _aid in sorted(_ts_rows):
        # station_open=True: membership in _ts_rows IS the open verdict, applied at the capture site.
        _routes = tsproject.route_rows(_ts_rows[_aid], station_open=True)
        if _routes:
            _ts_access[_aid] = {lvl: dict(sorted(_routes[lvl].items())) for lvl in sorted(_routes)}
    if _ts_access:
        _ts_access_bytes = _jdump(_ts_access, separators=(",", ":"))
        (out / "ts_access.json").write_text(_ts_access_bytes, encoding="utf-8")
        if prod:
            (prod / "ts_access.json").write_text(_ts_access_bytes, encoding="utf-8")
    # ---- C42 Amendment A2: the BASE-STATION-ID surface (boot artifact) ----
    # The C43 stations-panel override fieldset must key by BASE station id — never a file stem, never a
    # variant-suffixed id (D2 fix-round-2, the probe-e discipline). A base id is the record id with its
    # engine-appended processing-variant tag stripped, derivable ONLY via the record's `variant` field
    # (never dot-guessing). No served/boot artifact exposed that (A2 gap), so the workbench could not
    # construct guaranteed-base keys. Emit a compact map ausmt_id -> base_station_id for the VARIANT
    # stations ONLY (those whose served catalogue id differs from their base) via the SAME
    # base_station_id() the mask seam matches with — one derivation, never a re-derivation. A non-variant
    # station is ABSENT: its base IS its catalogue id, so the workbench falls back to that (absent =>
    # every station is its own base). Carries NO coordinate and NO policy — only ids already in the
    # served catalogue — so it is leak-sweep-clean by construction. Emitted ONLY when the corpus has a
    # variant station, so a corpus with no processing variants is byte-identical (no new file) — the
    # default-stability discipline and the A1 only-when-it-carries-information precedent. It is a SEPARATE
    # artifact from coord_policy.json because their membership differs: coord_policy lists NON-EXACT
    # stations; this lists VARIANT stations — a curator setting the FIRST override on a variant station in
    # an all-exact survey needs this base id while that station is (correctly) absent from coord_policy.json.
    _base_id_map = {r["ausmt_id"]: coordacc.base_station_id(r.get("id"), r.get("variant"))
                    for (p, r) in all_stations
                    if coordacc.base_station_id(r.get("id"), r.get("variant")) != r.get("id")}
    if _base_id_map:
        (out / "base_ids.json").write_text(
            _jdump(_base_id_map, separators=(",", ":")), encoding="utf-8")
    (out / "tf.json").write_text(_jdump(tf_out, separators=(",", ":")), encoding="utf-8")
    (out / "sci.json").write_text(_jdump(sci_out, separators=(",", ":")), encoding="utf-8")
    (out / "surveys.json").write_text(_jdump(surveys_meta, separators=(",", ":")), encoding="utf-8")
    # Group surveys into collections ONCE; both collections.json and MTCAT reuse it.
    coll_by_id, _ = _group_collections(surveys_meta, all_stations)
    for _dup in _near_duplicate_collection_ids(list(coll_by_id)):
        print(f"WARNING collections: ids {_dup} differ only by case/whitespace — likely a typo; they form "
              f"SEPARATE collections. Use one exact collection.id across member surveys.", file=sys.stderr)
    (out / "collections.json").write_text(_jdump(collections_document(surveys_meta, all_stations, coll_by_id), separators=(",", ":")), encoding="utf-8")
    # ---- stations.geojson: the corpus as a vector layer (owner ruling 2026-08-02) ----
    # Emitted from the SAME masked records the catalogue projection above reads, so the two documents
    # cannot disagree about where a station is; a withheld station has no geometry and is absent (see
    # stations_geojson). Served beside the other top-level documents and mirrored under products/ like
    # mtcat.json. Both paths are published in docs/docs/reference/index.md. Compact bytes in both
    # copies: a FeatureCollection is read by software, and 1418 features of pretty-printing is dead weight.
    _stations_gj = _jdump(stations_geojson(all_stations, surveys_meta), separators=(",", ":"))
    (out / "stations.geojson").write_text(_stations_gj, encoding="utf-8")
    if prod:
        (prod / "stations.geojson").write_text(_stations_gj, encoding="utf-8")
    # C18: the deterministic cache hit/miss/write tally (design §4.6) — NOT wall-clock timing. Only
    # emitted into build_provenance.json (which already carries a non-deterministic `generated`
    # timestamp, so it is NOT a §4.5 byte-equivalence surface); the served products stay cache-blind.
    _cache_stats = build_cache.counters() if build_cache is not None else {"enabled": False}
    (out / "build_provenance.json").write_text(_jdump(
        {**PROV, "n_stations": len(all_stations), "n_surveys": len(surveys_meta),
         "input_formats": sorted(input_formats) or ["edi"],
         "edi_bundled": bool(available_ids),
         "nci_tier_artifacts": sum(1 for _r in manifest["files"] + manifest["bundles"]
                                   if _r["tier"] == "nci"),
         "distribution_flags": flags, "base_url": base_url,
         "cache": _cache_stats,   # C18 hit/miss/write counters (deterministic build-report evidence)
         # The EFFECTIVE MTH5 worker count (1 = the serial code path ran, whatever was asked), so a
         # build record always says how its h5 bytes were produced.
         "parallel": {"workers": workers},
         # C32 §2: the mt_metadata / mth5 versions this build ran against (additive; a key is absent
         # when that library was not importable in the build environment).
         "mt_metadata_version": LIB_VERSIONS.get("mt_metadata"),
         "mth5_version": LIB_VERSIONS.get("mth5"),
         "source_commit": BUILD_ID["source_commit"]}, indent=1), encoding="utf-8")   # C12: the build<->data handshake
    if build_cache is not None and build_cache.enabled:
        print(f"C18 cache [{_cache_stats['mode']}]: hits={_cache_stats['hits']} "
              f"misses={_cache_stats['misses']} writes={_cache_stats['writes']}")
    # build.json (C12): a small standalone identity document (build_id/engine_commit/source_commit/
    # generated) — deploy/Makefile's rebuild-data names each builds/<timestamp> dir by wall-clock time,
    # not this id, so this file is what lets an operator (or the portal footer) trace a *specific*
    # already-built dir back to the commits that produced it, without re-deriving from build_provenance.
    # C32 §2: additive served-tool version keys alongside the C12 identity fields (build id string
    # format is UNCHANGED — versions ride beside it, never inside the commit-commit-timestamp id).
    (out / "build.json").write_text(_jdump(
        {**BUILD_ID, "mt_metadata_version": LIB_VERSIONS.get("mt_metadata"),
         "mth5_version": LIB_VERSIONS.get("mth5")}, indent=1), encoding="utf-8")

    # ---- build_report.json: structured per-survey build metadata (validated against
    # schema/build_report.schema.json in the self-check below; verify.py re-checks its presence +
    # schema + a cheap manifest cross-count). Public build metadata consumed by the (planned) curator
    # serve-state UI. Reuses the SAME identity helpers build_provenance.json / build.json do
    # (BUILD_ID: engine_commit/source_commit/build_id; PROV: pipeline_version) so the recorded commits
    # cannot drift from the other build docs. `generated` is a fresh UTC stamp (like the other docs). ----
    import datetime as _dt_report  # noqa: PLC0415 (house style: local import where used)
    _report_stations_built = sum(s["stations_built"] for s in build_report_surveys.values())
    _report_warnings = sum(len(s["warnings"]) for s in build_report_surveys.values())
    # peak_rss_mib: the process high-water mark at this point, i.e. after the survey loop (where all
    # the memory is: parse, XML, MTH5) and the station products; the corpus-wide emissions that follow
    # (manifest, mtcat, schema self-check, feed) were measured at ~10 MiB on 1,418 stations. Recorded so
    # the trend is visible build over build and the memory regression pin has a number to read.
    _peak_rss = peak_rss_mib()
    build_report = {
        "generated": _dt_report.datetime.now(_dt_report.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_commit": BUILD_ID["engine_commit"],
        "source_commit": BUILD_ID["source_commit"],
        "build_id": BUILD_ID["build_id"],
        "pipeline_version": PROV["pipeline_version"],
        "peak_rss_mib": _peak_rss,
        "surveys": build_report_surveys,
        "totals": {"surveys": len(build_report_surveys),
                   "stations_built": _report_stations_built,
                   "warnings": _report_warnings},
        # D20, the LOUD skip: the packages the survey validator FAILed and the build skipped (see
        # discover_work). Empty on a clean build; scripts/verify.py FAILs on a non-empty list so
        # `make rebuild-data` never swaps a build that silently lost a survey from every surface.
        "surveys_skipped_validation": sorted(surveys_skipped_validation),
        # The same rule for EVERY other survey-granularity drop (unreadable/non-mapping survey.yaml,
        # invalid coordinate policy or station_ids, zero-station parse, unserialisable SMETA):
        # recorded here, and verify.py FAILs on any entry. Always present; empty on a clean build.
        "surveys_dropped": sorted(
            ({"survey": str(lbl),
              "reason": (reason if reason else f"0 stations from {n} input file(s)")}
             for lbl, n, reason in dropped_surveys), key=lambda e: e["survey"]),
    }
    (out / "build_report.json").write_text(_jdump(build_report, indent=1), encoding="utf-8")
    if _peak_rss is not None:
        # One log line an operator can read off the tail: the number the kernel's OOM killer would
        # have quoted, before it has to.
        print(f"build peak RSS: {_peak_rss:.0f} MiB ({_report_stations_built} stations built)", file=sys.stderr)

    # C18b (A3): the digest-stamp sidecar. out/products/survey_digests.json maps each served survey's
    # slug -> {yaml_digest_current, xml_digest_stamped:{station_id:digest}}. This is the independent
    # observable the verify.py --surveys consistency gate needs to catch a product served under a stale
    # cache digest (the 2026-07-07 incident): it recomputes the LIVE survey.yaml digest and asserts the
    # stamps agree. Emitted for EVERY served survey (non-served/embargoed surveys have no served XML and
    # so no stamps). NOT a §4.5 byte-equivalence surface — the digests are stable inputs, but this file
    # is deliberately kept out of the manifest/mtcat products the cache-equivalence test pins.
    _pdir = out / "products"
    _pdir.mkdir(parents=True, exist_ok=True)
    (_pdir / "survey_digests.json").write_text(
        _jdump(survey_digests_sidecar, indent=1), encoding="utf-8")

    # NCI footgun guard (audit M2): a survey's nci_base points ALL its formats at one flat NCI dir, but
    # AusMT DERIVES the EMTF-XML / EDI-zip / MTH5 — those won't exist at an EDI-only NCI base and would
    # 404. Warn LOUDLY per survey (the curator must verify they were uploaded) so dead links are never
    # emitted silently; the EDIs are assumed already on NCI (the validated "point at existing data" case).
    _nci_derived = {}
    for _r in manifest["files"] + manifest["bundles"]:
        if _r.get("tier") == "nci" and _r.get("format") != "edi":
            _nci_derived.setdefault(_r["survey"], set()).add(_r["format"])
    for _sv, _fmts in sorted(_nci_derived.items()):
        print(f"WARNING: survey '{_sv}' has nci_base set, so AusMT-DERIVED artifacts "
              f"({', '.join(sorted(_fmts))}) are pointed at NCI but were generated by AusMT — verify they "
              f"exist under the survey's nci_base or those downloads will 404 (the EDIs are assumed "
              f"already on NCI).", file=sys.stderr)

    # ---- download manifest (slice #4): the key-based index of every downloadable artifact + its
    # integrity (size/sha256) and tier-resolved URL. Written to BOTH the portal data dir (consumed by
    # the portal's resolver) and --products (curator). Empty build => a valid empty manifest.
    manifest_doc = {"generated_count": len(manifest["files"]) + len(manifest["bundles"]),
                    "base_url": base_url,
                    # SPEC A2: the download manifest self-declares the MTH5/mt_metadata pin its served
                    # bundles were written with, so a consumer of a <slug>-tf.h5 can read the exact library
                    # version from the same index that carries the artifact's size/sha256 (additive keys;
                    # None when the library was not importable in the build env — an EDI-only build).
                    "mth5_version": LIB_VERSIONS.get("mth5"),
                    "mt_metadata_version": LIB_VERSIONS.get("mt_metadata"),
                    "files": manifest["files"], "bundles": manifest["bundles"]}
    (out / "manifest.json").write_text(_jdump(manifest_doc, separators=(",", ":")), encoding="utf-8")

    # ---- MTCAT discovery/federation document (portal owns data; shared minimal metadata) ----
    # MTCAT 1.2 reads the manifest assembled just above so each survey entry can state the formats
    # ACTUALLY distributed for it. The manifest is already complete at this point (both writers below and
    # the file above consume the same object), so this costs one dict pass and no new derivation.
    mtcat = mtcat_document(surveys_meta, all_stations, portal=load_portal_config(a.portal_config),
                           coll_by_id=coll_by_id, manifest_doc=manifest_doc)
    (out / "mtcat.json").write_text(_jdump(mtcat, indent=1), encoding="utf-8")
    # FAIR-I: serve the schema beside the data at BOTH published routes (the ratified $id policy,
    # MTCAT 2.0): data/schemas/mtcat/<version>/mtcat.schema.json is the VERSION-SPECIFIC IMMUTABLE
    # route the schema's own $id names, and data/mtcat.schema.json is the latest-convenience copy
    # that mtcat.json's relative schema_url ("mtcat.schema.json") resolves to - so a harvester can
    # validate without reaching the canonical host, and a pinned consumer can fetch the exact
    # version forever. Byte-copies of the in-tree schema (identical at both routes by
    # construction); skipped (noted, not fatal) if unreadable so a schema-path glitch never fails
    # an otherwise-good build. The version segment derives from MTCAT_SCHEMA_VERSION (the
    # generated mirror of the single-source constant), never a literal.
    _mtcat_schema = HERE.parent / "schema" / "mtcat.schema.json"
    try:
        _schema_bytes = _mtcat_schema.read_bytes()
        (out / "mtcat.schema.json").write_bytes(_schema_bytes)
        _versioned_dir = out / "schemas" / "mtcat" / MTCAT_SCHEMA_VERSION
        _versioned_dir.mkdir(parents=True, exist_ok=True)
        (_versioned_dir / "mtcat.schema.json").write_bytes(_schema_bytes)
    except OSError as _e:
        print(f"note: mtcat schema not served beside data ({type(_e).__name__}: {_e})", file=sys.stderr)
    # The survey-metadata schema (the second public contract, D3): the SAME two routes, by the same
    # rule - data/schemas/ausmt-survey-metadata/<version>/ausmt-survey-metadata.schema.json is the
    # version-specific immutable route the schema's own $id names, data/ausmt-survey-metadata.schema.json
    # the latest-convenience copy beside the data. Byte-copies of the in-tree artifact; the version
    # segment derives from SURVEY_METADATA_SCHEMA_VERSION (the generated mirror), never a literal.
    _sm_schema = HERE.parent / "schema" / "ausmt-survey-metadata.schema.json"
    try:
        _sm_schema_bytes = _sm_schema.read_bytes()
        (out / "ausmt-survey-metadata.schema.json").write_bytes(_sm_schema_bytes)
        _sm_versioned_dir = out / "schemas" / "ausmt-survey-metadata" / SURVEY_METADATA_SCHEMA_VERSION
        _sm_versioned_dir.mkdir(parents=True, exist_ok=True)
        (_sm_versioned_dir / "ausmt-survey-metadata.schema.json").write_bytes(_sm_schema_bytes)
    except OSError as _e:
        print(f"note: survey-metadata schema not served beside data ({type(_e).__name__}: {_e})", file=sys.stderr)
    # The station schema (the third public contract): the SAME two routes, by the same rule -
    # data/schemas/ausmt-station/<version>/ausmt-station.schema.json is the version-specific immutable
    # route the schema's own $id names, data/ausmt-station.schema.json the latest-convenience copy
    # beside the data. Byte-copies of the in-tree artifact; the version segment derives from
    # STATION_SCHEMA_VERSION (the generated mirror), never a literal.
    _st_schema = HERE.parent / "schema" / "ausmt-station.schema.json"
    try:
        _st_schema_bytes = _st_schema.read_bytes()
        (out / "ausmt-station.schema.json").write_bytes(_st_schema_bytes)
        _st_versioned_dir = out / "schemas" / "ausmt-station" / STATION_SCHEMA_VERSION
        _st_versioned_dir.mkdir(parents=True, exist_ok=True)
        (_st_versioned_dir / "ausmt-station.schema.json").write_bytes(_st_schema_bytes)
    except OSError as _e:
        print(f"note: station schema not served beside data ({type(_e).__name__}: {_e})", file=sys.stderr)

    # ---- contract self-check: validate the emitted MTCAT + download manifest + build_report against
    # their OWN schemas (schema/*.schema.json), so a shape drift or a config typo (e.g. a non-MAJOR.MINOR
    # portal.version, a missing required field) FAILS the build loudly instead of shipping a silently
    # non-conforming product. This is the only place the build validates its JSON output against its
    # schemas. jsonschema is an optional (dev) dep — skipped with a note if absent; CI installs it so
    # the check runs there. ----
    _serrs = _validate_products(mtcat, manifest_doc, build_report)
    if _serrs:
        for _e in _serrs:
            print(f"ERROR: product schema self-check failed — {_e}", file=sys.stderr)
        return 2
    # The survey-metadata documents: format-checked schema validation, the zero-null / zero-empty
    # scan and the T25 hard stop (raises naming the survey), beside the product self-check above.
    _smerrs = _validate_survey_metadata(_survey_metadata_docs)
    if _smerrs:
        for _e in _smerrs:
            print(f"ERROR: survey-metadata self-check failed: {_e}", file=sys.stderr)
        return 2
    # The station documents: the same posture on the third public contract, plus the semantic layer
    # JSON Schema cannot state (SCOPE:377-380). scripts/verify.py re-runs that layer over the built
    # tree, so a non-zero exit there leaves a deployment's `current` untouched.
    _sterrs = _validate_station_metadata(_station_docs)
    if _sterrs:
        for _e in _sterrs:
            print(f"ERROR: station self-check failed: {_e}", file=sys.stderr)
        return 2

    # ---- optional sitemap.xml (discoverability) ----
    # PATH-URL CONTRACT (owner ruling 2026-08-18): the published URL for each entity is the PATH
    # form - <base>/surveys/<slug>, <base>/stations/<ausmt_id>, <base>/collections/<id> - which the
    # front door 301s into the SPA's hash routes (tier 1, deploy/frontdoor/Caddyfile). The sitemap
    # advertises ONLY the path form: it is the published contract, and crawlers ignore fragments
    # anyway, so the old #/... entries never indexed as pages. Collections join the sitemap here
    # (previously no collection link was emitted at all). Honesty note carried over from the old
    # caveat: tier 1 still lands a crawler on a redirect into a fragment, so real per-page indexing
    # needs tier 3 (prerendered per-entity landing pages at these same paths); the CONTRACT is what
    # this advertises, and it will not change when tier 2/3 come.
    if a.sitemap_base:
        base = a.sitemap_base.rstrip("/") + "/"
        from xml.sax.saxutils import escape as _xesc
        locs = [base]
        # The AUTHORITATIVE slug (smeta_entry["slug"], the same one ausmt_id / product paths / the
        # portal router use), never a re-slugified display label: a declared slug that differs from
        # slugify(label) would otherwise advertise an id the portal cannot resolve. slugify(lbl)
        # remains only as the fallback for raw-mode builds whose smeta carries no slug.
        locs += [f"{base}surveys/{(surveys_meta.get(lbl) or {}).get('slug') or slugify(lbl)}"
                 for lbl in sorted(surveys_meta)]
        locs += [f"{base}stations/{r['ausmt_id']}" for (_p, r) in all_stations]
        locs += [f"{base}collections/{cid}" for cid in sorted(coll_by_id)]
        body = "\n".join(f"  <url><loc>{_xesc(u)}</loc></url>" for u in locs)
        (out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- path-URL contract (tier 1): these path forms 301 into the portal SPA; '
            'prerendered per-entity pages (tier 3) will serve them at the same URLs -->\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n",
            encoding="utf-8")
        print(f"  sitemap.xml -> {out}/sitemap.xml ({len(locs)} urls)")

    # ---- optional feed.xml (S3: Atom feed of surveys, newest release/date first) ----
    # Emitted whenever at least one survey has a resolvable date, INDEPENDENT of --sitemap-base
    # (base only changes whether entries carry a <link>); an empty build (surveys_meta == {}) always
    # has zero dated surveys, so this naturally emits no file for --allow-empty builds.
    _feed_xml = build_feed_xml(surveys_meta, base_url=a.sitemap_base)
    if _feed_xml is not None:
        (out / "feed.xml").write_text(_feed_xml, encoding="utf-8")
        print(f"  feed.xml -> {out}/feed.xml ({len(feed_entries(surveys_meta))} entries)")

    if prod:
        (prod / "catalogue.json").write_text(_jdump(compact, separators=(",", ":")), encoding="utf-8")
        (prod / "surveys.json").write_text(_jdump(surveys_meta, indent=1), encoding="utf-8")
        (prod / "mtcat.json").write_text(_jdump(mtcat, indent=1), encoding="utf-8")
        (prod / "manifest.json").write_text(_jdump(manifest_doc, indent=1), encoding="utf-8")

    print(f"built {len(all_stations)} stations across {len(surveys_meta)} surveys")
    print(f"  surveys: {', '.join(sorted(surveys_meta))}")
    if dropped_surveys:
        # reason is None for the 0-station drop (the original case) and a short cause for a survey
        # dropped by the LAYER 2 SMETA-serialisability guard; render each honestly.
        print(f"  DROPPED {len(dropped_surveys)} survey(s): "
              + ", ".join(f"{lbl} ({n} files{'' if reason is None else '; ' + reason})"
                          for lbl, n, reason in dropped_surveys))
    if cdir is not None:
        (cdir / "provenance.json").write_text(_jdump(
            {"pipeline": "ausmt_science.ingest.normalize", "format": "emtfxml",
             "engine_versions": canonical_versions,
             "canonical_written": canonical_ok, "failed": canonical_fail,
             # Per-station conditioning notes ({slug: {station_id: [note,...]}}) — what normalize() had
             # to change per station to make the canonical XML schema-valid + round-trippable, not just
             # aggregate counts, so the store is self-documenting about where it diverges from the source.
             "conditioning": {s: n for s, n in all_canonical_notes.items() if n},
             "note": "canonical EMTF XML store (D6); the original EDI uploads remain the citable artifact"},
            indent=1), encoding="utf-8")
        print(f"  canonical EMTF XML store -> {cdir}/  ({canonical_ok} written, {canonical_fail} failed)")
    print(f"  portal data -> {out}/  (catalogue,tf,sci,surveys).json")
    if prod:
        print(f"  product contract + sha256 manifest -> {prod}/")

    # --- EMPTY OUTPUT HANDLING ---
    # A green run that produced nothing is normally worse than a red one: it makes every other green
    # check meaningless. So an empty build FAILS LOUDLY by default (the trust invariant). But a
    # *fresh-start* deployment legitimately has no surveys yet — `--allow-empty` makes that explicit and
    # writes valid empty default files (all portal product JSON files were already written above).
    if len(all_stations) == 0:
        if a.allow_empty:
            print("note: 0 stations — wrote valid EMPTY default product files (--allow-empty). "
                  "The portal will show its empty state until surveys are added.")
            _prune_cache(build_cache)
            return 0
        attempted = len(work)
        print(f"ERROR: pipeline produced 0 stations from {attempted} survey(s) attempted — "
              f"failing the build (empty products are not a success). Use --allow-empty for an "
              f"intentional fresh-start build.", file=sys.stderr)
        return 2   # a FAILED build does not prune (design §3: prune at the end of a SUCCESSFUL build)
    _prune_cache(build_cache)
    return 0


def _prune_cache(build_cache):
    """C18 (design §3): run the cache prune at the end of a SUCCESSFUL build (drop entries untouched
    for the age window, then enforce the AUSMT_CACHE_MAX_MB size cap oldest-first). A prune failure
    must never fail the build; a disabled/absent cache is a no-op."""
    if build_cache is None or not build_cache.enabled:
        return
    try:
        summary = build_cache.prune()
        if summary.get("pruned_age") or summary.get("pruned_size"):
            print(f"C18 cache prune: dropped {summary['pruned_age']} aged + {summary['pruned_size']} "
                  f"over-cap entries; kept {summary['kept']} ({summary['bytes'] // 1024} KiB).")
    except Exception as e:  # noqa: BLE001
        print(f"  [cache] WARN prune failed (non-fatal): {type(e).__name__}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
