"""Keep imported Contact/User associations bound to their AVO source identity.

Installed through ``extend_doctype_class`` for Contact. Native Contacts without
an AVO identity retain Frappe's existing email-based association behaviour.
"""
import frappe


_SITE_ACCOUNTS = {
    "access-stage2.local": "mv-centr",
    "my-lk.mv-centr.ru": "mv-centr",
    "my-lk.mastervision.su": "mastervision",
    "my-lk.iomp.ru": "iomp",
}
_NATIVE_CONTACT_JOB = "frappe.core.doctype.user.user.create_contact"
_IDENTITY_CONFLICT = "AVO contact identity conflict."


def _field(value, name):
    getter = getattr(value, "get", None)
    return getter(name) if callable(getter) else getattr(value, name, None)


def _fail():
    # Never include a contact, email, source ID or job payload in the exception.
    frappe.throw(_IDENTITY_CONFLICT)


def _canonical_id(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 19
        and value.isascii()
        and value.isdecimal()
        and value[0] != "0"
        and int(value) < 2**63
    )


class AvoContactIdentityMixin:
    def set_user(self):
        account = self.get("custom_avo_account")
        source_id = self.get("custom_avo_contact_id")
        if account in (None, "") and source_id in (None, ""):
            return super().set_user()

        expected_account = _SITE_ACCOUNTS.get(getattr(frappe.local, "site", None))
        if (
            not isinstance(account, str)
            or expected_account is None
            or account != expected_account
            or not _canonical_id(source_id)
        ):
            _fail()

        matches = frappe.get_all(
            "User",
            filters={"custom_avo_account": account, "custom_avo_contact_id": source_id},
            pluck="name",
            limit_page_length=2,
        )
        if len(matches) > 1:
            _fail()
        exact_user = matches[0] if matches else None
        if matches and (
            not isinstance(exact_user, str)
            or not exact_user
            or exact_user in ("Administrator", "Guest")
        ):
            _fail()

        if self.get("user") not in (None, "", exact_user):
            _fail()

        job = getattr(frappe.local, "job", None)
        if _field(job, "method") == _NATIVE_CONTACT_JOB:
            # Native User.create_contact selects an existing Contact by email
            # and changes its names/phones before save(), without setting user.
            # RQ supplies the intended User in this trusted execution context.
            # Throwing in validate prevents those foreign changes persisting.
            queued_user = _field(_field(job, "kwargs"), "user")
            queued_name = _field(queued_user, "name")
            if not exact_user or queued_name != exact_user:
                _fail()

        # An imported standalone Contact must never claim a different source's
        # User merely because the native email field happens to be identical.
        self.user = exact_user
