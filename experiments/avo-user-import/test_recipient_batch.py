import collections
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import recipient_batch as batch


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=batch.source.ROOT/'exports/contacts-api-all-fields')
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'pending.json'
        self.patcher=patch.object(batch,'PENDING',self.path);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.events=[]
        self.log=patch.object(batch.source,'log_event',side_effect=lambda i,s:self.events.append((i,s)))
        self.log.start();self.addCleanup(self.log.stop)
        self.items=[(1,{'email':'one@example.test'}),(2,{'email':'two@example.test'}),(3,{'email':'three@example.test'})]
        self.counts=collections.Counter(created=0,consecutive_issues=0)

    def test_success_checkpoints_before_writing_and_verifies_every_contact(self):
        def post(records,headers):
            self.assertEqual(batch.read_pending(),[1,2,3])
            return {'processed':3,'failed':False}
        with patch.object(batch,'post',side_effect=post), patch.object(batch,'reconcile',return_value={1:'present',2:'present',3:'present'}):
            self.assertTrue(batch.transfer(self.items,{},self.counts,wait=lambda _:None))
        self.assertEqual(self.events,[(1,'created_verified'),(2,'created_verified'),(3,'created_verified')])
        self.assertFalse(self.path.exists())

    def test_timeout_reconciles_committed_prefix_before_retrying_only_missing(self):
        def post(records,headers):
            if len(records)==3: raise TimeoutError()
            self.assertEqual([i for i,_ in records],[2,3])
            return {'processed':2,'failed':False}
        with patch.object(batch,'post',side_effect=post),patch.object(batch,'reconcile',side_effect=[{1:'present',2:'absent',3:'absent'},{2:'present',3:'present'}]):
            self.assertTrue(batch.transfer(self.items,{},self.counts,wait=lambda _:None))
        self.assertEqual(self.counts['created'],3)
        self.assertEqual([i for i,_ in self.events],[1,2,3])

    def test_rejected_record_is_skipped_without_losing_remaining_contacts(self):
        responses=[{'processed':1,'failed':True,'reason':'rejected'}, {'processed':1,'failed':False}]
        states=[{1:'present',2:'absent',3:'absent'},{3:'present'}]
        with patch.object(batch,'post',side_effect=responses),patch.object(batch,'reconcile',side_effect=states):
            self.assertTrue(batch.transfer(self.items,{},self.counts,wait=lambda _:None))
        self.assertIn((2,'validation_conflict'),self.events)
        self.assertIn((3,'created_verified'),self.events)

    def test_ambiguous_identity_stops_and_keeps_checkpoint(self):
        with patch.object(batch,'post',side_effect=TimeoutError()),patch.object(batch,'reconcile',return_value={1:'present',2:'conflict',3:'absent'}):
            self.assertFalse(batch.transfer(self.items,{},self.counts,wait=lambda _:None))
        self.assertEqual(self.counts['stopped'],'batch_identity_conflict')
        self.assertEqual(batch.read_pending(),[1,2,3])
        self.assertEqual(self.events,[])

    def test_restart_recovers_every_id_before_removing_checkpoint(self):
        batch.write_pending([1,2,3])
        outcomes={1:'present',2:'absent',3:'present'}
        batch.recover_pending(inspect=outcomes.get,wait=lambda _:None)
        self.assertEqual(self.events,[(1,'created_verified'),(2,'resolved_not_created'),(3,'created_verified')])
        self.assertFalse(self.path.exists())

    def test_restart_conflict_preserves_checkpoint(self):
        batch.write_pending([1,2,3])
        with self.assertRaises(RuntimeError):batch.recover_pending(inspect=lambda i:'conflict',wait=lambda _:None)
        self.assertTrue(self.path.exists())


if __name__=='__main__':unittest.main()
