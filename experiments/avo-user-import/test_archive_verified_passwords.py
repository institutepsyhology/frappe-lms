import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('archive',Path(__file__).with_name('archive_verified_passwords.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class ArchiveTest(unittest.TestCase):
    def test_lookup_requires_unique_selected_source_ids(self):
        class Response:
            def __init__(self,data):self.data=io.BytesIO(json.dumps({'data':data}).encode())
            def __enter__(self):return self.data
            def __exit__(self,*args):return False
        with patch.object(module.source.DIRECT_OPENER,'open',return_value=Response([
            {'name':'one@example.invalid','custom_avo_contact_id':'10'}])):
            self.assertEqual(module.users_for_ids([10,11],{}),{10:'one@example.invalid'})
        with patch.object(module.source.DIRECT_OPENER,'open',return_value=Response([
            {'name':'one@example.invalid','custom_avo_contact_id':'10'},
            {'name':'two@example.invalid','custom_avo_contact_id':'10'}])):
            with self.assertRaises(ValueError):module.users_for_ids([10],{})


if __name__=='__main__':unittest.main()
