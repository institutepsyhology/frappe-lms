"""Extract a literal APE payload from an editor response without executing JS."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
import re

from packed import unquote_js_string, decode_ape_payload, PackedError

ORIGIN = 'https://shop.mv-centr.ru'
MAX_PAGE_CHARS = 32 * 1024 * 1024
_STRING = r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""
_APE = re.compile(
    r"AWO\.APE\s*\(\s*(['\"])#TrainingLessons_description_ape\1\s*,\s*\{"
    r"\s*['\"]?formatVersion['\"]?\s*:\s*(\d+)\s*,"
    r"\s*['\"]?packed['\"]?\s*:\s*(true|false)\s*,"
    r"\s*['\"]?block['\"]?\s*:\s*(" + _STRING + r")", re.DOTALL)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.scripts = []
        self.current = []
        self.links = []
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'script' and 'src' not in a:
            self.in_script, self.current = True, []
        if tag == 'a' and a.get('href'):
            self.links.append(a['href'])
        if tag == 'input':
            self.inputs.append(a)

    def handle_data(self, data):
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_script:
            self.scripts.append(''.join(self.current))
            self.in_script = False


def parse_editor_page(html, origin, lesson_id, expected_course_id):
    if origin != ORIGIN:
        raise ValueError('wrong_origin')
    if type(lesson_id) is not int or lesson_id < 1 or type(expected_course_id) is not int or expected_course_id < 1:
        raise ValueError('invalid_id')
    if not isinstance(html, str) or not html or len(html) > MAX_PAGE_CHARS:
        raise ValueError('invalid_page_size')
    page = Page()
    page.feed(html)
    # The editor supplies a real course link in the current form. Multiple
    # distinct IDs or no match cannot be safely associated with an account.
    matches = set()
    for href in page.links:
        u = urlsplit(href)
        if u.netloc and (u.scheme + '://' + u.netloc) != origin:
            continue
        if u.path == '/shop/training/admin/update':
            values = parse_qs(u.query).get('id', [])
            if len(values) == 1 and values[0].isdigit():
                matches.add(int(values[0]))
    if matches != {expected_course_id}:
        raise ValueError('course_identity_unconfirmed')
    if not any(x.get('name') == 'TrainingLessons[training_lessons]' for x in page.inputs):
        raise ValueError('lesson_editor_unconfirmed')
    found = []
    for script in page.scripts:
        found.extend(_APE.findall(script))
    if len(found) != 1:
        raise ValueError('ape_payload_missing_or_ambiguous')
    _, version, packed, token = found[0]
    if packed != 'true':
        raise PackedError('unpacked payload requires review')
    payload = {'formatVersion': int(version), 'packed': True, 'block': unquote_js_string(token)}
    result = decode_ape_payload(payload)
    return {'account': 'mv-centr', 'account_origin': origin, 'course_id': expected_course_id,
            'lesson_id': lesson_id, 'decoded': result}
