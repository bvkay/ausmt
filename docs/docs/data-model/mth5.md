# MTH5 Integration

MTH5 is the HDF5-based container developed by the international MT community alongside mt_metadata.
It stores time series, transfer functions, survey and station metadata, processing information and
provenance in one self-describing file.

## Why AusMT uses it

EDI is the exchange format most interpretation and inversion workflows expect, and it was never designed
to carry the full record around a dataset: survey metadata, processing notes, provenance and publication
links end up stored separately and lost separately. MTH5 keeps that material together in a structured,
machine-readable form, interoperates with mt_metadata, MTpy, Aurora and the processing tools that follow
them, and is the better bet for remaining readable decades from now. That makes it AusMT's preferred
long-term archival format.

That is a preference, not a deprecation. Much of the MT archive is EDI, EMTF XML and project-specific
formats, and AusMT does not require anyone to migrate.

## What AusMT does with it

MTH5 is an accepted submission input for transfer-function products only, never raw time series.
Separately, the build generates transfer-function-only MTH5 download products at two granularities: one
file per survey (`bundles/<slug>-tf.h5`, gated by `flags.survey_h5_enabled`) and one file per served
station (`h5/<slug>/<station>.h5`, gated by `flags.station_h5_enabled`). Both flags ship set to `true`.
The same writer produces both, so a station reads identically out of either. Where a package holds
several representations of the same survey, they must describe the same transfer functions.

The package layout is in [Survey package](survey-package.md), the formats are compared in
[Transfer functions](../science/transfer-functions.md), and reading a served bundle is in
[Tool integration](../interoperability/tool-integration.md). Time-series pointers are covered in
[External archives](../interoperability/external-archives.md).
