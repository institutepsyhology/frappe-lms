# Other-field audit and API coverage, MV-Centr

Owner requested checking other migrated data and considering a full API export,
including employees. Read-only audit; no bulk data correction was applied to
Frappe. A changed source password is a normal source update, not automatically
a migration defect.

## Existing contact archive

All 2,139 raw list pages, 213,874 saved contacts and 45 returned fields were
checked. Field sets are consistent. The page-wide repeated nonempty, nondefault
value defect was found only in `link_personal_auth`.

| Field | Nonempty records | Pages containing different values |
| --- | ---: | ---: |
| password | 213,874 | 2,139 |
| email | 203,489 | 2,139 |
| name | 45,545 | 2,138 |
| last_name | 33,515 | 2,138 |
| middle_name | 2,844 | 1,598 |
| phone_number | 54,816 | 2,138 |
| telegram_user_id | 59,366 | 2,133 |
| vk_user_id | 5,732 | 1,169 |

Other whole-page constants are empty/default values, including boolean flags.
There is no comparable nonempty last-row copying signature for unsubscribe/spam
flags. Full original-page vs saved `api_data.list`, selected-profile fields,
password copies and ID-order comparisons found zero preservation mismatches.

One archived individual-card response agrees in 43/45 fields with its list row,
including password, email, names, phone and social IDs. Differences are the
personal login link and `partner_set_date`; the latter's cause is not established
from one sample. The fresh three-card preflight concerns link ownership only.

These checks prove archive preservation and rule out this specific systematic
pattern for other fields. They do not prove current per-contact correctness,
Frappe persistence for all fields, or employee/permission coverage.

## Confirmed documented interfaces

| Category | Legacy API/official SDK | Limitation to verify |
| --- | --- | --- |
| Contacts | contacts | Actual field completeness, changed/deleted/new records |
| Employees | employee | Login, contact link, status; not full role matrices |
| Invoices/purchases/products | accounts, accountline, goods, ContactRecurringPayments | Full payment-attempt history not established |
| Groups/subscriptions | newsletter, contactnewsletterlinks | Complete attribution/history not established |
| Courses | training | Complete course settings not established |
| Course/lesson assignments | trainingAccess | GET round-trip of every date, freeze and lesson field must be checked |
| Tags | contacttaglnk | Complete tag dictionary not established |
| Telegram/funnel participation | telegrambotcontactlnk, funnelcontact | Full builder definitions not established |
| Advertising | advertisingchannelcompany, advertisingchannel, advertisingchannelstatistics | Full UTM/touch history not established |

Public sources do not establish complete export of staff position trees/CRUD
matrices, employee passwords, lesson-builder blocks, homework answers,
progress/tests/certificates, or all outgoing-message history. This is a
documentation gap, not proof that no other API supports them.

The newer Data Export API documents Bearer authorization, a `/v1/schema`
discovery endpoint and schema-dependent `/v1/{resource}` reads at
`data-api.autoweboffice.ru`. An account's actual resource/column list must be
retrieved before promising full coverage. A legacy GET key must not be assumed
to work as a Data Export bearer token. Public documentation does not establish
an asynchronous export-job API.

## Recommended collection contract

1. Capture the account's schema and resource availability first. Keep MVC/MV/IOMP
   archives and credentials separate.
2. Export supported resources as separate resumable script jobs, preserving
   source field types, IDs and raw original responses. Sensitive snapshots stay
   encrypted/private; never publish them to GitHub.
3. Validate IDs, duplicate rows, page boundaries, required fields, relationships
   and list-vs-detail sample comparisons. A nonempty field alone is not proof.
4. Produce per-resource status: complete/partial/access denied/interface not
   established, with counts, fields, capture time and outstanding gaps.
5. Compare the new snapshot with Frappe and the prior archive; plan scoped
   updates rather than silently overwrite current roles/passwords/accesses.

Sources:

- https://autoweboffice.com/help/ru/api/api-akkaunta-na-platforme-avtovebofis
- https://github.com/AutoWebOffice/AwoApi
- https://github.com/AutoWebOffice/AwoApi/blob/master/AwoApi.php
- https://autoweboffice.com/guide/data-export-api.html
