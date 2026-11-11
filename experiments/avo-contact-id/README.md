# Contact cards by AVO ID

The `/lms/settings/contacts/<AVO ID>` route resolves the account from the
current site and requires permission to manage contact cards. It rejects an
ambiguous ID. Legacy member URLs still work, and users without an AVO ID keep
their existing routes. Existing Frappe User names and linked records are not
renamed. Imported Contacts without a User use the same route.

On 2026-11-11 the guarded release activated image
`sha256:b43a6d9392ee940bf7f4a74b680ae2e06e400865d505e1e81096821e2217e099`
over `sha256:0a0344aa29de64cee4d02ae9e848dd98bf4b915be6284f639a630fa1111e7b8a`.
The image built from source commit `55c646fab332a4678fa9e9f5868c1180e7a8d4fe`
and the Dockerfile memory adjustment in `d0bd2086`. Four resolver unit tests
and 24 frontend tests passed. All three sites returned healthy, document
counts did not decrease, and integrity-checked database backups were saved
before switching. The running import workers resumed after the switch.
Live MCP resolved an existing User and an unlinked Contact on MV-Centr; an
unauthenticated request to the resolver returned HTTP 403. The route returned
HTTP 200, but visual browser testing was unavailable because browser control
failed to start. This does not establish that all no-email contacts have been
imported or that every linked document has been exercised through the UI.
