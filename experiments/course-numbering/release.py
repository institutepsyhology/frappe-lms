"""Guarded numbering-schema deployment with three-site backup and rollback."""
import importlib.util
from pathlib import Path
import re,sys,json
HERE=Path(__file__).resolve().parent
OLD='sha256:4191f318740c845d0dbdeb8c7de574d62fc62be582cca6ac20004449628b51ea'
TAG='company-lms:course-numbering-20261112'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def setup_numbering(mod, original):
 rows=original()
 code='''import frappe,json,sys
from lms.lms.course_numbering import execute,DOCTYPES
site=sys.argv[1];frappe.init(site=site);frappe.connect();frappe.set_user('Administrator')
try:
 result=execute();frappe.db.commit();frappe.clear_cache()
 for dt in DOCTYPES:
  field=frappe.get_meta(dt).get_field('custom_lms_id')
  if not field or not field.unique or not field.read_only or not field.no_copy:raise RuntimeError('numbering_schema_invalid')
 plan=execute(dry_run=True)
 if any(row['native_to_number'] or row['source_ids_to_copy'] for row in plan['doctypes'].values()):raise RuntimeError('numbering_migration_incomplete')
 print(json.dumps({'site':site,'migration':result,'verified':plan}))
finally:frappe.destroy()
'''
 for row in rows:
  result=json.loads(mod.run(['docker','exec','-u','frappe','-w',mod.BENCH+'/sites',mod.BACKEND,mod.BENCH+'/env/bin/python','-c',code,row['site']],timeout=240))
  row['numbering']=result
 return rows

def main():
 if len(sys.argv)==2 and sys.argv[1]=='prepare':
  mod=load('prepare_sites',HERE.parent/'avo-credential-profiles-interface/prepare_sites.py');mod.EXPECTED=OLD;mod.main();return 0
 if len(sys.argv)==3 and sys.argv[1]=='activate' and re.fullmatch(r'sha256:[0-9a-f]{64}',sys.argv[2]):
  mod=load('guarded_release',HERE.parent/'avo-credential-profiles-interface/deploy.py');mod.OLD,mod.NEW,mod.TAG=OLD,sys.argv[2],TAG
  original=mod.setup_sites;mod.setup_sites=lambda:setup_numbering(mod,original);return mod.main()
 raise SystemExit('usage: release.py prepare | activate sha256:...')
if __name__=='__main__':raise SystemExit(main())
