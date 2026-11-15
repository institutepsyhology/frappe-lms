# Stream the current MVC collection to the MVC Frappe server

The owner cannot provide more laptop storage and explicitly requests immediate
delivery to MVC Frappe. Keep the running AVO reader and its in-memory key intact.
Use a separate small sender that reads only committed batches, decrypts locally
in memory, and sends over the existing host-key-verified SSH connection to the
fixed MVC backend. The receiving program encrypts with the existing MVC site
key and stores a versioned archive below that site's private directory, outside
the downloadable files tree. No learner login is redeemed and account settings
are not changed. This preserves source data for the separate authentication work;
it does not claim that old AVO login links already authenticate to Frappe.

Considered alternatives: restart the source with a new API key on the server
(unnecessary interruption); upload Windows DPAPI databases (not decryptable on
Linux); add a public HTTP endpoint/new application image (unnecessary scope).
The existing strict SSH transport and small sidecar solve storage without these.

Each batch is checked for source account, contact binding and content hash.
Server commit and independent decrypt/read-back precede acknowledgment. Retries
are idempotent; conflicting versions fail closed. Only after exact acknowledgment
may the sender atomically store a receipt and replace a local link ciphertext
with an explicit remote reference. Keep version rows, contact cursors and all
learning data. Ship existing fixed-size raw pages too; retain their local copy
while the parent job is open. Reuse freed SQLite pages, without VACUUM or copies.

Test bad/missing ACKs, retry after a lost ACK, server payload tampering, source
isolation, rollback, old archive resumption, and producer/sender concurrency.
Publish reviewed sources, run a small real batch, verify it independently on
the MVC site, then start the sender in the background and measure queue growth.
Ten consecutive transfer failures or critically low local space stop the reader
with a clearly logged reason. Never print private payloads, keys or URLs.
