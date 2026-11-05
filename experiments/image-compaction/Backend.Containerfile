# Always rebuild this cumulative backend overlay from the same verified base.
# Do not use the latest release image as the parent.
FROM company-lms:flat-verified-20261105
COPY --chown=frappe:frappe lms/lms/avo_import.py lms/lms/avo_transform.py lms/lms/avo_html_fragment.py /home/frappe/frappe-bench/apps/lms/lms/lms/
