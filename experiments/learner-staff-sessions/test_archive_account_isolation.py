"""Fresh-process account isolation; synthetic inputs, no live network or keys."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid


HERE = Path(__file__).resolve().parent


def child(script, account=None, values=None):
    env = os.environ.copy()
    if account is None:
        env.pop('AVO_ARCHIVE_ACCOUNT', None)
    else:
        env['AVO_ARCHIVE_ACCOUNT'] = account
    env['PYTHONUTF8'] = '1'
    if values:
        env.update(values)
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=HERE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=25)
    if result.returncode:
        raise AssertionError('Synthetic subprocess failed:\n' + result.stderr[-6000:])
    return json.loads(result.stdout)


PROFILE_REPORT = '''
import json
import server_archive_sink as sink
import audit_legacy_links as audit
import collect_personal_links as detail
import collect_personal_links_bulk as bulk
import legacy_api_snapshot as snapshot
import private_link_storage as storage
import stream_archive_to_frappe as stream
p=sink.PROFILE
assert audit.API_ORIGIN==detail.API_ORIGIN==bulk.API_ORIGIN==snapshot.API_ORIGIN==sink.API_ORIGIN==p.api_origin
assert audit.SHOP_HOST==sink.SHOP_HOST==p.shop_host
assert bulk.ACCOUNT==snapshot.ACCOUNT==sink.ACCOUNT==p.account
assert sink.SITE==stream.SITE==p.site
assert snapshot.FORMAT==sink.PAGE_FORMAT==p.page_format
assert sink.FORMAT==stream.FORMAT==p.wire_format
assert stream.REMOTE_PREFIX==p.remote_prefix
assert bulk.collect.__kwdefaults__['fetch'] is detail.read_detail
assert snapshot.collect.__kwdefaults__['fetch'] is snapshot.read_page
assert snapshot.collect.__kwdefaults__['account']==p.account
print(json.dumps({k:(v.decode('ascii') if isinstance(v,bytes) else v) for k,v in p._asdict().items()}))
'''


class ProfileIsolationTests(unittest.TestCase):
    def test_default_mvc_profile_preserves_all_existing_identity_values(self):
        result = child(PROFILE_REPORT)
        self.assertEqual(result, {'account': 'mv-centr', 'api_origin': 'https://mvcentr.autoweboffice.ru',
            'shop_host': 'shop.mv-centr.ru', 'site': 'my-lk.mv-centr.ru',
            'page_format': 'mvcentr-legacy-api-snapshot-v1', 'link_schema': 'mvcentr-individual-links-v1',
            'wire_format': 'mvc-frappe-archive-v1', 'remote_prefix': 'REMOTE:MVC-FRAPPE:v1:',
            'crypto_namespace': 'AVO-MVC-Learner-Link-v1:', 'label': 'МВЦ'})

    def test_mastervision_profile_is_explicit_and_all_modules_agree(self):
        result = child(PROFILE_REPORT, 'mastervision')
        self.assertEqual(result, {'account': 'mastervision', 'api_origin': 'https://shop.mastervision.su',
            'shop_host': 'shop.mastervision.su', 'site': 'my-lk.mastervision.su',
            'page_format': 'mastervision-legacy-api-snapshot-v1',
            'link_schema': 'mastervision-individual-links-v1',
            'wire_format': 'mastervision-frappe-archive-v1', 'remote_prefix': 'REMOTE:MV-FRAPPE:v1:',
            'crypto_namespace': 'AVO-MV-Learner-Link-v1:', 'label': 'МВ'})

    def test_iomp_profile_is_explicit_and_all_modules_agree(self):
        result = child(PROFILE_REPORT, 'iomp')
        self.assertEqual(result, {'account': 'iomp', 'api_origin': 'https://shop.iomp.ru',
            'shop_host': 'shop.iomp.ru', 'site': 'my-lk.iomp.ru',
            'page_format': 'iomp-legacy-api-snapshot-v1', 'link_schema': 'iomp-individual-links-v1',
            'wire_format': 'iomp-frappe-archive-v1', 'remote_prefix': 'REMOTE:IOMP-FRAPPE:v1:',
            'crypto_namespace': 'AVO-IOMP-Learner-Link-v1:', 'label': 'ИОМП'})

    def test_unknown_profile_fails_before_any_worker_import(self):
        result = child('''
import json
try:
 import server_archive_sink
except Exception as e:
 print(json.dumps({'rejected':str(e)=='wrong_account'}))
else:
 print(json.dumps({'rejected':False}))
''', 'unknown-shop')
        self.assertTrue(result['rejected'])

    def test_profile_is_immutable_and_cannot_change_after_environment_mutation(self):
        result = child('''
import json,os
import server_archive_sink as sink
os.environ['AVO_ARCHIVE_ACCOUNT']='mv-centr'
import legacy_api_snapshot as snapshot
try:
 sink.PROFILE.account='mv-centr'
except (AttributeError,TypeError):
 immutable=True
else:
 immutable=False
print(json.dumps({'immutable':immutable,'frozen':sink.PROFILE.account==snapshot.ACCOUNT=='mastervision'}))
''', 'mastervision')
        self.assertEqual(result, {'immutable': True, 'frozen': True})

    def test_receiver_remains_self_contained_when_executed_like_live_mvc_sender(self):
        result = child('''
import json
from pathlib import Path
namespace={'__name__':'mvc_private_archive'}
exec(compile(Path('server_archive_sink.py').read_bytes(),'<mvc-private-archive>','exec'),namespace)
assert namespace['PROFILE'].account=='mv-centr'
assert namespace['PROFILE'].site=='my-lk.mv-centr.ru'
assert callable(namespace['main'])
print(json.dumps({'standalone':True}))
''')
        self.assertTrue(result['standalone'])

    def test_profile_bound_url_key_and_raw_source_validation(self):
        result = child('''
import json
import collect_personal_links as detail
import legacy_api_snapshot as snapshot
url='https://shop.mastervision.su/personal/auth/secure-login?uid=10&vc=SYNTHETIC_ONLY'
assert detail.verified_link(10,{'link_personal_auth':url})[0]==url
rejected=0
for bad in (url.replace('mastervision.su','mv-centr.ru'),url.replace('uid=10','uid=11')):
 try: detail.verified_link(10,{'link_personal_auth':bad})
 except detail.CollectionError: rejected+=1
assert detail.parse_key('https://shop.mastervision.su/?r=api/rest/contacts&key=SYNTHETIC')=='SYNTHETIC'
try: detail.parse_key('https://mvcentr.autoweboffice.ru/?r=api/rest/contacts&key=SYNTHETIC')
except detail.CollectionError: rejected+=1
try: snapshot.parse_rows(b'{"source":"https://mvcentr.autoweboffice.ru","contacts":[]}',snapshot.RESOURCES[0])
except snapshot.SnapshotError: rejected+=1
print(json.dumps({'rejected':rejected}))
''', 'mastervision')
        self.assertEqual(result['rejected'], 4)

    def test_source_requests_and_captured_defaults_use_only_selected_origin(self):
        result = child('''
import json
from unittest.mock import patch
import collect_personal_links as detail
import legacy_api_snapshot as snapshot
seen=[]
class Reply:
 code=200
 headers={}
 def __init__(self,url,body): self.url,self.body=url,body
 def __enter__(self): return self
 def __exit__(self,*args): return False
 def geturl(self): return self.url
 def read(self,n): return self.body
class Opener:
 def __init__(self,body): self.body=body
 def open(self,request,timeout):
  seen.append(request.full_url)
  return Reply(request.full_url,self.body)
with patch.object(detail,'build_opener',return_value=Opener(b'{"id_contact":10}')):
 detail.read_detail('SYNTHETIC',10)
with patch.object(snapshot,'build_opener',return_value=Opener(b'[]')):
 snapshot.read_page('SYNTHETIC','contacts',0,100,'id_contact ASC')
print(json.dumps({'correct':len(seen)==2 and all(v.startswith('https://shop.mastervision.su/?') for v in seen)}))
''', 'mastervision')
        self.assertTrue(result['correct'])

    def test_server_cipher_is_once_only_and_bound_to_account_and_source_id(self):
        result = child('''
import json
from cryptography.fernet import Fernet
import private_link_storage as storage
cipher=Fernet(Fernet.generate_key())
storage.configure_server_cipher(cipher,'mastervision')
encrypted=storage._crypt(10,b'SYNTHETIC ONLY')
assert storage._crypt(10,encrypted,decrypt=True)==b'SYNTHETIC ONLY'
rejected=0
try: storage._crypt(11,encrypted,decrypt=True)
except storage.StorageError: rejected+=1
try: storage.configure_server_cipher(cipher,'mastervision')
except storage.StorageError: rejected+=1
print(json.dumps({'rejected':rejected}))
''', 'mastervision')
        self.assertEqual(result['rejected'], 2)

    def test_server_cipher_rejects_wrong_account_configuration(self):
        result = child('''
import json
from cryptography.fernet import Fernet
import private_link_storage as storage
try: storage.configure_server_cipher(Fernet(Fernet.generate_key()),'mv-centr')
except storage.StorageError: rejected=True
else: rejected=False
print(json.dumps({'rejected':rejected}))
''', 'mastervision')
        self.assertTrue(result['rejected'])

    def test_server_cipher_registration_is_atomic(self):
        result = child('''
import json,threading
from concurrent.futures import ThreadPoolExecutor
from cryptography.fernet import Fernet
import private_link_storage as storage
barrier=threading.Barrier(4)
def configure(_):
 cipher=Fernet(Fernet.generate_key())
 barrier.wait()
 try: storage.configure_server_cipher(cipher,'mastervision')
 except storage.StorageError: return False
 return True
with ThreadPoolExecutor(max_workers=4) as pool:
 successes=sum(pool.map(configure,range(4)))
print(json.dumps({'successes':successes}))
''', 'mastervision')
        self.assertEqual(result['successes'], 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI identity boundary')
    def test_windows_dpapi_payloads_are_also_account_bound(self):
        encrypted = child('''
import json,base64
import private_link_storage as storage
print(json.dumps({'ciphertext':base64.b64encode(storage._crypt(10,b'SYNTHETIC')).decode()}))
''')['ciphertext']
        result = child('''
import json,os,base64
import private_link_storage as storage
try: storage._crypt(10,base64.b64decode(os.environ['SYNTHETIC_CIPHERTEXT']),decrypt=True)
except storage.StorageError: rejected=True
else: rejected=False
print(json.dumps({'rejected':rejected}))
''', 'mastervision', {'SYNTHETIC_CIPHERTEXT': encrypted})
        self.assertTrue(result['rejected'])

    def test_same_fernet_key_cannot_decrypt_other_accounts_payloads(self):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        encrypted = child('''
import json,os,base64
from cryptography.fernet import Fernet
import private_link_storage as storage
storage.configure_server_cipher(Fernet(os.environ['SYNTHETIC_KEY'].encode()),'mastervision')
print(json.dumps({'ciphertext':base64.b64encode(storage._crypt(10,b'SYNTHETIC')).decode()}))
''', 'mastervision', {'SYNTHETIC_KEY': key})['ciphertext']
        result = child('''
import json,os,base64
from cryptography.fernet import Fernet
import private_link_storage as storage
storage.configure_server_cipher(Fernet(os.environ['SYNTHETIC_KEY'].encode()),'mv-centr')
try: storage._crypt(10,base64.b64decode(os.environ['SYNTHETIC_CIPHERTEXT']),decrypt=True)
except storage.StorageError: rejected=True
else: rejected=False
print(json.dumps({'rejected':rejected}))
''', None, {'SYNTHETIC_KEY': key, 'SYNTHETIC_CIPHERTEXT': encrypted})
        self.assertTrue(result['rejected'])

    def test_wrong_profile_archive_metadata_and_receipts_are_rejected(self):
        result = child('''
import json,sqlite3
import server_archive_sink as sink
import collect_personal_links_bulk as bulk
metadata={'schema':'mvcentr-individual-links-v1','account':'mv-centr',
 'origin':'https://mvcentr.autoweboffice.ru','source_ids_sha256':'a'*64,'source_count':'1'}
rejected=0
try: sink._metadata(metadata,'links','b'*32)
except sink.SinkError: rejected+=1
db=sqlite3.connect(':memory:')
db.executescript('CREATE TABLE links(version_id INTEGER PRIMARY KEY,url_encrypted BLOB);'
 'CREATE TABLE delivery_receipts(version_id INTEGER,snapshot TEXT,sha256 TEXT,target TEXT);')
snapshot,sha='b'*32,'c'*64
marker=sink.PROFILE.remote_prefix+(snapshot+':1:'+sha).encode()
db.execute('INSERT INTO links VALUES (?,?)',(1,marker))
db.execute('INSERT INTO delivery_receipts VALUES (?,?,?,?)',(1,snapshot,sha,'my-lk.mv-centr.ru'))
try: bulk.validate_remote_receipts(db)
except bulk.BulkError: rejected+=1
db.execute('UPDATE delivery_receipts SET target=?',(sink.PROFILE.site,))
bulk.validate_remote_receipts(db)
db.close()
print(json.dumps({'rejected':rejected}))
''', 'mastervision')
        self.assertEqual(result['rejected'], 2)

    def test_fresh_processes_have_distinct_page_crypto_identifiers(self):
        script = "import json,legacy_api_snapshot as s;print(json.dumps({'key':s.page_key('contacts',0)}))"
        self.assertNotEqual(child(script)['key'], child(script, 'mastervision')['key'])

    def test_standalone_server_layout_allows_private_job_but_rejects_real_git(self):
        parent = HERE.parents[2] / 'exports'
        fixture = parent / ('.synthetic-server-layout-' + uuid.uuid4().hex)
        private = fixture / 'private'
        base = private / 'avo-api-archive'
        release = base / 'release-test'
        job = base / 'job-test'
        files = ('server_archive_sink.py', 'audit_legacy_links.py', 'collect_personal_links.py',
                 'collect_personal_links_bulk.py', 'private_link_storage.py', 'progress_io.py')
        release.mkdir(parents=True)
        job.mkdir()
        try:
            for name in files:
                (release / name).write_bytes((HERE / name).read_bytes())
            result = child('''
import json,os,sys,sqlite3
from pathlib import Path
release,job=Path(os.environ['SYNTHETIC_RELEASE']),Path(os.environ['SYNTHETIC_JOB'])
sys.path.insert(0,str(release))
import collect_personal_links_bulk as bulk
assert Path(bulk.__file__).parent==release
source=job/'source.sqlite'
with sqlite3.connect(source) as db:
 db.execute('CREATE TABLE contacts(id INTEGER PRIMARY KEY,record_json TEXT)')
 db.execute('INSERT INTO contacts VALUES (?,?)',(10,json.dumps({'source':'https://shop.mastervision.su','contact':{'id':10}})))
target=job/'links'
assert bulk.private_output(target,source)==target
(job/'.git').mkdir()
try: bulk.private_output(target,source)
except bulk.BulkError as e: rejected=str(e)=='private_output_required'
else: rejected=False
print(json.dumps({'private_job_allowed':True,'git_rejected':rejected}))
''', 'mastervision', {'SYNTHETIC_RELEASE': str(release), 'SYNTHETIC_JOB': str(job)})
            self.assertEqual(result, {'private_job_allowed': True, 'git_rejected': True})
        finally:
            # Fixed synthetic files and directories only, no recursive deletion.
            for name in files:
                (release / name).unlink(missing_ok=True)
            for name in ('source.sqlite', 'source.sqlite-journal', 'source.sqlite-wal', 'source.sqlite-shm'):
                (job / name).unlink(missing_ok=True)
            if (job / '.git').exists():
                (job / '.git').rmdir()
            job.rmdir()
            release.rmdir()
            base.rmdir()
            private.rmdir()
            fixture.rmdir()


if __name__ == '__main__':
    unittest.main()
