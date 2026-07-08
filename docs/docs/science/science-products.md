# Science Products

## Overview

Transfer functions are the primary scientific products published by AusMT.

Most other products available through the portal are derived from transfer functions and should be regarded as diagnostic or interpretive products rather than primary scientific observations.

## Primary Products

- EDI
- EMTFXML
- MTH5 transfer-function representations

## Derived Products

**Implemented today** (parsed with `mt_metadata`, computed by the engine, and shown in the portal):

- Apparent resistivity and phase, with per-period error bars where the EDI supplies them
- Phase tensor (per-period parameters and the dimensionality screening diagnostic)
- Tipper (magnitude and full complex components; induction arrows in the station drawer,
  Parkinson convention)
- Selection-level strike rose (drawn in the portal from served phase-tensor azimuths)

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
