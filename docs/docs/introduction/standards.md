# Standards and Alignment

AusMT invents no formats or identifier systems. It aligns with the research-data and MT-domain
standards the community already uses, so its records interoperate with existing identifier
infrastructure, repositories and software. The portal's About page carries the same material in
summary form.

## Persistent identifiers

AusMT records and carries through DOI (dataset and publication), ORCID (researcher), ROR (organisation)
and RAiD (research activity) identifiers. Where a survey supplies them, they travel with the record into
discovery so that custodians, investigators and funders are credited.

## FAIR and CARE

The discovery, metadata and provenance model is designed against FAIR (Findable, Accessible,
Interoperable, Reusable). CARE (Collective benefit, Authority to control, Responsibility, Ethics) is
supported by recording a survey's CARE fields and having a curator review them at publication. There is
no automated CARE enforcement; see [Scientific Philosophy](scientific-philosophy.md).

## MT-domain standards

- EDI and EMTF XML: the transfer-function exchange formats.
- mt_metadata: the community MT metadata model and the sole parser stack.
- MTH5: the community MT data container and the preferred archival format.

[Transfer functions](../science/transfer-functions.md) says what each format carries and
[MTH5 integration](../data-model/mth5.md) says how MTH5 is used.

## Interoperability between portals

AusMT emits an MTCAT discovery document: one JSON file describing every survey, so that another
repository can discover AusMT's holdings without exchanging the scientific data. The schema declares its
version in its `title` and every document declares the version it was written against in
`portal.version`; read it from there. See the [MTCAT schema reference](../reference/mtcat-schema.md).
