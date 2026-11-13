"""Recognize inert legacy decorations without changing authored material."""
import copy
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import re

from importer import Review
from normalize_empty_discussion_widgets import EMPTY_SPACE, STYLES
from normalize_static_presentation import _content_style, _material, _visual_value, VISUAL_TEXT_STYLE

CODE = 'legacy_html_decoration_normalized'
KNOWN_BUTTON_STYLES = frozenset(STYLES['talks-widget-button'][0])
VOID = {'br', 'hr', 'col'}
INLINE = {'a', 'span', 'br'}
CANDIDATE = re.compile(r'talks-widget-button|display\s*:\s*inline\s*!\s*important', re.I)
STYLE = re.compile(r'''(?is)\s+style\s*=\s*(["'])(.*?)\1''')


def _review():
    raise Review('legacy_html_decoration_requires_review')


def _has_content_style(style):
    if not _content_style(style): return False
    lists = style.get('lists') if isinstance(style, dict) else None
    text = lists.get('text') if isinstance(lists, dict) else None
    # AVO stores font controls inside the CSS group named "text". Both
    # observed extra controls are typed visual values, not authored content.
    if (isinstance(text, dict) and not set(text) - VISUAL_TEXT_STYLE - {'color', 'fontSize'}
            and all(_visual_value(value) for value in text.values())):
        probe = copy.deepcopy(style); probe['lists'].pop('text')
        return _content_style(probe)
    return True


class _Decorations(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [i + 1 for i, c in enumerate(source) if c == '\n']
        self.stack, self.edits, self.widget_ranges, self.active = [], [], [], None
        self.widgets = self.displays = self.visited = 0
        self.feed(source); self.close()
        if self.stack or self.active is not None: _review()

    def pos(self):
        line, column = self.getpos(); return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        self.visited += 1
        if self.visited > 50000 or len(self.stack) > 100 or len(dict(attrs)) != len(attrs): _review()
        if self.active is not None: _review()  # An empty widget has no child elements.
        values = dict(attrs)
        if 'talks-widget-button' in values.get('class', '').split():
            css = values.get('style')
            if (tag != 'div' or set(values) - {'class', 'style'} or
                    values.get('class', '').split() != ['talks-widget-button'] or self.widgets or
                    css not in (None, '') and hashlib.sha256(css.encode()).hexdigest() not in KNOWN_BUTTON_STYLES):
                _review()
            self.active = self.pos()
        elif 'style' in values:
            self.inline_style(tag, values['style'])
        if tag not in VOID: self.stack.append(tag)

    def inline_style(self, tag, css):
        if not isinstance(css, str): _review()
        pieces, keep, removed = css.split(';'), [], 0
        for piece in pieces:
            if ':' in piece and piece.split(':', 1)[0].strip().lower() == 'display':
                value = piece.split(':', 1)[1].strip()
                if tag not in INLINE or not re.fullmatch(r'inline\s*!\s*important', value, re.I) or removed:
                    _review()
                removed += 1
            else: keep.append(piece)
        if not removed: return
        opening = self.get_starttag_text(); matches = list(STYLE.finditer(opening))
        if len(matches) != 1 or unescape(matches[0][2]) != css: _review()
        match = matches[0]; remaining = ';'.join(keep)
        replacement = ' style="' + escape(remaining, quote=True) + '"' if remaining.strip() else ''
        self.edits.append((self.pos() + match.start(), self.pos() + match.end(), replacement))
        self.displays += removed

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack or self.stack.pop() != tag: _review()
        if self.active is not None:
            if tag != 'div': _review()
            ending = re.match(r'</\s*div\s*>', self.source[self.pos():], re.I)
            if ending is None: _review()
            self.edits.append((self.active, self.pos() + len(ending[0]), ''))
            self.widget_ranges.append((self.active, self.pos() + len(ending[0])))
            self.active = None; self.widgets += 1

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: _review()
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.active is not None and data.strip(EMPTY_SPACE): _review()

    def handle_entityref(self, name): self.handle_data(unescape('&' + name + ';'))
    def handle_charref(self, name): self.handle_data(unescape('&#' + name + ';'))
    def handle_comment(self, data): _review()
    def handle_decl(self, data): _review()
    def handle_pi(self, data): _review()
    def unknown_decl(self, data): _review()

    def rendered(self):
        result = self.source
        for start, end, replacement in sorted(self.edits, reverse=True):
            result = result[:start] + replacement + result[end:]
        return result


def _clean(source, validate):
    if not isinstance(source, str) or not CANDIDATE.search(source): return None
    try:
        validate(source)
        return None  # Keep already accepted HTML byte-for-byte unchanged.
    except (ValueError, UnicodeError, RecursionError): pass
    if len(source.encode('utf-8')) > 200000: _review()
    parser = _Decorations(source)
    if not parser.edits: return None
    cleaned = parser.rendered()
    # Remove only proven empty widgets from the reference signature. Style
    # changes cannot alter text, ordered URLs, media, anchors or list structure.
    material_source = source
    for start, end in sorted(parser.widget_ranges, reverse=True):
        material_source = material_source[:start] + material_source[end:]
    if _material(material_source) != _material(cleaned):
        raise Review('legacy_html_decoration_material_mismatch')
    try: validate(cleaned)
    except (ValueError, UnicodeError, RecursionError): _review()
    return cleaned, parser.widgets, parser.displays


def normalize_legacy_html_decorations(ape, validate_static):
    """Keep unsupported or protected content for explicit review, never execute it."""
    if not callable(validate_static): raise Review('legacy_html_decoration_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('legacy_html_decoration_ape_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0

    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict):
            raise Review('legacy_html_decoration_ape_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list):
            raise Review('legacy_html_decoration_ape_invalid')
        protected = protected or any(fields.get(k) not in (None, '', False, [], {}) for k in ('visibleConditions', 'displayDelay'))
        if (not protected and node.get('name') == 'text' and not children and
                not set(fields) - {'html', 'anchor'} and fields.get('anchor') in (None, '') and
                not set(node) - {'id', 'name', 'fields', 'children', 'style'} and not _has_content_style(node.get('style'))):
            value = _clean(fields.get('html'), validate_static)
            if value is not None:
                fields['html'], widgets, displays = value
                changes.append({'path': list(path), 'code': CODE, 'empty_widgets': widgets, 'inline_displays': displays})
        for index, child in enumerate(children): walk(child, path + [index], protected)

    walk(copied, [])
    return copied, changes
