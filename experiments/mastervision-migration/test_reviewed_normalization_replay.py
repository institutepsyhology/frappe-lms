"""New reviewed witnesses retain raw source and replay with private audio receipts."""
import copy
import hashlib
import unittest
from unittest.mock import patch

from importer import Review
from normalize_source import normalize_payload
import normalize_remaining_static_material as static
import normalize_reviewed_legacy_players as players
import normalize_reviewed_text_fragments as text_fragments


class ReviewedNormalizationReplayTests(unittest.TestCase):
    @staticmethod
    def payload(ape):
        return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                'course_id': 990, 'lesson_id': 991, 'course_title': 'Synthetic course',
                'lesson_title': 'Synthetic lesson', 'format': 'ape', 'ape': ape}

    def test_v20_header_and_audio_replay_uses_exact_stored_receipt(self):
        html = '<h3><strong>Keep this title</strong></h3>'
        url = 'https://f1.autoweboffice.ru/files/100/replay.mp3'
        ape = {'name': 'page', 'children': [
            {'name': 'header', 'fields': {'html': html, 'anchor': '', 'format': 'h1'}},
            {'name': 'audio', 'fields': {'audioSrc': url, 'anchor': '', 'showLoopButton': True}}]}
        raw = self.payload(ape); original = copy.deepcopy(raw)
        sha = 'a' * 64
        assets = {hashlib.sha256(url.encode()).hexdigest(): {
            'file_url': '/private/files/avo-mastervision-audio-' + sha + '.mp3',
            'sha256': sha, 'md5': 'b' * 32, 'size': 123}}
        binding = { (990, 991): (((0,), hashlib.sha256(html.encode()).hexdigest(), 'header', 'header'),) }
        with patch.dict(static.APPROVED, binding):
            prepared, codes = normalize_payload(raw, assets)
            self.assertEqual(raw, original)
            self.assertEqual(prepared['source_original_ape'], ape)
            self.assertEqual(prepared['source_normalization']['version'], 20)
            self.assertEqual(prepared['source_normalization']['audio_assets'], assets)
            self.assertEqual(normalize_payload(prepared), (prepared, codes))
            for key in ('remaining_static_blocks', 'reviewed_legacy_player_blocks'):
                bad = copy.deepcopy(prepared)
                bad['source_normalization'][key] = [{'unexpected': 'material'}]
                with self.assertRaisesRegex(Review, 'normalization_metadata_conflict'):
                    normalize_payload(bad)

    def test_v20_mixed_youtube_witness_rejects_changed_output_or_original(self):
        html = ('<p><iframe src="https://www.youtube.com/embed/abcdefghijk" '
                'width="560" height="315" allowfullscreen></iframe></p>'
                '<p><a href="https://example.test/file">Presentation</a></p>')
        node = {'id': 'source', 'name': 'text', 'fields': {'html': html, 'anchor': ''}}
        raw = self.payload({'name': 'page', 'children': [node]})
        binding = {(990, 991): (((0,), players._sha(node), 'mixed_youtube', 1),)}
        original = copy.deepcopy(raw)
        with patch.dict(players.BINDINGS, binding):
            prepared, codes = normalize_payload(raw)
            self.assertEqual(raw, original)
            self.assertEqual(prepared['source_normalization']['version'], 20)
            self.assertEqual(normalize_payload(prepared), (prepared, codes))
            changed = copy.deepcopy(prepared)
            changed['ape']['children'][0]['children'][0]['fields']['videoSrc'] = 'https://youtu.be/12345678901'
            with self.assertRaisesRegex(Review, 'normalization_metadata_conflict'):
                normalize_payload(changed)
            changed = copy.deepcopy(prepared)
            changed['source_original_ape']['children'][0]['fields']['html'] += '<p>Changed source</p>'
            with self.assertRaises(Review):
                normalize_payload(changed)

    def test_material_or_identity_failure_stops_before_fallback_import(self):
        import run as controller
        import audit
        raw = self.payload({'name': 'page', 'children': []})
        for code in ('remaining_static_material_mismatch', 'remaining_static_source_invalid',
                     'reviewed_legacy_player_account_mismatch', 'reviewed_legacy_player_source_invalid',
                     'reviewed_text_source_invalid', 'reviewed_text_source_changed', 'reviewed_text_material_mismatch',
                     'reviewed_getcourse_source_changed', 'reviewed_getcourse_source_invalid',
                     'reviewed_getcourse_account_mismatch', 'reviewed_getcourse_validator_invalid',
                     'reviewed_getcourse_material_mismatch', 'reviewed_email_account_mismatch',
                     'reviewed_email_source_invalid', 'reviewed_email_material_mismatch',
                     'reviewed_keycap_account_mismatch', 'reviewed_keycap_source_invalid',
                     'reviewed_keycap_source_changed', 'reviewed_keycap_material_mismatch',
                     'owner_purchase_account_mismatch', 'owner_purchase_source_invalid', 'owner_purchase_source_changed',
                     'reviewed_intro_account_mismatch', 'reviewed_intro_source_invalid',
                     'reviewed_intro_source_changed', 'reviewed_intro_material_mismatch',
                     'reviewed_club_account_mismatch', 'reviewed_club_source_invalid',
                     'reviewed_club_source_changed', 'reviewed_club_material_mismatch',
                     'reviewed_shared_image_account_mismatch', 'reviewed_shared_image_source_invalid',
                     'reviewed_shared_image_source_changed', 'reviewed_shared_image_material_mismatch'):
            self.assertIn(code, audit.FATAL)
            with self.subTest(code=code), patch('normalize_source.normalize_payload', side_effect=Review(code)):
                with self.assertRaisesRegex(controller.Stop, '^' + code + '$'):
                    controller.prepare_payloads([raw])

    def test_v21_trainer_omission_retains_raw_and_audio_receipt(self):
        html = '<p><a href="https://example.test/ask">Задать вопрос тренеру курса Анне Ивановой</a></p>'
        url = 'https://f1.autoweboffice.ru/files/100/replay.mp3'
        raw = self.payload({'name':'page','children':[
            {'name':'text','fields':{'html':html}},
            {'name':'audio','fields':{'audioSrc':url,'anchor':''}}]})
        original = copy.deepcopy(raw); sha = 'a' * 64
        assets = {hashlib.sha256(url.encode()).hexdigest():{
            'file_url':'/private/files/avo-mastervision-audio-' + sha + '.mp3',
            'sha256':sha,'md5':'b' * 32,'size':123}}
        binding = {(990,991):(((0,),hashlib.sha256(html.encode()).hexdigest(),'trainer'),)}
        with patch.dict(text_fragments.APPROVED,binding):
            prepared, codes = normalize_payload(raw,assets)
            self.assertEqual(raw, original)
            self.assertEqual(prepared['source_original_ape'], original['ape'])
            self.assertEqual(prepared['source_normalization']['version'],21)
            self.assertEqual(normalize_payload(prepared),(prepared,codes))
            changed = copy.deepcopy(prepared)
            changed['source_normalization']['reviewed_text_blocks'][0]['removed_links'] = 0
            with self.assertRaisesRegex(Review,'normalization_metadata_conflict'):normalize_payload(changed)


if __name__ == '__main__':
    unittest.main()
