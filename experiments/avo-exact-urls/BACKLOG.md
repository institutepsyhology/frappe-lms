# Follow-up issues

## AVO-URL-001 - Guest app menu requests a staff-only endpoint

Status: open, low priority; outside URL compatibility change.

A cookie-free visit to either `/lms/courses` or a protected AVO lesson URL starts
`frappe.apps.get_apps` from `frontend/src/components/Sidebar/UserDropdown.vue`.
That endpoint correctly rejects guests, but the automatic resource request emits
an unhandled PermissionError before the protected route finishes redirecting to
login. The login page itself has no error. Actual form login and exact return
addresses were verified successfully.

Suggested fix: load the app switcher resource only for an authenticated session,
while preserving ordinary public course browsing. Add a guest startup regression
check. Do not change the endpoint permission to allow guests.
