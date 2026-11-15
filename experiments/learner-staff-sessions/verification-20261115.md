# MV-Centr legacy personal-link audit, 15 November 2026

## Current result

The local contacts archive preserves the API's `link_personal_auth`, but most
list-row associations are unsafe for authentication. Do not import them as
person-specific login credentials. No production authentication, contact,
password, role or course data was changed by this audit.

| Full archived SQLite check | Count |
| --- | ---: |
| Contact records checked | 213,874 |
| Nonempty links with expected host/path/query format | 213,874 |
| URL UID matches the row's source contact ID | 2,139 |
| URL UID differs from that source contact ID | 211,735 |
| Additional cross-contact repetitions of a token | 211,735 |
| Raw saved API pages | 2,139 |
| Pages repeating the last contact's link in every row | 2,139 |
| First/last raw-row comparisons with saved contact copies | 4,278 |
| Preservation mismatches in those comparisons | 0 |

Format, without real credential values:
`https://shop.mv-centr.ru/personal/auth/secure-login?uid=<contact>&vc=<opaque>`.

The source profile ID agrees with the SQLite key throughout. The convenience
link, original auth field and raw list field agree; the problem already exists
in the source list response. The exporter fetched individual details only when
password/link were empty, so its presence check did not catch this problem.
This finding concerns login-link association; it is not evidence that other
profile fields were mismapped.

One separate archived single-contact API response has a matching UID and a
different link from the list response for that same contact. This establishes a
useful next probe, not proof that all current individual responses are correct.
The archive is an October capture; no link was redeemed and current validity
has not been tested.

## Reproducible safe checks

`audit_legacy_links.py --database <private contacts.sqlite>` performs a streaming,
query-only pass and prints aggregate counts/status codes. The audit exits 1 on
this archive because the credentials fail association checks. It performs zero
network calls and does not change the archive.

`collect_personal_links.py` is a three-card live preflight utility, not a bulk
repair worker. It takes `--source-database` and a new `--output-directory`, asks
for the account's GET key in a masked local window, and reads only three
individual contact cards. It blocks redirects and wrong-account key URLs,
checks response contact ID and URL UID, stops on the first invalid response,
and saves only verified URLs/provenance in a separate private SQLite file.
URLs are encrypted with current-user Windows DPAPI and bound to the source
contact ID; they are not stored as plain text. The output file is created
exclusively. Moving the archive to a server requires deliberate local decryption
and re-encryption for that destination; the Windows ciphertext is not portable.
It neither opens login links nor writes to Frappe. The key and returned profile
fields/passwords are never stored. Its safe report contains no source values.

17 synthetic unit tests pass, including the source-page repetition regression,
wrong-account/wrong-UID rejection, encoded URL preservation, separate private
output, no source writes, no password/key/profile leakage, no overwriting of a
previous output and redaction of exception text. The additional checks cover
actual DPAPI round-trip/tamper/wrong-contact rejection, encoded API-key leakage,
and invalid source IDs being rejected before any network call.

## Requirements recorded

- One shared hostname: my-lk now, shop after the final cutover.
- `/personal` learner portal and `/shop` staff portal; concurrent independent
  sessions/passwords and separate learner-login vs read-only staff-preview links.
- Owner selected repeated learner-link login until explicit revocation;
  blocked accounts remain denied.
- Preserve a verified source key/path/query; never infer ownership from an
  unverified row or manufacture a replacement by editing the UID.

The Frappe contact import code reviewed does not pass these link fields. No
production DB scan of secret values was needed or performed. Native Frappe
still has one common session; same-host realm isolation and legacy-link
redemption have not been deployed by this preparatory work.

## Fresh individual-card preflight

The owner entered the account's GET key in the local masked window. Exactly
three individual contact cards were requested: three response-ID/link-UID
checks passed, zero failed. Only their verified links and provenance were
stored in the separate Windows-user-encrypted local archive. Read-back confirms
all three DPAPI decryptions work and the plaintext login path is absent from
the database bytes. No login links were opened; no AVO/Frappe records or
credentials were changed. The process exited and the GET key was not stored.

This proves the individual-card retrieval path for three contacts. It is not
bulk completeness, successful Frappe authentication, or a guarantee that every
historical email/bot key has been captured.

One previously saved individual response can be matched to the fresh captures.
For that same contact the origin, path and UID are unchanged, but `vc` differs.
This is evidence that captured key versions can change between observations;
it does not establish a rotation schedule, invalidate the old key, or prove
that API reads themselves rotate keys. Preserve separately captured versions.

## Resumable bulk link worker prepared

`collect_personal_links_bulk.py` adds the full individual-card collection mode.
44 synthetic tests pass across the preflight, DPAPI and bulk modules. The worker
checks every source ID/account before asking for a key, keeps the key only in
memory, appends encrypted versions and commits link/success/audit together.
It writes an atomic aggregate progress report, supports STOP/resume, respects
retry delays and prevents concurrent writers. It stops after ten consecutive
ordinary failed contacts, or immediately on authentication, structure, UID,
secret-leak or encryption errors. A wrong link is never marked as a success.

The three-card verified archive can seed a new bulk run after decryption and
revalidation. Historical list captures are not treated as fresh individual-card
verification. The bulk worker has not been launched against the live API;
the only live requests so far were the three-card preflight. Broader resource
snapshot collection is being prepared following the owner's new instruction.

## Full legacy-resource archive utility

The new `legacy_api_snapshot.py` collects the 26 documented legacy resource
names available to the MVC GET key. It compresses/encrypts raw source responses,
records per-resource coverage, preserves failed-page evidence without advancing
the success cursor, and builds a separate numeric-IDs-only contact index.
Optional individual-link collection reuses the key in memory after the other
resources, with independent progress and correct failure propagation. The GUI
provides progress, Stop and completion/failure notification. No new Data Export
host or credential is used.

72 synthetic tests pass across the archive and link modules. Independent review
findings were fixed and regression-tested: provider backoff applies even after
the final attempt; interrupted HTTP bodies are retryable; 403/404 after a saved
prefix is partial; undecodable bodies cannot persist an unchecked encoded key;
explicit foreign source metadata is rejected; and a wrong-model empty marker
cannot complete another resource. Tests use no real account data or network.

The complete archive utility is ready for its first live run. It still needs
the GET key entered in its own masked window because the separate three-card
preflight process exited without storing that key. No full live run is claimed
by the tests or by this preparation receipt.

## Full archive run started

The owner entered the GET key in the full collector window. The running process
uses the published `d725c689` collection source. At the live read-back check it
had saved 20,397 contacts, made 205 requests, reported zero consecutive errors,
and was continuing the contacts resource; other resources/link phase were still
pending. These are a checkpoint, not a completeness claim.

Three persisted pages (0, 101, 202) were decrypted locally for metadata-only
verification. All 300 rows had matching stored counts, unique source IDs,
matching encrypted snapshot provenance and entries in the separate contact-ID
index. Each page had only one correct row-to-personal-link UID association,
confirming the source list-link defect in the current live API too. Raw list
links remain untrusted; the later individual-card phase is required.

No source values were printed/published. Frappe and the AVO records were not
modified. The live count/progress file in the private output folder is the
authority for subsequent status; the application continues without model calls.
