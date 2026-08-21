# Science Products

Transfer functions are the primary products; everything else the portal shows is derived from them and
is diagnostic rather than observational. This page is the authoritative list of what is implemented and
what is planned.

## Primary products

EDI, EMTF XML and MTH5 transfer-function representations. See
[Transfer functions](transfer-functions.md).

## Derived products

Implemented, parsed with mt_metadata and computed by the engine into the served data products:

- apparent resistivity and phase, with per-period error bars where the EDI supplies them
- per-period [phase tensor](phase-tensor.md) parameters
- tipper, magnitude and full complex components
- the dimensionality screening diagnostic and the median skew, served in
  [`dimensionality.json`](../reference/station-products.md#2-dimensionalityjson)
- the selection-level [strike](strike-analysis.md) rose, drawn in the browser from served phase-tensor
  azimuths
- the `q` completeness-and-smoothness scalar, defined under
  [`station.json` diagnostics](../reference/station-products.md#18-diagnostics)

The station drawer renders four response plots: apparent resistivity, phase, phase tensor, and
Parkinson-convention induction arrows. The per-station screening panel that displayed the
dimensionality class, the median skew and the strike estimate is hidden pending a design review; the
values are still computed, still served in `sci.json` and the per-station products, and still carried
by the CSV and GeoJSON exports.

Planned, as scaffolding in `engine/ausmt_science/` that is not wired into the build:

- dedicated [strike products](strike-analysis.md) (`ausmt_science/strike`)
- distortion and decomposition products, Groom-Bailey and related
  (`ausmt_science/decomposition`, an optional MTpy-v2-backed stub)
- quicklook image products

Derived products are a portal capability. They are never written back into the survey package, so they
can be regenerated and improved without touching the published record. The file shape each product must
take is in [Per-station products](../reference/station-products.md#new-products).
