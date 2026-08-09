#!/usr/bin/env python3
"""Pre-flight EDI reader check: tell a curator or a submitter what an EDI's >INFO block will do to
its metadata BEFORE a build runs, in words a geophysicist can act on.

WHY THIS EXISTS. The 2026-08 >INFO fallback (see `_mtm.normalise_info_json_delimiters`) made the
engine READ the GSSA Western Gawler 2023 delivery. It did not make the problem VISIBLE. Today the
only way to learn that a delivery's magnetic declination is unreadable, or that 141 of a station's
160 scraped >INFO values will be stored with a stray comma, or that a contact resistance written as
"2.5 kilo-ohms" quietly stores nothing at all, is to read build logs after the fact. This module
answers those questions from the file text alone, fast enough to run over a whole package at upload.

IT IS A REPORTER. It opens files read-only, changes nothing, repairs nothing, and blocks nothing.
Its output is a finding list a human acts on. Nothing here may ever edit an EDI.

HOW IT PREDICTS. mt_metadata's >INFO handling is mirrored here in stdlib Python, from its source, so
the prediction is the same computation the reader performs rather than a guess about it:

  * `io/tools.py::_validate_edi_lines`            -> `sanitise_lines`
  * `io/edi/metadata/information.py::read_info`   -> `_collect_info_block` (block bounds + dialect)
  * `_parse_empower_info` / `_parse_standard_info` / `_parse_phoenix_info` -> `_scrape_*`
  * `io/edi/metadata/define_measurement.py`       -> `_reference_positions`
  * `utils/location_helpers.py::validate_position` -> `_position_is_readable`

MIRRORS ARE GUARDED, NOT TRUSTED. `MIRRORED_MT_METADATA` names the version this was read from, and
`engine/tests/test_edi_preflight.py` runs the real library over the checked-in fixtures and asserts
the mirror still reproduces `Info.info_dict` key for key and value for value. If mt_metadata changes
its scraping, that test goes RED; the pre-flight never silently starts lying.

WHAT THE VERDICT COVERS, AND WHAT IT DOES NOT. `outcome` predicts the two failure surfaces this
module models, both established by measurement over 1736 real EDIs (see the test module):

  1. an >INFO value that reaches a numerically-typed field edi.py sets WITHOUT a try/except, so a
     value pydantic refuses RAISES (`_FATAL_INFO_FIELDS`);
  2. a >=DEFINEMEAS reference position that mt_metadata's own validator refuses, which
     `read_measurement` sets unguarded too.

It is NOT a claim to predict every way mt_metadata can fail. A file reported as reading may still
fail on an unmodelled surface, and the build remains the authority. The asymmetry is deliberate and
is the right one: a MISSED failure costs a build that fails the way it does today, while a FALSE
alarm costs the curator's trust in the whole check, so nothing is reported fatal on speculation.
Every fatal rule below is one an EDI in the measured corpora actually exercises.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# The mt_metadata release this mirror was read from. Pinned in the lock
# (engine/environments/requirements-mtmetadata-lock.txt) and re-asserted by the parity test.
MIRRORED_MT_METADATA = "1.0.9"

# The three verdicts, in worsening order.
READS = "reads"                      # stock mt_metadata reads this file today
NEEDS_REPAIR = "needs_repair"        # stock reader refuses; the AusMT >INFO fallback rescues it
WILL_NOT_READ = "will_not_read"      # no code path in AusMT reads this file; it must be fixed upstream

# Numerically-typed destinations that `io/edi/edi.py::station_metadata` assigns through a BARE
# `sm.update_attribute(...)` -- no try/except around it -- so a value pydantic refuses propagates out
# of the read and the file does not open at all.
#
# MEASURED, not assumed: each key below was injected into a real EDI with a non-numeric value against
# the pinned mt_metadata 1.0.9 and observed to RAISE (2026-08-09). Keys that looked equally dangerous
# and were observed NOT to raise are deliberately absent -- `station.location.declination.model`,
# `transfer_function.software.name`, `station.time_period.start` and `provenance.creation_time` all
# absorb junk quietly, and reporting them fatal would be a false alarm.
#
# `station.location.declination.value` is the one the Western Gawler delivery exercises 246 times
# over, and it is reachable from BOTH >INFO dialects: the Empower branch maps a bare `declination`
# key onto it, and a standard-dialect block can name it in full (the AusMT-enriched
# newer-volcanic-province-2019 EDIs write exactly that key, 49 of them). Each entry carries the
# plain-language field name the report shows a geophysicist.
#
# BOUNDARY, stated rather than hidden: `transfer_function.processed_date` is the one other unguarded
# field an >INFO scrape can reach that raises on junk, but it is a DATE, not a number, and it was
# measured to accept a trailing comma happily ('2023-03-06,' reads fine). Predicting it would mean
# mirroring mt_metadata's date grammar, a far larger and more brittle surface than the delimiter
# class this exists for, and no EDI in either corpus carries the key at all. It is left unmodelled on
# purpose: a missed failure costs a build that fails the way it does today, a false alarm costs trust.
_FATAL_INFO_FIELDS = {
    "station.location.declination.value": "magnetic declination",
    "station.location.latitude": "station latitude",
    "station.location.longitude": "station longitude",
    "station.location.elevation": "station elevation",
    "station.orientation.angle_to_geographic_north": "orientation angle to geographic north",
    "transfer_function.data_quality.rating.value": "data quality rating",
}

# Numerically-typed CHANNEL destinations. `station_metadata` assigns these inside a
# `try: ch.update_attribute(...) except Exception: logger.warning(...)`, so a value pydantic refuses
# is swallowed: no error, no data, the field simply stays empty. This is the class nothing tells a
# curator about today -- a contact resistance recorded as "2.5 kilo-ohms" is silently lost, and the
# published station carries no contact resistance at all.
#
# Keyed by the attribute path AFTER `run.<component>.`, with the words the report uses. Every entry
# was MEASURED against mt_metadata 1.0.9's Electric/Magnetic models (2026-08-09): each one exists,
# each one accepts "12.5", and each one refuses "12 bananas". That matters because the sentence this
# table produces blames the units, so it must only ever be said about a field that is really a number
# and really there. Two plausible-looking names are deliberately ABSENT because the measurement says
# they are not fields at all in 1.0.9 -- `measured_azimuth` (which the Empower key map nevertheless
# targets) and a bare `tilt` -- and a value sent to either is lost for a different reason.
_SILENT_NUMERIC_CHANNEL_FIELDS = {
    "contact_resistance.start": "electrode contact resistance at the start of the run",
    "contact_resistance.end": "electrode contact resistance at the end of the run",
    "dipole_length": "dipole length",
    "measurement_azimuth": "measurement azimuth",
    "measurement_tilt": "measurement tilt",
    "translated_azimuth": "translated azimuth",
    "translated_tilt": "translated tilt",
    "ac.start": "AC voltage at the start of the run",
    "ac.end": "AC voltage at the end of the run",
    "dc.start": "DC voltage at the start of the run",
    "dc.end": "DC voltage at the end of the run",
    "h_field_max.start": "maximum H field at the start of the run",
    "h_field_max.end": "maximum H field at the end of the run",
    "h_field_min.start": "minimum H field at the start of the run",
    "h_field_min.end": "minimum H field at the end of the run",
    "sample_rate": "sample rate",
}

# The exporter tokens that flip mt_metadata's >INFO reader into its Empower branch. Verbatim from
# `read_info`: any block line carrying "empower" AND "v", or the bare words "electrics"/"magnetics",
# routes the WHOLE block through `_parse_empower_info` -- including a JSON block that is not in
# Empower's line-oriented format at all, and including a curator's prose comment. Four EDIs in the
# selected corpus trip it on the phrase "bad electrics" in a note about the site.
_EMPOWER_TOKENS = ("empower", "electrics", "magnetics")

# `mt_metadata.NULL_VALUES`. `read_measurement` skips a reference position carrying any of these
# before it ever reaches the validator, so neither must the prediction flag them.
_NULL_VALUES = (None, "", "null", "None", "NONE", "NULL", "Null", "none",
                "1980-01-01T00:00:00", "1980-01-01T00:00:00+00:00")


def sanitise_lines(raw: bytes) -> list[str]:
    """The line list mt_metadata's section parsers actually see.

    Mirrors `io/tools.py::_validate_edi_lines`, which strips `"`, `'`, `[` and `]` from EVERY line
    before any parser runs. That single step is what makes a JSON >INFO block indistinguishable from
    EDI `key: value` pairs, so every prediction below has to start from the same text the reader
    starts from, not from the bytes on disk."""
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) == 1:
        return (lines[0].replace('"', "").replace("\r", "\n").replace("'", "")
                .replace("[", "").replace("]", "").split("\n"))
    return [ln.replace('"', "").replace("'", "").replace("[", "").replace("]", "")
            for ln in lines]


def _get_separator(line: str) -> str | None:
    """Verbatim mirror of `Information._get_separator`: `:` and `=` both present picks whichever
    comes first, otherwise whichever is present, otherwise None."""
    if line.count(":") > 0 and line.count("=") > 0:
        return ":" if line.find(":") < line.find("=") else "="
    if line.count(":") >= 1:
        return ":"
    if line.count("=") >= 1:
        return "="
    return None


def _collect_info_block(lines: list[str]) -> tuple[list[str], str, str | None]:
    """(block lines, dialect, the exact trigger line) for the >INFO section.

    Mirrors the collection pass of `read_info`. Two details matter and are easy to get wrong:
      * the collected lines are STRIPPED before they are handed to the branch parsers, so
        `_parse_empower_info`'s indentation test always sees indent 0 -- its section headers are
        therefore matched on the whole line, never on how deep it sits;
      * dialect detection runs per line while collecting, and Empower WINS over Phoenix.
    The returned trigger line is what the report quotes back, because "this file was read as an
    Empower export because line N says `bad electrics`" is the sentence a curator can act on."""
    block: list[str] = []
    started = False
    phoenix = False
    empower = False
    trigger = None
    for raw_line in lines:
        line = raw_line.strip()
        if ">info" in line.lower():
            started = True
            continue
        if started and line and line[0] == ">":
            break
        if started and line:
            low = line.lower()
            if "run information" in low:
                phoenix = True
            elif ("empower" in low and "v" in low) or "electrics" in low or "magnetics" in low:
                if not empower:
                    trigger = line
                empower = True
            block.append(line)
    dialect = "empower" if empower else ("phoenix" if phoenix else "standard")
    return block, dialect, trigger


# `Information._translation_dict`, the standard-dialect key map. Only the entries that can change a
# key are mirrored; anything absent is stored under its own lowercased name, which is what the
# AusMT-enriched EDIs rely on (they write `run.ex.contact_resistance.start` in full).
_STANDARD_KEYS = {
    "operator": "run.acquired_by.author", "adu_serial": "run.data_logger.id",
    "e_azimuth": "run.ex.measurement_azimuth", "ex_len": "run.ex.dipole_length",
    "ey_len": "run.ey.dipole_length", "ex_resistance": "run.ex.contact_resistance.start",
    "ey_resistance": "run.ey.contact_resistance.start", "h_azimuth": "run.hx.measurement_azimuth",
    "hx": "run.hx.sensor.id", "hy": "run.hy.sensor.id", "hz": "run.hz.sensor.id",
    "hx_resistance": "run.hx.h_field_max.start", "hy_resistance": "run.hy.h_field_max.start",
    "hz_resistance": "run.hz.h_field_max.start",
    "algorithmname": "transfer_function.software.name",
    "ndec": "processing_parameter", "nfft": "processing_parameter", "ntype": "processing_parameter",
    "rrtype": "processing_parameter", "removelargelines": "processing_parameter",
    "rotmaxe": "processing_parameter", "project": "survey.project",
    "processedby": "transfer_function.processed_by.name",
    "processingsoftware": "transfer_function.software.name",
    "processingtag": "transfer_function.id",
    "signconvention": "transfer_function.sign_convention",
    "sitename": "station.geographic_name", "survey": "survey.id",
    "year": "survey.time_period.start_date", "runlist": "transfer_function.runs_processed",
    "remotesite": "transfer_function.remote_references",
    "remoteref": "transfer_function.processing_parameters",
}

# `Information._empower_translation_dict`.
_EMPOWER_KEYS = {
    "processingsoftware": "transfer_function.software.name",
    "sitename": "station.geographic_name", "year": "survey.time_period.start_date",
    "process_date": "transfer_function.processed_date",
    "declination": "station.location.declination.value",
    "tag": "component", "length": "dipole_length", "ac": "ac.end", "dc": "dc.end",
    "negative res": "contact_resistance.start", "negative_res": "contact_resistance.start",
    "positive res": "contact_resistance.end", "positive_res": "contact_resistance.end",
    "sensor type": "sensor.model", "sensor_type": "sensor.model",
    "detected sensor type": "sensor.model", "azimuth": "measured_azimuth",
    "sensor serial": "sensor.id", "sensor_serial": "sensor.id",
    "cal name": "comments", "cal_name": "comments", "saturation": "comments",
    "instrument type": "data_logger.model", "station name": "geographic_name",
    "operator": "acquired_by.author", "recording id": "id",
    "min value": "comments", "max value": "comments",
}

_EMPOWER_COMPONENTS = ("ex", "ey", "hx", "hy", "hz", "rx", "ry", "e1", "e2", "h1", "h2", "h3")
_EMPOWER_COMPONENT_MAP = {"ex": "ex", "ey": "ey", "hx": "hx", "hy": "hy", "hz": "hz",
                          "rx": "rrhx", "ry": "rrhy", "e1": "ex", "e2": "ey",
                          "h1": "hx", "h2": "hy", "h3": "hz"}


def _empower_std_key(section: str, component: str | None, key: str, sub_section: str | None) -> str | None:
    """Mirror of `Information._get_empower_std_key`."""
    if section == "general":
        return _EMPOWER_KEYS.get(key)
    if not component:
        mapped = _EMPOWER_KEYS.get(key)
        if not mapped:
            return None
        if section == "reference":
            return f"transfer_function.remote_references.{mapped}"
        return f"run.{mapped}" if sub_section else mapped
    std_component = _EMPOWER_COMPONENT_MAP.get(component, component)
    mapped = _EMPOWER_KEYS.get(key)
    if mapped:
        if section == "reference":
            return f"transfer_function.remote_references.{std_component}.{mapped}"
        return f"run.{std_component}.{mapped}"
    if key in ("cal name", "cal_name", "saturation", "min value", "max value"):
        if section == "reference":
            return f"transfer_function.remote_references.{std_component}.comments"
        return f"run.{std_component}.comments"
    if section == "reference":
        return f"transfer_function.remote_references.{std_component}.{key}"
    return f"run.{std_component}.{key}"


def _empower_clean(value: str) -> str:
    """Mirror of `_parse_empower_info`'s value cleanup. Reproduced EXACTLY, quirks included: the
    ` m` and ` V` substitutions are unanchored, so they bite anywhere in a value, and NOTHING here
    removes JSON's structural member separator. That last absence is the whole defect."""
    if value.find("[") > 2:          # unreachable after sanitise_lines strips brackets; kept faithful
        parts = value.replace("[", "").replace("]", "").split(",")
        value = parts[0].strip().split(" ")[0] if len(parts) == 1 else ",".join(p.strip() for p in parts)
    return (value.replace("°", "").replace("Â", "").replace(" m", "").replace(" V", "")
            .replace(" â„", "").replace("¦", "").replace(" Ω", "").strip())


def _scrape_empower(block: list[str]) -> dict[str, object]:
    """Mirror of `Information._parse_empower_info`. Returns the info_dict it would build."""
    info: dict[str, object] = {}
    section = "general"
    component: str | None = None
    sub_section: str | None = None
    for raw_line in block:
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        # Indentation is always 0 here (the collector stripped every line), so mt_metadata's
        # `indent_level <= 5` gate is always open: a bare section word ALWAYS switches section.
        if low == "stations":
            section = "stations"
            continue
        if low in ("electrics", "magnetics", "reference"):
            section = sub_section = low
            continue
        if section in ("electrics", "magnetics", "reference") or sub_section in ("electrics", "magnetics", "reference"):
            if _get_separator(line) is None and low in _EMPOWER_COMPONENTS:
                component = low
                continue
        sep = _get_separator(line)
        if not sep:
            if low in ("editing workbench", "stations"):
                section = low.replace(" ", "_")
            continue
        parts = line.split(sep, 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip().lower()
        value: object = _empower_clean(parts[1].strip())
        std_key = _empower_std_key(section, component, key, sub_section)
        if not std_key:
            if component:
                context_key = f"{section}.{component}.{key}"
            elif sub_section and sub_section != section:
                context_key = f"{sub_section}.{key}"
            elif section != "general":
                context_key = f"{section}.{key}"
            else:
                context_key = key
            info[context_key] = value
            continue
        if "remote_references." in std_key and ("acquired_by" in std_key or "data_logger" in std_key
                                                or "author" in std_key):
            continue
        if "azimuth" in std_key and "measured_azimuth" not in std_key:
            continue
        if "component" in std_key:
            value = component
        if ("hx" in std_key or "hy" in std_key or "hz" in std_key):
            if "acquired_by" in std_key or "data_logger" in std_key:
                std_key = std_key.replace(".hx.", ".").replace(".hy.", ".").replace(".hz.", ".")
            elif "ac" in std_key or "dc" in std_key:
                std_key = std_key.replace("ac", "comments").replace("dc", "comments")
        if "comments" in std_key:
            previous = info.get(std_key, [])
            if not isinstance(previous, list):
                previous = [] if not previous else [previous]
            previous.append(f"{key}={value}")
            value = previous
        elif "data_logger.model" in std_key:
            std_key = "run.data_logger.model"
        elif std_key.endswith(".id") and "sensor.id" not in std_key:
            std_key = "run.id"
        elif "geographic_name" in std_key:
            std_key = ("transfer_function.remote_references.geographic_name"
                       if "remote_references" in std_key else "station.geographic_name")
        elif "author" in std_key:
            std_key = "run.acquired_by.author"
        info[std_key] = value
    return info


def _scrape_standard(block: list[str]) -> dict[str, object]:
    """Mirror of `Information._parse_standard_info`."""
    info: dict[str, object] = {}
    for line in block:
        if not line or "<" in line or ">" in line:
            continue
        sep = _get_separator(line)
        if not sep:
            info[line.strip()] = ""
            continue
        parts = line.split(sep, 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip().lower()
        value: object = parts[1].strip()
        if isinstance(value, str) and value.startswith("[") and value.endswith("]"):
            value = [v.strip() for v in value[1:-1].replace(",", " ").replace(";", " ")
                     .replace(":", " ").split()]
        std_key = _STANDARD_KEYS.get(key)
        if std_key is None:
            info[key] = value
        elif std_key == "processing_parameter":
            params = info.get("transfer_function.processing_parameters", [])
            if not isinstance(params, list):
                params = [params]
            params.append(f"{key}={value}")
            info["transfer_function.processing_parameters"] = params
        else:
            info[std_key] = value
    return info


_PHOENIX_KEYS = {
    "survey": "survey.id", "company": "station.acquired_by.organization", "job": "survey.project",
    "hardware": "run.data_logger.model", "mtuprog version": "run.data_logger.firmware.version",
    "xpr weighting": "processing_parameter", "hx sen": "run.hx.sensor.id",
    "hy sen": "run.hy.sensor.id", "hz sen": "run.hz.sensor.id", "rx sen": "run.rrhx.sensor.id",
    "ry sen": "run.rrhy.sensor.id", "stn number": "station.id",
    "mtu-box serial number": "run.data_logger.id",
    "ex pot resist": "run.ex.contact_resistance.start",
    "ey pot resist": "run.ey.contact_resistance.start",
    "ex voltage": ["run.ex.ac.start", "run.ex.dc.start"],
    "ey voltage": ["run.ey.ac.start", "run.ey.dc.start"],
    "start-up": "station.time_period.start", "end-time": "station.time_period.end",
}


def _split_phoenix_columns(line: str) -> list[str]:
    """Mirror of `Information._split_phoenix_columns`: a Phoenix INFO line can hold TWO key/value
    pairs side by side, split at the widest inter-word gap when both halves carry a separator."""
    if not line or len(line) < 10:
        return [line]
    parts = []
    idx = 0
    for word in line.split(" "):
        if word:
            parts.append((word, idx))
        idx += len(word) + 1
    if len(parts) < 4:
        return [line]
    gaps = [parts[i + 1][1] - (parts[i][1] + len(parts[i][0])) for i in range(len(parts) - 1)]
    if not gaps:
        return [line]
    max_gap = max(gaps)
    if max_gap <= 3:
        return [line]
    split_pos = parts[gaps.index(max_gap) + 1][1]
    left, right = line[:split_pos].strip(), line[split_pos:].strip()
    if (":" in left or "=" in left) and (":" in right or "=" in right):
        return [left, right]
    return [line]


def _scrape_phoenix(block: list[str]) -> dict[str, object]:
    """Mirror of `Information._parse_phoenix_info` + `_apply_phoenix_translation`."""
    info: dict[str, object] = {}
    for line in block:
        for column in _split_phoenix_columns(line):
            sep = _get_separator(column)
            if not sep:
                continue
            parts = column.split(sep, 1)
            if len(parts) != 2:
                continue
            key = parts[0].strip().lower()
            value = parts[1].strip()
            if value.count("  ") > 0:
                value = value.split(" ")[0].strip()
            if "pot resist" in key and value:
                value = value.split()[0]
            if "voltage" in key:
                for comp in value.replace(" ", "").split(","):
                    if "=" in comp:
                        typ, val = comp.split("=", 1)
                        info[f"run.{key[0:2].lower()}.{typ.lower()}.start"] = val.replace("mV", "")
                continue
            std_key = _PHOENIX_KEYS.get(key, "phoenix_attribute")
            if isinstance(std_key, list):
                for kk in std_key:
                    info[kk] = value
            else:
                info[std_key] = value
            if " sen" in key:
                comp = key.split()[0]
                info[f"{comp}.sensor.manufacturer"] = "Phoenix Geophysics"
                info[f"{comp}.sensor.type"] = "Induction Coil"
    return info


def scrape_info(raw: bytes) -> tuple[dict[str, object], str, str | None]:
    """(info_dict, dialect, trigger line) -- exactly what `Information.read_info` would produce for
    these bytes, including its `_comments_to_string` pass. The parity test asserts this against the
    real library rather than taking the mirror on trust."""
    block, dialect, trigger = _collect_info_block(sanitise_lines(raw))
    scraper = {"empower": _scrape_empower, "phoenix": _scrape_phoenix}.get(dialect, _scrape_standard)
    info = scraper(block)
    for key, value in list(info.items()):
        if "comment" in key and isinstance(value, list):
            info[key] = ",".join(value)
    return info, dialect, trigger


def _head_value(lines: list[str], want: str) -> str | None:
    """A >HEAD `KEY=value` value, read the way `Header.get_header_list` reads them."""
    found = False
    for line in lines:
        if ">" in line and "head" in line.lower():
            found = True
            continue
        if ">" in line:
            if found:
                break
            continue
        if found and len(line.strip()) > 2:
            pair = line.strip().replace('"', "").split("=")
            if len(pair) == 2 and pair[0].strip().lower() == want:
                return pair[1].strip()
    return None


def _reference_positions(lines: list[str]) -> dict[str, str]:
    """The `>=DEFINEMEAS` reference position strings, keyed reflat/reflon/refelev.

    Mirrors `DefineMeasurement.get_measurement_lists` + `read_measurement`, whose `setattr` is
    UNGUARDED: a reference latitude mt_metadata's validator refuses stops the read dead. That is the
    one pre-existing failure in the selected corpus (capricorn-2010 CP3B21.edi, reflat
    `--26.0322667`, a doubled minus), and it is a failure the >INFO fallback cannot help with."""
    out: dict[str, str] = {}
    found = False
    for line in lines:
        if ">=" in line and "definemeas" in line.lower():
            found = True
            continue
        if ">=" in line:
            if found:
                break
            continue
        if not found or ">" in line:
            continue
        pair = line.strip().split("=")
        if len(pair) != 2:
            continue
        key, value = pair[0].strip().lower(), pair[1].strip()
        # mt_metadata's own SUBSTRING tests, kept as they are so the same aliases resolve.
        if key and key in "reflatitude":
            out["reflat"] = value
        elif key and key in "reflongitude":
            out["reflon"] = value
        elif key and key in "refelevation":
            out["refelev"] = value
    return out


def _position_is_readable(value: str, kind: str) -> bool:
    """Mirror of `utils/location_helpers.validate_position`: a `DD:MM:SS` string is split on `:`
    (exactly three parts, each a float), anything else must be a bare float, and the result must sit
    inside the legal range for a latitude or a longitude."""
    if value in (None, "", "None"):
        return True
    try:
        if ":" in value:
            parts = value.split(":")
            if len(parts) != 3:
                return False
            deg, minutes, sec = float(parts[0]), float(parts[1]), float(parts[2])
            degrees = (-1 if deg < 0 else 1) * (abs(deg) + minutes / 60.0 + sec / 3600.0)
        else:
            degrees = float(value)
    except (TypeError, ValueError):
        return False
    return abs(degrees) <= (90 if kind == "latitude" else 180)


_STATION_NAME_OK = re.compile(r"^[a-zA-Z0-9_]+$")


def station_name(raw_dataid: str) -> str:
    """The station id the BUILD will use, not the string in the file. Mirrors
    `utils/validators.validate_station_name`, which swaps space, `-`, `.` and `+` for `_`. The report
    names stations the way the catalogue and the build log name them, so a curator can match a
    finding to a station without translating."""
    return raw_dataid.strip().replace(" ", "_").replace("-", "_").replace(".", "_").replace("+", "_")


def _station_name_is_readable(raw_dataid: str) -> bool:
    """`validate_station_name` RAISES on any surviving character outside letters, digits and
    underscore -- and `read_header` calls it OUTSIDE the try/except that guards the assignment, so a
    station called `MT01(a)` stops the read before anything else is attempted. Measured against
    mt_metadata 1.0.9 (2026-08-09): `MT-01`, `MT 01` and `MT_01` all read; `MT01(a)`, `MT#1` and
    `MT/1` all raise."""
    return bool(_STATION_NAME_OK.match(station_name(raw_dataid)))


def _is_number(value: object) -> bool:
    """Can pydantic coerce this to a float? A plain `float()` is the same test its scalar validator
    applies, so `'5,'` (a JSON member separator left behind) and `'2.5 kilo-ohms'` (a unit carried
    into a number field) both answer no, which is exactly why they break."""
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    try:
        float(value.strip())
    except ValueError:
        return False
    return True


def _drop_trailing_delimiters(raw: bytes) -> bytes:
    """The AusMT fallback's normalisation, byte for byte: drop a trailing `,` from every line INSIDE
    the >INFO block and change nothing else. Duplicated here rather than imported so this module
    stays stdlib-only and importable in the gateway runner without the scientific stack; the parity
    test asserts it agrees with `_mtm.normalise_info_json_delimiters` byte for byte."""
    out: list[bytes] = []
    in_info = False
    for line in raw.splitlines(keepends=True):
        body = line.rstrip(b"\r\n")
        eol = line[len(body):]
        stripped = body.strip()
        if not in_info:
            if b">info" in stripped.lower():
                in_info = True
            out.append(line)
            continue
        if stripped.startswith(b">"):
            in_info = False
            out.append(line)
            continue
        trimmed = body.rstrip()
        out.append(trimmed[:-1] + body[len(trimmed):] + eol if trimmed.endswith(b",") else line)
    return b"".join(out)


def _fatal_info_problems(info: dict[str, object]) -> list[dict]:
    """Every scraped >INFO value bound for a numerically-typed field that mt_metadata sets WITHOUT a
    try/except and that will not coerce. Each one stops the read."""
    problems = []
    for key, plain in _FATAL_INFO_FIELDS.items():
        if key in info and not _is_number(info[key]):
            problems.append({"field": key, "field_plain": plain, "value": info[key]})
    return problems


def _silent_numeric_problems(info: dict[str, object]) -> list[dict]:
    """Values bound for a numerically-typed CHANNEL field that will not coerce. mt_metadata catches
    the error and logs it, so the read succeeds and the field is simply never populated. Nothing in
    AusMT tells anyone about these today."""
    problems = []
    for key, value in info.items():
        if not key.startswith("run.") or not isinstance(value, str):
            continue
        rest = key[len("run."):]
        component, _, attribute = rest.partition(".")
        plain = _SILENT_NUMERIC_CHANNEL_FIELDS.get(attribute)
        if plain and not _is_number(value):
            problems.append({"field": key, "field_plain": plain,
                             "component": component.upper(), "value": value})
    return problems


def _delimited_values(info: dict[str, object]) -> list[dict]:
    """Scraped values that keep a trailing comma. In a JSON >INFO block every scalar that is not the
    last member of its object keeps one, and mt_metadata stores the comma as part of the value. Only
    the one that lands in a numeric field raises; the rest ride into the published metadata."""
    return [{"field": k, "value": v} for k, v in info.items()
            if isinstance(v, str) and v.rstrip().endswith(",")]


def preflight_bytes(raw: bytes, *, label: str = "") -> dict:
    """The whole prediction for one EDI's bytes. Pure: no I/O, no state, nothing written."""
    lines = sanitise_lines(raw)
    dataid = _head_value(lines, "dataid")
    station = station_name(dataid) if dataid else (Path(label).stem or "?")
    info, dialect, trigger = scrape_info(raw)

    finding = {
        "file": label,
        "station": station,
        "info_dialect": dialect,
        "empower_trigger": trigger,
        "scraped_values": len(info),
        "delimited_values": _delimited_values(info),
        "silent_numeric_fields": _silent_numeric_problems(info),
        "blocking_fields": [],
        "outcome": READS,
        "reason": "",
    }

    # 1. A station id mt_metadata's own validator refuses. `read_header` calls the validator OUTSIDE
    #    the try/except that guards the assignment, so this stops the read before anything else runs
    #    and is reported first, ahead of anything further down the file.
    if dataid is not None and not _station_name_is_readable(dataid):
        finding["outcome"] = WILL_NOT_READ
        finding["blocking_fields"] = [{"field": ">HEAD DATAID", "field_plain": "station id",
                                       "value": dataid}]
        finding["reason"] = (f"the station id is written as \"{dataid}\", and the reader accepts only "
                             f"letters, digits and underscores (it turns spaces, hyphens, full stops "
                             f"and plus signs into underscores for you), so no reader can open this file")
        return finding

    # 2. A reference position mt_metadata refuses. Set unguarded in read_measurement, and the >INFO
    #    fallback cannot touch it, so this is terminal.
    positions = _reference_positions(lines)
    for key, kind in (("reflat", "latitude"), ("reflon", "longitude")):
        value = positions.get(key)
        if value not in _NULL_VALUES and not _position_is_readable(value, kind):
            finding["outcome"] = WILL_NOT_READ
            finding["blocking_fields"] = [{"field": f">=DEFINEMEAS {key.upper()}",
                                           "field_plain": f"reference {kind}", "value": value}]
            finding["reason"] = (f"the reference {kind} is written as \"{value}\", which is not a "
                                 f"number or a DD:MM:SS position, so no reader can open this file")
            return finding

    # 3. An >INFO value bound for an unguarded numeric field. If dropping the trailing delimiters
    #    inside the block clears it, this is precisely what the AusMT fallback rescues; if it does
    #    not, the value is wrong for some other reason and the file will not read at all.
    fatal = _fatal_info_problems(info)
    if fatal:
        finding["blocking_fields"] = fatal
        repaired_info, _, _ = scrape_info(_drop_trailing_delimiters(raw))
        still_fatal = _fatal_info_problems(repaired_info)
        first = fatal[0]
        if still_fatal:
            finding["outcome"] = WILL_NOT_READ
            finding["reason"] = (f"{first['field_plain']} is written as \"{first['value']}\", which "
                                 f"is not a number, so no reader can open this file")
        else:
            finding["outcome"] = NEEDS_REPAIR
            finding["reason"] = (f"{first['field_plain']} is scraped as \"{first['value']}\" -- the "
                                 f"stray comma is JSON punctuation the reader keeps -- so a stock "
                                 f"mt_metadata reader refuses the file; AusMT reads it by repairing "
                                 f"a temporary copy and never changes the file on disk")
    return finding


def preflight_file(path: Path) -> dict:
    """`preflight_bytes` for a file on disk, read-only. A file that cannot even be read is reported,
    not raised: a pre-flight over a package must always produce a finding list."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"file": path.name, "station": path.stem, "info_dialect": "unknown",
                "empower_trigger": None, "scraped_values": 0, "delimited_values": [],
                "silent_numeric_fields": [], "blocking_fields": [], "outcome": WILL_NOT_READ,
                "reason": f"the file could not be opened ({exc.strerror or exc})"}
    return preflight_bytes(raw, label=path.name)


def preflight_tree(root: Path) -> dict:
    """Pre-flight every `.edi` under `root` (recursively). Returns {summary, findings}, findings in
    path order so two runs over the same package are comparable."""
    root = Path(root)
    findings = []
    for path in sorted(root.rglob("*.edi")):
        finding = preflight_file(path)
        finding["path"] = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        findings.append(finding)
    counts = {READS: 0, NEEDS_REPAIR: 0, WILL_NOT_READ: 0}
    for finding in findings:
        counts[finding["outcome"]] = counts.get(finding["outcome"], 0) + 1
    return {
        "summary": {
            "files": len(findings),
            "reads": counts[READS],
            "needs_repair": counts[NEEDS_REPAIR],
            "will_not_read": counts[WILL_NOT_READ],
            "files_with_delimited_values": sum(1 for f in findings if f["delimited_values"]),
            "delimited_values": sum(len(f["delimited_values"]) for f in findings),
            "files_with_silent_numeric_fields": sum(1 for f in findings if f["silent_numeric_fields"]),
            "silent_numeric_fields": sum(len(f["silent_numeric_fields"]) for f in findings),
            "mirrored_mt_metadata": MIRRORED_MT_METADATA,
        },
        "findings": findings,
    }


# --------------------------------------------------------------------------------------------
# Plain-words rendering. A curator is a geophysicist, not a developer: every line below names the
# station, the field and the consequence, and never asks the reader to know what pydantic is.
# --------------------------------------------------------------------------------------------
_SAMPLE = 3


def _advisory_lines(finding: dict) -> list[str]:
    """The advisory sentences for one station: what will be stored wrong, and what will be blank."""
    lines = []
    delimited = finding["delimited_values"]
    if delimited:
        sample = ", ".join(f"{d['field']} = \"{d['value']}\"" for d in delimited[:_SAMPLE])
        lines.append(f"{len(delimited)} of {finding['scraped_values']} metadata values will be stored "
                     f"with a trailing comma (JSON punctuation the reader keeps), for example {sample}")
    for problem in finding["silent_numeric_fields"]:
        lines.append(f"{problem['field_plain']} for {problem['component']} is a number field, but the "
                     f"file supplies \"{problem['value']}\"; the units make it unreadable as a number, "
                     f"so this station will be published with no {problem['field_plain']}")
    return lines


def advisory_summary(report: dict, *, limit: int = 12) -> list[str]:
    """A BOUNDED list of plain sentences for somewhere with no room for a full report: the gateway's
    submission status page and the curator's reports panel.

    Advisory by construction. Nothing here is a verdict on a submission: a stray comma in a metadata
    field must tell the person about it, never refuse their data. Returns [] when there is nothing to
    say, so a clean package adds no noise at all.

    Bounded because the Western Gawler delivery would otherwise put 246 lines on a status page, and a
    page nobody reads to the end is a page that tells nobody anything. The rest are rolled into a
    count, with the full per-station detail in the JSON report beside it."""
    s = report["summary"]
    lines: list[str] = []
    if s["will_not_read"]:
        lines.append(f"EDI pre-flight: {s['will_not_read']} of {s['files']} files will not open in "
                     "the reader AusMT uses, and need fixing by whoever produced them")
    if s["needs_repair"]:
        lines.append(f"EDI pre-flight: {s['needs_repair']} of {s['files']} files need AusMT's >INFO "
                     "repair to be read at all (AusMT does this on a temporary copy; your files are "
                     "never changed)")
    if s["delimited_values"]:
        lines.append(f"EDI pre-flight: {s['delimited_values']} metadata values across "
                     f"{s['files_with_delimited_values']} files will be stored with a trailing comma, "
                     "which is JSON punctuation the reader keeps")
    if s["silent_numeric_fields"]:
        lines.append(f"EDI pre-flight: {s['silent_numeric_fields']} number fields across "
                     f"{s['files_with_silent_numeric_fields']} files carry their units in the value, "
                     "so they will be published empty")
    if not lines:
        return []

    detail = [f for f in report["findings"] if f["outcome"] in (WILL_NOT_READ, NEEDS_REPAIR)]
    detail += [f for f in report["findings"]
               if f["outcome"] == READS and f["silent_numeric_fields"]]
    for finding in detail[:limit]:
        reason = finding["reason"] or "; ".join(_advisory_lines(finding))
        lines.append(f"{finding['file']} (station {finding['station']}): {reason}")
    if len(detail) > limit:
        lines.append(f"... and {len(detail) - limit} more stations; the full list is in the "
                     "EDI pre-flight report")
    lines.append("None of the above blocks this submission. It is advice about the metadata AusMT "
                 "will be able to read.")
    return lines


def render(report: dict, *, root_label: str = "") -> str:
    """The human report. Ordered worst first, because the first screen is the one that gets read."""
    s = report["summary"]
    out = [f"=== AusMT EDI pre-flight: {s['files']} files{f' under {root_label}' if root_label else ''} ===",
           "",
           f"  will not read       {s['will_not_read']:>5}   must be fixed by whoever produced the file",
           f"  needs the repair    {s['needs_repair']:>5}   AusMT reads these; a stock mt_metadata reader will not",
           f"  reads as-is         {s['reads']:>5}",
           "",
           f"  metadata values that will carry a stray comma   {s['delimited_values']:>7}"
           f"   in {s['files_with_delimited_values']} files",
           f"  number fields that will silently stay empty     {s['silent_numeric_fields']:>7}"
           f"   in {s['files_with_silent_numeric_fields']} files",
           ""]
    if s["files"] and not (s["will_not_read"] or s["needs_repair"] or s["delimited_values"]
                           or s["silent_numeric_fields"]):
        out.append("Nothing to report: every file reads, and no metadata value is damaged on the way in.")
        return "\n".join(out)

    for title, outcome in (("WILL NOT READ", WILL_NOT_READ), ("NEEDS THE >INFO REPAIR", NEEDS_REPAIR)):
        rows = [f for f in report["findings"] if f["outcome"] == outcome]
        if not rows:
            continue
        out.append(f"--- {title} ({len(rows)}) ---")
        for finding in rows:
            out.append(f"{finding['file']}  (station {finding['station']})")
            out.append(f"    {finding['reason']}.")
            if finding["empower_trigger"]:
                out.append(f"    read as an Empower export because a line in >INFO says: "
                           f"{finding['empower_trigger'][:90]}")
            for line in _advisory_lines(finding):
                out.append(f"    {line}.")
            out.append("")

    advisory = [f for f in report["findings"]
                if f["outcome"] == READS and (f["delimited_values"] or f["silent_numeric_fields"])]
    if advisory:
        out.append(f"--- READS, BUT METADATA IS DAMAGED ON THE WAY IN ({len(advisory)}) ---")
        out.append("These files build. Nobody is told any of this today.")
        out.append("")
        for finding in advisory:
            out.append(f"{finding['file']}  (station {finding['station']})")
            for line in _advisory_lines(finding):
                out.append(f"    {line}.")
            out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="an EDI file, or a directory searched recursively for *.edi")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the full machine-readable report to this path")
    ap.add_argument("--quiet", action="store_true", help="write only the JSON report")
    a = ap.parse_args(argv)
    target = Path(a.target)
    if not target.exists():
        sys.exit(f"no such file or directory: {target}")
    if target.is_file():
        finding = preflight_file(target)
        finding["path"] = target.name
        report = {"summary": {"files": 1, "reads": int(finding["outcome"] == READS),
                              "needs_repair": int(finding["outcome"] == NEEDS_REPAIR),
                              "will_not_read": int(finding["outcome"] == WILL_NOT_READ),
                              "files_with_delimited_values": int(bool(finding["delimited_values"])),
                              "delimited_values": len(finding["delimited_values"]),
                              "files_with_silent_numeric_fields": int(bool(finding["silent_numeric_fields"])),
                              "silent_numeric_fields": len(finding["silent_numeric_fields"]),
                              "mirrored_mt_metadata": MIRRORED_MT_METADATA},
                  "findings": [finding]}
    else:
        report = preflight_tree(target)
    if not a.quiet:
        print(render(report, root_label=target.name))
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        if not a.quiet:
            print(f"full report -> {a.json_out}")
    # A REPORTER blocks nothing: the exit status is 0 whatever it finds. Anything that turns a
    # metadata advisory into a failed pipeline step belongs in the validator, not here.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
