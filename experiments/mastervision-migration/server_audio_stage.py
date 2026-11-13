"""Stage one MP3 on the Master Vision host; stdlib only, no Frappe/DB writes.

Read {url, expected_size, site_files_root} JSON from stdin or --manifest.
site_files_root is the existing my-lk.mastervision.su/private/files directory.
Only fixed codes, digests, size and a staging basename leave this program.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import unicodedata
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit

SITE = 'my-lk.mastervision.su'
PREFIX = 'avo-mastervision-audio-stage-'
MAX_SIZE = 50 * 1024 * 1024
RESERVE = 64 * 1024 * 1024
CHUNK = 64 * 1024
FIELDS = {'basename', 'url_sha256', 'size', 'sha256', 'md5'}


class StageError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _url(value):
    if (not isinstance(value, str) or not value or len(value) > 8192
            or re.search(r'[\x00-\x20\x7f\\?#]', value)):
        raise StageError('audio_url_invalid')
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.username is not None or url.password is not None
                or url.port is not None or url.query or url.fragment
                or not (url.hostname == 'f1.autoweboffice.ru'
                        or re.fullmatch(r'f[0-9]+\.autoweboffice\.com', url.hostname or ''))):
            raise ValueError()
        if re.search(r'%(?![a-fA-F0-9]{2})|%(?:2f|5c)', url.path, re.I):
            raise ValueError()
        decoded = unquote(url.path, encoding='utf-8', errors='strict')
        if (not decoded.startswith('/') or '%' in decoded or any(c in decoded for c in '\\?#')
                or any(unicodedata.category(c).startswith('C') for c in decoded)
                or any(not part or part.startswith('.') for part in decoded.split('/')[1:])
                or not decoded.lower().endswith('.mp3')):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise StageError('audio_url_invalid') from None
    return value


def _root(value):
    if not isinstance(value, (str, os.PathLike)):
        raise StageError('audio_stage_root_invalid')
    path = Path(value)
    if not path.is_absolute() or any(item.is_symlink() for item in (path, *path.parents)):
        raise StageError('audio_stage_root_invalid')
    try:
        path = path.resolve(strict=True)
    except OSError:
        raise StageError('audio_stage_root_invalid') from None
    if (not path.is_dir() or path.name != 'files' or path.parent.name != 'private'
            or path.parent.parent.name != SITE):
        raise StageError('audio_stage_root_invalid')
    return path


def _regular(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StageError('audio_stage_path_invalid')
    return info


def _magic(head, size):
    if head.startswith(b'ID3'):
        if len(head) < 10 or head[3] not in (2, 3, 4) or head[4] == 255 or any(x >= 128 for x in head[6:10]):
            return False
        if head[5] & ~{2: 0xC0, 3: 0xE0, 4: 0xF0}[head[3]]:
            return False
        tag_size = sum(value << shift for value, shift in zip(head[6:10], (21, 14, 7, 0)))
        footer = 10 if head[3] == 4 and head[5] & 0x10 else 0
        return 10 + tag_size + footer <= size
    return (len(head) >= 4 and head[0] == 255 and head[1] & 224 == 224
            and (head[1] >> 3) & 3 != 1 and (head[1] >> 1) & 3 != 0
            and (head[2] >> 4) not in (0, 15) and (head[2] >> 2) & 3 != 3
            and head[3] & 3 != 2)


def _hash(path, expected_size):
    info = _regular(path)
    if info is None or info.st_size != expected_size:
        raise StageError('audio_existing_hash_mismatch')
    sha, md5, size, head = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0, b''
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        if (actual.st_ino, actual.st_dev) != (info.st_ino, info.st_dev):
            raise StageError('audio_stage_path_invalid')
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            size += len(chunk); sha.update(chunk); md5.update(chunk)
            head = (head + chunk)[:10]
    if size != expected_size or not _magic(head, size):
        raise StageError('audio_existing_hash_mismatch')
    return sha.hexdigest(), md5.hexdigest()


def _receipt(path, basename, url_hash, size):
    info = _regular(path)
    if info is None or not 0 < info.st_size <= 2048:
        raise StageError('audio_stage_receipt_invalid')
    try:
        row = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        raise StageError('audio_stage_receipt_invalid') from None
    if (not isinstance(row, dict) or set(row) != FIELDS or row['basename'] != basename
            or row['url_sha256'] != url_hash or type(row['size']) is not int or row['size'] != size
            or not isinstance(row['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', row['sha256'])
            or not isinstance(row['md5'], str) or not re.fullmatch('[a-f0-9]{32}', row['md5'])):
        raise StageError('audio_stage_receipt_invalid')
    return row


def stage_one(url, expected_size, site_files_root):
    url = _url(url)
    if type(expected_size) is not int or not 10 <= expected_size <= MAX_SIZE:
        raise StageError('audio_expected_size_invalid')
    root = _root(site_files_root)
    key = hashlib.sha256(url.encode()).hexdigest(); basename = PREFIX + key + '.mp3'
    final, part, receipt = root / basename, root / (basename + '.part'), root / (basename + '.json')
    states = [_regular(path) for path in (final, part, receipt)]
    if states[0] or states[2]:
        row = _receipt(receipt, basename, key, expected_size)
        candidate = final if states[0] else part
        if _hash(candidate, expected_size) != (row['sha256'], row['md5']):
            raise StageError('audio_existing_hash_mismatch')
        if not states[0]:
            if final.exists(): raise StageError('audio_stage_path_invalid')
            os.rename(part, final)
        return {'code': 'audio_reused' if states[0] else 'audio_recovered', **row}
    if states[1]:
        raise StageError('audio_stage_partial_exists')
    if shutil.disk_usage(root).free < expected_size + RESERVE:
        raise StageError('audio_stage_space_low')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    opener.addheaders = []
    request = urllib.request.Request(url, headers={'Accept': 'audio/mpeg', 'User-Agent': 'MasterVisionAudioStage/1.0'})
    created = None; recorded = False
    try:
        with opener.open(request, timeout=30) as response:
            if response.geturl() != url: raise StageError('audio_redirect_forbidden')
            if response.status != 200: raise StageError('audio_http_failed')
            length = response.headers.get('Content-Length', '')
            if not re.fullmatch('[0-9]{1,12}', length) or int(length) != expected_size:
                raise StageError('audio_content_length_invalid')
            if response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'audio/mpeg':
                raise StageError('audio_content_type_invalid')
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            created = os.fstat(fd); sha, md5, size, head = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0, b''
            with os.fdopen(fd, 'wb') as stream:
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk: break
                    if not isinstance(chunk, bytes): raise StageError('audio_stream_invalid')
                    size += len(chunk)
                    if size > expected_size or size > MAX_SIZE: raise StageError('audio_body_size_invalid')
                    head = (head + chunk)[:10]; sha.update(chunk); md5.update(chunk); stream.write(chunk)
                if size != expected_size: raise StageError('audio_body_size_invalid')
                if not _magic(head, size): raise StageError('audio_magic_invalid')
                stream.flush(); os.fsync(stream.fileno())
        row = {'basename': basename, 'url_sha256': key, 'size': size, 'sha256': sha.hexdigest(), 'md5': md5.hexdigest()}
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(row, stream, sort_keys=True); stream.flush(); os.fsync(stream.fileno())
        recorded = True
        if final.exists() or final.is_symlink(): raise StageError('audio_stage_path_invalid')
        os.rename(part, final)
        return {'code': 'audio_staged', **row}
    except StageError:
        raise
    except urllib.error.HTTPError as error:
        raise StageError('audio_redirect_forbidden' if 300 <= error.code < 400 else 'audio_http_failed') from None
    except OSError:
        raise StageError('audio_download_or_io_failed') from None
    except Exception:
        raise StageError('audio_download_failed') from None
    finally:
        # Remove only the incomplete part created by this call. A complete part
        # with a durable receipt is retained for exact-hash recovery after crash.
        if created is not None and not recorded:
            try:
                current = part.lstat()
                if (current.st_ino, current.st_dev) == (created.st_ino, created.st_dev) and stat.S_ISREG(current.st_mode):
                    part.unlink()
            except FileNotFoundError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest')
    args = parser.parse_args()
    try:
        if args.manifest:
            with open(args.manifest, encoding='utf-8') as stream: value = stream.read(16385)
        else:
            value = sys.stdin.read(16385)
        row = json.loads(value)
        if len(value) > 16384 or not isinstance(row, dict) or set(row) != {'url', 'expected_size', 'site_files_root'}:
            raise StageError('audio_manifest_invalid')
        result = stage_one(**row)
    except StageError as error:
        print(json.dumps({'code': str(error)})); return 1
    except Exception:
        print(json.dumps({'code': 'audio_manifest_or_stage_invalid'})); return 1
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
