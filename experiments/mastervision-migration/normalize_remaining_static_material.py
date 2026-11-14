"""Exact-capture MV table/heading repairs, preserving ordered lesson material."""
import copy
import hashlib
import json
import re

from importer import Review
from normalize_legacy_html_decorations import _has_content_style
from normalize_reviewed_static_material import (
    PAGE_VISUAL_FIELDS, _Tree, _signature as _previous_signature, _clean as _previous_clean,
)

TABLE_CODE = 'remaining_static_table_normalized'
HEADER_CODE = 'remaining_header_html_preserved'
KIND_CODE = 'remaining_code_html_preserved'
# Original APE paths and complete UTF-8 fragment SHA256, not text/URL heuristics.
# Each tuple: path, source hash, native kind, reviewed operation.
APPROVED = {
    (316, 2261): (((1,), '273fc66c4a6cd07cdba90bffb8fbaa9dc7f681476b753127c5e8797b13286e0f', 'text', 'table'),),
    (316, 2288): (((2,), 'ee5070807941e50895355a704a5d0a1556c39b059089e3ff45a40e4a072afb20', 'text', 'table'),),
    (316, 2902): (((2,), '025ffd57addf84a78ea85f91ed86f0bfaf0ad31b65acdb97e76a3e118a242f2e', 'text', 'table'),),
    (316, 5146): (((2,), 'efc95242014a2a30b9388e8e46b335501db5879178396cf7df9a842d7414cbc6', 'text', 'table'),),
    (316, 5249): (((2,), 'e15c37a0cd58e9ad515eda6dd85452e2cb742db789d1e5a3ed7c399a4f0b7fbe', 'text', 'table'),),
    (316, 5276): (((2,), 'f42a1c280953a0a71f5614853b5b7c5720583c20fcc60e18f8e9b4e179fa7b2d', 'text', 'table'),),
    (316, 5588): (((2,), '1e2d9938cfc4d83750d378a0f155e75ad2b9ea8f62c4a9b1872f9ba8b121236a', 'text', 'table'),),
    (538, 5603): (((4,), 'c2379580214b2cd30f8704f318e719e9aee0fb2710b56e641d3f01d22f4c7c24', 'text', 'table'),),
    (538, 5609): (((8,), '5b0e5fc87c9cfd50b9dc3982961131843c2c4a48844a7caac3deef9959a8c0f9', 'text', 'table'),),
    (538, 5608): (((10,), '28569832f2695c31ce26494b549abde7d7066185d05b45e4558cf2449570a107', 'text', 'table'),),
    (538, 5890): (((5,), '09e39978129e81f87ee2952bbe17dce73f776d019f43b17ae85992368995d0bb', 'text', 'table'),),
    (538, 5892): (((3,), 'f84907565e10d9d1f1d5778456780df27ac6790d76026f9835f3c19064f092d6', 'text', 'table'),),
    (656, 7789): (((6,), 'd823cd7b3f2126af23e42ae367a503d93294a761cc3963c6ab76b4ca31325080', 'text', 'table'),),
    (656, 7784): (((5,), '4ff22f99f9fb9036459e639a596fbf76b06ea391e249f4a57d16b49f301546a1', 'text', 'table'),),
    (383, 3767): (
        ((0, 1, 0), '213757f986faee4536c8272c3d2c424e260f165d2ea764d7e4e518aea0284ee7', 'header', 'header'),
        ((1,), '922ab72327808792fd9bd3d54f87211588f260987472f494426eb212c990a0a6', 'header', 'header'),
        ((3,), '6636eb017016fb737da44561f4c93a89ea4d5c3e5df66d683eefba8055208dca', 'header', 'header'),
        ((5,), 'ea25d05d17fce0d4546cde812a91dce0bba789ee52a6d4ba75fb9a6c36a945bc', 'header', 'header'),
        ((7,), '77d5411b22b3bd3110e1ca289ea228484104d73a4c6e7304a3d125fab6b08cb8', 'header', 'header')),
    (383, 3768): (
        ((0, 1, 0), 'c8451c03a7c16f768059fcc9f93754e4da641caacc1ecd1f02ff819abc0b3ce2', 'header', 'header'),
        ((1,), 'd26f93f3f7d5d85081ac1d67664638db7d71d75eed299c9ac15f667c22d4a169', 'header', 'header'),
        ((3,), '8dd75da331de8177a1282b266d086acc49c4bf6bab2aeefcc035678a076c9641', 'header', 'header'),
        ((5,), 'cafde345d33d351c43b3ad8a765d73d5424af2d23bd44acf59ba9b3dd6782bb0', 'header', 'header'),
        ((7,), 'f7d2529fa68e2fe630a08606b3ff0f76c9a6d2ea1e5f667b42e4fa73d8664a78', 'header', 'header')),
    (383, 3769): (
        ((0, 1, 0), 'a72d086f81f79bd1ad64d7528b0576f6d93760304a02c5f5e2fe90903dc8807c', 'header', 'header'),
        ((1,), 'ddb962fe4e99f6dc0329ad0d036ba637a6b270da55dd1c03a6839340134a3b9e', 'header', 'header'),
        ((3,), 'ba809b524d041de932a4cb13dc4c87b92d4b4b3c6e1ca696ade4e4c8e636379f', 'header', 'header'),
        ((5,), '9e56b4662647432e36c45061d2924b34f4fb7eaa2935a44934e0c416302748ef', 'header', 'header'),
        ((7,), '4aa592bd5c13d3e0acac7ba1b0bb792051f070ed82a243f86f22dd271186204f', 'header', 'header'),
        ((9,), '9cd075b3b3489cc34580fdbf1578fa3d13ca64a30823e7eeafdd4eca44b21c09', 'header', 'header')),
    (438, 4035): (((1,), '9e0e934030d3f1613f3717070603bdbfa83097ed40fb282aa85b7cb4e093c1fa', 'header', 'header'),),
    (573, 6137): (
        ((0,), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'header-simple', 'empty_header'),
        ((6,), '5d8dd9563bf5624e9d1f649ce8a7394b2678e38c4c556e626a5620d7990617bf', 'header-simple', 'simple_header')),
    (590, 6396): (((20,), '8393d54b0ea076664a3ca222abbe8179fc276e72743e8d4add4a95413b4550a4', 'code', 'code_as_text'),),
}
_ALIASES = {(316, 2288): (206, 1688), (316, 2902): (206, 3101)}
_MIDDLE = {(316, lid) for lid in (5146, 5249, 5276, 5588)}
_SCOPED = {(538, lid) for lid in (5603, 5609, 5890, 5892)}
_CLIPBOARD = '<style type="text/css"><!--td {border: 1px solid #ccc;}br {mso-data-placement:same-cell;}--></style>'


def _review(): raise Review('remaining_static_material_requires_review')


def _signature(source):
    # The shared safe validator already recognizes this exact clipboard CSS;
    # its declarations are not visible cell text. Unknown styles remain data.
    return _previous_signature(source.replace(_CLIPBOARD, ''))


def _style_runs(value):
    # Sheets serializes formatting-run offsets with U+EE10 as a separator.
    # These are typed visual controls; never accept authored text or expressions.
    if not isinstance(value, str) or len(value) > 2000: _review()
    for piece in value.split('\uee10'):
        try: run = json.loads(piece)
        except (ValueError, TypeError): _review()
        if (not isinstance(run, dict) or set(run) - {'1', '2'} or type(run.get('1')) is not int
                or not 0 <= run['1'] <= 200000): _review()
        if '2' in run:
            if (not isinstance(run['2'], dict) or set(run['2']) != {'5'}
                    or type(run['2']['5']) is not int or run['2']['5'] not in (0, 1)): _review()


def _clean(source, binding, validate):
    if binding in _ALIASES: return _previous_clean(source, _ALIASES[binding], validate)
    from normalize_source import TablePresentation, presentation_css, table_content
    rewritten = source
    if _CLIPBOARD in rewritten:
        if binding != (656, 7784) or rewritten.count(_CLIPBOARD) != 1: _review()
        rewritten = rewritten.replace(_CLIPBOARD, '', 1)
    tree = _Tree(rewritten, validate.__globals__['TAGS'] - {'style'} | {'thead', 'th'})
    for node in tree.nodes:
        css = node['attrs'].get('style', '')
        if css:
            presentation_css(css)
            if re.search(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:|opacity\s*:\s*0(?:[.;\s]|$))', css, re.I): _review()

    class Parser(TablePresentation):
        def handle_starttag(self, tag, attrs):
            values, preserved = dict(attrs), []
            spans = set(values) & {'rowspan', 'colspan'}
            if spans and (binding != (656, 7784) or tag != 'td'
                    or any(not isinstance(values[k], str) or not re.fullmatch(r'(?:[1-9]|1[0-6])', values[k]) for k in spans)): _review()
            if 'align' in values:
                if binding != (316, 2261) or tag != 'td' or values.pop('align') != 'right': _review()
                preserved.append('text-align:right')
            if 'valign' in values:
                if binding not in _MIDDLE or tag != 'td' or values.pop('valign') != 'middle': _review()
                preserved.append('vertical-align:middle')
            if 'scope' in values:
                if binding not in _SCOPED or tag != 'th' or values.pop('scope') != 'col': _review()
            if 'data-sheets-textstyleruns' in values:
                if binding != (656, 7789) or tag != 'td': _review()
                _style_runs(values.pop('data-sheets-textstyleruns'))
            # Keep list markers rather than losing them with other copied CSS.
            css = values.get('style', '')
            markers = [(k.strip().lower(), v.strip().lower()) for p in css.split(';')
                       if ':' in p for k, v in [p.split(':', 1)]
                       if k.strip().lower() in {'list-style', 'list-style-type'}]
            if markers and tag in {'ul', 'ol', 'li'}:
                if len(markers) != 1 or markers[0][0] != 'list-style-type' or markers[0][1] not in {'disc', 'decimal'}: _review()
                preserved.append('list-style-type:' + markers[0][1])
            before = len(self.parts)
            super().handle_starttag(tag, list(values.items()))
            if preserved:
                self.parts[before] = self.parts[before][:-1] + ' style="' + ';'.join(preserved) + '">'

    parser = Parser(rewritten); parser.feed(rewritten); parser.close()
    if parser.stack or parser.iframe is not None or parser.stylesheet is not None: _review()
    cleaned = ''.join(parser.parts)
    validate(cleaned)
    if _signature(source) != _signature(cleaned) or table_content(source) != table_content(cleaned):
        raise Review('remaining_static_material_mismatch')
    return cleaned, parser.stats


def _number(value):
    if type(value) is int and 0 < value < 2**31: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value) and int(value) < 2**31: return int(value)


def _node_at(ape, path):
    node = ape
    for index in path:
        fields = node.get('fields', {}) if isinstance(node, dict) else None
        if (not isinstance(fields, dict) or set(fields) - PAGE_VISUAL_FIELDS - {'anchor', 'visibleConditions', 'displayDelay'}
                or fields.get('anchor') not in (None, '') or _has_content_style(node.get('style'))
                or any(fields.get(k) is not None for k in ('visibleConditions', 'displayDelay'))): return None
        children = node.get('children', [])
        if not isinstance(children, list) or not 0 <= index < len(children): return None
        node = children[index]
    return node


def normalize_remaining_static_material(ape, course_id, lesson_id, validate_static):
    """Run before generic node removals; caller retains the exact original APE."""
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not callable(validate_static):
        raise Review('remaining_static_source_invalid')
    copied = copy.deepcopy(ape); changes = []
    binding = (_number(course_id), _number(lesson_id))
    for path, expected, kind, action in APPROVED.get(binding, ()):
        node = _node_at(copied, path)
        if (not isinstance(node, dict) or node.get('name') != kind or node.get('children')
                or set(node) - {'id', 'name', 'fields', 'style', 'children'} or _has_content_style(node.get('style'))): continue
        fields = node.get('fields')
        known = {'anchor', 'html'} | ({'format'} if kind == 'header' else {'level'} if kind == 'header-simple' else set())
        if not isinstance(fields, dict) or set(fields) - known or fields.get('anchor') not in (None, ''): continue
        markup = fields.get('html')
        if not isinstance(markup, str): continue
        try: raw = markup.encode('utf-8')
        except UnicodeError: raise Review('remaining_static_source_invalid') from None
        if len(raw) > 200000 or hashlib.sha256(raw).hexdigest() != expected: continue
        if kind == 'header' and fields.get('format') not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'): continue
        if kind == 'header-simple' and fields.get('level') not in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'): continue
        try:
            if action == 'table':
                cleaned, _ = _clean(markup, binding, validate_static)
                if _signature(markup) != _signature(cleaned): raise Review('remaining_static_material_mismatch')
                node['fields']['html'] = cleaned
            else:
                if action == 'empty_header':
                    if markup != '': _review()
                    cleaned = ''
                elif action == 'simple_header':
                    cleaned = '<' + fields['level'] + '>' + markup + '</' + fields['level'] + '>'
                    validate_static(cleaned)
                elif action == 'header':
                    validate_static(markup); cleaned = markup
                elif action == 'code_as_text':
                    validate_static(markup); cleaned = markup
                else: _review()
                if _signature(markup) != _signature(cleaned): raise Review('remaining_static_material_mismatch')
                node['name'] = 'text'
                if action != 'code_as_text': node['fields'] = {'anchor': fields.get('anchor', ''), 'html': cleaned}
        except (ValueError, UnicodeError, RecursionError): _review()
        changes.append({'path': list(path), 'code': TABLE_CODE if action == 'table' else KIND_CODE if action == 'code_as_text' else HEADER_CODE})
    return copied, changes
