"""Validate archived audio references, stage remotely, keep a metadata-only index.

No source archive writes, lesson/File creation, credentials output or retries.
The caller owns the archive worker lock and invokes stage_audio(store, emit).
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import uuid

from importer import ACCOUNT, ORIGIN, SITE, Stop
from normalize_editor_nodes import _style_content
from server_audio_stage import FIELDS, MAX_SIZE, PREFIX, StageError, _url

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('MASTER_VISION_WORKSPACE', str(HERE.parents[2]))).resolve()
COURSES = (297, 324, 336, 377, 391, 399, 472, 486, 616)
BENCH = '/home/frappe/frappe-bench'
CONTAINER = 'company-lms-backend-1'
REMOTE_FILES = BENCH + '/sites/my-lk.mastervision.su/private/files'
FLAGS = {'showDownloadButton', 'showLoopButton', 'showStopButton', 'showVolumeButton', 'showVolumeSlider'}


def _binding():
    if (ACCOUNT, ORIGIN, SITE) != ('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su'):
        raise Stop('audio_wrong_account')


def _json(path):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 2_000_000:
        raise Stop('audio_private_manifest_invalid')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        raise Stop('audio_private_manifest_invalid') from None
    if not isinstance(value, dict): raise Stop('audio_private_manifest_invalid')
    return value


def _source_audio(store):
    sources = {}
    for cid in COURSES:
        payloads = store.completed_course(cid)
        if not isinstance(payloads, list): raise Stop('audio_source_invalid')
        lesson_ids = set()
        for payload in payloads:
            if (not isinstance(payload, dict) or payload.get('account') != ACCOUNT
                    or payload.get('source_origin') != ORIGIN or type(payload.get('course_id')) is not int
                    or payload['course_id'] != cid or type(payload.get('lesson_id')) is not int
                    or payload['lesson_id'] <= 0 or payload['lesson_id'] in lesson_ids
                    or payload.get('format') != 'ape'):
                raise Stop('audio_source_identity_invalid')
            lid = payload['lesson_id']; lesson_ids.add(lid); ape = payload.get('ape')
            if not isinstance(ape, dict) or ape.get('name') != 'page': raise Stop('audio_source_invalid')
            pending, visited = [(ape, ())], 0
            while pending:
                node, path = pending.pop(); visited += 1
                if (visited > 250000 or len(path) > 128 or not isinstance(node, dict)
                        or not isinstance(node.get('name'), str) or not isinstance(node.get('children', []), list)):
                    raise Stop('audio_source_invalid')
                children = node.get('children', [])
                pending.extend((child, (*path, i)) for i, child in reversed(list(enumerate(children))))
                if node['name'] != 'audio': continue
                fields = node.get('fields')
                if (not isinstance(fields, dict) or set(fields) - FLAGS - {'audioSrc', 'anchor'}
                        or fields.get('anchor') not in (None, '') or children
                        or any(type(fields[k]) is not bool for k in FLAGS & set(fields))
                        or set(node) - {'id', 'name', 'fields', 'children', 'style'}
                        or _style_content(node.get('style'))):
                    raise Stop('audio_source_unsupported')
                try: url = _url(fields.get('audioSrc'))
                except StageError: raise Stop('audio_source_url_invalid') from None
                key = hashlib.sha256(url.encode()).hexdigest()
                entry = sources.setdefault(key, {'url': url, 'references': set()})
                if entry['url'] != url: raise Stop('audio_source_identity_invalid')
                entry['references'].add((cid, lid, path))
    return sources


def _plan(store):
    _binding()
    source = _source_audio(store)
    inventory = _json(Path(store.directory) / 'audio-inventory.json')
    if (type(inventory.get('version')) is not int or inventory['version'] != 1 or inventory.get('account') != ACCOUNT
            or inventory.get('origin') != ORIGIN or inventory.get('site', SITE) != SITE
            or not isinstance(inventory.get('files'), list)):
        raise Stop('audio_inventory_identity_invalid')
    records = {}
    for row in inventory['files']:
        key = row.get('url_sha256') if isinstance(row, dict) else None
        if (not isinstance(key, str) or not re.fullmatch('[a-f0-9]{64}', key) or key in records
                or type(row.get('size_bytes')) is not int or not 10 <= row['size_bytes'] <= MAX_SIZE
                or row.get('mime') != 'audio/mpeg' or row.get('http_status') != 200
                or row.get('reachable') is not True or row.get('error') is not None
                or not isinstance(row.get('references'), list) or not row['references']):
            raise Stop('audio_inventory_invalid')
        refs = []
        for ref in row['references']:
            if (not isinstance(ref, dict) or set(ref) != {'course_id', 'lesson_id', 'block_path'}
                    or type(ref['course_id']) is not int or ref['course_id'] not in COURSES
                    or type(ref['lesson_id']) is not int or ref['lesson_id'] <= 0
                    or not isinstance(ref['block_path'], list) or not 0 < len(ref['block_path']) <= 128
                    or any(type(n) is not int or n < 0 for n in ref['block_path'])):
                raise Stop('audio_inventory_references_invalid')
            refs.append((ref['course_id'], ref['lesson_id'], tuple(ref['block_path'])))
        if len(refs) != len(set(refs)) or key not in source or set(refs) != source[key]['references']:
            raise Stop('audio_inventory_source_mismatch')
        records[key] = {'url': source[key]['url'], 'size': row['size_bytes']}
    if set(records) != set(source) or not records: raise Stop('audio_inventory_source_mismatch')
    return records


def _validate_receipt(row, key, size):
    if (not isinstance(row, dict) or set(row) != FIELDS or row.get('url_sha256') != key
            or row.get('basename') != PREFIX + key + '.mp3'
            or type(row.get('size')) is not int or row['size'] != size
            or not isinstance(row.get('sha256'), str) or not re.fullmatch('[a-f0-9]{64}', row['sha256'])
            or not isinstance(row.get('md5'), str) or not re.fullmatch('[a-f0-9]{32}', row['md5'])):
        raise Stop('audio_stage_receipt_invalid')
    return row


def _index(path, records):
    if not path.exists() and not path.is_symlink():
        return {'version': 1, 'account': ACCOUNT, 'origin': ORIGIN, 'site': SITE, 'files': {}}
    value = _json(path)
    if (set(value) != {'version', 'account', 'origin', 'site', 'files'} or type(value['version']) is not int or value['version'] != 1
            or (value['account'], value['origin'], value['site']) != (ACCOUNT, ORIGIN, SITE)
            or not isinstance(value['files'], dict) or set(value['files']) - set(records)):
        raise Stop('audio_stage_index_invalid')
    for key, row in value['files'].items(): _validate_receipt(row, key, records[key]['size'])
    return value


def _save_index(path, value):
    if path.is_symlink(): raise Stop('audio_stage_index_invalid')
    temp = path.with_name('.audio-stage-index-' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    except OSError:
        raise Stop('audio_stage_index_write_failed') from None
    finally:
        if temp.exists() and not temp.is_symlink(): temp.unlink()


def _remote(url, size):
    code = (HERE / 'server_audio_stage.py').read_bytes()
    if not 0 < len(code) <= 20000: raise Stop('audio_stage_program_invalid')
    # Only reviewed local program bytes enter argv. Private source URL travels
    # through stdin; stderr is discarded, never copied into logs or exceptions.
    wrapper = ("import base64,sys;n={'__name__':'mastervision_audio_stage'};"
               "exec(compile(base64.b64decode('" + base64.b64encode(code).decode() +
               "'),'<mastervision-audio-stage>','exec'),n);sys.exit(n['main']())")
    command = shlex.join(['docker', 'exec', '-i', '-u', 'frappe', '-w', BENCH + '/sites',
                          CONTAINER, BENCH + '/env/bin/python', '-B', '-c', wrapper])
    args = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(ROOT / 'frappe-deploy/known_hosts'),
            '-i', str(Path.home() / '.ssh/codex_timeweb_lms_20261010'), 'root@89.223.71.30', command]
    data = json.dumps({'url': url, 'expected_size': size, 'site_files_root': REMOTE_FILES}).encode()
    try:
        response = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        value = json.loads(response.stdout)
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, UnicodeError):
        raise Stop('audio_remote_result_uncertain') from None
    if not isinstance(value, dict): raise Stop('audio_remote_result_uncertain')
    if response.returncode:
        error = value.get('code')
        raise Stop(error if set(value) == {'code'} and isinstance(error, str)
                   and re.fullmatch('audio_[a-z_]{1,90}', error) else 'audio_remote_result_uncertain')
    return value


def stage_audio(store, emit):
    if not callable(emit): raise Stop('audio_progress_invalid')
    records = _plan(store)
    path = Path(store.directory) / 'audio-stage-index.json'; index = _index(path, records)
    total, completed, size = len(records), 0, 0
    emit({'stage': 'audio', 'completed': 0, 'total': total})
    for key, entry in records.items():
        result = _remote(entry['url'], entry['size'])
        if (not isinstance(result, dict) or result.get('code') not in ('audio_staged', 'audio_reused', 'audio_recovered')
                or set(result) != FIELDS | {'code'}):
            raise Stop('audio_remote_result_uncertain')
        receipt = _validate_receipt({k: v for k, v in result.items() if k != 'code'}, key, entry['size'])
        if key in index['files'] and index['files'][key] != receipt: raise Stop('audio_stage_receipt_changed')
        index['files'][key] = receipt; _save_index(path, index)
        completed += 1; size += entry['size']
        emit({'stage': 'audio', 'completed': completed, 'total': total, 'size': entry['size'], 'code': result['code']})
    return {'stage': 'audio', 'completed': completed, 'total': total, 'size': size}
