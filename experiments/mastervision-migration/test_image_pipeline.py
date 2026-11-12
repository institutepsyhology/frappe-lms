"""A real tiny raster crosses HTML extraction, cache decoding and core planning."""
import base64
import copy
import hashlib
from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch

from assets import AssetCache
from importer import Review
from normalize_source import normalize_payload
from lms.lms.avo_transform import plan_import
from test_assets import png
from test_normalize_source import payload


class ImagePipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parent / ('.test-image-pipeline-' + uuid.uuid4().hex)
        self.directory.mkdir(mode=0o777)

    def tearDown(self):
        expected = Path(__file__).resolve().parent
        if self.directory.resolve().parent != expected or self.directory.is_symlink():
            raise AssertionError('unsafe test cleanup')
        shutil.rmtree(self.directory)

    def test_inline_base64_png_becomes_a_prepared_image_between_unchanged_text(self):
        raw = png()
        uri = 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
        original = payload('<p>Before &amp; {name}<img alt="" src="' + uri + '">After <a href="https://example.test/">Link</a></p>')
        before = copy.deepcopy(original)
        normalized, _ = normalize_payload(original)
        image = normalized['ape']['children'][1]
        with AssetCache(self.directory) as cache:
            with patch.object(cache.opener, 'open', side_effect=AssertionError('base64 must never use network')):
                images = cache.lesson_images(normalized)
        self.assertEqual(base64.b64decode(images[image['id']]), raw)
        prepared = '/private/files/avo-' + hashlib.sha256(raw).hexdigest() + '.png'
        result = plan_import(normalized, {image['id']: prepared})
        self.assertTrue(result['ready'], result['issues'])
        self.assertEqual([block['type'] for block in result['blocks']], ['paragraph', 'image', 'paragraph'])
        self.assertEqual(result['blocks'][1]['data']['url'], prepared)
        self.assertNotIn('data:image', str(result['blocks']))
        self.assertEqual(normalized['source_original_ape'], before['ape'])
        self.assertEqual(original, before)

    def test_image_mime_spoof_is_rejected_before_it_can_become_a_lesson_block(self):
        uri = 'data:image/jpeg;base64,' + base64.b64encode(png()).decode('ascii')
        normalized, _ = normalize_payload(payload('<p><img src="' + uri + '">Keep text</p>'))
        with AssetCache(self.directory) as cache:
            with self.assertRaises(Review): cache.lesson_images(normalized)
