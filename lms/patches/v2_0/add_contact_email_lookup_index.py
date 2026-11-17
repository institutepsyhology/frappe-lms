"""Cover Frappe's native Contact lookup without imposing email uniqueness."""
import frappe

INDEX = "lms_contact_email_lookup"
COLUMNS = ("email_id", "parenttype", "parent")


def _covered(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["Key_name"], []).append(row)
    for name, parts in grouped.items():
        parts.sort(key=lambda row: int(row["Seq_in_index"]))
        columns = tuple(row["Column_name"] for row in parts)
        complete = all(row.get("Sub_part") is None for row in parts[:3])
        if columns[:3] == COLUMNS and complete and int(parts[0]["Non_unique"]) == 1:
            return True
        if name == INDEX:
            raise RuntimeError("contact_email_index_conflict")
    return False


def execute():
    if not frappe.db.table_exists("Contact Email"):
        return {"changed": False, "reason": "table_absent"}
    if frappe.db.db_type != "mariadb":
        # Other engines retain the framework's own safe/idempotent index API.
        frappe.db.add_index("Contact Email", list(COLUMNS), index_name=INDEX)
        return {"changed": True, "index": INDEX}
    query = "SHOW INDEX FROM `tabContact Email`"
    if _covered(frappe.db.sql(query, as_dict=True)):
        return {"changed": False, "reason": "already_covered"}
    previous = int(frappe.db.sql("SELECT @@SESSION.lock_wait_timeout")[0][0])
    try:
        frappe.db.sql("SET SESSION lock_wait_timeout = 5")
        # Reject a table-copy/locking fallback instead of silently stopping
        # active imports. This adds no uniqueness constraint and edits no rows.
        frappe.db.sql_ddl(
            "ALTER TABLE `tabContact Email` ADD INDEX `lms_contact_email_lookup` "
            "(`email_id`, `parenttype`, `parent`), ALGORITHM=NOCOPY, LOCK=NONE"
        )
        if not _covered(frappe.db.sql(query, as_dict=True)):
            raise RuntimeError("contact_email_index_readback_failed")
    finally:
        frappe.db.sql("SET SESSION lock_wait_timeout = %s", (previous,))
    return {"changed": True, "index": INDEX}
