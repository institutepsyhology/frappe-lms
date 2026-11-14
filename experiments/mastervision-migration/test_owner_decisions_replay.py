"""Synthetic owner-decision witnesses preserve raw source and private receipts."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
from normalize_editor_nodes import _core
from normalize_source import normalize_payload
import normalize_owner_purchase_buttons as purchase
import normalize_reviewed_keycap_lesson as keycap


AUDIO = 'https://f1.autoweboffice.ru/files/100/owner-replay.mp3'
FRAME = ('<iframe src="https://www.youtube.com/embed/abcdefghijk?rel=0" width="560" height="315" '
         'allow="autoplay; encrypted-media; picture-in-picture" frameborder="0" allowfullscreen></iframe>')
MARK_STYLE = ('box-sizing: border-box; background: rgb(255, 214, 30); padding: 0.2rem 0.4rem; '
              'display: inline-block; line-height: 1; border-radius: 4px;')


def payload(ape, cid=990, lid=991):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': cid, 'lesson_id': lid, 'course_title': 'Synthetic course',
            'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': ape}


def audio_assets():
    digest = 'a' * 64
    return {hashlib.sha256(AUDIO.encode()).hexdigest(): {
        'file_url': '/private/files/avo-mastervision-audio-' + digest + '.mp3',
        'sha256': digest, 'md5': 'b' * 32, 'size': 123}}


def purchase_source():
    return payload({'name': 'page', 'children': [
        {'id': 'authored', 'name': 'text', 'fields': {'html': '<p>Keep the lesson text.</p>'}},
        {'id': 'obsolete', 'name': 'button', 'fields': {
            'html': 'Obsolete checkout', 'linkType': 'url', 'url': '{goods_ordering_123}'}, 'children': []},
        {'id': 'audio', 'name': 'audio', 'fields': {'audioSrc': AUDIO, 'anchor': '', 'showLoopButton': True}}]})


def purchase_binding(raw):
    return {(990, 991): (purchase._sha(raw['ape']),
        (((1,), purchase._sha(raw['ape']['children'][1])),))}


def keycap_source():
    markers = []
    for number in range(1, 4):
        source = 'https://' + 'vk.com/emoji/e/' + str(number) + 'e283a3.png'
        tag = '<img src="' + source + '" style="' + keycap.IMAGE_STYLE + '">'
        markers.append({'src_sha256': keycap._sha(source), 'tag_sha256': keycap._sha(tag),
                        'text': str(number), 'tag': tag})
    markup = (FRAME + '<p>' + markers[0]['tag'] + ' First material.</p><p>' + markers[1]['tag'] +
              ' <mark style="' + MARK_STYLE + '">Highlighted teaching text.</mark></p><p>' +
              markers[2]['tag'] + ' Third material. <a href="https://example.test/material">Keep link</a></p>')
    node = {'id': 'reviewed', 'name': 'text', 'fields': {'html': markup, 'anchor': ''}, 'style': {}}
    raw = payload({'name': 'page', 'children': [node]}, 130, 369)
    record = {'ape_sha256': keycap._digest(raw['ape']), 'node_sha256': keycap._digest(node),
              'html_sha256': keycap._sha(markup), 'style_sha256': keycap._digest(node['style']),
              'markers': [{k: value for k, value in item.items() if k != 'tag'} for item in markers]}
    return raw, {(130, 369): record}


class OwnerDecisionsReplayTests(unittest.TestCase):
    def test_v22_purchase_audio_keeps_full_raw_source_and_replays_private_receipts(self):
        raw = purchase_source(); original = copy.deepcopy(raw); assets = audio_assets()
        with patch.dict(purchase.APPROVED, purchase_binding(raw)):
            prepared, codes = normalize_payload(raw, assets)
            self.assertEqual(raw, original)
            self.assertEqual(prepared['source_original_ape'], original['ape'])
            witness = prepared['source_normalization']
            self.assertEqual(witness['version'], 22)
            self.assertEqual(witness['audio_assets'], assets)
            self.assertEqual(len(witness['owner_purchase_buttons']), 1)
            self.assertEqual(witness['owner_purchase_buttons'][0]['path'], [1])
            self.assertIn(purchase.CODE, codes)
            self.assertEqual(normalize_payload(prepared), (prepared, codes))
            self.assertEqual(normalize_payload(prepared, copy.deepcopy(assets)), (prepared, codes))
            self.assertTrue(_core().plan_import(prepared)['ready'])

    def test_purchase_audio_replay_rejects_conflicting_or_missing_receipts(self):
        raw = purchase_source(); assets = audio_assets()
        with patch.dict(purchase.APPROVED, purchase_binding(raw)):
            prepared, _ = normalize_payload(raw, assets)
            conflict = copy.deepcopy(assets)
            next(iter(conflict.values()))['md5'] = 'c' * 32
            for supplied in ({}, conflict):
                with self.subTest(supplied=bool(supplied)), self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                    normalize_payload(prepared, supplied)

    def test_purchase_witness_and_normalized_output_cannot_be_forged(self):
        raw = purchase_source()
        with patch.dict(purchase.APPROVED, purchase_binding(raw)):
            prepared, _ = normalize_payload(raw, audio_assets())
            bad = copy.deepcopy(prepared)
            bad['source_normalization']['owner_purchase_buttons'][0]['source_node_sha256'] = '0' * 64
            with self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                normalize_payload(bad)
            bad = copy.deepcopy(prepared)
            bad['ape']['children'][0]['fields']['html'] = '<p>Changed teaching content.</p>'
            with self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                normalize_payload(bad)

    def test_purchase_original_source_hash_is_not_bypassed_by_replay(self):
        raw = purchase_source()
        with patch.dict(purchase.APPROVED, purchase_binding(raw)):
            prepared, _ = normalize_payload(raw, audio_assets())
            bad = copy.deepcopy(prepared)
            bad['source_original_ape']['children'][1]['fields']['url'] = '{goods_ordering_999}'
            with self.assertRaises(Review): normalize_payload(bad)
            self.assertEqual(raw, purchase_source())

    def test_v22_keycap_replay_retains_raw_images_and_rejects_witness_or_source_tampering(self):
        raw, bindings = keycap_source(); original = copy.deepcopy(raw)
        with patch.dict(keycap.BINDINGS, bindings):
            prepared, codes = normalize_payload(raw)
            self.assertEqual(raw, original)
            self.assertEqual(prepared['source_original_ape'], original['ape'])
            witness = prepared['source_normalization']
            self.assertEqual(witness['version'], 22)
            self.assertEqual(witness['keycap_blocks'][0]['marker_text'], ['1', '2', '3'])
            self.assertIn(keycap.CODE, codes)
            self.assertEqual(normalize_payload(prepared), (prepared, codes))
            plan = _core().plan_import(prepared)
            self.assertTrue(plan['ready'], plan['issues'])
            self.assertEqual([block['type'] for block in plan['blocks']], ['videoChoice', 'htmlBlock'])
            bad = copy.deepcopy(prepared)
            bad['source_normalization']['keycap_blocks'][0]['marker_text'] = ['3', '2', '1']
            with self.assertRaisesRegex(Review, '^normalization_metadata_conflict$'):
                normalize_payload(bad)
            bad = copy.deepcopy(prepared)
            bad['source_original_ape']['children'][0]['fields']['html'] += '<p>Changed.</p>'
            with self.assertRaises(Review): normalize_payload(bad)

    def test_existing_audio_without_new_owner_changes_does_not_become_v22(self):
        raw = payload({'name': 'page', 'children': [
            {'name': 'audio', 'fields': {'audioSrc': AUDIO, 'anchor': ''}}]})
        prepared, codes = normalize_payload(raw, audio_assets())
        self.assertNotEqual(prepared['source_normalization']['version'], 22)
        self.assertEqual(normalize_payload(prepared), (prepared, codes))


if __name__ == '__main__': unittest.main()
