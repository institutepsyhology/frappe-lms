import hashlib
import io
import unittest
from unittest.mock import patch

from import_capture import Review
from jpeg_cover import prepare_jpeg_upload

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, 'Pillow required for real JPEG coverage')
class JpegUploadTests(unittest.TestCase):
    def sample(self, orientation=None):
        with Image.new('RGB', (12, 8)) as image:
            image.putdata([(x * 17, y * 23, (x + y) * 11) for y in range(8) for x in range(12)])
            exif = Image.Exif()
            if orientation:
                exif[274] = orientation
                exif[305] = 'test'
            target = io.BytesIO()
            image.save(target, format='JPEG', exif=exif, quality=91)
        return target.getvalue()

    def test_no_exif_is_identical_and_exif_is_removed_after_rotation(self):
        for orientation, size in [(None, (12, 8)), (1, (12, 8)), (6, (8, 12))]:
            with self.subTest(orientation=orientation):
                raw = self.sample(orientation)
                prepared = prepare_jpeg_upload(raw)
                if orientation:
                    self.assertNotEqual(raw, prepared)
                else:
                    self.assertEqual(raw, prepared)
                self.assertEqual(prepare_jpeg_upload(prepared), prepared)
                with Image.open(io.BytesIO(prepared)) as image:
                    self.assertEqual(image.size, size)
                    self.assertFalse(image.getexif())

    def test_compatible_with_existing_readback_witness(self):
        from covers import _stripped_jpeg_metadata
        raw = self.sample(8)
        prepared = prepare_jpeg_upload(raw)
        self.assertEqual((len(prepared), hashlib.md5(prepared).hexdigest()), _stripped_jpeg_metadata(raw))

    def test_missing_decoder_bad_image_and_incomplete_transform_fail_during_preparation(self):
        raw = self.sample(6)
        with patch.dict('sys.modules', {'PIL': None}):
            with self.assertRaisesRegex(Review, 'cover_transform_requires_pillow'):
                prepare_jpeg_upload(raw)
        with self.assertRaises(Review):
            prepare_jpeg_upload(raw[:-25])
        with patch('jpeg_cover.strip_jpeg_for_storage', return_value=raw):
            with self.assertRaisesRegex(Review, 'cover_jpeg_preparation_invalid'):
                prepare_jpeg_upload(raw)
