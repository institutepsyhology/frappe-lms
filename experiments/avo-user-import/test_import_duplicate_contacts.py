import unittest
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('duplicates',Path(__file__).with_name('import_duplicate_contacts.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DuplicateContactTest(unittest.TestCase):
    def test_preserves_source_email_and_id_without_linking_user(self):
        data=module.make_payload(123,{'contact':{'not_to_write':'0','spam_clicked':'0','name':'Example','email':'same@example.test','vk_user_id':'9'}})
        self.assertEqual(data['custom_avo_contact_id'],'123')
        self.assertEqual(data['custom_avo_vk_id'],'9')
        self.assertEqual(data['email_ids'][0]['email_id'],'same@example.test')
        self.assertNotIn('user',data)

    def test_invalid_email_is_not_imported(self):
        with self.assertRaises(ValueError):module.make_payload(123,{'contact':{'not_to_write':'0','spam_clicked':'0','email':'invalid'}})


if __name__=='__main__':unittest.main()
