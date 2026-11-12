"""Guarded follow-up using the installed standard Frappe Series capacity."""
import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('numbering_release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
release.OLD='sha256:7e7dced29c949ef42b5bface5fdfc2809db8534a9cc3013ca0cba42b412bd7c6'
release.TAG='company-lms:course-numbering-v2-20261112'
if __name__=='__main__':raise SystemExit(release.main())
