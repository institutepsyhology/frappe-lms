"""Preserve one reviewed lesson using the owner's explicit ASCII digit mapping.

The three original image names are not canonical UTF-8 encodings. No glyph is
inferred from a filename: only the exact reviewed image/tag hashes map to the
owner-approved text. Original APE and this receipt belong in caller snapshots.
"""
import copy
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_legacy_html_decorations import _has_content_style
from normalize_missing_course_images import _merged
from normalize_reviewed_getcourse import _clean as clean_getcourse
from normalize_reviewed_legacy_players import _mixed
from normalize_static_presentation import _material

CODE = 'owner_keycap_images_replaced_with_digits'
BINDINGS = {(130, 369): {
    'ape_sha256': 'd175bce70d90104d373128de90b299bd0bd48e4abaa25e9a963b0e8c088f1a90',
    'node_sha256': 'edd660652a4ab81040d85f30abed125292bddfd762a32634006dd516f2b45040',
    'html_sha256': 'fa2b9e1e7418e8991f76baff894258c3b4b49f4192dee7aeb43da04488779e12',
    'style_sha256': '4d9addf564245b7b1dff50df2879e35ddb80726e04f34c57f74c4af2168cf88d',
    'markers': [
        {'src_sha256': 'd45f6fda79252bfc179679adf07116325e3dd2c7476a40e4df380db3d72e35cf',
         'tag_sha256': 'f391ad0ed1fdd3bd37709f9e121a192b3780250bd71967a615f5be97b8cd8d5a', 'text': '1'},
        {'src_sha256': '3eee657bf0a7bea41ad838069e57c2dd68a4fa643897a23f408437eb9bccfb07',
         'tag_sha256': 'e25c14c36b307718f7a87372ac512098d3844cf3f11bfc1dd687a673cc7acf6c', 'text': '2'},
        {'src_sha256': 'ae9389d826a07f6a1c82d5320314458dbba2daa06b09129e1140c0e1c4fbd869',
         'tag_sha256': '9e76b7c883c27be03d233a472084e2ad8a176879296d943338c42669a9085761', 'text': '3'},
    ],
}}
NODE_KEYS = {'id', 'name', 'fields', 'children', 'style'}
IMAGE_STYLE = 'box-sizing: border-box; border: 0px; vertical-align: middle;'


def _review(code='reviewed_keycap_requires_review'):
    raise Review(code)


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _digest(value):
    try:
        return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _review('reviewed_keycap_source_invalid')


def _number(value):
    if type(value) is int and 0 < value <= 2**31 - 1: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value) and int(value) <= 2**31 - 1: return int(value)


class _Repair(HTMLParser):
    def __init__(self, source, markers):
        super().__init__(convert_charrefs=False)
        self.source, self.markers = source, markers
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']
        self.edits, self.found, self.marks, self.visited = [], [], 0, 0
        self.feed(source); self.close()

    def position(self):
        line, column = self.getpos(); return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        self.visited += 1
        if self.visited > 50000 or len(dict(attrs)) != len(attrs): _review()
        if tag not in {'img', 'mark'}: return
        values, opening = dict(attrs), self.get_starttag_text()
        if tag == 'img':
            if (set(values) - {'src', 'style', 'alt'} or values.get('alt') not in (None, '')
                    or values.get('style') != IMAGE_STYLE or len(self.found) >= 3): _review()
            src = values.get('src')
            if not isinstance(src, str): _review()
            try:
                url = urlsplit(src)
                if (url.scheme != 'https' or url.hostname != 'vk.com' or url.username is not None
                        or url.password is not None or url.port is not None or url.query or url.fragment
                        or not re.fullmatch(r'/emoji/e/[123]e283a3\.png', url.path)): _review()
            except ValueError: _review()
            record = self.markers[len(self.found)]
            if (_sha(src) != record['src_sha256'] or _sha(opening) != record['tag_sha256']
                    or record['text'] != str(len(self.found) + 1)): _review()
            self.found.append(record)
            self.edits.append((self.position(), self.position() + len(opening), record['text']))
        else:
            if set(values) != {'style'} or not isinstance(values['style'], str): _review()
            kept, removed, seen = [], set(), set()
            for piece in values['style'].split(';'):
                if not piece.strip(): kept.append(piece); continue
                if ':' not in piece: _review()
                key, value = (part.strip() for part in piece.split(':', 1)); key = key.lower()
                if key in seen: _review()
                seen.add(key)
                if key in {'display', 'border-radius'}:
                    if value != {'display': 'inline-block', 'border-radius': '4px'}[key]: _review()
                    removed.add(key)
                else: kept.append(piece)
            if removed != {'display', 'border-radius'}: _review()
            replacement = '<mark style="' + escape(';'.join(kept), quote=True) + '">'
            self.edits.append((self.position(), self.position() + len(opening), replacement)); self.marks += 1

    def handle_startendtag(self, tag, attrs):
        if tag not in {'img', 'br', 'hr', 'col'}: _review()
        self.handle_starttag(tag, attrs)

    def rendered(self):
        if len(self.found) != 3 or self.marks != 1: _review()
        output = self.source
        for start, end, replacement in sorted(self.edits, reverse=True): output = output[:start] + replacement + output[end:]
        return output


def normalize_reviewed_keycap_lesson(ape, course_id, lesson_id, validate_static):
    """Return an immutable, source-bound repair; never access network or files."""
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_keycap_account_mismatch')
    context = (_number(course_id), _number(lesson_id))
    if (None in context or not callable(validate_static) or not isinstance(ape, dict)
            or ape.get('name') != 'page' or not isinstance(ape.get('children'), list)):
        _review('reviewed_keycap_source_invalid')
    result = copy.deepcopy(ape); binding = BINDINGS.get(context)
    if binding is None: return result, []
    if _digest(ape) != binding['ape_sha256'] or len(ape['children']) != 1:
        _review('reviewed_keycap_source_changed')
    node = result['children'][0]
    if not isinstance(node, dict) or _digest(node) != binding['node_sha256']:
        _review('reviewed_keycap_source_changed')
    fields, style = node.get('fields'), node.get('style')
    if (node.get('name') != 'text' or set(node) - NODE_KEYS or not isinstance(fields, dict)
            or set(fields) - {'html', 'anchor'} or fields.get('anchor') not in (None, '')
            or node.get('children', []) != [] or not isinstance(node.get('children', []), list)
            or not isinstance(style, dict) or _has_content_style(style)):
        _review('reviewed_keycap_source_invalid')
    if not isinstance(ape.get('fields', {}), dict): _review('reviewed_keycap_source_invalid')
    if any(ape.get('fields', {}).get(k) not in (None, '', False, [], {})
           for k in ('anchor', 'visibleConditions', 'displayDelay')):
        _review('reviewed_keycap_source_invalid')
    source = fields.get('html')
    if (not isinstance(source, str) or not 0 < len(source.encode()) <= 200000
            or _sha(source) != binding['html_sha256'] or _digest(style) != binding['style_sha256']):
        _review('reviewed_keycap_source_changed')
    repair = _Repair(source, binding['markers']); replaced = repair.rendered()
    mapping = {item['src_sha256']: item['text'] for item in binding['markers']}
    expected = [('text', mapping[_sha(event[2])]) if event[0] == 'src' and event[1] == 'img'
                and _sha(event[2]) in mapping else event for event in _material(source)]
    if _merged(expected) != _material(replaced): _review('reviewed_keycap_material_mismatch')
    prefix = re.fullmatch(r'(<iframe\b[^<>]*></iframe>)([\s\S]*)', replaced)
    if not prefix: _review()
    # The reviewed fragment starts directly with its player. Reuse the existing
    # strict mixed-player splitter after cleaning only the static text suffix.
    try: suffix, stats, image_count = clean_getcourse(prefix[2], validate_static)
    except Review: _review()
    if image_count or _material(prefix[2]) != _material(suffix): _review('reviewed_keycap_material_mismatch')
    fields['html'] = '<p>' + prefix[1] + '</p>' + suffix
    try: details = _mixed(node, 1, validate_static, context, (0,), binding['node_sha256'])
    except Review: _review()
    video_url = node['children'][0]['fields']['videoSrc']
    return result, [{'path': [0], 'code': CODE, 'source_ape_sha256': binding['ape_sha256'],
        'source_node_sha256': binding['node_sha256'], 'html_sha256': binding['html_sha256'],
        'style_sha256': binding['style_sha256'], 'marker_text': ['1', '2', '3'],
        'marker_source_sha256': [x['src_sha256'] for x in binding['markers']],
        'material_preserved_with_owner_digits': True, 'material_witness_sha256': _digest(_material(replaced)),
        'removed_mark_properties': ['display:inline-block', 'border-radius:4px'],
        'source_video_url_sha256': _sha(video_url), 'getcourse_presentation': stats,
        'result_ape_sha256': _digest(result), **details}]
