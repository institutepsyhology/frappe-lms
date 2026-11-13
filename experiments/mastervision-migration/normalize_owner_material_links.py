"""Remove four exact owner-approved obsolete Vimeo anchors and their labels."""
import copy
import hashlib
from html.parser import HTMLParser
from urllib.parse import urlsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_static_presentation import _content_style

CODE = 'owner_material_link_omitted'
FIRST = {'path': (2,), 'html_sha256': '6823dce415f4ee614c396161aa362fb4d915b865bbbf2d6d58a413b36a6cfd40',
         'url_sha256': 'a451f7b9d6d779b31d3fc05b056eefaae0442401994791c77a7a892bdc31d5a7',
         'outer_sha256': '0831f583adacf46b6615159e0ebe97cc6a88b1574e44216fca091295ff0e3684'}
SECOND = {'path': (2,), 'html_sha256': '798754fc49267c19df7e110bb08da702cb624d9e45b58671a5c5c887bea92ad3',
          'url_sha256': '0d82019b28859551d52822bde482411a2ee13ea1463ef06c86cd67f51fcc6799',
          'outer_sha256': '6b009d1413b67a9984c179cd6a4fb3fdc524b545873591ee4111a20aee80da18'}
APPROVED = {(326, 2636): FIRST, (329, 2729): FIRST, (374, 3162): SECOND, (376, 3165): SECOND}
NODE_KEYS = {'id', 'name', 'fields', 'children', 'style'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
INLINE = {'strong', 'b', 'em', 'i', 'u', 's', 'span', 'br', 'sub', 'sup', 'mark'}
PARENTS = INLINE | {'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote'}


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest() if isinstance(value, str) else None


def _protected(node):
    fields = node.get('fields', {})
    return (bool(set(node) - NODE_KEYS) or fields.get('anchor') not in (None, '')
            or any(fields.get(key) is not None for key in ('visibleConditions', 'displayDelay')))


def _vimeo(value):
    if not isinstance(value, str): return False
    try:
        url = urlsplit(value)
        return url.scheme in {'http', 'https'} and url.hostname in {'vimeo.com', 'www.vimeo.com', 'player.vimeo.com'}
    except ValueError:
        return False


class _Material(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []

    def handle_data(self, data):
        if self.events and self.events[-1][0] == 'text': self.events[-1] = ('text', self.events[-1][1] + data)
        else: self.events.append(('text', data))
    def handle_starttag(self, tag, attrs): self.events.append(('start', tag, tuple(attrs)))
    def handle_endtag(self, tag): self.events.append(('end', tag))
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)


class _Target(_Material):
    """Expected material events are the source with only its approved anchor skipped."""
    def __init__(self, source, policy):
        super().__init__()
        self.source, self.policy = source, policy
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']
        self.stack, self.active, self.ranges, self.vimeo_count = [], None, [], 0

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'a' and _vimeo(values.get('href')): self.vimeo_count += 1
        if tag == 'a' and _sha(values.get('href')) == self.policy['url_sha256']:
            if (self.active is not None or self.ranges or len(values) != len(attrs)
                    or set(values) != {'href', 'target'} or not _vimeo(values['href'])
                    or values['target'] not in {'_blank', '_self', '_parent', '_top'}
                    or any(protected for name, protected in self.stack)):
                raise ValueError('owner_material_anchor_changed')
            self.active = {'start': self.position(), 'depth': len(self.stack), 'label': []}
        elif self.active is not None:
            if tag not in INLINE or attrs: raise ValueError('owner_material_label_changed')
        else:
            super().handle_starttag(tag, attrs)
        if tag not in VOID:
            protected = (tag not in PARENTS or any(key.lower().startswith('on')
                or key.lower() in {'href', 'action', 'data-action', 'formaction'}
                or any(word in key.lower() for word in ('condition', 'permission', 'access', 'delay'))
                for key, value in attrs))
            self.stack.append((tag, protected))

    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack or self.stack[-1][0] != tag: raise ValueError('owner_material_markup_changed')
        if self.active is not None:
            if tag == 'a' and len(self.stack) == self.active['depth'] + 1:
                end = self.source.find('>', self.position())
                if end < 0 or not ''.join(self.active['label']).strip(): raise ValueError('owner_material_label_changed')
                start = self.active['start']
                if _sha(self.source[start:end + 1]) != self.policy['outer_sha256']:
                    raise ValueError('owner_material_anchor_changed')
                self.ranges.append((start, end + 1)); self.active = None
        else:
            super().handle_endtag(tag)
        self.stack.pop()

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: raise ValueError('owner_material_markup_changed')
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.active is not None: self.active['label'].append(data)
        else: super().handle_data(data)

    def _nontext(self):
        if self.active is not None: raise ValueError('owner_material_label_changed')
    def handle_comment(self, data): self._nontext()
    def handle_decl(self, decl): self._nontext()
    def handle_pi(self, data): self._nontext()
    def unknown_decl(self, data): self._nontext()


def _remove_outer(source, start, end): return source[:start] + source[end:]


def _clean(source, policy):
    try:
        if not isinstance(source, str) or len(source.encode('utf-8')) > 200000 or _sha(source) != policy['html_sha256']:
            return None
        expected = _Target(source, policy)
        expected.feed(source); expected.close()
        if expected.stack or expected.active is not None or expected.vimeo_count != 1 or len(expected.ranges) != 1:
            return None
        start, end = expected.ranges[0]
        cleaned = _remove_outer(source, start, end)
        actual = _Material(); actual.feed(cleaned); actual.close()
    except (ValueError, UnicodeError, RecursionError):
        return None
    if actual.events != expected.events: raise Review('owner_material_signature_mismatch')
    return cleaned


def normalize_owner_material_links(ape, course_id, lesson_id):
    """Return a copy and a metadata-only witness; all unapproved material remains."""
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        raise Review('owner_material_account_mismatch')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('owner_material_source_invalid')
    copied = copy.deepcopy(ape)
    pending, visited = [(copied, 0)], 0
    while pending:
        node, depth = pending.pop(); visited += 1
        if (visited > 150000 or depth > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str)
                or not isinstance(node.get('fields', {}), dict) or not isinstance(node.get('children', []), list)):
            raise Review('owner_material_source_invalid')
        pending.extend((child, depth + 1) for child in node.get('children', []))
    policy = APPROVED.get((course_id, lesson_id)) if type(course_id) is int and type(lesson_id) is int else None
    if policy is None: return copied, []
    if policy.get('path') != (2,): return copied, []
    if _protected(copied) or len(copied['children']) <= 2: return copied, []
    node = copied['children'][2]; fields = node.get('fields', {})
    if (node['name'] != 'text' or node.get('children') or _protected(node)
            or set(fields) - {'anchor', 'html'} or _content_style(node.get('style'))):
        return copied, []
    cleaned = _clean(fields.get('html'), policy)
    if cleaned is None: return copied, []
    fields['html'] = cleaned
    return copied, [{'path': [2], 'code': CODE, 'html_sha256': policy['html_sha256'],
                     'url_sha256': policy['url_sha256'], 'outer_sha256': policy['outer_sha256']}]
