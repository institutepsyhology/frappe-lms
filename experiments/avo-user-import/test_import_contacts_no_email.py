import unittest
import importlib.util
import sys
import io
import json
import urllib.error
from unittest.mock import patch, Mock
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('noemail',Path(__file__).with_name('import_contacts_no_email.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ContactTest(unittest.TestCase):
    def test_social_contact_never_gets_synthetic_email(self):
        record={'contact':{'name':'Test','email':'','vk_user_id':'123','phone_number':'9999'}}
        data=module.payload(166,record)
        self.assertNotIn('email_id',data)
        self.assertEqual(data['custom_avo_contact_id'],'166')
        self.assertEqual(data['custom_avo_vk_id'],'123')
        self.assertEqual(data['phone_nos'][0]['phone'],'9999')
    def test_valid_email_is_not_processed_in_this_batch(self):
        self.assertIsNone(module.payload(1,{'contact':{'email':'test@example.test'}}))
    def test_nameless_contact_gets_identifiable_label_not_fake_email(self):
        data=module.payload(123,{'contact':{}})
        self.assertIn('123',data['first_name'])
        self.assertNotIn('email_id',data)

    def test_conflict_is_logged_and_next_contact_is_created(self):
        records=[(101,{'contact':{'name':'A'}}),(102,{'contact':{'name':'B'}})]
        saved=module.payload(102,records[1][1])
        response=Mock()
        response.__enter__=Mock(return_value=io.BytesIO(json.dumps({'data':saved}).encode()))
        response.__exit__=Mock(return_value=False)
        helper=Mock();helper.authenticated_headers.return_value={}
        spec=Mock()
        conflict=urllib.error.HTTPError('https://example.test',409,'conflict',{},None)
        events=[]
        journal=Mock();journal.exists.return_value=False
        with patch.object(module,'JOURNAL',journal), \
             patch.object(module,'event',side_effect=lambda ident,status: events.append((ident,status))), \
             patch.object(module.source,'load',return_value=iter(records)), \
             patch.object(module.source.DIRECT_OPENER,'open',side_effect=[conflict,response]), \
             patch('importlib.util.spec_from_file_location',return_value=spec), \
             patch('importlib.util.module_from_spec',return_value=helper), \
             patch.object(module.time,'sleep'), \
             patch.object(sys,'argv',['importer','--apply','--limit','2']), \
             patch('sys.stdout',new_callable=io.StringIO):
            module.main()
        self.assertEqual(events,[(101,'rejected'),(102,'created_verified')])


if __name__=='__main__':unittest.main()
