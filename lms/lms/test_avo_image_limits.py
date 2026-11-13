"""Synthetic bounded raster checks; no network, Frappe site or source images."""
import base64
import hashlib
import io
import struct
import sys
import types
import unittest
from unittest.mock import Mock, patch
import warnings
import zlib

from PIL import Image

fake = types.ModuleType('frappe')
fake.whitelist = lambda **kwargs: lambda function: function
fake.PermissionError = PermissionError
sys.modules.setdefault('frappe', fake)
from lms.lms import avo_import as module


def raster(width, height):
    """Stream a valid grayscale PNG without allocating a decoded pixel buffer."""
    def chunk(kind, body):
        return (len(body).to_bytes(4, 'big') + kind + body
                + (zlib.crc32(kind + body) & 0xffffffff).to_bytes(4, 'big'))
    compressor = zlib.compressobj()
    compressed = bytearray()
    row = b'\x00' * (width + 1)
    for _ in range(height):
        compressed.extend(compressor.compress(row))
    compressed.extend(compressor.flush())
    header = struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', bytes(compressed)) + chunk(b'IEND', b''))


def encoded(raw):
    return base64.b64encode(raw).decode('ascii')


class ImageLimitTests(unittest.TestCase):
    def test_tall_and_wide_original_bytes_are_accepted_without_resize(self):
        for size in ((2126, 6099), (6099, 2126)):
            with self.subTest(size=size):
                raw = raster(*size)
                result = module._images({'picture': encoded(raw)})['picture']
                digest = hashlib.sha256(raw).hexdigest()
                self.assertEqual(result, {'bytes': raw, 'sha256': digest,
                                         'name': 'avo-' + digest + '.png'})
                with Image.open(io.BytesIO(result['bytes'])) as image:
                    self.assertEqual(image.size, size)
                    image.verify()

    def test_exact_dimension_and_area_boundaries_keep_the_previous_maximum_area(self):
        self.assertEqual(module.MAX_IMAGE, 5 * 1024 * 1024)
        self.assertEqual(module.MAX_IMAGE_DIMENSION, 8192)
        self.assertEqual(module.MAX_IMAGE_PIXELS, 4096 * 4096)
        for size in ((4096, 4096), (8192, 2048), (2048, 8192), (8192, 1), (1, 8192)):
            with self.subTest(size=size):
                self.assertIn('picture', module._images({'picture': encoded(raster(*size))}))

    def test_one_pixel_over_either_dimension_or_area_is_rejected(self):
        for size in ((8193, 1), (1, 8193), (4096, 4097), (8192, 2049), (2049, 8192)):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, '^image_invalid$'):
                module._images({'picture': encoded(raster(*size))})

    def test_area_comparison_is_inclusive_at_the_exact_integer_pixel_budget(self):
        with patch.object(module, 'MAX_IMAGE_PIXELS', 8):
            self.assertIn('picture', module._images({'picture': encoded(raster(4, 2))}))
            with self.assertRaisesRegex(ValueError, '^image_invalid$'):
                module._images({'picture': encoded(raster(3, 3))})

    def test_oversized_header_is_rejected_before_verify_or_pixel_loading(self):
        for size in ((8193, 1), (4096, 4097), (0, 1), (1, -1)):
            image = Mock(format='PNG', size=size)
            image.__enter__ = Mock(return_value=image)
            image.__exit__ = Mock(return_value=False)
            with self.subTest(size=size), patch.object(module.Image, 'open', return_value=image):
                with self.assertRaisesRegex(ValueError, '^image_invalid$'):
                    module._images({'picture': encoded(b'bounded header fixture')})
            image.verify.assert_not_called()
            image.load.assert_not_called()

    def test_encoded_size_is_checked_before_decode_and_raw_size_before_image_open(self):
        with patch.object(module, 'MAX_IMAGE', 32):
            with patch.object(module.base64, 'b64decode', side_effect=AssertionError('decode called')) as decode:
                with self.assertRaisesRegex(ValueError, '^image_too_large$'):
                    module._images({'picture': encoded(b'x' * 34)})
                decode.assert_not_called()
            with patch.object(module.Image, 'open', side_effect=AssertionError('image opened')) as opened:
                # 33 bytes share the encoded-length boundary with 32 bytes.
                with self.assertRaisesRegex(ValueError, '^image_size_invalid$'):
                    module._images({'picture': encoded(b'x' * 33)})
                opened.assert_not_called()

    def test_nonimages_corruption_and_unsupported_raster_format_stay_rejected(self):
        gif = io.BytesIO()
        Image.new('L', (1, 1)).save(gif, format='GIF')
        broken = bytearray(raster(2, 2))
        broken[broken.index(b'IDAT') + 4] ^= 1
        for raw in (b'<html>not an image</html>', bytes(broken), gif.getvalue()):
            with self.subTest(kind=raw[:8]), self.assertRaisesRegex(ValueError, '^image_invalid$'):
                module._images({'picture': encoded(raw)})

    def test_pillow_decode_bomb_warning_and_error_stay_fatal(self):
        def warn(*args, **kwargs):
            warnings.warn('synthetic bomb', Image.DecompressionBombWarning)
            raise AssertionError('warning was not fatal')
        for failure in (warn, Image.DecompressionBombError('synthetic bomb')):
            with self.subTest(kind=type(failure).__name__), patch.object(module.Image, 'open', side_effect=failure):
                with self.assertRaisesRegex(ValueError, '^image_invalid$'):
                    module._images({'picture': encoded(raster(1, 1))})

    def test_tall_encoded_image_has_a_read_only_draft_import_plan(self):
        raw = raster(2126, 6099)
        source = {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
                  'course_id': 900001, 'lesson_id': 900002, 'course_title': 'Synthetic course',
                  'lesson_title': 'Synthetic lesson', 'format': 'preview',
                  'content': [{'type': 'image', 'image_key': 'picture', 'caption': ''}]}
        field = types.SimpleNamespace(fieldtype='Data', length=512)
        meta = types.SimpleNamespace(has_field=lambda name: True, get_field=lambda name: field)
        with patch.multiple(module.frappe, create=True,
                local=types.SimpleNamespace(site='my-lk.mastervision.su'),
                only_for=Mock(), get_meta=lambda doctype: meta,
                get_all=lambda *args, **kwargs: [],
                get_doc=Mock(side_effect=AssertionError('document accessed'))), \
                patch.object(module, '_take_lock', side_effect=AssertionError('write lock taken')):
            result = module.import_lesson(source, {'picture': encoded(raw)}, dry_run=True)
        self.assertTrue(result['ready'])
        self.assertTrue(result['dry_run'])
        self.assertFalse(result['source_complete'])
        self.assertEqual(result['action'], 'create_course_and_lesson')


if __name__ == '__main__':
    unittest.main()
