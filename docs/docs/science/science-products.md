# Science Products

Transfer functions are the primary products; everything else the portal shows is derived from
them and is diagnostic rather than observational. This page is the authoritative list of what
is implemented and what is planned. Other pages defer here for that status.

## Primary products

EDI, EMTF XML and MTH5 transfer-function representations. See
[Transfer functions](transfer-functions.md).

## Derived products

**Implemented today**, parsed with `mt_metadata` and computed by the engine into the served
data products:

- Apparent resistivity and phase, with per-period error bars where the EDI supplies them
- [Phase tensor](phase-tensor.md), per-period parameters
- Tipper, magnitude and full complex components
- The [dimensionality](dimensionality.md) screening diagnostic and the median skew
- Selection-level [strike](strike-analysis.md) rose, drawn in the browser from served
  phase-tensor azimuths
- The [`q` screening scalar](quality-metrics.md#the-q-screening-scalar)

The station drawer renders four response plots: apparent resistivity, phase, phase tensor, and
Parkinson-convention induction arrows. The per-station screening panel that displayed the
dimensionality class, the median skew and the strike estimate is hidden pending a design review
of how those numbers should be presented. The values themselves are unchanged: still computed,
still served in `sci.json` and the per-station products, and still carried by the CSV and
GeoJSON exports.

**Planned.** Scaffolding exists in `engine`, intended for the MTpy-v2-backed advanced layer,
and is not yet generated. Do not assume these are present:

- [Strike analyses](strike-analysis.md)
- [Distortion and decomposition products](distortion-and-dimensionality.md) (Groom-Bailey and
  related)
- Quicklook image products

Derived products are a portal capability. They are never written back into the survey package,
which stays centred on transfer functions, metadata and provenance, so they can be regenerated
and improved without touching the published record. The file shape each product must take is in
[Portal data files](../developer/data-files.md#derived-product-files).
