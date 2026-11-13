"""Local read-only progress display. It never starts or modifies a migration."""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import status as archive_status

MSK = timezone(timedelta(hours=3))
STATES = {'pending', 'review', 'imported', 'collected', 'empty'}
EVENTS = {'complete', 'captured', 'equivalent_source_reused', 'review', 'created', 'already_present', 'audio_staged',
          'ready', 'empty_created', 'empty_already_present', 'lesson_created', 'lesson_write_started',
          'warning', 'stopped', 'cover_created', 'cover_already_imported', 'private_updated', 'private_already_private'}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64: raise ValueError('invalid_time')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None: raise ValueError('invalid_time')
    return parsed


def msk(value):
    return timestamp(value).astimezone(MSK).strftime('%d.%m.%Y %H:%M:%S МСК') if value else None


def windows_process_matches(pid, started_at):
    """Query rights only: never use os.kill(pid, 0) on Windows."""
    if os.name != 'nt' or type(pid) is not int or not 0 < pid < 2**32: return False
    try:
        import ctypes
        from ctypes import wintypes as w
        expected = timestamp(started_at).timestamp()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]; kernel.CloseHandle.restype = w.BOOL
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        kernel.GetExitCodeProcess.restype = w.BOOL
        kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        kernel.GetProcessTimes.restype = w.BOOL
        kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = w.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return False
        try:
            code = w.DWORD(); times = [w.FILETIME() for _ in range(4)]
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259: return False
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)): return False
            created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 10**7 - 11644473600
            size = w.DWORD(32768); image = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)): return False
            return abs(created - expected) <= 10 and Path(image.value).name.lower() in {'python.exe', 'pythonw.exe'}
        finally:
            kernel.CloseHandle(handle)
    except (OSError, ValueError, AttributeError): return False


def worker_status(directory, checker=windows_process_matches):
    jobs = []
    for path in Path(directory).glob('job-*.json'):
        if not re.fullmatch(r'job-[0-9a-f]{32}\.json', path.name) or path.is_symlink(): continue
        try:
            if path.stat().st_size > 65536: continue
            job = json.loads(path.read_bytes())
            if (not isinstance(job, dict) or job.get('version') != 1 or job.get('job_id') != path.stem
                    or job.get('workspace') != str(Path(directory).resolve().parents[3])
                    or job.get('status') not in {'starting', 'running', 'completed', 'failed'}
                    or not re.fullmatch('[0-9a-f]{40}', job.get('source_commit', ''))): continue
            jobs.append((timestamp(job.get('created_at_utc')), job))
        except (OSError, ValueError, TypeError): continue
    if not jobs: return {'running': False, 'state': 'none', 'pid': None, 'source_commit': None}
    job = max(jobs, key=lambda item: item[0])[1]
    pid = job.get('pid'); started = job.get('started_at_utc'); finished = job.get('finished_at_utc')
    running = (job['status'] == 'running' and not finished and type(pid) is int and 0 < pid < 2**32
               and isinstance(started, str) and checker(pid, started) is True)
    return {'running': running, 'state': 'running' if running else 'stopped' if job['status'] == 'running' else job['status'],
            'pid': pid if running else None, 'source_commit': job['source_commit'],
            'created_at_msk': msk(job['created_at_utc']), 'started_at_msk': msk(started), 'finished_at_msk': msk(finished)}


def audio_progress(directory):
    """Read aggregate staged-file counts; never return URLs or file identities."""
    paths = [Path(directory) / name for name in ('audio-inventory.json', 'audio-stage-index.json')]
    if not all(path.is_file() and not path.is_symlink() and path.stat().st_size <= 2 * 1024 * 1024 for path in paths):
        return None
    inventory, index = [json.loads(path.read_bytes()) for path in paths]
    for data in (inventory, index):
        if (not isinstance(data, dict) or data.get('version') != 1 or data.get('account') != 'mastervision'
                or data.get('origin') != 'https://shop.mastervision.su'):
            raise ValueError('audio_progress_identity_invalid')
    if index.get('site') != 'my-lk.mastervision.su' or not isinstance(index.get('files'), dict) or not isinstance(inventory.get('files'), list):
        raise ValueError('audio_progress_invalid')
    expected = {}
    for item in inventory['files']:
        if (not isinstance(item, dict) or not re.fullmatch('[0-9a-f]{64}', item.get('url_sha256', ''))
                or type(item.get('size_bytes')) is not int or not 0 < item['size_bytes'] <= 50 * 1024 * 1024):
            raise ValueError('audio_progress_invalid')
        if item['url_sha256'] in expected: raise ValueError('audio_progress_invalid')
        expected[item['url_sha256']] = item['size_bytes']
    for key, receipt in index['files'].items():
        if (key not in expected or not isinstance(receipt, dict) or receipt.get('url_sha256') != key
                or type(receipt.get('size')) is not int or receipt['size'] != expected[key]):
            raise ValueError('audio_progress_invalid')
    return {'staged': len(index['files']), 'total': len(expected),
            'bytes_staged': sum(receipt['size'] for receipt in index['files'].values()),
            'bytes_total': sum(expected.values())}


def snapshot(path=archive_status.PATH, checker=windows_process_matches):
    path = Path(path).resolve()
    stats = archive_status.status(path)  # Existing read-only account/origin/site guard.
    if set(stats['courses']) - STATES: raise ValueError('invalid_states')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        if db.execute('SELECT account,origin,site FROM meta').fetchall() != [('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su')]:
            raise ValueError('status_account_mismatch')
        imported = 0
        for row in db.execute("SELECT lesson_ids FROM courses WHERE state='imported'"):
            ids = json.loads(row[0])
            if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids): raise ValueError('invalid_ids')
            imported += len(ids)
    last = stats.get('last_event')
    if last:
        last = {'at_msk': msk(last['at_utc']), 'stage': last['stage'] if last['stage'] in {'collect', 'import', 'catalog', 'cover', 'settings', 'audio'} else 'unknown',
                'status': last['status'] if last['status'] in EVENTS else 'unknown',
                'course': last['course'] if type(last['course']) is int else None,
                'lesson': last['lesson'] if type(last['lesson']) is int else None}
    return {'status': 'ok', 'updated_at_msk': datetime.now(MSK).strftime('%d.%m.%Y %H:%M:%S МСК'),
            'courses': stats['courses'], 'catalog_courses': stats['catalog_courses'],
            'source_courses': stats['completed_source_courses'], 'source_lessons': stats['completed_source_lessons'],
            'imported_lessons': imported, 'last_event': last, 'worker': worker_status(path.parent / 'jobs', checker),
            'audio': audio_progress(path.parent)}


HTML = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Перенос Master Vision</title><style>
body{font:17px system-ui,sans-serif;background:#f4f6fa;color:#172332;margin:0;padding:32px;max-width:1120px;margin:auto}h1{font-size:32px;margin-bottom:8px}.hint{color:#5c6979}#worker{padding:18px 22px;background:white;border-left:6px solid #8b97a8;border-radius:8px;font-weight:600;margin:24px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card{background:white;padding:22px;border-radius:12px}.number{font-size:38px;font-weight:700;margin-bottom:8px}.details{background:white;border-radius:12px;padding:24px;margin-top:24px;line-height:1.8}code{overflow-wrap:anywhere}p{margin:8px 0}
</style><h1>Перенос Master Vision</h1><div class="hint">Обновляется каждые 5 секунд. Эта страница показывает состояние и не запускает перенос.</div>
<div id="worker">Проверяю состояние процесса…</div><div class="grid">
<div class="card"><div class="number" id="imported">—</div>Курсов перенесено</div><div class="card"><div class="number" id="lessons">—</div>Уроков в перенесённых курсах</div><div class="card"><div class="number" id="review">—</div>Курсов на разборе</div><div class="card"><div class="number" id="total">—</div>Курсов в исходной базе</div></div>
<div class="details"><p id="source"></p><p id="audio"></p><p id="event"></p><p id="job"></p><p id="updated" class="hint"></p></div>
<script>
const put=(id,v)=>document.getElementById(id).textContent=v;
const states={none:'Сборщик сейчас не запущен',stopped:'Сборщик сейчас не работает: прежний процесс не подтверждён',completed:'Сборщик сейчас не запущен. Предыдущий запуск завершён',failed:'Сборщик сейчас не запущен. Предыдущий запуск остановился с ошибкой',starting:'Запуск готовится; работа процесса пока не подтверждена',running:'Сборщик работает — процесс подтверждён'};
const stages={collect:'сбор исходников',import:'перенос',catalog:'список курсов',cover:'обложки',settings:'настройки доступа',audio:'перенос аудиофайлов'};
const actions={complete:'завершено',captured:'урок сохранён',equivalent_source_reused:'снимок проверен',review:'требуется разбор',created:'курс перенесён',already_present:'курс уже перенесён',ready:'готово к переносу',empty_created:'курс без уроков перенесён',empty_already_present:'курс без уроков уже есть',lesson_created:'урок перенесён',lesson_write_started:'переносится урок',warning:'замечание сохранено',stopped:'остановлено',cover_created:'обложка перенесена',cover_already_imported:'обложка уже есть',private_updated:'доступ настроен',private_already_private:'доступ проверен',audio_staged:'аудиофайл сохранён на сервере'};
async function refresh(){try{const response=await fetch('/status.json',{cache:'no-store'});if(!response.ok)throw Error();const d=await response.json();if(d.status!=='ok')throw Error();
put('worker',states[d.worker.state]||'Состояние процесса не подтверждено');document.getElementById('worker').style.borderLeftColor=d.worker.running?'#2f8757':'#8b97a8';
put('imported',d.courses.imported||0);put('lessons',d.imported_lessons);put('review',d.courses.review||0);put('total',d.catalog_courses);
put('audio',d.audio?`Аудиофайлы сохранены на сервере: ${d.audio.staged} из ${d.audio.total}; ${Math.round(d.audio.bytes_staged/1048576)} из ${Math.round(d.audio.bytes_total/1048576)} МБ.`:'');
put('source',`Сохранено исходников: ${d.source_courses} курсов, ${d.source_lessons} уроков.`);const e=d.last_event;put('event',e?`Последнее действие: ${e.at_msk}; ${stages[e.stage]||'проверка'}; ${actions[e.status]||'проверка'}${e.course?' · курс '+e.course:''}${e.lesson?' · урок '+e.lesson:''}`:'Действий пока нет.');
put('job',d.worker.created_at_msk?`Последний запуск создан: ${d.worker.created_at_msk}${d.worker.finished_at_msk?'; завершён: '+d.worker.finished_at_msk:''}`:'Запусков пока нет.');put('updated','Проверено: '+d.updated_at_msk);
}catch(error){put('worker','Текущее состояние недоступно. Показанные ниже числа могут быть устаревшими.');document.getElementById('worker').style.borderLeftColor='#b15a35';}}
refresh();setInterval(refresh,5000);
</script></html>'''


def make_server(path=archive_status.PATH, checker=windows_process_matches, port=0):
    if type(port) is not int or not 0 <= port <= 65535: raise ValueError('invalid_local_port')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Host') not in {host + ':' + str(self.server.server_address[1]) for host in ('127.0.0.1', 'localhost')}:
                code, kind, body = 403, 'text/plain; charset=utf-8', b'Forbidden'
            elif self.path not in {'/', '/status.json'}:
                code, kind, body = 404, 'text/plain; charset=utf-8', b'Not found'
            elif self.path == '/':
                code, kind, body = 200, 'text/html; charset=utf-8', HTML.encode()
            else:
                try: data = snapshot(path, checker)
                except Exception: data = {'status': 'unavailable'}
                code, kind, body = 200, 'application/json; charset=utf-8', json.dumps(data, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; form-action 'none'")
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *args): pass
    return HTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    with make_server(port=args.port) as server:
        port = server.server_address[1]
        print(json.dumps({'dashboard_url': 'http://127.0.0.1:' + str(port) + '/', 'port': port, 'pid': os.getpid()}), flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass


if __name__ == '__main__': main()
