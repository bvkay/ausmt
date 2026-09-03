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


PLAIN_TIPPER_LABELS = (
    "plain TXR/TXI/TYR/TYI tipper labels (mt_metadata reads only the .EXP-suffixed forms)"
)

# The tipper block labels mt_metadata accepts are ONLY the .EXP-suffixed forms
# (_t_labels: txr.exp/txi.exp/txvar.exp, tyr.exp/tyi.exp/tyvar.exp). The Capricorn 2010
# long-period EDIs label the same blocks plainly (>TXR, >TX.VAR ...), so the reader discards a
# real 24-period tipper wholesale. Upstream issue material; until fixed, the parse-side
# normalisation below maps each plain label to its accepted spelling.
_PLAIN_TIPPER_MAP = {
    b">TXR": b">TXR.EXP", b">TXI": b">TXI.EXP", b">TX.VAR": b">TXVAR.EXP",
    b">TYR": b">TYR.EXP", b">TYI": b">TYI.EXP", b">TY.VAR": b">TYVAR.EXP",
}


def normalise_plain_tipper_labels(raw: bytes) -> bytes:
    """Return `raw` with plain tipper DATA-BLOCK labels rewritten to the .EXP-suffixed spellings
    mt_metadata accepts, and every other byte exactly as it was. Only a line-leading label token
    followed by whitespace or a comment is rewritten (an already-suffixed >TXR.EXP is left alone),
    so the change set is exactly the six block headers. Returns the ORIGINAL object when nothing
    changes, which is what lets the caller refuse to retry a file that does not carry the shape."""
    out: list[bytes] = []
    changed = False
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        stripped = body.lstrip()
        replaced = None
        for plain, exp in _PLAIN_TIPPER_MAP.items():
            if stripped.upper().startswith(plain) and not stripped[len(plain):len(plain) + 1] == b".":
                tail = stripped[len(plain):]
                if tail[:1] in (b"", b" ", b"\t", b"/"):
                    prefix = body[:len(body) - len(stripped)]
                    replaced = prefix + exp + tail + line[len(body):]
                    break
        if replaced is not None:
            changed = True
            out.append(replaced)
        else:
            out.append(line)
    return b"".join(out) if changed else raw


def _recover_plain_tipper(p: Path, tf):
    """(TF, reason_or_None): the second normalised-temporary-copy fallback, for a file that PARSES
    but whose tipper the reader silently discarded. Narrow by construction: .edi only; only when
    the parsed TF carries no tipper; only when the label normalisation actually changes the bytes;
    and if the retry fails or still carries no tipper, the ORIGINAL parse stands untouched (a
    recovery must never cost a station its impedance). The served bytes are the custodian's file
    either way - only the parse-side TEMPORARY copy is conditioned (the >INFO delimiter
    precedent), and the fallback is RECORDED per station, never silent."""
    try:
        if p.suffix.lower() != ".edi" or tf.has_tipper():
            return tf, None
    except Exception:  # noqa: BLE001
        return tf, None
    raw = p.read_bytes()
    fixed = normalise_plain_tipper_labels(raw)
    if fixed is raw:
        return tf, None
    with tempfile.TemporaryDirectory(prefix="ausmt-edi-tipper-") as scratch_dir:
        scratch = Path(scratch_dir) / p.name
        scratch.write_bytes(fixed)
        try:
            tf2 = _read_once(scratch)
        except Exception:  # noqa: BLE001
            return tf, None
    if not tf2.has_tipper():
        return tf, None
    tf2.fn = p        # scrub the scratch path exactly as the delimiter fallback does
    return tf2, PLAIN_TIPPER_LABELS


Z_BLOCK_LENGTH_MISMATCH = (
    "the >Z impedance data blocks carry fewer values than the section's declared NFREQ, so "
    "mt_metadata could not build the impedance tensor and the whole file failed to read; reparsed "
    "from a temporary copy with the impedance blocks removed, so everything else the file carries "
    "(coordinates, periods, tipper) survives (the source file is untouched and is what is served)"
)

# The impedance DATA-block labels mt_metadata reads, verbatim from edi.EDI._z_labels: the four
# tensor elements x (real, imaginary, variance). `>ZROT` is a rotation-angle block, not impedance
# data, and is deliberately absent -- the vocabulary is the reader's own, not a `>Z` prefix sweep.
_Z_DATA_LABELS = (b">ZXXR", b">ZXXI", b">ZXX.VAR", b">ZXYR", b">ZXYI", b">ZXY.VAR",
                  b">ZYXR", b">ZYXI", b">ZYX.VAR", b">ZYYR", b">ZYYI", b">ZYY.VAR")

# The observable signature: numpy's broadcast refusal, raised where _read_mt fills the impedance
# tensor from the parsed data dict (edi.py:414 in the pinned reader). Deliberately narrow -- an
# unrelated read failure raises a different error, and a file whose impedance blocks are the right
# length never reaches here at all because it parses.
_Z_BLOCK_MISMATCH_RE = re.compile(
    r"could not broadcast input array from shape \(\d+,?\) into shape \(\d+,?\)")


def _is_z_block_length_defect(exc: BaseException) -> bool:
    """True only for the impedance-block length defect above: numpy's broadcast refusal raised
    inside mt_metadata's own `_read_mt`. Both halves are required -- the message alone could come
    from anywhere in the stack, and the frame alone would also catch the tipper fill, which this
    normalisation does not touch and must never be asked to rescue."""
    if not isinstance(exc, ValueError) or not _Z_BLOCK_MISMATCH_RE.search(str(exc)):
        return False
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_name == "_read_mt":
            return True
        tb = tb.tb_next
    return False


def _is_z_data_label(stripped: bytes) -> bool:
    """True when a section line opens one of the twelve impedance data blocks. The label must be
    followed by whitespace, a comment or the line end, so a longer label that merely starts with one
    of these tokens is not matched."""
    upper = stripped.upper()
    for label in _Z_DATA_LABELS:
        if upper.startswith(label) and upper[len(label):len(label) + 1] in (b"", b" ", b"\t", b"/"):
            return True
    return False


def strip_impedance_blocks(raw: bytes) -> bytes:
    """Return `raw` with the twelve >Z impedance DATA blocks (each label line and the value lines
    that follow it, up to the next section) removed, and every other byte exactly as it was.

    Operates on BYTES and never re-encodes. A block ends where mt_metadata's own section scan ends
    it -- at the next line whose stripped form starts with `>` -- so the region removed is exactly
    the region the reader would have read. Section banners (`>!****IMPEDANCES****!`) start with `>`
    and are kept: they label nothing once the blocks are gone, but leaving them keeps the change set
    to the blocks themselves. Returns the ORIGINAL object when there is nothing to remove, which is
    what lets the caller refuse to retry a file that does not actually carry the shape."""
    out: list[bytes] = []
    dropping = False
    changed = False
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(b">"):
            dropping = _is_z_data_label(stripped)
            if dropping:
                changed = True
                continue
            out.append(line)
            continue
        if dropping:
            continue
        out.append(line)
    return b"".join(out) if changed else raw


SINGLE_PERIOD_ORDERING_DEFECT = (
    "mt_metadata's descending-frequency assertion indexes the SECOND frequency unconditionally, so "
    "an EDI declaring a single period raises IndexError before the transfer function is built; "
    "reparsed with that assertion neutralised for this one read (a lone frequency is already "
    "ordered, so nothing is reordered and no multi-period file's ordering can change)"
)

# The third guard for the single-period defect, the counterpart of "normalisation changes bytes":
# the file must actually DECLARE one frequency. `NFREQ= 10` and `NFREQ=  30` do not match (the word
# boundary after the 1 fails), so only a genuine single-frequency section reaches the retry.
_NFREQ_ONE_RE = re.compile(rb"NFREQ\s*=\s*0*1\b", re.IGNORECASE)


def _is_single_period_defect(exc: BaseException) -> bool:
    """True only for mt_metadata's single-period ordering defect: an IndexError raised INSIDE
    `edi.EDI._assert_descending_frequency`. Identified by the raising FRAME rather than by the
    message, because the message is numpy's own ('index 1 is out of bounds ...') and names nothing
    specific to this defect; the frame is what makes the trigger unambiguous."""
    if not isinstance(exc, IndexError):
        return False
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_name == "_assert_descending_frequency":
            return True
        tb = tb.tb_next
    return False


# ---------------------------------------------------------------------------------------------
# THE EPI-KIT SECTION OF RECORD.
#
# An EPI-KIT file records its solution twice over: one `>=MTSECT` block carries the averaged
# solution, named <DATAID>_avg, and after it come the per-frequency realisations the processor's own
# "EstimationsPerFrequency" setting produced, named XPR-0 .. XPR-n. The averaged block is the
# transfer function of record; the realisations are its inputs, and the late ones hold little but the
# EMPTY sentinel.
#
# mt_metadata reads a multi-section file by scanning EVERY data block in it and REBINDING
# data_dict[key] at each block header (io/edi/edi.py::_read_mt), so the parse silently returns the
# LAST section in the file. Measured over the three GSSA EPI-KIT packages, 932 files, 2026-09-03:
# the reader returned the averaged block 0 times of 75 sampled and the last realisation 75 times; on
# copper-coast-2020 that is 440 of the 3847 impedance values the averaged blocks hold, and four
# stations publishing no resistivity at all.
#
# THE SELECTION RULE: <DATAID>_avg, else the section named for the DATAID, else the FIRST section.
# The last clause is the honest default for a file whose sections name no solution of record -- the
# first section is where a writer puts the answer -- and it is never "whichever one the parser
# happened to finish on".
#
# Applied ON A TEMPORARY COPY, exactly like the >INFO delimiter repair: the copy keeps the head, the
# info block, the measurement definitions and the chosen section alone. D1 stands: the served bytes
# are the custodian's file.
SECTION_OF_RECORD_RULE = "<DATAID>_avg, else the section named for the DATAID, else the first"

_SECTID_RE = re.compile(rb"^\s*SECTID\s*=\s*(.*?)\s*$", re.IGNORECASE)
_DATAID_RE = re.compile(rb"^\s*DATAID\s*=\s*(.*?)\s*$", re.IGNORECASE)


def _unquote(value: bytes) -> str:
    """The value as mt_metadata sees it: io/tools.py::_validate_edi_lines strips `"` and `'` from
    every line before any section parser runs, so quoting is not part of any identifier."""
    return value.replace(b'"', b"").replace(b"'", b"").strip().decode("utf-8", "replace")


def _is_section_header(stripped: bytes) -> bool:
    """True for a line that OPENS an EDI data section. mt_metadata's own test (data_section.py::
    get_data) is `">=" in line and "sect" in line.lower()`, which also matches a line carrying that
    pair anywhere -- an >INFO note, for instance. This requires the `>=` to LEAD the stripped line,
    which every real section header does. The two only disagree on a file whose prose fools the
    reader, and there this test finds FEWER sections, so the conditioning below stands down and the
    file reads exactly as it does today."""
    return stripped.startswith(b">=") and b"sect" in stripped.lower()


def _head_dataid(lines: list[bytes]) -> str | None:
    """The DATAID written in the >HEAD block, or None. Block bounds mirror header.py::
    get_header_list (start: a line containing ">" and "head"; end: the next line starting with ">"),
    so a DATAID-shaped line anywhere else in the file is not mistaken for the header's."""
    in_head = False
    for line in lines:
        stripped = line.strip()
        if not in_head:
            if stripped.startswith(b">") and b"head" in stripped.lower():
                in_head = True
            continue
        if stripped.startswith(b">"):
            return None
        m = _DATAID_RE.match(stripped)
        if m:
            return _unquote(m.group(1))
    return None


def _sections(lines: list[bytes]) -> list[tuple]:
    """Every data section as (sectid_or_None, start_line, stop_line). A section runs from its header
    to the next section header, or to the `>END` marker, or to the end of the file."""
    starts = [i for i, ln in enumerate(lines) if _is_section_header(ln.strip())]
    end = next((i for i, ln in enumerate(lines) if ln.strip().upper().startswith(b">END")),
               len(lines))
    out = []
    for n, start in enumerate(starts):
        stop = starts[n + 1] if n + 1 < len(starts) else (end if end > start else len(lines))
        sectid = None
        for ln in lines[start:stop]:
            m = _SECTID_RE.match(ln.strip())
            if m:
                sectid = _unquote(m.group(1))
                break
        out.append((sectid, start, stop))
    return out


def section_of_record(raw: bytes) -> tuple:
    """(sectid, index, total) for `raw` under SECTION_OF_RECORD_RULE. `total` is how many data
    sections the file carries, so a caller can tell "one section, nothing to choose" from "chose the
    first of several". (None, -1, 0) for a file with no data section at all."""
    lines = raw.splitlines(keepends=True)
    sections = _sections(lines)
    if not sections:
        return (None, -1, 0)
    dataid = _head_dataid(lines)
    if dataid:
        wanted = dataid.strip().lower()
        for preferred in (wanted + "_avg", wanted):
            for i, (sectid, _a, _b) in enumerate(sections):
                if sectid is not None and sectid.strip().lower() == preferred:
                    return (sectid, i, len(sections))
    return (sections[0][0], 0, len(sections))


def keep_single_section(raw: bytes, sectid) -> bytes:
    """Return `raw` carrying the section named `sectid` and no other, every other byte exactly as it
    was: the head, the info block and the measurement definitions ahead of the first section are
    kept, the other sections' metadata and data blocks are dropped, and the `>END` marker and
    anything after it are kept. Operates on BYTES and never re-encodes.

    Returns the ORIGINAL object when there is nothing to drop (one section, or a name this file does
    not carry), which is what lets the caller refuse to condition a file that does not need it."""
    lines = raw.splitlines(keepends=True)
    sections = _sections(lines)
    if len(sections) < 2:
        return raw
    chosen = next(((a, b) for sid, a, b in sections if sid == sectid), None)
    if chosen is None:
        return raw
    end = next((i for i, ln in enumerate(lines) if ln.strip().upper().startswith(b">END")),
               len(lines))
    tail = lines[end:] if end >= sections[-1][1] else []
    return b"".join(lines[:sections[0][1]] + lines[chosen[0]:chosen[1]] + tail)


def _freq_count(raw: bytes, sectid) -> int | None:
    """How many values the named section's `>FREQ` block carries, counted from the bytes. None when
    the section carries no such block."""
    lines = raw.splitlines(keepends=True)
    for sid, a, b in _sections(lines):
        if sid != sectid:
            continue
        values, reading = 0, False
        for line in lines[a:b]:
            stripped = line.strip()
            if stripped.startswith(b">"):
                reading = stripped.upper().startswith(b">FREQ")
                continue
            if reading:
                values += len(stripped.split())
        return values if values else None
    return None


def _assert_section_of_record(p: Path, conditioned: bytes, sectid: str, tf) -> None:
    """The build-time assertion the refuter asked for: when a file carried more than one section, the
    parse must have come from the one the rule names, or the station is dropped LOUDLY (the caller
    records the raise in build_report's source_parse_failures and stations_dropped, and the deploy
    gate refuses the build). Two independent observables over the conditioned bytes: exactly one
    section survives and it is the named one, and the parsed frequency count is that section's own.

    BOUNDARY, stated: the frequency count cannot tell two sections of equal length apart, which every
    EPI-KIT realisation is. It catches a copy that lost or merged blocks, not a mis-selection; the
    NAME check is what proves the selection, and the per-value proof against a section's own ZXYR
    block lives in the test suite and in the lane's build evidence, not in every build of every
    file."""
    sections = _sections(conditioned.splitlines(keepends=True))
    if len(sections) != 1 or sections[0][0] != sectid:
        raise ValueError(
            f"section-of-record conditioning did not isolate {sectid!r} in {p.name}: the copy carries "
            f"{[s[0] for s in sections]} (rule: {SECTION_OF_RECORD_RULE})")
    want = _freq_count(conditioned, sectid)
    got = int(tf.period.size) if getattr(tf, "period", None) is not None else 0
    if want is not None and want != got:
        raise ValueError(
            f"section-of-record parse of {p.name} returned {got} frequencies where section "
            f"{sectid!r} declares {want}: the parse did not come from the section it was given")


def _pre_read_conditioning(p: Path, raw: bytes):
    """(conditioned_bytes, facts, reasons) for the EPI-KIT section of record, read off the FILE.

    It is conditioned BEFORE the read, not after a failure, because it never announces itself as
    one: a multi-section file parses happily and returns the wrong transfer function. The condition
    is measured with the reader's own section scan instead, which is as narrow as the signature
    predicates its siblings use.

    Narrow in the same four ways as every other conditioning here: `.edi` only (the caller's guard);
    only when the measured condition holds; only when the conditioning actually CHANGES the bytes;
    and, unlike the failure-triggered fallbacks, a conditioned read that fails is NOT quietly
    replaced by the unconditioned one -- publishing the wrong section silently is the defect, so the
    station is dropped loudly instead."""
    facts: dict = {}
    reasons: list = []
    conditioned = raw
    sectid, _index, total = section_of_record(conditioned)
    if total > 1 and sectid is not None:
        kept = keep_single_section(conditioned, sectid)
        if kept is not conditioned:
            conditioned = kept
            facts["section_selected"] = {"sectid": sectid, "sections_dropped": total - 1}
    return conditioned, facts, reasons


def _read_once(path: Path):
    tf = TF()
    tf.read(str(path))
    return tf


def _reparse_from_normalised_copy(p: Path, exc: BaseException, fixed: bytes, reason: str):
    """(TF, reason): the shared body of every byte-normalising fallback. `fixed` is the conditioned
    bytes the caller's normaliser produced; the caller has already checked that they differ from the
    source. The copy lives in a TemporaryDirectory destroyed before this returns, is never returned
    to a caller and never reaches the served tree or the sha256 integrity gate (both of which take
    the ORIGINAL path). If the retry fails, the ORIGINAL exception is re-raised, so a file broken
    for any other reason still fails exactly as it does today, with its own error."""
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
    tf, _treason = _recover_plain_tipper(p, tf)
    return tf, (reason + " + " + _treason) if _treason else reason


def _reparse_without_frequency_ordering(p: Path, exc: BaseException):
    """(TF, reason): the single-period fallback. Unlike its two siblings this one conditions the
    READER, not a copy of the bytes, because no byte of a one-period EDI is wrong -- the file is
    correct and the assertion that reads it is not. The neutralisation is therefore the narrowest
    possible statement of that: `_assert_descending_frequency` is wrapped so that it delegates to
    the shipped implementation for every frequency array longer than one and returns without
    touching anything for a lone frequency, which is already ordered. It is installed for THIS read
    and removed in a finally, and it is reached only after a normal read has already failed with the
    defect's own frame in its traceback, so no file that parses today can take this path.

    CONSTRAINT, stated because a class attribute is process-wide while installed: the EDI parse loop
    is serial in-process (the build's only pool spawns separate processes for MTH5 bundles), so no
    concurrent read can observe the wrapper. A threaded parser would need this narrowed further."""
    try:
        from mt_metadata.transfer_functions.io.edi.edi import EDI  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        raise exc from None
    shipped = getattr(EDI, "_assert_descending_frequency", None)
    if shipped is None:      # the reader no longer carries the method: nothing to neutralise
        raise exc from None

    def _order_only_when_there_is_an_order(self):
        freq = getattr(self, "frequency", None)
        if freq is not None and getattr(freq, "size", 0) > 1:
            return shipped(self)
        return None

    EDI._assert_descending_frequency = _order_only_when_there_is_an_order
    try:
        tf = _read_once(p)
    except Exception:  # noqa: BLE001
        raise exc from None      # report the ORIGINAL failure, never the retry's
    finally:
        EDI._assert_descending_frequency = shipped
    tf, _treason = _recover_plain_tipper(p, tf)
    return tf, (SINGLE_PERIOD_ORDERING_DEFECT + " + " + _treason) if _treason \
        else SINGLE_PERIOD_ORDERING_DEFECT


def _read_with_fallback(path: Path):
    """(TF, fallback_reason_or_None). Normal read first; on a failure ATTRIBUTABLE TO one of the
    three recognised reader defects, retry ONCE for that defect alone, then return the parse.

    Narrow by construction, in four independent ways, so no unrelated failure is ever swallowed:
      * only for `.edi` inputs (every one of these is an EDI construct);
      * only when the raised error carries that defect's signature (the three predicates below);
      * only when the conditioning actually CHANGES something -- the bytes for the two normalising
        fallbacks, and for the single-period one a file that really declares NFREQ=1;
      * and if the retry itself fails, the ORIGINAL exception is re-raised, so a file broken for any
        other reason still fails exactly as it does today, with its own error.

    The three are mutually exclusive by error type and raising frame (a pydantic scalar-parsing
    failure, numpy's broadcast refusal inside _read_mt, an IndexError inside the ordering
    assertion), so the order they are tried in cannot change any outcome.
    """
    p = Path(path)
    try:
        return _recover_plain_tipper(p, _read_once(p))
    except Exception as exc:  # noqa: BLE001  (re-raised unless it is precisely one of these defects)
        if p.suffix.lower() != ".edi":
            raise
        if _is_info_delimiter_defect(exc):
            raw = p.read_bytes()
            fixed = normalise_info_json_delimiters(raw)
            if fixed == raw:
                raise
            return _reparse_from_normalised_copy(p, exc, fixed, INFO_JSON_DELIMITER_DEFECT)
        if _is_z_block_length_defect(exc):
            raw = p.read_bytes()
            fixed = strip_impedance_blocks(raw)
            if fixed == raw:
                raise
            return _reparse_from_normalised_copy(p, exc, fixed, Z_BLOCK_LENGTH_MISMATCH)
        if _is_single_period_defect(exc):
            if not _NFREQ_ONE_RE.search(p.read_bytes()):
                raise
            return _reparse_without_frequency_ordering(p, exc)
        raise


def _read_with_parse_facts(path: Path):
    """(TF, fallback_reason_or_None, facts). `_read_with_fallback` preceded by the EPI-KIT
    conditioning that has to happen BEFORE the reader sees the file (see `_pre_read_conditioning`).

    `facts` is what the build records per station: `section_selected` when the file carried more than
    one data section. An absent key means absent conditioning, so every file in a corpus of ordinary
    EDIs yields `{}` and takes the untouched path below, byte for byte as before.

    The reason string stays what it has always meant -- what stopped mt_metadata reading the file at
    all -- so a section selection does NOT set one: the file read perfectly well, it just answered
    with the wrong one of its solutions. The two are recorded in different ledgers for that reason.
    """
    p = Path(path)
    if p.suffix.lower() != ".edi":
        tf, reason = _read_with_fallback(p)
        return tf, reason, {}
    raw = p.read_bytes()
    conditioned, facts, reasons = _pre_read_conditioning(p, raw)
    if conditioned is raw:
        tf, reason = _read_with_fallback(p)
        return tf, reason, facts
    # The conditioned copy lives in a TemporaryDirectory destroyed before this returns, is never
    # returned to a caller and never reaches the served tree or the sha256 integrity gate (both of
    # which take the ORIGINAL path). The three failure-triggered fallbacks still apply to it, so a
    # file carrying a section stack AND a delimiter defect is still rescued.
    with tempfile.TemporaryDirectory(prefix="ausmt-edi-epikit-") as scratch_dir:
        scratch = Path(scratch_dir) / p.name
        scratch.write_bytes(conditioned)
        tf, reason = _read_with_fallback(scratch)
    if facts.get("section_selected"):
        _assert_section_of_record(p, conditioned, facts["section_selected"]["sectid"], tf)
    # mt_metadata records the path it read in TF.fn. Point it back at the custodian's file, exactly
    # as the delimiter fallback does. NOT guarded -- a failure to scrub is a leak and must be loud.
    tf.fn = p
    if reason:
        reasons.append(reason)
    return tf, (" + ".join(reasons) if reasons else None), facts


def _read(path: Path):
    return _read_with_parse_facts(path)[0]


def read(path: Path):
    """Public single parse of an EDI/MTH5 into a TF object, so callers can parse ONCE and reuse
    it across record_from_tf / components_from_tf / proc_info_from_tf (instead of re-reading the
    file three times)."""
    return _read(path)


def read_with_fallback(path: Path):
    """`read`, plus the reason string when a normalising fallback fired (None when none did), so the
    build can RECORD per station that a file needed one. Silent repair is not acceptable."""
    return _read_with_parse_facts(path)[:2]


def read_with_parse_facts(path: Path):
    """`read_with_fallback`, plus the per-file parse facts the build carries into station.json and
    build_report: which data section the transfer function came from. `{}` for a file that carried
    one section, which is every EDI in the corpus."""
    return _read_with_parse_facts(path)


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


def components_from_tf(tf, notes=None):
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
        # (the detector reads the already-masked series). With a `notes` list the CALLER owns the
        # emission (build_portal records the fact on the parse product so it rides the C18 cache and
        # build_report - a cache hit and a miss emit the same diagnostics); without one, the NOTICE
        # prints here as before.
        if _is_placeholder_tipper(comp["TXR"], comp["TXI"], comp["TYR"], comp["TYI"]):
            for k in ("TXR", "TXI", "TYR", "TYI"):
                comp[k] = [None] * n
            _station = getattr(tf, "station", None) or "?"
            _msg = "placeholder tipper (|T| flat at 1.0) masked - tipper withheld"
            if notes is not None:
                notes.append(_msg)
            else:
                print(f"  NOTICE {_station}: {_msg}", file=sys.stderr)

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
    second - measured - which would break normalize for a caller that only wants the reader. The
    import failure loses ONLY the writer-vocabulary claim (`sw`): alg/rr/name/version are computed
    regardless, so a remote-reference station never publishes rr=0 because a sibling import did not
    resolve. No vocabulary means no software claim, never a wrong one - for `sw` alone."""
    try:
        import _edi_catalog as cat  # noqa: PLC0415  (see the docstring: import shape, not laziness)
    except Exception:  # noqa: BLE001
        cat = None
    try:
        tfm = tf.station_metadata.transfer_function
        swobj = getattr(tfm, "software", None)
        name = (getattr(swobj, "name", None) or "").strip() or None
        version = (getattr(swobj, "version", None) or "").strip() or None
        rr = 1 if (tfm.processing_type and "remote" in str(tfm.processing_type).lower()) else 0
        alg = str(tfm.processing_type) if tfm.processing_type else None
        sw = None if (name is None or cat is None or cat.is_known_writer(name)) else name
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
