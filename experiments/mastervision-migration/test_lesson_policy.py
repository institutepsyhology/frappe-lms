import copy
import unittest
from unittest.mock import patch
from importer import ACCOUNT, ORIGIN, Stop
from lesson_policy import DEFERRED, EXCLUDED, deferred_ids, excluded_ids, partition_payloads

PENDING = {317:{2314},607:{6577},624:{7050},627:{7198},628:{7247},629:{7252},630:{7295},746:{8845}}


def payload(cid, lid):
    return {'account':ACCOUNT, 'source_origin':ORIGIN, 'course_id':cid, 'lesson_id':lid,
            'ape':{'name':'page','children':[]}, 'private_source':'unchanged'}


class PolicyTests(unittest.TestCase):
    def test_exact_eight_owner_deferrals_and_19_exclusions(self):
        self.assertEqual(DEFERRED, PENDING)
        self.assertTrue(all(isinstance(ids, frozenset) for ids in DEFERRED.values()))
        expected={1:{1,6},2:{2,5},17:{2558},23:{30},207:{1976},259:{1536},273:{1735},274:{1749},
                  354:{2937},355:{2952},440:{7326},445:{4089},557:{5952},598:{7544},613:{6750},
                  618:{6870},634:{7341}}
        self.assertEqual(EXCLUDED, expected)
        self.assertEqual(sum(map(len, EXCLUDED.values())), 19)
        self.assertNotIn(9037, set().union(*DEFERRED.values(), *EXCLUDED.values()))

    def test_eight_deferrals_keep_source_payloads_order_and_exact_identity(self):
        for cid, ids in PENDING.items():
            lid = next(iter(ids))
            source = [payload(cid, x) for x in (900001, lid, 900002)]
            before = copy.deepcopy(source)
            selected, pending = partition_payloads(source)
            self.assertEqual([p['lesson_id'] for p in selected], [900001,900002])
            self.assertEqual(pending, [lid]); self.assertEqual(source, before)
            self.assertIs(selected[0], source[0]); self.assertIs(selected[1], source[2])
            self.assertEqual(deferred_ids(cid), {lid}); self.assertEqual(excluded_ids(cid), set())
            outside = [payload(999999,lid)]
            self.assertEqual(partition_payloads(outside), (outside, []))

    def test_selected_five_courses_run_as_partial_without_normalizing_deferred_content(self):
        import test_run as controller
        for cid in (317,607,624,627,628,630,746):
            lid = next(iter(PENDING[cid]))
            source = [{**controller.payload(cid),'lesson_id':x} for x in (900001,lid,900002)]
            source[1]['ape'] = {'name':'unrecognized_owner_pending_source'}
            before = copy.deepcopy(source)
            with patch.object(controller.mod,'stored_course',return_value=source):
                result=controller.ControllerTests().invoke(cid,args=['--stored','--apply','--course',str(cid)])
            self.assertEqual(result[0],0); self.assertEqual(source,before)
            self.assertEqual([p['lesson_id'] for p in result[4].payloads[0]],[900001,900002])
            self.assertEqual(result[1].marks,[(cid,'partial')])
            self.assertIn(('import',cid,lid,'review',['owner_deferred_lesson']),result[1].events)
            self.assertIn({'course':cid,'status':'partial','lessons':2,'created':0,'deferred':[lid]},result[5])
            self.assertEqual(result[2].urls,[])

    def test_629_all_deferred_retains_review_without_fake_empty_target(self):
        import test_run as controller
        import course_metadata
        source=[{**controller.payload(629),'lesson_id':7252}]; before=copy.deepcopy(source)
        with patch.object(controller.mod,'stored_course',return_value=source), \
                patch.object(course_metadata,'ensure_empty_course') as empty:
            result=controller.ControllerTests().invoke(629,args=['--stored','--apply','--course','629'])
        self.assertEqual(result[0],0); self.assertEqual(source,before)
        self.assertEqual(result[4].calls,[]); empty.assert_not_called()
        self.assertEqual(result[1].marks,[(629,'review')])
        self.assertIn({'course':629,'status':'deferred','lessons':0,'deferred':[7252]},result[5])
        self.assertIn(('import',629,7252,'review',['owner_deferred_lesson']),result[1].events)
        self.assertEqual(result[2].urls,[])

    def test_bulk_test_and_obsolete_lesson_exclusions_keep_other_source_items(self):
        approved={1:{1,6},2:{2,5},17:{2558},23:{30},259:{1536},273:{1735},274:{1749},354:{2937},355:{2952}}
        for cid,lids in approved.items():
            source=[payload(cid,lid) for lid in (999001,*sorted(lids),999002)]
            before=copy.deepcopy(source);selected,pending=partition_payloads(source)
            self.assertEqual([p['lesson_id'] for p in selected],[999001,999002])
            self.assertEqual(pending,[]);self.assertEqual(source,before)
            self.assertEqual(excluded_ids(cid),lids)
            for lid in lids:
                self.assertEqual(partition_payloads([payload(999999,lid)]),([payload(999999,lid)],[]))
        self.assertEqual(partition_payloads([payload(2,2),payload(2,5)]),([],[]))
        self.assertEqual(partition_payloads([payload(23,30)]),([],[]))

    def test_permanent_omissions_are_not_temporary_pending_or_cross_course(self):
        for cid,lid in ((207,1976),(440,7326),(445,4089),(557,5952),(598,7544),
                        (613,6750),(618,6870),(634,7341)):
            source=[payload(cid,1),payload(cid,lid),payload(cid,2)];before=copy.deepcopy(source)
            selected,pending=partition_payloads(source)
            self.assertEqual([p['lesson_id'] for p in selected],[1,2]);self.assertEqual(pending,[])
            self.assertEqual(source,before);self.assertEqual(excluded_ids(cid),{lid})
            self.assertEqual(partition_payloads([payload(999,lid)]),([payload(999,lid)],[]))
        self.assertEqual(excluded_ids(598),{7544});self.assertEqual(deferred_ids(207),set())
        for value in (True,0,'207'):
            with self.assertRaises(Stop):excluded_ids(value)

    def test_only_exact_binding_omitted_without_payload_changes(self):
        source=[payload(598,x) for x in [7,7544,9]]; before=copy.deepcopy(source)
        selected,pending=partition_payloads(source)
        self.assertEqual([x['lesson_id'] for x in selected],[7,9]);self.assertEqual(pending,[])
        self.assertEqual(source,before);self.assertIs(selected[0],source[0])
        self.assertFalse(any('deferred' in str(x) for x in selected))
        self.assertEqual(partition_payloads([payload(599,7544)]),([payload(599,7544)],[]))

    def test_empty_and_all_excluded_are_explicitly_empty_without_reminders(self):
        self.assertEqual(partition_payloads([]),([],[]))
        self.assertEqual(partition_payloads([payload(598,7544)]),([],[]))
        self.assertEqual(DEFERRED,PENDING)
        self.assertEqual(deferred_ids(598),set());self.assertEqual(deferred_ids(557),set())

    def test_final_owner_exclusion_keeps_source_and_order_and_cannot_return_as_pending(self):
        source=[payload(557,lid) for lid in (5941,5952,5942)];before=copy.deepcopy(source)
        selected,pending=partition_payloads(source)
        self.assertEqual([p['lesson_id'] for p in selected],[5941,5942])
        self.assertEqual(pending,[]);self.assertEqual(source,before)
        self.assertEqual(deferred_ids(557),set());self.assertEqual(excluded_ids(557),{5952})
        self.assertEqual(partition_payloads([payload(999,5952)]),([payload(999,5952)],[]))

    def test_foreign_mixed_duplicate_or_invalid_identity_fails(self):
        foreign=payload(598,7544);foreign['account']='mv-centr'
        origin=payload(598,7544);origin['source_origin']='https://shop.iomp.ru'
        boolean=payload(598,True)
        for source in ([foreign],[origin],[boolean],[payload(598,1),payload(599,2)],
                       [payload(598,1),payload(598,1)],{},[{}]):
            with self.subTest(source=source),self.assertRaisesRegex(Stop,'^lesson_policy_identity_invalid$'):
                partition_payloads(source)


if __name__=='__main__':unittest.main()
