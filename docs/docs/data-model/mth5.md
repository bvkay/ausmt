# MTH5 Integration

MTH5 is an HDF5-based format developed by the international magnetotelluric community, closely
tied to the mt_metadata project. It stores time series, transfer functions, survey and station
metadata, processing information and provenance in one self-describing container.

## Why AusMT uses it

EDI remains the most widely used exchange format and is still what most interpretation and
inversion workflows expect. It was never designed to carry the full record around a modern
dataset, so survey metadata, processing notes, station detail, provenance and publication
links end up stored separately and, over time, lost separately.

MTH5 brings that material back together in a structured, machine-readable form. It aligns with
what AusMT is for: metadata preserved beside the products, provenance and lineage recorded well
enough to support reproducibility, and interoperability with mt_metadata, MTpy, Aurora and the
processing tools that follow them. A self-describing container is also the better bet for
remaining readable decades from now, which makes MTH5 AusMT's preferred long-term archival
format.

That is a preference, not a deprecation. Much of the global MT archive is EDI, EMTF XML and
project-specific formats, and many legacy datasets will stay that way. AusMT treats MTH5 as
part of an evolving ecosystem and does not require anyone to migrate: a package can improve its
representation over time, and historical and contemporary datasets coexist under one framework.

## What AusMT does with it

MTH5 is an accepted submission input for transfer-function products only, never raw time
series. Separately, the build generates transfer-function-only MTH5 download products at two
granularities: one file per survey (`bundles/<slug>-tf.h5`, gated by `flags.survey_h5_enabled`)
and one file per served station (`h5/<slug>/<station>.h5`, gated by `flags.station_h5_enabled`).
Both flags ship set to `true`. The same writer produces both, so a station reads identically out
of either. Where a package holds several representations of the same survey, they must describe
the same underlying transfer functions.

The package layout and the rules on accepted inputs are in
[Survey package](survey-package.md). The formats themselves are compared in
[Transfer functions](../science/transfer-functions.md), and reading a served MTH5 bundle in
practice is covered in [Tool integration](../interoperability/tool-integration.md).

MTH5 was designed to hold time series as well. AusMT does not, and its packages record
pointers to external time-series collections instead; see
[External archives](../interoperability/external-archives.md).
