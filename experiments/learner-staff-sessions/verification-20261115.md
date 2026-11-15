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
