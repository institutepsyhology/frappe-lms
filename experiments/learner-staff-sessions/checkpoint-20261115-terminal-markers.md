# Live checkpoint and terminal-marker repair

The first legacy API traversal reached all 26 configured resources. The parser
did not recognize the provider's exact end response: `No items where found for
model <b></b>`, or the same tag containing the endpoint's model name. Consequently
completed source traversals were conservatively labelled partial/invalid_json.
No accepted page or contact data was lost.

The parser now accepts only this exact wrapper and preserves model-to-resource
checks; unrelated HTML and foreign model names still fail closed. 73 synthetic
tests pass. The saved end responses were decrypted locally and matched, then
page continuity, total row counts, ID counts and snapshot provenance were
verified before 22 statuses were reclassified (17 nonempty, 5 empty/inferred).
Original source responses remain intact; local audit events record the repair.
The repair is idempotent; its immediate second run changed zero records.

Selected saved source totals:

| Resource | Rows |
| --- | ---: |
| Contacts | 213,885 |
| Employees | 37 |
| Courses | 972 |
| Course-access rows | 96,727 |
| Invoices | 53,613 |
| Invoice lines | 53,617 |
| Products | 1,817 |
| Newsletter groups | 736 |
| Contact-tag links | 12,919 |

Four resources need separate handling: contactnewsletterlinks timed out,
telegrambotcontactlnk returned HTTP 500, and funnelcontact/callcenterrequest
returned HTTP 404. No successful export of these four is claimed.

Before the local reclassification, the original process reached the end,
declined to start personal-link collection from the partial contacts status,
and discarded its in-memory GET key. Resume therefore requires a new masked
key entry. Completed resources will be reused; the two source-error resources
can be retried, followed by individually verified personal links. AVO and
Frappe records were not changed by this repair.
