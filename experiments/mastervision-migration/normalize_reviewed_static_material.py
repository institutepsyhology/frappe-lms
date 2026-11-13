"""Bounded, reviewed Master Vision HTML repairs; no source text is embedded here."""
import copy
import hashlib
from html.parser import HTMLParser
import re

from importer import Review
from normalize_legacy_html_decorations import _has_content_style

CODE = 'reviewed_static_material_normalized'
FOOTER_CODE = 'table_footer_unwrapped'
# Exact original APE paths and full HTML hashes, verified from bound MV captures.
APPROVED = {
    (206, 1202): ((1,), '5c14da8c51c434fe675e3e3209c53f6a74e274832c9b8be9f7d3f4c36575bdbe'),
    (206, 1203): ((1,), 'ca5fcc35f3eb775127e8ec1cfb2e2a74bd0226ece8806666da2865b153c80991'),
    (206, 1204): ((1,), '82bef78221efdf17b79156fadfd5bfef1c4c40cd103aa7411ccdec63b755b77a'),
    (206, 1205): ((1,), '2b40a81e70e795974e5e3950dfc9e6da8b89878fea2bc222193e69f4bb544c67'),
    (206, 1206): ((1,), 'f2712dc4216731b3ca27647c0423a129bddfa87b8bf77710cb1bf81e72a0667b'),
    (206, 1207): ((1,), '390245501a5c9b6ac1a888db8e8df16bd2da987c453bfaec47c1e94355ea9777'),
    (206, 1208): ((1,), 'dc78c040715c97540735c1ad703adfd6561cbd9668bc508435a32edcb49f7232'),
    (206, 1209): ((1,), '8802ed3442b2bdd3a02744a9ece41908ea9075449f1503055a78e8325c7dfdf8'),
    (206, 1211): ((1,), 'e5fda764a1033e2530d47b60ceef4c8225abaa45337065bf1de3fd1ee94290d9'),
    (206, 1212): ((1,), '249dc48dc79ddf03023e3fd7bd99c477cc265219329264524908891b7f9d30f5'),
    (206, 1215): ((1,), '83cda6ef63ab504209bebd8e6af0ad884791f3b62d79afb7471e5bf442585f51'),
    (206, 1216): ((1,), '7ed0392014aa68a41bfe9e8e032ae9d1090f784bd987e01d6b04be29941ad39a'),
    (206, 1219): ((1,), '0332d1433494270996d9924b40924dc97aa6b7cbf151f89d5fe577f6f3a14dc1'),
    (206, 1222): ((1,), '534f8d2ceabff3df9bff20f3c75eb41947e33ab89f2db2e16b739ea0c31492ff'),
    (206, 1223): ((1,), '0cfea1e369c4e7552830bc15441fa7a122f5fbbd3c5ce822d55050a108125b2a'),
    (206, 1224): ((1,), '2f27d49ff1ff6a9736a679abd6499f6646e7137208b87092ee3b4de149fee510'),
    (206, 1688): ((1,), 'ee5070807941e50895355a704a5d0a1556c39b059089e3ff45a40e4a072afb20'),
    (206, 3101): ((2,), '025ffd57addf84a78ea85f91ed86f0bfaf0ad31b65acdb97e76a3e118a242f2e'),
    (259, 1568): ((0,), '07172274b0af090bafca394a0dca44cec8351d13148a2fd1c4d03cd05a059366'),
}
INERT_CLASSES = frozenset('standard-page-content lite-page block-set '
    'o-lt-lesson-comment-block lt-lesson-comment-block lesson-comment-block-1 '
    'answers-list other-answers talks-widget activated-talks-widget talks-widget-button '
    'grid-container ritz waffle freezebar-origin-ltr row-header column-headers-background '
    'row-headers-background row-header-wrapper s0 s1 s2 xl6329282 xl6429282 xl6529282 '
    'xl6629282 xl6729282 xl6829282 xl6929282'.split())
WIDGETS = frozenset('answers-list other-answers talks-widget activated-talks-widget talks-widget-button'.split())
PAGE_VISUAL_FIELDS = frozenset('backgroundOverlayColor commonFontFamily commonFontLink commonFontName '
                              'fontPair headingFontFamily headingFontLink headingFontName'.split())
VOID = {'br', 'hr', 'col'}


def _review(): raise Review('reviewed_static_material_requires_review')


class _Tree(HTMLParser):
    def __init__(self, source, allowed):
        super().__init__(convert_charrefs=False)
        self.source, self.allowed = source, allowed
        self.lines = [0] + [i + 1 for i, c in enumerate(source) if c == '\n']
        self.nodes, self.stack, self.count = [], [], 0
        self.feed(source); self.close()
        if self.stack: _review()

    def pos(self):
        line, column = self.getpos(); return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if (self.count > 50000 or len(self.stack) > 100 or tag not in self.allowed
                or len(dict(attrs)) != len(attrs) or any(k.startswith('on') for k, _ in attrs)):
            _review()
        start = self.pos()
        node = {'tag': tag, 'attrs': dict(attrs), 'start': start,
                'inner_start': start + len(self.get_starttag_text()), 'children': [], 'end': None}
        if self.stack: self.stack[-1]['children'].append(node)
        self.nodes.append(node)
        if tag in VOID: node['inner_end'] = node['end'] = node['inner_start']
        else: self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in VOID: return
        if not self.stack or self.stack[-1]['tag'] != tag: _review()
        node = self.stack.pop(); closing = re.match(r'</\s*' + tag + r'\s*>', self.source[self.pos():], re.I)
        if not closing: _review()
        node['inner_end'], node['end'] = self.pos(), self.pos() + len(closing[0])

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID: _review()
        self.handle_starttag(tag, attrs)

    def handle_comment(self, value): _review()
    handle_decl = handle_comment
    handle_pi = handle_comment
    unknown_decl = handle_comment


class _Signature(HTMLParser):
    """Ordered text, materials, list semantics and canonical table topology."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.events = [], []

    def handle_data(self, value): self.text.append(value)

    def handle_starttag(self, tag, attrs):
        if tag in {'p', 'div', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'ul', 'ol', 'li', 'br', 'hr'}:
            self.text.append(' ')  # Visible block/cell boundaries are separators.
        values = dict(attrs)
        if tag == 'a': self.events.append(('a', tuple((k, v) for k, v in attrs if k not in {'style', 'class'})))
        if 'src' in values: self.events.append(('media', tag, tuple(attrs)))
        if tag in {'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'colgroup', 'col', 'ul', 'ol', 'li'}:
            mapped = {'th': 'td', 'thead': 'tbody'}.get(tag, tag)
            semantic = tuple((k, v) for k, v in attrs if k in {'colspan', 'rowspan', 'span', 'start', 'type', 'value', 'reversed'})
            self.events.append(('start', mapped, semantic))
            markers = [p.split(':', 1)[1].strip().lower() for p in values.get('style', '').split(';')
                       if ':' in p and p.split(':', 1)[0].strip().lower() in {'list-style', 'list-style-type'}]
            if markers: self.events.append(('marker', markers[-1]))

    def handle_endtag(self, tag):
        if tag in {'p', 'div', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'ul', 'ol', 'li'}:
            self.text.append(' ')
        if tag == 'a': self.events.append(('end_a',))
        if tag in {'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'colgroup', 'ul', 'ol', 'li'}:
            self.events.append(('end', {'th': 'td', 'thead': 'tbody'}.get(tag, tag)))

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)


def _signature(source):
    parser = _Signature(); parser.feed(source); parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.text)).strip(), parser.events


def _footer(source, tree):
    tables = [n for n in tree.nodes if n['tag'] == 'table']
    rows = [n for n in tree.nodes if n['tag'] == 'tr']
    if len(tables) != 1 or len(rows) < 5: _review()
    table, footers = tables[0], rows[-4:]
    if any(n['attrs'].get('rowspan') for n in tree.nodes): _review()
    contents = []
    for row in footers:
        if not table['inner_start'] <= row['start'] < row['end'] <= table['inner_end']: _review()
        if [n['tag'] for n in row['children']] != ['th', 'td']: _review()
        empty, value = row['children']
        if set(value['attrs']) & {'rowspan'} or value['attrs'].get('colspan') != '2': _review()
        empty_html = source[empty['inner_start']:empty['inner_end']]
        if _signature(empty_html) != ('', []): _review()
        contents.append(source[value['inner_start']:value['inner_end']])
    spanned = [n for n in tree.nodes if 'colspan' in n['attrs']]
    if spanned != [n['children'][1] for n in footers]: _review()
    # Only the verified trailing whole-data-width rows move. No neighbouring
    # bytes or cell contents are chosen by a text match or URL heuristic.
    result = source[:table['end']] + ''.join('<div>' + html + '</div>' for html in contents) + source[table['end']:]
    for row in reversed(footers): result = result[:row['start']] + result[row['end']:]
    before, after = _signature(source), _signature(result)
    materials = lambda events: [event for event in events if event[0] in {'a', 'end_a', 'media', 'marker'}]
    if before[0] != after[0] or materials(before[1]) != materials(after[1]):
        raise Review('reviewed_static_material_mismatch')
    return result


def _clean(source, binding, validate):
    # Runtime import avoids an import cycle: normalize_source calls this helper
    # only after its existing reviewed table parser has been fully defined.
    from normalize_source import TablePresentation, presentation_css, table_content
    allowed = validate.__globals__['TAGS'] - {'style'} | {'thead', 'th', 'button', 'code'}
    tree = _Tree(source, allowed)
    for node in tree.nodes:
        attrs = node['attrs']
        css = attrs.get('style', '')
        if css:
            presentation_css(css)
            if re.search(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:|opacity\s*:\s*0(?:[.;\s]|$))', css, re.I): _review()
        if set(attrs.get('class', '').split()) & WIDGETS:
            if node['tag'] != 'div' or set(attrs) - {'class', 'style', 'id'}: _review()
            if 'id' in attrs and ('talks-widget' not in attrs.get('class', '').split()
                                  or not re.fullmatch(r'w[1-9][0-9]{0,11}', attrs['id'] or '')): _review()
            if _signature(source[node['inner_start']:node['inner_end']]) != ('', []): _review()
    rewritten = _footer(source, tree) if binding == (206, 1205) else source
    class Parser(TablePresentation):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if 'class' in values:
                tokens = values['class'].split()
                if set(tokens) - validate.__globals__['CLASSES'] - INERT_CLASSES: _review()
                kept = [v for v in tokens if v not in INERT_CLASSES]
                if kept: values['class'] = ' '.join(kept)
                else: values.pop('class')
            if 'x:publishsource' in values:
                if binding != (206, 1215) or tag != 'div' or values.pop('x:publishsource') != 'Excel': _review()
            if 'align' in values:
                if binding != (206, 1215) or tag != 'div' or values.pop('align') != 'center': _review()
            if values.get('width') == 'NaN':
                if binding != (206, 3101) or tag not in {'table', 'td'}: _review()
                values.pop('width')
            if tag == 'button':
                if binding != (206, 1688) or values != {'type': 'button'}: _review()
                tag, values = 'span', {}
            if tag == 'code':
                if binding != (259, 1568) or values: _review()
                tag, values = 'span', {'style': 'font-family:monospace'}
                # TablePresentation intentionally removes ordinary CSS, while
                # this explicit code-font substitution is preserved below.
                self.parts.append('<span style="font-family:monospace">'); self.stack.append('span'); return
            super().handle_starttag(tag, list(values.items()))

        def handle_endtag(self, tag):
            super().handle_endtag('span' if tag in {'button', 'code'} else tag)
    parser = Parser(rewritten); parser.feed(rewritten); parser.close()
    if parser.stack or parser.iframe is not None or parser.stylesheet is not None: _review()
    cleaned = ''.join(parser.parts)
    validate(cleaned)
    if (_signature(rewritten) != _signature(cleaned)
            or table_content(rewritten) != table_content(cleaned)):
        raise Review('reviewed_static_material_mismatch')
    return cleaned, parser.stats


def normalize_reviewed_static_material(ape, course_id, lesson_id, validate_static):
    """Repair only full-hash-bound reviewed fragments; retain the source upstream."""
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not callable(validate_static):
        raise Review('reviewed_static_source_invalid')
    copied = copy.deepcopy(ape)
    def number(value):
        if type(value) is int and value > 0: return value
        if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value): return int(value)
    binding = (number(course_id), number(lesson_id)); approved = APPROVED.get(binding)
    if approved is None: return copied, []
    path, expected = approved; node = copied
    for index in path:
        if (not isinstance(node, dict) or not isinstance(node.get('fields', {}), dict)
                or set(node.get('fields', {})) - PAGE_VISUAL_FIELDS - {'anchor', 'visibleConditions', 'displayDelay'}
                or node.get('fields', {}).get('anchor') not in (None, '')
                or any(node.get('fields', {}).get(k) is not None for k in ('visibleConditions', 'displayDelay'))
                or _has_content_style(node.get('style'))): return copied, []
        children = node.get('children', [])
        if not isinstance(children, list) or not 0 <= index < len(children): return copied, []
        node = children[index]
    if (not isinstance(node, dict) or node.get('name') != 'text' or node.get('children')
            or set(node) - {'id', 'name', 'fields', 'style', 'children'}
            or not isinstance(node.get('fields'), dict) or set(node['fields']) - {'html', 'anchor'}
            or node['fields'].get('anchor') not in (None, '') or _has_content_style(node.get('style'))): return copied, []
    html = node['fields'].get('html')
    if not isinstance(html, str): return copied, []
    try: encoded = html.encode('utf-8')
    except UnicodeError: raise Review('reviewed_static_source_invalid') from None
    if len(encoded) > 200000 or hashlib.sha256(encoded).hexdigest() != expected: return copied, []
    try: cleaned, stats = _clean(html, binding, validate_static)
    except (ValueError, UnicodeError, RecursionError): _review()
    node['fields']['html'] = cleaned
    changes = [{'path': list(path), 'code': CODE, **stats}]
    if binding == (206, 1205): changes.append({'path': list(path), 'code': FOOTER_CODE, 'rows': 4})
    return copied, changes
