"""C42 coordinate-access policy: exact / generalised / withheld (the ENGINE mask seam).

The custodian chooses whether a station's coordinates are served exact, generalised (rounded to
0.1deg, ~11 km), or withheld (null). This module owns the ONE mask seam and its ONE rounding
function, per the frozen design record maintainer/C42-CoordinateAccess.md (D2/D3). The seam is
pipeline-ordered by the caller: parse -> QC on TRUE coordinates -> apply_coordinate_policy() in
place -> ALL emission. No emitter reads a coordinate from anywhere but the post-mask station record.

Fail-closed posture (consistent with the C25 gates' refuse-to-serve stance): an UNKNOWN enum value
or an override naming a station that does not exist is a survey-level build FAILURE (raised as
CoordinatePolicyError), never a silent fallback to exact.

Default stability: a survey with no `access.coordinates` field parses to ("exact", {}) and the mask
is a no-op for every one of its stations, so the whole existing corpus builds byte-identically
(the default-stability pin, D6).
"""
from __future__ import annotations

from pathlib import Path

# The three policies, in the order the record lists them (D2). "exact" is the default.
COORDINATE_POLICIES = ("exact", "generalised", "withheld")

# Generalisation grid: 0.1deg (~11 km). ONE rounding function, engine-side only — the portal never
# re-rounds; it renders the masked catalogue value verbatim (pinned, D6). 1 dp of a degree.
_GENERALISE_DP = 1


class CoordinatePolicyError(ValueError):
    """A survey's access.coordinates policy is invalid: an unknown enum value, or an override id that
    names no station in the survey. Raised so the caller fails the survey-level build LOUDLY (never a
    silent fallback to exact — the same refuse-to-serve posture as the C25 convention gates)."""


def round_generalised(v):
    """The ONE generalisation rounding function: a coordinate rounded to 0.1deg (1 dp). None passes
    through as None (a station with no coordinate has nothing to generalise). Used for BOTH lat and
    lon so the disclosed precision is single-sourced here; anything finer than this in served output
    is a leak (the leak-sweep's epsilon is sized to catch a 3-dp derivative that slips past)."""
    if v is None:
        return None
    return round(float(v), _GENERALISE_DP)


def _normalise_policy(raw):
    """Trim+lowercase a declared policy token. None/blank is NOT accepted here (the caller supplies
    the 'exact' default for an ABSENT field); a present-but-empty or unknown value is invalid and the
    caller raises. Returns the normalised string (which may be an unknown value the caller rejects)."""
    return str(raw).strip().lower() if raw not in (None, "") else ""


def parse_coordinate_policy(access_block):
    """Read (survey_default, overrides) from a survey.yaml `access` mapping.

    * `access.coordinates`         -> the survey default policy (absent => 'exact', zero behaviour
                                      change for every existing survey).
    * `access.coordinate_overrides` -> optional {STATION_ID: policy} per-station map.

    Returns (default: str, overrides: dict[str, str]) with every value a member of
    COORDINATE_POLICIES. Raises CoordinatePolicyError on any unknown enum value (survey default OR an
    override value) — fail-closed, never coerced to exact. Override IDS are validated separately, via
    validate_overrides (fix round 2: in the build loop at the point the REAL parsed station ids exist,
    for both EDI and MTH5 inputs, before any of that survey's bytes are emitted), because the station
    ids are only known after parsing.

    `access_block` may be anything the YAML gave us (the `access` value): a mapping, or — under the
    older flat schema where `access:` was a bare level string — a non-mapping, in which case there is
    no coordinates policy and the default 'exact' with no overrides is returned.
    """
    if not isinstance(access_block, dict):
        return "exact", {}
    raw_default = access_block.get("coordinates")
    if raw_default in (None, ""):
        default = "exact"
    else:
        default = _normalise_policy(raw_default)
        if default not in COORDINATE_POLICIES:
            raise CoordinatePolicyError(
                f"access.coordinates={raw_default!r} is not one of {list(COORDINATE_POLICIES)} "
                f"— refusing to build this survey (fail closed; fix the policy or omit it for exact).")
    overrides = {}
    raw_overrides = access_block.get("coordinate_overrides")
    if raw_overrides not in (None, "", {}):
        if not isinstance(raw_overrides, dict):
            raise CoordinatePolicyError(
                f"access.coordinate_overrides must be a mapping of {{station_id: policy}}, "
                f"got {type(raw_overrides).__name__} — refusing to build this survey (fail closed).")
        for sid, pol in raw_overrides.items():
            npol = _normalise_policy(pol)
            if npol not in COORDINATE_POLICIES:
                raise CoordinatePolicyError(
                    f"access.coordinate_overrides[{sid!r}]={pol!r} is not one of "
                    f"{list(COORDINATE_POLICIES)} — refusing to build this survey (fail closed).")
            overrides[str(sid)] = npol
    return default, overrides


def base_station_id(station_id, variant=None):
    """THE id half of the one shared matcher (fix round 2): the PHYSICAL station id an override keys
    on — the record id with its engine-appended processing-variant tag stripped. build_portal's
    _disambiguate dedups DATAID collisions as `<base>.<variant>` AND stores the tag on the record
    (`r["variant"]`), so stripping uses that field — NEVER dot-guessing on the id string, because a
    natural DATAID may legitimately contain '.' (safe_component preserves it). A record with no
    variant tag IS its own base."""
    sid = str(station_id) if station_id is not None else ""
    if variant:
        suffix = "." + str(variant)
        if sid.endswith(suffix):
            return sid[: -len(suffix)]
    return sid


def station_policy(default, overrides, station_id, variant=None):
    """The APPLICATION half of the one shared matcher: the effective policy for one station — its
    per-station override if declared, else the survey default. Override keys are BASE station ids
    (fix round 2 ruling): the record's id is base-stripped via base_station_id before matching, so
    privacy of a physical site covers ALL its processing variants. EXACT base match only — no
    prefixes, no stems. validate_overrides() is the validation half, checking keys against the very
    same base_station_id derivation, so a validated key can never be a silent no-op."""
    return (overrides or {}).get(base_station_id(station_id, variant), default)


def validate_overrides(overrides, stations):
    """THE VALIDATION half of the one shared matcher (fix round 2): every override key must be the
    BASE station id of at least one ACTUAL parsed station record in `stations` [(path, record), ...]
    — the same records, the same base_station_id derivation that station_policy applies with, so
    validation and application cannot diverge BY CONSTRUCTION (the probe-e class: a stem∪prefix
    candidate set validated keys the matcher never applied, silently serving a withheld-intent
    station's exact position).

    Rules (all fail-closed, raising CoordinatePolicyError):
      * a key matching NO station's base id fails — file stems are NOT valid keys, full stop (the
        record id derives from the EDI DATAID / MTH5 station, never the file name);
      * a FULL variant-suffixed id (`<base>.<variant>`) is NOT a valid key — overrides key the base;
        an override on the base covers all its variants;
      * a key that IS some station's id but ALSO the file stem of a DIFFERENT station (probe-e's
        exact construction) is AMBIGUOUS — almost certainly a filename-keyed mistake — and fails
        loudly rather than silently masking the wrong physical site.

    Every failure message LISTS the survey's real base station ids, so a custodian who keyed by
    filename learns the correct handles immediately."""
    if not overrides:
        return
    bases = {}
    for (p, r) in stations:
        bases.setdefault(base_station_id(r.get("id"), r.get("variant")), []).append(p)
    unknown = sorted(k for k in overrides if k not in bases)
    if unknown:
        raise CoordinatePolicyError(
            f"access.coordinate_overrides names station id(s) {unknown} that match no station in "
            f"this survey. Override keys are BASE STATION ids (from the EDI DATAID / MTH5 station "
            f"id) — never file names, and never variant-suffixed ids (an override on the base id "
            f"covers all processing variants). This survey's station ids: {sorted(bases)}.")
    # probe-e ambiguity guard: a key that names one station's id but is ALSO the file stem of a
    # DIFFERENT station is almost certainly filename-keyed. Masking whichever station happens to
    # carry that id would silently serve the intended site's exact position — refuse instead.
    for (p, r) in stations:
        stem = Path(str(p)).stem if p is not None else ""
        b = base_station_id(r.get("id"), r.get("variant"))
        for k in overrides:
            if k == stem and k != b:
                raise CoordinatePolicyError(
                    f"access.coordinate_overrides key {k!r} is AMBIGUOUS: it is the file name of "
                    f"{Path(str(p)).name!r} whose station id is {b!r}, while also matching a "
                    f"different station's id. Override keys are STATION ids, never file names — "
                    f"refusing to guess which physical site you meant (fail closed). This survey's "
                    f"station ids: {sorted(bases)}.")


def coordinates_served(policy) -> bool:
    """The per-station BYTE-GATE predicate: only an 'exact' station's source bytes (EDI + EMTF-XML +
    derived EDI) may be served. A generalised or withheld station is byte-gated out entirely — its
    coordinates hide in too many EDI corners (HEAD, INFO free-text, DEFINEMEAS, comments) for
    redaction to be trustworthy, so we withhold the file rather than rewrite custodian bytes (D3)."""
    return policy == "exact"


def _mask_qc_report(qc, masked_ids, policy_of):
    """Rewrite every coordinate-bearing qc_report field so a non-exact station carries no true-position
    bits (D3). Two fields carry coordinates today:

      * outside_declared_extent[].lat/lon (qc_pass :1339) — the TRUE position of a station outside its
        survey's declared extent. For a non-exact station: generalised -> the 0.1deg cell; withheld ->
        null (the station keeps its entry so the FYI is not lost, it simply carries no position).
      * near_duplicate_locations[].at_deg (qc_pass :1311-1318) — a 3-dp ROUNDED derivative of the true
        position (~100 m bin). Finer than the 0.1deg disclosure, so it is a leak for ANY non-exact
        station on either side of the pair; drop it to the generalised cell (or null if withheld).

    `masked_ids` maps a station's qc identity (its `file`/`fid`) to its ausmt_id is NOT available here;
    instead the caller passes `policy_of(entry) -> policy` resolving the entry's policy by whatever key
    the qc field carries. This keeps the qc rewrite artifact-shaped, not id-shaped.
    """
    # outside_declared_extent: keyed by the entry's ausmt_id (present in the entry).
    for e in qc.get("outside_declared_extent", []):
        pol = policy_of(e.get("ausmt_id"))
        if pol == "exact":
            continue
        if pol == "withheld":
            e["lat"] = e["lon"] = None
        else:  # generalised
            e["lat"] = round_generalised(e.get("lat"))
            e["lon"] = round_generalised(e.get("lon"))
    # near_duplicate_locations: each entry is a PAIR (a, b) identified by file names, with a shared
    # at_deg. If EITHER side is non-exact the at_deg (a true derivative finer than 0.1deg) must go —
    # coarsen it to the generalised cell, or null it if either side is withheld. `masked_ids` here is
    # the file->policy resolver the caller supplies via policy_of on the pair's file keys.
    kept = []
    for e in qc.get("near_duplicate_locations", []):
        pa = policy_of(e.get("a"))
        pb = policy_of(e.get("b"))
        if pa == "exact" and pb == "exact":
            kept.append(e)
            continue
        if "withheld" in (pa, pb):
            e["at_deg"] = None
        else:  # both generalised (or exact+generalised) -> coarsen to the disclosed 0.1deg cell
            lat, lon = e.get("at_deg") or [None, None]
            e["at_deg"] = [round_generalised(lat), round_generalised(lon)]
        kept.append(e)
    qc["near_duplicate_locations"] = kept


def apply_coordinate_policy(stations, default, overrides, qc=None):
    """THE mask seam. Mutate the station records IN PLACE (the withhold_tf_row width-preserving
    template) so that, for every non-exact station:

      * withheld  -> lat / lon / elev_m null (the station keeps its row; alignment invariant).
      * generalised -> lat / lon rounded to 0.1deg via round_generalised(); elev_m null (defensive
        invariant per D2 — no served JSON carries elevation today, but any future emitter inherits the
        mask).

    Also nulls the record's OTHER true-coordinate bearers (info_lat/info_lon and coord_candidates) for
    a non-exact station: they are not emitted today, but the record's rule is that no true-position bit
    survives on a non-exact station's post-mask record, so a future emitter cannot resurrect them.

    When `qc` (the qc_pass findings dict) is given, every coordinate-bearing qc_report field is
    rewritten too (see _mask_qc_report) — the qc report is computed on TRUE coords (correct) and then
    de-leaked here, at the SAME single seam.

    Re-validates the overrides against `stations` via validate_overrides (the SAME shared matcher);
    an invalid override here is a hard failure (CoordinatePolicyError) — never a silent no-op.

    Returns the set of ausmt_ids that were masked (non-exact), for the caller's byte-gate/logging.
    """
    # Fail-closed BACKSTOP (defence in depth, fix round 2): the SAME validate_overrides the build
    # loop already ran — on the SAME station records, at the point their ids became known and before
    # any bytes were emitted, for BOTH input kinds (EDI and MTH5 alike). Same function + same inputs
    # => this raise is UNREACHABLE on every input path of a full build, by construction (pinned:
    # probe-e, variant, and mth5-input pins all prove survey-granularity drops with rc=0). It still
    # guards direct API callers; if it ever fires in a full build that is a bug upstream, and
    # aborting loudly beats serving under a half-applied policy.
    validate_overrides(overrides, stations)

    masked_ausmt_ids = set()
    policy_by_ausmt: dict = {}
    policy_by_file: dict = {}
    for (p, r) in stations:
        pol = station_policy(default, overrides, r.get("id"), r.get("variant"))
        # record the resolved policy under BOTH keys the qc fields use (ausmt_id, and the fid = file
        # name / r["file"]) so the qc rewrite can resolve either field's identity.
        policy_by_ausmt[r.get("ausmt_id")] = pol
        _fid = r.get("file") or getattr(p, "name", None)
        if _fid is not None:
            policy_by_file[_fid] = pol
        if pol == "exact":
            continue
        masked_ausmt_ids.add(r.get("ausmt_id"))
        # A1: stamp the RESOLVED policy on the (non-exact) record so the boot-loaded coord_policy.json
        # marker and station.json can emit it WITHOUT re-deriving from coordinate values — the mask seam
        # already resolved it here (the record's rule: reuse, never re-derive). Exact records are left
        # unstamped, so an all-exact corpus keeps its zero-change default (no marker, no new key).
        r["coord_policy"] = pol
        if pol == "withheld":
            r["lat"] = None
            r["lon"] = None
        else:  # generalised: lat/lon to the 0.1deg cell
            r["lat"] = round_generalised(r.get("lat"))
            r["lon"] = round_generalised(r.get("lon"))
        # elevation nulled for BOTH non-exact classes (defensive invariant, D2).
        r["elev_m"] = None
        # scrub the record's other true-coordinate bearers so no future emitter can resurrect them.
        r["info_lat"] = None
        r["info_lon"] = None
        r["coord_candidates"] = None
        # processing_note is the raw >INFO free-text scraped from the EDI (station.json processing.note).
        # It carries the INFO block's LATITUDE/LONGITUDE/ELEVATION lines verbatim — a true-position leak
        # the artifact-agnostic leak-sweep caught. Coordinates hide in too many free-text corners to redact
        # trustworthily (the same reasoning that byte-gates the EDI rather than rewriting it, D3), so the
        # whole derived note is WITHHELD for a non-exact station. It is best-effort metadata, not data; the
        # curator still sees the full note in the package (surveys-live). remote_site (a station NAME, no
        # position) is kept.
        r["processing_note"] = None

    if qc is not None:
        def _policy_of(key):
            # a qc field carries either an ausmt_id (outside_declared_extent) or a file name
            # (near_duplicate_locations a/b). Resolve via whichever map has it; default exact
            # (an unknown key is treated as exact so we never over-mask an unrelated entry).
            if key in policy_by_ausmt:
                return policy_by_ausmt[key]
            return policy_by_file.get(key, "exact")
        _mask_qc_report(qc, masked_ausmt_ids, _policy_of)

    return masked_ausmt_ids


def apply_coordinate_policy_corpus(all_stations, policy_of_survey, qc=None):
    """Corpus-wide driver of the single mask seam over a MULTI-survey station list (build_portal's
    `all_stations`, one tuple per catalogued station across every survey). `policy_of_survey(label)`
    returns that survey's (default, overrides). Groups stations by their survey label, masks each
    group's records in place with that survey's policy (validating its override ids against ITS OWN
    stations, fail-closed), then rewrites the coordinate-bearing qc_report fields ONCE using a
    corpus-wide policy resolver (the qc report spans all surveys). Returns the set of masked ausmt_ids.

    This is the single seam the record mandates: it runs AFTER the corpus-wide qc_pass (which sees true
    coordinates) and BEFORE any emitter reads the records. Records are shared objects, so mutating them
    here masks every downstream emitter (catalogue, mtcat, collections, station.json) with no per-emitter
    logic."""
    # group station tuples by survey label
    by_survey: dict = {}
    for (p, r) in all_stations:
        by_survey.setdefault(r.get("survey"), []).append((p, r))

    masked_ausmt_ids: set = set()
    policy_by_ausmt: dict = {}
    policy_by_file: dict = {}
    for label, group in by_survey.items():
        default, overrides = policy_of_survey(label)
        # mask this survey's records in place (qc=None here; the qc rewrite is done once, below, over
        # the corpus). Override-id validation happens per survey against ITS station set (fail-closed).
        masked_ausmt_ids |= apply_coordinate_policy(group, default, overrides, qc=None)
        # accumulate the resolved per-station policy under both qc identity keys for the corpus rewrite.
        for (p, r) in group:
            pol = station_policy(default, overrides, r.get("id"), r.get("variant"))
            policy_by_ausmt[r.get("ausmt_id")] = pol
            _fid = r.get("file") or getattr(p, "name", None)
            if _fid is not None:
                policy_by_file[_fid] = pol

    if qc is not None:
        def _policy_of(key):
            if key in policy_by_ausmt:
                return policy_by_ausmt[key]
            return policy_by_file.get(key, "exact")
        _mask_qc_report(qc, masked_ausmt_ids, _policy_of)

    return masked_ausmt_ids
