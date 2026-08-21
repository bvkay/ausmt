# Why identifiers carry a data level

Dataset-level DOIs, handles and URLs are recorded in one list, `related_identifiers[]`. Each row states
what the identifier points at using the NCI Table 1 data-level terms, and the DataCite relation is
derived from that level rather than typed by hand. The vocabularies and the row shape are in
[survey.yaml](../reference/survey-yaml.md#6-identifiers-by-data-level).

AusMT is a curator, not a minter. It issues no DOIs, so almost every identifier a survey carries points
at somebody else's record: an NCI collection, a raw time-series deposit, a state geological survey
landing page, a GA eCAT entry. A named slot per relationship cannot describe those, because the same
identifier legitimately plays different roles for different surveys, and one value in two slots makes
a corpus look like it holds dataset DOIs it does not hold.

Typing the pointer describes them all. A row says what the identifier is (`identifier_type`), what it
points at (`identifies`), and who holds it (`custodian`), and it scales to relationships nobody has
thought of yet without a schema change.

Deriving the relation from the level puts the question where the knowledge is. Curators know what a
DOI points at, because they can read the landing page; few know whether that makes the AusMT record
`IsDerivedFrom` or `IsVariantFormOf` the target. A hand-edited file can still set the relation
explicitly, and if it disagrees with the derived value the validator says so and leaves the explicit
value alone.

The level vocabulary is fail-closed for the same reason the credit roles are: an out-of-vocabulary
level publishes a wrong provenance claim about somebody else's data.

The vocabularies and their fail-closed behaviour are written out in the survey validator, a pinned copy
of which is at
[`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py).
