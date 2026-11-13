import copy
import hashlib
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import normalize_reviewed_image_rotation as subject
import normalize_source
from normalize_image_wrapper_layout import normalize_image_wrapper_layout
from normalize_inline_images import normalize_inline_images
from importer import Review


URL = 'https://example.org/synthetic-image.png'
OUTER = '<span style="transform:rotate(3.14rad)"><span style="display:inline-block;height:20px"><img src="' + URL + '" width="30" height="20"></span></span>'
HTML = '<p>Keep every word.</p>' + OUTER + '<p><a href="https://example.org/material">Keep document</a></p>'


def ape(html=HTML):
    return {'name': 'page', 'fields': {}, 'children': [
        {'id': 'first', 'name': 'text', 'fields': {'html': '<p>First</p>'}},
        {'id': 'second', 'name': 'text', 'fields': {'html': '<p>Second</p>'}},
        {'id': 'reviewed', 'name': 'text', 'fields': {'anchor': '', 'html': html}, 'style': {}}]}


def constants(html=HTML, outer=OUTER, url=URL):
    stack = ExitStack()
    for key, value in [('HTML_SHA', html), ('OUTER_SHA', outer), ('URL_SHA', url)]:
        stack.enter_context(patch.object(subject, key, hashlib.sha256(value.encode()).hexdigest()))
    return stack



class RotationTests(unittest.TestCase):
    def test_v18_integrated_original_witness_audio_and_exact_replay(self):
        from test_normalize_audio import audio,key,receipt
        data={'account':'mastervision','source_origin':'https://shop.mastervision.su',
              'course_id':520,'lesson_id':5176,'course_title':'Synthetic','lesson_title':'Synthetic',
              'format':'ape','ape':ape()}
        data['ape']['children'].append(audio());before=copy.deepcopy(data)
        with constants():
            normalized,codes=normalize_source.normalize_payload(data,{key():receipt()})
            self.assertEqual(normalized['source_normalization']['version'],18)
            self.assertEqual(normalized['source_normalization']['reviewed_image_rotations'],[subject._receipt()])
            self.assertEqual(normalized['source_original_ape'],data['ape'])
            self.assertEqual(normalize_source.normalize_payload(normalized),(normalized,codes))
        self.assertEqual(data,before)

    def test_exact_span_edit_preserves_all_other_bytes_and_source(self):
        original = ape(); before = copy.deepcopy(original)
        with constants():
            result, changes = subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator())
            self.assertEqual(changes, [subject._receipt()])
        self.assertEqual(original, before)
        self.assertEqual(result['children'][:2], original['children'][:2])
        self.assertEqual(result['children'][2]['fields']['html'], HTML.replace('<span style="transform:rotate(3.14rad)">', '<span>', 1))

    def test_other_scope_changed_hash_and_idempotence_are_unchanged(self):
        original = ape()
        with constants():
            for cid, lid in [(519, 5176), (520, 5177), (True, 5176)]:
                self.assertEqual(subject.normalize_reviewed_image_rotation(original, cid, lid, normalize_source.static_validator()), (original, []))
            revised = ape(HTML + '<p>New material</p>')
            self.assertEqual(subject.normalize_reviewed_image_rotation(revised, 520, 5176, normalize_source.static_validator()), (revised, []))
            result, _ = subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator())
            self.assertEqual(subject.normalize_reviewed_image_rotation(result, 520, 5176, normalize_source.static_validator()), (result, []))

    def test_conditions_anchors_and_actions_cannot_be_transformed(self):
        for target, key, value in [('root', 'event', 'purchase'), ('root', 'visibleConditions', {}),
                                   ('child', 'anchor', 'keep'), ('child', 'visibleConditions', None),
                                   ('child', 'event', 'action')]:
            original = ape(); node = original if target == 'root' else original['children'][2]
            node['fields'][key] = value
            with constants(), self.subTest(key=key):
                self.assertEqual(subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator()), (original, []))

    def test_caption_extra_attribute_duplicate_and_unknown_rotation_are_refused(self):
        for altered in [OUTER.replace('<img', 'Authored caption<img'),
                        OUTER.replace('<span style=', '<span title="Keep" style=', 1),
                        OUTER + OUTER, OUTER.replace('3.14rad', '90deg')]:
            html = HTML.replace(OUTER, altered)
            with constants(html, altered), self.subTest(html=html), self.assertRaises(Review):
                subject.normalize_reviewed_image_rotation(ape(html), 520, 5176, normalize_source.static_validator())

    def test_changed_source_or_outer_hash_refuses_rotation(self):
        with constants(), patch.object(subject, 'OUTER_SHA', '0' * 64), self.assertRaises(Review):
            subject.normalize_reviewed_image_rotation(ape(), 520, 5176, normalize_source.static_validator())
        with constants(), patch.object(subject, 'URL_SHA', '0' * 64), self.assertRaises(Review):
            subject.normalize_reviewed_image_rotation(ape(), 520, 5176, normalize_source.static_validator())

    def test_manual_full_pipeline_preserves_all_four_source_images(self):
        from lms.lms.avo_transform import plan_import
        from normalize_inline_images import Document
        other = ''.join('<img src="https://example.org/other-' + str(i) + '.png" width="30" height="20">' for i in range(3))
        html = other + HTML
        original = ape(html); before = copy.deepcopy(original)
        with constants(html):
            result, changes = subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator())
            self.assertEqual(changes[0]['action'], 'omit_css_rotation')
            self.assertIs(changes[0]['source_image_unchanged'], True)
        self.assertEqual(original, before)
        wrapped, _ = normalize_image_wrapper_layout(result, normalize_source.static_validator())
        split, _ = normalize_inline_images(wrapped, normalize_source.static_validator())
        source_urls = [image.attrs['src'] for image in Document(html).images]
        def images(node):
            if node.get('name') == 'image': yield node['fields']['imageSrc']
            for child in node.get('children', []): yield from images(child)
        self.assertEqual(list(images(split)), source_urls)
        self.assertEqual(len(source_urls), 4)
        payload = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                   'course_id': 520, 'lesson_id': 5176, 'course_title': 'Synthetic', 'lesson_title': 'Synthetic',
                   'format': 'ape', 'ape': split}
        def nodes(node):
            yield node
            for child in node.get('children', []): yield from nodes(child)
        prepared_images = {node['id']: '/private/files/synthetic-image.png'
                           for node in nodes(split) if node.get('name') == 'image'}
        self.assertTrue(plan_import(payload, image_urls=prepared_images)['ready'])

    def test_receipt_has_no_urls_or_binary_transform_contract(self):
        import json
        with constants():
            result, changes = subject.normalize_reviewed_image_rotation(ape(), 520, 5176, normalize_source.static_validator())
        self.assertEqual(changes[0]['code'], 'owner_reviewed_image_rotation_omitted')
        self.assertIs(changes[0]['source_image_unchanged'], True)
        self.assertNotIn('https:', json.dumps(changes))
        self.assertFalse(hasattr(subject, 'rotate_reviewed_asset'))
        self.assertFalse(hasattr(subject, '_rotate'))

    def test_only_expected_original_path_is_allowed(self):
        original = ape(); original['children'][0], original['children'][2] = original['children'][2], original['children'][0]
        with constants():
            self.assertEqual(subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator()), (original, []))

    def test_material_mismatch_is_fatal_and_source_stays_unchanged(self):
        original = ape(); before = copy.deepcopy(original)
        with constants(), patch.object(subject, '_material', side_effect=[['source'], ['different']]):
            with self.assertRaisesRegex(Review, 'reviewed_rotation_material_mismatch'):
                subject.normalize_reviewed_image_rotation(original, 520, 5176, normalize_source.static_validator())
        self.assertEqual(original, before)


if __name__ == '__main__': unittest.main()
