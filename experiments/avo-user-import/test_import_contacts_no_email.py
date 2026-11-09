import unittest
import importlib.util
import sys
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


if __name__=='__main__':unittest.main()
