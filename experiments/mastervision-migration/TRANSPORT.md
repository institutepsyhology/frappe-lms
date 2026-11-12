# Isolated Master Vision acquisition

These helpers read only `https://shop.mastervision.su` and use the dedicated
Windows profile `exports/lesson-content/private-browser-profiles/mastervision`
under the AVO workspace, outside this repository. They do not reuse or alter the
MVC/IOMP collectors, profiles, queues, checkpoints or source databases. The
historical `mastervision.sqlite` sample is also left untouched.

## Interactive login

From the repository root, run only when the user is ready to sign in:

```powershell
node experiments/mastervision-migration/login.cjs
```

The helper resolves an already installed `playwright`, `@playwright/test`, or the
bundled Codex runtime, and opens a visible Microsoft Edge window. It does not
install dependencies or launch the collector. There is no login countdown.
After the authenticated admin grid is visible, a same-origin catalog GET with
redirects disabled independently confirms the login. Only then does the helper
close its isolated browser cleanly, flushing the persistent profile, and print
the fixed confirmation message. If confirmation fails, an open window is kept
open for the user to inspect and close. Do not run the HTTP worker concurrently
with this profile's login browser.

## Long-running JSONL transport

```powershell
node experiments/mastervision-migration/transport.cjs
```

Its private stdin/stdout contract is one serialized request and response per
line, with no startup messages or extra fields:

```json
{"url":"https://shop.mastervision.su/shop/training/admin/admin?lg=ru"}
```

Successful response: `{"ok":true,"html":"...original source HTML..."}`.
Failure response: `{"ok":false,"error":"fixed_code"}`, then exit code 1.
The caller must keep stdout in a private pipe/cache; HTML can contain personal
source data and must not enter public logs or Git. EOF after successful requests
exits with code 0. There is no automatic retry or write operation.

Only the catalog, course editor and lesson editor paths are permitted:

- `/shop/training/admin/admin`
- `/shop/training/admin/update`
- `/shop/training/traininglessons/admin/update`

The worker reads this profile once, opens its Cookies SQLite database read-only,
decrypts supported `v10` cookies in memory with the current Windows user's DPAPI
key, checks cookie host binding/metadata and expiry, and sends applicable cookie
paths only to the fixed HTTPS origin. Decrypted key buffers are cleared after
use. Unsupported encryption or an unavailable/expired session stops the worker;
it does not fall back to another profile. It never writes cookie values, keys,
raw exceptions, server error bodies or headers to logs. Same-origin redirects
also stop acquisition rather than silently returning a login page. A 200 HTML
login page must additionally be rejected by the caller's catalog/editor parser.

Every request is GET, with manual redirects, a 45-second timeout and a 32 MiB
response cap. Identity is checked before loading local secrets. Fixed failure
codes include `wrong_origin`, `unsupported_path`, `profile_unavailable`,
`session_not_found`, `session_expired`, `key_unavailable`,
`cookie_database_unavailable`, `cookie_format_unavailable`,
`cookie_host_mismatch`, `invalid_cookie`, `source_auth_error`,
`source_http_error`, `unexpected_content_type`, `source_timeout`, `source_size`
and `source_transport_error`. Every error ends the worker, so the controller
must inspect/log the code and deliberately choose whether to start a new one.

## Synthetic checks

```powershell
node --test experiments/mastervision-migration/test_transport.cjs
```

Tests use fabricated encryption/session fixtures and mocked HTTP responses;
they do not read the real profile, contact AVO, or open a browser. The installed
Playwright module is resolved without launching it. The tests cover source and
profile boundaries, host-bound v10 decoding, cookie scope/expiry, redirect and
size limits, the JSONL contract, one-time session loading, fixed errors without
secret leakage, and login-confirmation identity.
