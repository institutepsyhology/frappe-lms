"""Read-only Master Vision source parsing; never execute JS.

The transport must verify the response URL/origin before supplying HTML: a page
containing only relative URLs cannot itself prove which host returned it.
"""
import ast
from dataclasses import dataclass
from html.parser import HTMLParser
import importlib.util
import math
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urljoin, urlsplit

ACCOUNT = 'mastervision'
ORIGIN = 'https://shop.mastervision.su'
MAX_HTML = 32 * 1024 * 1024
COURSE = '/shop/training/admin/update'
LESSON = '/shop/training/traininglessons/admin/update'
CATALOG = '/shop/training/admin/admin'


class Review(ValueError):
    """A fixed diagnostic code; never include source content or URLs."""


@dataclass(frozen=True)
class Config:
    account: str = ACCOUNT
    origin: str = ORIGIN

    def __post_init__(self):
        if self.account != 'mastervision' or self.origin != 'https://shop.mastervision.su':
            raise Review('wrong_account_origin')


_path = Path(__file__).resolve().parents[1] / 'avo-batch-import/support/collector/lesson_content/packed.py'
_spec = importlib.util.spec_from_file_location('mastervision_packed_support', _path)
_packed = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _packed
_spec.loader.exec_module(_packed)
_STRING = r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\""


def _js_key(name):
    return '(?:' + name + "|'" + name + "'|\"" + name + '\")'


_APE_CALL = re.compile(r"AWO\.APE\s*\(\s*(['\"])#TrainingLessons_description_ape\1\s*,", re.S)
_APE_HEAD = (_APE_CALL.pattern + r'\s*\{\s*' + _js_key('formatVersion') + r'\s*:\s*(\d+)\s*,'
             r'\s*' + _js_key('packed') + r'\s*:\s*(true|false)\s*,'
             r'\s*' + _js_key('block') + r'\s*:\s*(' + _STRING + r')')
_APE = re.compile(_APE_HEAD + r'\s*\}\s*[,)]', re.S)
# Observed editor UI option, not lesson content. Only this exact literal
# fieldset and integer map is accepted; expressions and duplicate keys cannot
# match the complete object grammar. The original option is retained below.
_APE_CONDITIONS = re.compile(_APE_HEAD + r'\s*,\s*' + _js_key('visibleConditionsTypes')
    + r'\s*:\s*\{\s*' + _js_key('purchaseGoods') + r'\s*:\s*(0|[1-9][0-9]{0,9})'
    + r'\s*\}\s*\}\s*[,)]', re.S)


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ''.join(x.text() if isinstance(x, Node) else x for x in self.children)

    def nodes(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.nodes(tag)


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node(); self.stack = [self.root]
        self.feed(html); self.close()

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > 256: raise Review('source_depth_exceeded')
        node = Node(tag, attrs); self.stack[-1].children.append(node)
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag: self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]; break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def _page(html):
    Config(ACCOUNT, ORIGIN)
    if not isinstance(html, str) or not html or len(html) > MAX_HTML:
        raise Review('invalid_page_size')
    root = Page(html).root
    # Some AVO sessions fail with a 200 login page rather than a redirect. Only
    # explicit login forms count: normal editor passwords, links, and JS strings
    # must not turn a course structure review into an authentication failure.
    for form in root.nodes('form'):
        inputs = list(form.nodes('input'))
        names = [(item.attrs.get('name') or '').lower() for item in inputs]
        login_model = any(name.startswith(('loginform[', 'userlogin[', 'userloginform[', 'signinform[')) for name in names)
        form_id = re.sub('[^a-z]', '', (form.attrs.get('id') or '').lower())
        try:
            action = urlsplit(form.attrs.get('action') or '').path.rstrip('/').rsplit('/', 1)[-1].lower()
        except ValueError:
            action = ''
        password = any((item.attrs.get('type') or '').lower() == 'password' for item in inputs)
        if login_model or (password and (form_id in {'loginform', 'signinform', 'userloginform'} or
                                        action in {'login', 'signin', 'sign-in', 'sign_in'})):
            raise Review('source_auth_error')
    return root


def _id(value):
    if type(value) is not int or not 0 < value <= 2**53 - 1: raise Review('invalid_id')
    return value


def _url(value, path=None, ident=None):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value): raise Review('source_identity_mismatch')
    url = urlsplit(urljoin(ORIGIN, value))
    if url.scheme + '://' + url.netloc != ORIGIN or (path and url.path != path): raise Review('source_identity_mismatch')
    if ident is not None and parse_qs(url.query).get('id') != [str(ident)]: raise Review('source_identity_mismatch')
    return url.geturl()


def _one(items, code='source_structure_error'):
    if len(items) != 1: raise Review(code)
    return items[0]


def _cover_url(value):
    # A confirmed image field may point to AVO's CDN; it is data, not an
    # account-navigation URL. The caller still controls any later download.
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value): raise Review('course_cover_unrecognized')
    url = urlsplit(urljoin(ORIGIN, value))
    if url.scheme != 'https' or not url.hostname or url.username or url.password: raise Review('course_cover_unrecognized')
    return url.geturl()


def _settings(form):
    result = []
    for node in form.nodes():
        if node.tag not in ('input', 'textarea', 'select', 'button'): continue
        row = {'tag': node.tag, 'attrs': dict(node.attrs)}
        if node.tag == 'textarea': row['value'] = node.text()
        elif node.tag == 'select':
            row['options'] = [{'attrs': dict(x.attrs), 'text': x.text()} for x in node.nodes('option')]
        else: row['value'] = node.attrs.get('value')
        result.append(row)
    return result


def _field(settings, name):
    return _one([row.get('value') for row in settings if row['attrs'].get('name') == name], 'editor_field_unconfirmed')


def parse_catalog(html, page=1):
    _id(page); root = _page(html)
    grid = _one([x for x in root.nodes() if x.attrs.get('id') == 'training-grid'])
    summary = _one([x for x in grid.nodes() if 'summary' in x.attrs.get('class', '').split()]).text()
    match = re.search(r'Элементы\s+(\d+)\s*[—–-]\s*(\d+)\s+из\s+(\d+)', summary)
    if not match: raise Review('catalog_summary_unrecognized')
    start, end, total = map(int, match.groups()); courses = []
    for body in grid.nodes('tbody'):
        for row in body.nodes('tr'):
            links = [a for a in row.nodes('a') if urlsplit(a.attrs.get('href', '')).path == COURSE]
            # A row may repeat its edit link as an icon; all must name one course.
            if not links: raise Review('catalog_row_unrecognized')
            urls = [_url(a.attrs.get('href'), COURSE) for a in links]
            ids = [parse_qs(urlsplit(u).query).get('id', []) for u in urls]
            if any(len(v) != 1 or not re.fullmatch(r'[1-9][0-9]*', v[0]) for v in ids): raise Review('source_identity_mismatch')
            ident = _id(int(ids[0][0]))
            if any(v != ids[0] for v in ids): raise Review('catalog_row_ambiguous')
            title = next((a.text().strip() for a in links if a.text().strip()), '')
            if not title: raise Review('course_title_unconfirmed')
            courses.append({'id': ident, 'title': title, 'editor_url': urls[0]})
    if (not (1 <= start <= end <= total) or (page == 1) != (start == 1)
            or len(courses) != end - start + 1 or len({x['id'] for x in courses}) != len(courses)):
        raise Review('catalog_range_mismatch')
    next_url = None
    if end < total:
        links = {_url(a.attrs.get('href'), CATALOG) for a in grid.nodes('a') if 'Следующая' in a.text()}
        next_url = _one(list(links), 'catalog_next_unconfirmed')
        if parse_qs(urlsplit(next_url).query).get('TrainingSearch_page') != [str(page + 1)]: raise Review('catalog_next_unconfirmed')
    return {'total': total, 'start': start, 'end': end, 'courses': courses, 'next_url': next_url}


def _literal(script, start):
    if start >= len(script) or script[start] != '[': raise Review('course_tree_unrecognized')
    depth = 0; quote = None; escaped = False
    for index in range(start, len(script)):
        char = script[index]
        if quote:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == quote: quote = None
        elif char in "'\"": quote = char
        elif char in '[{': depth += 1
        elif char in ']}':
            depth -= 1
            if not depth:
                try:
                    node = ast.parse(script[start:index + 1], mode='eval')
                    class LiteralNames(ast.NodeTransformer):
                        def visit_Name(self, item):
                            if item.id not in ('true', 'false', 'null'): raise ValueError()
                            return ast.copy_location(ast.Constant({'true': True, 'false': False, 'null': None}[item.id]), item)
                        def visit_Dict(self, item):
                            keys = [ast.literal_eval(x) for x in item.keys]
                            if len(keys) != len(set(keys)): raise ValueError()
                            return self.generic_visit(item)
                    return ast.literal_eval(LiteralNames().visit(node))
                except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError): raise Review('course_tree_unrecognized') from None
    raise Review('course_tree_unrecognized')


def _json_shape(value, depth=0):
    if depth > 128: raise Review('source_depth_exceeded')
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value): raise Review('source_type_unrecognized')
        for child in value.values(): _json_shape(child, depth + 1)
    elif isinstance(value, list):
        for child in value: _json_shape(child, depth + 1)
    elif value is not None and type(value) not in (str, int, bool, float): raise Review('source_type_unrecognized')
    elif type(value) is float and not math.isfinite(value): raise Review('source_type_unrecognized')


def parse_course(html, course_id):
    _id(course_id); root = _page(html)
    form = _one([f for f in root.nodes('form') if any(n.attrs.get('name') == 'TrainingForm[id_training]' for n in f.nodes('input'))])
    settings = _settings(form)
    if _field(settings, 'TrainingForm[id_training]') != str(course_id): raise Review('source_identity_mismatch')
    if form.attrs.get('action'): _url(form.attrs['action'], COURSE, course_id)
    title = _field(settings, 'TrainingForm[training]')
    if not isinstance(title, str) or not title.strip(): raise Review('course_title_unconfirmed')
    trees = []
    for script in root.nodes('script'):
        if script.attrs.get('src') or not re.search(r'\.LessonsEditor\s*\(', script.text()): continue
        for match in re.finditer(r"['\"]trainingLessonsTree['\"]\s*:\s*", script.text()):
            trees.append(_literal(script.text(), match.end()))
    tree = _one(trees, 'course_tree_unrecognized'); _json_shape(tree)
    if not isinstance(tree, list): raise Review('course_tree_unrecognized')
    lessons = []
    def visit(value):
        if isinstance(value, list):
            for child in value: visit(child)
        elif isinstance(value, dict):
            if 'id_training_lessons' in value:
                ident = _id(value['id_training_lessons'])
                if type(value.get('id_training')) is not int or value['id_training'] != course_id: raise Review('source_identity_mismatch')
                link = value.get('links', {}).get('update') if isinstance(value.get('links'), dict) else None
                _url(link, LESSON, ident)
                name = value.get('training_lessons')
                if not isinstance(name, str) or not name.strip(): raise Review('lesson_title_unconfirmed')
                lessons.append({'id': ident, 'title': name, 'raw': value})
            for child in value.values():
                if isinstance(child, (list, dict)): visit(child)
    visit(tree)
    ids = [row['id'] for row in lessons]
    if len(ids) != len(set(ids)): raise Review('duplicate_lesson_id')
    if tree and not ids: raise Review('unrecognized_empty_course_tree')
    cover_names = {'image', 'image_url', 'cover', 'cover_url', 'main_image', 'imageSrc', 'image_src'}
    covers = set()
    for row in settings:
        name = row['attrs'].get('name', '')
        if (name.startswith('TrainingForm[') and name.endswith(']') and name[len('TrainingForm['):-1] in cover_names
                and row.get('value') and row['attrs'].get('type') != 'file'):
            covers.add(_cover_url(row['value']))
    for image in form.nodes('img'):
        if image.attrs.get('id') in {'TrainingForm_' + key for key in cover_names} and image.attrs.get('src'):
            covers.add(_cover_url(image.attrs['src']))
    # Confirmed Yii crop widget: its current image belongs to the course's
    # image field only when both appear in the same editor-form table row.
    image_rows = [row for row in form.nodes('tr') if any(
        label.attrs.get('for') == 'TrainingForm_image' for label in row.nodes('label'))]
    widgets = [node for row in image_rows for node in row.nodes('div') if
        re.fullmatch(r'yii_rcrop_[A-Za-z0-9_]+_currentImage', node.attrs.get('id', ''))
        and 'current-image-wrap' in node.attrs.get('class', '').split()]
    if widgets:
        if len(image_rows) != 1 or len(widgets) != 1: raise Review('course_cover_ambiguous')
        images = list(widgets[0].nodes('img'))
        if len(images) > 1: raise Review('course_cover_ambiguous')
        if images: covers.add(_cover_url(images[0].attrs.get('src')))
    if len(covers) > 1: raise Review('course_cover_ambiguous')
    return {'course_id': course_id, 'title': title, 'lesson_ids': ids, 'lessons': lessons,
            'settings': settings, 'cover_url': next(iter(covers), None), 'tree': tree,
            'empty_reason': 'empty_course_tree' if not ids else None}


def parse_lesson(html, course_id, lesson_id, course_title, lesson_title):
    _id(course_id); _id(lesson_id); root = _page(html)
    if any(not isinstance(x, str) or not x.strip() for x in (course_title, lesson_title)): raise Review('invalid_title')
    form = _one([f for f in root.nodes('form') if any(n.attrs.get('name') == 'TrainingLessons[training_lessons]' for n in f.nodes('input'))])
    settings = _settings(form)
    if _field(settings, 'TrainingLessons[training_lessons]') != lesson_title: raise Review('lesson_title_changed')
    links = [a for a in root.nodes('a') if urlsplit(a.attrs.get('href', '')).path == COURSE]
    if not links: raise Review('course_identity_unconfirmed')
    for anchor in links: _url(anchor.attrs.get('href'), COURSE, course_id)
    own = [row.get('value') for row in settings if row['attrs'].get('name') == 'TrainingLessons[id_training_lessons]']
    if own and own != [str(lesson_id)]: raise Review('source_identity_mismatch')
    parent = [row.get('value') for row in settings if row['attrs'].get('name') == 'TrainingLessons[id_training]']
    if parent and parent != [str(course_id)]: raise Review('source_identity_mismatch')
    if form.attrs.get('action'): _url(form.attrs['action'], LESSON, lesson_id)
    elif not own: raise Review('lesson_identity_unconfirmed')
    scripts = [s.text() for s in root.nodes('script') if not s.attrs.get('src')]
    # A malformed second initializer must never be silently ignored just
    # because one of its neighbours happens to match a recognized grammar.
    calls = [m for script in scripts for m in _APE_CALL.finditer(script)]
    _one(calls, 'ape_payload_missing_or_ambiguous')
    matches = [m for script in scripts for m in _APE.findall(script)]
    editor_options = None
    if matches:
        _, version, packed, token = _one(matches, 'ape_payload_missing_or_ambiguous')
    else:
        extended = [m for script in scripts for m in _APE_CONDITIONS.findall(script)]
        _, version, packed, token, condition_type = _one(extended, 'ape_payload_missing_or_ambiguous')
        if int(condition_type) > 2**31 - 1: raise Review('ape_payload_unrecognized')
        editor_options = {'visibleConditionsTypes': {'purchaseGoods': int(condition_type)}}
    try:
        decoded = _packed.decode_ape_payload({'formatVersion': int(version), 'packed': packed == 'true',
                                              'block': _packed.unquote_js_string(token)})['json']
    except _packed.PackedError: raise Review('ape_payload_unrecognized') from None
    _json_shape(decoded)
    def validate(node):
        if not isinstance(node, dict) or not isinstance(node.get('name'), str) or not node['name']: raise Review('ape_node_unrecognized')
        if 'fields' in node and not isinstance(node['fields'], dict): raise Review('ape_node_unrecognized')
        if 'children' in node:
            if not isinstance(node['children'], list): raise Review('ape_node_unrecognized')
            for child in node['children']: validate(child)
    if not isinstance(decoded, dict) or decoded.get('name') != 'page': raise Review('ape_root_unrecognized')
    # AVO may omit the optional children member on a genuine page leaf. Add
    # only an empty list, preserving every original field/style; the private
    # capture still contains the exact packed source. An explicit null or
    # unknown material is never rewritten into an empty page.
    children_defaulted = 'children' not in decoded
    if children_defaulted: decoded['children'] = []
    if not isinstance(decoded['children'], list): raise Review('ape_root_unrecognized')
    validate(decoded)
    result = {'payload': {'account': ACCOUNT, 'source_origin': ORIGIN, 'course_id': course_id,
            'lesson_id': lesson_id, 'course_title': course_title, 'lesson_title': lesson_title,
            'format': 'ape', 'ape': decoded}, 'settings': settings}
    if children_defaulted: result['ape_root_children_defaulted'] = True
    if editor_options is not None: result['editor_options'] = editor_options
    return result
