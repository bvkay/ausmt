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
import cache as cache_mod           # noqa: E402  (C18 content-addressed per-station build cache)
from _contract import CATALOGUE_COLUMNS  # noqa: E402  (single-source positional column contract)

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


def _jdump(obj, **kw) -> str:
    # ensure_ascii=False: catalogue text (survey/custodian names, the mtcat portal_name em-dash)
    # is emitted as real UTF-8, not \uXXXX escapes — byte-identical semantics for every JSON
    # parser, readable for humans. REQUIRES the paired write_text(..., encoding="utf-8") at
    # every product-emit site below: pathlib defaults to the locale encoding, which is cp1252
    # on the Windows dev box and unpinned in slim containers.
    return json.dumps(obj, ensure_ascii=False, **kw)


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
            if r.get("lat") is not None:
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
    Preference order: the most recent release_notes[].date (a real release event, day-precision) ->
    else dates.year_end/year_start (a bare year, so falls back to Dec 31 / midnight UTC per RFC3339
    when only a year is known) -> else None (no date at all -> excluded from feed/recently-added,
    per the "dated data" comment on the year filter above)."""
    rn = meta.get("release_notes")
    best = None
    if isinstance(rn, list):
        for e in rn:
            if not isinstance(e, dict):
                continue
            d = str(e.get("date") or "").strip()[:10]
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
    '#/survey/<slug>', or OMITTED (no <link> element) when base_url is None — the feed is still valid
    Atom without it, just not clickable outside the portal's own context."""
    from xml.sax.saxutils import escape as _xesc
    entries = feed_entries(surveys_meta)
    if not entries:
        return None
    base = (base_url.rstrip("/") + "/") if base_url else None
    feed_updated = f"{entries[0]['date']}T00:00:00Z"   # newest entry's date = the whole feed's <updated>
    items = []
    for e in entries:
        link = f'\n    <link href="{_xesc(base + "#/survey/" + e["slug"])}"/>' if base else ""
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


def mtcat_document(surveys_meta: dict, all_stations: list, generated_at: str = None,
                   portal: dict = None, coll_by_id: dict = None, lib_vers: dict = None) -> dict:
    """Build an MTCAT v1.0 discovery/federation document (see docs/MTCAT_v1.0.md and
    schema/mtcat.schema.json). Portal owns its data; MTCAT is the shared, minimal metadata other
    portals could harvest. Derived purely from already-computed catalogue data — no new science.
    `coll_by_id` may be passed in so the (single) collection grouping is shared with
    collections_document instead of being recomputed here."""
    from datetime import datetime, timezone
    slug_of, bbox_of = {}, {}
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
    surveys = []
    for lbl, meta in sorted(surveys_meta.items()):
        bb = bbox_of.get(lbl)
        m = meta or {}
        entry = {
            "survey_id": slug_of.get(lbl, slugify(lbl)), "title": lbl,
            "organisation": m.get("org", "unknown"),
            # C7: additive optional federation fields (schema/mtcat.schema.json) — the organisation's ROR
            # and the project's RAiD, when the survey declares them; None when not (schema allows null).
            "organisation_ror": m.get("org_ror"),
            "raid": m.get("raid"),
            "country": m.get("country", "Australia"),
            "version": m.get("version"),
            "collection_id": (m.get("collection") or {}).get("id"),
            "doi": m.get("doi"), "license": m.get("lic"),
            # C1: emit the NORMALISED access level (a plain string — mtcat.schema.json's access is string|null).
            # SMETA already normalises it; normalise again so a raw-mode seed value stays a clean scalar.
            "access": normalise_access_level(m.get("access", "open")),
            "bbox": ({"west": round(bb[0], 6), "south": round(bb[1], 6),
                      "east": round(bb[2], 6), "north": round(bb[3], 6)} if bb else None),
            "centroid": ({"latitude": round((bb[1] + bb[3]) / 2, 6),
                          "longitude": round((bb[0] + bb[2]) / 2, 6)} if bb else None)}
        # C46-W3a (schema 1.1): the attribution/sources/changes rights blocks, PRESENT ONLY when the
        # survey declares them in SMETA — a survey without them keeps a byte-identical entry (the whole
        # existing corpus). Emitted verbatim from SMETA (mtcat.schema.json is additionalProperties:true).
        for k in ("attribution", "sources", "changes"):
            if m.get(k) is not None:
                entry[k] = m[k]
        # §2a (identifiers design): the typed provenance relations, PRESENT ONLY when the survey declares
        # any — a survey without them keeps a byte-identical entry (mtcat.schema.json is additionalProperties
        # :true). SMETA carries this as always-a-list ([] when absent); emit only the non-empty list so the
        # posture matches the sources/attribution/changes blocks above rather than shipping empty arrays.
        if m.get("related_identifiers"):
            entry["related_identifiers"] = m["related_identifiers"]
        surveys.append(entry)
    stations = [{"station_id": r["ausmt_id"], "survey_id": slug_of.get(r["survey"], slugify(r["survey"])),
                 "latitude": r["lat"], "longitude": r["lon"], "data_type": r["type"]}
                for (_p, r) in all_stations]
    if coll_by_id is None:
        coll_by_id, _ = _group_collections(surveys_meta, all_stations)
    collections = [{"collection_id": c["id"], "title": c["title"], "type": c["type"],
                    "status": c.get("status"), "start_year": c.get("start_year"),
                    "last_updated": c.get("last_updated"), "description": c.get("description"),
                    "n_surveys": c["n_surveys"], "n_stations": c["n_stations"],
                    "bbox": c["bbox"], "centroid": c["centroid"]}
                   for c in sorted(coll_by_id.values(), key=lambda x: x["id"])]
    p = portal or {}
    doc = {
        "portal": {"portal_id": p.get("portal_id", "ausmt"),
                   "portal_name": p.get("portal_name", "AusMT — Australia's Magnetotelluric Data Portal"),
                   "schema": "mtcat", "version": str(p.get("schema_version", "1.1")),
                   # FAIR-I: point harvesters at the schema served BESIDE this document (relative to the
                   # data dir — the build copies schema/mtcat.schema.json to out/mtcat.schema.json), so a
                   # second implementation can validate mtcat.json without resolving the canonical $id.
                   "schema_url": p.get("schema_url", "mtcat.schema.json"),
                   # FAIR-R: the licence of the CATALOGUE METADATA itself (distinct from per-survey data
                   # licences). CC0 by recommendation; overridable via portal.config.yaml pending owner
                   # sign-off on the catalogue-metadata licence.
                   "metadata_license": p.get("metadata_license", "CC0-1.0"),
                   "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "surveys": surveys, "stations": stations,
        "collections": collections}      # always present (empty list when none) for a stable shape
    # C32 §2: additive document-level served-tool versions (mtcat.schema.json is additionalProperties:
    # true at the top level, so no schema-version bump — same posture as the C7 optional fields). A key
    # is None when that library was not importable in the build environment.
    _lv = lib_vers or {}
    doc["mt_metadata_version"] = _lv.get("mt_metadata")
    doc["mth5_version"] = _lv.get("mth5")
    return doc


# --- survey.yaml -> SMETA: per-facet mappers (each small + independently testable; the assembler
# below just composes them). Both the Prototype-20 structured schema and the older flat schema. ----

def _org_of(y: dict):
    """(name, ror) from organisation: a {name, ror} map, or a bare string (then ror=None)."""
    org = y.get("organisation")
    if isinstance(org, dict):
        return org.get("name"), org.get("ror")
    return org or "unknown", None


def _investigators_of(y: dict) -> list:
    """[{name, orcid}] from a single lead_investigator {name, orcid}, else the principal_investigators
    list. C7: the ORCID solicited by the schema used to be discarded here (bare name strings only);
    now it rides alongside the name so the portal can render it as a PID link. orcid is None when the
    field is absent/blank (both the '« REPLACE »' template default and legacy surveys predate it)."""
    li = y.get("lead_investigator")
    if isinstance(li, dict) and li.get("name"):
        return [{"name": li["name"], "orcid": (li.get("orcid") or None)}]
    return [{"name": pi["name"], "orcid": (pi.get("orcid") or None)}
            for pi in (y.get("principal_investigators") or [])
            if isinstance(pi, dict) and pi.get("name")]


def _funders_of(y: dict) -> list:
    """[{name, pid}] from funding/funders; tolerates odd shapes (non-dicts dropped), never crashes."""
    raw = [f for f in (y.get("funding") or y.get("funders") or []) if isinstance(f, dict)]
    return [{"name": f.get("organisation") or f.get("name"),
             "pid": f.get("organisation_ror") or f.get("pid")} for f in raw]


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
        "investigators": _investigators_of(y),
        "funders": _funders_of(y),
        "pubs": _publications_of(y),
        "blurb": y.get("abstract"),
        "ts": "ok" if (y.get("time_series", {}) or {}).get("levels_available") else "unk",
        "ts_pid": _ts_pid_of(y),              # C7: survey-specific raw-TS collection PID (None => deployment default)
        "edi": "ok",
        "mth5": "unk",
        "access": acc,                       # normalised level (open|metadata_only|embargoed|legacy) — SMETA key
        "embargo_until": embargo_until,       # C1: ISO date or None; the portal badges withholding from these
        # C7: yr/ve were always '' (every citation rendered "(n.d.)" regardless of a declared date/version);
        # yr = year of dates.end, else dates.start, else '' (genuinely no date -> honest "(n.d.)"); ve = the
        # declared survey version, else '' (no version -> the apa()/bibtex()/ris() helpers already omit it).
        "cite": {"au": org_name, "yr": _citation_year_of(y),
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
    return sm


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
        return _mini_yaml(text if text is not None else path.read_text())
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
        if not v or v[0] in "\"'":
            return v.strip()
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
    key_re = re.compile(r"^([\w.\-]+):\s*(.*)$")

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
                    k, val = m.group(1), m.group(2).strip()
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
                                k2, v2 = m2.group(1), m2.group(2).strip()
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
            k, val = m.group(1), m.group(2).strip()
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
    tfobj = mtm.read(p)                          # parse ONCE, reuse below
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
    _pm, _pt = mtm.proc_info_from_tf(tfobj), sci.proc_info(_raw)
    proc = (_pm[0] or _pt[0] or cat.grab(_raw, "PROGVERS"),   # sw: scrape, else PROGVERS
            _pm[1] or _pt[1],                                  # alg: scrape
            _pm[2] or _pt[2] or (1 if r.get("remote_site") else 0))  # rr: ...or remote_site found
    per, comp = mtm.components_from_tf(tfobj)
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
            "frame": _frame, "frame_notes": _frame_notes}


def process_edis(edi_paths, survey_label, org, slug, extractor="mt_metadata",
                 cache=None, survey_digest="", report=None):
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
    cached gate-skip replays identically too)."""
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
        if parsed.get("email_flag"):
            _email_hits.append(p.name)
        if parsed.get("coord_warn"):
            print(f"  WARNING: coord-QC failed for {p.name}: {parsed['coord_warn']} "
                  f"(DMS sign-bug detection SKIPPED for this station)", file=sys.stderr)
        # Graceful degradation: a record with no coordinates or no periods is unusable (a malformed
        # header, or an EDI mt_metadata cannot turn into a transfer function). Skip it rather than
        # emit a junk station.
        if r.get("lat") is None or not r.get("n_periods"):
            print(f"  SKIP {p.name}: no coordinates/periods recovered by mt_metadata "
                  f"(malformed header or unreadable transfer function)", file=sys.stderr)
            continue
        r["survey"] = survey_label
        r["org"] = org
        r["id"] = safe_component(r.get("id"))          # untrusted DATAID -> no traversal / XSS
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
    else:
        for (_p, _r) in stations:
            _r.pop("_frame_notes", None)
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


def process_mth5(h5_paths, survey_label, org, slug):
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
                if r.get("lat") is None or not r.get("n_periods"):
                    print(f"  SKIP {r.get('id')} in {h5.name}: no coordinates/periods in MTH5", file=sys.stderr)
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
            continue
    _disambiguate(stations, slug)   # keep same-station re-processings as distinct variant records
    return stations, tf_rows, sci_rows


def load_portal_config(path) -> dict:
    """Read the portal's branding/version config (portal.config.yaml) for the MTCAT portal block, so a
    re-used portal (NZMT, CanadaMT, …) is configured in one place. Falls back to AusMT defaults when no
    config is given or it cannot be read. Uses PyYAML if present, else the stdlib mini-parser."""
    default = {"portal_id": "ausmt",
               "portal_name": "AusMT — Australia's Magnetotelluric Data Portal",
               "schema_version": "1.1"}
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
            "schema_version": str(p.get("schema_version", "1.1"))}


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
    INFO coordinate, recompute the state facet, and record the resolution + its basis. With no
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
        cand = (r.get("coord_candidates") or {}).get(choose)
        if choose == "info" and cand and cand[0] is not None and cand[1] is not None:
            r["lat"], r["lon"] = round(cand[0], 6), round(cand[1], 6)
        r["coord_flag"] = "dms_sign_resolved"
        r["coord_conflict_deg"] = None   # the HEAD/INFO conflict is now resolved, not outstanding
        r["coord_resolution"] = {"chosen": choose, "basis": cr.get("basis"), "source": "survey.yaml"}


def _write_station_products(job, prov):
    """Render + write one station's --products station.json + dimensionality.json (C42 deferred so it
    runs AFTER the coordinate mask: `r` is the SHARED station record, masked in place at the single seam,
    so `location` carries the post-mask value every other emitter reads — no per-emitter mask logic).
    `job` is the tuple captured in main()'s per-survey loop; `prov` is the build PROV block."""
    (sdir, r, srow, label, org, meta, lic, slug, p, edi_served, conditioning_notes, served) = job
    sdir.mkdir(parents=True, exist_ok=True)
    # C1c: --products IS a served surface in deployment (deploy/Makefile writes products/ INSIDE the served
    # build dir; D1). So it rides the SAME C1 access gate as tf.json/sci.json: for a NON-SERVED survey
    # (embargoed with an active embargo, or metadata_only) the derived TF science IS the embargoed data —
    # emitting median_relative_error / dimensionality / skew_beta / the completeness diagnostic / the frame
    # phase medians here would publish exactly what the byte gate (C1) and the display gate (C1b) withhold.
    # `served` is the survey's access_serve_state["served"] captured at the emit site (never re-derived). A
    # non-served survey gets a WITHHELD station.json carrying ONLY the discovery-safe identity the public
    # catalogue already exposes (id, survey, access state, edi_available=false) — NO TF-derived science, NO
    # exact source position, NO input_sha256 — and NO dimensionality.json (a pure interpretation product).
    if not served:
        _wdoc = {
            "ausmt_id": r["ausmt_id"], "station": r["id"], "survey": label,
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
        (sdir / "station.json").write_text(_jdump(_wdoc, indent=1), encoding="utf-8")
        return   # no dimensionality.json for a non-served survey (interpretation product = withheld science)
    _doc = {
        "ausmt_id": r["ausmt_id"], "station": r["id"], "survey": label,
        "country": (meta or {}).get("country", "Australia"), "organisation": org,
        # C42: post-mask coordinates — exact/generalised(0.1deg)/withheld(null) per the custodian policy,
        # read from the single-seam-masked record. This products/ surface IS served in deployment (D1).
        "location": {"lat": r["lat"], "lon": r["lon"]},
        "data": {"type": r.get("type"), "n_periods": r.get("n_periods"),
                 "period_min_s": r.get("period_min_s"), "period_max_s": r.get("period_max_s")},
        "diagnostics": {"median_relative_error": srow[_SC["mre"]], "remote_reference": bool(srow[_SC["rr"]]),
                        "tipper_available": "T" in (r.get("comps") or ""),
                        "dimensionality": srow[_SC["dim"]], "skew_beta_median_deg": srow[_SC["skew"]],
                        "completeness_smoothness_diagnostic": {
                            "value": srow[_SC["q"]], "basis": srow[_SC["qb"]],
                            "note": "not a quality or geological-value judgement"}},
        # Processing metadata — all BEST-EFFORT (scraped from the EDI; mt_metadata's
        # structured fields are empty for most dialects). The remote_reference arrangement
        # detail lives in `note` (the EDI INFO block); remote_site is the named reference
        # station where derivable (Phoenix 'P=x R=y' DATAID / REFERENCE section).
        "processing": {"software": srow[_SC["sw"]], "algorithm": srow[_SC["alg"]],
                       "remote_reference": bool(srow[_SC["rr"]]),
                       "remote_site": r.get("remote_site"),
                       "note": r.get("processing_note")},
        # C42: edi_served folds in the per-station coordinate byte-gate — a non-exact station is NOT
        # distributed even inside a served survey, so its station.json must not advertise an EDI.
        "distribution": {"edi_available": edi_served, "license": lic,
                         "edi_path": f"edi/{slug}/{p.name}" if edi_served else None},
        # provenance: input -> software/params -> output (traceable, per Egbert)
        "provenance": {**prov, "input_file": p.name, "input_sha256": sha256(p)},
        # coordinate QC: present only when the parse flagged something, so consumers can
        # surface "treat with caution" without implying anything about unflagged stations.
        "coordinate_qc": ({"flag": r.get("coord_flag"),
                           "head_info_conflict_deg": r.get("coord_conflict_deg"),
                           "resolution": r.get("coord_resolution")}
                          if (r.get("coord_flag") or r.get("coord_conflict_deg")) else None),
        # canonical_conditioning: what normalize() had to change to make this station's
        # canonical EMTF XML schema-valid + round-trippable (rotation frame not asserted,
        # source-id preserved in the Site Name, citation provenance). Present only when the
        # station was actually conditioned, so an unconditioned station is not implied to be.
        "canonical_conditioning": (conditioning_notes.get(r["id"]) or None),
        # frame (C25): the measured frame facts + the sign-convention verdict for THIS
        # station — what rotation the source declared, whether the engine de-rotated to
        # geographic north at ingest, and the Gate-2 quadrant medians. None only for
        # inputs the gates do not cover (the flag-gated MTH5 path).
        "frame": r.get("frame"),
    }
    # C42 A1: carry the coordinate policy on station.json too (secondary to the boot-loaded
    # coord_policy.json — the surface the portal drawer reads — but consistent for a curator reading
    # the product). Added ONLY for a non-exact station (reuses the mask-seam-stamped r["coord_policy"]);
    # an exact station.json gains no key, so it is byte-unchanged.
    _cp = r.get("coord_policy")
    if _cp and _cp != "exact":
        _doc["coordinate_policy"] = _cp
    (sdir / "station.json").write_text(_jdump(_doc, indent=1), encoding="utf-8")
    (sdir / "dimensionality.json").write_text(_jdump({
        "classification": srow[_SC["dim"]], "skew_beta_median_deg": srow[_SC["skew"]],
        "pct_periods_3d": srow[_SC["p3d"]], "method": "phase-tensor (Caldwell 2004)",
        "screening_diagnostic": True,
        "note": "screening diagnostic, not an interpretation product"}, indent=1), encoding="utf-8")


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
        return r.get("file") or getattr(p, "name", str(p))

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
        return _git_commit_at(HERE)

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
            "software": {"python": _pf.python_version()},
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
            res = normalize(p, out, survey_id=slug, station_id=r["id"], survey_meta=survey_meta)
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


def _emit_served_xml(stations, slug, xmldir, survey_meta=None, cache=None, survey_digest="",
                     coord_default="exact", coord_overrides=None):
    """Write the canonical EMTF XML for each station into the PORTAL data dir (xmldir = out/xml/<slug>)
    so EMTF XML is a downloadable format alongside the bundled EDI. Same normalize() path + impedance
    round-trip gate as the canonical store; a per-EDI failure is logged and SKIPPED (that station
    simply has no XML download). Keyed by the station's FINAL r["id"] (post-disambiguation) so the XML
    filename matches the manifest/catalogue id. `survey_meta` (the survey SMETA) sources an HONEST
    citation (custodian org, not the portal brand). Engine-guarded by the caller (mt_metadata is a core
    build dep). Returns (written, notes, stamped): written={station_id: xml_path},
    notes={station_id:[note,...]} for conditioned stations (rotation unknown / source-id preserved /
    citation provenance) — the caller persists notes into that station's station.json
    (canonical_conditioning) and emits a NOTICE — and stamped={station_id: survey_digest} recording,
    per served station, the survey.yaml digest the served XML was KEYED/PRODUCED under (C18b,
    Amendment A3). On the FRESH path that is the digest this call was invoked with; on a cache HIT it is
    the digest carried in the entry's own meta blob (a stale entry surfaces its stale digest here). The
    caller writes stamped into the out/products/survey_digests.json sidecar the verify.py consistency
    gate compares against the LIVE survey.yaml, so a product served under a stale digest is caught.

    C18 (the DOMINANT cost, ~84% of a build): when `cache` is an ENABLED BuildCache, the normalize()
    round-trip is cached per station by source-EDI sha + salt. A HIT writes the cached XML BYTES
    verbatim to <xmldir>/<station>.xml (the exact bytes normalize() produced on the miss build) and
    returns the cached conditioning notes — skipping the round-trip entirely. The served XML a hit
    writes is byte-identical to what a fresh normalize() writes (the round-trip QC gate already ran on
    the miss build that populated it); verify.py re-hashes these bytes cache-blind regardless."""
    from ausmt_science.ingest.normalize import normalize  # noqa: PLC0415  (installed pkg; C37/F8)
    written = {}
    notes = {}
    stamped = {}   # C18b (A3): {station_id: survey_digest the served XML was keyed/produced under}
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
        _ck = cache.key(edi_sha=sha256(p), survey_digest=survey_digest,
                        kind=f"xml:{r['id']}") if _use_cache else None
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
            res = normalize(p, xmldir, survey_id=slug, station_id=r["id"], survey_meta=survey_meta)
            written[r["id"]] = res.canonical_xml
            # C18b (A3): the FRESH path is keyed under THIS call's survey_digest — stamp it directly.
            stamped[r["id"]] = survey_digest
            if res.conditioned:
                notes[r["id"]] = res.conditioned
                # per-station NOTICE retired -> survey-level aggregation in main() (aggregate_conditioning).
            # normalize() also writes a round-trip derived .edi beside the .xml; we only serve the
            # canonical XML here, so drop the derived EDI to keep out/xml/ to manifested artifacts.
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
            print(f"  [xml] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
    return written, notes, stamped


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


def emit_survey_mth5(stations, slug, label, out):
    """C32 §1.2: write ONE survey-aggregated MTH5 (out/bundles/<slug>-tf.h5) holding every served
    station's TRANSFER FUNCTION via mth5.add_transfer_function — the idiomatic MTCollection working unit
    for mtpy-v2/ModEM. It contains transfer functions ONLY (never time series); the -tf filename says so.
    FLAG-GATED by the caller (survey_h5_enabled, default OFF — D4 keeps MTH5 off pending the storage/
    management call). Each station is grouped under one named survey (survey_metadata.id = slug). A
    per-station TF write failure is logged (WARN) and SKIPPED — never a build failure — and n_written is
    the ACTUAL count included, so the manifest row's n_stations reflects reality (design §1.4).
    Returns (rel_url, h5_path, n_written) or (None, None, 0).
    NOTE: HDF5 embeds creation timestamps/uuids, so this file is NOT byte-reproducible across builds; its
    manifest sha256 is a download-integrity hash for THIS build's bytes, not a cross-build invariant."""
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415
    from mth5.mth5 import MTH5  # noqa: PLC0415
    hdir = out / "bundles"; hdir.mkdir(parents=True, exist_ok=True)
    hpath = hdir / f"{slug}-tf.h5"
    if hpath.exists():
        hpath.unlink()
    # Opening the h5 can itself fail (file lock, HDF5 driver). Keep it best-effort like the per-station
    # loop: a single survey's h5 failure must NOT abort the whole portal build (catalogue/tf/sci/manifest
    # are written after the survey loop), so swallow it and return "no bundle".
    try:
        m = MTH5()
        m.open_mth5(str(hpath), mode="w")
    except Exception as ex:  # noqa: BLE001
        print(f"  [h5] WARN open {hpath.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
        hpath.unlink(missing_ok=True)
        return None, None, 0
    n = 0
    try:
        for (p, r) in stations:
            try:
                tf = TF(fn=str(p))
                tf.read()
                tf.survey_metadata.id = slug        # group all stations under one named survey
                # mt_metadata's Site.id is alphanumeric-only; a disambiguated id like 'MBV20.lemigraph'
                # would be rejected and the station silently dropped. Strip to alnum so it is kept.
                tf.station_metadata.id = _re.sub(r"[^A-Za-z0-9]", "", r["id"]) or r["id"]
                m.add_transfer_function(tf)
                n += 1
            except Exception as ex:  # noqa: BLE001
                print(f"  [h5] WARN {p.name}: {type(ex).__name__}: {str(ex)[:120]}", file=sys.stderr)
    finally:
        m.close_mth5()
    if not n:
        hpath.unlink(missing_ok=True)
        return None, None, 0
    return f"bundles/{slug}-tf.h5", hpath, n


def load_flags(path) -> dict:
    """Distribution feature flags from the portal.config.yaml `flags:` block (default OFF). The single
    config seam, mirrored to the portal via tools/gen_config.py -> config.js. survey_h5_enabled gates the
    survey-aggregated MTH5 producer (D4: MTH5 off pending management sign-off); collection_download_enabled
    reserves the future collection-level bundle. CLI --survey-h5 / --collection-download OR on top."""
    flags = {"survey_h5_enabled": False, "collection_download_enabled": False}
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
    for k in list(flags):
        flags[k] = bool(f.get(k, flags[k]))
    return flags


def _validate_products(mtcat_doc, manifest_doc, build_report_doc=None):
    """Validate the emitted MTCAT + download-manifest (+ optional build_report) docs against
    schema/{mtcat,manifest,build_report}.schema.json. Returns a list of human-readable violations
    (empty = OK). jsonschema is optional: absent => [] + a note. A missing/broken schema file is
    noted, not fatal — only an actual schema VIOLATION fails."""
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
            jsonschema.validate(doc, json.loads(schema_path.read_text()))
        except jsonschema.ValidationError as e:  # noqa: PERF203
            errs.append(f"{name}.json: {e.message} (at /{'/'.join(str(x) for x in e.absolute_path)})")
        except Exception as e:  # noqa: BLE001  (missing/unreadable schema must not crash the build)
            print(f"note: {name} schema self-check skipped ({type(e).__name__}: {e})", file=sys.stderr)
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
    survey's bytes are emitted — with the SAME matcher station_policy applies with."""
    work, survey_extent, coord_policy = [], {}, {}
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
                continue
            y = _read_yaml(sy, raw=sy_raw)
            if not isinstance(y, dict):
                if y is not None:  # valid YAML but not a mapping (list/scalar); None was already warned in _read_yaml
                    print(f"SKIP {d.name}: survey.yaml is not a YAML mapping -- survey dropped", file=sys.stderr)
                continue
            sy_digest = hashlib.sha256(sy_raw).hexdigest()   # the ONE digest this survey builds under
            label = y.get("name", d.name)
            slug = safe_component(y.get("slug", d.name))   # untrusted slug -> safe paths/ids
            edis = sorted((d / "transfer_functions" / "edi").glob("*.edi"))
            mh = sorted((d / "transfer_functions" / "mth5").glob("*.h5")) \
                + sorted((d / "transfer_functions" / "mth5").glob("*.mth5"))
            fmt = a.input_format
            if fmt == "edi":
                inputs, kind = edis, "edi"
            elif fmt == "mth5":
                inputs, kind = mh, "mth5"
            else:  # auto: EDI if present, otherwise MTH5
                inputs, kind = (edis, "edi") if edis else ((mh, "mth5") if mh else (edis, "edi"))
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
                continue
            work.append((label, smeta["org"], inputs, kind, smeta, d, slug, sy_digest))
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
    return work, survey_extent, coord_policy


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surveys", help="root of survey packages (<slug>/survey.yaml + transfer_functions/edi/)")
    ap.add_argument("--raw", help="root of raw EDI folders (bulk seed mode)")
    ap.add_argument("--collections", help="JSON {folder:[survey_label,org]} for --raw mode")
    ap.add_argument("--seed-meta", help="JSON of survey metadata (SMETA) for --raw mode -> surveys.json")
    ap.add_argument("--out", required=True, help="portal data dir to write {catalogue,tf,sci,surveys}.json")
    ap.add_argument("--products", default=None, help="optional dir for the product-contract JSON")
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
    ap.add_argument("--input-format", choices=["auto", "edi", "mth5"], default="auto",
                    help="transfer-function input for --surveys packages: 'edi', 'mth5', or 'auto' "
                         "(EDI if present in a package, otherwise MTH5). One science seam for both.")
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
    flags["collection_download_enabled"] = flags["collection_download_enabled"] or a.collection_download
    base_url = a.base_url
    if flags["survey_h5_enabled"] and not mtm.available():
        sys.exit("ERROR: --survey-h5 / flags.survey_h5_enabled requires the mt_metadata stack "
                 "(pip install -r environments/requirements-mtmetadata-lock.txt).")

    all_stations, all_tf, all_sci = [], [], []
    # manifest: per-station artifacts (files) + per-survey bundles (bundles). Key-based, NOT positional.
    surveys_meta, manifest = {}, {"files": [], "bundles": []}
    dropped_surveys = []   # surveys that validated but yielded 0 stations (never silently vanish)
    # build_report.json accumulator: {slug: {stations_built, stations_dropped, warnings, conditioning,
    # cache, duration_seconds}}. Populated per survey in the loop; assembled + written alongside
    # build_provenance.json below. Public build metadata for the (planned) curator serve-state UI.
    build_report_surveys: dict = {}
    work, survey_extent, coord_policy = discover_work(a, ap, validator)

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
    # C42: --products station.json carries a `location` (r[lat/lon]) and IS a served surface in
    # deployment (deploy/Makefile writes products/ INSIDE the served build dir; D1/D3). Its coordinates
    # must therefore be the POST-MASK values from the single seam — but the mask runs after the corpus-
    # wide qc_pass, which is after this per-survey loop. So the per-station product emission is DEFERRED:
    # each iteration appends a job here capturing its (shared, in-place-masked) station record; the jobs
    # run AFTER apply_coordinate_policy, so station.json reads the same masked record every other emitter
    # reads (D3: "no per-emitter logic"). Nothing else in station.json depends on the mask, so deferral is
    # value-preserving for exact stations (proven by the default-stability pin).
    _station_product_jobs: list = []
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
        if kind == "mth5":
            stations, tf_rows, sci_rows = process_mth5(inputs, label, org, slug)   # MTH5 path not cached
        else:
            stations, tf_rows, sci_rows = process_edis(inputs, label, org, slug, a.extractor,
                                                       cache=build_cache, survey_digest=_survey_digest,
                                                       report=_gate_report)
        for _d in _gate_report.get("stations_dropped", []):
            _survey_warnings.append(f"station {_d['station']} SKIPPED by convention gate: {_d['reason']}")
        if not stations:
            n_in = len(inputs)
            print(f"  WARNING: survey '{label}' produced 0 stations from {n_in} input file(s) and "
                  f"was DROPPED from the portal. (Check that mt_metadata could read these EDIs — "
                  f"malformed headers or missing coordinates yield no usable station.)",
                  file=sys.stderr)
            dropped_surveys.append((label, n_in))
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
                continue
        _apply_coord_resolution(stations, (meta or {}).get("coord_resolution"))
        # Per-station canonical-conditioning notes (rotation-unknown, source-id preservation, citation
        # provenance). Populated by whichever normalize() pass runs below (canonical store and/or served
        # XML — both take the SAME survey SMETA `meta`, so their notes agree); station.json reads it so
        # the conditioning is persisted even for surveys whose bytes are withheld (no served XML). The
        # canonical store's provenance.json also records this per-station map (not just counts).
        conditioning_notes: dict = {}
        if cdir is not None and kind == "edi":
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
        input_formats.add(kind)
        all_stations += stations; all_tf += tf_rows; all_sci += sci_rows
        smeta_entry = meta or {"country": "Australia", "org": org, "edi": "ok",
                               "lic": "unknown", "cite": {"au": org, "ti": label, "yr": "", "ve": "", "pb": org}}
        smeta_entry["slug"] = slug  # authoritative survey slug; the portal reads this (no re-derivation)
        # IDCONS D4: annotate the resolution facets from the pid_status cache (no-op when no cache).
        apply_pid_resolution(smeta_entry, pid_status)
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
        # C1b: the DISPLAY-product gate keys on the ACCESS state ALONE (not can_serve). A survey may be
        # access=open yet non-redistributably licensed (or built with --no-bundle-edi): that survey's bytes
        # are withheld by the licence/flag gate but its curves SHOULD still plot (open-access preview). Only
        # a NON-OPEN ACCESS state (embargoed/metadata_only/unrecognised) withholds the derived display data.
        if not _acc["served"]:
            withheld_ids.update(r["ausmt_id"] for (_p, r) in stations)
        can_serve = a.bundle_edi and redistributable(lic) and kind == "edi" and _acc["served"]  # only EDI is byte-copied
        xml_written = {}
        # Per-survey EDI dir, NAMESPACED by slug (like out/xml/<slug>/ and out/bundles/) so two surveys
        # that reuse an EDI basename (e.g. both ship 01.edi) cannot overwrite each other in a flat tree —
        # which would also corrupt the path-keyed sha256 cache. ausmt_id is unique but basenames are not.
        sedir = edidir / slug
        if can_serve:
            sedir.mkdir(parents=True, exist_ok=True)
            # Derived EMTF XML is the SAME redistribution as the EDI (same TF data), so it rides the
            # same license gate; served into out/xml/<slug>/ as a downloadable format.
            xml_written, _xnotes, _xstamped = _emit_served_xml(
                stations, slug, out / "xml" / slug, survey_meta=meta,
                cache=build_cache, survey_digest=_survey_digest,
                coord_default=_coord_default, coord_overrides=_coord_overrides)
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
        # C46-W3a: the survey's custodian of record for manifest rows — the declared attribution.custodian
        # (rights-holder, may differ from the acquiring organisation), else the organisation. Computed once.
        _custodian = (((meta or {}).get("attribution") or {}).get("custodian") or org)
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
            if can_serve and _cserved:
                served_edi = sedir / p.name
                served_edi.write_bytes(p.read_bytes())
                available_ids.add(r["ausmt_id"])
                served_edis.append(served_edi)
                manifest["files"].append(_file_row(r["ausmt_id"], label, r["id"], "edi",
                                                    served_edi, f"edi/{slug}/{p.name}", lic,
                                                    nci_base=nci_base, base_url=base_url,
                                                    custodian=_custodian))
                _xmlp = xml_written.get(r["id"])
                if _xmlp and Path(_xmlp).exists():
                    manifest["files"].append(_file_row(r["ausmt_id"], label, r["id"], "emtfxml",
                                                        Path(_xmlp), f"xml/{slug}/{Path(_xmlp).name}",
                                                        lic, nci_base=nci_base, base_url=base_url,
                                                        custodian=_custodian))
            if prod:
                # C42: DEFER station.json/dimensionality.json to after the mask (see _station_product_jobs
                # above). The job captures this station's SHARED record `r` (masked in place downstream), its
                # science row, and the survey context needed to render — nothing here depends on cross-survey
                # state that changes after this iteration (conditioning_notes is this survey's own dict). The
                # per-station coordinate byte-gate (_cserved) is captured too: even inside a served survey, a
                # non-exact station's EDI is withheld, so station.json's distribution must not advertise it.
                # C1c: the SURVEY access-serve state (_acc["served"], the SAME result the byte gate and the
                # C1b tf/sci withholding use — never re-derived) is captured so the deferred emitter withholds
                # the derived science products for a non-served survey, exactly as tf.json/sci.json are.
                _station_product_jobs.append(
                    (prod / slug / r["id"], r, srow, label, org, meta, lic, slug, p,
                     bool(can_serve and _cserved), conditioning_notes, bool(_acc["served"])))
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
            _derived = bool(xml_written) or bool(flags.get("survey_h5_enabled"))
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
                _hrel, _hpath, _hn = emit_survey_mth5(_h5_stations, slug, label, out)
                if _hpath:
                    manifest["bundles"].append(_bundle_row(label, slug, "mth5", _hpath, _hrel,
                                                           lic, _hn, nci_base=nci_base, base_url=base_url,
                                                           custodian=_custodian))
                    # C46-W3a: rights must travel with the MTH5 bytes too. The survey MTH5 ships as a bare
                    # file (bundles/<slug>-tf.h5, NOT a zip — HDF5 embeds timestamps so it is not
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
        # Convention WARNs (one off-diagonal out of quadrant) are survey-level warnings in the
        # report — the honest "look at this" surface. Derotation/insufficient/unverifiable notes
        # stay in `frame` (they are recorded facts, not warnings).
        for _fe in conditioning_report(_frame_notes_by_station):
            if _fe["note"].startswith("convention:") and "outside its expected quadrant" in _fe["note"]:
                _survey_warnings.append(f"{_fe['note']} — {_fe['count']} station(s): "
                                        f"{_fe['stations'] or _fe['except'] or _fe['count']}")
        build_report_surveys[slug] = {
            "stations_built": len(stations),
            # C25: convention-gate skips are STRUCTURED drops ({station, reason}); the legacy
            # unusable-EDI print+continue path still records nothing here (per the original brief).
            "stations_dropped": list(_gate_report.get("stations_dropped", [])),
            "warnings": list(_survey_warnings),
            # Same shared aggregation as the log lines above: [{note,count,stations|null,except|null}].
            "conditioning": conditioning_report(conditioning_notes),
            # C25: frame/convention notes, same aggregation shape as `conditioning`.
            "frame": conditioning_report(_frame_notes_by_station),
            "cache": ({"digest": (_survey_digest or "")[:12], "hits": _dh, "misses": _dm, "writes": _dw}
                      if _c0 is not None else {"digest": (_survey_digest or "")[:12],
                                              "hits": 0, "misses": 0, "writes": 0}),
            "duration_seconds": round(_time.perf_counter() - _survey_t0, 3),
        }

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
    # ---- deferred --products station.json/dimensionality.json: run NOW, after the mask, so each
    # station.json `location` carries the post-mask coordinate (D3: products/ is a served surface in
    # deployment). The jobs read the same shared records the mask mutated.
    for _job in _station_product_jobs:
        _write_station_products(_job, PROV)
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
    build_report = {
        "generated": _dt_report.datetime.now(_dt_report.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "engine_commit": BUILD_ID["engine_commit"],
        "source_commit": BUILD_ID["source_commit"],
        "build_id": BUILD_ID["build_id"],
        "pipeline_version": PROV["pipeline_version"],
        "surveys": build_report_surveys,
        "totals": {"surveys": len(build_report_surveys),
                   "stations_built": _report_stations_built,
                   "warnings": _report_warnings},
    }
    (out / "build_report.json").write_text(_jdump(build_report, indent=1), encoding="utf-8")

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
                    "base_url": base_url, "files": manifest["files"], "bundles": manifest["bundles"]}
    (out / "manifest.json").write_text(_jdump(manifest_doc, separators=(",", ":")), encoding="utf-8")

    # ---- MTCAT v1.0 discovery/federation document (portal owns data; shared minimal metadata) ----
    mtcat = mtcat_document(surveys_meta, all_stations, portal=load_portal_config(a.portal_config),
                           coll_by_id=coll_by_id, lib_vers=LIB_VERSIONS)
    (out / "mtcat.json").write_text(_jdump(mtcat, indent=1), encoding="utf-8")
    # FAIR-I: serve the schema beside the data so mtcat.json's schema_url ("mtcat.schema.json")
    # resolves relative to the catalogue itself — a harvester can validate without reaching the
    # (custody-pending) canonical $id host. Byte-copy of the in-tree schema; skipped (noted, not
    # fatal) if it is unreadable so a schema-path glitch never fails an otherwise-good build.
    _mtcat_schema = HERE.parent / "schema" / "mtcat.schema.json"
    try:
        (out / "mtcat.schema.json").write_bytes(_mtcat_schema.read_bytes())
    except OSError as _e:
        print(f"note: mtcat schema not served beside data ({type(_e).__name__}: {_e})", file=sys.stderr)

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

    # ---- optional sitemap.xml (discoverability) ----
    # CAVEAT: the portal is a hash-routed SPA (#/station/<id>); most crawlers ignore the
    # fragment, so these deep links collapse to the base URL for indexing. The sitemap is
    # emitted for completeness/tooling; real per-page SEO needs path-based routing + prerender.
    if a.sitemap_base:
        base = a.sitemap_base.rstrip("/") + "/"
        from xml.sax.saxutils import escape as _xesc
        locs = [base]
        locs += [f"{base}#/survey/{slugify(lbl)}" for lbl in sorted(surveys_meta)]
        locs += [f"{base}#/station/{r['ausmt_id']}" for (_p, r) in all_stations]
        body = "\n".join(f"  <url><loc>{_xesc(u)}</loc></url>" for u in locs)
        (out / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!-- hash-routed SPA: fragment deep links are not separately indexed by most crawlers -->\n'
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
        print(f"  DROPPED {len(dropped_surveys)} survey(s) with 0 stations: "
              + ", ".join(f"{lbl} ({n} files)" for lbl, n in dropped_surveys))
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
