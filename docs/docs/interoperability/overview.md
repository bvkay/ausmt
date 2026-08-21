# Using the data

Australian MT data already exists in universities, agencies, geological surveys, research
infrastructure facilities and industry, held in institutional repositories, national archives, project
websites and local systems. The problem is rarely that the data are missing; it is that they are hard
to find, understand and reuse. AusMT's operating principle:

> Repositories remain independent. Discovery becomes shared.

An organisation keeps its own infrastructure, governance and practices, and still participates in a
shared discovery layer. What gets exchanged is descriptions of datasets, not the datasets themselves,
which is why AusMT adopts existing formats and identifier systems instead of defining its own; see
[Standards and alignment](../introduction/standards.md).

## The three practical pages

- **[How AusMT serves data](api-overview.md)**: read-only static JSON behind an ordinary file server;
  caching, CORS and integrity; how access levels and embargoes appear to a consumer; what deliberately
  does not exist.
- **[Data reference](api-reference.md)**: every served document, its shape, and worked fetch patterns
  (whole-survey bundles, per-station downloads through the manifest, bounding-box selection).
- **[Tool integration](tool-integration.md)**: reading the three distributed formats in MT software,
  harvesting MTCAT, and the sharp edges.

[External archives](external-archives.md) covers what AusMT does not hold and how it records links to
the repositories that do.

## Where the layers sit

```text
EDI / EMTF XML / MTH5   ->   what is in the dataset
MTCAT                   ->   what datasets exist
```

Transfer-function formats say what is in a dataset. MTCAT says what datasets exist. Keeping the two
separate is what lets a repository publish discovery records without publishing its data, whatever
formats its holdings use. The discovery document AusMT emits is specified in the
[MTCAT schema reference](../reference/mtcat-schema.md).
