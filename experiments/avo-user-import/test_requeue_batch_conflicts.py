import unittest
from requeue_batch_conflicts import candidates

class RequeueTest(unittest.TestCase):
    def test_only_latest_unresolved_selected_conflicts_after_cutoff(self):
        def event(i,status,date='2026-11-11T22:10:00+00:00',account='mv-centr'):
            return {'account':account,'contact_id':i,'status':status,'at':date}
        rows=[event(1,'validation_conflict'),event(2,'validation_conflict'),event(2,'created_verified'),
              event(3,'validation_conflict','2026-11-11T21:00:00+00:00'),event(4,'validation_conflict',account='iomp'),
              event(5,'validation_conflict'),event(5,'retry_validation_conflict')]
        self.assertEqual(candidates(rows,{1,2,3,4,5}),[1])
        self.assertEqual(candidates(rows,set()),[])

if __name__=='__main__':unittest.main()
