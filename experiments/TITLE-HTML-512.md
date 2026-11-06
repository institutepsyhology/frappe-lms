# Titles up to 512 characters with safe HTML

Work in progress; not a production release. Course and lesson title Data
fields are widened to 512 characters of stored markup. The migration
`lms.lms.avo_title_schema.execute` is site-scoped, rejects conflicting property
setters, widens only the two title columns, and requires verified backups.
Long imported course titles receive a deterministic account-scoped internal
name; source IDs and full source snapshots remain unchanged.

The frontend allows formatting and links in title views, safely removes active
markup and unsafe styles, and uses plain title text in breadcrumbs and browser
metadata. Navigational cards show formatted link text without nesting links.
Headings in lessons retain safe formatted links. Frontend tests and isolated
Vue compilation do not prove that production assets have been built or
deployed. Rendering and access checks remain required. The previous full Vite
build exhausted the 3 GiB Node heap; use a verified lower-memory build strategy
or suitable separate builder, not an unbounded build on the production host.
