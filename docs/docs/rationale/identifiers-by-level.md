# Why identifiers carry a data level

## What it is

Dataset-level DOIs, handles and URLs are recorded in one list, `related_identifiers[]`. Each row
states what the identifier points at using the NCI Table 1 data-level terms, and the DataCite
relation is derived from that level rather than typed by hand. The vocabularies and the row shape
are in [survey.yaml Reference](../reference/survey-yaml.md#identifiers-by-data-level).

## Why it is built that way

AusMT is a curator, not a minter. It does not issue DOIs, so almost every identifier a survey
carries points at somebody else's record: an NCI collection, a raw time-series deposit, a state
geological survey landing page, a GA eCAT entry. The old model had a separate flat slot for each
of those relationships, and the slots disagreed with each other. All seven AusLAMP South Australia
surveys carried the same NCI collection DOI as both `dataset_doi` and `time_series.collection_pid`,
because there was no slot for what that DOI actually identified. One value in two roles is not a
richer record. It is the same fact asserted twice, and it made the corpus look like it had dataset
DOIs it did not have.

The fix was to stop adding slots and start typing the pointer. A row says what the identifier is
(`identifier_type`), what it points at (`identifies`), and who holds it (`custodian`). That is
enough to describe every relationship the old flat keys tried to cover, and it scales to
relationships nobody has thought of yet without a schema change.

Deriving the relation from the level matters more than it looks. Curators know what a DOI points
at, because they can read the landing page. Very few curators know whether that makes the AusMT
record `IsDerivedFrom` or `IsVariantFormOf` the target. Asking for the level and computing the
DataCite relation puts the question where the knowledge is. A hand-edited file can still set the
relation explicitly, and if it disagrees with the derived value the validator says so and leaves
the explicit value alone.

The level vocabulary is fail-closed for the same reason the credit roles are. An out-of-vocabulary
level publishes a wrong provenance claim about somebody else's data, so it blocks.

Migration is not required to keep publishing. The retired flat keys and the deprecated `sources[]`
list are still read, and the warnings point at the migration scripts in `ausmt-surveys/_tools/`.

## Where the depth is

The ratified specification is cited from the code as `IDCONS`. The vocabularies and their
fail-closed reasoning are written out in the survey validator, a pinned copy of which is public at
[`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py).
The project's frozen design records live in
[`maintainer/`](https://github.com/bvkay/ausmt/blob/main/maintainer/README.md); identifier
consolidation was ratified as a spec rather than frozen as a C-series record, so there is no
C-number to cite here.
