"""Remove only a redundant CKEditor link address, preserving lesson material."""
import copy
from html import escape
from html.parser import HTMLParser

from importer import Review
from normalize_static_presentation import _material

CODE = 'redundant_editor_link_metadata_normalized'
ATTRIBUTE = 'data-cke-saved-href'


def _signature(markup):
    events = _material(markup)
    return [(event[0], tuple((k, v) for k, v in event[1] if k != ATTRIBUTE))
            if event[0] == 'a_start' else event for event in events]


class _Links(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=False)
        self.markup = markup
        self.lines = [0] + [i + 1 for i, char in enumerate(markup) if char == '\n']
        self.changes = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a' or ATTRIBUTE not in dict(attrs): return
        fields = dict(attrs)
        if (len(fields) != len(attrs) or not fields.get('href')
                or fields.get(ATTRIBUTE) != fields['href']): return
        row, col = self.getpos(); start = self.lines[row - 1] + col
        raw = self.get_starttag_text()
        # Keep every other parsed attribute. The final static validator rejects
        # unsupported actions/URLs; the exact material signature is also checked.
        kept = [(key, value) for key, value in attrs if key != ATTRIBUTE]
        if any(value is None for key, value in kept): return
        replacement = '<a' + ''.join(' ' + key + '="' + escape(value, quote=True) + '"'
                                    for key, value in kept) + '>'
        self.changes.append((start, start + len(raw), replacement))


def normalize_redundant_link_metadata(ape, validate_static):
    if not callable(validate_static): raise Review('redundant_link_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page':
        raise Review('redundant_link_ape_invalid')
    result = copy.deepcopy(ape); changes = []; visited = 0

    def walk(node, path):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict):
            raise Review('redundant_link_ape_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list):
            raise Review('redundant_link_ape_invalid')
        markup = fields.get('html')
        if (node.get('name') in {'text', 'code', 'header', 'button'}
                and isinstance(markup, str) and ATTRIBUTE in markup and len(markup) <= 200000):
            try:
                parser = _Links(markup); parser.feed(markup); parser.close()
                cleaned = markup
                for start, end, replacement in reversed(parser.changes):
                    cleaned = cleaned[:start] + replacement + cleaned[end:]
                if parser.changes:
                    validate_static(cleaned)
                    if _signature(markup) != _signature(cleaned):
                        raise Review('redundant_link_material_mismatch')
                    fields['html'] = cleaned
                    changes.append({'path': list(path), 'code': CODE, 'links': len(parser.changes)})
            except (ValueError, UnicodeError, RecursionError):
                pass
        for index, child in enumerate(children): walk(child, path + [index])

    walk(result, [])
    return result, changes
