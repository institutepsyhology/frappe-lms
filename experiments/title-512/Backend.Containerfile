FROM company-lms:flat-verified-20261105
COPY --chown=frappe:frappe overlay/ /home/frappe/frappe-bench/apps/lms/
