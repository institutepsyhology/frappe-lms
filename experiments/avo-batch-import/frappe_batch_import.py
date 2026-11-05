"""Resume-safe draft import from the isolated mv-centr AVO snapshots via Frappe MCP.

Default is a read-only check. --apply creates drafts; it never publishes or
grants access. The event database contains identifiers and diagnostic codes,
never lesson text, URLs, cookies, or authentication details.
"""
import argparse
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


ROOT = workspace_root()
DATA = ROOT / 'exports/lesson-content'
SITE = 'my-lk.mv-centr.ru'
ORIGIN = 'https://shop.mv-centr.ru'
ACCOUNT = 'mv-centr'
MAX_ERRORS = 3
REPORT = DATA / 'ОТЧЁТ-перенос-mv-centr.md'
# User-confirmed disposable test lesson. This is a lesson ID, not course 17.
EXCLUDED_LESSONS = {17}


class Stop(Exception):
    pass


class Review(Exception):
    pass


def readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)


def course_ids(start=1, selected=None):
    with readonly(DATA / 'mv-centr-captures.sqlite') as db:
        if db.execute('select account,origin from capture_meta where singleton=1').fetchone() != (ACCOUNT, ORIGIN):
            raise Stop('wrong_capture_account')
    with readonly(DATA / 'mv-centr-queue.sqlite') as db:
        if db.execute('select origin from queue_meta where singleton=1').fetchone() != (ORIGIN,):
            raise Stop('wrong_queue_account')
    with readonly(DATA / 'mv-centr-course-manifests.sqlite') as db:
        if db.execute('select account,origin from manifest_meta where singleton=1').fetchone() != (ACCOUNT, ORIGIN):
            raise Stop('wrong_manifest_account')
        rows = db.execute('select course_id,lesson_ids,sha256,state from course_manifests order by course_id,id').fetchall()
    with readonly(DATA / 'mv-centr-course-catalog.sqlite') as db:
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
    for cid in sorted(set(catalog).intersection(grouped)):
        if cid < start or (selected is not None and cid != selected):
            continue
        variants = grouped[cid]
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
    doc=client.call('get_document',{'doctype':'LMS Course','name':row['name']})
    chapters=doc.get('chapters')
    if not isinstance(chapters,list) or len(chapters)!=1:raise Review('course_chapters_ambiguous')
    chapter=client.call('get_document',{'doctype':'Course Chapter','name':chapters[0]['chapter']})
    if chapter.get('course') != row['name'] or chapter.get('is_scorm_package'):raise Review('course_chapter_invalid')
    lessons=chapter.get('lessons')
    if not isinstance(lessons,list):raise Review('course_outline_invalid')
    ids=[]
    for position,item in enumerate(lessons,1):
        if item.get('idx') != position:raise Review('course_outline_invalid')
        lesson=client.call('get_document',{'doctype':'Course Lesson','name':item['lesson']})
        if lesson.get('custom_avo_account') != ACCOUNT or lesson.get('course') != row['name'] or lesson.get('chapter') != chapter.get('name') or not lesson.get('is_draft') or lesson.get('include_in_preview'):
            raise Review('existing_lesson_not_safe')
        try:ident=int(lesson['custom_avo_id'])
        except (TypeError,ValueError,KeyError):raise Review('existing_lesson_invalid')
        ids.append(ident)
    return ids


def preview(client,payload):
    result=client.call('call_method',{'method':'lms.lms.avo_import.import_lesson','args':{'payload':payload,'dry_run':True}}).get('result')
    if not isinstance(result,dict) or result.get('account') != ACCOUNT or str(result.get('lesson_id')) != str(payload['lesson_id']) or str(result.get('course_id')) != str(payload['course_id']) or result.get('dry_run') is not True:
        raise Stop('preview_identity_invalid')
    for key in ('issues','warnings'):
        if not isinstance(result.get(key),list) or any(not isinstance(x,str) or not re.fullmatch(r'[a-z0-9_]{1,80}',x) for x in result[key]):
            raise Stop('preview_diagnostic_invalid')
    return result


def import_course(client,journal,course,expected,apply):
    if expected is None: raise Review('manifest_changed')
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
    checks=[]
    for p in payloads:
        pending=[p['ape']]
        while pending:
            node=pending.pop()
            if isinstance(node,dict):
                if node.get('name')=='image':
                    journal.event(course,p['lesson_id'],'lesson_needs_review',['image_requires_preparation'])
                    raise Review('course_needs_review')
                if isinstance(node.get('children'),list):pending.extend(node['children'])
        result=preview(client,p)
        if result.get('ready') is not True:
            journal.event(course,p['lesson_id'],'lesson_needs_review',result['issues']);raise Review('course_needs_review')
        journal.event(course,p['lesson_id'],'lesson_preflight',result['warnings'])
        checks.append(result)
    if any(r.get('action') != 'already_imported' for r in checks[:len(existing)]):
        raise Review('existing_lesson_conflict')
    if any(r.get('action') == 'already_imported' for r in checks[len(existing):]):
        raise Review('course_order_conflict')
    if not apply:
        journal.event(course,None,'course_ready');return 'ready'
    for p in payloads[len(existing):]:
        # Re-check the complete current prefix before every mutation.
        if outline(client,course) != expected[:expected.index(p['lesson_id'])]:
            journal.event(course,p['lesson_id'],'course_changed',['course_changed_during_import'])
            raise Stop('course_changed_during_import')
        try:
            result=client.call('call_method',{'method':'lms.lms.avo_import.import_lesson','args':{'payload':p,'dry_run':False}}).get('result')
            if not isinstance(result,dict) or result.get('action') != 'created':raise Stop('write_result_uncertain')
            verified=preview(client,p)
            if verified.get('action') != 'already_imported':raise Stop('readback_failed')
        except Exception as exc:
            journal.event(course,p['lesson_id'],'write_uncertain',['write_result_uncertain'])
            raise Stop('write_result_uncertain') from exc
        journal.event(course,p['lesson_id'],'lesson_created',verified['warnings'])
        print(json.dumps({'course':course,'lesson':p['lesson_id'],'status':'draft_created'}),flush=True)
    if outline(client,course) != expected:raise Stop('final_order_mismatch')
    journal.event(course,None,'course_created');return 'created'


def main():
    parser=argparse.ArgumentParser(description='Перенос снимков mv-centr в черновики Frappe')
    parser.add_argument('--apply',action='store_true',help='создавать черновики; без флага только проверка')
    parser.add_argument('--from-course',type=int,default=1)
    parser.add_argument('--course',type=int,help='проверить или перенести один курс')
    parser.add_argument('--limit',type=int,default=0,help='максимум курсов за запуск; 0 — без ограничения')
    parser.add_argument('--resume',action='store_true',help='снять остановку после разбора журнала')
    parser.add_argument('--report',action='store_true',help='обновить отчёт без подключения к сайтам')
    args=parser.parse_args()
    if args.from_course<1 or args.limit<0 or (args.course is not None and args.course<1):parser.error('неверный номер')
    client=None; journal=None
    try:
        journal=Journal(DATA/'mv-centr-frappe-import.sqlite')
        if args.report:
            journal.report();print(str(REPORT));return 0
        courses=course_ids(args.from_course,args.course)
        if args.resume:journal.resume()
        if journal.state()[0]:raise Stop('journal_paused')
        client=MCP()
        for cid,ids in courses[:args.limit or None]:
            try:
                status=import_course(client,journal,cid,ids,args.apply)
                journal.success()
                print(json.dumps({'course':cid,'status':status},ensure_ascii=True),flush=True)
            except Review as error:
                journal.event(cid,None,'course_needs_review',[str(error)])
                print(json.dumps({'course':cid,'status':'needs_review','reason':str(error)}),flush=True)
                if journal.failure():raise Stop('too_many_consecutive_errors')
        return 0
    except Exception as error:
        code=str(error) if isinstance(error,Stop) and re.fullmatch(r'[a-z0-9_]{1,80}',str(error)) else 'unexpected_failure'
        if journal and code not in ('journal_paused','too_many_consecutive_errors'):
            journal.event(None,None,'stopped',[code]);journal.failure(immediate=True)
        print(json.dumps({'status':'stopped','reason':code}),file=sys.stderr,flush=True)
        return 1
    finally:
        if client:client.close()
        if journal:
            try:journal.report()
            finally:journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
