# Always rebuild this cumulative backend overlay from the same verified base.
# Do not use the latest release image as the parent.
FROM sha256:b90574d3160c04f5d1597a85a30f23cbdeee017607d89729333237d3e6d13486
COPY --chown=frappe:frappe lms/lms/avo_import.py lms/lms/avo_transform.py lms/lms/avo_html_fragment.py /home/frappe/frappe-bench/apps/lms/lms/lms/
