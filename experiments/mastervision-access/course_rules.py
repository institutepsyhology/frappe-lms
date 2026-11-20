"""Read access settings from a verified MV course capture. No network or Frappe writes."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlsplit
import zlib


ORIGIN = 'https://shop.mastervision.su'
ACCOUNT = 'mastervision'
MSK = timezone(timedelta(hours=3))
_path = Path(__file__).resolve().parents[1] / 'avo-batch-import/support/collector/lesson_content/packed.py'
_spec = importlib.util.spec_from_file_location('mv_notice_packed', _path)
_packed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _packed
_spec.loader.exec_module(_packed)


def require(ok, code):
    if not ok:
        raise ValueError(code)


def bound(value, *, open_end=False):
    if open_end and value == '9999-12-31 23:59:59':
        return {'kind': 'unlimited', 'iso': None}
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        return {'kind': 'unknown', 'iso': None}
    try:
        date = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return {'kind': 'unknown', 'iso': None}
    return {'kind': 'datetime', 'iso': date.replace(tzinfo=MSK).isoformat()}


def safe_url(value):
    if not isinstance(value, str) or re.search(r'[\s\\{}<>\x00-\x1f\x7f]', value):
        return None
    try:
        url = urlsplit(value)
        if url.scheme == 'https' and url.hostname and url.username is None and url.password is None:
            return value
    except ValueError:
        pass
    return None


class NoticeHTML(HTMLParser):
    tags = {'p','h1','h2','h3','h4','h5','h6','div','br','b','strong','i','em','u',
            'ul','ol','li','a','blockquote','span','s','sub','sup','hr','table','tbody','td','tr','th'}
    def __init__(self, warnings):
        super().__init__()
        self.warnings = warnings
        self.output = []
        self.suppressed = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.append(tag)
            return
        if tag in ('script','style','iframe','object','form','svg','math','template'):
            self.suppressed.append(tag)
            if tag == 'iframe' and (url := safe_url(attrs.get('src'))):
                label = attrs.get('title') or url
                self.output.append(f'<a href="{escape(url, quote=True)}">{escape(label)}</a>')
                self.warnings.add('iframe_as_link')
            else:
                self.warnings.add('omitted_' + tag)
            return
        if tag not in self.tags:
            self.warnings.add('omitted_markup')
            return
        href = safe_url(attrs.get('href')) if tag == 'a' else None
        self.output.append(f'<a href="{escape(href,quote=True)}">' if href else f'<{tag}>')

    def handle_endtag(self, tag):
        if self.suppressed:
            if tag == self.suppressed[-1]:
                self.suppressed.pop()
        elif tag in self.tags and tag not in ('br','hr'):
            self.output.append(f'</{tag}>')

    def handle_data(self, data):
        if not self.suppressed:
            self.output.append(escape(data))


def read_notice(payload):
    warnings = set()
    parts = []
    if not payload:
        return '', []
    root = _packed.decode_ape_payload(payload)['json']
    require(root.get('name') == 'page', 'unknown_notice_root')
    def visit(node):
        fields = node.get('fields') or {}
        name = node.get('name')
        if fields.get('visibleConditions') or fields.get('displayDelay'):
            warnings.add('conditional_notice_block')
            return
        if name in ('text','code'):
            renderer = NoticeHTML(warnings)
            renderer.feed(fields.get('html') or '')
            renderer.close()
            parts.append(''.join(renderer.output))
        elif name not in ('row','column','columns','page','section','container'):
            warnings.add('unrepresented_notice_block')
        for child in node.get('children') or []:
            visit(child)
    visit(root)
    return '\n'.join(part for part in parts if part), sorted(warnings)


def editor_notice(markup):
    """Factory for the read-only EditorJS viewer installed in Frappe Learning."""
    if not markup:
        return None
    blocks = []
    pos = 0
    pattern = re.compile(r'\s*<(p|h[1-6])>((?:(?!</?(?:p|h[1-6])\b).)*?)</\1>', re.S)
    while pos < len(markup):
        if not markup[pos:].strip():
            break
        match = pattern.match(markup, pos)
        if not match:
            # HTML has already been reduced to inert, allowlisted text and links.
            blocks.append({'type':'htmlBlock','data':{'encodedHtml':base64.b64encode(
                markup[pos:].encode()).decode('ascii'),'height':600}})
            break
        tag, content = match.groups()
        if tag == 'p':
            blocks.append({'type':'paragraph','data':{'text':content}})
        else:
            blocks.append({'type':'header','data':{'text':content,'level':int(tag[1])}})
        pos = match.end()
    return json.dumps({'blocks':blocks}, ensure_ascii=False, separators=(',',':'))


def read_fresh_rules(capture, archived_rules=None):
    cid = capture['course_id']
    require(type(cid) is int and cid > 0 and capture['source_origin'] == ORIGIN, 'wrong_course_origin')
    if archived_rules is not None:
        require(archived_rules['course_id'] == cid, 'course_id_mismatch')
    settings = capture['settings']
    mode = str(settings.get('start_date_used'))
    start = None if mode == '0' else bound(settings.get('start_date') if mode == '1' else None)
    shown = settings.get('always_show')
    require(shown in ('0','1',0,1), 'unknown_notice_visibility')
    notice, warnings = read_notice(capture.get('no_access_info')) if shown in ('1',1) else ('', [])
    retention = settings.get('permanent_lesson_access')
    require(retention in (0,1,'0','1'), 'unknown_completed_retention')
    days = settings.get('permanent_lesson_access_days')
    require(not isinstance(days, bool) and (days in (None,'') or re.fullmatch(r'[0-9]{1,6}',str(days))),
            'unknown_completed_retention_days')
    draft_ids = capture.get('draft_lesson_ids')
    if draft_ids is None and archived_rules is not None:
        draft_ids = archived_rules['draft_lesson_ids']
    require(isinstance(draft_ids, list) and all(type(v) is int and v > 0 for v in draft_ids)
            and len(draft_ids) == len(set(draft_ids)), 'unconfirmed_draft_lessons')
    return {'course_id': cid, 'end_at': bound(settings.get('end_date'), open_end=True),
            'starts_at': start, 'draft_lesson_ids': sorted(draft_ids),
            'access_notice_content': editor_notice(notice), 'show_when_unavailable': int(shown),
            'lesson_rules': capture.get('lesson_rules', {}),
            'notice_warnings': warnings,
            'permanent_lesson_access': bool(int(retention)),
            'permanent_lesson_access_days': int(days) if days not in (None, '') else None}


def read_course_rules(archive, course_id):
    require(archive.execute('select account, origin from meta').fetchall() == [(ACCOUNT, ORIGIN)], 'wrong_archive')
    row = archive.execute("select payload from captures where kind='course' and course=? and lesson=0 "
                          "order by at desc, rowid desc limit 1", (course_id,)).fetchone()
    require(row is not None, 'missing_course')
    data = json.loads(zlib.decompress(row[0]))
    source = data['parsed']
    require(data.get('verified') is True and not data.get('error') and data['account'] == ACCOUNT
            and data['origin'] == ORIGIN and source['course_id'] == course_id, 'unverified_course')
    settings = {}
    for r in source['settings']:
        attrs = r['attrs']
        name = re.fullmatch(r'TrainingForm\[(start_date_used|start_date|end_date|always_show|permanent_lesson_access|permanent_lesson_access_days)\]', attrs.get('name',''))
        if not name or attrs.get('type') == 'hidden':
            continue
        if r['tag'] == 'select':
            selected = [v['attrs']['value'] for v in r['options'] if 'selected' in v['attrs']]
            value = selected[0] if len(selected) == 1 else None
        elif attrs.get('type') == 'checkbox':
            value = int('checked' in attrs)
        else:
            value = r.get('value')
        settings[name[1]] = value
    draft_ids = []
    for lesson in source['lessons']:
        flag = lesson['raw'].get('is_draft')
        require(flag in (0,1) and lesson['raw']['id_training'] == course_id, 'unconfirmed_draft_flags')
        if flag:
            draft_ids.append(lesson['id'])
    pattern = r"""AWO\.APE\(\s*(['"])#TrainingForm_no_access_info\1\s*,\s*\{\s*['"]?formatVersion['"]?\s*:\s*(\d+)\s*,\s*['"]?packed['"]?\s*:\s*(true|false)\s*,\s*['"]?block['"]?\s*:\s*('[^']*'|"[^"]*")"""
    matches = list(re.finditer(pattern, data['html']))
    require(len(matches) <= 1, 'duplicate_notice_editor')
    payload = None
    if matches:
        m = matches[0]
        payload = {'formatVersion':int(m[2]), 'packed':m[3]=='true', 'block':_packed.unquote_js_string(m[4])}
    elif settings.get('always_show'):
        raise ValueError('unconfirmed_notice_editor')
    return read_fresh_rules({'course_id':course_id,'source_origin':ORIGIN,'settings':settings,
                             'draft_lesson_ids':draft_ids,'no_access_info':payload})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fresh-dir', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    db = sqlite3.connect(args.archive.resolve().as_uri()+'?mode=ro', uri=True) if args.archive else None
    courses = {}
    for item in sorted(args.fresh_dir.glob('*.json')):
        if not re.fullmatch('[1-9][0-9]*', item.stem):
            continue
        capture = json.loads(item.read_text(encoding='utf-8-sig'))
        require(capture['course_id'] == int(item.stem), 'filename_id_mismatch')
        fallback = read_course_rules(db, int(item.stem)) if db and 'draft_lesson_ids' not in capture else None
        try:
            rules = read_fresh_rules(capture, fallback)
        except (ValueError, KeyError, TypeError) as error:
            if item.stem == '598':
                raise
            print(json.dumps({'course_id': int(item.stem), 'status': 'review_course_settings',
                              'reason': type(error).__name__}), flush=True)
            continue
        # Only the club's verified text and two links have an explicit decision
        # about its old form. Surface unrepresented material in other notices.
        approved = {'iframe_as_link', 'omitted_script'} if item.stem == '598' else set()
        unresolved = set(rules['notice_warnings']) - approved
        if unresolved:
            print(json.dumps({'course_id': int(item.stem), 'status': 'review_course_notice',
                              'reasons': sorted(unresolved)}), flush=True)
            continue
        courses[item.stem] = rules
    require(courses, 'no_fresh_courses')
    temp = args.out.with_name(args.out.name+'.tmp')
    temp.write_text(json.dumps({'account':ACCOUNT,'origin':ORIGIN,'courses':courses},ensure_ascii=False),
                    encoding='utf-8')
    temp.replace(args.out)


if __name__ == '__main__':
    main()
