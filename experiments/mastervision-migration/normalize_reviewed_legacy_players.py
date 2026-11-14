"""Exact reviewed legacy video layouts; original APE remains with the caller.

Only numeric identities, paths and SHA256 witnesses are public. Source HTML and
media URLs come exclusively from the private payload and are never fetched here.
This helper neither infers alternative videos nor drops neighbouring materials.
"""
import copy
import hashlib
import json
import re
import uuid

from importer import ACCOUNT, ORIGIN, Review
from normalize_legacy_html_decorations import _has_content_style

CODE = 'reviewed_legacy_player_preserved'
BINDINGS = {
    (21, 27): (((0,), '7fd8e26d43813955a700b79d662695248de68a8381bb13eee0b48740a07361c8', 'mixed_youtube', 1),),
    (231, 1452): (((0,), '85e2d9a083cca8ef307d627a0023ee0ddfcf0b7b149587401249bfe6415c5a2d', 'mixed_youtube', 1),),
    (231, 1453): (((0,), '42f4868c4218f3c55c94e125b0cf66f5f0bf9bfb4c81ca509fe09bc5b6667b5f', 'mixed_youtube', 2),),
    (231, 1455): (((0,), '2c3484c3e03b349efe62325773dc0243875f9034f80c7185b6afd4b8e717a5af', 'mixed_youtube', 1),),
    (515, 5066): (((0,), '4c2386cf74772b4b86ae5aa3f48c433299e5c05f45e5d3da4b819becbe7dbae5', 'youtube_attribute_tail', None),),
    (96, 169): (((0, 1, 1), '224b80f6aa88cd0a0bc26f20ef10ed6b049506abec162f3f4183ee1e2ba41775', 'vk', (0,)),),
    (188, 1041): (((2,), 'bc1d73c927625e734859fc55c1460cdea5677ebf5874ae6dc655a2d48a70016f', 'vk', None),),
    (201, 1178): (
        ((4, 1, 1), '8e80bcad2d66701478a4d820705ff4b96de88894b1edbd1ea5f450280d48c876', 'vk', (4,)),
        ((7, 1, 1), '6c9f8f9bd51b251ea5a8c08e073d0c11f9d8145ed53edbcefa8d61d2c2d61b0a', 'vk', (7,))),
    (201, 1179): (((1, 1, 1), '94f8e782f496e53a429970a29ee30c701f6ecaaec20a0fad6372b5bfecfdc578', 'vk', (1,)),),
    (201, 1182): (((0, 1, 1), 'c9c095dabb6af6d23d2291f58715db411c6d83b8bffc290b39dff8849a18cebc', 'vk', (0,)),),
}
NODE_KEYS = {'id', 'name', 'fields', 'children', 'style'}
VIDEO_FIELDS = {'anchor', 'html', 'embeddedHtml', 'isFloating', 'videoSrc', 'videoSrc2',
                'videoProvider', 'videoProvider2', 'nativePlayer', 'nativePlayer2',
                'posterSrc', 'posterSrc2', 'isShowFastRewindButtons',
                'isShowFastRewindButtons2', 'isShowProgressControl', 'isShowProgressControl2'}


def _review(code='reviewed_legacy_player_requires_review'):
    raise Review(code)


def _sha(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _review('reviewed_legacy_player_source_invalid')
    return hashlib.sha256(raw).hexdigest()


def _number(value):
    if type(value) is int and value > 0: return value
    if isinstance(value, str) and re.fullmatch('[1-9][0-9]{0,9}', value): return int(value)


def _node(root, path):
    current = root
    for index in path:
        if not isinstance(current, dict) or not isinstance(current.get('children'), list): return None
        if not 0 <= index < len(current['children']): return None
        current = current['children'][index]
    return current


def _leaf(node, kind, fields):
    return (isinstance(node, dict) and node.get('name') == kind
            and not set(node) - NODE_KEYS and node.get('children', []) == []
            and isinstance(node.get('children', []), list)
            and isinstance(node.get('fields'), dict) and not set(node['fields']) - fields
            and node['fields'].get('anchor') in (None, '') and not _has_content_style(node.get('style')))


def _mixed(node, count, validate_static, context, path, digest):
    if not _leaf(node, 'text', {'html', 'anchor'}): _review()
    source = node['fields'].get('html')
    if not isinstance(source, str): _review()
    prefix = re.fullmatch(r'<p>((?:<iframe\b[^<>]*></iframe>)+)</p>([\s\S]*)', source)
    if not prefix: _review()
    frames = re.findall(r'<iframe\b[^<>]*></iframe>', prefix[1])
    if len(frames) != count or ''.join(frames) != prefix[1]: _review()
    # Reuse the existing bounded pure iframe parser. It rejects duplicate attrs,
    # scripts, visible iframe fallback text, unknown features and unsafe URLs.
    from normalize_source import SingleFrame
    videos = []
    for frame in frames:
        parser = SingleFrame(); parser.feed(frame); parser.close()
        if parser.stack or not parser.video or parser.video[0] != 'youtube': _review()
        videos.append(parser.video[1])
    remainder = prefix[2]
    try: validate_static(remainder)
    except (ValueError, UnicodeError, RecursionError): _review()
    # The first paragraph contained only the iframe(s): all authored text,
    # anchors and formatting remain in the exact, unmodified suffix.
    children = []
    for index, url in enumerate(videos):
        ident = str(uuid.uuid5(uuid.NAMESPACE_URL, 'mastervision:%s:%s:%s:%s:%s' %
                              (context[0], context[1], path, digest, index)))
        children.append({'id': ident, 'name': 'video', 'fields': {'videoProvider': 'youtube', 'videoSrc': url}})
    children.append({'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'mastervision:' + digest + ':remainder')),
                     'name': 'text', 'fields': {'html': remainder}})
    node.update(name='section', fields={}, children=children)
    return {'kind': 'mixed_youtube', 'video_count': len(videos),
            'association': 'independent_sequential', 'remainder_sha256': hashlib.sha256(remainder.encode()).hexdigest()}


def _repair_tail(node):
    if not _leaf(node, 'video', VIDEO_FIELDS): _review()
    fields = node['fields']
    if (fields.get('videoProvider') != 'youtube' or fields.get('nativePlayer') is not False
            or fields.get('html') not in (None, '', 'Видео')
            or any(fields.get(k) not in (None, '') for k in
                   ('anchor', 'embeddedHtml', 'videoSrc2', 'posterSrc', 'posterSrc2'))): _review()
    value = fields.get('videoSrc')
    if not isinstance(value, str): _review()
    matched = re.fullmatch(r'(https://www\.youtube\.com/embed/([A-Za-z0-9_-]{11})\?rel=0&controls=1&showinfo=0)" frameborder="0', value)
    if not matched: _review()
    fields['videoSrc'] = matched[1]
    return {'kind': 'youtube_attribute_tail', 'same_video_id': True,
            'query_preserved': True, 'native_player_setting_preserved': True}


def _vk(node, group, validate_static):
    if not _leaf(node, 'video', VIDEO_FIELDS): _review()
    fields = node['fields']
    if (fields.get('videoProvider') != 'embedded' or fields.get('videoProvider2') not in (None, '', 'rutube')
            or fields.get('nativePlayer') is not False or fields.get('nativePlayer2') not in (None, False)
            or fields.get('html') not in (None, '') or fields.get('isFloating') is not None
            or any(fields.get(k) not in (None, '') for k in ('videoSrc', 'videoSrc2', 'posterSrc', 'posterSrc2'))
            or any(fields.get(k) is not None and fields.get(k) is not True for k in
                   ('isShowFastRewindButtons', 'isShowFastRewindButtons2', 'isShowProgressControl', 'isShowProgressControl2'))): _review()
    markup = fields.get('embeddedHtml')
    # Shared backend validator owns the strict VK host/query/iframe policy.
    if not isinstance(markup, str) or not re.fullmatch(r'<iframe\b[^<>]*></iframe>', markup): _review()
    try: validate_static(markup)
    except (ValueError, UnicodeError, RecursionError): _review()
    node.update(name='text', fields={'html': markup})
    receipt = {'kind': 'vk', 'embedded_html_unchanged': True,
               'association': 'explicit_alternative_group' if group is not None else 'independent'}
    if group is not None: receipt['group_path'] = list(group)
    return receipt


def normalize_reviewed_legacy_players(ape, course_id, lesson_id, validate_static):
    """Return copied APE and metadata-only witnesses for exact reviewed leaves.

    Run before generic iframe extraction and editor-node repairs. The caller
    must retain the original APE and include these witnesses in replay metadata.
    Explicit VK grouping is preserved in the original section; an unlabelled
    VK after an audio caption remains independent. No source is fetched here.
    """
    if (ACCOUNT, ORIGIN) != ('mastervision', 'https://shop.mastervision.su'):
        _review('reviewed_legacy_player_account_mismatch')
    if (not isinstance(ape, dict) or ape.get('name') != 'page'
            or not isinstance(ape.get('children'), list) or not callable(validate_static)):
        _review('reviewed_legacy_player_source_invalid')
    context = (_number(course_id), _number(lesson_id))
    result, changes = copy.deepcopy(ape), []
    for path, digest, kind, extra in BINDINGS.get(context, ()):
        node = _node(result, path)
        if node is None or _sha(node) != digest: continue
        if kind == 'mixed_youtube': details = _mixed(node, extra, validate_static, context, path, digest)
        elif kind == 'youtube_attribute_tail': details = _repair_tail(node)
        elif kind == 'vk': details = _vk(node, extra, validate_static)
        else: _review('reviewed_legacy_player_source_invalid')
        changes.append({'path': list(path), 'code': CODE, 'source_node_sha256': digest, **details})
    return result, changes
