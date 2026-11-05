import importlib.util
import io
from pathlib import Path
import sqlite3
import tarfile
import unittest

path=Path(__file__).with_name('compact_image.py')
spec=importlib.util.spec_from_file_location('compact_image',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def archive(files):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w') as tf:
        for name,content in files:
            data=content.encode(); info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o640
            tf.addfile(info,io.BytesIO(data))
    out.seek(0);return out


class CompactionTests(unittest.TestCase):
    def test_config_and_platform_preserved(self):
        image={'Os':'linux','Architecture':'amd64','Config':{'User':'frappe','Env':['EXAMPLE=a'],
              'Entrypoint':['/bin/start'],'Cmd':['serve'],'Volumes':{'/data':{}},'WorkingDir':'/work','ArgsEscaped':True}}
        result=module.build_config(image,'sha256:'+'a'*64)
        self.assertEqual(result['config'],image['Config'])
        self.assertEqual(result['rootfs']['diff_ids'],['sha256:'+'a'*64])
        self.assertEqual(result['architecture'],'amd64')

    def test_archive_manifest_detects_changed_file_and_metadata(self):
        baseline=module.file_manifest(archive([('a','first'),('b','second')]))
        self.assertEqual(baseline,module.file_manifest(archive([('b','second'),('a','first')])))
        self.assertNotEqual(baseline,module.file_manifest(archive([('a','altered'),('b','second')])))

    def test_duplicate_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate_archive_path'):
            module.file_manifest(archive([('a','first'),('a','second')]))

    def test_stream_comparison_rejects_added_missing_and_changed_files(self):
        def database():
            db=sqlite3.connect(':memory:')
            db.execute('create table files(name text primary key,metadata text not null,seen integer not null default 0)')
            module.index_archive(archive([('a','first'),('b','second')]),db)
            return db
        db=database();self.assertEqual(module.compare_archive(archive([('b','second'),('a','first')]),db),2);db.close()
        for bad in ([('a','wrong'),('b','second')],[('a','first')],[('a','first'),('b','second'),('c','extra')]):
            db=database()
            with self.assertRaises(ValueError):module.compare_archive(archive(bad),db)
            db.close()


if __name__=='__main__':unittest.main()
