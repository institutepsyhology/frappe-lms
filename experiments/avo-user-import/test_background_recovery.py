import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import run_background as worker


class FakeProcess:
    def __init__(self,row):self.stdout=io.StringIO(json.dumps(row)+'\n')
    def wait(self):return 0


class BackgroundRecoveryTest(unittest.TestCase):
    def test_transport_failure_reconciles_and_restarts_without_alert(self):
        with tempfile.TemporaryDirectory(dir=worker.migration.ROOT/'exports/contacts-api-all-fields') as folder:
            root=Path(folder);report=root/'exports/contacts-api-all-fields/report.json';report.parent.mkdir(parents=True)
            report.write_text(json.dumps({'origin':'https://mvcentr.autoweboffice.ru'}),encoding='utf-8')
            results=[FakeProcess({'created':2,'transport_error':1,'create_error':1}),FakeProcess({'created':3})]
            recovery=types.SimpleNamespace(unresolved_id=lambda:42,inspect=lambda ident:'present')
            events=[];alerts=[]
            fake_windows=types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *args:alerts.append(args)))
            with patch.object(worker.migration,'ROOT',root),patch.object(worker.migration,'log_event',side_effect=lambda i,s:events.append((i,s))), \
                 patch.object(worker,'STATUS',root/'status.json'),patch.object(worker,'LOG',root/'run.log'), \
                 patch.object(worker,'RECIPIENT_RECOVERY',True),patch.object(worker.subprocess,'Popen',side_effect=results), \
                 patch.dict('sys.modules',{'recipient_recovery':recovery}),patch.object(worker.ctypes,'windll',fake_windows):
                worker.main()
                state=json.loads((root/'status.json').read_text(encoding='utf-8'))
            self.assertEqual(events,[(42,'created_verified')])
            self.assertEqual(state['status'],'completed')
            self.assertEqual(state['created_this_run'],5)
            self.assertEqual(len(alerts),1)


if __name__=='__main__':unittest.main()
