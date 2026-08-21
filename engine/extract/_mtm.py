#!/usr/bin/env python3
"""mt_metadata-based EDI extractor — the sole parser since the regex retirement.

Produces a station record dict (`record_from_tf`) and a canonical component dict
(`components_from_tf`) that feed the shared downstream math in `_edi_tf.tf_from_components` and
`_edi_science.science_from_components`. mt_metadata reads each EDI ONCE into a TF object (`read`)
that the record/components/processing helpers all reuse.

mt_metadata is the canonical community model (Kelbert lens) and the basis of the EMTF XML canonical
store (see docs developer/architecture.md).
"""
from __future__ import annotations
import math
import re
import sys
import tempfile
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
# mt_metadata logs verbose per-file warnings via loguru; silence them for batch use.
try:
    from loguru import logger as _loguru_logger
    _loguru_logger.disable("mt_metadata")
except Exception:  # noqa: BLE001
    pass

try:
    from mt_metadata.transfer_functions.core import TF
    HAVE_MTM = True
except Exception:  # noqa: BLE001
    HAVE_MTM = False


def available() -> bool:
    return HAVE_MTM


# ---------------------------------------------------------------------------------------------
# mt_metadata 1.0.9 >INFO JSON trailing-delimiter defect (measured 2026-08-08, GSSA Western Gawler
# 2023, a Zonge job: 246 of 312 EDIs unreadable). THE DATA IS FINE; THE READER IS WRONG, in three
# composing steps, all in mt_metadata:
#
#   1. io/tools.py::_validate_edi_lines strips `"`, `'`, `[` and `]` from EVERY line of the file
#      before any section parser runs:
#          return [line.replace('"', "").replace("'", "").replace("[", "").replace("]", "")
#                  for line in edi_lines]
#      so the JSON object member `    "Declination": 5,` reaches the >INFO parser as
#      `    Declination: 5,`, now indistinguishable from an EDI `key: value` pair.
#   2. io/edi/metadata/information.py::read_info flips into its EMPOWER branch for any INFO line
#      containing "empower" and "v". The Zonge JSON carries `"empower_version": "v1.54.2.5"`, so
#      the branch fires on a file that is not in Empower's line-oriented format at all.
#   3. _parse_empower_info splits on `:` and keeps the remainder verbatim (`value = parts[1].strip()`).
#      Its cleanup handles bracketed units and degree symbols; NOTHING removes JSON's structural
#      member separator. The value is the STRING '5,', _empower_translation_dict maps `declination`
#      onto the typed field station.location.declination.value, and pydantic's float validator raises.
#
# The defect is a CLASS: every JSON scalar that is not the LAST member of its object keeps its
# trailing comma (measured: 141 of 160 scraped values on one file). Declination is only the one that
# lands in a numerically-typed field, so it is the only one that RAISES; the rest carry junk into
# free-text metadata silently. The remedy below therefore targets the trailing DELIMITER, not the
# word "Declination". (The 21 Western Gawler files that carry the key and still parse simply lack an
# "empower" token, so step 2 never fires for them and the value never reaches a typed field.)
#
# THE REMEDY IS PARSE-ONLY. The normalised copy lives in a TemporaryDirectory that is destroyed
# before this function returns, is never returned to a caller, and never reaches the served tree or
# the sha256 integrity gate (both of which take the ORIGINAL path). D1 stands: source EDI bytes are
# never edited, and what AusMT serves stays byte-identical to what the custodian released.
INFO_JSON_DELIMITER_DEFECT = (
    "mt_metadata could not read the >INFO JSON block: a JSON scalar kept its trailing delimiter; "
    "reparsed from a normalised temporary copy (the source file is untouched and is what is served)"
)

# The observable signature of the defect: a pydantic scalar-parsing failure (`*_parsing`) whose
# offending input is a STRING ending in the JSON member separator. Deliberately narrow -- an
# unrelated read failure has either a different error type or an input that does not end in a comma,
# and must still fail loudly.
#
# BOUNDARY, stated because the NORMALISATION below is general over the delimiter class while this
# TRIGGER is not. Only pydantic's own scalar coercion (`float_parsing`, `int_parsing`, ...) is
# recognised. A field whose custom validator raises `value_error` instead is NOT recognised, even if
# its input carries the same trailing comma -- mt_metadata's lat/lon validator is exactly that shape.
# That restriction has no effect on this corpus: substituting every other key `_empower_translation_dict`
# maps onto a typed field (year, process_date, length, azimuth, ac, dc, negative_res, positive_res) into
# the fixture still PARSES on stock 1.0.9, so `declination` is the only mapped key that raises at all, and the one
# real value_error in the selected corpus (capricorn CP3B21.edi, reflat='--26.0322667') has no trailing
# comma either way. If a value_error-shaped instance of the delimiter class ever turns up, widening
# here is safe by construction -- guards 3 and 4 of _read_with_fallback make a false positive inert --
# but it is not widened on speculation.
_DELIMITED_SCALAR_RE = re.compile(r"type=\w+_parsing, input_value='[^']*,'")


def _is_info_delimiter_defect(exc: BaseException) -> bool:
    """True only for the >INFO trailing-delimiter defect above. Prefers pydantic's STRUCTURED errors
    (stable across message rewording) and falls back to the rendered message for any other raiser."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            rows = list(errors())
        except Exception:  # noqa: BLE001  (a non-pydantic .errors(); fall through to the message)
            rows = None
        if rows is not None:
            for row in rows:
                if not str(row.get("type", "")).endswith("_parsing"):
                    continue
                value = row.get("input")
                if isinstance(value, str) and value.rstrip().endswith(","):
                    return True
            return False
    return bool(_DELIMITED_SCALAR_RE.search(str(exc)))


def normalise_info_json_delimiters(raw: bytes) -> bytes:
    """Return `raw` with the JSON structural member separator removed from the end of lines INSIDE
    the >INFO block, and every other byte of the file left exactly as it was.

    Operates on BYTES and never re-encodes, so nothing outside the one dropped comma can shift. The
    block bounds mirror mt_metadata's own read_info (start: a line containing ">info"; end: the next
    line starting with ">"), so the region normalised is exactly the region it mis-parses. Returns
    the ORIGINAL object when there is nothing to change, which is what lets the caller refuse to
    retry a file that does not actually carry the defect."""
    out: list[bytes] = []
    in_info = False
    changed = False
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        eol = line[len(body):]
        stripped = body.strip()
        if not in_info:
            if b">info" in stripped.lower():
                in_info = True
            out.append(line)
            continue
        if stripped.startswith(b">"):        # next section: the >INFO block is over
            in_info = False
            out.append(line)
            continue
        trimmed = body.rstrip()
        if trimmed.endswith(b","):
            changed = True
            out.append(trimmed[:-1] + body[len(trimmed):] + eol)   # keep trailing space + line ending
        else:
            out.append(line)
    return b"".join(out) if changed else raw


def _read_once(path: Path):
    tf = TF()
    tf.read(str(path))
    return tf


def _read_with_fallback(path: Path):
    """(TF, fallback_reason_or_None). Normal read first; on a failure ATTRIBUTABLE TO the >INFO
    delimiter defect, retry ONCE against a normalised temporary copy, then return the parse.

    Narrow by construction, in four independent ways, so no unrelated failure is ever swallowed:
      * only for `.edi` inputs (>INFO is an EDI construct);
      * only when the raised error carries the defect's signature (_is_info_delimiter_defect);
      * only when normalisation actually CHANGES the bytes, i.e. the file really carries it;
      * and if the retry itself fails, the ORIGINAL exception is re-raised, so a file broken for any
        other reason still fails exactly as it does today, with its own error.
    """
    p = Path(path)
    try:
        return _read_once(p), None
    except Exception as exc:  # noqa: BLE001  (re-raised unless it is precisely this defect)
        if p.suffix.lower() != ".edi" or not _is_info_delimiter_defect(exc):
            raise
        raw = p.read_bytes()
        fixed = normalise_info_json_delimiters(raw)
        if fixed == raw:
            raise
        with tempfile.TemporaryDirectory(prefix="ausmt-edi-parse-") as scratch_dir:
            scratch = Path(scratch_dir) / p.name
            scratch.write_bytes(fixed)
            try:
                tf = _read_once(scratch)
            except Exception:  # noqa: BLE001
                raise exc from None      # report the ORIGINAL failure, never the retry's
        # mt_metadata records the path it read in TF.fn. Point it back at the custodian's file: a TF
        # carrying the (now deleted) scratch path would hand any downstream consumer a location
        # outside the citable record. NOT guarded -- a failure to scrub is a leak and must be loud.
        tf.fn = p
        return tf, INFO_JSON_DELIMITER_DEFECT


def _read(path: Path):
    return _read_with_fallback(path)[0]


def read(path: Path):
    """Public single parse of an EDI/MTH5 into a TF object, so callers can parse ONCE and reuse
    it across record_from_tf / components_from_tf / proc_info_from_tf (instead of re-reading the
    file three times)."""
    return _read(path)


def read_with_fallback(path: Path):
    """`read`, plus the reason string when the >INFO delimiter fallback fired (None when it did not),
    so the build can RECORD per station that a file needed it. Silent repair is not acceptable."""
    return _read_with_fallback(path)


def classify(pmin, has_z, has_t):
    """Period-band classifier: AMT (<1e-3 s) / BBMT (<1 s) / LPMT, or GDS for tipper-only."""
    if has_t and not has_z:
        return "GDS"
    if pmin is None:
        return "unknown"
    if pmin < 1e-3:
        return "AMT"
    if pmin < 1.0:
        return "BBMT"
    return "LPMT"


def explicit_sample_rates_from_tf(tf) -> list:
    """The station's EXPLICIT acquisition sample rates in Hz, read off the parsed run metadata
    (tf.station_metadata.runs - populated from MTH5 run tables, EMTF-XML field-notes runs, or any
    EDI dialect the pinned mt_metadata actually parses a run rate from). MTCAT 2.0 rule: a rate is
    explicit ONLY when a run declares it > 0; mt_metadata's Run.sample_rate default is 0.0
    (undeclared) and is never emitted, and nothing here reads instrument models or period coverage
    (never inferred - the ratified sample_rates_hz source rule). Returns a sorted deduped list of
    floats; [] when no run declares a rate, which the record builder maps to NO key at all."""
    rates = set()
    for run in (getattr(getattr(tf, "station_metadata", None), "runs", None) or []):
        sr = getattr(run, "sample_rate", None)
        try:
            sr = float(sr) if sr is not None else None
        except (TypeError, ValueError):
            sr = None
        if sr is not None and sr > 0:
            rates.add(sr)
    return sorted(rates)


def record_from_tf(tf, file_label: str, *, extractor: str = "mt_metadata") -> dict:
    """Per-station catalogue record (the canonical key set the build pipeline consumes) from a parsed
    TF object — reusable whether the TF came from an EDI or from an MTH5 file."""
    per = tf.period
    has_z = bool(tf.has_impedance())
    has_t = bool(tf.has_tipper())
    pmin = float(per.min()) if per is not None and per.size else None
    pmax = float(per.max()) if per is not None and per.size else None
    comps = []
    if has_z:
        comps.append("Z")
    if has_t:
        comps.append("T")
    lat = tf.latitude
    lon = tf.longitude
    record = {
        "id": tf.station or Path(file_label).stem,
        "file": file_label,
        "lat": round(lat, 6) if lat is not None else None,
        "lon": round(lon, 6) if lon is not None else None,
        "elev_m": float(tf.elevation) if getattr(tf, "elevation", None) not in (None, 0) else None,
        "n_periods": int(per.size) if per is not None else 0,
        "period_min_s": round(pmin, 6) if pmin is not None else None,
        "period_max_s": round(pmax, 6) if pmax is not None else None,
        "components": comps,
        "type": classify(pmin, has_z, has_t),
        "coord_flag": None,
        "extractor": extractor,
    }
    # MTCAT 2.0 sample_rates_hz: the key exists ONLY when a run declares an explicit rate (absent to
    # absent, so an EDI corpus with no parsed run rates keeps byte-identical records everywhere the
    # record is serialised - the default-stability discipline).
    rates = explicit_sample_rates_from_tf(tf)
    if rates:
        record["sample_rates_hz"] = rates
    return record


def parse_edi(path: Path) -> dict:
    """Per-station catalogue record from an EDI, via mt_metadata.

    Coordinates come from the parsed station metadata (mt_metadata reads HEAD LAT/LONG, the
    authoritative field). The DMS sign-bug detection and the processing-note scrape are applied
    separately in build_portal.process_edis (via the kept `_edi_catalog` helpers), not here.
    """
    return record_from_tf(_read(path), path.name)


# mt_metadata / EMTF XML use a large sentinel (~1e32) for MISSING data. Treat any non-physical
# magnitude as missing so a fill never leaks into rho/phase/tipper products — a 1e32 tipper fill
# would otherwise plot as a garbage tip_mag. Real MT impedances/tippers are far below this. (Only
# triggers on EMTF-XML-sourced TFs; an EDI read straight to components carries no values this large.)
_FILL_MAX = 1e8

# C20 placeholder-tipper detection. Some EDIs carry an UNPHYSICAL placeholder tipper — observed as
# |T| identically 1.0 at every period, with one component ~1e-17 (a filler, not an estimate). These
# named constants (siblings of _FILL_MAX; in the spirit of the _edi_science science constants) define
# the detector: a tipper is a placeholder when it has at least PLACEHOLDER_TIPPER_MIN_PERIODS present
# periods AND is FLAT (max|T|-min|T| < PLACEHOLDER_TIPPER_FLAT_TOL) AND sits AT UNITY
# (||T|-1| < PLACEHOLDER_TIPPER_UNITY_TOL) at every present period. A real tipper (|T| varies, or is
# far from 1) never satisfies all three, so it is untouched.
PLACEHOLDER_TIPPER_MIN_PERIODS = 4
PLACEHOLDER_TIPPER_FLAT_TOL = 1e-6      # max|T| - min|T| below this => FLAT
PLACEHOLDER_TIPPER_UNITY_TOL = 1e-3     # ||T| - 1.0| below this at every period => AT UNITY


def _is_placeholder_tipper(txr, txi, tyr, tyi) -> bool:
    """True iff the four masked tipper component series describe an unphysical placeholder tipper
    (C20): |T| flat AND pinned at 1.0 across at least PLACEHOLDER_TIPPER_MIN_PERIODS present periods.
    Present = all four components non-None at that period (the same joint-presence the tip magnitude
    needs). Returns False for any real (varying, or off-unity) tipper, and for a tipper with too few
    present periods to judge."""
    mags = []
    n = max((len(s) for s in (txr, txi, tyr, tyi) if s), default=0)
    for i in range(n):
        vals = [s[i] if s and i < len(s) else None for s in (txr, txi, tyr, tyi)]
        if all(v is not None for v in vals):
            mags.append(math.sqrt(sum(v * v for v in vals)))
    if len(mags) < PLACEHOLDER_TIPPER_MIN_PERIODS:
        return False
    if (max(mags) - min(mags)) >= PLACEHOLDER_TIPPER_FLAT_TOL:
        return False
    return all(abs(m - 1.0) < PLACEHOLDER_TIPPER_UNITY_TOL for m in mags)


def _is_missing(zi) -> bool:
    """True if a complex Z/T element is absent, NaN, a non-physical missing-data fill (~1e32), or
    EXACT complex zero. The exact-zero arm is C19b (TAS120 incident, 2026-07-07): mt_metadata
    converts an EDI's 1e32 fills to exact zeros on read, which passed the magnitude threshold and
    plotted as phase=0deg / rho=0 / tipper-dip data points at every source-masked period. A real
    estimated Z/T element is never exactly 0+0j to double precision; a SINGLE zero component
    (e.g. tipper imag crossing 0.0 while real is finite) remains valid data."""
    if zi is None:
        return True
    if isinstance(zi, complex):
        return (math.isnan(zi.real) or math.isnan(zi.imag)
                or abs(zi.real) > _FILL_MAX or abs(zi.imag) > _FILL_MAX
                or (zi.real == 0.0 and zi.imag == 0.0))
    return False


def _z(Z, out, inp):
    """Return the complex array for impedance element (output, input), or None."""
    try:
        return Z.sel(output=out, input=inp).values
    except Exception:  # noqa: BLE001
        return None


def components_from_tf(tf):
    """(periods, canonical component dict) from a parsed TF object — same layout the regex path
    emits, reusable whether the TF came from an EDI or an MTH5 file. ρ/φ from Z, ρ- AND φ-errors
    propagated from impedance_error (linear |dZ| propagation), tipper from Tx/Ty."""
    per = tf.period
    if per is None or not per.size:
        return None, None
    periods = [float(p) for p in per]
    n = len(periods)
    comp = {k: [None] * n for k in (
        "RHOXY", "RHOYX", "PHSXY", "PHSYX", "RHOXY.ERR", "RHOYX.ERR",
        "PHSXY.ERR", "PHSYX.ERR",
        "ZXXR", "ZXXI", "ZXYR", "ZXYI", "ZYXR", "ZYXI", "ZYYR", "ZYYI",
        "TXR", "TXI", "TYR", "TYI")}

    if tf.has_impedance():
        Z = tf.impedance
        Ze = tf.impedance_error if tf.impedance_error is not None else None
        pairs = {"XX": ("ex", "hx"), "XY": ("ex", "hy"), "YX": ("ey", "hx"), "YY": ("ey", "hy")}
        arr = {k: _z(Z, o, i) for k, (o, i) in pairs.items()}
        earr = {k: (_z(Ze, o, i) if Ze is not None else None) for k, (o, i) in pairs.items()}
        for i, T in enumerate(periods):
            for k in ("XX", "XY", "YX", "YY"):
                z = arr[k]
                if z is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                comp["Z" + k + "R"][i] = float(zi.real)
                comp["Z" + k + "I"][i] = float(zi.imag)
            for mode, k in (("XY", "XY"), ("YX", "YX")):
                z = arr[k]
                if z is None or z[i] is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                mag2 = zi.real ** 2 + zi.imag ** 2
                comp["RHO" + mode][i] = 0.2 * T * mag2
                comp["PHS" + mode][i] = math.degrees(math.atan2(zi.imag, zi.real))
                e = earr[k]
                if e is not None and e[i] is not None and not (isinstance(e[i], float) and math.isnan(e[i])):
                    # Standard small-error LINEAR propagation from the impedance error |dZ| (C20):
                    #   rho = 0.2*T*|Z|^2   -> drho  = 0.4*T*|Z|*|dZ|
                    #   phi = atan2(Im,Re)  -> dphi  = degrees(|dZ|/|Z|)
                    # |dZ| is the (real, non-negative) impedance-error magnitude mt_metadata carries
                    # per component. Both errors come from the ONE |dZ| here so rho- and phase-error
                    # cannot diverge; documented in data-files.md.
                    dz = float(abs(e[i]))
                    mag = math.sqrt(mag2)
                    comp["RHO" + mode + ".ERR"][i] = 0.4 * T * mag * dz
                    if mag > 0:
                        comp["PHS" + mode + ".ERR"][i] = math.degrees(dz / mag)

    if tf.has_tipper():
        Tp = tf.tipper
        tpairs = {"TX": ("hz", "hx"), "TY": ("hz", "hy")}
        tarr = {k: _z(Tp, o, i) for k, (o, i) in tpairs.items()}
        for i in range(n):
            for k in ("TX", "TY"):
                z = tarr[k]
                if z is None or z[i] is None:
                    continue
                zi = z[i]
                if _is_missing(zi):
                    continue
                comp[k + "R"][i] = float(zi.real)
                comp[k + "I"][i] = float(zi.imag)

        # C20 placeholder-tipper honesty: an unphysical filler tipper (|T| flat at 1.0) is masked
        # WHOLESALE — all four component series to null — so neither the tip magnitude nor the C20
        # tzx/tzy columns paint it as data. Composes with the per-element fill/zero masking above
        # (the detector reads the already-masked series). A build NOTICE names the station.
        if _is_placeholder_tipper(comp["TXR"], comp["TXI"], comp["TYR"], comp["TYI"]):
            for k in ("TXR", "TXI", "TYR", "TYI"):
                comp[k] = [None] * n
            _station = getattr(tf, "station", None) or "?"
            print(f"  NOTICE {_station}: placeholder tipper (|T| flat at 1.0) masked — tipper withheld",
                  file=sys.stderr)

    comp = {k: (v if any(x is not None for x in v) else None) for k, v in comp.items()}
    return periods, comp


def components(path: Path):
    """(periods, canonical component dict) via mt_metadata from an EDI path."""
    return components_from_tf(_read(path))


def proc_info_from_tf(tf, with_writer=False):
    """(software, algorithm, remote_reference[, file_written_by]) from an already-parsed TF object.

    LINEAGE (2026-08-14): `software` is the program that PROCESSED the transfer function, which is
    NOT the same fact as mt_metadata's `transfer_function.software`. That field is populated from
    the source file's own program stamp (an EDI HEAD's PROGNAME/PROGVERS), i.e. from whatever WROTE
    the file — for most of the corpus a database/plotting exporter that estimated nothing (see
    _edi_catalog.KNOWN_WRITERS). So a known writer is NOT returned as the processor; it is returned
    separately as `file_written_by`. A software name that is NOT a known writer is a program that
    plausibly did the processing (an EDI written directly by LEMIMT), and stands as `software`.

    `with_writer=True` appends file_written_by = {"name", "version"} — mt_metadata's software block
    VERBATIM, None where the field is empty (which it is for most EDI dialects; the build layer
    supplements it from the HEAD via _edi_catalog.writer_from_text). The default 3-tuple keeps the
    signature every existing caller unpacks (the `proc` argument of
    _edi_science.science_from_components) unchanged.

    The writer vocabulary is imported HERE, not at module scope. `_mtm` is reached BOTH ways in
    this tree: by bare name (build_portal, which puts extract/ on sys.path) and as `extract._mtm`
    (ausmt_science.ingest.normalize, by package path with engine/ as the root, for read_with_fallback
    alone). A module-level `import _edi_catalog` resolves under the first and raises under the
    second — measured — which would break normalize for a caller that only wants the reader. Inside
    the try it also fails SAFE: no vocabulary means no software claim, never a wrong one."""
    try:
        import _edi_catalog as cat  # noqa: PLC0415  (see the docstring: import shape, not laziness)
        tfm = tf.station_metadata.transfer_function
        swobj = getattr(tfm, "software", None)
        name = (getattr(swobj, "name", None) or "").strip() or None
        version = (getattr(swobj, "version", None) or "").strip() or None
        rr = 1 if (tfm.processing_type and "remote" in str(tfm.processing_type).lower()) else 0
        alg = str(tfm.processing_type) if tfm.processing_type else None
        sw = None if (name is None or cat.is_known_writer(name)) else name
        out = (sw, alg, rr)
        return out + ({"name": name, "version": version},) if with_writer else out
    except Exception:  # noqa: BLE001
        return (None, None, 0, {"name": None, "version": None}) if with_writer else (None, None, 0)


def proc_info(path: Path, with_writer=False):
    """(software, algorithm, remote_reference[, file_written_by]) from mt_metadata where present."""
    try:
        return proc_info_from_tf(_read(path), with_writer=with_writer)
    except Exception:  # noqa: BLE001
        return (None, None, 0, {"name": None, "version": None}) if with_writer else (None, None, 0)
