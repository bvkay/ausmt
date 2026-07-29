# Science Products

## Overview

Transfer functions are the primary scientific products published by AusMT.

Most other products available through the portal are derived from transfer functions and should be regarded as diagnostic or interpretive products rather than primary scientific observations.

## Primary Products

- EDI
- EMTFXML
- MTH5 transfer-function representations

## Derived Products

**Implemented today** (parsed with `mt_metadata` and computed by the engine into the served data
products):

- Apparent resistivity and phase, with per-period error bars where the EDI supplies them
- Phase tensor, per-period parameters
- Tipper, magnitude and full complex components
- The dimensionality screening diagnostic and the median skew
- Selection-level strike rose, drawn in the browser from served phase-tensor azimuths

What the station drawer renders today is the four response plots: apparent resistivity, phase,
phase tensor, and Parkinson-convention induction arrows. The per-station screening panel that
displayed the dimensionality class, the median skew and the strike estimate is hidden pending a
design review of how those numbers should be presented. The values themselves are unchanged: they
are still computed, still served in `sci.json` and the per-station products, and still ride the
CSV and GeoJSON exports.

**Planned** (scaffolding exists in `engine`, intended for the MTpy-v2-backed advanced
layer; not yet generated — do not assume these are present):

- Strike analyses
- Distortion / decomposition products (Groom–Bailey, etc.)
- Quicklook image products

These products assist interpretation but do not replace the underlying transfer functions.

## Portal vs Survey Package

Derived products are primarily a portal capability.

The survey package remains centred on transfer functions, metadata and provenance.

## Principle

Transfer functions are authoritative.

Derived products provide context.
