"""Preserve static lesson material while normalizing observed presentation HTML."""
import copy
from html import escape, unescape
from html.parser import HTMLParser
import re

from importer import Review
from normalize_editor_nodes import _style_content

CODE = 'static_presentation_normalized'
VOID = {'br', 'hr', 'col', 'img', 'input', 'meta', 'link', 'source', 'embed', 'wbr'}
STRUCTURE = {'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'col', 'colgroup',
             'ul', 'ol', 'li', 'dl', 'dt', 'dd'}
FORBIDDEN = {'script', 'style', 'form', 'input', 'select', 'textarea', 'object', 'embed',
             'svg', 'math', 'audio', 'video', 'img', 'meta', 'link', 'base'}
ELIGIBLE = {'text', 'code', 'header', 'button'}
PROTECTED = {'visibleConditions', 'displayDelay'}
BASE_FIELDS = {'html', 'anchor'} | PROTECTED
CANDIDATE = re.compile(r'<\s*(?:button|pre|hr)\b|\s(?:align|data-pm-slice)\s*=|tab-stops\s*:', re.I)
VISUAL_TEXT_STYLE = {
    '#__backgroundColor__after', '#__maskImage__after', '#__maskPosition__after',
    '#__maskRepeat__after', '#__maskSize__after', 'backgroundAttachment', 'backgroundColor',
    'backgroundImage', 'backgroundPosition', 'backgroundRepeat', 'backgroundSize',
    'borderBottomColor', 'borderBottomLeftRadius', 'borderBottomRightRadius', 'borderBottomWidth',
    'borderLeftColor', 'borderLeftWidth', 'borderRightColor', 'borderRightWidth', 'borderStyle',
    'borderTopColor', 'borderTopLeftRadius', 'borderTopRightRadius', 'borderTopWidth', 'boxShadow',
    'height', 'marginBottom', 'marginLeft', 'marginRight', 'marginTop', 'opacity',
    'paddingBottom', 'paddingLeft', 'paddingRight', 'paddingTop', 'textAlign', 'width',
}
CONTROL_SHAPES = tuple(map(frozenset, (
    {'value'}, {'a', 'b', 'enabled', 'g', 'r'}, {'url'}, {'type'}, {'type', 'units', 'width'},
    {'number', 'units'}, {'number', 'type', 'units'}, {'number'},
    {'blurRadius', 'colorAlpha', 'colorB', 'colorEnabled', 'colorG', 'colorR',
     'enabled', 'inset', 'offsetX', 'offsetY', 'spreadRadius'},
)))


def _review():
    raise Review('static_presentation_requires_review')


def _visual_value(value, depth=0):
    if depth > 12: return False
    if value is None or type(value) in (int, float, bool): return True
    if isinstance(value, str):
        return len(value) <= 2000 and not re.search(r'https?:|data:|url\s*\(|<|expression\s*\(|@|\\', value, re.I)
    return (isinstance(value, dict) and frozenset(value) in CONTROL_SHAPES
            and all(_visual_value(child, depth + 1) for child in value.values()))


def _content_style(style):
    # AVO calls this *visual CSS group* "text". Do not mistake that group name
    # for a lesson caption; its original metadata remains completely unchanged.
    lists = style.get('lists') if isinstance(style, dict) else None
    visual = lists.get('text') if isinstance(lists, dict) else None
    if (isinstance(visual, dict) and not set(visual) - VISUAL_TEXT_STYLE
            and all(_visual_value(value) for value in visual.values())
            and not _style_content(visual)
            and not any(isinstance(value, str) and re.search(r'expression\s*\(|@|\\', value, re.I)
                        for value in visual.values())):
        probe = copy.deepcopy(style); probe['lists'].pop('text')
        return _style_content(probe)
    return _style_content(style)


class _Material(HTMLParser):
    """Decoded text and ordered material events, independent of cosmetic tags."""
    def __init__(self): super().__init__(convert_charrefs=False); self.events = []
    def handle_data(self, data):
        if self.events and self.events[-1][0] == 'text':
            self.events[-1] = ('text', self.events[-1][1] + data)
        else: self.events.append(('text', data))
    def handle_entityref(self, name): self.handle_data(unescape('&' + name + ';'))
    def handle_charref(self, name): self.handle_data(unescape('&#' + name + ';'))
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'a':
            self.events.append(('a_start', tuple((key, value) for key, value in attrs
                                                 if key not in {'style', 'data-pm-slice', 'align'})))
        if 'src' in values: self.events.append(('src', tag, values['src']))
        if tag in STRUCTURE:
            semantic = tuple((k, v) for k, v in attrs if k in {'colspan', 'rowspan', 'span', 'start', 'type', 'value', 'reversed'})
            self.events.append(('structure_start', tag, semantic))
    def handle_endtag(self, tag):
        if tag == 'a': self.events.append(('a_end',))
        if tag in STRUCTURE and tag not in VOID: self.events.append(('structure_end', tag))
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID: self.handle_endtag(tag)


def _material(source):
    parser = _Material(); parser.feed(source); parser.close()
    return parser.events


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output, self.stack, self.count = [], [], 0
        self.changes = {'alignment': 0, 'hr_attributes': 0, 'clipboard': 0,
                        'tab_stops': 0, 'buttons': 0, 'pre': 0}

    def _style(self, value):
        if not isinstance(value, str): _review()
        pieces, removed = [], False
        for piece in value.split(';'):
            if not piece.strip(): continue
            if ':' not in piece: _review()
            name, content = (part.strip() for part in piece.split(':', 1))
            if name.lower() != 'tab-stops':
                pieces.append(piece); continue
            measure = r'(?:[0-9]{1,4}(?:\.[0-9]{1,4})?|\.[0-9]{1,4})(?:pt|px|in|cm|mm|pc)'
            if not re.fullmatch(r'(?:list\s+)?' + measure + r'(?:\s+' + measure + r')*', content, re.I):
                _review()
            self.changes['tab_stops'] += 1; removed = True
        return ';'.join(pieces) if removed else value

    def _align(self, values, alignment):
        if alignment not in {'left', 'right', 'center', 'justify', 'start', 'end'}: _review()
        style = values.get('style', '')
        if not isinstance(style, str): _review()
        existing = [piece.split(':', 1)[1].strip().lower() for piece in style.split(';')
                    if ':' in piece and piece.split(':', 1)[0].strip().lower() == 'text-align']
        if existing:
            if existing != [alignment]: _review()
        else:
            values['style'] = style + (';' if style and not style.rstrip().endswith(';') else '') + 'text-align:' + alignment
        self.changes['alignment'] += 1

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > 50000 or len(self.stack) > 100 or len(dict(attrs)) != len(attrs): _review()
        if tag in FORBIDDEN or any(key.startswith('on') for key, _ in attrs): _review()
        values, mapped = dict(attrs), tag
        if 'style' in values:
            style = self._style(values['style'])
            if style.strip(): values['style'] = style
            else: values.pop('style')
        if 'data-pm-slice' in values:
            match = re.fullmatch(r'([0-9]{1,3})\s+([0-9]{1,3})\s+\[\s*\]', values['data-pm-slice'] or '')
            if not match or any(int(value) > 128 for value in match.groups()): _review()
            values.pop('data-pm-slice'); self.changes['clipboard'] += 1
        if tag in {'div', 'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'} and 'align' in values:
            alignment = values.pop('align')
            if not isinstance(alignment, str): _review()
            self._align(values, alignment.strip().lower())
        if tag == 'hr':
            for key in ('align', 'width', 'size'):
                if key not in values: continue
                value = values[key]
                if key == 'align': valid = value in {'left', 'right', 'center'}
                elif key == 'size': valid = isinstance(value, str) and bool(re.fullmatch('[1-9][0-9]?', value))
                else:
                    match = re.fullmatch(r'([1-9][0-9]{0,3})(%)?', value or '')
                    valid = bool(match and int(match[1]) <= (100 if match[2] else 4096))
                if not valid: _review()
                values.pop(key); self.changes['hr_attributes'] += 1
        if tag == 'button':
            if attrs: _review()
            mapped = 'span'; self.changes['buttons'] += 1
        if tag == 'pre':
            if attrs: _review()
            mapped = 'div'; values = {'style': 'white-space:pre'}; self.changes['pre'] += 1
        attributes = ''.join(' ' + key + ('="' + escape(value, quote=True) + '"' if value is not None else '')
                             for key, value in values.items())
        self.output.append('<' + mapped + attributes + '>')
        if tag not in VOID: self.stack.append((tag, mapped))

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag: _review()
        _, mapped = self.stack.pop(); self.output.append('</' + mapped + '>')
    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: _review()
        self.handle_starttag(tag, attrs)
    def handle_data(self, data): self.output.append(escape(data, quote=False))
    def handle_entityref(self, name): self.output.append('&' + name + ';')
    def handle_charref(self, name): self.output.append('&#' + name + ';')
    def handle_comment(self, _): _review()
    def handle_decl(self, _): _review()
    def handle_pi(self, _): _review()
    unknown_decl = handle_decl
    def finish(self):
        self.close()
        if self.stack: _review()
        return ''.join(self.output)


def _clean(source, validate):
    if not CANDIDATE.search(source): return None
    try:
        validate(source)
    except (TypeError, ValueError, UnicodeError, RecursionError): pass
    else: return None  # Existing accepted bytes/fingerprints remain unchanged.
    try:
        if len(source.encode('utf-8')) > 200000: _review()
    except UnicodeError: _review()
    parser = _Cleaner(); parser.feed(source); cleaned = parser.finish()
    if not any(parser.changes.values()): return None
    try: validate(cleaned)
    except (TypeError, ValueError, UnicodeError, RecursionError): _review()
    if _material(source) != _material(cleaned):
        raise Review('static_presentation_material_mismatch')
    return cleaned, {key: value for key, value in parser.changes.items() if value}


def normalize_static_presentation(ape, validate_static):
    """Return a copy and metadata-only changes; the caller retains original APE."""
    if (not callable(validate_static) or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list)):
        raise Review('static_presentation_source_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0
    def walk(node, path, protected=False):
        nonlocal visited
        visited += 1
        if (visited > 150000 or len(path) > 100 or not isinstance(node, dict)
                or not isinstance(node.get('name'), str) or not isinstance(node.get('fields', {}), dict)
                or not isinstance(node.get('children', []), list)):
            raise Review('static_presentation_source_invalid')
        fields = node.get('fields', {})
        protected = (protected or fields.get('anchor') not in (None, '')
                     or any(fields.get(key) not in (None, '', False, [], {}) for key in PROTECTED)
                     or _content_style(node.get('style')))
        if not protected and node['name'] in ELIGIBLE and not node.get('children'):
            allowed = BASE_FIELDS | ({'format'} if node['name'] == 'header' else
                {'icon', 'linkType', 'url', 'blank', 'toAnchor', 'event'} if node['name'] == 'button' else set())
            meaningful_action = node['name'] == 'button' and any(fields.get(key) not in (None, '', False)
                                                                          for key in ('icon', 'toAnchor', 'event'))
            source = fields.get('html')
            if (not set(fields) - allowed and not set(node) - {'id', 'name', 'fields', 'children', 'style'}
                    and not meaningful_action and isinstance(source, str)):
                result = _clean(source, validate_static)
                if result:
                    fields['html'], statistics = result
                    changes.append({'path': list(path), 'code': CODE, 'presentation': statistics})
        for index, child in enumerate(node.get('children', [])): walk(child, path + (index,), protected)
    walk(copied, ())
    return copied, changes
