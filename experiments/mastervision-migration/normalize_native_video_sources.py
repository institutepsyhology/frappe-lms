"""Canonicalize exact source forms while preserving the AVO player's video ID.

Read-only renderer proof: module.awo-ape.3952ddc5.js SHA256
9cb867372194527bed4ec03dff82c969c137a2962dc94a3fe6a12a47374ac55e.
Its non-native YouTube tech accepts bare IDs and extracts watch/short-link IDs;
the Rutube tech extracts its route ID and forwards the original query. No
vendor implementation, private URL or source text is copied into this module.
The caller must retain original APE alongside its normalization witness.
"""
import copy
import re
from urllib.parse import urlsplit

from importer import Review
from normalize_editor_nodes import _core, _style_content

CODE = 'native_video_url_normalized'
FIELDS = {'anchor', 'videoProvider', 'videoSrc', 'nativePlayer', 'posterSrc',
          'isShowProgressControl', 'isShowFastRewindButtons', 'videoProvider2',
          'videoSrc2', 'nativePlayer2', 'posterSrc2', 'isShowProgressControl2',
          'isShowFastRewindButtons2', 'embeddedHtml', 'html', 'isFloating'}
FLAGS = {'nativePlayer', 'nativePlayer2', 'isShowProgressControl',
         'isShowProgressControl2', 'isShowFastRewindButtons',
         'isShowFastRewindButtons2', 'isFloating'}
ID = r'[A-Za-z0-9_-]{11}'


def _youtube_id(value):
    if re.fullmatch(ID, value): return value
    found = re.search(r'(?:youtu\.be/|watch\?v=)(' + ID + r')(?=[#&?]|$)', value)
    return found.group(1) if found else None


def _rutube_id(value):
    found = re.match(r'^.*rutube\.ru/video/private/([^/]*).*', value)
    return found.group(1) if found else None


def _candidate(value, provider):
    if (not isinstance(value, str) or not value or len(value) > 4096
            or provider not in ('youtube', 'rutube') or _core()._player_url(value, provider)):
        return None
    canonical = kind = None
    if provider == 'youtube':
        if re.fullmatch(ID, value):
            canonical, kind = 'https://youtu.be/' + value, 'youtube_bare_id'
        elif re.fullmatch(r'watch\?v=' + ID + r'(?:&feature=[A-Za-z0-9_.-]{1,80})?', value):
            canonical, kind = 'https://www.youtube.com/' + value, 'youtube_relative_watch'
        elif re.fullmatch(r'hhttps://youtu\.be/' + ID, value):
            canonical, kind = value[1:], 'youtube_same_id_scheme'
        if canonical is not None and _youtube_id(value) != _youtube_id(canonical): return None
    else:
        # Restrict the title-prefix repair to the exact private route/query
        # shape observed in the source. Never select among multiple URLs.
        found = re.search(r'https://rutube\.ru/video/private/[0-9a-f]{32}/\?p=[A-Za-z0-9_-]+$', value)
        if found and len(re.findall('https?://', value)) == 1 and found.start() > 0:
            prefix = value[:found.start()]
            if (prefix.strip() and prefix.rstrip(' \t') != prefix
                    and re.fullmatch(r'[\w \t«»“”„".,():;+–—-]{1,512}', prefix)):
                canonical, kind = found.group(0), 'rutube_same_id_title_prefix'
                if (_rutube_id(value) != _rutube_id(canonical)
                        or not re.fullmatch('[0-9a-f]{32}', _rutube_id(value) or '')
                        or value.count('?') != 1 or value.split('?', 1)[1] != urlsplit(canonical).query):
                    return None
    if canonical is None or not _core()._player_url(canonical, provider): return None
    return canonical, kind


def _safe_node(node):
    fields = node.get('fields', {})
    return (not node.get('children') and not set(node) - {'id', 'name', 'fields', 'children', 'style'}
            and not set(fields) - FIELDS
            and all(fields.get(key) in (None, '') for key in ('anchor', 'embeddedHtml', 'posterSrc', 'posterSrc2'))
            and fields.get('html') in (None, '', 'Видео')
            and all(fields.get(key) is None or type(fields.get(key)) is bool for key in FLAGS)
            and not _style_content(node.get('style')))


def normalize_native_video_sources(ape, validate_static):
    """Return copied APE and metadata-only same-ID repairs, never pairing nodes.

    Only an explicitly non-native source slot is repaired. Its other nonempty
    slot must already be a valid URL of the other provider; no uncertain pair,
    embedded player, image, control behavior or source field is discarded.
    """
    if not callable(validate_static): raise Review('native_video_sources_validator_invalid')
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('native_video_sources_invalid')
    copied, changes, visited = copy.deepcopy(ape), [], 0

    def walk(node, path):
        nonlocal visited
        visited += 1
        if visited > 150000 or len(path) > 100 or not isinstance(node, dict) or not isinstance(node.get('name'), str):
            raise Review('native_video_sources_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('native_video_sources_invalid')
        if node['name'] == 'video' and _safe_node(node):
            for suffix, other in (('', '2'), ('2', '')):
                provider = fields.get('videoProvider' + suffix)
                candidate = _candidate(fields.get('videoSrc' + suffix), provider)
                if candidate is None or fields.get('nativePlayer' + suffix) is not False: continue
                other_source, other_provider = fields.get('videoSrc' + other), fields.get('videoProvider' + other)
                if other_source not in (None, ''):
                    if (other_provider not in ('youtube', 'rutube') or other_provider == provider
                            or fields.get('nativePlayer' + other) is not False
                            or not _core()._player_url(other_source, other_provider)):
                        continue
                elif other_provider not in (None, '', 'youtube', 'rutube'):
                    continue
                fields['videoSrc' + suffix] = candidate[0]
                changes.append({'path': list(path), 'code': CODE, 'slot': 2 if suffix else 1, 'kind': candidate[1]})
        for index, child in enumerate(children): walk(child, path + [index])

    walk(copied, [])
    return copied, changes
