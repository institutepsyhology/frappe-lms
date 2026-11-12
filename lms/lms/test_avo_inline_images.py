"""Pure inline-image source/file binding checks; no Frappe, I/O or decoder service."""
import base64
import copy
import hashlib
import struct
import unittest
from unittest.mock import patch
import zlib

from lms.lms import avo_transform as mod


def png():
    def chunk(kind, body):
        return len(body).to_bytes(4, 'big') + kind + body + (zlib.crc32(kind + body) & 0xffffffff).to_bytes(4, 'big')
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00\xff')) + chunk(b'IEND', b''))


def uri(raw=None, mime='image/png'):
    return 'data:' + mime + ';base64,' + base64.b64encode(png() if raw is None else raw).decode('ascii')


def private(raw=None, extension='png'):
    return '/private/files/avo-' + hashlib.sha256(png() if raw is None else raw).hexdigest() + '.' + extension


def payload(src):
    return {'account': 'mastervision', 'source_origin': 'https://shop.mastervision.su',
            'course_id': 618, 'lesson_id': 6887, 'course_title': 'Synthetic course', 'lesson_title': 'Synthetic lesson',
            'format': 'ape', 'ape': {'name': 'page', 'children': [
                {'name': 'image', 'id': 'picture', 'fields': {'imageSrc': src, 'anchor': ''}}]}}


class InlineImagesTests(unittest.TestCase):
    def test_real_png_is_replaced_only_by_exact_prepared_hash_url(self):
        source = payload(uri()); before = copy.deepcopy(source)
        result = mod.plan_import(source, {'picture': private()})
        self.assertTrue(result['ready'], result['issues'])
        self.assertEqual(result['blocks'][0]['data']['url'], private())
        self.assertEqual(source, before)
        self.assertNotIn('data:', str(result['blocks']))

    def test_missing_foreign_public_or_mismatched_prepared_url_never_becomes_ready(self):
        for url in (None, '/private/files/image.png', '/files/' + private().rsplit('/', 1)[-1],
                    private(b'other bytes'), private(extension='jpg'), private() + '?token=private',
                    '/private/files/../' + private().rsplit('/', 1)[-1],
                    'https://example.test' + private()):
            with self.subTest(url=url):
                result = mod.plan_import(payload(uri()), {} if url is None else {'picture': url})
                self.assertFalse(result['ready'])
                self.assertIn('unsupported_image_settings', result['issues'])

    def test_mime_and_format_magic_must_match_even_when_hash_matches(self):
        for value, target in ((uri(mime='image/jpeg'), private(extension='jpg')),
                              (uri(b'<svg/>'), private(b'<svg/>')),
                              (uri(b'<html>not an image</html>'), private(b'<html>not an image</html>'))):
            with self.subTest(value=value[:24]):
                result = mod.plan_import(payload(value), {'picture': target})
                self.assertFalse(result['ready'])
                self.assertIn('unsupported_image_settings', result['issues'])

    def test_jpeg_aliases_and_webp_magic_bind_to_expected_extension(self):
        # Full raster decoding belongs to avo_import._images; these synthetic
        # byte fixtures exercise only this pure magic/hash binding boundary.
        jpeg = b'\xff\xd8\xffsynthetic-prepared-jpeg\xff\xd9'
        webp = b'RIFF' + (12).to_bytes(4, 'little') + b'WEBPVP8Ltest'
        for raw, mime, extension in ((jpeg, 'image/jpeg', 'jpg'), (jpeg, 'image/jpg', 'jpg'),
                                      (webp, 'image/webp', 'webp')):
            with self.subTest(mime=mime):
                self.assertTrue(mod._image_source_valid(uri(raw, mime), private(raw, extension)))
                self.assertFalse(mod._image_source_valid(uri(raw, mime), private(raw, 'png')))

    def test_unsupported_mime_and_parameters_are_rejected_before_decode(self):
        encoded = base64.b64encode(png()).decode('ascii')
        with patch.object(mod.base64, 'b64decode', side_effect=AssertionError('must not allocate')) as decode:
            for header in ('data:image/svg+xml;base64,', 'data:text/html;base64,',
                           'data:image/png;charset=utf-8;base64,', 'data:image/PNG;base64,'):
                self.assertFalse(mod._image_source_valid(header + encoded, private()))
            decode.assert_not_called()

    def test_malformed_noncanonical_or_oversized_input_is_rejected_before_decode(self):
        encoded = base64.b64encode(png()).decode('ascii')
        alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        noncanonical = encoded[:-3] + alphabet[alphabet.index(encoded[-3]) + 1] + '=='
        with patch.object(mod.base64, 'b64decode', side_effect=AssertionError('must not allocate')) as decode:
            for value in (encoded.rstrip('='), encoded + '=', encoded[:4] + '\n' + encoded[4:], noncanonical):
                self.assertFalse(mod._image_source_valid('data:image/png;base64,' + value, private()))
            with patch.object(mod, 'MAX_INLINE_IMAGE', 32):
                for raw in (b'x' * 33, b'x' * 40):
                    self.assertFalse(mod._image_source_valid(uri(raw), private(raw)))
            decode.assert_not_called()

    def test_data_urls_remain_forbidden_for_links_buttons_and_general_urls(self):
        value = uri()
        self.assertFalse(mod._url(value))
        source = payload(value)
        source['ape']['children'] = [{'name': 'button', 'fields': {'linkType': 'url', 'html': 'Button', 'url': value}}]
        result = mod.plan_import(source)
        self.assertFalse(result['ready'])
        self.assertIn('unsupported_button', result['issues'])

    def test_existing_remote_image_path_and_invalid_image_keys_keep_old_behavior(self):
        source = payload('https://example.test/image.png')
        result = mod.plan_import(source, {'picture': '/private/files/prepared-image.png'})
        self.assertTrue(result['ready'], result['issues'])
        source['ape']['children'][0]['id'] = []
        result = mod.plan_import(source)
        self.assertFalse(result['ready'])
        self.assertIn('invalid_image', result['issues'])


if __name__ == '__main__': unittest.main()
