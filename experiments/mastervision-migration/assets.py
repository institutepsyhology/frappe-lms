"""Anonymous, allowlisted Master Vision image downloads and private asset cache.

Only the private SQLite index retains source URLs. Blob names are content
hashes; no source URLs or image bytes are emitted as diagnostics.
"""
import base64
import binascii
from contextlib import closing
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import warnings
import zlib

from importer import ACCOUNT, ORIGIN, Review
from avatar_placeholders import _decoded_safe_path

MAX_IMAGE = 5 * 1024 * 1024
MAX_IMAGES = 10
PLACEHOLDER_IMAGE_SHA256 = '44c98968db4973a119db3bbc00ca36392c1466e1b631596e1fff0ac4a2474ea2'
IMAGE_KEY = re.compile(r'[A-Za-z0-9_-]{1,80}')
DATA_MIMES = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/webp': 'webp'}
BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'


def _binding():
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('asset_account_mismatch')


def _url(value):
    _binding()
    if not isinstance(value, str) or not value or len(value) > 8192 or re.search(r'[\x00-\x20\x7f\\]', value):
        raise Review('asset_url_invalid')
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.username is not None or url.password is not None
                or url.port is not None or url.fragment):
            raise ValueError()
    except ValueError: raise Review('asset_url_invalid') from None
    decoded_ru = _decoded_safe_path(url.path) if url.hostname == 'f1.autoweboffice.ru' else None
    verified_ru = bool(decoded_ru and not url.query and '?' not in value and '#' not in value
                       and re.search(r'\.(?:jpe?g|png|webp)$', decoded_ru, re.I))
    verified_getcourse = (url.hostname == 'fs-thb01.getcourse.ru' and not url.query and
        re.fullmatch(r'/fileservice/file/thumbnail/h/[a-f0-9]{32}\.png/s/f[0-9]{4}x/a/[0-9]{5}/sc/[0-9]{3}', url.path))
    if (url.hostname != 'shop.mastervision.su' and
            not re.fullmatch(r'f[0-9]+\.autoweboffice\.com', url.hostname or '')
            and not verified_ru and not verified_getcourse):
        raise Review('asset_host_requires_review')
    # Preserve percent-encoded source paths byte for byte; do not rewrite the
    # original URL into its decoded form before an anonymous CDN request.
    return value if verified_ru else url.geturl()


def _data_image(value):
    """Validate canonical base64 and decoded size before allocating image bytes."""
    _binding()
    if not isinstance(value, str): raise Review('asset_data_uri_invalid')
    prefixes = {f'data:{mime};base64,': mime for mime in DATA_MIMES}
    maximum = max(map(len, prefixes)) + 4 * ((MAX_IMAGE + 2) // 3)
    if len(value) > maximum: raise Review('asset_image_size_invalid')
    prefix = next((prefix for prefix in prefixes if value.startswith(prefix)), None)
    if prefix is None: raise Review('asset_data_uri_type_invalid')
    encoded = value[len(prefix):]
    if not encoded or len(encoded) % 4 or not re.fullmatch('[A-Za-z0-9+/]+={0,2}', encoded):
        raise Review('asset_data_uri_invalid')
    padding = 2 if encoded.endswith('==') else 1 if encoded.endswith('=') else 0
    size = len(encoded) // 4 * 3 - padding
    if not 1 <= size <= MAX_IMAGE: raise Review('asset_image_size_invalid')
    # validate=True alone accepts nonzero unused pad bits; reject those without
    # decoding/re-encoding or allocating a second encoded copy of the source.
    if ((padding == 2 and BASE64_ALPHABET.index(encoded[-3]) & 15) or
            (padding == 1 and BASE64_ALPHABET.index(encoded[-2]) & 3)):
        raise Review('asset_data_uri_invalid')
    return prefixes[prefix], encoded


def _image_source(value):
    if isinstance(value, str) and value.startswith('data:'):
        _data_image(value)
        return value
    return _url(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _magic(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, size, found_data = 8, None, False
        while offset + 12 <= len(raw):
            length = int.from_bytes(raw[offset:offset + 4], 'big')
            kind = raw[offset + 4:offset + 8]; end = offset + 12 + length
            if end > len(raw): break
            content = raw[offset + 8:end - 4]
            if zlib.crc32(kind + content) & 0xffffffff != int.from_bytes(raw[end - 4:end], 'big'): break
            if offset == 8:
                if kind != b'IHDR' or length != 13: break
                size = struct.unpack('>II', content[:8])
            if kind == b'IDAT': found_data = True
            if kind == b'IEND':
                if length == 0 and end == len(raw) and size and found_data: return 'png', size
                break
            offset = end
    elif raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):
        offset = 2
        while offset + 4 <= len(raw) and raw[offset] == 255:
            marker = raw[offset + 1]; offset += 2
            if marker == 255: offset -= 1; continue
            if marker in (0xd8, 0xd9, 0x01) or 0xd0 <= marker <= 0xd7: continue
            length = int.from_bytes(raw[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(raw): break
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf) and length >= 8:
                height, width = struct.unpack('>HH', raw[offset + 3:offset + 7])
                return 'jpg', (width, height)
            if marker == 0xda: break
            offset += length
    elif len(raw) >= 25 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' and int.from_bytes(raw[4:8], 'little') == len(raw) - 8:
        kind = raw[12:16]
        if kind == b'VP8X' and len(raw) >= 30:
            return 'webp', (int.from_bytes(raw[24:27], 'little') + 1, int.from_bytes(raw[27:30], 'little') + 1)
        if kind == b'VP8L' and raw[20] == 0x2f:
            bits = int.from_bytes(raw[21:25], 'little')
            return 'webp', ((bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1)
        if kind == b'VP8 ' and len(raw) >= 30 and raw[23:26] == b'\x9d\x01\x2a':
            width, height = struct.unpack('<HH', raw[26:30])
            return 'webp', (width & 0x3fff, height & 0x3fff)
    raise Review('asset_image_invalid')


def _inspect(raw, content_type=''):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_IMAGE: raise Review('asset_image_size_invalid')
    extension, size = _magic(raw)
    if any(not 1 <= dimension <= 4096 for dimension in size): raise Review('asset_image_dimensions_invalid')
    expected = {'png':'image/png', 'jpg':'image/jpeg', 'webp':'image/webp'}[extension]
    content_type = content_type.split(';', 1)[0].strip().lower()
    if content_type not in ('', 'application/octet-stream', 'binary/octet-stream', expected,
                            'image/jpg' if extension == 'jpg' else expected):
        raise Review('asset_content_type_invalid')
    try:
        from PIL import Image
    except ImportError:
        # The Frappe endpoint verifies complete image decoding with Pillow too.
        return extension
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != {'png':'PNG','jpg':'JPEG','webp':'WEBP'}[extension] or image.size != size:
                    raise ValueError()
                image.verify()
    except Exception: raise Review('asset_image_invalid') from None
    return extension


def _placeholder(node):
    if node.get('name') != 'image' or node.get('children', []): return False
    if any(value not in (None, '', False, [], {}) for key, value in node.items()
           if key not in ('id', 'name', 'fields', 'children', 'style')): return False
    fields = node.get('fields')
    return (isinstance(fields, dict) and not set(fields) - {'anchor', 'imageSrc'}
            and fields.get('anchor') in ('', None) and isinstance(fields.get('imageSrc'), str)
            and hashlib.sha256(fields['imageSrc'].encode()).hexdigest() == PLACEHOLDER_IMAGE_SHA256)


def _blob(path, size, digest):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size: raise Review('asset_cache_invalid')
    with path.open('rb') as stream: raw = stream.read(MAX_IMAGE + 1)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest: raise Review('asset_cache_invalid')
    return raw


class AssetCache:
    def __init__(self, directory):
        _binding(); selected = Path(directory)
        if selected.is_symlink(): raise Review('asset_cache_invalid')
        self.directory = selected.resolve(); self.db = None
        path = self.directory / 'assets.sqlite'
        if path.is_symlink(): raise Review('asset_cache_invalid')
        if path.exists():
            try:
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    if db.execute('SELECT account,origin FROM meta').fetchall() != [(ACCOUNT, ORIGIN)]:
                        raise Review('asset_cache_account_mismatch')
            except sqlite3.Error: raise Review('asset_cache_invalid') from None
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o777 if os.name == 'nt' else 0o700)
        if os.name != 'nt': os.chmod(self.directory, 0o700)
        self.db = sqlite3.connect(path, timeout=5); self.db.row_factory = sqlite3.Row
        try:
            if os.name != 'nt': os.chmod(path, 0o600)
            self.db.executescript('CREATE TABLE IF NOT EXISTS meta(account TEXT,origin TEXT);'
                'CREATE TABLE IF NOT EXISTS assets(url_hash TEXT PRIMARY KEY,url TEXT NOT NULL,'
                'digest TEXT NOT NULL,extension TEXT NOT NULL,size INTEGER NOT NULL);')
            if not self.db.execute('SELECT 1 FROM meta').fetchone(): self.db.execute('INSERT INTO meta VALUES(?,?)',(ACCOUNT,ORIGIN))
            self.db.commit()
            self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            self.opener.addheaders = []
        except Exception:
            self.close(); raise Review('asset_cache_invalid') from None

    def close(self):
        db, self.db = self.db, None
        if db is not None: db.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def _cached(self, url, key):
        row = self.db.execute('SELECT * FROM assets WHERE url_hash=?', (key,)).fetchone()
        if row is None: return None
        if (row['url'] != url or not re.fullmatch('[0-9a-f]{64}', row['digest'])
                or row['extension'] not in ('png','jpg','webp') or type(row['size']) is not int
                or not 1 <= row['size'] <= MAX_IMAGE): raise Review('asset_cache_invalid')
        path = self.directory / (row['digest'] + '.' + row['extension'])
        raw = _blob(path, row['size'], row['digest'])
        if _inspect(raw) != row['extension']: raise Review('asset_cache_invalid')
        return raw, row['extension']

    def fetch(self, url):
        if isinstance(url, str) and url.startswith('data:'):
            inline = _data_image(url)
        else:
            url, inline = _url(url), None
        key = hashlib.sha256(url.encode()).hexdigest()
        # The original data URI remains in the source archive. Keep only its
        # identity in this private index instead of duplicating a large payload.
        indexed_url = f'data:{inline[0]};sha256,{key}' if inline else url
        cached = self._cached(indexed_url, key)
        if cached is not None and inline:
            if _inspect(cached[0], inline[0]) != DATA_MIMES[inline[0]]: raise Review('asset_cache_invalid')
        if cached is not None: return cached
        if shutil.disk_usage(self.directory).free < 16 * 1024 * 1024: raise Review('asset_cache_space_low')
        if inline:
            try: raw = base64.b64decode(inline[1], validate=True)
            except (binascii.Error, ValueError): raise Review('asset_data_uri_invalid') from None
            extension = _inspect(raw, inline[0])
            if extension != DATA_MIMES[inline[0]]: raise Review('asset_content_type_invalid')
        else:
            request = urllib.request.Request(url, headers={'Accept':'image/png,image/jpeg,image/webp',
                                                          'User-Agent':'MasterVisionAssetCache/1.0'})
            try:
                with self.opener.open(request, timeout=25) as response:
                    if response.geturl() != url: raise Review('asset_redirect_forbidden')
                    if response.status != 200: raise Review('asset_http_failed')
                    length = response.headers.get('Content-Length')
                    if length is not None and (not re.fullmatch('[0-9]+', length) or not 1 <= int(length) <= MAX_IMAGE):
                        raise Review('asset_image_size_invalid')
                    raw = response.read(MAX_IMAGE + 1)
                    if length is not None and len(raw) != int(length): raise Review('asset_image_size_invalid')
                    extension = _inspect(raw, response.headers.get('Content-Type', ''))
            except urllib.error.HTTPError as error:
                raise Review('asset_redirect_forbidden' if 300 <= error.code < 400 else 'asset_http_failed') from None
            except Review: raise
            except Exception: raise Review('asset_download_failed') from None
        digest = hashlib.sha256(raw).hexdigest(); path = self.directory / (digest + '.' + extension)
        if path.is_symlink(): raise Review('asset_cache_invalid')
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            _blob(path, len(raw), digest)
        else:
            with os.fdopen(fd, 'wb') as stream: stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?)',(key,indexed_url,digest,extension,len(raw)))
        return self._cached(indexed_url, key)

    def lesson_images(self, payload):
        _binding()
        if not isinstance(payload, dict) or payload.get('account') != ACCOUNT or payload.get('source_origin') != ORIGIN:
            raise Review('asset_account_mismatch')
        root = payload.get('ape')
        if not isinstance(root, dict) or root.get('name') != 'page' or not isinstance(root.get('children'), list):
            raise Review('asset_ape_invalid')
        images, seen, pending, count = [], set(), [(root,0)], 0
        while pending:
            node, depth = pending.pop(); count += 1
            if count > 250000 or depth > 128 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
                raise Review('asset_ape_invalid')
            fields, children = node.get('fields', {}), node.get('children', [])
            if not isinstance(fields, dict) or not isinstance(children, list): raise Review('asset_ape_invalid')
            if _placeholder(node): continue
            if node['name'] == 'image':
                key = node.get('id')
                if not isinstance(key, str) or not IMAGE_KEY.fullmatch(key) or key in seen: raise Review('asset_image_key_invalid')
                seen.add(key); images.append((key, _image_source(fields.get('imageSrc'))))
                if len(images) > MAX_IMAGES: raise Review('asset_too_many_images')
            pending.extend((child,depth + 1) for child in reversed(children))
        return {key:base64.b64encode(self.fetch(url)[0]).decode('ascii') for key,url in images}
