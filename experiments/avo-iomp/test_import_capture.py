import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from import_capture import (
    ACCOUNT, ORIGIN, SITE, Course60Importer, IompImporter, Review, Stop,
    ARCHIVE, main, normalize_avatar_label, ready_prefix, refreshed_lessons,
)
from lms.lms.avo_transform import omit_placeholder_node
from normalize_review import EXCLUDED_LESSONS, clean_timing_table, normalize_review


class AvatarNormalizationTests(unittest.TestCase):
    def test_archive_prefix_stops_before_the_first_unresolved_lesson(self):
        lessons = [{'lesson_id': str(i)} for i in (25, 12, 7, 21)]
        def review(*ids):
            return Review('course_needs_review', [{'lesson_id': str(i), 'codes': ['unknown_block']} for i in ids])
        rows, code = ready_prefix('4', lessons, review(21, 7), None, allow_prefix=True)
        self.assertEqual((rows, code), (lessons[:2], 'remaining_lessons_deferred'))
        for blocked in ((25,), (999,), (12, 999)):
            with self.assertRaises(Review):
                ready_prefix('4', lessons, review(*blocked), None, allow_prefix=True)

    def test_only_the_known_avatar_loses_the_generic_image_label(self):
        avatar = 'https://example.test/avatar.jpeg'
        picture = 'https://example.test/lesson.png'
        avatar_hash = hashlib.sha256(avatar.encode()).hexdigest()
        nodes = [
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': avatar, 'html': 'Изображение'}},
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': picture, 'html': 'Изображение'}},
            {'name': 'image', 'fields': {'anchor': '', 'imageSrc': avatar, 'html': 'Схема урока'}},
            {'name': 'text', 'fields': {'html': '<p>Здравствуйте, {name}</p>'}},
        ]
        payload = {'course_id': '3', 'lesson_id': '424', 'ape': {'name': 'page', 'children': nodes}}
        with patch('lms.lms.avo_transform.PLACEHOLDER_IMAGE_SHA256', avatar_hash):
            normalize_avatar_label(payload)
            self.assertTrue(omit_placeholder_node(nodes[0], 'iomp', '3', '424'))
            self.assertEqual(nodes[1]['fields']['html'], 'Изображение')
            self.assertEqual(nodes[2]['fields']['html'], 'Схема урока')
            self.assertTrue(omit_placeholder_node(nodes[3], 'iomp', '3', '424'))


class OwnerReviewTests(unittest.TestCase):
    def test_excluded_courses_do_not_open_a_capture_or_a_connection(self):
        with patch('import_capture.read_capture') as read, patch('import_capture.IompClient') as connect:
            for cid in ('247', '251'):
                self.assertEqual(main(ARCHIVE / ('course-' + cid) / 'capture')['status'], 'excluded')
            read.assert_not_called()
            connect.assert_not_called()

    def test_only_confirmed_prefix_can_be_imported_ahead_of_pending_materials(self):
        rows = [{'lesson_id': lid} for lid in ('3262', '3280', '3279', '3260')]
        problem = Review('course_needs_review', [{'lesson_id': '3279', 'codes': ['unsupported_button']},
                                                  {'lesson_id': '3260', 'codes': ['owner_decision_pending']}])
        self.assertEqual(ready_prefix('193', rows, problem, None), (rows[:2], 'remaining_lessons_deferred'))
        with self.assertRaises(Review):
            ready_prefix('194', rows, problem, None)
        with self.assertRaises(Review):
            ready_prefix('193', rows, Review('course_needs_review', [{'lesson_id': '3280', 'codes': ['empty_lesson']}]), None)


class ReviewedContentTests(unittest.TestCase):
    def test_only_owner_selected_material_buttons_are_omitted(self):
        for course_id, lesson_id, label in (
            ('63', '537', 'АУДИОЗАПИСЬ'),
            ('97', '1277', 'ПРЕЗЕНТАЦИЯ'),
        ):
            with self.subTest(lesson_id=lesson_id):
                button = {'name': 'button', 'fields': {
                    'html': label, 'linkType': 'url', 'url': 'https://example.test/material',
                }}
                video = {'name': 'video', 'fields': {'videoProvider': 'youtube'}}
                payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                           'course_id': course_id, 'lesson_id': '1',
                           'ape': {'name': 'page', 'children': [video, button]}}
                normalize_review(payload)
                self.assertEqual(payload['ape']['children'], [video, button])
                payload['lesson_id'] = lesson_id
                normalize_review(payload)
                self.assertEqual(payload['ape']['children'], [video])

    def test_reviewed_video_poster_is_omitted_without_changing_player(self):
        poster = 'https://youtu.be/aaaaaaaaaaa'
        player = 'https://youtu.be/bbbbbbbbbbb'
        fields = {'videoProvider': 'youtube', 'videoSrc': player, 'posterSrc': poster}
        video = {'name': 'video', 'fields': fields}
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '38', 'lesson_id': '1841', 'ape': {'name': 'page', 'children': [video]}}
        with patch('normalize_review.STALE_POSTER_DIGEST', hashlib.sha256(poster.encode()).hexdigest()):
            normalize_review(payload)
            self.assertEqual(fields, {'videoProvider': 'youtube', 'videoSrc': player})
            fields['posterSrc'] = 'https://example.test/poster.jpg'
            normalize_review(payload)
            self.assertEqual(fields['posterSrc'], 'https://example.test/poster.jpg')

    def test_drive_file_button_gets_https_and_empty_presentation_is_omitted(self):
        drive = 'drive.google.com/file/d/sample-id/view?usp=sharing'
        nodes = [
            {'name': 'button', 'fields': {'html': 'ПРЕЗЕНТАЦИЯ', 'linkType': 'url', 'url': ''}},
            {'name': 'button', 'fields': {'html': 'ПРЕЗЕНТАЦИЯ', 'linkType': 'url', 'url': drive}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': drive + '&extra=1'}},
        ]
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '74', 'lesson_id': '736', 'ape': {'name': 'page', 'children': nodes}}
        normalize_review(payload)
        self.assertEqual([node['fields']['url'] for node in payload['ape']['children']],
                         ['https://' + drive, drive + '&extra=1'])

    def test_table_repairs_keep_text_cells_and_links(self):
        source = '<table cellpadding="3"><tbody><tr><td valign="middle"><a id="start"></a>00:01</td>' \
                 '<td><a href="https://example.test/material">Материал</a></td></tr></tbody></table>'
        result = clean_timing_table(source)
        self.assertIn('<span id="start"></span>00:01', result)
        self.assertIn('<a href="https://example.test/material">Материал</a>', result)
        self.assertNotIn('cellpadding', result)
        self.assertNotIn('valign', result)

    def test_heading_keeps_its_link_and_blank_audio_is_omitted(self):
        heading = '<h4 style="text-align: center"><a href="https://example.test/audio">Аудио</a></h4>'
        nodes = [
            {'name': 'header', 'fields': {'anchor': '', 'format': 'h4', 'html': heading}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': ''}},
            {'name': 'button', 'fields': {'html': 'АУДИОЗАПИСЬ', 'linkType': 'url', 'url': 'https://example.test/audio'}},
        ]
        payload = {'account': 'iomp', 'source_origin': 'https://shop.iomp.ru', 'format': 'ape',
                   'course_id': '8', 'lesson_id': '32', 'course_title': 'Course', 'lesson_title': 'Lesson',
                   'ape': {'name': 'page', 'children': nodes}}
        normalize_review(payload)
        updated, button = payload['ape']['children']
        self.assertEqual((updated['name'], updated['fields']['html']), ('text', heading))
        self.assertEqual(button['fields']['url'], 'https://example.test/audio')
        self.assertIn('5296', EXCLUDED_LESSONS)
        self.assertIn('4396', EXCLUDED_LESSONS)
        payload.update(course_id='34', lesson_id='1792')
        normalize_review(payload)
        self.assertEqual(payload['ape']['children'], [updated])


class RefreshReceiptTests(unittest.TestCase):
    def test_new_full_snapshot_supersedes_only_earlier_partial_snapshots(self):
        course = Path('course-74')
        capture = course / '2026-11-18T18-04-00-000Z'
        old = course / 'refreshed' / '2026-11-18T18-03-00-000Z' / 'refresh-status.json'
        new = course / 'refreshed' / '2026-11-18T18-05-00-000Z' / 'refresh-status.json'
        with (patch.object(Path, 'glob', return_value=[old, new]),
              patch.object(Path, 'read_text', return_value=json.dumps({
                  'account': 'iomp', 'course_id': 74, 'lesson_ids': [714], 'refreshed': [714],
              })) as read):
            self.assertEqual(refreshed_lessons(capture, '74', [714]),
                             {'714': new.parent / 'lesson-714.json'})
            read.assert_called_once_with(encoding='utf-8')
            with self.assertRaisesRegex(Stop, 'refreshed_outline_mismatch'):
                refreshed_lessons(capture, '74', [714, 715])


class RetainedDraftTests(unittest.TestCase):
    source_ids = [337, 338, 340, 339, 341, 342, 344, 343, 345, 1942]

    def setUp(self):
        self.ids = list(map(str, self.source_ids))
        self.client = Mock(account=ACCOUNT, site=SITE)

    def outline(self, ids):
        return {'course': 'course', 'ids': list(ids),
                'by_id': {lid: {'name': 'doc-' + lid} for lid in ids}}

    def payloads(self):
        return [{'account': ACCOUNT, 'source_origin': ORIGIN, 'course_id': '60',
                 'course_title': 'Course', 'lesson_title': lid, 'lesson_id': lid,
                 'format': 'ape'} for lid in self.ids if lid != '345']

    def test_importer_previews_only_included_lessons_for_both_destination_states(self):
        payloads = self.payloads()
        active = [payload['lesson_id'] for payload in payloads]
        for ids in [self.ids, active]:
            with (self.subTest(retained='345' in ids),
                  patch.object(IompImporter, 'outline', return_value=self.outline(ids))):
                importer = Course60Importer(self.client, self.source_ids)
                with patch.object(importer, 'preview', return_value=({'action': 'already_imported'}, [])) as preview:
                    result = importer.import_course(payloads, apply=True)
                self.assertEqual(result['status'], 'already_present')
                self.assertEqual(result['created_lesson_ids'], [])
                self.assertEqual([call.args[0]['lesson_id'] for call in preview.call_args_list], active)
                self.assertEqual(importer.outline('60').get('retained_lesson_ids', []),
                                 ['345'] if '345' in ids else [])
                self.client.call.assert_not_called()

    def test_appends_only_missing_included_lesson_with_or_without_the_draft(self):
        for retain in [False, True]:
            ids = [lid for lid in self.ids[:-1] if retain or lid != '345']

            def create(_method, arguments):
                args = arguments['args']
                lid = args['payload']['lesson_id']
                self.assertIs(args['dry_run'], False)
                self.assertEqual(lid, '1942')
                ids.append(lid)
                return {'result': {'action': 'created', 'account': ACCOUNT, 'course_id': '60',
                                   'lesson_id': lid, 'dry_run': False}}

            def preview(payload, _images):
                action = 'already_imported' if payload['lesson_id'] in ids else 'create_lesson'
                return {'action': action}, []

            with (self.subTest(retain=retain), patch.object(self.client, 'call', side_effect=create) as write,
                  patch.object(IompImporter, 'outline', side_effect=lambda _: self.outline(ids)),
                  patch.object(Course60Importer, 'preview', side_effect=preview)):
                result = Course60Importer(self.client, self.source_ids).import_course(self.payloads(), apply=True)
                self.assertEqual(result['created_lesson_ids'], ['1942'])
                write.assert_called_once()
                self.assertEqual(ids, [lid for lid in self.ids if retain or lid != '345'])

    def test_changed_order_or_retained_record_fails_even_when_other_ids_are_unchanged(self):
        moved = self.ids.copy()
        moved[7], moved[8] = moved[8], moved[7]
        active = [lid for lid in self.ids if lid != '345']
        changed = self.outline(self.ids)
        changed['by_id']['345']['name'] = 'replacement'
        for before, after in [(self.ids, self.outline(moved)), (self.ids, self.outline(active)),
                              (active, self.outline(self.ids)), (self.ids, changed),
                              (self.ids, self.outline(self.ids + ['999']))]:
            with (self.subTest(after=after),
                  patch.object(IompImporter, 'outline', side_effect=[self.outline(before), after])):
                importer = Course60Importer(self.client, self.source_ids)
                with self.assertRaisesRegex(Review, 'course_order_conflict'):
                    importer.outline('60')


if __name__ == '__main__':
    unittest.main()
