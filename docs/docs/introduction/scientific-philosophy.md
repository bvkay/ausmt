# Scientific Philosophy

AusMT exists because of practical problems in reusing MT datasets, and most of those problems are not
technical: data, metadata, processing history and scientific context are preserved separately, when
they are preserved at all. The decisions below follow from trying to keep them together. The survey,
not the file, is the unit AusMT publishes and cites (see the [home page](../index.md)).

## Transfer functions, not time series

Time-series archives are large and need infrastructure built for them, which NCI and institutional
repositories already provide. Transfer functions are what the MT community exchanges, interprets,
publishes and reuses, and for many older surveys they are the only surviving products. Concentrating on
them lets AusMT cover historical and current datasets without duplicating archival infrastructure.

## Metadata is data

Where the station was, when it was recorded, which instruments were used, whether remote reference was
applied, which software processed it and at what version: without those a transfer function may be
impossible to interpret. Metadata and [provenance](../data-model/provenance.md) are first-class products.

## Reproducibility where possible

Historical datasets were processed with software that no longer runs, through workflows nobody wrote
down. AusMT does not require perfect reproducibility. It requires enough recorded information that a
future researcher can understand the products and regenerate them where that is still possible.

## Interoperability over reinvention

The MT community maintains EDI, EMTF XML, MTH5 and mt_metadata. Where an established standard solves a
problem adequately, AusMT adopts it rather than inventing an alternative. See
[Standards and alignment](standards.md).

## Curation over open upload

Submissions pass validation and human review before publication, which is how metadata completeness,
provenance, licensing and collection consistency are kept. The purpose is not to restrict access; it is
to make what is published usable later.

## CARE

AusMT supports FAIR and CARE. CARE support today means `survey.yaml`'s `care.*` fields are recorded and
surfaced to reviewers. There is no automated enforcement: a curator reads and acts on them during
review, and nothing in the pipeline blocks publication on their content.
