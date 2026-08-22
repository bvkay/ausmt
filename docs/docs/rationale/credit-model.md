# Why the credit model has two lists

A survey records credit in two places. `creators[]` is an ordered list of the parties the citation
names, in author order. `contributors[]` is a repeatable list of who did what, and every row carries a
role from a fixed vocabulary. The field-by-field detail is in
[survey.yaml](../reference/survey-yaml.md#3-credit-creators-and-contributors).

Most Australian MT data reaches AusMT through a chain rather than from a single lab: a mining company
pays for a survey, a contractor collects it, a state geological survey holds it through an embargo and
releases it, a university reprocesses it years later. Asking which of those is the "principal
investigator" has no defensible answer, so the model does not ask. The citation needs an ordered author
list and nothing else, so `creators[]` is ordered and carries no roles. Attribution needs to say what
each party did, so `contributors[]` is unordered, repeatable and role-bearing. The same person can
appear once as a creator and three times as a contributor without either list becoming ambiguous.

The vocabularies are fail-closed: an unrecognised `name_type` or `role` blocks validation. A wrong role
publishes a false statement about who collected or owned a dataset, which is worse than refusing the
package.

Credit is optional. Omit `creators[]` and the citation falls back to an organisation-and-year
synthesis, which is the correct citation for most state-survey releases.

## Why the retired fields are gone rather than kept as fallbacks

`lead_investigator` and `principal_investigators` were retired when this model was ratified, but the
engine went on reading them into a back-compat `investigators` facet, and the public form went on
writing them. Both have now stopped.

Keeping a reader would have meant publishing a fact through two contradictory paths: a survey could
name one party in `creators[]` and a different one in the retired field, and which of them a given
consumer saw would depend on which path it read. The migration seeds the typed lists from the retired
values and deletes them, so the answer moves to the one place that has it. The served `investigators`
key went with the reader rather than being left in place as a key that is always empty, because a
documented field that can only ever be `[]` is a false promise.

The plain-language question that replaced the lead field is "Who led this survey?", and it writes one
`contributors[]` row with the role `ProjectLeader`. That is the same fact, said in the vocabulary the
rest of the model already uses, and it no longer competes with the citation.

## Organisations, and why a publisher is never inferred

People are only half of credit. `organisations[]` states what each body did, over a fail-closed
vocabulary: published, holds, distributes, collected, owns the rights, hosts. Australian MT data
usually arrives through exactly such a chain, so the roles are the honest way to record it.

One rule in that block is worth stating on its own: a publisher is never inferred. It would be easy to
assume the custodian also published the release, and it is often wrong: a state survey may hold data a
national agency published, or the reverse. Structured citation generation that needs a publisher fails
closed and says so, rather than naming a body that never made that claim. The same reasoning drives
`primary_custodian`: it is one explicitly curated flag, not "the first row in the list", because a
projection that depends on array order is a fact nobody chose.

The clearest single read is the editor's typed credit rows in
[`gateway/editor_form.py`](https://github.com/bvkay/ausmt/blob/main/gateway/editor_form.py). The
vocabularies and their fail-closed behaviour are enforced by the survey validator, a pinned copy of
which is at
[`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py).
