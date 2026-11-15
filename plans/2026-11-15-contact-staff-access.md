# Contacts, staff authority and per-person course access

User-authorized implementation. The numeric contact/profile route update and
source-map build fix are already deployed separately. This work adds:

1. A single contact interface for linked Users and Contacts without logins.
   Basic contact read/write, password management and staff administration are
   distinct permissions. No synthetic email or source identity is created.
2. Separate employee and position screens. Non-administrators cannot edit their
   own authority. Delegation stays inside their position's subordinate tree;
   every child's actions and native LMS roles must fit the creator and parent
   ceilings. Technical framework roles are not delegated through this UI.
3. A server-paginated course roster: default 50, selectable 25/50/100/200,
   server-wide sorting in both directions, FIO/email/phone/access dates, numeric
   contact links, permission-gated removal and per-person access pencil.
4. One member/course access dialog reachable from roster and contact course
   list. General course settings retain only course defaults and schedule.
   Preserve progress/homework when rights change. Course blocking must not be
   bypassed by multiple grants; temporary blocks expire at request time.
5. Accurate access provenance. Original AVO issuer/cause/time remains unknown
   where missing from source; import/capture time is separately identified.
   New manual/import/purchase events must record their actual actor/time.

Implementation sequence:

- [x] Diagnose/rebuild numeric-route update without source maps; retain 51 layers.
- [x] Audit staff-mutation bypasses, roster, access engine and shared card.
- [x] Guard role changes/deletion in API, native User/Role hooks and evaluator.
- [x] Add delegated position model, permissions and employee/position screens.
- [x] Unify contact card and permission-filtered course list.
- [x] Replace roster load-more with bounded server pages and sorting.
- [x] Move personal rights to shared dialog; add pair-level blocking/provenance.
- [x] Test permissions through component tests and direct methods, page boundaries, source
      account separation, multi-grant deny behavior and timed unblock.
- [ ] Publish exact sources, back up sites, targeted schema reload, deploy with
      healthy-services/count checks and image rollback, verify actual MCP/HTTP.

Existing unrelated worktree edits are excluded. Browser-session extraction was
initially rejected. The owner subsequently explicitly authorized reading the
saved local session solely on shop.mv-centr.ru for position 37 and related
permission pages; those read-only requests succeeded. Private captures and the
82-group/280-option catalogue stay under exports/avo-role-reference, outside
Git. The empty source role is a structure example, not a permission assignment.
Its editor has a required parent position; supports CRUD, import/export,
own-record scope, section visibility and specialised restrictions. Only
implemented Frappe resources may expose working configuration controls.
Official reference: https://wiki.autoweboffice.com/doku.php?id=prava_dostupa .
