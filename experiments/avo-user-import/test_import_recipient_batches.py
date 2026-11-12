import collections
import io
import json
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import import_recipient_batches as importer


class RecipientBatchSelectionTest(unittest.TestCase):
    def test_only_selected_uncreated_contacts_are_batched_with_optouts(self):
        with tempfile.TemporaryDirectory(dir=importer.source.ROOT/'exports/contacts-api-all-fields') as folder:
            journal=Path(folder)/'events.jsonl'
            journal.write_text(''.join(json.dumps(e)+'\n' for e in [
                {'account':'mv-centr','contact_id':100,'status':'created_verified'},
                {'account':'mv-centr','contact_id':102,'status':'validation_conflict'},
                {'account':'mv-centr','contact_id':102,'status':'retry_validation_conflict'},
            ]),encoding='utf-8')
            records=[(i,{'email':f'test{i}@example.test'}) for i in range(100,114)]
            taken=[]
            def transfer(items,headers,counters):
                taken.extend(items);counters['created']+=len(items);return True
            helper=types.SimpleNamespace(authenticated_headers=lambda site:{})
            spec=types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda mod:None))
            with patch.object(importer.source,'JOURNAL',journal),patch.object(importer.source,'load',side_effect=lambda:iter(records)), \
                 patch.object(importer.source,'email_of',side_effect=lambda r:r['email']), \
                 patch.object(importer.source,'payload',side_effect=lambda i,r:{'email':r['email'],'custom_no_marketing_email':0}), \
                 patch.object(importer.batch,'recover_pending'),patch.object(importer.batch,'transfer',side_effect=transfer), \
                 patch.object(importer.importlib.util,'spec_from_file_location',return_value=spec), \
                 patch.object(importer.importlib.util,'module_from_spec',return_value=helper),redirect_stdout(io.StringIO()):
                importer.run(types.SimpleNamespace(apply=True,limit=100),set(range(100,113)),{102},{})
            self.assertEqual([i for i,_ in taken],list(range(101,113)))
            self.assertEqual(next(data for i,data in taken if i==102)['custom_no_marketing_email'],1)
            self.assertEqual(next(data for i,data in taken if i==103)['custom_no_marketing_email'],0)


if __name__=='__main__':unittest.main()
