"""Remove proven empty legacy discussion shells, retaining all authored HTML.

Only structural schemas and verified CSS hashes are retained here, rather than
vendor markup or scripts. The caller preserves the complete original APE.
"""
import copy
import hashlib
from html.parser import HTMLParser
import re
from urllib.parse import unquote, urlsplit

from importer import Review

CODE = 'empty_discussion_widget_omitted'
ORDER = ('xdget-lessonAnswers', 'talks-widget', 'talks-widget-button')
CLASSES = {
    'xdget-lessonAnswers': (
        frozenset(('xdget-block', 'xdget-lessonAnswers', 'xdget-visible-to-bg-')),
        frozenset(('row', 'row-section')), frozenset(('col-md-12',)),
        frozenset(('other-answers', 'answers-list'))),
    'talks-widget': (frozenset(('talks-widget', 'activated-talks-widget')),),
    'talks-widget-button': (frozenset(('talks-widget-button',)),),
}
BASE = '6adbb09a0c61ebba0cec70089260a0eb6d8ded0ae6ab0688f6cef58ab9cec3e3'
STYLES = {
    'xdget-lessonAnswers': ({BASE},
        {'ffeb64e30841908f393be29b1bfd18b542248b220f320213bdd10225c564535c'},
        {'2b550bb0bc066b4ee3a0757012f6aa7ef61fb189b0e4549f0cb8d65ac3a0d82a',
         'e01e8fe3774454a02bddf302fd269ec335331075299219f854bc84b7a4de4602'}, {BASE}),
    'talks-widget': ({'89e1b441b967fa181b2e2939c887b9e385568b016010c22835e50bc1d6dd5dc0'},),
    'talks-widget-button': ({'10a5fd8c13228d51f0f8e131b379c6e5c51205d2fe81272af617d96d0666a75f'},),
}
# Every observed shell uses one nonbreaking-space layout placeholder.
EMPTY_SPACE = ' \t\r\n\f\v\u00a0'


class _Signature(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.images = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag == 'a': self.links.append(tuple(attrs))
        if tag == 'img': self.images.append(tuple(attrs))

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_data(self, data): self.text.append(data)
    def signature(self): return ''.join(self.text), tuple(self.links), tuple(self.images)


class _Widgets(_Signature):
    def __init__(self, source):
        super().__init__()
        self.source = source
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']
        self.active, self.ranges, self.ids = None, [], set()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def _element(self, tag, attrs, index):
        kind = self.active['kind']
        values = dict(attrs)
        if (tag != 'div' or len(values) != len(attrs) or index >= len(CLASSES[kind])
                or frozenset(values.get('class', '').split()) != CLASSES[kind][index]):
            raise ValueError('discussion_widget_unknown')
        allowed = {'class', 'style'}
        if index == 0 and kind == 'xdget-lessonAnswers':
            allowed |= {'id', 'data-xdget-id'}
            ident = values.get('data-xdget-id')
            if not isinstance(ident, str) or not re.fullmatch('[1-9][0-9]{0,9}', ident) or values.get('id') != 'xdget' + ident:
                raise ValueError('discussion_widget_unknown')
        elif kind == 'talks-widget':
            allowed.add('id')
            if not isinstance(values.get('id'), str) or not re.fullmatch('w[0-9]{1,10}', values['id']):
                raise ValueError('discussion_widget_unknown')
        if set(values) - allowed: raise ValueError('discussion_widget_unknown')
        style = values.get('style')
        if style not in (None, '') and hashlib.sha256(style.encode()).hexdigest() not in STYLES[kind][index]:
            raise ValueError('discussion_widget_unknown')
        if values.get('id'): self.ids.add(values['id'])

    def handle_starttag(self, tag, attrs):
        roots = set(dict(attrs).get('class', '').split()) & set(ORDER)
        if self.active is None:
            if not roots:
                super().handle_starttag(tag, attrs)
                return
            if len(roots) != 1 or len(self.ranges) >= len(ORDER) or next(iter(roots)) != ORDER[len(self.ranges)]:
                raise ValueError('discussion_widget_unknown')
            self.active = {'kind': next(iter(roots)), 'start': self.position(), 'depth': 0, 'nodes': 0}
        elif roots:
            raise ValueError('discussion_widget_unknown')
        # The observed answer shell is one four-div chain, never siblings.
        index = self.active['nodes']
        if self.active['depth'] != index: raise ValueError('discussion_widget_unknown')
        self._element(tag, attrs, index)
        self.active['depth'] += 1
        self.active['nodes'] += 1

    def handle_endtag(self, tag):
        if self.active is None: return
        if tag != 'div': raise ValueError('discussion_widget_unknown')
        self.active['depth'] -= 1
        if self.active['depth'] == 0:
            if self.active['nodes'] != len(CLASSES[self.active['kind']]):
                raise ValueError('discussion_widget_unknown')
            end = self.source.find('>', self.position())
            if end < 0: raise ValueError('discussion_widget_unknown')
            self.ranges.append((self.active['start'], end + 1))
            self.active = None

    def handle_startendtag(self, tag, attrs):
        if self.active is not None or set(dict(attrs).get('class', '').split()) & set(ORDER):
            raise ValueError('discussion_widget_unknown')
        super().handle_startendtag(tag, attrs)

    def handle_data(self, data):
        if self.active is not None:
            if data.strip(EMPTY_SPACE): raise ValueError('discussion_widget_not_empty')
        else: super().handle_data(data)

    def _nontext(self):
        if self.active is not None: raise ValueError('discussion_widget_unknown')

    def handle_comment(self, data): self._nontext()
    def handle_decl(self, decl): self._nontext()
    def handle_pi(self, data): self._nontext()
    def unknown_decl(self, data): self._nontext()


def _clean(source, validate):
    if not isinstance(source, str) or 'talks-widget' not in source:
        return None
    try:
        if len(source.encode('utf-8')) > 200000: return None
        before = _Widgets(source)
        before.feed(source)
        before.close()
        if before.active is not None or len(before.ranges) != 3: return None
        if any(isinstance(value, str) and unquote(urlsplit(value).fragment) in before.ids
               for attrs in before.links for key, value in attrs if key == 'href'): return None
        cleaned = source
        for start, end in reversed(before.ranges): cleaned = cleaned[:start] + cleaned[end:]
        validate(cleaned)
        after = _Signature()
        after.feed(cleaned)
        after.close()
        if before.signature() != after.signature(): return None
    except (ValueError, UnicodeError, RecursionError):
        return None
    return cleaned


def normalize_empty_discussion_widgets(ape, validate_static):
    """Remove only complete empty bundles; preserve every other source byte.

    Nonempty answers, material links, unknown settings and anchor targets remain
    untouched for review. No HTML, scripts or remote actions are executed.
    """
    if not callable(validate_static): raise Review('empty_discussion_widgets_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('empty_discussion_widgets_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0

    def walk(node, path):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
            raise Review('empty_discussion_widgets_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('empty_discussion_widgets_invalid')
        if (node['name'] == 'text' and not children and not set(fields) - {'html', 'anchor'}
                and fields.get('anchor') in (None, '')
                and not set(node) - {'id', 'name', 'fields', 'children', 'style'}):
            cleaned = _clean(fields.get('html'), validate_static)
            if cleaned is not None:
                fields['html'] = cleaned
                changes.append({'path': list(path), 'code': CODE, 'widgets': 3})
        for index, child in enumerate(children): walk(child, path + [index])

    walk(copied, [])
    return copied, changes
