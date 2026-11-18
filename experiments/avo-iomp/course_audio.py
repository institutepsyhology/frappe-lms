"""Prepare the reviewed IOMP course 91 and run its resumable private-file import."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from importer import IOMP_BINDING, Review, Stop
from lms.lms.avo_html_fragment import make_html_block

import course_audio_worker as worker

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
LESSONS = {str(value) for value in range(1829, 1839)}
PLAYER_STYLE = '7ce563a7ab1d249197c75de36aac44f2f46ecf53e2f24e9585f441000c374c41'
PLAYER_CONTROLS = dict(showDownloadButton=False, showLoopButton=True, showStopButton=True,
                       showVolumeButton=True, showVolumeSlider=True)
DRIVE = re.compile(r'(<p><iframe src="https://drive\.google\.com/file/d/[A-Za-z0-9_-]{1,200}/preview"'
                   r' width="640" height="480") scrolling="no" frameborder="0"(></iframe></p>)')


def prepare_course_audio(payloads):
    rows = []
    for payload in payloads:
        if (payload.get('account'), payload.get('source_origin'), payload.get('format'),
                payload.get('course_id'), payload.get('lesson_id') in LESSONS) != (
                IOMP_BINDING[0], IOMP_BINDING[1], 'ape', '91', True):
            continue
        lesson = payload['lesson_id']
        pending = [payload['ape']]
        while pending:
            node = pending.pop()
            fields = node.get('fields', {})
            children = node.get('children', [])
            pending.extend(reversed(children))
            if children:
                continue
            kind = node['name']
            if (kind == 'image' and set(fields) == {'html', 'anchor', 'imageSrc'} and
                    fields['anchor'] == '' and fields['html'] == 'Изображение'):
                # Default editor label. Keep the image itself for the private image importer.
                del fields['html']
            elif kind == 'text' and set(fields) == {'anchor', 'html'} and fields['anchor'] == '':
                markup = fields['html']
                if isinstance(markup, str) and DRIVE.fullmatch(markup):
                    cleaned = DRIVE.sub(r'\1\2', markup)
                    make_html_block(cleaned)
                    fields['html'] = cleaned
            elif kind == 'audio':
                controls = {key: value for key, value in fields.items() if key not in {'audioSrc', 'anchor'}}
                style = json.dumps(node.get('style'), sort_keys=True, separators=(',', ':')).encode()
                if (set(node) - {'id', 'name', 'style', 'fields', 'children'} or fields.get('anchor') != ''
                        or controls != PLAYER_CONTROLS or any(type(v) is not bool for v in controls.values())
                        or hashlib.sha256(style).hexdigest() != PLAYER_STYLE):
                    raise Review('iomp_audio_controls_changed', [{'lesson_id': lesson}])
                row = {'lesson_id': lesson, 'url': fields.get('audioSrc')}
                try:
                    url = worker.target(row)
                except worker.AudioError as error:
                    raise Review(str(error), [{'lesson_id': lesson}]) from None
                rows.append(row)
                node['name'] = 'button'
                node['fields'] = {'anchor': '', 'html': 'Аудиозапись', 'linkType': 'url',
                                  'url': 'https://' + worker.SITE + url, 'blank': True}
    if any(p.get('account') == 'iomp' and p.get('course_id') == '91' for p in payloads):
        try:
            worker.check_manifest(rows)
        except worker.AudioError as error:
            raise Review(str(error)) from None
    return rows


def sync_course_audio(mode, rows):
    if not rows:
        return
    worker.check_manifest(rows)
    if mode not in ('prepare', 'attach'):
        raise Stop('iomp_audio_mode_invalid')
    # The worker runs in a fresh process of the existing backend. No files or credentials
    # are installed on the server. Only source references travel over authenticated SSH.
    bundle = base64.b64encode((HERE / 'course_audio_worker.py').read_bytes()).decode('ascii')
    runner = "import base64;exec(compile(base64.b64decode('" + bundle + "'),'<iomp-audio>','exec'))"
    bench = '/home/frappe/frappe-bench'
    command = shlex.join(['docker', 'exec', '-i', '-u', 'frappe', '-w', bench + '/sites',
                          'company-lms-backend-1', bench + '/env/bin/python', '-B', '-c', runner])
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15',
           '-o', 'ServerAliveCountMax=2', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'UserKnownHostsFile=' + str(WORKSPACE / 'frappe-deploy/known_hosts'),
           '-i', str(Path.home() / '.ssh/codex_timeweb_lms_20261010'), 'root@89.223.71.30', command]
    try:
        result = subprocess.run(ssh, input=json.dumps({'mode': mode, 'rows': rows}).encode(),
                                capture_output=True, timeout=1800,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        reply = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise Stop('iomp_audio_worker_unconfirmed') from None
    if result.returncode or reply != {'mode': mode, 'verified': len(rows)}:
        code = reply.get('code') if isinstance(reply, dict) else None
        lesson = reply.get('lesson_id') if isinstance(reply, dict) else None
        if code == 'iomp_audio_worker_failed':
            raise Stop(code)
        if isinstance(code, str) and re.fullmatch('iomp_audio_[a-z_]+', code):
            raise Review(code, [{'lesson_id': lesson}] if lesson in LESSONS else [])
        raise Stop('iomp_audio_worker_unconfirmed')
