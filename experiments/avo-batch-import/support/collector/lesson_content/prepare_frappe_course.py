"""Prepare a course only after the live AVO editor and local snapshots agree.

Read {course_id, html} from stdin; emit private payloads to stdout only.
Caller must protect the stream and use the matching mv-centr MCP endpoint.
"""
import html as html_lib
import json
from pathlib import Path
import re
import sqlite3
import sys
from course_source import _literal_array, course_lessons_from_html
from page_extract import Page

ROOT=Path(__file__).resolve().parents[2]
ORIGIN='https://shop.mv-centr.ru'


def prepare(course, html):
    if type(course) is not int or course<1: raise ValueError('invalid_course')
    ids=course_lessons_from_html(html,course)
    page=Page();page.feed(html)
    scripts=[s for s in page.scripts if re.search(r'\.LessonsEditor\s*\(',s)]
    if len(scripts)!=1:raise ValueError('ambiguous_editor')
    fields=list(re.finditer(r"['\"]trainingLessonsTree['\"]\s*:\s*",scripts[0]))
    if len(fields)!=1:raise ValueError('ambiguous_tree')
    tree=_literal_array(scripts[0],fields[0].end())
    names={}
    def visit(v):
        if isinstance(v,list):
            for i in v:visit(i)
        elif isinstance(v,dict):
            if 'id_training_lessons' in v:
                n=v['id_training_lessons']; title=v.get('training_lessons')
                if n in names or not isinstance(title,str) or not title.strip():raise ValueError('ambiguous_lesson_title')
                names[n]=title
            else:
                for child in v.values():
                    if isinstance(child,(dict,list)):visit(child)
    visit(tree)
    if list(names)!=ids:raise ValueError('lesson_order_mismatch')
    catalog=json.loads((ROOT/'exports/course-catalogues/mv-centr-observed.json').read_text(encoding='utf-8'))
    if catalog.get('account')!='mv-centr':raise ValueError('wrong_account')
    rows=[x for x in catalog['courses'] if str(x['course_id'])==str(course)]
    if len(rows)!=1:raise ValueError('course_missing_in_catalog')
    titles={x['value']['title'] for x in rows[0]['observed_course_values'] if isinstance(x.get('value',{}).get('title'),str)}
    live_html=html_lib.unescape(html)
    titles={t for t in titles if t and t in live_html}
    if len(titles)!=1:raise ValueError('course_title_unconfirmed')
    course_title=titles.pop()
    base=ROOT/'exports/lesson-content'
    captures=sqlite3.connect('file:'+(base/'mv-centr-captures.sqlite').resolve().as_posix()+'?mode=ro',uri=True)
    queue=sqlite3.connect('file:'+(base/'mv-centr-queue.sqlite').resolve().as_posix()+'?mode=ro',uri=True)
    try:
        if queue.execute('select origin from queue_meta where singleton=1').fetchone()!=(ORIGIN,):raise ValueError('wrong_account')
        out=[]
        for n in ids:
            state=queue.execute('select state from queue_items where course_id=? and lesson_id=?',(course,n)).fetchone()
            record=captures.execute("select decoded_json from captures where account='mv-centr' and course_id=? and lesson_id=? and decoded_json is not null order by id desc limit 1",(course,n)).fetchone()
            if state!=('candidate',) or not record:raise ValueError('snapshot_requires_review')
            out.append({'account':'mv-centr','source_origin':ORIGIN,'course_id':course,'lesson_id':n,
                        'course_title':course_title,'lesson_title':names[n],'format':'ape','ape':json.loads(record[0])})
        return out
    finally:captures.close();queue.close()


if __name__=='__main__':
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    try:
        x=json.load(sys.stdin);print(json.dumps(prepare(x['course_id'],x['html']),ensure_ascii=True))
    except Exception as e:
        allowed={'invalid_course','ambiguous_editor','ambiguous_tree','ambiguous_lesson_title','lesson_order_mismatch','wrong_account','course_missing_in_catalog','course_title_unconfirmed','snapshot_requires_review','source_structure_error','source_identity_mismatch'}
        print(json.dumps({'error':str(e) if str(e) in allowed else 'preparation_failed'}));sys.exit(1)
