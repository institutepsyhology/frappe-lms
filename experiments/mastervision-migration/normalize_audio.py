"""Replace recognized native audio with links to verified private MV files.

The caller verifies uploaded bytes and retains the exact original APE, including
player controls. This pure helper neither downloads nor uploads any asset.
"""
import copy
import hashlib
import re
from urllib.parse import urlsplit

from importer import ACCOUNT, ORIGIN, SITE, Review
from avatar_placeholders import _decoded_safe_path
from normalize_editor_nodes import _style_content

CODE = 'native_audio_private_link_normalized'
FLAGS = {'showDownloadButton', 'showLoopButton', 'showStopButton', 'showVolumeButton', 'showVolumeSlider'}
FIELDS = FLAGS | {'anchor', 'audioSrc', 'visibleConditions'}
NODE_KEYS = {'id', 'name', 'fields', 'children', 'style'}
HOSTS = {'f1.autoweboffice.ru', 'f1.autoweboffice.com'}
TARGET = re.compile(r'/private/files/avo-mastervision-audio-([0-9a-f]{64})\.mp3')


def _binding():
    if (ACCOUNT, ORIGIN, SITE) != ('mastervision', 'https://shop.mastervision.su', 'my-lk.mastervision.su'):
        raise Review('audio_account_mismatch')


def _empty(value):
    return value is None or value is False or value == '' or value == [] or value == {}


def _hidden_style(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str): return True
            current = path + (key,)
            # Observed on every native player: the full-opacity editor control,
            # preserved exactly in the copied style, cannot hide its content.
            if (current == ('lists', 'player', 'opacity') and isinstance(child, dict)
                    and set(child) == {'value'} and isinstance(child['value'], dict)
                    and set(child['value']) == {'number'}
                    and type(child['value']['number']) is int and child['value']['number'] == 1): continue
            if (key.lower() in {'display', 'visibility', 'opacity', 'hidden', 'visibleconditions'}
                    and child is not None and child != '' and child != [] and child != {}): return True
            if _hidden_style(child, current): return True
    if isinstance(value, list): return any(_hidden_style(item, path + (index,)) for index, item in enumerate(value))
    return False


def _recognized(node):
    fields = node.get('fields', {})
    if (set(node) - NODE_KEYS or set(fields) - FIELDS or node.get('children')
            or fields.get('anchor') not in (None, '')
            or not _empty(fields.get('visibleConditions'))): return False
    if any(not (type(value) is bool or type(value) is int and value in (0, 1))
           for key, value in fields.items() if key in FLAGS): return False
    style = node.get('style', {})
    return isinstance(style, dict) and not _style_content(style) and not _hidden_style(style)


def _source_hash(value):
    if not isinstance(value, str) or not value or len(value) > 8192 or re.search(r'[\x00-\x20\x7f\\?#]', value):
        raise Review('audio_source_url_invalid')
    try:
        parsed = urlsplit(value)
        path = _decoded_safe_path(parsed.path)
        if (parsed.scheme != 'https' or parsed.netloc not in HOSTS or parsed.port is not None
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not path or not path.lower().endswith('.mp3')):
            raise ValueError()
    except ValueError: raise Review('audio_source_url_invalid') from None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _receipt(assets, key):
    if assets is None or isinstance(assets, dict) and key not in assets:
        raise Review('audio_asset_not_prepared')
    if not isinstance(assets, dict): raise Review('audio_asset_mapping_invalid')
    receipt = assets[key]
    if not isinstance(receipt, dict) or set(receipt) != {'file_url', 'sha256', 'md5', 'size'}:
        raise Review('audio_asset_mapping_invalid')
    path, sha, md5, size = (receipt[name] for name in ('file_url', 'sha256', 'md5', 'size'))
    match = TARGET.fullmatch(path) if isinstance(path, str) else None
    if (not match or not isinstance(sha, str) or match.group(1) != sha
            or not isinstance(md5, str) or not re.fullmatch('[0-9a-f]{32}', md5)
            or type(size) is not int or not 0 < size <= 2**53 - 1):
        raise Review('audio_asset_mapping_invalid')
    return path


def normalize_audio(ape, assets):
    """Return copied APE plus {path, code, url_sha256} changes in source order.

    Unknown controls, content styles, anchors and conditional subtrees stay
    unchanged for review. Mapping keys hash the exact, unmodified source URL.
    """
    _binding()
    if not isinstance(ape, dict) or ape.get('name') != 'page' or not isinstance(ape.get('children'), list):
        raise Review('audio_nodes_invalid')
    try: copied = copy.deepcopy(ape)
    except (TypeError, RecursionError): raise Review('audio_nodes_invalid') from None
    changes = []; visited = 0
    def walk(node, path):
        nonlocal visited
        visited += 1
        if (visited > 150000 or len(path) > 100 or not isinstance(node, dict)
                or not isinstance(node.get('name'), str)):
            raise Review('audio_nodes_invalid')
        fields, children = node.get('fields', {}), node.get('children', [])
        if not isinstance(fields, dict) or not isinstance(children, list): raise Review('audio_nodes_invalid')
        if not _empty(fields.get('visibleConditions')): return
        if node['name'] == 'audio':
            if not _recognized(node): return
            key = _source_hash(fields.get('audioSrc')); path_url = _receipt(assets, key)
            node['name'] = 'button'
            node['fields'] = {'anchor': '', 'html': 'Аудиозапись', 'linkType': 'url',
                              'url': 'https://' + SITE + path_url, 'blank': True}
            changes.append({'path': list(path), 'code': CODE, 'url_sha256': key})
            return
        for index, child in enumerate(children): walk(child, path + [index])
    walk(copied, [])
    return copied, changes
