# Selected Master Vision migration: startup verification

## Scope and inputs

Three owner-supplied, unchanged CSV exports contain 300,548 rows and 269,196
distinct positive source IDs. There are 31,352 extra cross-file occurrences and
28,806 IDs appearing in multiple files. No invalid IDs, within-file duplicates,
or row-width errors were found. The private manifest retains exact source hashes.
Neither the CSVs, contact IDs, passwords nor personal URLs are in this repository.

The completed encrypted MV API contacts resource contains all 269,196 selected
IDs. Before this task the destination had 17,574 selected identities (17,571
Users and 3 standalone Contacts), leaving 251,622 identities to add. No general
MV/IOMP collection or application STOP was removed. MVC was not modified.

## Published and deployed

- Initial scoped release: `d0404978f703a84edf9c4faf60e74f68faee999d`.
- Accelerated application release: `e5b960aabbed3fed13b064b7840c3bb27a771a8d`.
- Individual API dependency release: `8256ed1d520cd77d7eddfe5cecd1bb2d99c3c74e`.
- GitHub tree creation matched the local committed tree before non-forced branch
  updates. The installed five-file manifests/hash checks passed on the MV server.
- Local checkout and published accelerated commit were synchronized. No Docker
  rebuild, additional image layer or app-container restart was performed.

## Checks performed

79 targeted synthetic tests passed: CSV union/source mutation checks, native
identity/transaction boundaries, scoped execution, encryption, secret rejection,
positive opt-out preservation and recovery after a committed native creation.
After removing delay from already imported identities, the 25 directly affected
worker/selection tests passed again. Queue/disk gates remain on native writes.

The selected background writer is running under its own resumable ledger and
the shared MV writer lock. A live snapshot showed 237 recorded new Users and
17,574 preserved identities; native destination counts had already advanced to
17,811 Users and 3 Contacts. Zero failed/deferred decisions were present. The
default native queue temporarily reached its throttle threshold; this is a wait,
not a discarded contact or failed import. A later actual MCP count was 18,033
MV Users, confirming that progress continued independently of the laptop turn.

Five newly created Users were read back by exact source account and ID. Profile
fields, native password hashes, encrypted support-password presence, and disabled
welcome emails all passed. No passwords, names, emails or URLs were output.
The actual MV MCP identity guard reported active on `my-lk.mastervision.su`.
Both general MV and IOMP application STOP markers were still present.

## Remaining work and boundaries

This is startup verification, not a claim that all 269,196 identities are already
present. The detached application keeps working with queue and free-space checks.
Individual link/profile capture awaits the owner entering the MV GET key in the
masked local window. That key is not persisted. Full fresh API profiles and verified
individual links will be encrypted on the MV server, not spooled onto the laptop.
Capturing legacy URLs does not by itself activate login redemption in Frappe.

New accounts receive source passwords through the existing native import path.
Existing account passwords/roles are preserved; fresh no-marketing flags can only
tighten suppression. Unmapped API fields remain in the encrypted source archive;
this task does not claim that every AVO field already has a Frappe UI widget.
