"""normalize: the Phase-1 canonical ingest path (mt_metadata-backed).

Any TF input (EDI / EMTF XML) -> mt_metadata TF object -> a *conditioned*, schema-valid canonical
EMTF XML + a derived EDI, with a VERIFIED round-trip (impedance preserved). This backs the Phase-1
D6 canonical EMTF XML store (see docs developer docs / the Phase-1 format-backbone design).
Requires the core mt_metadata/mth5 stack; every heavy import is function-local so merely importing
this module is cheap and never pulls the heavy stack until normalize() is actually called.

WHY a conditioning step is required (measured on real AusLAMP/AusMT EDIs, mt_metadata 1.0.9):
mt_metadata does NOT round-trip arbitrary real EDIs through EMTF XML out of the box — its writer
emits metadata its own reader then rejects. Four distinct issues occur, all handled here:
  1. enum serialization bug: `sub_type` is written as the repr "DataTypeEnum.MT_TF" instead of the
     value "MT_TF", which fails validation on read. Fixed by rewriting the XML post-write.
  2. Copyright.citation = None is rejected on read; we populate citation_dataset — HONESTLY, from the
     survey SMETA (custodian org / investigators / survey title / DOI), NEVER the portal brand "AusMT"
     (which would falsely assert the portal authored the custodian's data). Absent survey_meta => an
     explicit "unknown (not asserted by source)", not a fabricated value.
  3. Survey.id pattern: mt_metadata maps the free-text `geographic_name` into the restricted
     Survey.id slot (pattern ^[a-zA-Z0-9_\\- ]*$), so a name with commas/parens fails the WRITE.
     We sanitize geographic_name (keeping spaces for readability). Verified: setting survey_metadata.id
     alone does NOT help — geographic_name is the field that must be cleaned.
  4. _rotation_angle = None for spectra-origin (Phoenix EMpower) TFs blocks the write; mt_metadata's
     writer requires the array, so we zero-fill — but honestly: a machine-readable note records that the
     frame is NOT asserted (not a claimed 0°), and build_portal surfaces it (station marked conditioned).
  5. Site.id (station_metadata.id) pattern is even stricter — ^[a-zA-Z0-9]*$ (no underscore/hyphen) —
     so real ids like "C6_BxByReplaced" fail the write; sanitized to alphanumeric for the Site.id +
     filename. The UNSANITISED source id is preserved INSIDE the artifact, in the Site <Name>
     (geographic_name) — the free-text station slot that survives the round-trip — recoverable via
     source_station_id_from_geographic_name(). (Site.id sanitising found by the full-corpus parity run.)
  6. Site.project pattern is ^[a-zA-Z0-9-_]*$ (no spaces) — survey project names like "Stuart Shelf
     2009" fail the write; sanitized (the readable name stays in survey.yaml). Found by the
     remote-reference data inspection across real dialects (EDL/BIRRP).
  7. Library-default metadata the XML asserts as fact (final hostile audit 4.2): for EDI sources the
     sign convention, declination epoch/model, and degenerate-geometry channel orientations are
     mt_metadata defaults the source never stated. The values stay (the writer requires them) but
     each gets a machine-readable NOT-asserted conditioning note, like the rotation zero-fill.

The round-trip is then VERIFIED (impedance allclose) and a failure RAISES — a hard QC gate, so a
silently-broken canonical artifact can never be published. The original upload remains the citable
artifact (it is never mutated here); this module only produces the derived canonical + convenience
files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Mirrors mt_metadata's EMTF-XML id-field validator: letters, digits, underscore, hyphen, space.
_ID_BAD = re.compile(r"[^a-zA-Z0-9_\- ]")
# 'DataTypeEnum.MT_TF' -> 'MT_TF' (and any other '<Word>Enum.VALUE' the writer emits as a repr).
_ENUM_REPR = re.compile(r"\b\w+Enum\.(\w+)")
# mt_metadata/EMTF-XML missing-data sentinel (~1e32, settled design — see extract/_mtm.py _FILL_MAX).
# Same threshold reused here for the round-trip QC gate's tipper/error comparisons (not invented).
_FILL_MAX = 1e8


def _sanitize_id(value: Optional[str], default: str) -> str:
    cleaned = _ID_BAD.sub("_", (value or "").strip())
    return cleaned or default


def _sanitize_name(value: Optional[str]) -> Optional[str]:
    # Keep spaces/readability; strip only the chars the id validator rejects (commas, parens, dots).
    return _ID_BAD.sub("", value) if value else value


def _sanitize_alnum(value: Optional[str], default: str) -> str:
    # EMTF-XML Site.id is stricter than Survey.id: ^[a-zA-Z0-9]*$ (no underscore/hyphen/space). The
    # station's real identity is preserved by the AusMT ausmt_id (EDI DATAID) and the artifact
    # filename; this only cleans the XML's internal Site.id so the write/read validates.
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", (value or "").strip())
    return cleaned or default


# Recoverable token that carries the UNSANITISED source station id inside the artifact. It rides in
# the EMTF-XML Site <Name> (station_metadata.geographic_name), the one free-text station slot that
# survives mt_metadata's write->read round-trip (station.comments and transfer_function.id do NOT).
# Only the id-safe chars of the id survive (Site.id validator set: letters/digits/_/-/space) — a colon
# separates the marker so the token can be recovered even when appended to a real geographic name.
_SRC_ID_MARKER = "ausmt_src_id:"
_SRC_ID_RE = re.compile(r"ausmt_src_id:(\S+)")


def source_station_id_from_geographic_name(geographic_name: Optional[str]) -> Optional[str]:
    """Recover the true source station id embedded by condition_tf, from a (possibly round-tripped)
    Site <Name>/geographic_name. Returns None when no token is present (id needed no sanitising)."""
    if not geographic_name:
        return None
    m = _SRC_ID_RE.search(geographic_name)
    return m.group(1) if m else None


def _survey_meta_get(survey_meta: Optional[dict]):
    """Extract (authors, title_prefix, doi) intent from a survey SMETA dict, honestly. authors prefers
    named investigators over the custodian organisation; NEVER the portal brand. Returns (None,None,None)
    when survey_meta is absent so the caller can fall back to an explicit-unknown, not a fabricated value.

    C7: SMETA.investigators is [{name, orcid}, ...] (build_portal._investigators_of no longer discards
    the ORCID); only the name feeds the citation-author string here. Still tolerates the PRE-C7 shape
    (bare name strings) so a stale/hand-built survey_meta degrades to the same author string instead of
    a stringified-dict repr."""
    if not survey_meta:
        return None, None, None
    invs_raw = survey_meta.get("investigators") or []
    invs = [str(x.get("name") or "").strip() if isinstance(x, dict) else str(x).strip()
            for x in invs_raw]
    invs = [x for x in invs if x]
    org = (survey_meta.get("org") or "").strip() or None
    authors = ", ".join(invs) if invs else org           # investigator names > custodian org
    cite = survey_meta.get("cite") if isinstance(survey_meta.get("cite"), dict) else {}
    title = (cite.get("ti") or survey_meta.get("title") or "").strip() or None
    doi = (survey_meta.get("doi") or "").strip() or None
    return authors, title, doi


def condition_tf(tf, *, survey_id: str, station_id: Optional[str] = None,
                 survey_meta: Optional[dict] = None,
                 source_format: Optional[str] = None) -> list[str]:
    """Make an mt_metadata TF schema-valid for EMTF-XML write+read. Returns notes of what changed.

    `survey_meta` (a survey SMETA dict: org, investigators, cite.ti/title, doi) sources the citation
    honestly — see the citation block below. When absent (bare API use), the citation is left unset or
    filled with an explicit-unknown, NEVER the portal brand "AusMT" (the historical fabrication defect).

    `source_format` (the source file suffix, e.g. ".edi") gates the Issue-#7 library-default notes:
    an EDI cannot state those fields machine-readably, so for EDI sources they are always library
    defaults and get flagged; an EMTF-XML source CAN state them, so no note is emitted there (or when
    the caller does not say — backward compatible).

    Mutates the in-memory TF object only (never the source file)."""
    import numpy as np  # noqa: PLC0415

    n_periods = int(tf.period.size)
    notes: list[str] = []

    sm = tf.survey_metadata
    sid = _sanitize_id(survey_id, "ausmt_survey")
    if sm.id != sid:
        sm.id = sid
        notes.append(f"survey.id->{sid}")

    # Site.id (station_metadata.id) — alphanumeric-only EMTF-XML pattern (real ids like
    # "C6_BxByReplaced" carry underscores). Sanitize so the XML validates; the station's true id is
    # carried by the AusMT ausmt_id and the artifact filename.
    # Site.id: prefer the authoritative id passed in (the EDI DATAID, Phoenix-unpacked) over what
    # mt_metadata parsed — which is empty/mangled for compound 'P=<station> R=<remote>' DATAIDs.
    st_src = station_id if station_id else getattr(tf.station_metadata, "id", None)
    st_new = _sanitize_alnum(st_src, "station")
    if tf.station_metadata.id != st_new:
        tf.station_metadata.id = st_new
        notes.append(f"station.id->{st_new}")

    # Site.project pattern is ^[a-zA-Z0-9-_]*$ (no spaces) — survey project names like
    # "Stuart Shelf 2009" fail the EMTF-XML write. Sanitize (the readable name stays in survey.yaml).
    proj = getattr(sm, "project", None)
    if proj:
        proj2 = re.sub(r"[^a-zA-Z0-9_-]", "_", proj)
        if proj2 != proj:
            sm.project = proj2
            notes.append(f"survey.project->{proj2}")

    # Issue #3: geographic_name leaks into the restricted Survey.id slot on write.
    for obj, label in ((tf.survey_metadata, "survey"), (tf.station_metadata, "station")):
        name = getattr(obj, "geographic_name", None)
        cleaned = _sanitize_name(name)
        if cleaned != name:
            obj.geographic_name = cleaned
            notes.append(f"{label}.geographic_name sanitized")

    # Identity preservation: when the Site.id sanitiser above ACTUALLY dropped identity
    # (true id != Site.id), embed the unsanitised source id in the Site <Name>
    # (station_metadata.geographic_name) — the one free-text station slot that survives the EMTF-XML
    # write->read round-trip (station.comments and transfer_function.id do NOT). This AUGMENTS any real
    # geographic name (e.g. Phoenix's "Near Broken Hill, AU"), it never replaces it, and runs AFTER the
    # Issue #3 sanitisation so the marker's ':' is not stripped. So the artifact is not the only place
    # the real id is lost; recover it with source_station_id_from_geographic_name(). Skipped when the id
    # needed no sanitising (nothing to recover) — no pollution of the common clean-id case.
    st_true = (st_src or "").strip()
    if st_true and st_true != st_new and _SRC_ID_MARKER not in (tf.station_metadata.geographic_name or ""):
        _existing = (tf.station_metadata.geographic_name or "").strip()   # already sanitised above
        tf.station_metadata.geographic_name = (f"{_existing} {_SRC_ID_MARKER}{st_true}").strip()
        notes.append(f"station.source_id_preserved_in_site_name:{st_true}")

    # Issue #4: spectra-origin TFs have _rotation_angle == None (frame unknown — e.g. Phoenix EMpower,
    # derived from a spectra section). mt_metadata's writer requires the array, so we STILL zero-fill —
    # but honestly: the note is machine-readable and states the frame is NOT asserted, and build_portal
    # surfaces it (marks the station's canonical/served XML as conditioned). This is the least-bad option
    # mt_metadata 1.0.9 allows; a written frame of 0° would otherwise be an unflagged fabrication.
    if getattr(tf, "_rotation_angle", None) is None:
        tf._rotation_angle = np.zeros(n_periods)
        notes.append("rotation: unknown — writer requires array; zeros written, frame NOT asserted")

    # Issue #7 (final hostile audit 4.2): fields mt_metadata fills with LIBRARY DEFAULTS that an EDI
    # cannot state machine-readably, yet the written XML asserts as station facts — the sign
    # convention (<SignConvention>+), the declination epoch/model, and channel orientations
    # synthesised from degenerate EMEAS geometry (zero-length, azimuth-less dipoles => Ey "north").
    # Same honesty contract as the Issue-#4 rotation zero-fill: the values STAY (the writer requires
    # them; nulling breaks the write), but a machine-readable note records that each is NOT asserted
    # by the source. Gated on EDI sources only — an EMTF-XML source can state all three, so there
    # they are source-authored and a note would itself be false.
    if source_format == ".edi":
        try:
            sc_val = getattr(getattr(tf.station_metadata, "transfer_function", None),
                             "sign_convention", None)
            if sc_val:
                notes.append(f"sign_convention: '{sc_val}' is a library default — EDI carries no "
                             "machine-readable sign convention; NOT asserted by source")
        except Exception:  # noqa: BLE001  (model shape varies across mt_metadata versions; non-fatal)
            pass
        try:
            dec = getattr(getattr(tf.station_metadata, "location", None), "declination", None)
            epoch = getattr(dec, "epoch", None) if dec is not None else None
            model = getattr(dec, "model", None) if dec is not None else None
            if epoch or model:
                notes.append(f"declination.epoch/model: library defaults (epoch={epoch}, "
                             f"model={model}) — an EDI states only the declination value; "
                             "epoch/model NOT asserted by source")
        except Exception:  # noqa: BLE001
            pass
        try:
            for run in (getattr(tf.station_metadata, "runs", None) or []):
                # Run has no .ex/.ey attributes — channels are reached via get_channel() (pydantic
                # ListDict model, verified on mt_metadata 1.0.9's Run).
                try:
                    ex, ey = run.get_channel("ex"), run.get_channel("ey")
                except Exception:  # noqa: BLE001
                    continue
                if ex is None or ey is None:
                    continue
                ax = getattr(ex, "measurement_azimuth", None)
                ay = getattr(ey, "measurement_azimuth", None)
                # Two degenerate shapes, both meaning "the XML's orientations are not measurements":
                # (a) azimuths UNSTATED (None/None) — the EMTF-XML writer then defaults both to 0,
                #     printing Ey as pointing north (the audit's reproduced Vulcan_A1 case); or
                # (b) azimuths stated but IDENTICAL — parallel electric dipoles are non-physical.
                both_none = ax is None and ay is None
                both_equal = ax is not None and ay is not None and abs(float(ax) - float(ay)) < 1e-6
                if both_none or both_equal:
                    detail = ("ex and ey azimuths unstated; the writer defaults both to 0"
                              if both_none else
                              f"ex and ey azimuths both {float(ax):g} deg — parallel dipoles are non-physical")
                    notes.append(f"channel orientations: degenerate/defaulted ({detail}); "
                                 "orientations NOT asserted by source EMEAS geometry")
                    break
        except Exception:  # noqa: BLE001
            pass

    # Issue #2: a None Copyright.citation is written but rejected on read. Populate it HONESTLY from the
    # survey SMETA (authors = named investigators, else the custodian organisation; title = survey
    # title + station; the survey DOI when present). NEVER the portal brand "AusMT" — the survey
    # custodian, not the portal, authored the data (the historical fabrication defect). When no
    # survey_meta is supplied (bare API use) fall back to an EXPLICIT-unknown so the field is honest
    # rather than falsely attributed; silence is preferred but this mt_metadata build rejects a None
    # citation on read, so an explicit "unknown (not asserted by source)" is the honest minimum.
    sm_authors, sm_title, sm_doi = _survey_meta_get(survey_meta)
    try:
        cd = sm.citation_dataset
        if not getattr(cd, "authors", None):
            if sm_authors:
                cd.authors = sm_authors
                notes.append(f"citation.authors<-survey_meta:{sm_authors}")
            else:
                cd.authors = "unknown (not asserted by source)"
                notes.append("citation.authors=explicit-unknown (no survey_meta)")
        if not getattr(cd, "title", None):
            # title = survey title + the TRUE station id (free-text, round-trips fine — so it carries the
            # unsanitised id, not the lossy Site.id); else fall back to the survey id when no survey title.
            if sm_title:
                cd.title = f"{sm_title} - {st_true or st_new}"
                notes.append("citation.title<-survey_meta")
            else:
                cd.title = sm.id
                notes.append("citation.title=survey.id")
        if sm_doi and not getattr(cd, "doi", None):
            cd.doi = sm_doi                       # mt_metadata normalises to https://doi.org/<doi>
            notes.append(f"citation.doi<-survey_meta:{sm_doi}")
    except Exception:  # noqa: BLE001  (citation model varies across versions; non-fatal)
        pass

    return notes


def _fix_enum_repr(xml_path: Path) -> bool:
    """Issue #1: rewrite '<Word>Enum.VALUE' -> 'VALUE' in the written XML so mt_metadata can re-read it."""
    text = xml_path.read_text(encoding="utf-8")
    fixed = _ENUM_REPR.sub(r"\1", text)
    if fixed != text:
        xml_path.write_text(fixed, encoding="utf-8")
        return True
    return False


def _mask_fills(a, b):
    """Boolean mask of cells where EITHER side is the ~1e32 EMTF-XML missing-data fill (|v|>_FILL_MAX).

    Same convention as extract/_mtm.py._is_missing — NOT invented here. Real EDIs from some producers
    (e.g. Geotools/MT-GFZ) carry the community missing-data sentinel 1e32 INSIDE impedance data blocks
    at periods where a component is undetermined. mt_metadata's EDI reader turns those into 0+0j, but
    its EMTF-XML writer faithfully re-emits the 1e32 sentinel (D6: the canonical XML must stay
    mt_metadata-faithful, sentinels included), which re-reads as (1e32+1e32j). Comparing orig 0+0j vs
    re-read (1e32+1e32j) at such a cell is a fill-vs-fill artefact, not a corrupted transfer function —
    so the round-trip comparators exclude these cells and verify only the real (non-fill) values."""
    import numpy as np  # noqa: PLC0415

    return (np.abs(a) > _FILL_MAX) | (np.abs(b) > _FILL_MAX)


def _compare_optional_field(name: str, orig, rt, *, src_name: str, rtol: float, atol: float) -> None:
    """Round-trip check for a field that may legitimately be absent (tipper/impedance_error/
    tipper_error): None on both sides is fine (no such data), but present-on-original-yet-missing-
    on-re-read is exactly the silent-corruption case this gate exists to catch, so it FAILS. Present
    on both: shape must match and values must agree, masking cells that are the ~1e32 missing-data
    fill on EITHER side (same convention as extract/_mtm.py._is_missing — not invented here)."""
    import numpy as np  # noqa: PLC0415

    if orig is None:
        return  # absent on the original: nothing to verify (rt may be None or all-zero; not our concern)
    if rt is None:
        raise RuntimeError(
            f"canonical EMTF-XML round-trip FAILED for {src_name}: {name} present on the original "
            f"but MISSING on re-read — a silently-dropped field")
    a = np.asarray(orig.data)
    b = np.asarray(rt.data)
    if a.shape != b.shape:
        raise RuntimeError(
            f"canonical EMTF-XML round-trip FAILED for {src_name}: {name} shape mismatch "
            f"original={a.shape} re-read={b.shape}")
    mask = _mask_fills(a, b)  # exclude missing-data fills either side
    a, b = np.where(mask, 0, a), np.where(mask, 0, b)
    if not np.allclose(a, b, rtol=rtol, atol=atol, equal_nan=True):
        maxdiff = float(np.nanmax(np.abs(a - b)))
        raise RuntimeError(
            f"canonical EMTF-XML round-trip FAILED for {src_name}: {name} maxdiff={maxdiff:.3e} "
            f"(rtol={rtol}, atol={atol})")


@dataclass
class NormalizeResult:
    canonical_xml: Path
    derived_edi: Path
    n_periods: int
    roundtrip_maxdiff: float
    conditioned: list[str]
    versions: dict = field(default_factory=dict)


def normalize(src: str | Path, out_dir: str | Path, *, survey_id: str,
              station_id: Optional[str] = None, survey_meta: Optional[dict] = None,
              rtol: float = 1e-3, atol: float = 1e-6) -> NormalizeResult:
    """Read a TF (EDI/EMTF-XML) -> conditioned canonical EMTF XML + derived EDI, round-trip verified.

    `survey_meta` (the survey's SMETA dict) sources the citation honestly (custodian org / investigators
    / survey title / DOI) — see condition_tf. The returned NormalizeResult.conditioned notes list what
    was conditioned (rotation-unknown, source-id preservation, citation provenance); callers persist it.

    Raises RuntimeError if the impedance does not survive the EDI->XML->re-read round-trip — the QC
    gate that stops a silently-broken canonical artifact from being published. The source file is
    read but never modified (it remains the citable artifact)."""
    import numpy as np  # noqa: PLC0415
    from mt_metadata.transfer_functions.core import TF  # noqa: PLC0415

    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = station_id or src.stem

    tf = TF()
    tf.read(str(src))
    notes = condition_tf(tf, survey_id=survey_id, station_id=station_id, survey_meta=survey_meta,
                         source_format=src.suffix.lower())

    canonical_xml = out_dir / f"{stem}.xml"
    # The canonical XML is mt_metadata's FAITHFUL standard EMTF-XML output. For missing components
    # (e.g. an absent tipper period) mt_metadata's writer emits the EMTF-XML missing-data sentinel
    # ~1e32 — this is the community-standard convention (SPUD/EMTF/mtpy-v2 readers treat |v|>1e8 as
    # missing, exactly as AusMT's own _mtm._is_missing does for the portal tf.json). Do NOT "null" or
    # strip these fills here: that would make AusMT's served canonical form DIVERGE from what the
    # reference tool produces (the whole point of D6 is to serve the standard form). The portal's
    # tf.json is a display derivative that nulls the fill; the canonical XML keeps it.
    tf.write(str(canonical_xml), file_type="emtfxml")
    _fix_enum_repr(canonical_xml)

    derived_edi = out_dir / f"{stem}.edi"
    tf.write(str(derived_edi), file_type="edi")

    # Round-trip QC gate: re-read the canonical XML and confirm the impedance is preserved.
    tf_rt = TF()
    tf_rt.read(str(canonical_xml))
    za = np.asarray(tf.impedance.data)
    zb = np.asarray(tf_rt.impedance.data)
    # A header-only / period-less TF (no impedance) must NOT pass: np.allclose over EMPTY arrays is
    # vacuously True, which would certify a canonical artifact that contains no data. Fail loudly so the
    # caller logs+skips it rather than publishing a "verified" empty XML.
    if za.shape[0] == 0 or not int(getattr(tf, "period", np.asarray([])).size):
        raise RuntimeError(
            f"canonical EMTF-XML QC for {src.name}: no impedance/periods to verify (empty TF) — "
            f"refusing to certify an artifact with no data")
    # Shape equality (period count AND 2x2) is required, not just a prefix comparison: a re-read with
    # FEWER periods than the original must not silently pass by only checking the common prefix.
    if za.shape != zb.shape:
        raise RuntimeError(
            f"canonical EMTF-XML round-trip FAILED for {src.name}: impedance shape mismatch "
            f"original={za.shape} re-read={zb.shape}")
    # Mask the ~1e32 missing-data fill on EITHER side (see _mask_fills): some real EDIs carry the
    # community sentinel INSIDE impedance blocks at undetermined periods; mt_metadata reads those as
    # 0+0j but its writer faithfully re-emits 1e32, which re-reads as (1e32+1e32j). That fill-vs-fill
    # artefact (maxdiff=sqrt(2)*1e32) is not a corrupted transfer function, so the gate compares only
    # the real (non-fill) values — maxdiff is reported over the masked cells too.
    z_mask = _mask_fills(za, zb)
    za_c, zb_c = np.where(z_mask, 0, za), np.where(z_mask, 0, zb)
    maxdiff = float(np.nanmax(np.abs(za_c - zb_c)))
    if not np.allclose(za_c, zb_c, rtol=rtol, atol=atol, equal_nan=True):
        raise RuntimeError(
            f"canonical EMTF-XML round-trip FAILED for {src.name}: impedance maxdiff={maxdiff:.3e} "
            f"(rtol={rtol}, atol={atol})")

    # tipper / impedance_error / tipper_error: previously never compared, so a re-read that silently
    # dropped or corrupted any of these passed the gate. Absent-on-original is fine either way.
    _compare_optional_field("tipper", tf.tipper, tf_rt.tipper, src_name=src.name, rtol=rtol, atol=atol)
    _compare_optional_field("impedance_error", tf.impedance_error, tf_rt.impedance_error,
                             src_name=src.name, rtol=rtol, atol=atol)
    _compare_optional_field("tipper_error", tf.tipper_error, tf_rt.tipper_error,
                             src_name=src.name, rtol=rtol, atol=atol)

    # Derived-EDI spot check: the EDI is also published, so it must round-trip too — a cheap full
    # check (one extra file re-read; the impedance arrays being compared are already in memory).
    tf_edi_rt = TF()
    tf_edi_rt.read(str(derived_edi))
    zc = np.asarray(tf_edi_rt.impedance.data)
    if za.shape != zc.shape:
        raise RuntimeError(
            f"derived EDI round-trip FAILED for {src.name}: impedance shape mismatch "
            f"original={za.shape} derived-edi={zc.shape}")
    # Same fill masking as the canonical-XML comparison above: exclude the ~1e32 missing-data sentinel
    # on either side so a fill-vs-fill artefact is not read as a corrupted transfer function.
    zc_mask = _mask_fills(za, zc)
    za_e, zc_e = np.where(zc_mask, 0, za), np.where(zc_mask, 0, zc)
    if not np.allclose(za_e, zc_e, rtol=rtol, atol=atol, equal_nan=True):
        edi_maxdiff = float(np.nanmax(np.abs(za_e - zc_e)))
        raise RuntimeError(
            f"derived EDI round-trip FAILED for {src.name}: impedance maxdiff={edi_maxdiff:.3e} "
            f"(rtol={rtol}, atol={atol})")

    versions = {}
    try:
        import mt_metadata  # noqa: PLC0415
        versions["mt_metadata"] = mt_metadata.__version__
    except Exception:  # noqa: BLE001
        pass
    try:
        import mth5  # noqa: PLC0415
        versions["mth5"] = mth5.__version__
    except Exception:  # noqa: BLE001
        pass

    return NormalizeResult(
        canonical_xml=canonical_xml, derived_edi=derived_edi, n_periods=int(tf.period.size),
        roundtrip_maxdiff=maxdiff, conditioned=notes, versions=versions)
