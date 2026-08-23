#!/usr/bin/env python3
"""The presence rule: which parsed run values are SOURCE ASSERTIONS and which are library defaults.

mt_metadata 1.0.9 is pydantic-based and instantiates a complete Run for every transfer function it
reads, whether or not the source states one. The values it invents are indistinguishable from real
ones at the attribute level, so an emitter that simply serialises the model publishes a fabricated
acquisition record: run id `<station>a`, a 0 Hz rate, a 1980 epoch window, an unnamed logger, a
0-ohm contact resistance and a pair of remote-reference channels the corpus never recorded.

ONE definition of "asserted", used twice: the emitter gates every run/channel value through the
predicates here, and the build REPORTS through run_default_notes() what each station's parse
carried, so a default that is dropped is visible to a curator instead of vanishing. The notes join
the build report's conditioning row family, whose existing rows state the same thing about the
canonical-XML side ("is a library default ... NOT asserted by source").

Values, not fields: every predicate takes the parsed value and answers whether the SOURCE stated it.
That keeps the rule testable against a real parse rather than against a list of field names.
"""
from __future__ import annotations

# mt_metadata's MTime zero. It reaches a Run.time_period whenever the source carries no window, and
# it is a real timestamp in every other respect, which is why it needs naming.
MTIME_EPOCH = "1980-01-01"
# Run.id where the source declares none: the station name with a trailing sequence letter.
_SYNTHESISED_RUN_ID_SUFFIXES = "abcdefghijklmnopqrstuvwxyz"
# D9: the rr* channels are mt_metadata RUN DEFAULTS. Over the corpus EDIs the CHTYPE census carries
# no RRHX at all, so DEFINEMEAS cannot be their source and no source declares them.
_RUN_DEFAULT_COMPONENT_PREFIX = "rr"


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def asserted_run_id(value, station: str) -> bool:
    """A run id the SOURCE declared. mt_metadata synthesises `<station><letter>` from the station
    name, so an id that is exactly that is the library's, not the custodian's."""
    rid = _text(value)
    if not rid:
        return False
    stem = _text(station)
    return not (stem and rid[:-1] == stem and rid[-1:] in _SYNTHESISED_RUN_ID_SUFFIXES)


def asserted_sample_rate(value) -> bool:
    """Run.sample_rate defaults to 0.0 (undeclared). Only a positive rate is a source assertion -
    the same rule the catalogue's sample_rates_hz rollup already applies."""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def asserted_time(value) -> bool:
    """A time_period bound the source stated, i.e. anything but the MTime epoch."""
    text = _text(value)
    return bool(text) and not text.startswith(MTIME_EPOCH)


def asserted_instrument(obj) -> bool:
    """An Instrument (data logger, sensor, electrode) the source identified. The model fills
    manufacturer/id/type with empty strings and model/name with None, so identity is asserted only
    when one of the naming fields carries text."""
    if obj is None:
        return False
    return any(_text(getattr(obj, field, None))
               for field in ("manufacturer", "model", "id", "serial_number", "name"))


def asserted_resistance(obj) -> bool:
    """Channel.contact_resistance defaults to 0.0 ohms on both bounds. A resistance of zero is not a
    measurement, so only a positive bound is asserted. Magnetic channels carry no such attribute."""
    if obj is None:
        return False
    for bound in ("start", "end"):
        try:
            if float(getattr(obj, bound, 0.0) or 0.0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def is_run_default_component(component) -> bool:
    """True for a component mt_metadata adds to every run rather than reading from the source."""
    return _text(component).lower().startswith(_RUN_DEFAULT_COMPONENT_PREFIX)


# The reported layer. One note per default the parse carried, station-independent text so the build
# report's shared aggregation groups them by distinct note across the survey.
_RUN_ID_NOTE = ("run.id: mt_metadata synthesises '<station>a' where the source declares no run id "
                "- NOT asserted by source")
_SAMPLE_RATE_NOTE = ("run.sample_rate: 0.0 is a library default - the source declares no run rate; "
                     "NOT asserted by source")
_TIME_NOTE = ("run.time_period.{bound}: the {epoch} MTime epoch is a library default - the source "
              "declares no acquisition window; NOT asserted by source")
_DATA_LOGGER_NOTE = ("run.data_logger: empty manufacturer/model/id are library defaults - the "
                     "source names no logger; NOT asserted by source")
_RESISTANCE_NOTE = ("run.channels[].contact_resistance: 0.0 ohms is a library default, not a "
                    "measurement; NOT asserted by source")
_RR_NOTE = ("run.channels[]: the rr* remote-reference channels are mt_metadata run defaults, not "
            "acquired channels; NOT asserted by source")


def run_default_notes(tf) -> list:
    """The presence notes for one parsed transfer function, in inventory order. Empty when the
    source states everything (no corpus station does today). Defensive against model shape drift:
    an attribute the pinned library stops carrying yields no note rather than an exception, because
    a parse must never fail over its own reporting."""
    station = _text(getattr(getattr(tf, "station_metadata", None), "id", None))
    notes = []

    def note(text):
        if text not in notes:
            notes.append(text)

    for run in (getattr(getattr(tf, "station_metadata", None), "runs", None) or []):
        try:
            if not asserted_run_id(getattr(run, "id", None), station):
                note(_RUN_ID_NOTE)
            if not asserted_sample_rate(getattr(run, "sample_rate", None)):
                note(_SAMPLE_RATE_NOTE)
            period = getattr(run, "time_period", None)
            for bound in ("start", "end"):
                if not asserted_time(getattr(period, bound, None)):
                    note(_TIME_NOTE.format(bound=bound, epoch=MTIME_EPOCH))
            if not asserted_instrument(getattr(run, "data_logger", None)):
                note(_DATA_LOGGER_NOTE)
            for channel in (getattr(run, "channels", None) or []):
                if is_run_default_component(getattr(channel, "component", None)):
                    note(_RR_NOTE)
                elif (hasattr(channel, "contact_resistance")
                      and not asserted_resistance(channel.contact_resistance)):
                    note(_RESISTANCE_NOTE)
        except Exception:  # noqa: BLE001  (model shape varies across mt_metadata versions)
            continue
    return notes
