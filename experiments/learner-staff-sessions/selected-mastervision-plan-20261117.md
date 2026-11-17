# Selected Master Vision contact migration

The owner supplied three overlapping contact exports. Only their union of source
IDs is authorized now; the previously paused general MV and IOMP jobs stay paused.
MVC is not a destination. Never merge different source IDs by email or phone.

## Acceptance

- Stream all three CSVs unchanged, validate every row, union positive integer IDs,
  bind the private selection to source hashes and an ordered-ID fingerprint.
- Prove archive coverage and current destination presence before writing.
- Apply only this selection from the existing encrypted MV API archive, preserving
  source IDs, native password imports, no-marketing flags and social identifiers.
- Keep an independent resumable ledger and STOP; acquire the general MV writer
  lock to avoid concurrent importers. Preserve every prior STOP.
- Fetch fresh individual API cards for their own personal URLs, encrypt complete
  profiles and URLs on the MV server; do not trust URLs in list responses.
- API key only in masked entry and stdin pipes/RAM; no source mutations or email.
- Existing accounts retain passwords and manually assigned permissions; fresh
  opt-outs may only tighten the no-marketing flag. Contact-only identities remain
  distinct when email is absent/shared. Raw profiles retain fields without UI mapping.
- Stop/retry safely on queue pressure, disk reserve, malformed data, or ten
  consecutive problems. Report application and link collection separately.
- Read back native records and report exact selected presence. Published scripts
  and manifests must match deployed scripts; private data is excluded from Git.

## Choice and limits

Reusing the completed source archive avoids another full export and laptop spool.
The existing native importer already validates password read-back and queue limits.
A scoped extension is smaller than a second importer and gives the paused general
job no new authority. Individual links still require one API request per ID.

Alternatives rejected: resuming the 563k general importer exceeds current scope;
matching CSVs by email loses independent IDs; mass-resetting existing passwords
would overwrite user changes. Link capture does not itself implement Frappe login
redemption, and contact-only records do not imply a working Website User account.

## Verification

Synthetic parser, source identity, bounded selection, transaction, encrypted profile,
secret rejection and scoped execution tests; then a small live selected batch,
native/read-back audit, published release/hash check, background launch and progress.
No Docker image build, added layer or app-container restart is required.
