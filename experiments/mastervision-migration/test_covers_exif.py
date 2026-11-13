"""Real synthetic JPEG/EXIF cover integrity checks; no site or private images."""
import base64
import copy
import hashlib
import io
import unittest
from unittest.mock import patch

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

import covers
from importer import Review, Stop
from test_covers import Client


def jpeg(orientation=None, exif=True):
    image = Image.new('RGB', (12, 8))
    image.putdata([(x * 17, y * 29, (x + y) * 11) for y in range(8) for x in range(12)])
    metadata = Image.Exif()
    if exif:
        metadata[305] = 'Synthetic test fixture'
        if orientation is not None:
            metadata[274] = orientation
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=91, exif=metadata)
    image.close()
    return output.getvalue()


def frappe_stripped(raw):
    # Independent fixture for the verified public Frappe transformation.
    with Image.open(io.BytesIO(raw)) as original:
        if not original.getexif():
            return raw
        image = ImageOps.exif_transpose(original)
        try:
            output = io.BytesIO()
            image.save(output, format='jpeg', exif=b'')
            return output.getvalue()
        finally:
            image.close()


def document(source, saved=None):
    saved = source if saved is None else saved
    filename = 'avo-mastervision-course-618-' + hashlib.sha256(source).hexdigest()[:16] + '.jpg'
    return {'doctype': 'File', 'name': 'existing-cover', 'file_name': filename,
            'file_url': '/files/' + filename, 'is_private': 0, 'attached_to_doctype': 'LMS Course',
            'attached_to_name': 'target-course', 'attached_to_field': 'image',
            'file_size': len(saved), 'content_hash': hashlib.md5(saved, usedforsecurity=False).hexdigest()}


class JpegClient(Client):
    def rpc(self, method, params):
        if params['name'] != 'create_document':
            return super().rpc(method, params)
        self.mutations.append(('create_document', copy.deepcopy(params['arguments'])))
        arguments = params['arguments']; data = arguments['data']
        source = base64.b64decode(data['content'], validate=True)
        value = document(source, frappe_stripped(source))
        assert value['file_name'] == data['file_name']
        self.files.append(value)
        return {'structuredContent': copy.deepcopy(value)}


@unittest.skipUnless(Image is not None, 'Pillow is required for EXIF cover tests')
class ExifCoverTests(unittest.TestCase):
    def test_existing_transformed_file_reused_then_repeat_is_idempotent(self):
        source = jpeg(); before = bytes(source)
        client = Client(); client.files = [document(source, frappe_stripped(source))]
        content = covers._content(client.course)
        first = covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(first['status'], 'updated')
        self.assertFalse(first['file_created'])
        self.assertEqual([tool for tool, _ in client.mutations], ['update_document'])
        self.assertEqual(len(client.files), 1)
        self.assertEqual(covers._content(client.course), content)
        client.mutations.clear()
        second = covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(second['status'], 'already_imported')
        self.assertEqual(client.mutations, [])
        self.assertEqual(source, before)

    def test_orientation_is_applied_before_stripping_and_owned_file_reused(self):
        source = jpeg(orientation=6); saved = frappe_stripped(source)
        with Image.open(io.BytesIO(saved)) as image:
            self.assertEqual(image.size, (8, 12))
            self.assertFalse(image.getexif())
        client = Client(); client.files = [document(source, saved)]
        result = covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual([tool for tool, _ in client.mutations], ['update_document'])

    def test_first_upload_accepts_exact_frappe_transform_without_changing_original_name(self):
        source = jpeg(orientation=8); client = JpegClient()
        result = covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(result['status'], 'created')
        self.assertEqual([tool for tool, _ in client.mutations], ['create_document', 'update_document'])
        self.assertIn(hashlib.sha256(source).hexdigest()[:16], client.files[0]['file_name'])
        self.assertEqual(len(client.files), 1)

    def test_arbitrary_other_saved_bytes_or_wrong_size_remain_fatal(self):
        source = jpeg(); transformed = frappe_stripped(source)
        for field, value in [('content_hash', '0' * 32), ('file_size', len(transformed) + 1)]:
            client = Client(); file = document(source, transformed); file[field] = value; client.files = [file]
            with self.subTest(field=field), self.assertRaisesRegex(Stop, '^cover_file_readback_invalid$'):
                covers.sync_cover(client, 618, source, 'jpg', apply=True)
            self.assertEqual(client.mutations, [])
            self.assertIsNone(client.course['image'])

    def test_no_exif_source_cannot_authorize_an_arbitrary_jpeg_resave(self):
        source = jpeg(exif=False)
        with Image.open(io.BytesIO(source)) as image:
            self.assertFalse(image.getexif())
            output = io.BytesIO(); image.save(output, format='JPEG', quality=75)
        saved = output.getvalue(); self.assertNotEqual(saved, source)
        client = Client(); client.files = [document(source, saved)]
        with self.assertRaisesRegex(Stop, '^cover_file_readback_invalid$'):
            covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(client.mutations, [])

    def test_other_jpeg_quality_is_rejected_even_for_an_exif_source(self):
        source = jpeg()
        with Image.open(io.BytesIO(source)) as image:
            output = io.BytesIO(); image.save(output, format='JPEG', quality=95, exif=b'')
        saved = output.getvalue(); self.assertNotEqual(saved, frappe_stripped(source))
        client = Client(); client.files = [document(source, saved)]
        with self.assertRaisesRegex(Stop, '^cover_file_readback_invalid$'):
            covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(client.mutations, [])

    def test_wrong_readback_attachment_stays_fatal_before_course_update(self):
        source = jpeg(); client = Client(); client.files = [document(source, frappe_stripped(source))]
        client.bad_file_readback = True
        with self.assertRaisesRegex(Stop, '^cover_file_readback_invalid$'):
            covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(client.mutations, [])

    def test_missing_pillow_is_fixed_review_only_when_transform_needed(self):
        source = jpeg(); saved = frappe_stripped(source)
        original_import = __import__
        def no_pillow(name, *args, **kwargs):
            if name == 'PIL' or name.startswith('PIL.'):
                raise ImportError('synthetic unavailable dependency')
            return original_import(name, *args, **kwargs)
        client = Client(); client.files = [document(source, saved)]
        with patch('builtins.__import__', side_effect=no_pillow):
            with self.assertRaisesRegex(Review, '^cover_transform_requires_pillow$'):
                covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(client.mutations, [])
        client.files = [document(source)]; client.mutations.clear()
        with patch('builtins.__import__', side_effect=no_pillow):
            result = covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(result['status'], 'updated')
        self.assertEqual([tool for tool, _ in client.mutations], ['update_document'])

    def test_transform_fallback_does_not_bypass_concurrent_update_guard(self):
        source = jpeg(); client = Client(); client.files = [document(source, frappe_stripped(source))]
        client.race_at_update = True
        with self.assertRaisesRegex(Stop, '^cover_write_uncertain$'):
            covers.sync_cover(client, 618, source, 'jpg', apply=True)
        self.assertEqual(client.course['image'], '/files/manual-cover.png')
        self.assertEqual([tool for tool, _ in client.mutations], ['update_document'])


if __name__ == '__main__':
    unittest.main()
