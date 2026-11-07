"""Resume-safe draft import from the isolated mv-centr AVO snapshots via Frappe MCP.

Default is a read-only check. --apply creates drafts; it never publishes or
grants access. The event database contains identifiers and diagnostic codes,
never lesson text, URLs, cookies, or authentication details.
"""
import argparse
import base64
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import urllib.request

def workspace_root():
    for parent in Path(__file__).resolve().parents:
        if ((parent / 'collector/lesson_content/prepare_frappe_course.cjs').is_file()
                and (parent / 'frappe-mcp/headers.py').is_file()):
            return parent
    raise RuntimeError('workspace_not_found')


REMOTE_WORKER = os.environ.get('AVO_REMOTE_JOURNAL_WORKER') == '1' and os.name != 'nt'
ROOT = Path('/opt/company-lms') if REMOTE_WORKER else workspace_root()
DATA = (ROOT / 'private/avo-journal-mvcentr') if REMOTE_WORKER else ROOT / 'exports/lesson-content'
SITE = 'my-lk.mv-centr.ru'
ORIGIN = 'https://shop.mv-centr.ru'
ACCOUNT = 'mv-centr'
MAX_ERRORS = 10
REPORT = DATA / 'ОТЧЁТ-перенос-mv-centr.md'
PROBLEMS_REPORT = DATA / 'ПРОБЛЕМНЫЕ-УРОКИ-mv-centr.md'
# User-confirmed disposable test lessons. These are lesson IDs, not course IDs.
EXCLUDED_LESSONS = {17, 19, 23, 5695, 5704, 5697, 5705, 6345, 6398, 9140, 10242}
# Owner excluded the obsolete course 50 and test courses 837 and 849.
EXCLUDED_COURSES = {50, 837, 849}
# Only the verified image for this source snapshot; unknown images stop.
REVIEWED_IMAGES = {(258,1150,'92ab32ec-5836-4443-998d-16b2ec13a2c0'):
    ('44c98968db4973a119db3bbc00ca36392c1466e1b631596e1fff0ac4a2474ea2',
     'eb781d7527cb12f817ae59ace8310ca3ab2f1c34c2e360813b9052f1cc6d2d33','mv-centr-image-1150.jpg')}
REVIEWED_IMAGES.update({
    (847,7758,'ffc4b821-7d86-424a-b806-c40544569f3e'):
        ('9ded212d34af81481864431c59aa0bf3f2d5b6928f69ba6249db083ef046d541','e23c2d873c3edbe6100f2652e24b9c69249e5d8ffa558cca25d09e81698b2fcf','mv-centr-reviewed-image-7758.jpg'),
    (847,7759,'a628618a-8deb-461a-8e66-ce643ab72385'):
        ('b1d067222208d5059fc9761755d3a355814944c5b49bc2a0d863331391f0ee9d','0ed86e907f71cc456f1ba29a7f7e04f7b791d5bcb0ea43b56866300265a0405a','mv-centr-reviewed-image-7759.png'),
    (847,7760,'a8d28cd3-6500-4083-84a0-cd96d12c67b1'):
        ('aac6256c1a69e0d17092fec38fe96ab9ee55324171f6ead42c9a652e0ab7c919','0e90f18ba7b324c314125cf79d10f5c23c449131b7ea73804693d5efe1ad6b63','mv-centr-reviewed-image-7760.jpg'),
})
# One independently checked image, explicitly scoped to each source block.
for _course, _lesson, _block in (
    (800,6760,'12e376fa-9558-47e7-aaa7-3706b83c4a1b'),
    (809,7706,'e8fcf1c9-fcc0-444d-a47e-34672f068c97'),
    (854,7892,'3f3b7fc5-7e76-4143-a1bb-4d1bbd9d681b'),
    (854,7914,'ceb343d9-b162-41f8-bd3b-4a0a469bc435'),
    (854,7915,'75afe839-e28d-44cc-a9eb-fbed16509854'),
    (854,7916,'fd5004e6-21d6-4cd3-ab72-6c69f48376df'),
    (854,7918,'6082e86e-ac7c-4732-b35b-11fb58e46ff0'),
):
    REVIEWED_IMAGES[(_course,_lesson,_block)] = (
        '553bb21768e933c323558e94885f76c94c614859d2033a9b26f046ce1fac125a',
        '16656f7b2ca7b05aa814bb46ba2b061c95bd5ae30a7eaa5a4cb9f1f1916134da',
        'mv-centr-review-common-lesson-image.jpg')


class Stop(Exception):
    pass


class Review(Exception):
    pass


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def course_ids(start=1, selected=None):
    with closing(readonly(DATA / 'mv-centr-captures.sqlite')) as db:
        if db.execute('select account,origin from capture_meta where singleton=1').fetchone() != (ACCOUNT, ORIGIN):
            raise Stop('wrong_capture_account')
    with closing(readonly(DATA / 'mv-centr-queue.sqlite')) as db:
        if db.execute('select origin from queue_meta where singleton=1').fetchone() != (ORIGIN,):
            raise Stop('wrong_queue_account')
    with closing(readonly(DATA / 'mv-centr-course-manifests.sqlite')) as db:
        if db.execute('select account,origin from manifest_meta where singleton=1').fetchone() != (ACCOUNT, ORIGIN):
            raise Stop('wrong_manifest_account')
        rows = db.execute('select course_id,lesson_ids,sha256,state from course_manifests order by course_id,id').fetchall()
    with closing(readonly(DATA / 'mv-centr-course-catalog.sqlite')) as db:
        if db.execute('select account,origin from catalog_meta where singleton=1').fetchone() != (ACCOUNT, ORIGIN):
            raise Stop('wrong_catalog_account')
        runs = db.execute('select run_id,max(observed_at) from catalog_pages group by run_id order by max(observed_at) desc').fetchall()
        if not runs:
            raise Stop('catalog_missing')
        pages = db.execute('select page,total,start,end,course_ids from catalog_pages where run_id=? order by page',(runs[0][0],)).fetchall()
    catalog, expected, total = [], 1, pages[0][1]
    for index,(page,n,first,last,raw) in enumerate(pages,1):
        ids = json.loads(raw)
        if page != index or n != total or first != expected or last < first or len(ids) != last-first+1:
            raise Stop('catalog_incomplete')
        catalog.extend(ids); expected = last+1
    if len(catalog) != total or len(set(catalog)) != total or any(type(n) is not int or n < 1 for n in catalog):
        raise Stop('catalog_invalid')
    grouped = {}
    for cid,raw,digest,state in rows:
        if type(cid) is not int or cid < 1 or hashlib.sha256(raw.encode('ascii')).hexdigest() != digest:
            raise Stop('manifest_integrity_error')
        grouped.setdefault(cid, []).append((json.loads(raw), state))
    result = []
    for cid in sorted(catalog):
        if cid < start or (selected is not None and cid != selected):
            continue
        variants = grouped.get(cid, [])
        if not variants:
            result.append((cid, None)); continue
        accepted = [v for v,s in variants if s == 'accepted']
        if len(accepted) != 1 or any(s != 'accepted' for _,s in variants):
            result.append((cid, None)); continue
        ids = accepted[0]
        if not isinstance(ids,list) or not ids or any(type(n) is not int or n < 1 for n in ids) or len(ids) != len(set(ids)):
            raise Stop('manifest_invalid')
        result.append((cid, ids))
    if selected is not None and not result:
        raise Stop('selected_course_not_in_manifest_and_catalog')
    return result


class Journal:
    def __init__(self,path):
        # Acquire before touching the journal, and hold until process exit.
        self.lock = sqlite3.connect(str(path)+'.lock.sqlite', timeout=0, isolation_level=None)
        self.lock.execute('begin exclusive')
        self.db = sqlite3.connect(path, timeout=0, isolation_level=None)
        self.db.execute('create table if not exists state(singleton integer primary key check(singleton=1), account text not null, paused integer not null, consecutive_errors integer not null)')
        self.db.execute('create table if not exists events(id integer primary key, at_utc text not null, course_id integer, lesson_id integer, status text not null, codes text not null)')
        self.db.execute('insert or ignore into state values(1,?,0,0)',(ACCOUNT,))
        if self.db.execute('select account from state where singleton=1').fetchone() != (ACCOUNT,):
            raise Stop('journal_account_mismatch')

    def event(self,course,lesson,status,codes=()):
        if not re.fullmatch(r'[a-z_]{1,60}',status) or any(not re.fullmatch(r'[a-z0-9_]{1,80}',x) for x in codes):
            raise Stop('invalid_diagnostic')
        self.db.execute('insert into events(at_utc,course_id,lesson_id,status,codes) values(?,?,?,?,?)',
                        (datetime.now(timezone.utc).isoformat(),course,lesson,status,json.dumps(codes)))

    def state(self):
        return self.db.execute('select paused,consecutive_errors from state where singleton=1').fetchone()

    def resume(self):
        self.db.execute('update state set paused=0,consecutive_errors=0 where singleton=1')
        self.event(None,None,'resumed')

    def failure(self, immediate=False):
        _, n = self.state(); n += 1
        paused = int(immediate or n >= MAX_ERRORS)
        self.db.execute('update state set paused=?,consecutive_errors=? where singleton=1',(paused,n))
        return bool(paused)

    def success(self):
        self.db.execute('update state set consecutive_errors=0 where singleton=1')

    def close(self):
        self.lock.rollback(); self.lock.close(); self.db.close()

    def report(self):
        paused,errors=self.state()
        rows=self.db.execute('select at_utc,course_id,lesson_id,status,codes from events order by id desc limit 200').fetchall()
        labels={'lesson_needs_review':'Урок требует разбора', 'course_needs_review':'Курс требует разбора',
                'lesson_preflight':'Урок проверен', 'course_ready':'Курс готов к переносу',
                'lesson_created':'Черновик урока создан', 'course_created':'Черновик курса создан',
                'existing_structure_unverified':'Уже существует; проверена структура',
                'lesson_excluded':'Исключён по указанию пользователя',
                'stopped':'Работа остановлена', 'resumed':'Работа возобновлена'}
        lines=['# Перенос mv-centr во Frappe', '',
               'Состояние: '+('остановлено до разбора' if paused else 'готово к запуску')+f'; ошибок подряд: {errors}.',
               'Время в таблице указано по UTC. В журнале нет содержимого уроков и ссылок.', '',
               '| Время UTC | Курс | Урок | Результат | Диагностика |', '| --- | --- | --- | --- | --- |']
        for at,cid,lid,status,codes in rows:
            parsed=json.loads(codes)
            lines.append(f"| {at} | {cid or '—'} | {lid or '—'} | {labels.get(status,status)} | {', '.join(parsed) or '—'} |")
        temp=REPORT.with_name(REPORT.name+'.tmp')
        temp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        os.replace(temp,REPORT)
        # Only the latest course outcome counts: historical failures must not
        # reappear after a successful transfer. Collect each lesson issue found
        # during that preflight; no lesson is written if any still need review.
        latest = {}
        events = self.db.execute('select id,course_id,lesson_id,status,codes from events order by id').fetchall()
        pending = {}
        for ident,cid,lid,status,codes in events:
            if cid is None: continue
            if status == 'lesson_needs_review': pending.setdefault(cid,[]).append((lid, json.loads(codes)))
            if status in ('course_needs_review','course_created','course_ready','existing_structure_unverified'):
                latest[cid] = (ident,status,json.loads(codes),pending.get(cid))
                pending.pop(cid,None)
        descriptions = {'source_not_ready':'исходный снимок не готов',
            'vimeo_video_unavailable':'видео Vimeo не работает — нужна замена',
            'manifest_missing_or_changed':'нет подтверждённого состава курса',
            'unsupported_spacer':'разделитель (будет игнорироваться после обновления)',
            'spacer_renderer_not_installed':'разделитель (будет игнорироваться после обновления)',
            'unsupported_multicolumn_layout':'расположение в колонках',
            'unsupported_container_fields':'настройки блока',
            'unsafe_or_unrecognized_html':'HTML требует проверки',
            'empty_lesson':'не удалось распознать содержимое',
            'course_title_exceeds_frappe_limit':'слишком длинное название курса',
            'lesson_title_exceeds_frappe_limit':'слишком длинное название урока',
            'image_requires_preparation':'изображение требует подготовки'}
        descriptions.update({'unknown_page_fields':'неизвестные настройки страницы',
            'video_url_invalid':'ссылка на видео требует проверки',
            'unsupported_button':'кнопка или её ссылка требуют проверки',
            'unsupported_header':'заголовок требует проверки',
            'unsupported_video_settings':'настройки видео требуют проверки',
            'video_pair_unsupported':'видеопара требует проверки',
            'unknown_video_fields':'неизвестные настройки видео',
            'legacy_player_pair_unresolved':'не удалось определить пару видео',
            'source_unavailable':'источник временно недоступен',
            'unknown_block':'неизвестный тип блока',
            'reviewed_source_changed':'исходный урок изменился после согласования'})
        lines = ['# Проблемные уроки MV-Centr', '',
                 'Для каждого курса показаны проблемы последней проверки; при изменении исходных данных могут обнаружиться другие.', '',
                 '| Курс АВО | Урок АВО | Причина |', '| --- | --- | --- |']
        for cid,(_,status,codes,detail) in sorted(latest.items()):
            if status != 'course_needs_review' or cid in EXCLUDED_COURSES: continue
            course_link = f'[№ {cid}](https://shop.mv-centr.ru/shop/training/admin/update?id={cid}&lg=ru#training_lessons)'
            for lid,issues in detail or [(None,codes)]:
                if lid in EXCLUDED_LESSONS:continue
                lesson_link = f'[№ {lid}](https://shop.mv-centr.ru/shop/training/traininglessons/admin/update?id={lid}&lg=ru)' if lid else 'Не определён'
                reason = ', '.join(descriptions.get(code,code) for code in issues)
                lines.append(f'| {course_link} | {lesson_link} | {reason} |')
        temp=PROBLEMS_REPORT.with_name(PROBLEMS_REPORT.name+'.tmp')
        temp.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        os.replace(temp,PROBLEMS_REPORT)


class RemoteJournal:
    """Durable journal on the same Frappe host; never sends lesson content."""
    def __init__(self):
        key=Path.home()/'.ssh/codex_timeweb_lms_20261010'
        known=ROOT/'frappe-deploy/known_hosts'
        self.child=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',
            '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2',
            '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(known),
            '-i',str(key),'root@89.223.71.30',
            'python3 -u /opt/company-lms/avo-journal-service/remote_journal_worker.py'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:self.request('ping')
        except Exception:
            self.child.kill()
            raise

    def request(self,method,*args):
        try:
            self.child.stdin.write(json.dumps({'method':method,'args':args},ensure_ascii=True)+'\n')
            self.child.stdin.flush()
            line=self.child.stdout.readline()
            response=json.loads(line)
            if not response.get('ok'):raise ValueError('remote_rejected')
            return response.get('result')
        except Exception as exc:
            raise Stop('remote_journal_unavailable') from exc

    def event(self,*args):return self.request('event',*args)
    def state(self):return tuple(self.request('state'))
    def resume(self):return self.request('resume')
    def failure(self,immediate=False):return self.request('failure',immediate)
    def success(self):return self.request('success')
    def candidates(self):return self.request('candidates')
    def report(self):
        reports=self.request('report')
        # The server copy is authoritative. A full laptop disk must not erase
        # the report or turn a safely stopped run into an unreported failure.
        for path,key in ((REPORT,'report'),(PROBLEMS_REPORT,'problems')):
            try:
                temp=path.with_name(path.name+'.tmp')
                temp.write_text(reports[key],encoding='utf-8')
                os.replace(temp,path)
            except OSError:
                print('Отчёт сохранён на сервере; на ноутбуке нет места для копии.',file=sys.stderr,flush=True)
    def close(self):
        try:
            try:self.request('close')
            except Stop:pass
        finally:
            try:self.child.stdin.close()
            except Exception:pass
            try:self.child.wait(timeout=10)
            except subprocess.TimeoutExpired:self.child.kill()


class MCP:
    def __init__(self):
        sys.path.insert(0,str(ROOT/'frappe-mcp'))
        from headers import NoRedirect, authenticated_headers
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.auth = authenticated_headers(SITE)
        if set(self.auth) != {'Cookie'}:
            raise Stop('authentication_invalid')
        self.n = 0
        init = self.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},
                         'clientInfo':{'name':'avo-draft-import','version':'1.0'}})
        if init.get('serverInfo',{}).get('name') != 'my_lk_mv_centr_ru':
            raise Stop('wrong_frappe_site')

    def rpc(self,method,params):
        self.n += 1
        data=json.dumps({'jsonrpc':'2.0','id':self.n,'method':method,'params':params},ensure_ascii=True).encode()
        req=urllib.request.Request('https://'+SITE+'/api/v2/mcp',data=data,
            headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',**self.auth})
        try:
            with self.opener.open(req,timeout=90) as res:
                body=json.load(res)
        except Exception as exc:
            raise Stop('mcp_connection_failed') from exc
        if not isinstance(body,dict) or body.get('id') != self.n or 'error' in body or not isinstance(body.get('result'),dict):
            raise Stop('mcp_invalid_response')
        return body['result']

    def call(self,name,args):
        result=self.rpc('tools/call',{'name':name,'arguments':args})
        if result.get('isError'):
            # Never record remote exception bodies, which can contain source data.
            raise Review('mcp_rejected_request')
        data=result.get('structuredContent')
        if not isinstance(data,dict): raise Stop('mcp_invalid_response')
        return data

    def close(self):
        try:
            req=urllib.request.Request('https://'+SITE+'/api/method/logout',data=b'{}',headers={'Content-Type':'application/json',**self.auth})
            with self.opener.open(req,timeout=15):pass
        except Exception:pass
        self.auth.clear()


def prepare_course(course, expected):
    process=None
    try:
        process=subprocess.Popen(['node',str(ROOT/'collector/lesson_content/prepare_frappe_course.cjs'),str(course)],
                                 stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        chunks=[]; size=[0]; overflow=[False]
        def read_bounded():
            while True:
                chunk=process.stdout.read(1024*1024)
                if not chunk:break
                size[0]+=len(chunk)
                if size[0]>64*1024*1024:
                    overflow[0]=True;process.kill();break
                chunks.append(chunk)
        reader=threading.Thread(target=read_bounded,daemon=True);reader.start()
        process.wait(timeout=180);reader.join(timeout=5)
        if reader.is_alive() or overflow[0]:raise ValueError('source_size')
        value=json.loads(b''.join(chunks))
    except Exception as exc:
        if process and process.poll() is None:
            process.kill();process.wait()
        raise Review('source_unavailable') from exc
    if process.returncode or not isinstance(value,list):
        raise Review('source_not_ready')
    if ([p.get('lesson_id') for p in value] != expected or
            any(p.get('account') != ACCOUNT or p.get('source_origin') != ORIGIN or p.get('course_id') != course for p in value)):
        raise Review('source_manifest_changed')
    return value


def outline(client,course):
    data=client.call('list_documents',{'doctype':'LMS Course','fields':['name','published'],
        'filters':[['custom_avo_account','=',ACCOUNT],['custom_avo_id','=',str(course)]],'limit':3})
    rows=data.get('documents')
    if not isinstance(rows,list) or data.get('has_next_page') or len(rows)>1: raise Review('ambiguous_course')
    if not rows:return []
    row=rows[0]
    if row.get('published') != 0:raise Review('course_not_draft')
    course_name=row['name']
    doc=client.call('get_document',{'doctype':'LMS Course','name':course_name})
    chapters=doc.get('chapters')
    if not isinstance(chapters,list) or len(chapters)!=1:raise Review('course_chapters_ambiguous')
    chapter=client.call('get_document',{'doctype':'Course Chapter','name':chapters[0]['chapter']})
    if chapter.get('course') != course_name or chapter.get('is_scorm_package'):raise Review('course_chapter_invalid')
    lessons=chapter.get('lessons')
    if not isinstance(lessons,list):raise Review('course_outline_invalid')
    names=[]
    for position,item in enumerate(lessons,1):
        if (not isinstance(item,dict) or item.get('idx') != position or
                not isinstance(item.get('lesson'),str) or not item['lesson']):
            raise Review('course_outline_invalid')
        names.append(item['lesson'])
    if len(set(names)) != len(names):raise Review('course_outline_invalid')
    by_name={}
    for offset in range(0,len(names),100):
        group=names[offset:offset+100]
        result=client.call('list_documents',{'doctype':'Course Lesson',
            'fields':['name','custom_avo_id','custom_avo_account','course','chapter','is_draft','include_in_preview'],
            'filters':[['name','in',group]],'limit':len(group)})
        rows=result.get('documents')
        if not isinstance(rows,list) or result.get('has_next_page') or len(rows)!=len(group):
            raise Review('course_outline_invalid')
        for row in rows:
            if not isinstance(row,dict) or row.get('name') not in group or row['name'] in by_name:
                raise Review('course_outline_invalid')
            by_name[row['name']]=row
    ids=[]
    for name in names:
        lesson=by_name[name]
        if lesson.get('custom_avo_account') != ACCOUNT or lesson.get('course') != course_name or lesson.get('chapter') != chapter.get('name') or not lesson.get('is_draft') or lesson.get('include_in_preview'):
            raise Review('existing_lesson_not_safe')
        try:ident=int(lesson['custom_avo_id'])
        except (TypeError,ValueError,KeyError):raise Review('existing_lesson_invalid')
        ids.append(ident)
    return ids


def prepared_images(payload):
    # Reviewed selections omit all images. Match the full source digest using
    # the same rules as the server; changed captures must be reviewed again.
    repo = str(Path(__file__).resolve().parents[2])
    if repo not in sys.path: sys.path.insert(0, repo)
    from lms.lms.avo_transform import reviewed_selection
    if payload.get('format') == 'ape' and reviewed_selection(payload.get('ape'),payload.get('account'),payload.get('course_id'),payload.get('lesson_id')):
        return {}
    from lms.lms.avo_transform import omit_placeholder_section, omit_placeholder_node
    pending=[payload['ape']]; images={}
    while pending:
        node=pending.pop()
        if not isinstance(node,dict):continue
        if (omit_placeholder_section(node,payload.get('account'),payload.get('course_id'),payload.get('lesson_id')) or
                omit_placeholder_node(node,payload.get('account'),payload.get('course_id'),payload.get('lesson_id'))):continue
        if node.get('name')=='image':
            key=node.get('id'); match=REVIEWED_IMAGES.get((payload.get('course_id'),payload.get('lesson_id'),key))
            source=node.get('fields',{}).get('imageSrc')
            if not match or not isinstance(source,str) or hashlib.sha256(source.encode('utf-8')).hexdigest()!=match[0] or key in images:
                raise Review('image_requires_preparation')
            try: raw=(DATA/match[2]).read_bytes()
            except OSError: raise Review('image_requires_preparation')
            if len(raw)>5*1024*1024 or hashlib.sha256(raw).hexdigest()!=match[1]:raise Review('image_requires_preparation')
            images[key]=base64.b64encode(raw).decode('ascii')
        if isinstance(node.get('children'),list):pending.extend(node['children'])
    return images


def preview(client,payload,images=None):
    args={'payload':payload,'dry_run':True}
    if images:args['images']=images
    result=client.call('call_method',{'method':'lms.lms.avo_import.import_lesson','args':args}).get('result')
    if not isinstance(result,dict) or result.get('account') != ACCOUNT or str(result.get('lesson_id')) != str(payload['lesson_id']) or str(result.get('course_id')) != str(payload['course_id']) or result.get('dry_run') is not True:
        raise Stop('preview_identity_invalid')
    for key in ('issues','warnings'):
        if not isinstance(result.get(key),list) or any(not isinstance(x,str) or not re.fullmatch(r'[a-z0-9_]{1,80}',x) for x in result[key]):
            raise Stop('preview_diagnostic_invalid')
    return result


def import_course(client,journal,course,expected,apply):
    if course in EXCLUDED_COURSES:
        journal.event(course,None,'course_excluded',['user_excluded_course'])
        return 'excluded'
    if expected is None: raise Review('manifest_missing_or_changed')
    excluded=[ident for ident in expected if ident in EXCLUDED_LESSONS]
    if excluded and len(excluded)==len(expected):
        for ident in excluded:journal.event(course,ident,'lesson_excluded',['user_excluded_test_lesson'])
        return 'excluded'
    payloads=prepare_course(course,expected)
    if excluded:
        for ident in excluded:journal.event(course,ident,'lesson_excluded',['user_excluded_test_lesson'])
        expected=[ident for ident in expected if ident not in EXCLUDED_LESSONS]
        payloads=[p for p in payloads if p['lesson_id'] not in EXCLUDED_LESSONS]
    existing=outline(client,course)
    if existing != expected[:len(existing)] or len(existing)>len(expected):
        raise Review('course_order_conflict')
    if existing == expected:
        journal.event(course,None,'existing_structure_unverified'); return 'already_present'
    checks=[]; image_sets={}; needs_review=False
    # Existing draft lessons are intentionally left as they were. Their
    # identity, account and exact prefix order were checked by outline();
    # reinterpreting their historic source could conflict with owner edits.
    if existing:
        journal.event(course,None,'existing_prefix_preserved',['existing_content_not_reverified'])
    for p in payloads[len(existing):]:
        # The live schema was widened to 512. The server also checks the
        # sanitized title against its actual site metadata before writing.
        too_long=[]
        if len(p['course_title'])>512:too_long.append('course_title_exceeds_frappe_limit')
        if len(p['lesson_title'])>512:too_long.append('lesson_title_exceeds_frappe_limit')
        if too_long:
            journal.event(course,p['lesson_id'],'lesson_needs_review',too_long)
            needs_review=True; continue
        try:images=prepared_images(p)
        except Review:
            journal.event(course,p['lesson_id'],'lesson_needs_review',['image_requires_preparation'])
            needs_review=True; continue
        image_sets[p['lesson_id']]=images
        result=preview(client,p,images)
        if result.get('ready') is not True:
            journal.event(course,p['lesson_id'],'lesson_needs_review',result['issues']);needs_review=True;continue
        journal.event(course,p['lesson_id'],'lesson_preflight',result['warnings'])
        checks.append(result)
    if needs_review: raise Review('course_needs_review')
    if any(r.get('action') == 'already_imported' for r in checks):
        raise Review('course_order_conflict')
    if not apply:
        journal.event(course,None,'course_ready');return 'ready'
    for p in payloads[len(existing):]:
        # Re-check the complete current prefix before every mutation.
        if outline(client,course) != expected[:expected.index(p['lesson_id'])]:
            journal.event(course,p['lesson_id'],'course_changed',['course_changed_during_import'])
            raise Stop('course_changed_during_import')
        try:
            args={'payload':p,'dry_run':False}
            if image_sets[p['lesson_id']]:args['images']=image_sets[p['lesson_id']]
            result=client.call('call_method',{'method':'lms.lms.avo_import.import_lesson','args':args}).get('result')
            if not isinstance(result,dict) or result.get('action') != 'created':raise Stop('write_result_uncertain')
            verified=preview(client,p,image_sets[p['lesson_id']])
            if verified.get('action') != 'already_imported':raise Stop('readback_failed')
        except Exception as exc:
            journal.event(course,p['lesson_id'],'write_uncertain',['write_result_uncertain'])
            raise Stop('write_result_uncertain') from exc
        journal.event(course,p['lesson_id'],'lesson_created',verified['warnings'])
        print(json.dumps({'course':course,'lesson':p['lesson_id'],'status':'draft_created'}),flush=True)
    if outline(client,course) != expected:raise Stop('final_order_mismatch')
    journal.event(course,None,'course_created');return 'created'


def record_course_review(journal, course, error):
    reason = str(error)
    journal.event(course,None,'course_needs_review',[reason])
    # Unsupported lesson content is an item for later review, not a system
    # failure. Connection, account and uncertain-write errors still stop.
    if reason != 'course_needs_review' and journal.failure():
        raise Stop('too_many_consecutive_errors')


def main():
    parser=argparse.ArgumentParser(description='Перенос снимков mv-centr в черновики Frappe')
    parser.add_argument('--apply',action='store_true',help='создавать черновики; без флага только проверка')
    parser.add_argument('--from-course',type=int,default=1)
    parser.add_argument('--course',type=int,help='проверить или перенести один курс')
    parser.add_argument('--limit',type=int,default=0,help='максимум курсов за запуск; 0 — без ограничения')
    parser.add_argument('--resume',action='store_true',help='снять остановку после разбора журнала')
    parser.add_argument('--report',action='store_true',help='обновить отчёт без подключения к сайтам')
    parser.add_argument('--remote-journal',action='store_true',help='хранить рабочий журнал на сервере Frappe')
    parser.add_argument('--review-queue',action='store_true',help='повторно обработать курсы из отчёта')
    args=parser.parse_args()
    if args.from_course<1 or args.limit<0 or (args.course is not None and args.course<1):parser.error('неверный номер')
    client=None; journal=None
    try:
        marker=DATA/'mv-centr-remote-journal.enabled'
        if marker.exists() and not args.remote_journal:raise Stop('remote_journal_required')
        journal=RemoteJournal() if args.remote_journal else Journal(DATA/'mv-centr-frappe-import.sqlite')
        if args.report:
            journal.report();print(str(REPORT));return 0
        courses=course_ids(args.from_course,args.course)
        if args.review_queue:
            if not args.remote_journal:raise Stop('remote_journal_required')
            candidates=set(journal.candidates())
            courses=[item for item in courses if item[0] in candidates]
        if args.resume:journal.resume()
        if journal.state()[0]:raise Stop('journal_paused')
        client=MCP()
        for cid,ids in courses[:args.limit or None]:
            try:
                status=import_course(client,journal,cid,ids,args.apply)
                journal.success()
                print(json.dumps({'course':cid,'status':status},ensure_ascii=True),flush=True)
            except Review as error:
                record_course_review(journal,cid,error)
                print(json.dumps({'course':cid,'status':'needs_review','reason':str(error)}),flush=True)
            journal.report()
        return 0
    except Exception as error:
        code=str(error) if isinstance(error,Stop) and re.fullmatch(r'[a-z0-9_]{1,80}',str(error)) else 'unexpected_failure'
        if journal and code not in ('journal_paused','too_many_consecutive_errors'):
            try:journal.event(None,None,'stopped',[code]);journal.failure(immediate=True)
            except Stop:pass
        print(json.dumps({'status':'stopped','reason':code}),file=sys.stderr,flush=True)
        return 1
    finally:
        if client:client.close()
        if journal:
            try:
                try:journal.report()
                except Stop:
                    print('Журнал сервера недоступен; перенос остановлен.',file=sys.stderr,flush=True)
                    raise SystemExit(1)
            finally:journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
