"""Replace two reviewed club iframes with verified public links, without I/O.

The owner excluded legacy subscription payment actions only. Other intro text,
its literal personalization placeholder, and the support link remain intact.
The caller retains the complete private source and replays these witnesses.
"""
import copy
import hashlib
import json
from html import escape
from urllib.parse import urlsplit, urlunsplit

from importer import ACCOUNT, ORIGIN, Review
from normalize_legacy_html_decorations import _has_content_style
from normalize_reviewed_getcourse import _clean as clean_reviewed_html
from normalize_reviewed_intro_lesson import _Document as SourceDocument, _number

CODE = 'reviewed_club_legacy_payment_replaced_with_links'
IDENTITY = (619, 6883)
SOURCE_APE_SHA256 = '1d1943c0c7bc7a2d948d5b18ac013c21eb409e627c6b29c5a8f354323243c1bc'
RESULT_APE_SHA256 = '5a7311a52edcc7624afd7dc5f7e3a436aba7bdb0342168fccd22b9f63b9867dd'
SOURCE_HOST = 'profit-club.mvacademy.ru'
CANONICAL_HOST = 'mvacademy.ru'
NODE_SHA256 = {
    0: '8c253caa5afe9e355dda7767762fe39197cae90faef679ddedcdd0cfb3c5e98d',
    1: 'ecfc8082586de1899aa35a3bd0cc5a7fb4dc59f361833132f38272b312ed50c6',
    2: '5282da7b470a4fcfc7510bad8249e677cf8f0c3b1ec486cf8f8668abd4d381ea',
    3: '96c5b457af42ba34c1b543ecc7e6854f64e056ebca697c0393d4f0978242faae',
    4: '3e8c7fcbb10ba533f6ed9374a31bd9b5e923525ce3466845d0f158cb55bd921b',
    5: 'bd8a2fd733298c648b806bf3d92abef8b4873834235c0e4e81a427126384ab91',
    6: 'e3b32748af8f311c655a7fea9c4f4b694cf40c1cfe504ce5c96b95af4b0b8e5b',
    7: '01eb43cb46dee32095195efc451ef28f10b2e5d255e0bdbb27eed0b8115df14b',
    8: '1b73e22204993cd591aecf65ef87e8b3bc3abd22a9f3b8b1dbe804615de7c479',
    9: 'fd8340322d2eb030059bab20c848b94fdee30418dec670b9552f3d20366d8921',
}
PAYMENT_FRAGMENTS = (
    (3, '84fb5ee829776cef7ed1ee82da7dfba7f5f36cafb45faf3571ea68b6dab4aabe'),
    (5, '99f8e18d2e21aa969322de5db2625947ade09ce019fa2153bd6bdf24e7a4ed42'),
    (11, '065e515950b9c3e97195faa080ffd65784b286b9211ab0ecf3ab81deb24839d3'),
)
FRAMES = {
    8: {'path': '/', 'label': 'Клуб «Профит»',
        'source_url_sha256': 'e6feabef1d6dff7293673d471ce2702fbdaa347ec4865af7fddfd84619be45f3',
        'canonical_url_sha256': '0186b67f25f75f5b113f5892083258cde7f7243eb21ff40e03193a6b8f946801',
        'iframe_sha256': 'd01ded75f1e6ec9b28c471d241e17872deb3f4db543fd6221323fe553d8a0290'},
    9: {'path': '/schedule/', 'label': 'Расписание клуба «Профит»',
        'source_url_sha256': 'f728d6bed5bb4f4f4fb680ea0ac626cf9b7a29f4050aec7f0725a9e09ba5628c',
        'canonical_url_sha256': '824b53aadca43df8329c0e88fb7043160750cb4051aaab0050527a7890ea1569',
        'iframe_sha256': '17a06051ca923996f77022051c70b88bc2ede2676c1ba44363646c1aa26c6da6'},
}


def _review(code='reviewed_club_requires_review'):
    raise Review(code)


def _sha(value):
    try:
        return hashlib.sha256(value.encode('utf-8')).hexdigest()
    except (AttributeError, UnicodeError):
        _review('reviewed_club_source_invalid')


def _digest(value):
    try:
        return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        _review('reviewed_club_source_invalid')


def _Document(source):
    try:
        return SourceDocument(source)
    except Review as error:
        _review('reviewed_club_source_invalid' if str(error).endswith('source_invalid')
                else 'reviewed_club_requires_review')


def _receipt(index, action, **values):
    return {'path': [index], 'code': CODE, 'action': action, **values}


def _remove_payment_paragraphs(source):
    document = _Document(source)
    ranges, changes = [], []
    for ordinal, expected in PAYMENT_FRAGMENTS:
        if not 0 <= ordinal < len(document.nodes):
            _review('reviewed_club_source_changed')
        node = document.nodes[ordinal]
        if node['tag'] != 'p' or _sha(source[node['start']:node['end']]) != expected:
            _review('reviewed_club_source_changed')
        ranges.append((node['start'], node['end']))
        changes.append(_receipt(0, 'payment_paragraph_omitted',
                                html_start_tag_ordinal=ordinal, fragment_sha256=expected,
                                reason='owner_excluded_old_subscription_payment'))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        _review('reviewed_club_source_invalid')
    result = source
    for start, end in reversed(ranges):
        result = result[:start] + result[end:]
    return result, changes


def _verified_link(source, binding):
    document = _Document(source)
    if len(document.nodes) != 2:
        _review('reviewed_club_source_changed')
    wrapper, frame = document.nodes
    if (wrapper['tag'] != 'p' or wrapper['attrs'] or frame['tag'] != 'iframe'
            or set(frame['attrs']) - {'src', 'style', 'width', 'height', 'frameborder', 'allowfullscreen'}
            or source[:wrapper['start']].strip() or source[wrapper['end']:].strip()
            or source[wrapper['opening_end']:frame['start']].strip()
            or source[frame['opening_end']:frame['closing_start']].strip()
            or source[frame['end']:wrapper['closing_start']].strip()
            or _sha(source[frame['start']:frame['end']]) != binding['iframe_sha256']):
        _review('reviewed_club_source_changed')
    url = frame['attrs'].get('src')
    if not isinstance(url, str) or _sha(url) != binding['source_url_sha256']:
        _review('reviewed_club_source_changed')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != SOURCE_HOST or parsed.port is not None
                or parsed.username is not None or parsed.password is not None
                or parsed.path != binding['path'] or binding['path'] not in {'/', '/schedule/'}
                or parsed.query or parsed.fragment or '\\' in url or any(ord(c) < 33 for c in url)):
            _review('reviewed_club_source_changed')
        canonical = urlunsplit(('https', CANONICAL_HOST, parsed.path, '', ''))
    except ValueError:
        _review('reviewed_club_source_invalid')
    if _sha(canonical) != binding['canonical_url_sha256']:
        _review('reviewed_club_source_changed')
    html = ('<p><a href="' + escape(canonical, quote=True)
            + '" target="_blank" rel="noopener noreferrer">'
            + escape(binding['label']) + '</a></p>')
    return html


def normalize_reviewed_club_links(ape, course_id, lesson_id, validate_static):
    """Return a source-bound copy; raw preservation/replay belongs to the caller."""
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_club_account_mismatch')
    context = (_number(course_id), _number(lesson_id))
    if (None in context or not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list) or not callable(validate_static)):
        _review('reviewed_club_source_invalid')
    if context != IDENTITY:
        return copy.deepcopy(ape), []
    if _digest(ape) != SOURCE_APE_SHA256 or len(ape['children']) != 10:
        _review('reviewed_club_source_changed')
    if any(_digest(node) != NODE_SHA256.get(i) for i, node in enumerate(ape['children'])):
        _review('reviewed_club_source_changed')
    copied, changes, retained = copy.deepcopy(ape), [], []
    for i, node in enumerate(copied['children']):
        if 1 <= i <= 6:
            changes.append(_receipt(i, 'payment_button_omitted', source_node_sha256=NODE_SHA256[i],
                                    reason='owner_excluded_old_subscription_payment'))
            continue
        fields = node.get('fields')
        if (node.get('name') != 'text' or not isinstance(fields, dict) or node.get('children', [])
                or set(node) - {'id', 'name', 'fields', 'style', 'children'}
                or set(fields) - {'anchor', 'html', 'displayDelay', 'visibleConditions'}
                or fields.get('anchor') not in (None, '')
                or any(fields.get(key) not in (None, '') for key in ('displayDelay', 'visibleConditions'))
                or _has_content_style(node.get('style')) or not isinstance(fields.get('html'), str)):
            _review()
        source = fields['html']
        if i in FRAMES:
            prepared = _verified_link(source, FRAMES[i])
            try:
                validate_static(prepared)
            except (ValueError, UnicodeError, RecursionError):
                _review()
            changes.append(_receipt(i, 'iframe_replaced_by_verified_public_link',
                source_html_sha256=_sha(source), result_html_sha256=_sha(prepared),
                source_url_sha256=FRAMES[i]['source_url_sha256'],
                canonical_url_sha256=FRAMES[i]['canonical_url_sha256'],
                iframe_sha256=FRAMES[i]['iframe_sha256'], legacy_iframe_layout_replaced=True))
        else:
            rewritten, omissions = _remove_payment_paragraphs(source) if i == 0 else (source, [])
            changes.extend(omissions)
            prepared, stats, images = clean_reviewed_html(rewritten, validate_static)
            if prepared != source:
                changes.append(_receipt(i, 'html_normalized', source_html_sha256=_sha(source),
                    result_html_sha256=_sha(prepared), presentation=stats, images=images))
        fields['html'] = prepared
        retained.append(node)
    copied['children'] = retained
    result_sha = _digest(copied)
    if result_sha != RESULT_APE_SHA256:
        _review('reviewed_club_material_mismatch')
    changes.insert(0, {'path': [], 'code': CODE, 'action': 'exact_source_bound',
        'source_ape_sha256': SOURCE_APE_SHA256, 'result_ape_sha256': result_sha,
        'nonpayment_intro_and_support_preserved': True, 'literal_greeting_placeholder_preserved': True})
    return copied, changes
