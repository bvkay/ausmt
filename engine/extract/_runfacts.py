#!/usr/bin/env python3
"""Run-acquisition facts from an EDI `>INFO` block, one extractor per source dialect.

mt_metadata reads a transfer function, not a field record: for every EDI in this corpus its Run
carries library defaults (see _presence) and none of the acquisition metadata the custodians did
write, because each of them wrote it a different way inside the free-text `>INFO` section. Six
dialects appear in the corpus and no single scrape reads them all, so each has its own extractor
here and each says which dialect and which extraction-confidence class produced every value it
returns (station-metadata scope section 6).

    enriched-dotted   mt_metadata-style `run.*` / `station.*` keys (the AusMT header enrichment)
    mtpy-fieldnotes   `fieldnotes.*` keys written by MTpy's EDI writer
    lemimt-site       the LEMIMT `SITE :` / `Instrument :` lines (the band token is declined)
    empower-json      Phoenix EMpower's per-record receiver JSON
    phoenix           Phoenix MTU field sheets (free text) and the compact per-station JSON
    ga-geotools       the Geotools survey header, which states no acquisition fact at all

CONFIDENCE, not certainty: a class is recorded for every emitted value, and an uncertain parse
emits NOTHING (a missing field beats a confidently wrong number). Three facts the corpus does carry
are deliberately NOT extracted here and are reported for curation instead: the Phoenix field sheet's
`Ex Pot Resist` contact resistances (the 0.1 schema applies unit_value to the one dialect that
states resistance as a curated unit-bearing value); every acquisition window whose source states
no timezone (the EMpower record stamp and the field sheet's START-UP/END-TIME), because a run's
time_period is an ISO 8601 UTC instant and inventing the offset would be an inference; and the
LEMIMT SITE line's `S-<rate>Hz` band token, which records the MERGING OF DOWNSAMPLED EDI FILES and
not the rate the station was acquired at, so publishing it as a run rate would state a processing
parameter as a measurement.

The result is a plain-JSON dict so it can ride the C18 parse cache beside the record it describes.
"""
from __future__ import annotations

import json
import math
import re

# The extraction-confidence vocabulary (station-metadata scope section 6). `curator_supplied` and
# `inferred` are declared because the scope names them; nothing here emits an inferred value.
FORMAL_EDI_FIELD = "formal_edi_field"
STRUCTURED_DIALECT = "structured_dialect"
PATTERN_EXTRACTED = "pattern_extracted"
CURATOR_SUPPLIED = "curator_supplied"
INFERRED = "inferred"
CONFIDENCE_CLASSES = (FORMAL_EDI_FIELD, STRUCTURED_DIALECT, PATTERN_EXTRACTED,
                      CURATOR_SUPPLIED, INFERRED)

# The D2 fact vocabulary, shared with the surveys repo's run-id assignment tool so the store and the
# emitter qualify the same stations. A station asserting none of these gets no runs[] at all.
FACTS = ("source_run_id", "sample_rate", "time_period", "data_logger", "serial", "sensor",
         "dipole_length", "contact_resistance")

_DOTTED = re.compile(r"(?m)^([A-Za-z][\w.]*)\s*=\s*(.*)$")
_DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
# The magnetic component families the schema's channel guards recognise, lowercased.
_MAGNETIC = ("hx", "hy", "hz", "bx", "by", "bz")
# Resistance units the corpus states as source text. The parsed value is ohms; anything outside the
# table keeps its source_value and gains no number (schema: `unit` is required whenever `value` is).
_RESISTANCE_UNITS = {"ohm": 1.0, "ohms": 1.0, "kilo-ohm": 1e3, "kilo-ohms": 1e3,
                     "kiloohm": 1e3, "kiloohms": 1e3, "kohm": 1e3, "kohms": 1e3,
                     "mega-ohm": 1e6, "mega-ohms": 1e6, "megaohm": 1e6, "megaohms": 1e6,
                     "mohm": 1e6, "mohms": 1e6}
_RESISTANCE_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([A-Za-z-]+)\s*$")
# A source note that CONTRADICTS the channel list wins over any corroboration (D9). The corpus
# fixture is the enriched header's own caveat: "HZ/RX/RY channel declarations are exporter template
# artifacts". Components are read off the sentence, so a note naming other channels works unchanged.
_TEMPLATE_ARTEFACT_RE = re.compile(
    r"([A-Za-z0-9/ ,]+?)\s+channel declarations are exporter template artifacts", re.IGNORECASE)


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value):
    try:
        return float(_text(value))
    except (TypeError, ValueError):
        return None


def _positive(value):
    n = _number(value)
    return n if (n is not None and n > 0) else None


def bare_doi(value):
    """A DOI in the bare canonical form the schema wants (scope 4.2), or None when the value is not
    one. The resolver prefix is stripped; the DOI's own case is kept."""
    doi = _DOI_PREFIX.sub("", _text(value))
    return doi if re.match(r"^10\.\d{4,9}/\S+$", doi) else None


def unit_value(source_text):
    """The dual representation for a unit-bearing source value (scope section 6): the source string
    always, plus a parsed ohm value where the unit is one this table knows. An unrecognised unit
    keeps the source text alone rather than guessing a scale."""
    raw = _text(source_text)
    if not raw:
        return None
    out = {"source_value": raw}
    m = _RESISTANCE_RE.match(raw)
    if m:
        scale = _RESISTANCE_UNITS.get(m.group(2).lower())
        magnitude = _number(m.group(1))
        if scale is not None and magnitude is not None and magnitude > 0:
            out["value"] = round(magnitude * scale, 6)
            out["unit"] = "ohm"
    return out


def _blank_document() -> dict:
    return {"dialects": [], "facts": [], "confidence": {}, "run": {}, "channels": {},
            "named_components": [], "excluded_components": []}


class _Doc:
    """Accumulator: every setter records the dialect and confidence class behind its value, and the
    first extractor to state a value keeps it (families are applied strongest-evidence first)."""

    def __init__(self):
        self.doc = _blank_document()

    def dialect(self, name):
        if name not in self.doc["dialects"]:
            self.doc["dialects"].append(name)

    def fact(self, name):
        if name not in self.doc["facts"]:
            self.doc["facts"].append(name)

    def named(self, component):
        c = _text(component).lower()
        if c and c not in self.doc["named_components"]:
            self.doc["named_components"].append(c)

    def excluded(self, component):
        c = _text(component).lower()
        if c and c not in self.doc["excluded_components"]:
            self.doc["excluded_components"].append(c)

    def run(self, key, value, confidence, fact=None):
        if value is None or key in self.doc["run"]:
            return
        self.doc["run"][key] = value
        self.doc["confidence"][f"run.{key}"] = confidence
        if fact:
            self.fact(fact)

    def channel(self, component, key, value, confidence, fact=None):
        c = _text(component).lower()
        if value is None or not c:
            return
        ch = self.doc["channels"].setdefault(c, {})
        if key in ch:
            return
        ch[key] = value
        self.doc["confidence"][f"channels.{c}.{key}"] = confidence
        self.named(c)
        if fact:
            self.fact(fact)


def _instrument(manufacturer=None, model=None, serial=None, doi=None) -> dict:
    """An Instrument object carrying only what the source stated. Returns {} when it stated none."""
    out = {}
    for key, value in (("manufacturer", manufacturer), ("model", model), ("serial_number", serial)):
        if _text(value):
            out[key] = _text(value)
    identifier = bare_doi(doi)
    if identifier:
        out["identifiers"] = [{"scheme": "DOI", "identifier": identifier}]
    return out


# --------------------------------------------------------------------------- the six dialects

def _enriched_dotted(info: str, kv: dict, doc: _Doc):
    """The AusMT header enrichment: mt_metadata's own attribute paths written as `key = value`.
    The one dialect in the corpus that states a run id, a nominal rate, an acquisition window in
    UTC, instrument PIDs and contact resistance as a unit-bearing string."""
    if not any(k.startswith(("run.", "station.time_period.")) for k in kv):
        return
    doc.dialect("enriched-dotted")
    doc.run("id", _text(kv.get("run.id")) or None, STRUCTURED_DIALECT, fact="source_run_id")
    doc.run("sample_rate_hz", _positive(kv.get("run.sample_rate")), STRUCTURED_DIALECT,
            fact="sample_rate")
    period = {}
    for bound in ("start", "end"):
        stamp = _text(kv.get(f"station.time_period.{bound}"))
        if stamp:
            period[bound] = stamp
    if period.get("start"):
        doc.run("time_period", period, STRUCTURED_DIALECT, fact="time_period")
    logger = _instrument(kv.get("run.data_logger.manufacturer"), kv.get("run.data_logger.model"),
                         kv.get("run.data_logger.id"), kv.get("run.data_logger.doi"))
    if logger:
        doc.run("data_logger", logger, STRUCTURED_DIALECT, fact="data_logger")
        if "serial_number" in logger:
            doc.fact("serial")
    for name in _text(kv.get("station.channels_recorded")).split(","):
        doc.named(name)
    for key in kv:
        m = re.match(r"^run\.([a-z]\w*)\.", key)
        if m and m.group(1) not in ("id", "data_logger", "sample_rate"):
            doc.named(m.group(1))
    for component in list(doc.doc["named_components"]):
        prefix = f"run.{component}."
        doc.channel(component, "measurement_azimuth_deg", _number(kv.get(prefix + "measurement_azimuth")),
                    STRUCTURED_DIALECT)
        doc.channel(component, "dipole_length_m", _positive(kv.get(prefix + "dipole_length")),
                    STRUCTURED_DIALECT, fact="dipole_length")
        doc.channel(component, "contact_resistance",
                    unit_value(kv.get(prefix + "contact_resistance.start")),
                    STRUCTURED_DIALECT, fact="contact_resistance")
        sensor = _instrument(kv.get(prefix + "sensor.manufacturer"), kv.get(prefix + "sensor.model"),
                             kv.get(prefix + "sensor.id"), kv.get(prefix + "sensor.doi"))
        if sensor:
            doc.channel(component, "sensor", sensor, STRUCTURED_DIALECT, fact="sensor")
            if "serial_number" in sensor:
                doc.fact("serial")
    # D9 exclusion: a source assertion contradicting the channel list wins over any corroboration.
    for m in _TEMPLATE_ARTEFACT_RE.finditer(info):
        for token in re.split(r"[/,\s]+", m.group(1)):
            doc.excluded(token)


def _mtpy_fieldnotes(info: str, kv: dict, doc: _Doc):
    """MTpy's EDI writer emits a `fieldnotes.*` block. Its ids and coordinates are template values
    repeated unchanged across a whole survey, so only the MANUFACTURER strings and the electrode
    GEOMETRY are read; the azimuths are left alone, because a zero or identical pair in this dialect
    is the same "the orientations are not measurements" signature the canonical writer already
    records."""
    if not any(k.startswith("fieldnotes.") for k in kv):
        return
    doc.dialect("mtpy-fieldnotes")
    logger = _instrument(manufacturer=kv.get("fieldnotes.datalogger.manufacturer"),
                         model=kv.get("fieldnotes.datalogger.model"))
    if logger:
        doc.run("data_logger", logger, STRUCTURED_DIALECT, fact="data_logger")
    for component in _MAGNETIC:
        sensor = _instrument(manufacturer=kv.get(f"fieldnotes.magnetometer_{component}.manufacturer"),
                             model=kv.get(f"fieldnotes.magnetometer_{component}.model"))
        if sensor:
            doc.channel(component, "sensor", sensor, STRUCTURED_DIALECT, fact="sensor")
    for component in ("ex", "ey"):
        dx = (_number(kv.get(f"fieldnotes.electrode_{component}.x2")) or 0.0) - \
             (_number(kv.get(f"fieldnotes.electrode_{component}.x")) or 0.0)
        dy = (_number(kv.get(f"fieldnotes.electrode_{component}.y2")) or 0.0) - \
             (_number(kv.get(f"fieldnotes.electrode_{component}.y")) or 0.0)
        doc.channel(component, "dipole_length_m", _positive(round(math.hypot(dx, dy), 6)),
                    STRUCTURED_DIALECT, fact="dipole_length")


_SITE_LINE = re.compile(r"(?m)^SITE\s*:\s*(\S.*?)\s*$")
_LEMIMT_INSTRUMENT = re.compile(r"(?m)^Instrument\s*:\s*(\S.*?)\s*$")


def _lemimt_site(info: str, kv: dict, doc: _Doc):
    """LEMIMT writes the processing job into the SITE line: `P-<station>_RR-<remote>_S-10Hz_1`. The
    remote token is the reference STATION, never a second run, and it is already carried as the
    record's remote_site.

    The `S-<rate>Hz` token is the third declined fact (see the module docstring): it is the band of
    that processing job, recording the merging of downsampled EDI files rather than the rate the
    station was acquired at, so nothing in the site string is extracted. The Instrument line is the
    one acquisition fact this dialect states."""
    site = _SITE_LINE.search(info)
    instrument = _LEMIMT_INSTRUMENT.search(info)
    if not site and not instrument:
        return
    doc.dialect("lemimt-site")
    if instrument:
        doc.run("data_logger", _instrument(model=instrument.group(1)), PATTERN_EXTRACTED,
                fact="data_logger")


_EMPOWER_RECEIVER = re.compile(r'"receiver_model"\s*:\s*"([^"]+)"')
_EMPOWER_INSTID = re.compile(r'"instid"\s*:\s*"?(\w+)"?')
_EMPOWER_RATE = re.compile(r'"sampleRate"\s*:\s*(\d+(?:\.\d+)?)')


def _empower_json(info: str, kv: dict, doc: _Doc):
    """Phoenix EMpower writes one JSON record per acquisition into >INFO. D10: a SECOND top-level
    record is the REMOTE STATION, never a second run. The highest declared sampleRate is the run's
    nominal rate; the lower ones are the decimation ladder riding the transfer-function product.

    The model and the serial ARE isolated to the first record (`.search` takes the first match). The
    rate is not: `.findall` scans the whole block and takes the maximum across both records. That is
    safe by FIXTURE, not by construction - over the 246 two-record EDIs in the corpus no remote
    record declares a rate above its local one. A remote receiver sampled faster than the local one
    would publish the remote's rate, so this reads the whole block on purpose only while that holds."""
    if not _EMPOWER_RECEIVER.search(info):
        return
    doc.dialect("empower-json")
    model = _EMPOWER_RECEIVER.search(info)
    instid = _EMPOWER_INSTID.search(info)
    rates = [float(r) for r in _EMPOWER_RATE.findall(info)]
    doc.run("sample_rate_hz", _positive(max(rates)) if rates else None, STRUCTURED_DIALECT,
            fact="sample_rate")
    logger = _instrument(model=model.group(1), serial=instid.group(1) if instid else None)
    if logger:
        doc.run("data_logger", logger, STRUCTURED_DIALECT, fact="data_logger")
        if "serial_number" in logger:
            doc.fact("serial")


_PHX_HARDWARE = re.compile(r"(?m)^HARDWARE:\s*(\S+)")
_PHX_BOX_SERIAL = re.compile(r"MTU-Box Serial Number:\s*(\S+)")
_PHX_SENSOR = re.compile(r"(?m)^\s*(H[xyz])\s+Sen:\s*(\S+)", re.IGNORECASE)
_PHX_JSON_BLOCK = re.compile(r'"(LE|LH|Hz)"\s*:\s*\{([^}]*)\}')
_PHX_JSON_FIELD = r'"{field}"\s*:\s*"?([^",\n]+)"?'
_PHX_JSON_WINDOW = re.compile(r'"(Start|End)"\s*:\s*"([0-9T:\-]+Z)"')
_PHX_TAPPING_RATE = re.compile(r'"SampleRate"\s*:\s*(\d+(?:\.\d+)?)')


def _phoenix(info: str, kv: dict, doc: _Doc):
    """Phoenix MTU, two shapes in one survey. The field sheet is free text (HARDWARE, the MTU-Box
    serial, the per-coil `Hx Sen:` serials); the compact JSON states the receiver blocks, the dipole
    lengths and an acquisition window that carries an explicit Z.

    The `RH` block is the REMOTE station and the BLOCK regex never reads it as a channel or a second
    run. The window and the tapping rate are read off the whole record instead, so a second Start/End
    pair would win (`dict` keeps the last) and a second rate would join the maximum. Safe by FIXTURE:
    every corpus file carrying a window carries exactly one Start and one End."""
    hardware = _PHX_HARDWARE.search(info)
    blocks = {name: body for name, body in _PHX_JSON_BLOCK.findall(info)}
    if not hardware and not blocks:
        return
    doc.dialect("phoenix")

    def field(body, name):
        m = re.search(_PHX_JSON_FIELD.format(field=name), body)
        return m.group(1).strip() if m else None

    local = blocks.get("LE") or blocks.get("LH") or ""
    model = field(local, "StationType") if local else None
    serial = field(local, "Serial") if local else None
    confidence = STRUCTURED_DIALECT
    if hardware and not model:
        box = _PHX_BOX_SERIAL.search(info)
        model, serial, confidence = hardware.group(1), (box.group(1) if box else None), PATTERN_EXTRACTED
    logger = _instrument(model=model, serial=serial)
    if logger:
        doc.run("data_logger", logger, confidence, fact="data_logger")
        if "serial_number" in logger:
            doc.fact("serial")
    rates = [float(r) for r in _PHX_TAPPING_RATE.findall(info)]
    if rates:
        doc.run("sample_rate_hz", _positive(max(rates)), STRUCTURED_DIALECT, fact="sample_rate")
    window = dict(_PHX_JSON_WINDOW.findall(info))
    if window.get("Start"):
        doc.run("time_period",
                {k.lower(): v for k, v in window.items() if k in ("Start", "End")},
                STRUCTURED_DIALECT, fact="time_period")
    for component, length_key in (("ex", "ExLength"), ("ey", "EyLength")):
        doc.channel(component, "dipole_length_m",
                    _positive(field(blocks.get("LE", ""), length_key)), STRUCTURED_DIALECT,
                    fact="dipole_length")
    for name, body in blocks.items():
        for component in ("hx", "hy", "hz"):
            sensor = _instrument(serial=field(body, f"{component.capitalize()}Id"))
            if sensor:
                doc.channel(component, "sensor", sensor, STRUCTURED_DIALECT, fact="sensor")
                doc.fact("serial")
    for component, serial_text in _PHX_SENSOR.findall(info):
        sensor = _instrument(serial=serial_text)
        if sensor:
            doc.channel(component.lower(), "sensor", sensor, PATTERN_EXTRACTED, fact="sensor")
            doc.fact("serial")


_GEOTOOLS = re.compile(r"(?m)^SURVEY ID:")


def _ga_geotools(info: str, kv: dict, doc: _Doc):
    """The Geotools survey header (SURVEY ID / SURVEY CO / CLIENT CO / AREA / ROTATION). It carries
    survey context and NO acquisition fact, which is the correct outcome for a bare legacy EDI:
    nothing is populated and no run is published. Named so the classification is explicit rather
    than an absence."""
    if _GEOTOOLS.search(info):
        doc.dialect("ga-geotools")


_FAMILIES = (_enriched_dotted, _mtpy_fieldnotes, _lemimt_site, _empower_json, _phoenix, _ga_geotools)


def run_facts(info: str) -> dict:
    """The acquisition facts one EDI's >INFO block asserts. `facts` is the D2 gate's input (empty =>
    the station publishes no runs[] at all); `run` and `channels` carry the values themselves;
    `confidence` records the extraction class behind each; `named_components` and
    `excluded_components` feed the D9 channel rule."""
    text = _text(info)
    if not text:
        return _blank_document()
    kv = {k: v.strip() for k, v in _DOTTED.findall(text)}
    doc = _Doc()
    for family in _FAMILIES:
        try:
            family(text, kv, doc)
        except Exception:  # noqa: BLE001  (uncontrolled free text; a dialect miss is never fatal)
            continue
    return doc.doc


def run_facts_json(info: str) -> str:
    """Deterministic serialisation, for the cache-shape tests."""
    return json.dumps(run_facts(info), sort_keys=True)
