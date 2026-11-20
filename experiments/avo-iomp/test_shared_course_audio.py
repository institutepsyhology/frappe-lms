import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import import_capture
import shared_course_audio as shared
from importer import IOMP_BINDING, Review, Stop


class Client:
    account, origin, site, server_name = IOMP_BINDING

    def __init__(self, paths):
        self.calls = []
        self.outline = {'course': 'course-91', 'by_id': {k: {'name': 'lesson-' + k} for k in paths}}
        self.docs = {'DocShare': [], 'File': [], 'Course Lesson': []}
        for lid, ordered in paths.items():
            name = 'lesson-' + lid
            links = [{'type': 'paragraph', 'data': {'text': '<a href="' + shared.ORIGIN + p + '">Audio</a>'}} for p in ordered]
            self.docs['Course Lesson'].append({'name': name, 'course': 'course-91', 'custom_avo_id': lid,
                                               'custom_lms_id': lid, 'custom_avo_account': 'iomp',
                                               'content': json.dumps({'blocks': links})})
            for path in ordered:
                self.docs['File'].append({'name': path[-9:], 'file_url': path, 'file_name': path.split('/')[-1],
                                          'is_private': 1, 'is_folder': 0, 'owner': 'Administrator', 'file_size': 321,
                                          'content_hash': hashlib.md5(path.encode(), usedforsecurity=False).hexdigest(),
                                          'attached_to_doctype': 'Course Lesson', 'attached_to_name': name,
                                          'attached_to_field': 'content'})

    def call(self, name, args):
        assert name == 'list_documents', 'shared audio verifier must not modify Frappe'
        self.calls.append(args['doctype'])
        return {'documents': self.docs[args['doctype']], 'has_next_page': False}


class SharedAudioTests(unittest.TestCase):
    def test_verify_requires_lesson_order_private_attachments_and_no_shares(self):
        paths = {'1829': [shared.PREFIX + '01-abcde.mp3', shared.PREFIX + '02-fghij.mp3']}
        digest = hashlib.sha256(json.dumps(paths, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        client = Client(paths)
        importer = SimpleNamespace(client=client, outline=lambda cid: client.outline if cid == '91' else None)
        with patch.object(shared, 'ORDERED_MANIFEST', digest):
            shared.verify_shared_audio(importer, paths)
            self.assertEqual(client.calls, ['Course Lesson', 'File', 'DocShare'])
            for overrides in ({'is_private': 0}, {'attached_to_name': 'wrong'}, {'attached_to_field': None},
                              {'owner': 'wrong'}, {'file_name': 'wrong.mp3'}):
                with self.subTest(overrides=overrides), patch.dict(client.docs['File'][0], overrides), self.assertRaises(Review):
                    shared.verify_shared_audio(importer, paths)
            with patch.dict(client.docs, File=client.docs['File'][:1]), self.assertRaisesRegex(Review, 'file_missing'):
                shared.verify_shared_audio(importer, paths)
            with patch.dict(client.docs, DocShare=[{'name': 'shared'}]), self.assertRaisesRegex(Review, 'file_shared'):
                shared.verify_shared_audio(importer, paths)
            doc = client.docs['Course Lesson'][0]
            blocks = json.loads(doc['content'])['blocks']
            with patch.dict(doc, content=json.dumps({'blocks': list(reversed(blocks))})), self.assertRaisesRegex(Review, 'links_changed'):
                shared.verify_shared_audio(importer, paths)
            with patch.object(client, 'account', 'mastervision'), self.assertRaises(Stop):
                shared.verify_shared_audio(importer, paths)

    def test_current_116_uses_identical_paths_to_91_and_preserves_all_source_ids(self):
        def read(cid):
            candidates = sorted((import_capture.ARCHIVE / ('course-' + cid)).glob('*/course.json'))
            if not candidates:
                self.skipTest('private captures unavailable')
            return import_capture.read_capture(candidates[-1].parent)[2]
        target, donor = read('116'), read('91')
        ids = [(p['course_id'], p['lesson_id']) for p in target]
        source_paths = {}
        for row in shared.prepare_course_audio(donor):
            source_paths.setdefault(row['lesson_id'], []).append(shared.target(row))
        self.assertEqual(shared.prepare_shared_audio(target), source_paths)
        self.assertEqual([(p['course_id'], p['lesson_id']) for p in target], ids)
        self.assertEqual(len(target), 63)
        self.assertEqual(shared.prepare_shared_audio(donor), {})
        self.assertEqual(sum(map(len, source_paths.values())), 62)
        import_capture.preflight_source(target)

    def test_course_333_reuses_62_files_in_their_existing_order(self):
        captures = sorted((import_capture.ARCHIVE / 'course-333').glob('*/capture-status.json'))
        if not captures:
            self.skipTest('private captures unavailable')
        records = import_capture.read_capture(captures[-1].parent)[2]
        ids = [(record['course_id'], record['lesson_id']) for record in records]
        paths = shared.prepare_shared_audio(records)
        shared.check_order(paths)
        self.assertEqual(sum(map(len, paths.values())), 62)
        self.assertEqual(ids, [(record['course_id'], record['lesson_id']) for record in records])
        import_capture.preflight_source(records)
        client = Client({'6276': paths['1829']})
        client.outline['course'] = 'course-333'
        client.docs['Course Lesson'][0]['course'] = 'course-333'
        importer = SimpleNamespace(client=client, outline=lambda cid: client.outline if cid == '333' else None)
        shared.verify_shared_destination(importer, paths, '333', included_lessons={'6276'})
        self.assertEqual(client.calls, ['Course Lesson'])

    def test_destination_uses_its_own_lesson_ids_and_donor_file_urls(self):
        paths = {src: [shared.PREFIX + src + '-sample.mp3'] for src in shared.PAIRED.values()}
        digest = hashlib.sha256(json.dumps(paths, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        target_paths = {dst: paths[src] for dst, src in shared.PAIRED.items()}
        client = Client(target_paths)
        client.outline['course'] = 'course-116'
        for doc in client.docs['Course Lesson']:
            doc['course'] = 'course-116'
        importer = SimpleNamespace(client=client, outline=lambda cid: client.outline if cid == '116' else None)
        with patch.object(shared, 'ORDERED_MANIFEST', digest):
            shared.verify_shared_destination(importer, paths)
            self.assertEqual(client.calls, ['Course Lesson'])
            with patch.dict(client.docs['Course Lesson'][-1], content='{"blocks":[]}'), self.assertRaises(Review) as error:
                shared.verify_shared_destination(importer, paths)
            self.assertEqual(error.exception.problems, [{'lesson_id': '1905'}])

    def test_wrong_school_is_never_normalized(self):
        mixed = [{'account': 'iomp', 'source_origin': IOMP_BINDING[1], 'course_id': '116'},
                 {'account': 'iomp', 'source_origin': 'https://shop.mastervision.su', 'course_id': '116'}]
        with self.assertRaises(Stop):
            shared.prepare_shared_audio(mixed)
        self.assertEqual(shared.prepare_shared_audio([{'account': 'mastervision', 'course_id': '116'}]), {})


if __name__ == '__main__':
    unittest.main()
