import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zlib

import archive_store as store


def card(link_id, assigned=(14,)):
    return dict(id=link_id, status='card', origin=store.ORIGIN, contact_id=3, course_id=598,
                captured_at='2026-11-20T09:00:00Z', allLessons=[{'id':14}, {'id':15}],
                detail={'course':{'id':598}, 'availableLessons':[{'id':x} for x in assigned]})


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.db = store.connect(':memory:')
        self.addCleanup(self.db.close)

    def test_duplicate_links_with_different_assignments_survive(self):
        db=self.db
        store.save(db,[card(446461,(14,15)),card(446462)])
        self.assertEqual(db.execute('select count(*) from configs').fetchone(),(1,))
        self.assertEqual(store.resume(db),[[446461,446462]])
        self.assertIn(b'"availableLessons":[{"id":14}]',zlib.decompress(
            db.execute('select detail from cards where link_id=446462').fetchone()[0]))
        with self.assertRaisesRegex(ValueError,'identity_changed'):
            store.save(db,[dict(card(446462),contact_id=7)])
        with self.assertRaisesRegex(ValueError,'lesson_ids'):
            store.save(db,[card(446463,[16])])

    def test_scope_must_finish_before_release(self):
        db=self.db
        store.save(db,[card(446462),card(store.BOUND)])
        with self.assertRaisesRegex(ValueError,'incomplete_range'):
            store.respond(db,{'op':'finish'})
        scope=[2,446462,store.BOUND]
        with self.assertRaisesRegex(ValueError,'inventory_changed'):
            store.respond(db,{'op':'inventory','first':scope,'second':scope[1:]})
        store.respond(db,{'op':'inventory','first':scope,'second':scope})
        store.save(db,[{'id':2,'status':'error','code':'source_connection_failed'}])
        with self.assertRaisesRegex(ValueError,'unresolved_cards'):
            store.respond(db,{'op':'finish'})
        store.save(db,[card(2)])
        self.assertEqual(store.respond(db,{'op':'finish'})['state'],'complete')
        with self.assertRaisesRegex(ValueError,'archive_already_complete'):
            store.save(db,[card(2)])

    def test_negative_cannot_mask_positive(self):
        store.save(self.db,[card(446462)])
        with self.assertRaisesRegex(ValueError,'changed_during_capture'):
            store.save(self.db,[dict(card(446462),status='missing')])
        self.assertEqual(store.status(self.db)['missing'],0)

    def test_policies_remain_writable_after_capture_and_must_match_tenant(self):
        store.save(self.db,[card(446462)])
        store.put(self.db,'capture_state','complete')
        now=datetime.now(timezone.utc).isoformat()
        item=dict(course_id=598,source_origin=store.ORIGIN,captured_at=now,
                  no_access_info={'body':'Текст курса'},settings={},draft_lesson_ids=[14])
        with TemporaryDirectory() as base, patch.object(store,'FOLDER',Path(base)), patch.object(store,'RESERVE',0):
            def receive(policy):
                return store.respond(self.db,{'op':'policy','policy':policy})
            self.assertEqual(store.respond(self.db,{'op':'policy_ids'}),{'course_ids':[598]})
            with self.assertRaisesRegex(ValueError,'wrong_policy_origin'):
                receive(dict(item,source_origin='https://shop.iomp.ru'))
            with self.assertRaisesRegex(ValueError,'policy_timestamp'):
                receive(dict(item,captured_at='2025-01-01T00:00:00Z'))
            self.assertTrue(receive(item)['stored'])
            self.assertEqual(store.respond(self.db,{'op':'policy_ids'}),{'course_ids':[]})
            self.assertEqual(store.status(self.db)['state'],'complete')
            self.assertEqual((Path(base)/'policies/598.json').read_bytes(),store.packed(item))


if __name__=='__main__':
    unittest.main()
