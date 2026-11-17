"""Synthetic durable journal tuning with pre-existing writer connections."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from configure_selected_wal import configure_file

SCOPE='a'*64


class WalTests(unittest.TestCase):
    def database(self,path,kind='application'):
        db=sqlite3.connect(path)
        db.execute('PRAGMA synchronous=FULL')
        meta={'account':'mastervision','site':'my-lk.mastervision.su','snapshot':'b'*32+':'+SCOPE} if kind=='application' else {
            'format':'selected-mv-profile-v1','account':'mastervision','site':'my-lk.mastervision.su','selection':SCOPE}
        with db:
            db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)');db.executemany('INSERT INTO metadata VALUES (?,?)',meta.items())
            db.execute('CREATE TABLE records(id INTEGER PRIMARY KEY,value TEXT)');db.execute("INSERT INTO records VALUES(1,'synthetic-before')")
        return db

    def test_existing_writer_and_readonly_reader_continue_with_full_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.sqlite'
            with closing(self.database(path)) as writer,closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as reader:
                self.assertEqual(writer.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                result=configure_file(path,SCOPE,'application');self.assertEqual(result['after'],'wal')
                with writer:writer.execute("INSERT INTO records VALUES(2,'synthetic-after')")
                self.assertEqual(writer.execute('PRAGMA journal_mode').fetchone()[0],'wal')
                self.assertEqual(writer.execute('PRAGMA synchronous').fetchone()[0],2)
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM records').fetchone()[0],2)
                self.assertEqual(configure_file(path,SCOPE,'application')['before'],'wal')

    def test_profiles_binding_and_rollback_remain_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'profiles.sqlite'
            with closing(self.database(path,'individual')) as writer:
                configure_file(path,SCOPE,'individual')
                writer.execute("INSERT INTO records VALUES(2,'rolled-back')");writer.rollback()
                self.assertEqual(writer.execute('SELECT COUNT(*) FROM records').fetchone()[0],1)

    def test_wrong_account_or_selection_is_rejected_before_journal_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.sqlite'
            with closing(self.database(path)) as writer:
                with self.assertRaises(ValueError):configure_file(path,'c'*64,'application')
                self.assertEqual(writer.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                with writer:writer.execute("UPDATE metadata SET value='iomp' WHERE key='account'")
                with self.assertRaises(ValueError):configure_file(path,SCOPE,'application')
                self.assertEqual(writer.execute('PRAGMA journal_mode').fetchone()[0],'delete')


if __name__=='__main__':unittest.main()
