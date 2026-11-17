"""Schema guard tests; no actual contact data or server connection."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH=Path(__file__).resolve().parents[2]/'lms/patches/v2_0/add_contact_email_lookup_index.py'


def index_rows(name='lms_contact_email_lookup',*,unique=False,columns=('email_id','parenttype','parent')):
    return [{'Key_name':name,'Column_name':column,'Seq_in_index':i+1,'Non_unique':int(not unique),'Sub_part':None}
        for i,column in enumerate(columns)]


class DB:
    db_type='mariadb'
    def __init__(self,rows=(),error=None):self.rows=list(rows);self.error=error;self.calls=[];self.ddls=[]
    def table_exists(self,table):return True
    def sql(self,query,args=(),**kwargs):
        self.calls.append((query,args))
        if query.startswith('SHOW INDEX'):return self.rows
        if query.startswith('SELECT @@SESSION'):return [(123,)]
        return []
    def sql_ddl(self,query):
        self.ddls.append(query)
        if self.error:raise self.error
        self.rows.extend(index_rows())


class IndexTests(unittest.TestCase):
    def load(self,db):
        spec=importlib.util.spec_from_file_location('test_index_patch',PATH);module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'frappe':SimpleNamespace(db=db)}):spec.loader.exec_module(module)
        return module

    def test_online_nonunique_index_verified_and_session_restored(self):
        db=DB();module=self.load(db)
        self.assertTrue(module.execute()['changed'])
        self.assertEqual(len(db.ddls),1);self.assertIn('ALGORITHM=NOCOPY, LOCK=NONE',db.ddls[0])
        self.assertNotIn('UNIQUE',db.ddls[0]);self.assertEqual(db.calls[-1],('SET SESSION lock_wait_timeout = %s',(123,)))
        self.assertFalse(module.execute()['changed']);self.assertEqual(len(db.ddls),1)

    def test_equivalent_covering_index_has_no_schema_write(self):
        db=DB(index_rows('existing_covering'));module=self.load(db)
        self.assertFalse(module.execute()['changed']);self.assertEqual(db.ddls,[])

    def test_conflicting_unique_or_wrong_named_index_is_not_modified(self):
        for rows in (index_rows(unique=True),index_rows(columns=('parent','email_id','parenttype'))):
            db=DB(rows);module=self.load(db)
            with self.assertRaisesRegex(RuntimeError,'^contact_email_index_conflict$'):module.execute()
            self.assertEqual(db.ddls,[])

    def test_unsupported_online_ddl_never_falls_back_to_copy_or_locked_build(self):
        db=DB(error=RuntimeError('online unsupported'));module=self.load(db)
        with self.assertRaises(RuntimeError):module.execute()
        self.assertEqual(len(db.ddls),1);self.assertEqual(db.calls[-1],('SET SESSION lock_wait_timeout = %s',(123,)))

    def test_prefix_index_does_not_claim_full_covering(self):
        rows=index_rows('partial');rows[0]['Sub_part']=10
        db=DB(rows);module=self.load(db);self.assertTrue(module.execute()['changed'])


if __name__=='__main__':unittest.main()
