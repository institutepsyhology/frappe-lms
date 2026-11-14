"""Apply the owner's exact intro-lesson omissions, retaining the private source.

Only hashes, numeric source identities and paths are public. The caller must
retain the original APE and replay this witness before importing its result.
Other support descriptions, rules, certificates and reference links are kept.
"""
import copy
import hashlib
import json
import re
from html import unescape
from html.parser import HTMLParser

from importer import ACCOUNT, ORIGIN, Review
from normalize_legacy_html_decorations import _has_content_style
from normalize_reviewed_getcourse import _clean as clean_reviewed_html

CODE = 'reviewed_intro_owner_sections_normalized'
IDENTITY = (207, 1975)
SOURCE_APE_SHA256 = '169e0fd0b5e6e2911b16c81028785cc772928485bc1114ce3379076642ec216c'
RESULT_APE_SHA256 = '9dcffded3bec80b22d5284f10c179845cf86004e8dcd193de1301fc9192d9a09'
NODE_SHA256 = {
    0: '298a78f1540e58b15877a5fa65c2d21a83b944f812fa58a337bd27f41f569e6e',
    1: '46373dc634688ca8bf88ebdcd2147309df703f018a34d274bb401e27f2216df4',
    2: '8083ac85344702af3ddc3822fe9c2c1022ee62b52601556cc16bd71a8b3f0187',
    3: 'dff017dbb29daeb1894200e78d9be2571fa94aabb5d3025bc5110bcab52b660d',
    4: '204f8d9f8ce55d2dcf2ce6a2ee6237ef25037cf9a41d9625ca193b4db8866d71',
    5: 'b4d0d0e71a9de6e33c45c31f825cffb986c6522596399c36da5755bd7ce6a4b7',
    6: '93e9802dc8f841268fed82009a6c1f1be542df80184473eb8235d3724cbe7b8e',
    7: '1a985fc3c42b4c8c81401d0d30270de11c1d40f98a921659f9401700fc3d803b',
    8: '4d6d1cef7aac15f0a63a924738569a4b969369aeb35b7dfe6f5087da91c7fc74',
    9: 'a82b9f1990331e70fb35e42ed7860edfd6978923b535c3b2094babfcd5e87a42',
    10: '23853d0f997489d5aa3080c3a948a15ff57c4e7eee1b4198f2808e1a5f848d61',
    11: 'cffb72e5fb7c7cb7429a8e08b1adfbf2405caab6d3dd0440e7d4d14e53bd3920',
    12: '870be1e2a9b675121d7d6b66ba0ca68a393c4b884ffc9e5e8139ae39af42a1b5',
    13: 'c61b776b29344b5c3506c3f020ef43329a216d635b0e9572620b9e67d52c3c9c',
    14: '06db575b7f4d718389e7a4e1ce58a2a1f97caab5715dbecf3c22fe2079e9b716',
    15: 'fdf2e69e88ea6fdb0e08d2545c3b3470c4412e30b477cdc3ae3171da5de3b8e2',
}
OMIT_ROOTS = {0: 'internal_navigation', 1: 'internal_navigation',
              8: 'payment_action', 14: 'questionnaire', 15: 'questionnaire'}
ANCHORS = {
    2: (1, '83f700c20a660ed6c8fc5911aeeab5a965911657afac926508f159b0bdbf9851'),
    4: (1, '4162f11ccbe143686d88fad96b4f8e9838eab51d3f30bd084a74b442bb92ec9a'),
    6: (1, '2e622732b26359d3616220fdde446bb0db958b6180b5e16403906b668ba175f2'),
    12: (1, '0e0f24eefd1fe9c964a62ec84e07e6cf1113544448353ab9dfd21eee5a87e08c'),
}
PAYMENT_FRAGMENTS = (
    (92, 'li', '55b29b486f23684455d5f3c14844bef2d57d79cf4689f922cd4adf1b53636d0c', 'session_purchase'),
    (100, 'li', '3051056f6467b67a7d6f85a68ff9e50892db6eb8a1509c8bb4605a328cd5123c', 'session_purchase'),
    (108, 'li', 'fbbd7c01eef7d7789b6e10cd95a8b1845377ec676f2754614931f2d5b65acad0', 'session_purchase'),
    (122, 'p', '18d9e6489ef8ec00326053a56ed325b36f7ce6e5340bf523f5c91f69573351e2', 'payment_call_to_action'),
)
VOID = {'br', 'hr', 'img', 'col'}


def _review(code='reviewed_intro_requires_review'):
    raise Review(code)


def _sha(value):
    try:
        return hashlib.sha256(value.encode('utf-8')).hexdigest()
    except (AttributeError, UnicodeError):
        _review('reviewed_intro_source_invalid')


def _digest(value):
    try:
        return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        _review('reviewed_intro_source_invalid')


def _number(value):
    if type(value) is int and 0 < value <= 2**31 - 1:
        return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value) and int(value) <= 2**31 - 1:
        return int(value)


class _Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        if not isinstance(source, str) or not 0 < len(source.encode('utf-8')) <= 200000:
            _review('reviewed_intro_source_invalid')
        self.source = source
        self.lines = [0] + [i + 1 for i, char in enumerate(source) if char == '\n']
        self.stack, self.nodes = [], []
        self.feed(source)
        self.close()
        if self.stack:
            _review()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 50000 or len(self.stack) >= 100 or len(dict(attrs)) != len(attrs):
            _review()
        start = self.position()
        node = {'tag': tag, 'attrs': dict(attrs), 'start': start,
                'opening_end': start + len(self.get_starttag_text()), 'ordinal': len(self.nodes)}
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)
        else:
            node['end'] = node['opening_end']

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID:
            _review()
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1]['tag'] != tag:
            _review()
        node = self.stack.pop()
        node['closing_start'] = self.position()
        end = self.source.find('>', node['closing_start'])
        if end < 0:
            _review()
        node['end'] = end + 1

    def handle_comment(self, data):
        _review()

    handle_decl = handle_comment
    handle_pi = handle_comment
    unknown_decl = handle_comment


def _receipt(path, action, **values):
    return {'path': list(path), 'code': CODE, 'action': action, **values}


def _rewrite_html(source, root_index):
    document = _Document(source)
    ranges, changes = [], []
    if root_index == 7:
        for ordinal, tag, expected, reason in PAYMENT_FRAGMENTS:
            if not 0 <= ordinal < len(document.nodes):
                _review('reviewed_intro_source_changed')
            node = document.nodes[ordinal]
            fragment = source[node['start']:node['end']]
            if node['tag'] != tag or _sha(fragment) != expected:
                _review('reviewed_intro_source_changed')
            ranges.append((node['start'], node['end']))
            changes.append(_receipt([root_index], 'html_fragment_omitted', reason=reason,
                                    html_start_tag_ordinal=ordinal, fragment_sha256=expected))
    anchors = [node for node in document.nodes if node['tag'] == 'a' and 'name' in node['attrs']]
    selected = ANCHORS.get(root_index)
    if selected is None and anchors or selected is not None and len(anchors) != 1:
        _review('reviewed_intro_source_changed')
    for node in anchors:
        ordinal, expected = selected
        fragment = source[node['start']:node['end']]
        inner = source[node['opening_end']:node['closing_start']]
        if (node['ordinal'] != ordinal or set(node['attrs']) != {'name'}
                or _sha(fragment) != expected or '<' in inner or unescape(inner).strip()):
            _review('reviewed_intro_source_changed')
        # Keep inner whitespace exactly; only the authorized empty target goes.
        ranges.extend(((node['start'], node['opening_end']), (node['closing_start'], node['end'])))
        changes.append(_receipt([root_index], 'named_anchor_removed', fragment_sha256=expected))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        _review('reviewed_intro_source_invalid')
    result = source
    for start, end in reversed(ranges):
        result = result[:start] + result[end:]
    return result, changes


def normalize_reviewed_intro_lesson(ape, course_id, lesson_id, validate_static):
    """Return an immutable scoped result and URL-free owner-omission witnesses."""
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_intro_account_mismatch')
    context = (_number(course_id), _number(lesson_id))
    if (None in context or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list) or not callable(validate_static)):
        _review('reviewed_intro_source_invalid')
    if context != IDENTITY:
        return copy.deepcopy(ape), []
    if _digest(ape) != SOURCE_APE_SHA256 or len(ape['children']) != 16:
        _review('reviewed_intro_source_changed')
    if any(_digest(node) != NODE_SHA256.get(i) for i, node in enumerate(ape['children'])):
        _review('reviewed_intro_source_changed')
    copied, changes = copy.deepcopy(ape), []
    retained = []
    for i, node in enumerate(copied['children']):
        if i in OMIT_ROOTS:
            changes.append(_receipt([i], 'node_omitted', reason=OMIT_ROOTS[i], source_node_sha256=NODE_SHA256[i]))
            continue
        fields = node.get('fields')
        if (node.get('name') not in {'text', 'header', 'button'} or not isinstance(fields, dict)
                or node.get('children', []) != [] or _has_content_style(node.get('style'))
                or set(node) - {'id', 'name', 'fields', 'style', 'children'}
                or any(fields.get(key) not in (None, '') for key in ('visibleConditions', 'displayDelay'))):
            _review('reviewed_intro_requires_review')
        if 'anchor' in fields:
            value = fields.pop('anchor')
            if value is not None and not isinstance(value, str):
                _review('reviewed_intro_source_invalid')
            changes.append(_receipt([i], 'fields_anchor_removed', source_value_sha256=_digest(value)))
        if node['name'] in {'text', 'header'}:
            if set(fields) - ({'html', 'format'} if node['name'] == 'header' else {'html'}):
                _review()
            source = fields.get('html')
            rewritten, html_changes = _rewrite_html(source, i)
            cleaned, stats, images = clean_reviewed_html(rewritten, validate_static)
            changes.extend(html_changes)
            if source != cleaned:
                changes.append(_receipt([i], 'html_normalized', source_html_sha256=_sha(source),
                                        result_html_sha256=_sha(cleaned), images=images, presentation=stats))
            fields['html'] = cleaned
        # A surviving reference button is deliberately copied, including its
        # URL, label, style and event fields, for the existing strict converter.
        retained.append(node)
    copied['children'] = retained
    result_sha = _digest(copied)
    if result_sha != RESULT_APE_SHA256:
        _review('reviewed_intro_material_mismatch')
    changes.insert(0, _receipt([], 'exact_source_bound', source_ape_sha256=SOURCE_APE_SHA256,
                              result_ape_sha256=result_sha, other_support_description_preserved=True))
    return copied, changes
